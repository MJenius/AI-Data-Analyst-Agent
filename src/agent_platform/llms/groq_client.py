from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Callable
from urllib import request


logger = logging.getLogger(__name__)


class GroqClientError(RuntimeError):
    """Raised when Groq returns an invalid response or cannot be reached."""


def _truncate(value: str, limit: int = 1200) -> str:
    return value if len(value) <= limit else f"{value[:limit]}...[truncated]"


@dataclass(slots=True)
class GroqClient:
    """Small Groq Chat Completions wrapper with structured JSON support."""

    api_key: str | None = None
    model: str | None = None
    base_url: str = "https://api.groq.com/openai/v1/chat/completions"
    timeout_seconds: float = 20.0
    transport: Callable[[request.Request], Any] | None = None

    def __post_init__(self) -> None:
        self.api_key = self.api_key or os.getenv("GROQ_API_KEY")
        self.model = self.model or os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        self.transport = self.transport or request.urlopen

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise GroqClientError("GROQ_API_KEY is not configured.")

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
            },
            method="POST",
        )
        try:
            with self.transport(req) as response:
                raw = response.read().decode("utf-8")
        except Exception as exc:
            raise GroqClientError(str(exc)) from exc

        logger.info("groq_response", extra={"model": self.model, "response": _truncate(raw)})
        try:
            body = json.loads(raw)
            content = body["choices"][0]["message"]["content"]
            return json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise GroqClientError("Groq response did not contain valid JSON content.") from exc
