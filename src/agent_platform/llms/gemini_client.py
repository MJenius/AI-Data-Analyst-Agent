from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Callable
from urllib import request, error
from pydantic import BaseModel


logger = logging.getLogger(__name__)


class GeminiClientError(RuntimeError):
    """Raised when Gemini returns an invalid response or cannot be reached."""


def _truncate(value: str, limit: int = 1200) -> str:
    return value if len(value) <= limit else f"{value[:limit]}...[truncated]"


@dataclass(slots=True)
class GeminiClient:
    """Gemini Developer API Chat Completions wrapper with structured JSON support."""

    api_key: str | None = None
    model: str | None = None
    timeout_seconds: float = 20.0
    transport: Callable[[request.Request], Any] | None = None

    def __post_init__(self) -> None:
        self.api_key = self.api_key or os.getenv("GEMINI_API_KEY")
        self.model = self.model or os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
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
                "responseMimeType": "application/json"
            }
        }
        
        logger.info(
            "gemini_request",
            extra={
                "model": self.model,
                "system_prompt": _truncate(system_prompt),
                "user_prompt": _truncate(user_prompt),
            },
        )
        
        req = request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        
        try:
            with self.transport(req, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            error_body = exc.read().decode('utf-8')
            raise GeminiClientError(f"Gemini API returned HTTP {exc.code}: {error_body}") from exc
        except Exception as exc:
            raise GeminiClientError(f"Failed to connect to Gemini API: {exc}") from exc

        logger.info("gemini_response", extra={"model": self.model, "response": _truncate(raw)})
        
        try:
            body = json.loads(raw)
            candidates = body.get("candidates")
            if not candidates:
                raise GeminiClientError("Gemini response is empty or contains no candidates.")
            
            first_candidate = candidates[0]
            finish_reason = first_candidate.get("finishReason")
            if finish_reason and finish_reason != "STOP":
                raise GeminiClientError(f"Gemini candidate failed to finish normally. Reason: {finish_reason}")
                
            content = first_candidate.get("content")
            if not content:
                raise GeminiClientError(f"Gemini candidate content is missing. Finish reason: {finish_reason}")
                
            parts = content.get("parts")
            if not parts:
                raise GeminiClientError("Gemini candidate content contains no parts.")
                
            text_response = parts[0].get("text", "").strip()
            result_dict = json.loads(text_response)
            
            if response_model is not None:
                # Perform Pydantic validation
                from pydantic import ValidationError
                try:
                    validated_obj = response_model.model_validate(result_dict)
                    return validated_obj.model_dump()
                except ValidationError as val_err:
                    logger.error(f"JSON validation failed for {response_model.__name__} in Gemini response: {val_err}")
                    raise
                    
            return result_dict
        except GeminiClientError:
            raise
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise GeminiClientError(f"Gemini response did not contain valid JSON content. Raw response: {raw}") from exc
