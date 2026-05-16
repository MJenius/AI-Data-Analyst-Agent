import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_platform.orchestration.loop import ExecutionLoop
from agent_platform.orchestration.state import ExecutionState, StepStatus


class FakePlanner:
    async def plan(self, task):
        return ["retrieve logs", "summarize failure"]


class FakeRag:
    async def retrieve(self, step, state):
        return [f"context for {step}"]


class FakeStepExecutor:
    async def execute(self, step, context, state):
        return {
            "step": step,
            "output": f"completed {step}",
            "tool_results": [{"tool": "fake", "result": step}],
        }


class FakeEvaluator:
    async def evaluate(self, state):
        return {"valid": True, "score": 0.91, "reason": "looks grounded"}


class RecordingObserver:
    def __init__(self):
        self.events = []

    def on_run_start(self, state):
        self.events.append(("run_start", state.task))

    def on_step_start(self, state, step):
        self.events.append(("step_start", step))

    def on_step_end(self, state, step, result, elapsed_seconds):
        self.events.append(("step_end", step, result["output"]))

    def on_run_error(self, state, step, error):
        self.events.append(("run_error", step, str(error)))

    def on_run_end(self, state, elapsed_seconds):
        self.events.append(("run_end", state.status.value))


class ExecutionLoopTests(unittest.TestCase):
    def test_runs_plan_steps_and_evaluates_final_state(self):
        observer = RecordingObserver()
        loop = ExecutionLoop(
            planner=FakePlanner(),
            step_executor=FakeStepExecutor(),
            evaluator=FakeEvaluator(),
            rag_retriever=FakeRag(),
            observer=observer,
        )

        state = asyncio.run(loop.run("Analyze why API latency increased"))

        self.assertIsInstance(state, ExecutionState)
        self.assertEqual(state.plan, ["retrieve logs", "summarize failure"])
        self.assertEqual(state.current_step_index, 2)
        self.assertEqual(state.status, StepStatus.COMPLETED)
        self.assertEqual(
            state.intermediate_outputs,
            {
                "retrieve logs": "completed retrieve logs",
                "summarize failure": "completed summarize failure",
            },
        )
        self.assertEqual(len(state.tool_results), 2)
        self.assertEqual(state.evaluation["score"], 0.91)
        self.assertEqual(
            [event[0] for event in observer.events],
            [
                "run_start",
                "step_start",
                "step_end",
                "step_start",
                "step_end",
                "run_end",
            ],
        )

    def test_records_errors_and_marks_failed_when_step_raises(self):
        class FailingStepExecutor:
            async def execute(self, step, context, state):
                raise RuntimeError("tool failed")

        loop = ExecutionLoop(
            planner=FakePlanner(),
            step_executor=FailingStepExecutor(),
            evaluator=FakeEvaluator(),
            rag_retriever=FakeRag(),
            observer=RecordingObserver(),
        )

        state = asyncio.run(loop.run("Debug task"))

        self.assertEqual(state.status, StepStatus.FAILED)
        self.assertEqual(len(state.errors), 1)
        self.assertEqual(state.errors[0].step, "retrieve logs")
        self.assertIn("tool failed", state.errors[0].message)
        self.assertEqual(state.current_step_index, 0)


if __name__ == "__main__":
    unittest.main()
