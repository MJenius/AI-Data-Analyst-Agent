from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Protocol

from agent_platform.orchestration.state import ExecutionState


class Tool(Protocol):
    """Tool interface used by the default step executor."""

    name: str

    def can_handle(self, step: str, state: ExecutionState) -> bool:
        ...

    def run(self, step: str, context: list[Any], state: ExecutionState) -> Any:
        ...


@dataclass(slots=True)
class ToolRegistry:
    """Simple pluggable registry; production code can replace this with DI."""

    tools: list[Tool]

    def resolve(self, step: str, state: ExecutionState) -> Tool | None:
        for tool in self.tools:
            if tool.can_handle(step, state):
                return tool
        return None


class StepExecutor:
    """Executes a single plan step with tools when available, otherwise reasoning."""

    def __init__(self, tool_registry: ToolRegistry | None = None) -> None:
        self._tool_registry = tool_registry or ToolRegistry(tools=[])

    async def execute(
        self,
        step: str,
        context: list[Any],
        state: ExecutionState,
    ) -> dict[str, Any]:
        tool = self._tool_registry.resolve(step, state)
        if tool is None:
            return {
                "step": step,
                "output": self._reason_about_step(step, context, state),
                "tool_results": [],
            }

        result = tool.run(step, context, state)
        if inspect.isawaitable(result):
            result = await result
        return {
            "step": step,
            "output": result,
            "tool_results": [{"tool": tool.name, "result": result}],
        }

    def _reason_about_step(
        self,
        step: str,
        context: list[Any],
        state: ExecutionState,
    ) -> str:
        context_note = f" using {len(context)} context item(s)" if context else ""
        return f"Reasoned through step '{step}'{context_note}."
