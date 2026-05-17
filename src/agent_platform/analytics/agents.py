from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from agent_platform.infra.cache import global_cache
from agent_platform.llms.client import LLMClient, get_llm_client
from agent_platform.llms.evaluator_prompt import SYSTEM_PROMPT as EVALUATOR_SYSTEM_PROMPT
from agent_platform.llms.evaluator_prompt import build_evaluator_prompt
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

    def __init__(self, schema_retriever: SchemaRetriever, llm_client: LLMClient | None = None) -> None:
        self._schema_retriever = schema_retriever
        self._llm_client = llm_client or get_llm_client()
        self.last_reasoning: str | None = None

    async def plan(self, task: str) -> list[str]:
        """
        Generates a multi-step analytical plan for a given business question.
        
        Uses semantic retrieval to find relevant table schemas and then leverages
        the LLM to decompose the question into executable analytical steps.
        """
        context = self._schema_retriever.retrieve(task, top_k=5)
        context_text = [item.text for item in context]
        logger.info(f"Planning analytical steps for: {task}")
        if self._llm_client.enabled:
            try:
                logger.info(f"Requesting plan from LLM (Provider: {type(self._llm_client).__name__})...")
                from agent_platform.llms.models import PlannerOutput
                result = self._llm_client.complete_json(
                    system_prompt=PLANNER_SYSTEM_PROMPT,
                    user_prompt=build_planner_prompt(task, context_text),
                    response_model=PlannerOutput,
                )
                if not isinstance(result, dict):
                    raise ValueError("Planner did not return a valid JSON object.")
                steps = result.get("steps")
                if steps is None or not isinstance(steps, list):
                    raise KeyError("Planner output is missing 'steps' list.")
                if not all(isinstance(step, str) for step in steps):
                    raise ValueError("All planner steps must be strings.")
                reasoning = result.get("reasoning")
                if reasoning is None or not isinstance(reasoning, str):
                    raise KeyError("Planner output is missing 'reasoning' string.")
                
                self.last_reasoning = reasoning
                return steps
            except Exception as exc:
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
        llm_client: LLMClient | None = None,
    ) -> None:
        self._schema_retriever = schema_retriever
        self._sql_tool = sql_tool
        self._llm_client = llm_client or get_llm_client()

    async def execute(
        self,
        step: str,
        context: list[Any],
        state: ExecutionState,
    ) -> dict[str, Any]:
        """
        Executes a single step of the analytical plan.
        
        This involves:
        1. Retrieving specific schema context for the step.
        2. Generating SQL using the LLM.
        3. Validating the SQL for safety and correctness.
        4. Executing the SQL and interpreting the results.
        5. Retrying with error context if execution fails.
        """
        # 1. Fast Retrieval - Proactively retrieve table schemas if missing
        if not any(item.metadata.get("kind") == "table" for item in context):
            logger.info("No table documents found in step context. Proactively retrieving table schema context...")
            additional_context = self._schema_retriever.retrieve(step + " tables", top_k=3)
            existing_ids = {item.id for item in context}
            for item in additional_context:
                if item.id not in existing_ids:
                    context.append(item)

        schema_text = [item.text for item in context]

        # 2. SQL Generation (Enabled Retries for Self-Correction)
        max_retries = 2
        last_error = None
        sql = None
        reasoning = ""

        for attempt in range(max_retries + 1):
            prompt_context = schema_text
            if last_error:
                prompt_context = schema_text + [f"FIX PREVIOUS ERROR: {last_error}"]

            logger.info(f"Executing analytical step (Attempt {attempt + 1}/{max_retries + 1}): {step}")
            sql_payload = self._generate_sql_payload(state.task, step, prompt_context)
            sql = sql_payload.get("sql")
            reasoning = sql_payload.get("reasoning", "Generated SQL from schema context.")

            if sql is None:
                break

            # 3. Validation
            validation_errors = self._validate_sql(sql, context)
            if not validation_errors:
                try:
                    logger.info(f"Running SQL: {sql.strip()}")
                    sql_result = await asyncio.to_thread(self._sql_tool.execute, sql)
                    logger.info(f"SQL executed successfully. Returned {sql_result.get('row_count', 0)} rows.")
                    analysis = self._interpret(step, sql_result)
                    return {
                        "step": step,
                        "output": {
                            "analysis": analysis,
                            "reasoning": reasoning,
                            "sql": sql,
                            "schema_context": [item.text for item in context],
                            "sql_result": sql_result,
                        },
                        "tool_results": [{"tool": "sql", "result": sql_result}],
                    }
                except Exception as exc:
                    last_error = f"Execution error: {str(exc)}"
            else:
                last_error = f"Validation errors: {', '.join(validation_errors)}"
            
            logger.warning("sql_attempt_failed", extra={"attempt": attempt + 1, "error": last_error})

        # 4. Fallback if all retries fail
        if sql is None or last_error:
            fallback_sql = self._fallback_sql(state.task, step)
            if fallback_sql:
                logger.info(f"Using safe fallback SQL: {fallback_sql.strip()}")
                sql_result = await asyncio.to_thread(self._sql_tool.execute, fallback_sql)
                return {
                    "step": step,
                    "output": {
                        "analysis": self._interpret(step, sql_result),
                        "reasoning": f"Retries failed ({last_error}). Used safe fallback SQL.",
                        "sql": fallback_sql,
                        "schema_context": [item.text for item in context],
                        "sql_result": sql_result,
                    },
                    "tool_results": [{"tool": "sql", "result": sql_result}],
                }

        output = {
            "analysis": "Inspected schema context and business definitions.",
            "reasoning": reasoning,
            "sql": None,
            "schema_context": [item.text for item in context],
        }
        return {"step": step, "output": output, "tool_results": []}

    def _validate_sql(self, sql: str, schema_context: list[Any]) -> list[str]:
        """Strict linting to check for destructive keywords and prevent hallucinations."""
        errors = []
        lowered_sql = sql.lower()
        
        # Get allowed table names from retrieved context
        allowed_tables = set()
        for item in schema_context:
            if item.metadata.get("kind") == "table":
                allowed_tables.add(item.metadata["table"].lower())
        
        # Extract potential table targets by finding patterns in JOIN / FROM clauses
        # E.g. "from table_name" or "join table_name"
        table_matches = re.findall(r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)", lowered_sql)
        for tbl in table_matches:
            if tbl in ["product_category_name_translation"]:
                continue
            if tbl not in allowed_tables:
                errors.append(f"Table '{tbl}' is not in retrieved schema context (hallucination prevention).")

        # Rigorous check for destructive SQL commands to guarantee safety
        destructive_keywords = ["delete", "drop", "update", "insert", "alter", "create", "replace", "truncate", "grant", "revoke"]
        for kw in destructive_keywords:
            if re.search(r"\b" + kw + r"\b", lowered_sql):
                errors.append(f"Destructive SQL command '{kw}' is not allowed in read-only environment.")
            
        return errors

    def _generate_sql_payload(self, task: str, step: str, schema_context: list[str]) -> dict[str, Any]:
        if self._llm_client.enabled:
            try:
                from agent_platform.llms.models import SQLOutput
                result = self._llm_client.complete_json(
                    system_prompt=SQL_SYSTEM_PROMPT,
                    user_prompt=build_sql_prompt(task, step, schema_context),
                    response_model=SQLOutput,
                )
                if not isinstance(result, dict):
                    raise ValueError("Executor did not return a valid JSON object.")
                sql = result.get("sql")
                reasoning = result.get("reasoning")
                if reasoning is None or not isinstance(reasoning, str):
                    raise KeyError("Executor output is missing 'reasoning' string.")
                if sql is not None and not isinstance(sql, str):
                    raise ValueError("Executor 'sql' must be a string or null.")
                return {
                    "sql": sql,
                    "reasoning": reasoning,
                }
            except Exception as exc:
                logger.warning("sql_generation_llm_fallback", extra={"error": str(exc), "step": step})
        return {
            "sql": self._fallback_sql(task, step),
            "reasoning": "Used deterministic safe SQL fallback because Groq was unavailable.",
        }

    def _fallback_sql(self, task: str, step: str) -> str | None:
        core_step = step.split("|")[0].strip().lower()
        lowered = f"{task} {core_step}".lower()

        if "schema" in core_step and "calculate" not in core_step:
            return None
        
        if "regional" in lowered or "state" in lowered:
            return """
            SELECT
                c.customer_state AS state,
                ROUND(SUM(oi.price), 2) AS revenue
            FROM order_items oi
            JOIN orders o ON o.order_id = oi.order_id
            JOIN customers c ON c.customer_id = o.customer_id
            WHERE o.order_status IN ('delivered', 'shipped', 'invoiced')
            GROUP BY state
            ORDER BY revenue DESC
            LIMIT 10
            """
        if "growth" in lowered or "highest revenue" in lowered or "top 5" in lowered or "category" in lowered:
            return """
            SELECT
                p.product_category_name,
                ROUND(SUM(oi.price), 2) AS revenue
            FROM order_items oi
            JOIN orders o ON o.order_id = oi.order_id
            JOIN products p ON p.product_id = oi.product_id
            WHERE o.order_status IN ('delivered', 'shipped', 'invoiced')
            GROUP BY p.product_category_name
            ORDER BY revenue DESC
            LIMIT 10
            """
        if "trend" in lowered or "month" in lowered or "drop" in lowered or "over time" in lowered or "history" in lowered or "time series" in lowered:
            return """
            SELECT
                substr(o.order_purchase_timestamp, 1, 7) AS month,
                ROUND(SUM(oi.price), 2) AS revenue
            FROM order_items oi
            JOIN orders o ON o.order_id = oi.order_id
            WHERE o.order_status IN ('delivered', 'shipped', 'invoiced')
            GROUP BY month
            ORDER BY month
            """
        if "aov" in lowered or "average order value" in lowered or "average order" in lowered or "average value" in lowered:
            return """
            SELECT ROUND(SUM(price) / COUNT(DISTINCT order_id), 2) AS average_order_value
            FROM order_items
            """

        if "seller" in lowered:
            return """
            SELECT
                oi.seller_id,
                COUNT(DISTINCT oi.order_id) AS total_orders,
                ROUND(SUM(oi.price), 2) AS total_sales
            FROM order_items oi
            GROUP BY oi.seller_id
            ORDER BY total_sales DESC
            LIMIT 10
            """
        
        if "repeat" in lowered or "loyalty" in lowered or "recurring" in lowered:
            return """
            SELECT
                c.customer_unique_id,
                COUNT(o.order_id) AS order_count
            FROM orders o
            JOIN customers c ON c.customer_id = o.customer_id
            GROUP BY c.customer_unique_id
            HAVING order_count > 1
            ORDER BY order_count DESC
            LIMIT 10
            """
            
        if "cancel" in lowered or "cancellation" in lowered:
            return """
            SELECT
                o.order_status,
                COUNT(DISTINCT o.order_id) AS order_count,
                ROUND(SUM(oi.price), 2) AS total_price
            FROM orders o
            LEFT JOIN order_items oi ON o.order_id = oi.order_id
            WHERE o.order_status = 'canceled'
            GROUP BY o.order_status
            """
            
        if "rating" in lowered or "review" in lowered:
            return """
            SELECT
                review_score,
                COUNT(*) AS count,
                ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM order_reviews), 2) AS percentage
            FROM order_reviews
            GROUP BY review_score
            ORDER BY review_score DESC
            """
            
        if "geolocation" in lowered or "density" in lowered or "zip" in lowered:
            return """
            SELECT
                customer_state,
                COUNT(DISTINCT customer_unique_id) AS unique_customers
            FROM customers
            GROUP BY customer_state
            ORDER BY unique_customers DESC
            LIMIT 10
            """
            
        if "payment" in lowered:
            return """
            SELECT
                payment_type,
                COUNT(DISTINCT order_id) AS order_count,
                ROUND(SUM(payment_value), 2) AS total_payment_value
            FROM order_payments
            GROUP BY payment_type
            ORDER BY order_count DESC
            """

        return """
        SELECT
            p.product_category_name,
            COUNT(DISTINCT o.order_id) AS order_count,
            ROUND(SUM(oi.price), 2) AS total_revenue
        FROM order_items oi
        JOIN orders o ON o.order_id = oi.order_id
        JOIN products p ON p.product_id = oi.product_id
        GROUP BY p.product_category_name
        ORDER BY total_revenue DESC
        LIMIT 10
        """

    def _interpret(self, step: str, sql_result: dict[str, Any]) -> str:
        rows = sql_result["rows"]
        if not rows:
            return "The query returned no rows, so no supporting metric is available."
        first = rows[0]
        
        parts = []
        for col, val in first.items():
            if col in ["product_category_name", "category", "product_name", "state", "month", "payment_type", "seller_id", "customer_unique_id"]:
                parts.append(f"{col}: {val}")
            elif col in ["revenue", "total_revenue", "total_sales", "payment_value", "total_payment_value", "price"]:
                try:
                    parts.append(f"Revenue: ${float(val):,.2f}")
                except (ValueError, TypeError):
                    parts.append(f"Revenue: {val}")
            elif col in ["order_count", "total_orders", "count", "unique_customers", "order_item_id"]:
                parts.append(f"Count: {val}")
            elif col in ["average_order_value", "aov"]:
                try:
                    parts.append(f"AOV: ${float(val):,.2f}")
                except (ValueError, TypeError):
                    parts.append(f"AOV: {val}")
                    
        if parts:
            return f"Top result indicators: {', '.join(parts)}."
        return f"{list(first.values())[0]} is the leading metric for this step."


class AnalyticsEvaluatorAgent:
    """Validates SQL-backed analytical outputs and assigns confidence with Groq when available."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm_client = llm_client or get_llm_client()

    async def evaluate(self, state: ExecutionState) -> dict[str, Any]:
        """
        Evaluates the full execution state to assign a confidence score and verdict.
        
        Checks for SQL safety, data presence, and logical consistency between 
        the steps and the final outputs.
        """
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
            "why_explanation": "Analytical synthesis was performed based on available SQL data points.",
            "anomalies": [],
            "confidence_explanation": "Confidence is based on the presence of validated SQL queries and non-empty results." if not issues else "Confidence is low due to identified issues in the analytical trace.",
        }
        if not self._llm_client.enabled:
            return fallback
        try:
            draft_report = {"intermediate_outputs": state.intermediate_outputs}
            from agent_platform.llms.models import EvaluatorOutput
            result = self._llm_client.complete_json(
                system_prompt=EVALUATOR_SYSTEM_PROMPT,
                user_prompt=build_evaluator_prompt(state.task, state.plan, sql_results, draft_report),
                response_model=EvaluatorOutput,
            )
            if not isinstance(result, dict):
                raise ValueError("Evaluator did not return a valid JSON object.")
            
            # Require key structure fields
            summary = result.get("summary")
            if summary is None or not isinstance(summary, str):
                raise KeyError("Evaluator output is missing 'summary' string.")
            
            key_findings = result.get("key_findings")
            if key_findings is None or not isinstance(key_findings, list):
                raise KeyError("Evaluator output is missing 'key_findings' list.")
            
            confidence = result.get("confidence")
            if confidence is None:
                raise KeyError("Evaluator output is missing 'confidence' field.")
            try:
                confidence = float(confidence)
            except (ValueError, TypeError):
                raise ValueError("Evaluator 'confidence' must be a numeric value.")
            
            confidence = max(0.0, min(1.0, confidence))
            llm_issues = result.get("issues", [])
            if not isinstance(llm_issues, list):
                llm_issues = [str(llm_issues)]
            return {
                "summary": summary,
                "key_findings": key_findings,
                "why_explanation": result.get("why_explanation"),
                "anomalies": result.get("anomalies", []),
                "confidence": confidence,
                "confidence_explanation": result.get("confidence_explanation", fallback["confidence_explanation"]),
                "issues": issues + [str(issue) for issue in llm_issues],
                "validated": bool(result.get("validated", fallback["validated"])) and not issues,
                "reasoning": str(result.get("reasoning", fallback["reasoning"])),
                "verdict": "accurate" if confidence > 0.8 else "uncertain",
                "detected_contradictions": result.get("detected_contradictions", [])
            }
        except (Exception, TypeError, ValueError) as exc:
            logger.exception("evaluator_llm_fallback triggered")
            return fallback
