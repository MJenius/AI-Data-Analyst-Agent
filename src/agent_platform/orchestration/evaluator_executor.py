from __future__ import annotations

import inspect
from typing import Any, Protocol

from agent_platform.orchestration.state import ExecutionState


class Evaluator(Protocol):
    """Evaluator interface for validating the final run state."""

    def evaluate(self, state: ExecutionState) -> dict[str, Any]:
        ...


class EvaluatorExecutor:
    """Adapter around evaluator agents that score and validate completed runs."""

    def __init__(self, evaluator: Evaluator) -> None:
        self._evaluator = evaluator

    async def execute(self, state: ExecutionState) -> dict[str, Any]:
        evaluation = self._evaluator.evaluate(state)
        if inspect.isawaitable(evaluation):
            evaluation = await evaluation
        if not isinstance(evaluation, dict):
            raise ValueError("Evaluator must return a dictionary.")
        return evaluation
