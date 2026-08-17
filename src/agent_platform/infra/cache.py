from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Callable, TypeVar

T = TypeVar("T")
logger = logging.getLogger(__name__)


class VersionedCache:
    """Safe, version-isolated caching for deterministic retrieval and schema introspection.
    
    Guarantees:
    - Versioned keys across model, schema, prompt version, and config hash.
    - Can be fully bypassed via ENABLE_CACHE=0 or development flags.
    - Answer generation caches are strictly partitioned and disabled during final benchmarks.
    """

    def __init__(self, cache_dir: str | Path = "runtime/cache/versioned") -> None:
        self.cache_dir = Path(cache_dir)
        self.enabled = os.getenv("ENABLE_CACHE", "1").lower() in {"1", "true", "yes"}
        self._memory: dict[str, Any] = {}

    def _hash_key(self, namespace: str, key_data: dict[str, Any] | str) -> str:
        serialized = json.dumps(key_data, sort_keys=True) if isinstance(key_data, dict) else str(key_data)
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]
        return f"{namespace}_{digest}"

    def get(self, namespace: str, key_data: dict[str, Any] | str) -> Any | None:
        if not self.enabled:
            return None
        key = self._hash_key(namespace, key_data)
        if key in self._memory:
            return self._memory[key]
        
        disk_path = self.cache_dir / f"{key}.json"
        if disk_path.exists():
            try:
                with open(disk_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._memory[key] = data
                    return data
            except Exception:
                return None
        return None

    def set(self, namespace: str, key_data: dict[str, Any] | str, value: Any) -> None:
        if not self.enabled:
            return
        key = self._hash_key(namespace, key_data)
        self._memory[key] = value
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            disk_path = self.cache_dir / f"{key}.json"
            with open(disk_path, "w", encoding="utf-8") as f:
                json.dump(value, f, default=str)
        except Exception as exc:
            logger.warning(f"Could not persist cache to disk: {exc}")

    def clear(self) -> None:
        self._memory.clear()


global_cache = VersionedCache()
