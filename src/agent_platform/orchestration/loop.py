from __future__ import annotations

import inspect
import logging
from time import perf_counter
from typing import Any, Protocol

from agent_platform.orchestration.evaluator_executor import EvaluatorExecutor
from agent_platform.orchestration.planner_executor import PlannerExecutor
from agent_platform.orchestration.state import ExecutionState, StepStatus, StepTrace


logger = logging.getLogger(__name__)


class RagRetriever(Protocol):
    """Retrieves contextual evidence for the current step."""

    def retrieve(self, step: str, state: ExecutionState) -> list[Any]:
        ...


class StepExecutorProtocol(Protocol):
    """Executes one planned step and returns a structured result."""

    def execute(
        self,
        step: str,
        context: list[Any],
        state: ExecutionState,
    ) -> dict[str, Any]:
        ...


class Observer(Protocol):
    """Observability hooks for logs, traces, metrics, and external telemetry."""

    def on_run_start(self, state: ExecutionState) -> None:
        ...

    def on_step_start(self, state: ExecutionState, step: str) -> None:
        ...

    def on_step_end(
        self,
        state: ExecutionState,
        step: str,
        result: dict[str, Any],
        elapsed_seconds: float,
    ) -> None:
        ...

    def on_run_error(self, state: ExecutionState, step: str, error: Exception) -> None:
        ...

    def on_run_end(self, state: ExecutionState, elapsed_seconds: float) -> None:
        ...


class NullObserver:
    """Default observer that writes structured logs without external dependencies."""

    def on_run_start(self, state: ExecutionState) -> None:
        logger.info("agent_run_started", extra={"run_id": state.run_id, "task": state.task})

    def on_step_start(self, state: ExecutionState, step: str) -> None:
        logger.info("agent_step_started", extra={"run_id": state.run_id, "step": step})

    def on_step_end(
        self,
        state: ExecutionState,
        step: str,
        result: dict[str, Any],
        elapsed_seconds: float,
    ) -> None:
        logger.info(
            "agent_step_completed",
            extra={
                "run_id": state.run_id,
                "step": step,
                "elapsed_seconds": elapsed_seconds,
                "has_output": result.get("output") is not None,
            },
        )

    def on_run_error(self, state: ExecutionState, step: str, error: Exception) -> None:
        logger.exception(
            "agent_run_failed",
            extra={"run_id": state.run_id, "step": step, "error_type": error.__class__.__name__},
        )

    def on_run_end(self, state: ExecutionState, elapsed_seconds: float) -> None:
        logger.info(
            "agent_run_finished",
            extra={
                "run_id": state.run_id,
                "status": state.status.value,
                "elapsed_seconds": elapsed_seconds,
            },
        )


class EmptyRagRetriever:
    """No-op retriever for tasks that do not need RAG context."""

    async def retrieve(self, step: str, state: ExecutionState) -> list[Any]:
        return []


class ExecutionLoop:
    """Planner -> RAG -> step execution -> state update -> evaluation."""

    def __init__(
        self,
        planner: Any,
        step_executor: StepExecutorProtocol,
        evaluator: Any,
        rag_retriever: RagRetriever | None = None,
        observer: Observer | None = None,
    ) -> None:
        self._planner = PlannerExecutor(planner)
        self._step_executor = step_executor
        self._evaluator = EvaluatorExecutor(evaluator)
        self._rag_retriever = rag_retriever or EmptyRagRetriever()
        self._observer = observer or NullObserver()

    async def run(self, task: str) -> ExecutionState:
        state = ExecutionState(task=task)
        state.mark_running()
        run_started = perf_counter()
        self._observer.on_run_start(state)

        try:
            query_plan = await self._planner.execute(state)
            state.set_query_plan(query_plan)

            # Each step is isolated so retries/fallback policies can wrap this block later.
            while state.current_step is not None:
                step = state.current_step
                step_trace = StepTrace(
                    step=step,
                    status=StepStatus.RUNNING,
                    started_at=state.started_at,
                )
                state.traces.append(step_trace)
                step_started = perf_counter()
                self._observer.on_step_start(state, step)

                context = await self._retrieve_context(step, state)
                state.record_context(step, context)

                result = await self._execute_step(step, context, state)
                elapsed = perf_counter() - step_started
                step_trace.status = StepStatus.COMPLETED
                step_trace.elapsed_seconds = elapsed
                output = result.get("output", {})
                if not isinstance(output, dict):
                    output = {"analysis": output}
                step_trace.metadata = {
                    "reasoning": output.get("reasoning") or output.get("analysis"),
                    "sql": output.get("sql"),
                    "result_preview": self._preview_result(output),
                    "execution_time_ms": round(elapsed * 1000, 3),
                    "tool_result_count": len(result.get("tool_results", [])),
                }

                state.record_step_result(step, result)
                self._observer.on_step_end(state, step, result, elapsed)

            evaluation = await self._evaluator.execute(state)
            state.record_evaluation(evaluation)
            state.mark_completed()
            return state
        except Exception as error:
            failed_step = state.current_step or "planning/evaluation"
            state.record_error(failed_step, error)
            self._observer.on_run_error(state, failed_step, error)
            return state
        finally:
            self._observer.on_run_end(state, perf_counter() - run_started)

    async def _retrieve_context(self, step: str, state: ExecutionState) -> list[Any]:
        context = self._rag_retriever.retrieve(step, state)
        if inspect.isawaitable(context):
            context = await context
        if context is None:
            return []
        if not isinstance(context, list):
            raise ValueError("RAG retriever must return a list.")
        return context

    async def _execute_step(
        self,
        step: str,
        context: list[Any],
        state: ExecutionState,
    ) -> dict[str, Any]:
        result = self._step_executor.execute(step, context, state)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, dict):
            raise ValueError("Step executor must return a dictionary.")
        return result

    def _preview_result(self, output: dict[str, Any]) -> str:
        sql_result = output.get("sql_result")
        if isinstance(sql_result, dict):
            rows = sql_result.get("rows", [])
            if rows:
                return str(rows[:3])
            return "SQL returned no rows."
        analysis = output.get("analysis")
        return str(analysis)[:500] if analysis is not None else ""
