from __future__ import annotations

import os
import logging
from typing import Any, Protocol
from pydantic import BaseModel
from agent_platform.llms.groq_client import GroqClient
from agent_platform.llms.ollama_client import OllamaClient
from agent_platform.llms.gemini_client import GeminiClient


logger = logging.getLogger(__name__)

class LLMClient(Protocol):
    """Unified interface for LLM providers."""
    @property
    def enabled(self) -> bool: ...
    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
        response_model: type[BaseModel] | None = None,
    ) -> dict[str, Any]: ...


class FallbackLLMClient:
    """Tries a list of clients in priority order and falls back to subsequent ones on failure."""
    def __init__(self, clients: list[LLMClient]) -> None:
        self.clients = [c for c in clients if c is not None]

    @property
    def enabled(self) -> bool:
        return any(c.enabled for c in self.clients)

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
        response_model: type[BaseModel] | None = None,
    ) -> dict[str, Any]:
        last_error = None
        for client in self.clients:
            if client.enabled:
                try:
                    return client.complete_json(system_prompt, user_prompt, temperature, response_model)
                except Exception as e:
                    logger.warning(f"LLM Client {type(client).__name__} failed: {e}. Trying next fallback...")
                    last_error = e
                    continue
        
        raise RuntimeError(f"All configured LLM clients failed or were disabled. Last error: {last_error}")


def get_llm_client() -> LLMClient:
    """
    Returns the configured LLM client.
    By default, returns a FallbackLLMClient cascade: Groq -> Gemini -> Ollama.
    """
    provider = os.getenv("LLM_PROVIDER", "auto").lower()
    
    if provider == "groq":
        return GroqClient()
    
    if provider == "gemini":
        return GeminiClient()
    
    if provider == "ollama":
        return OllamaClient()
    
    # Auto-mode: Dynamic list-based cascade: Groq -> Gemini -> Ollama
    return FallbackLLMClient(clients=[GroqClient(), GeminiClient(), OllamaClient()])


