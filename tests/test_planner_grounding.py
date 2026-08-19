from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_platform.analytics.agents import AnalyticsPlannerAgent, AnalyticsExecutorAgent
from agent_platform.experiments.query_plan import QueryPlan
from agent_platform.orchestration.state import ExecutionState
from agent_platform.orchestration.loop import ExecutionLoop
from agent_platform.rag.retriever import SchemaRetriever


class MockSchemaRetriever:
    def retrieve_grounded(self, query: str) -> list[Any]:
        return []


class MockLLMClient:
    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self._response = response
        self.enabled = True

    def complete_json(self, system_prompt: str, user_prompt: str, temperature: float = 0.1, response_model: Any | None = None) -> dict[str, Any]:
        if self._response is not None:
            return self._response
        model_name = response_model.__name__ if response_model else ""
        if model_name == "QueryPlanOutput":
            return {
                "intent": "Identify top products by revenue growth",
                "metric": "total revenue",
                "entity": "product_category_name",
                "aggregation": "SUM",
                "filters": ["order_status IN ('delivered', 'shipped', 'invoiced')"],
                "group_by": ["product_category_name"],
                "ordering": "revenue DESC",
                "limit": 10,
                "required_tables": ["order_items", "orders", "products"],
                "reasoning": "Question asks for top products by revenue, so sum price grouped by category.",
            }
        return {}


class MockStepExecutor:
    async def execute(self, step: str, context: list[Any], state: ExecutionState) -> dict[str, Any]:
        return {
            "step": step,
            "output": {"analysis": f"done {step}", "reasoning": "", "sql": None, "schema_context": []},
            "tool_results": [],
        }


class MockEvaluator:
    async def evaluate(self, state: ExecutionState) -> dict[str, Any]:
        return {"valid": True, "score": 0.9, "reason": "grounded"}


class MockPlanner:
    def __init__(self, plan: QueryPlan) -> None:
        self._plan = plan

    async def plan(self, task: str) -> QueryPlan:
        return self._plan


class QueryPlanGroundingRegressionTests(unittest.TestCase):
    """Regression tests ensuring the planner generates question-specific QueryPlans."""

    def setUp(self) -> None:
        self.retriever = MockSchemaRetriever()

    def test_planner_returns_query_plan_not_list(self) -> None:
        planner = AnalyticsPlannerAgent(self.retriever, MockLLMClient())
        result = asyncio.run(planner.plan("What is total revenue by product category?"))
        self.assertIsInstance(result, QueryPlan)

    def test_llm_plan_fields_are_question_specific(self) -> None:
        question = "What is total revenue by product category?"
        planner = AnalyticsPlannerAgent(self.retriever, MockLLMClient())
        plan = asyncio.run(planner.plan(question))
        self.assertIn("revenue", plan.metric.lower())
        self.assertIn("product_category_name", plan.entity or "")
        self.assertEqual(plan.aggregation, "SUM")
        self.assertIn("order_items", plan.required_tables)
        self.assertIn("products", plan.required_tables)

    def test_fallback_plan_is_question_specific_not_generic(self) -> None:
        disabled_client = MockLLMClient()
        disabled_client.enabled = False
        planner = AnalyticsPlannerAgent(self.retriever, disabled_client)

        question = "What is total revenue by product category?"
        plan = asyncio.run(planner.plan(question))

        self.assertIsInstance(plan, QueryPlan)
        self.assertIn("revenue", plan.metric.lower())
        self.assertIn("product_category_name", plan.entity or "")
        self.assertEqual(plan.aggregation, "SUM")
        self.assertIn("order_items", plan.required_tables)

    def test_fallback_plan_extracts_monthly_trend(self) -> None:
        disabled_client = MockLLMClient()
        disabled_client.enabled = False
        planner = AnalyticsPlannerAgent(self.retriever, disabled_client)

        plan = asyncio.run(planner.plan("Show monthly revenue trend over time"))
        self.assertEqual(plan.group_by, ["month"])

    def test_fallback_plan_extracts_top_n_limit(self) -> None:
        disabled_client = MockLLMClient()
        disabled_client.enabled = False
        planner = AnalyticsPlannerAgent(self.retriever, disabled_client)

        plan = asyncio.run(planner.plan("Top 5 products by revenue"))
        self.assertEqual(plan.limit, 5)

    def test_fallback_plan_extracts_ordering(self) -> None:
        disabled_client = MockLLMClient()
        disabled_client.enabled = False
        planner = AnalyticsPlannerAgent(self.retriever, disabled_client)

        plan = asyncio.run(planner.plan("Highest revenue categories"))
        self.assertEqual(plan.ordering, "metric DESC")

    def test_fallback_plan_extracts_state_filter(self) -> None:
        disabled_client = MockLLMClient()
        disabled_client.enabled = False
        planner = AnalyticsPlannerAgent(self.retriever, disabled_client)

        plan = asyncio.run(planner.plan("Average order value by customer state"))
        self.assertIn("customers", plan.required_tables)
        self.assertEqual(plan.group_by, ["state"])

    def test_query_plan_to_steps_derives_executable_steps(self) -> None:
        plan = QueryPlan(
            intent="Top products by revenue",
            metric="total revenue",
            entity="product_category_name",
            aggregation="SUM",
            filters=["order_status IN ('delivered', 'shipped', 'invoiced')"],
            group_by=["product_category_name"],
            ordering="revenue DESC",
            limit=10,
            required_tables=["order_items", "orders", "products"],
        )
        steps = plan.to_steps()
        self.assertEqual(len(steps), 3)
        self.assertIn("order_items", steps[0])
        self.assertIn("SUM(total revenue)", steps[1])
        self.assertIn("product_category_name", steps[1])
        self.assertIn("revenue DESC", steps[1])
        self.assertIn("limited to 10", steps[1])

    def test_execution_loop_carries_query_plan(self) -> None:
        mock_plan = QueryPlan(
            intent="Top products by revenue",
            metric="total revenue",
            entity="product_category_name",
            aggregation="SUM",
            required_tables=["order_items", "orders", "products"],
            reasoning="Question-specific plan.",
        )
        loop = ExecutionLoop(
            planner=MockPlanner(mock_plan),
            step_executor=MockStepExecutor(),
            evaluator=MockEvaluator(),
        )
        state = asyncio.run(loop.run("What is total revenue by product category?"))
        self.assertIsInstance(state.query_plan, QueryPlan)
        self.assertIn("revenue", state.query_plan.metric.lower())
        self.assertEqual(len(state.plan), 3)

    def test_executor_uses_query_plan_context_for_sql_grounding(self) -> None:
        mock_sql_tool = MagicMock()
        mock_sql_tool.validate.return_value = MagicMock(tables=set())
        mock_sql_tool.verifier = None
        mock_sql_tool.execute.return_value = {"rows": [{"category": "test", "revenue": 100}], "row_count": 1}

        executor = AnalyticsExecutorAgent(
            schema_retriever=MockSchemaRetriever(),
            sql_tool=mock_sql_tool,
            llm_client=MockLLMClient(response={"sql": "SELECT 1", "reasoning": "ok"}),
        )
        state = ExecutionState(task="What is total revenue by product category?")
        state.query_plan = QueryPlan(
            intent="Top products by revenue",
            metric="total revenue",
            entity="product_category_name",
            aggregation="SUM",
            required_tables=["order_items", "orders", "products"],
            reasoning="Question-specific plan.",
        )
        state.plan = state.query_plan.to_steps()
        result = asyncio.run(executor.execute(state.plan[1], [], state))
        self.assertIn("sql", result["output"])
        self.assertIsNotNone(result["output"]["sql"])

    def test_generic_keyword_fallback_prevented_for_unknown_question(self) -> None:
        disabled_client = MockLLMClient()
        disabled_client.enabled = False
        planner = AnalyticsPlannerAgent(self.retriever, disabled_client)

        plan = asyncio.run(planner.plan("How many unique customers are there in Sao Paulo?"))
        self.assertIsInstance(plan, QueryPlan)
        self.assertIn("customers", plan.required_tables)

    def test_query_plan_does_not_use_hardcoded_generic_steps(self) -> None:
        disabled_client = MockLLMClient()
        disabled_client.enabled = False
        planner = AnalyticsPlannerAgent(self.retriever, disabled_client)

        plan = asyncio.run(planner.plan("What is the average review score?"))
        steps = plan.to_steps()
        for step in steps:
            self.assertNotIn("calculate revenue by product category", step.lower())
            self.assertNotIn("rank top products by revenue", step.lower())
            self.assertNotIn("summarize analytical findings with caveats", step.lower())


if __name__ == "__main__":
    unittest.main()