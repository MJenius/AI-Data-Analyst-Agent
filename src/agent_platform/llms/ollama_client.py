from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Callable
from urllib import request, error


logger = logging.getLogger(__name__)


class OllamaClientError(RuntimeError):
    """Raised when Ollama returns an invalid response or cannot be reached."""


def _truncate(value: str, limit: int = 1200) -> str:
    return value if len(value) <= limit else f"{value[:limit]}...[truncated]"


@dataclass(slots=True)
class OllamaClient:
    """Ollama Chat Completions wrapper with structured JSON support."""

    model: str | None = None
    base_url: str = "http://localhost:11434/api/chat"
    timeout_seconds: float = 60.0  # Local models can be slow
    transport: Callable[[request.Request], Any] | None = None

    def __post_init__(self) -> None:
        self.model = self.model or os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b")
        self.transport = self.transport or request.urlopen

    @property
    def enabled(self) -> bool:
        # Check if Ollama is reachable
        try:
            # Short timeout for reachability check
            with request.urlopen("http://localhost:11434/api/tags", timeout=1) as _:
                return True
        except Exception:
            return False

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        logger.info(f"Ollama ({self.model}) starting generation...")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "options": {
                "temperature": temperature,
            },
            "format": "json",
            "stream": False,
        }
        
        logger.info(
            "ollama_request",
            extra={
                "model": self.model,
                "system_prompt": _truncate(system_prompt),
                "user_prompt": _truncate(user_prompt),
            },
        )
        
        req = request.Request(
            self.base_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        
        try:
            with self.transport(req, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except error.URLError as exc:
            raise OllamaClientError(f"Ollama connection failed: {exc.reason}") from exc
        except Exception as exc:
            raise OllamaClientError(str(exc)) from exc

        logger.info("ollama_response", extra={"model": self.model, "response": _truncate(raw)})
        
        try:
            body = json.loads(raw)
            content = body["message"]["content"]
            # Ollama sometimes returns the JSON inside the content string, 
            # and 'format': 'json' ensures it is valid JSON.
            return json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise OllamaClientError("Ollama response did not contain valid JSON content.") from exc
