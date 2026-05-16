from __future__ import annotations

import logging
from typing import Any

from agent_platform.llms.evaluator_prompt import SYSTEM_PROMPT as EVALUATOR_SYSTEM_PROMPT
from agent_platform.llms.evaluator_prompt import build_evaluator_prompt
from agent_platform.llms.groq_client import GroqClient, GroqClientError
from agent_platform.llms.planner_prompt import SYSTEM_PROMPT as PLANNER_SYSTEM_PROMPT
from agent_platform.llms.planner_prompt import build_planner_prompt
from agent_platform.llms.sql_generation_prompt import SYSTEM_PROMPT as SQL_SYSTEM_PROMPT
from agent_platform.llms.sql_generation_prompt import build_sql_prompt
from agent_platform.orchestration.state import ExecutionState
from agent_platform.rag.retriever import SchemaRetriever
from agent_platform.tools.sql_tool import SQLTool


logger = logging.getLogger(__name__)


class AnalyticsPlannerAgent:
    """Schema-aware planner powered by Groq, with a deterministic local fallback."""

    def __init__(self, schema_retriever: SchemaRetriever, llm_client: GroqClient | None = None) -> None:
        self._schema_retriever = schema_retriever
        self._llm_client = llm_client or GroqClient()
        self.last_reasoning: str | None = None

    async def plan(self, task: str) -> list[str]:
        context = self._schema_retriever.retrieve(task, top_k=5)
        context_text = [item.text for item in context]
        if self._llm_client.enabled:
            try:
                result = self._llm_client.complete_json(
                    system_prompt=PLANNER_SYSTEM_PROMPT,
                    user_prompt=build_planner_prompt(task, context_text),
                )
                steps = result.get("steps", [])
                if isinstance(steps, list) and all(isinstance(step, str) for step in steps):
                    self.last_reasoning = str(result.get("reasoning", "LLM generated the analytical plan."))
                    return steps
            except GroqClientError as exc:
                logger.warning("planner_llm_fallback", extra={"error": str(exc)})
        self.last_reasoning = "Used deterministic fallback plan because Groq was unavailable."
        return self._fallback_plan(task, context)

    def _fallback_plan(self, task: str, context: list[Any]) -> list[str]:
        context_hint = "; ".join(item.metadata.get("table", item.id) for item in context[:3])
        steps = ["inspect relevant schema and business definitions"]
        lowered = task.lower()
        if "growth" in lowered or "highest revenue" in lowered:
            steps.extend(
                [
                    "calculate product revenue growth between prior and current periods",
                    "identify regional revenue contribution for growth leaders",
                    "summarize product growth drivers with supporting metrics",
                ]
            )
        elif "drop" in lowered or "decline" in lowered:
            steps.extend(
                [
                    "calculate monthly revenue trend",
                    "compare month over month revenue movement",
                    "identify category and product declines",
                ]
            )
        else:
            steps.extend(
                [
                    "calculate revenue by product category",
                    "rank top products by revenue",
                    "summarize analytical findings with caveats",
                ]
            )
        return [f"{step} | schema_context={context_hint}" for step in steps]


class AnalyticsExecutorAgent:
    """Executes each step by generating SQL with Groq and validating it through the SQL tool."""

    def __init__(
        self,
        schema_retriever: SchemaRetriever,
        sql_tool: SQLTool,
        llm_client: GroqClient | None = None,
    ) -> None:
        self._schema_retriever = schema_retriever
        self._sql_tool = sql_tool
        self._llm_client = llm_client or GroqClient()

    async def execute(
        self,
        step: str,
        context: list[Any],
        state: ExecutionState,
    ) -> dict[str, Any]:
        schema_context = self._schema_retriever.retrieve(f"{state.task} {step}", top_k=5)
        schema_text = [item.text for item in schema_context]
        sql_payload = self._generate_sql_payload(state.task, step, schema_text)
        sql = sql_payload.get("sql")
        reasoning = sql_payload.get("reasoning", "Generated SQL from schema context.")
        if sql is None:
            output = {
                "analysis": "Inspected schema context and business definitions.",
                "reasoning": reasoning,
                "sql": None,
                "schema_context": [item.text for item in schema_context],
            }
            return {"step": step, "output": output, "tool_results": []}

        try:
            sql_result = self._sql_tool.execute(sql)
        except Exception as exc:
            logger.warning("llm_sql_failed_using_fallback", extra={"step": step, "error": str(exc)})
            fallback_sql = self._fallback_sql(state.task, step)
            if fallback_sql is None:
                raise
            sql_result = self._sql_tool.execute(fallback_sql)
            sql = fallback_sql
            reasoning = f"LLM SQL failed validation; used safe fallback SQL. Original error: {exc}"
        analysis = self._interpret(step, sql_result)
        return {
            "step": step,
            "output": {
                "analysis": analysis,
                "reasoning": reasoning,
                "sql": sql,
                "schema_context": [item.text for item in schema_context],
                "sql_result": sql_result,
            },
            "tool_results": [{"tool": "sql", "result": sql_result}],
        }

    def _generate_sql_payload(self, task: str, step: str, schema_context: list[str]) -> dict[str, Any]:
        if self._llm_client.enabled:
            try:
                result = self._llm_client.complete_json(
                    system_prompt=SQL_SYSTEM_PROMPT,
                    user_prompt=build_sql_prompt(task, step, schema_context),
                )
                if "sql" in result:
                    return {
                        "sql": result.get("sql"),
                        "reasoning": result.get("reasoning", "Groq generated SQL from schema context."),
                    }
            except GroqClientError as exc:
                logger.warning("sql_generation_llm_fallback", extra={"error": str(exc), "step": step})
        return {
            "sql": self._fallback_sql(task, step),
            "reasoning": "Used deterministic safe SQL fallback because Groq was unavailable.",
        }

    def _fallback_sql(self, task: str, step: str) -> str | None:
        lowered = f"{task} {step}".lower()
        if "schema" in lowered and "calculate" not in lowered:
            return None
        if "growth" in lowered or "highest revenue" in lowered:
            return """
            WITH product_period_revenue AS (
                SELECT
                    p.name AS product_name,
                    p.category,
                    CASE
                        WHEN o.order_date < '2025-04-01' THEN 'prior_period'
                        ELSE 'current_period'
                    END AS period,
                    ROUND(SUM(oi.quantity * oi.unit_price * (1 - oi.discount_rate)), 2) AS revenue
                FROM order_items oi
                JOIN orders o ON o.id = oi.order_id
                JOIN products p ON p.id = oi.product_id
                WHERE o.status = 'paid'
                GROUP BY p.name, p.category, period
            )
            SELECT
                product_name,
                category,
                ROUND(SUM(CASE WHEN period = 'prior_period' THEN revenue ELSE 0 END), 2) AS prior_revenue,
                ROUND(SUM(CASE WHEN period = 'current_period' THEN revenue ELSE 0 END), 2) AS current_revenue,
                ROUND(
                    SUM(CASE WHEN period = 'current_period' THEN revenue ELSE 0 END)
                    - SUM(CASE WHEN period = 'prior_period' THEN revenue ELSE 0 END),
                    2
                ) AS revenue_growth
            FROM product_period_revenue
            GROUP BY product_name, category
            ORDER BY revenue_growth DESC
            LIMIT 5
            """
        if "regional" in lowered or "region" in lowered:
            return """
            SELECT
                o.region,
                p.name AS product_name,
                ROUND(SUM(oi.quantity * oi.unit_price * (1 - oi.discount_rate)), 2) AS revenue
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            JOIN products p ON p.id = oi.product_id
            WHERE o.status = 'paid'
            GROUP BY o.region, p.name
            ORDER BY revenue DESC
            LIMIT 8
            """
        if "trend" in lowered or "month" in lowered or "drop" in lowered:
            return """
            SELECT
                substr(o.order_date, 1, 7) AS month,
                ROUND(SUM(oi.quantity * oi.unit_price * (1 - oi.discount_rate)), 2) AS revenue
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            WHERE o.status = 'paid'
            GROUP BY month
            ORDER BY month
            """
        return """
        SELECT
            p.category,
            p.name AS product_name,
            ROUND(SUM(oi.quantity * oi.unit_price * (1 - oi.discount_rate)), 2) AS revenue
        FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        JOIN products p ON p.id = oi.product_id
        WHERE o.status = 'paid'
        GROUP BY p.category, p.name
        ORDER BY revenue DESC
        LIMIT 10
        """

    def _interpret(self, step: str, sql_result: dict[str, Any]) -> str:
        rows = sql_result["rows"]
        if not rows:
            return "The query returned no rows, so no supporting metric is available."
        first = rows[0]
        if "revenue_growth" in first:
            return (
                f"{first['product_name']} leads revenue growth with "
                f"{first['revenue_growth']} incremental revenue."
            )
        if "region" in first:
            return f"{first['region']} shows the strongest regional revenue contribution."
        if "month" in first:
            return "Monthly revenue trend was calculated for anomaly and drop analysis."
        return f"{first.get('product_name', first.get('category', 'Top segment'))} is the leading revenue contributor."


class AnalyticsEvaluatorAgent:
    """Validates SQL-backed analytical outputs and assigns confidence with Groq when available."""

    def __init__(self, llm_client: GroqClient | None = None) -> None:
        self._llm_client = llm_client or GroqClient()

    async def evaluate(self, state: ExecutionState) -> dict[str, Any]:
        issues: list[str] = []
        sql_results = [
            result["result"]
            for result in state.tool_results
            if result.get("tool") == "sql" and isinstance(result.get("result"), dict)
        ]
        if not sql_results:
            issues.append("No SQL-backed evidence was produced.")
        for result in sql_results:
            if not result.get("query", "").lower().lstrip().startswith(("select", "with")):
                issues.append("Generated SQL was not read-only.")
            if result.get("row_count", 0) == 0:
                issues.append("A generated query returned no rows.")
        fallback = {
            "confidence": 0.92 if bool(state.intermediate_outputs) and not issues else 0.45,
            "issues": issues,
            "validated": bool(state.intermediate_outputs) and not issues,
            "reasoning": "Validated SQL safety, evidence presence, and non-empty result sets.",
        }
        if not self._llm_client.enabled:
            return fallback
        try:
            draft_report = {"intermediate_outputs": state.intermediate_outputs}
            result = self._llm_client.complete_json(
                system_prompt=EVALUATOR_SYSTEM_PROMPT,
                user_prompt=build_evaluator_prompt(state.task, state.plan, sql_results, draft_report),
            )
            confidence = float(result.get("confidence", fallback["confidence"]))
            confidence = max(0.0, min(1.0, confidence))
            llm_issues = result.get("issues", [])
            if not isinstance(llm_issues, list):
                llm_issues = [str(llm_issues)]
            return {
                "confidence": confidence,
                "issues": issues + [str(issue) for issue in llm_issues],
                "validated": bool(result.get("validated", fallback["validated"])) and not issues,
                "reasoning": str(result.get("reasoning", fallback["reasoning"])),
            }
        except (GroqClientError, TypeError, ValueError) as exc:
            logger.warning("evaluator_llm_fallback", extra={"error": str(exc)})
            return fallback
