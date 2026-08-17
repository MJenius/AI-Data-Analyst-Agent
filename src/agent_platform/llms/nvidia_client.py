from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from queue import Empty, Queue
from threading import Thread
from typing import Any, Callable, ClassVar
from urllib import error, request

from pydantic import BaseModel


class NvidiaClientError(RuntimeError):
    """Base error for NVIDIA NIM requests."""


class NvidiaProviderError(NvidiaClientError):
    """A provider-side outage (5xx or transport error), not a model result."""

    is_provider_failure = True
    error_category = "provider_error"


class NvidiaRateLimitError(NvidiaProviderError):
    """NVIDIA NIM continued to rate-limit after bounded retries."""

    error_category = "rate_limited"


class NvidiaTimeoutError(NvidiaProviderError):
    """NVIDIA NIM did not complete a request before the hard deadline."""

    error_category = "timeout"


class NvidiaModelError(NvidiaClientError):
    """A model/request compatibility failure (for example HTTP 400/404)."""

    is_provider_failure = False
    error_category = "model_error"


@dataclass(slots=True)
class NvidiaClient:
    """OpenAI-compatible NVIDIA NIM client with structured JSON responses."""

    api_key: str | None = None
    model: str | None = None
    base_url: str = "https://integrate.api.nvidia.com/v1/chat/completions"
    timeout_seconds: float = 20.0
    max_tokens: int = 4096
    max_retries: int = 3
    backoff_seconds: float = 1.0
    transport: Callable[..., Any] | None = None
    sleep: Callable[[float], None] = time.sleep
    last_response_metadata: dict[str, Any] = field(default_factory=dict, init=False)
    usage_totals: dict[str, int] = field(default_factory=dict, init=False)

    MODEL_KEY_ENV: ClassVar[dict[str, str]] = {
        "meta/llama-3.3-70b-instruct": "NVIDIA_LLAMA_33_70B_API_KEY",
        "nvidia/llama-3.3-nemotron-super-49b-v1.5": "NVIDIA_NEMOTRON_49B_API_KEY",
        "nvidia/nemotron-3-super-120b-a12b": "NVIDIA_NEMOTRON_120B_API_KEY",
    }

    def __post_init__(self) -> None:
        self.model = self.model or os.getenv("NVIDIA_MODEL", "nvidia/llama-3.3-nemotron-super-49b-v1.5")
        model_key_env = self.MODEL_KEY_ENV.get(self.model)
        self.api_key = self.api_key or (os.getenv(model_key_env) if model_key_env else None) or os.getenv("NVIDIA_API_KEY")
        self.base_url = os.getenv("NVIDIA_BASE_URL", self.base_url)
        self.transport = self.transport or request.urlopen

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
        response_model: type[BaseModel] | None = None,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise NvidiaClientError("NVIDIA_API_KEY is not configured.")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero.")

        self.last_response_metadata = {}

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
        }
        encoded = json.dumps(payload).encode("utf-8")
        for attempt in range(self.max_retries + 1):
            started = time.perf_counter()
            req = request.Request(
                self.base_url,
                data=encoded,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                method="POST",
            )
            try:
                completed: Queue[tuple[bool, Any]] = Queue(maxsize=1)

                def send() -> None:
                    try:
                        with self.transport(req, timeout=self.timeout_seconds) as response:
                            completed.put((True, json.loads(response.read().decode("utf-8"))))
                    except BaseException as exc:
                        completed.put((False, exc))

                Thread(target=send, daemon=True).start()
                try:
                    ok, value = completed.get(timeout=self.timeout_seconds)
                except Empty as exc:
                    raise NvidiaTimeoutError(
                        f"NVIDIA NIM request exceeded {self.timeout_seconds:g} seconds."
                    ) from exc
                if not ok:
                    raise value
                body = value
                content = body["choices"][0]["message"]["content"]
                if not isinstance(content, str):
                    raise NvidiaModelError("NVIDIA response content was not text.")
                result = json.loads(content.strip().removeprefix("```json").removesuffix("```").strip())
                usage = body.get("usage") or {}
                for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    if usage.get(key) is not None:
                        self.usage_totals[key] = self.usage_totals.get(key, 0) + int(usage[key])
                self.last_response_metadata = {
                    "provider": "nvidia_nim",
                    "model": self.model,
                    "latency_seconds": round(time.perf_counter() - started, 4),
                    "usage": {
                        key: usage.get(key)
                        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                        if usage.get(key) is not None
                    },
                }
                if response_model is not None:
                    return response_model.model_validate(result).model_dump()
                return result
            except error.HTTPError as exc:
                exc.close()
                if exc.code == 429:
                    if attempt >= self.max_retries:
                        raise NvidiaRateLimitError("NVIDIA NIM rate limit persisted after bounded retries.") from exc
                    self.sleep(min(self.backoff_seconds * (2**attempt), 16.0))
                    continue
                if 500 <= exc.code < 600:
                    raise NvidiaProviderError(f"NVIDIA NIM returned HTTP {exc.code}.") from exc
                raise NvidiaModelError(f"NVIDIA NIM returned HTTP {exc.code}.") from exc
            except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
                raise NvidiaModelError("NVIDIA NIM response did not contain valid JSON content.") from exc
            except NvidiaClientError:
                raise
            except Exception as exc:
                raise NvidiaProviderError(f"Unable to reach NVIDIA NIM: {str(exc)[:300]}") from exc
