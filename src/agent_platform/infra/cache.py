from __future__ import annotations

import logging
from typing import Any, Callable, TypeVar

T = TypeVar("T")
logger = logging.getLogger(__name__)


class SimpleCache:
    """Lightweight in-memory cache for embeddings, schema results, and SQL outputs."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    def get(self, key: str) -> Any | None:
        return self._data.get(key)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def clear(self) -> None:
        self._data.clear()

    async def get_or_set(self, key: str, creator: Callable[[], Any]) -> Any:
        if key in self._data:
            logger.debug("cache_hit", extra={"key": key})
            return self._data[key]
        
        logger.debug("cache_miss", extra={"key": key})
        value = creator()
        if hasattr(value, "__await__"):
            value = await value
        
        self._data[key] = value
        return value


# Global singleton for easy access
global_cache = SimpleCache()
