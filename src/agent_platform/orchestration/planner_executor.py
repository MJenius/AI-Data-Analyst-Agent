from __future__ import annotations

import inspect
from typing import Protocol

from agent_platform.experiments.query_plan import QueryPlan
from agent_platform.orchestration.state import ExecutionState


class Planner(Protocol):
    """Planner interface for turning a task into a structured QueryPlan."""

    def plan(self, task: str) -> QueryPlan:
        ...


class PlannerExecutor:
    """Adapter around any planner agent that exposes a `plan(task)` method."""

    def __init__(self, planner: Planner) -> None:
        self._planner = planner

    async def execute(self, state: ExecutionState) -> QueryPlan:
        plan = self._planner.plan(state.task)
        if inspect.isawaitable(plan):
            plan = await plan
        if not isinstance(plan, QueryPlan):
            raise ValueError("Planner must return a QueryPlan instance.")
        return plan
