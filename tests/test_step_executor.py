import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_platform.orchestration.state import ExecutionState
from agent_platform.orchestration.step_executor import StepExecutor, ToolRegistry


class EchoTool:
    name = "echo"

    def can_handle(self, step, state):
        return "echo" in step

    def run(self, step, context, state):
        return {"step": step, "context": context}


class StepExecutorTests(unittest.TestCase):
    def test_uses_registered_tool_when_tool_can_handle_step(self):
        state = ExecutionState(task="test")
        executor = StepExecutor(tool_registry=ToolRegistry(tools=[EchoTool()]))

        result = asyncio.run(executor.execute("echo context", ["ctx"], state))

        self.assertEqual(result["output"], {"step": "echo context", "context": ["ctx"]})
        self.assertEqual(result["tool_results"][0]["tool"], "echo")

    def test_falls_back_to_reasoning_when_no_tool_matches(self):
        state = ExecutionState(task="test")
        executor = StepExecutor(tool_registry=ToolRegistry(tools=[]))

        result = asyncio.run(executor.execute("summarize", [], state))

        self.assertEqual(result["step"], "summarize")
        self.assertEqual(result["tool_results"], [])
        self.assertIn("Reasoned through step", result["output"])


if __name__ == "__main__":
    unittest.main()
