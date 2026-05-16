from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class StepStatus(str, Enum):
    """Lifecycle status for a task execution run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(slots=True)
class ExecutionError:
    """Structured error captured during a specific orchestration step."""

    step: str
    message: str
    error_type: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StepTrace:
    """Timing and output metadata for one executed step."""

    step: str
    status: StepStatus
    started_at: datetime
    finished_at: datetime | None = None
    elapsed_seconds: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExecutionState:
    """Mutable state passed through planner, executor, RAG, tools, and evaluator."""

    task: str
    run_id: str = field(default_factory=lambda: str(uuid4()))
    plan: list[str] = field(default_factory=list)
    current_step_index: int = 0
    intermediate_outputs: dict[str, Any] = field(default_factory=dict)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    errors: list[ExecutionError] = field(default_factory=list)
    retrieved_context: dict[str, list[Any]] = field(default_factory=dict)
    evaluation: dict[str, Any] | None = None
    traces: list[StepTrace] = field(default_factory=list)
    status: StepStatus = StepStatus.PENDING
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None

    @property
    def current_step(self) -> str | None:
        if self.current_step_index >= len(self.plan):
            return None
        return self.plan[self.current_step_index]

    def set_plan(self, plan: list[str]) -> None:
        self.plan = plan
        self.current_step_index = 0

    def mark_running(self) -> None:
        self.status = StepStatus.RUNNING

    def record_context(self, step: str, context: list[Any]) -> None:
        self.retrieved_context[step] = context

    def record_step_result(self, step: str, result: dict[str, Any]) -> None:
        self.intermediate_outputs[step] = result.get("output")
        self.tool_results.extend(result.get("tool_results", []))
        self.current_step_index += 1

    def record_error(self, step: str, error: Exception) -> None:
        self.errors.append(
            ExecutionError(
                step=step,
                message=str(error),
                error_type=error.__class__.__name__,
            )
        )
        self.status = StepStatus.FAILED
        self.finished_at = datetime.now(timezone.utc)

    def record_evaluation(self, evaluation: dict[str, Any]) -> None:
        self.evaluation = evaluation

    def mark_completed(self) -> None:
        self.status = StepStatus.COMPLETED
        self.finished_at = datetime.now(timezone.utc)
