from __future__ import annotations

import json
import logging
import os
import random
import time
from dataclasses import dataclass, field
from queue import Empty, Queue
from threading import Thread
from typing import Any, Callable
from urllib import error, request

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class GeminiClientError(RuntimeError):
    """Base error for Gemini API requests."""


class GeminiProviderError(GeminiClientError):
    """Provider-side issue (5xx, rate limits, transport failures)."""

    is_provider_failure = True
    error_category = "provider_error"


class GeminiRateLimitError(GeminiProviderError):
    """Gemini returned 429 after retries."""

    error_category = "rate_limited"


class GeminiTimeoutError(GeminiProviderError):
    """Gemini request timed out."""

    error_category = "timeout"


class GeminiModelError(GeminiClientError):
    """Model or prompt formatting error (4xx)."""

    is_provider_failure = False
    error_category = "model_error"


def _truncate(value: str, limit: int = 1200) -> str:
    return value if len(value) <= limit else f"{value[:limit]}...[truncated]"


@dataclass(slots=True)
class GeminiClient:
    """Production-grade Gemini Developer API client with structured JSON output and retries."""

    api_key: str | None = None
    model: str | None = None
    timeout_seconds: float = 30.0
    max_retries: int = 5
    backoff_seconds: float = 2.0
    transport: Callable[[request.Request], Any] | None = None
    sleep: Callable[[float], None] = time.sleep
    last_response_metadata: dict[str, Any] = field(default_factory=dict, init=False)
    usage_totals: dict[str, int] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.api_key = self.api_key or os.getenv("GEMINI_API_KEY")
        self.model = self.model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
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
            raise GeminiClientError("GEMINI_API_KEY is not configured.")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": user_prompt}
                    ]
                }
            ],
            "systemInstruction": {
                "parts": [
                    {"text": system_prompt}
                ]
            },
            "generationConfig": {
                "temperature": temperature,
                "responseMimeType": "application/json",
            },
        }

        encoded_data = json.dumps(payload).encode("utf-8")

        for attempt in range(self.max_retries + 1):
            started = time.perf_counter()
            req = request.Request(
                url,
                data=encoded_data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            try:
                completed: Queue[tuple[bool, Any]] = Queue(maxsize=1)

                def send() -> None:
                    try:
                        with self.transport(req, timeout=self.timeout_seconds) as response:
                            completed.put((True, response.read().decode("utf-8")))
                    except BaseException as exc:
                        completed.put((False, exc))

                Thread(target=send, daemon=True).start()
                try:
                    ok, raw_or_exc = completed.get(timeout=self.timeout_seconds)
                except Empty as exc:
                    raise GeminiTimeoutError(
                        f"Gemini request exceeded {self.timeout_seconds:g} seconds."
                    ) from exc

                if not ok:
                    raise raw_or_exc

                raw = raw_or_exc
                body = json.loads(raw)
                candidates = body.get("candidates")
                if not candidates:
                    raise GeminiModelError("Gemini response contains no candidates.")

                first_candidate = candidates[0]
                content = first_candidate.get("content")
                if not content:
                    raise GeminiModelError("Gemini candidate content is missing.")

                parts = content.get("parts")
                if not parts:
                    raise GeminiModelError("Gemini candidate parts are empty.")

                text_response = parts[0].get("text", "").strip()
                result_dict = json.loads(text_response)

                usage_meta = body.get("usageMetadata", {})
                p_tokens = usage_meta.get("promptTokenCount", 0)
                c_tokens = usage_meta.get("candidatesTokenCount", 0)
                t_tokens = usage_meta.get("totalTokenCount", 0)

                for k, v in [("prompt_tokens", p_tokens), ("completion_tokens", c_tokens), ("total_tokens", t_tokens)]:
                    self.usage_totals[k] = self.usage_totals.get(k, 0) + v

                self.last_response_metadata = {
                    "provider": "gemini",
                    "model": self.model,
                    "latency_seconds": round(time.perf_counter() - started, 4),
                    "usage": {
                        "prompt_tokens": p_tokens,
                        "completion_tokens": c_tokens,
                        "total_tokens": t_tokens,
                    },
                }

                if response_model is not None:
                    return response_model.model_validate(result_dict).model_dump()

                return result_dict

            except error.HTTPError as exc:
                exc.close()
                if exc.code == 429:
                    if attempt >= self.max_retries:
                        raise GeminiRateLimitError("Gemini rate limit persisted after bounded retries.") from exc
                    jitter = random.uniform(0.5, 1.5)
                    sleep_time = min(self.backoff_seconds * (2**attempt) + jitter, 32.0)
                    logger.warning("gemini_rate_limited attempt=%d/%d sleeping=%.1fs", attempt + 1, self.max_retries, sleep_time)
                    self.sleep(sleep_time)
                    continue

                if 500 <= exc.code < 600:
                    if attempt >= self.max_retries:
                        raise GeminiProviderError(f"Gemini server error HTTP {exc.code} persisted after retries.") from exc
                    jitter = random.uniform(0.5, 1.5)
                    sleep_time = min(self.backoff_seconds * (2**attempt) + jitter, 32.0)
                    logger.warning("gemini_server_error http=%d attempt=%d/%d sleeping=%.1fs", exc.code, attempt + 1, self.max_retries, sleep_time)
                    self.sleep(sleep_time)
                    continue

                raise GeminiModelError(f"Gemini returned HTTP {exc.code}.") from exc

            except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
                raise GeminiModelError(f"Gemini response was not valid JSON: {exc}") from exc
            except GeminiClientError:
                raise
