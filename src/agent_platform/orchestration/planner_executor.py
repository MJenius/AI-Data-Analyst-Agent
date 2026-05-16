from __future__ import annotations

import inspect
from typing import Protocol

from agent_platform.orchestration.state import ExecutionState


class Planner(Protocol):
    """Planner interface for turning a task into ordered executable steps."""

    def plan(self, task: str) -> list[str]:
        ...


class PlannerExecutor:
    """Adapter around any planner agent that exposes a `plan(task)` method."""

    def __init__(self, planner: Planner) -> None:
        self._planner = planner

    async def execute(self, state: ExecutionState) -> list[str]:
        plan = self._planner.plan(state.task)
        if inspect.isawaitable(plan):
            plan = await plan
        if not isinstance(plan, list) or not all(isinstance(step, str) for step in plan):
            raise ValueError("Planner must return a list of step strings.")
        return plan
