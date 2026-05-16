from __future__ import annotations

import json
from pathlib import Path
from time import time
from typing import Any


class JsonlTraceStore:
    """Small persistent trace sink suitable for local dev and tests."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, run_id: str, event: str, payload: dict[str, Any]) -> None:
        record = {"run_id": run_id, "event": event, "timestamp": time(), "payload": payload}
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, default=str) + "\n")


class AnalyticsObserver:
    """Observer adapter used by the orchestration loop."""

    def __init__(self, store: JsonlTraceStore | None = None) -> None:
        self.events: list[dict[str, Any]] = []
        self._store = store

    def on_run_start(self, state) -> None:
        self._record(state.run_id, "run_start", {"task": state.task})

    def on_step_start(self, state, step: str) -> None:
        self._record(state.run_id, "step_start", {"step": step})

    def on_step_end(self, state, step: str, result: dict[str, Any], elapsed_seconds: float) -> None:
        self._record(
            state.run_id,
            "step_end",
            {
                "step": step,
                "elapsed_seconds": elapsed_seconds,
                "tool_count": len(result.get("tool_results", [])),
            },
        )

    def on_run_error(self, state, step: str, error: Exception) -> None:
        self._record(state.run_id, "run_error", {"step": step, "error": str(error)})

    def on_run_end(self, state, elapsed_seconds: float) -> None:
        self._record(
            state.run_id,
            "run_end",
            {"status": state.status.value, "elapsed_seconds": elapsed_seconds},
        )

    def _record(self, run_id: str, event: str, payload: dict[str, Any]) -> None:
        record = {"run_id": run_id, "event": event, "payload": payload}
        self.events.append(record)
        if self._store is not None:
            self._store.append(run_id, event, payload)
