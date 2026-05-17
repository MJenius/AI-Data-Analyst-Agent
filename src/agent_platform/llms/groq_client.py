from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Callable
from urllib import request
from pydantic import BaseModel


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
        self.base_url = os.getenv("LLM_BASE_URL", self.base_url)
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
            raise GroqClientError("GROQ_API_KEY is not configured.")

        models_to_try = []
        if self.model:
            models_to_try.append(self.model)
        for fallback in ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]:
            if fallback not in models_to_try:
                models_to_try.append(fallback)

        last_error = None
        for current_model in models_to_try:
            payload = {
                "model": current_model,
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
                    "model": current_model,
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
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                },
                method="POST",
            )
            try:
                with self.transport(req, timeout=self.timeout_seconds) as response:
                    raw = response.read().decode("utf-8")
                
                logger.info("groq_response", extra={"model": current_model, "response": _truncate(raw)})
                try:
                    body = json.loads(raw)
                    content = body["choices"][0]["message"]["content"]
                    result_dict = json.loads(content)
                    
                    if response_model is not None:
                        # Perform Pydantic validation
                        from pydantic import ValidationError
                        try:
                            validated_obj = response_model.model_validate(result_dict)
                            return validated_obj.model_dump()
                        except ValidationError as val_err:
                            logger.error(f"JSON validation failed for {response_model.__name__}: {val_err}")
                            raise
                            
                    return result_dict
                except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
                    raise GroqClientError("Groq response did not contain valid JSON content.") from exc
            
            except Exception as exc:
                import urllib.error
                if isinstance(exc, urllib.error.HTTPError):
                    error_body = exc.read().decode('utf-8')
                    last_error = Exception(f"HTTP {exc.code}: {error_body}")
                    logger.warning(f"Groq model {current_model} failed: HTTP {exc.code}: {error_body}. Trying next model...")
                else:
                    last_error = exc
                    logger.warning(f"Groq model {current_model} failed: {exc}. Trying next model...")
                continue

        raise GroqClientError(f"All Groq models failed. Last error: {last_error}") from last_error
