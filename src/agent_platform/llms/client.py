from __future__ import annotations

import os
import logging
from typing import Any, Protocol
from agent_platform.llms.groq_client import GroqClient
from agent_platform.llms.ollama_client import OllamaClient


logger = logging.getLogger(__name__)

class LLMClient(Protocol):
    """Unified interface for LLM providers."""
    @property
    def enabled(self) -> bool: ...
    def complete_json(self, system_prompt: str, user_prompt: str, temperature: float = 0.1) -> dict[str, Any]: ...


class FallbackLLMClient:
    """Tries a primary client and falls back to a secondary client on failure."""
    def __init__(self, primary: LLMClient, secondary: LLMClient) -> None:
        self.primary = primary
        self.secondary = secondary

    @property
    def enabled(self) -> bool:
        return self.primary.enabled or self.secondary.enabled

    def complete_json(self, system_prompt: str, user_prompt: str, temperature: float = 0.1) -> dict[str, Any]:
        if self.primary.enabled:
            try:
                return self.primary.complete_json(system_prompt, user_prompt, temperature)
            except Exception as e:
                logger.warning(f"Primary LLM failed, falling back to secondary: {e}")
                if not self.secondary.enabled:
                    raise
        
        if self.secondary.enabled:
            return self.secondary.complete_json(system_prompt, user_prompt, temperature)
        
        raise RuntimeError("No enabled LLM clients available for request.")


def get_llm_client() -> LLMClient:
    """
    Returns the configured LLM client.
    By default, returns a FallbackLLMClient that prioritizes Groq and uses Ollama as a safety net.
    """
    provider = os.getenv("LLM_PROVIDER", "auto").lower()
    
    if provider == "groq":
        return GroqClient()
    
    if provider == "ollama":
        return OllamaClient()
    
    # Auto-mode: Dynamic fallback
    return FallbackLLMClient(primary=GroqClient(), secondary=OllamaClient())
