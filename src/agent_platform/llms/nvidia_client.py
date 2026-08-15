from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib import error, request

from pydantic import BaseModel


class NvidiaClientError(RuntimeError):
    """Base error for NVIDIA NIM requests."""


class NvidiaProviderError(NvidiaClientError):
    """A provider-side outage (5xx or transport error), not a model result."""

    is_provider_failure = True


class NvidiaRateLimitError(NvidiaProviderError):
    """NVIDIA NIM continued to rate-limit after bounded retries."""


class NvidiaModelError(NvidiaClientError):
    """A model/request compatibility failure (for example HTTP 400/404)."""

    is_provider_failure = False


@dataclass(slots=True)
class NvidiaClient:
    """OpenAI-compatible NVIDIA NIM client with structured JSON responses."""

    api_key: str | None = None
    model: str | None = None
    base_url: str = "https://integrate.api.nvidia.com/v1/chat/completions"
    timeout_seconds: float = 60.0
    max_retries: int = 3
    backoff_seconds: float = 1.0
    transport: Callable[..., Any] | None = None
    sleep: Callable[[float], None] = time.sleep
    last_response_metadata: dict[str, Any] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.api_key = self.api_key or os.getenv("NVIDIA_API_KEY")
        self.model = self.model or os.getenv("NVIDIA_MODEL", "meta/llama-3.3-70b-instruct")
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

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
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
                with self.transport(req, timeout=self.timeout_seconds) as response:
                    body = json.loads(response.read().decode("utf-8"))
                content = body["choices"][0]["message"]["content"]
                if not isinstance(content, str):
                    raise NvidiaModelError("NVIDIA response content was not text.")
                result = json.loads(content.strip().removeprefix("```json").removesuffix("```").strip())
                usage = body.get("usage") or {}
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
                detail = exc.read().decode("utf-8", errors="replace")
                if exc.code == 429:
                    if attempt >= self.max_retries:
                        raise NvidiaRateLimitError("NVIDIA NIM rate limit persisted after bounded retries.") from exc
                    self.sleep(min(self.backoff_seconds * (2**attempt), 16.0))
                    continue
                if 500 <= exc.code < 600:
                    raise NvidiaProviderError(f"NVIDIA NIM returned HTTP {exc.code}.") from exc
                raise NvidiaModelError(f"NVIDIA NIM returned HTTP {exc.code}: {detail[:300]}") from exc
            except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
                raise NvidiaModelError("NVIDIA NIM response did not contain valid JSON content.") from exc
            except NvidiaClientError:
                raise
            except Exception as exc:
                raise NvidiaProviderError("Unable to reach NVIDIA NIM.") from exc

