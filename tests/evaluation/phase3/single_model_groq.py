from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib import request, error
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class GroqClientError(RuntimeError):
    pass


def _truncate(value: str, limit: int = 1200) -> str:
    return value if len(value) <= limit else f"{value[:limit]}...[truncated]"


@dataclass(slots=True)
class SingleModelGroqClient:
    """Groq client that uses ONLY the specified model, with 429-aware retry and pacing."""

    api_key: str | None = None
    model: str = "llama-3.1-8b-instant"
    base_url: str = "https://api.groq.com/openai/v1/chat/completions"
    timeout_seconds: float = 30.0
    transport: Callable[[request.Request], Any] | None = None
    max_rpm: int = 30

    _last_request_time: float = 0.0
    _min_interval_seconds: float = 0.0  # no fixed pacing; rely on 429 retry logic
    _max_rpm: int = 30  # free tier limit
    _request_timestamps: list[float] = None

    def __post_init__(self) -> None:
        self.api_key = self.api_key or os.getenv("GROQ_API_KEY")
        self.base_url = os.getenv("LLM_BASE_URL", self.base_url)
        self.transport = self.transport or request.urlopen
        self._request_timestamps = []
        self._max_rpm = max(1, self.max_rpm)

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def _enforce_rpm(self) -> None:
        """Lightweight RPM enforcement: sleep if we've made > max_rpm requests in last 60s."""
        if self._max_rpm <= 0:
            return
        now = time.time()
        if self._request_timestamps is None:
            self._request_timestamps = []
        # Remove timestamps older than 60s
        self._request_timestamps = [ts for ts in self._request_timestamps if now - ts < 60.0]
        if len(self._request_timestamps) >= self._max_rpm:
            # Sleep until the oldest request is > 60s old
            oldest = self._request_timestamps[0]
            wait = 60.0 - (now - oldest) + 0.1
            if wait > 0:
                time.sleep(wait)
            now = time.time()
            self._request_timestamps = [ts for ts in self._request_timestamps if now - ts < 60.0]

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
        response_model: type[BaseModel] | None = None,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise GroqClientError("GROQ_API_KEY is not configured.")

        # Light RPM pacing
        self._enforce_rpm()

        last_error = None
        max_attempts = 4
        for attempt in range(max_attempts):
            self._last_request_time = time.time()
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": temperature,
                "response_format": {"type": "json_object"},
            }
            logger.info(
                "groq_request",
                extra={
                    "model": self.model,
                    "attempt": attempt + 1,
                    "system_prompt": _truncate(system_prompt),
                    "user_prompt": _truncate(user_prompt),
                },
            )
            req = request.Request(
                self.base_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                },
                method="POST",
            )
            try:
                with self.transport(req, timeout=self.timeout_seconds) as response:
                    raw = response.read().decode("utf-8")

                logger.info("groq_response", extra={"model": self.model, "response": _truncate(raw)})
                body = json.loads(raw)
                content = body["choices"][0]["message"]["content"]
                result_dict = json.loads(content)

                if response_model is not None:
                    from pydantic import ValidationError
                    try:
                        validated_obj = response_model.model_validate(result_dict)
                        return validated_obj.model_dump()
                    except ValidationError as val_err:
                        logger.error(f"JSON validation failed for {response_model.__name__}: {val_err}")
                        raise

                self._request_timestamps.append(time.time())
                return result_dict
            except error.HTTPError as exc:
                error_body = exc.read().decode('utf-8')
                if exc.code == 429:
                    # Try to parse retry-after from message
                    retry_after = 2.0
                    m = re.search(r"(\d+)m([\d.]+)s", error_body)
                    if m:
                        retry_after = int(m.group(1)) * 60 + float(m.group(2))
                        retry_after = min(retry_after, 20.0)  # cap at 20s
                    else:
                        m = re.search(r"(\d+\.?\d*)s", error_body)
                        if m:
                            retry_after = float(m.group(1))
                    logger.warning(f"Groq 429, sleeping {retry_after:.1f}s (attempt {attempt+1}/{max_attempts})")
                    time.sleep(retry_after)
                    continue
                last_error = Exception(f"HTTP {exc.code}: {error_body}")
                break  # non-429, don't retry
            except Exception as exc:
                last_error = exc
                if attempt < max_attempts - 1:
                    time.sleep(1.0 + attempt)
                    continue
                break

        raise GroqClientError(f"Groq {self.model} failed after {max_attempts} attempts. Last error: {last_error}") from last_error