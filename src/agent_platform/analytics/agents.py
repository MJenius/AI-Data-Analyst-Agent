from __future__ import annotations

import asyncio
import logging
from typing import Any

from agent_platform.infra.cache import global_cache
from agent_platform.llms.client import LLMClient, get_llm_client
from agent_platform.llms.evaluator_prompt import SYSTEM_PROMPT as EVALUATOR_SYSTEM_PROMPT
from agent_platform.llms.evaluator_prompt import build_evaluator_prompt
from agent_platform.llms.planner_prompt import SYSTEM_PROMPT as PLANNER_SYSTEM_PROMPT
from agent_platform.llms.planner_prompt import build_planner_prompt
from agent_platform.llms.repair_prompt import (
    SYSTEM_PROMPT as REPAIR_SYSTEM_PROMPT,
    build_repair_prompt,
    filter_actionable_issues,
)
from agent_platform.llms.sql_generation_prompt import SYSTEM_PROMPT as SQL_SYSTEM_PROMPT
from agent_platform.llms.sql_generation_prompt import build_sql_prompt
from agent_platform.orchestration.state import ExecutionState
from agent_platform.rag.retriever import SchemaRetriever
from agent_platform.tools.sql_tool import SQLTool, SQLValidationError
from agent_platform.tools.sql_verifier import SQLSemanticVerifier, VerificationLevel


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
        context = self._schema_retriever.retrieve_grounded(task)
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
        """Execute one analytical step with Phase 6 verification-driven repair.

        Pipeline:
        1. Retrieve grounded schema context (FK-aware).
        2. Generate SQL with column-level grounding in prompt.
        3. Run SQLGlot AST + schema validation.
        4. Run semantic verification (GROUP BY, grain, join fan-out, hallucinated columns).
        5. If actionable issues are found → issue ONE targeted repair LLM call.
        6. Re-validate and re-execute the repaired SQL.
        7. Fall back to safe deterministic SQL only if both attempts fail.
        """
        context = self._schema_retriever.retrieve_grounded(f"{state.task}\n{step}")
        schema_text = [item.text for item in context]

        # ── Step 1: generate SQL ─────────────────────────────────────────────
        last_error: str | None = None
        sql: str | None = None
        reasoning: str = ""

        for attempt in range(2):   # attempt 0 = initial, attempt 1 = after execution error
            prompt_ctx = schema_text if attempt == 0 else schema_text + [f"FIX PREVIOUS ERROR: {last_error}"]
            logger.info("sql_generation attempt=%d step=%s", attempt + 1, step[:80])
            payload  = self._generate_sql_payload(state.task, step, prompt_ctx)
            sql      = payload.get("sql")
            reasoning = payload.get("reasoning", "")
            if sql is None:
                break

            # ── Step 2: AST + schema validation ─────────────────────────────
            val_errors = self._validate_sql(sql, context)
            if val_errors:
                last_error = f"Validation errors: {', '.join(val_errors)}"
                logger.warning("sql_validation_failed attempt=%d errors=%s", attempt + 1, last_error)
                continue   # retry with error in context (only 1 retry)

            # ── Step 3: semantic verification (pre-execution) ────────────────
            verifier = self._sql_tool.verifier
            if verifier:
                pre_verify = verifier.verify(sql, level=VerificationLevel.BALANCED)
                actionable = filter_actionable_issues(pre_verify.issues)
                if actionable:
                    repaired = self._attempt_repair(sql, actionable, schema_text, step)
                    if repaired and repaired != sql:
                        logger.info("sql_repair_applied step=%s", step[:80])
                        # Re-validate repaired SQL before accepting
                        r_errors = self._validate_sql(repaired, context)
                        if not r_errors:
                            sql = repaired
                            reasoning = f"[repaired] {reasoning}"
                        else:
                            logger.warning("sql_repair_validation_failed errors=%s", r_errors)

            # ── Step 4: execute ──────────────────────────────────────────────
            try:
                logger.info("sql_execute sql=%s", sql.strip()[:120])
                sql_result = await asyncio.to_thread(self._sql_tool.execute, sql)
                logger.info("sql_execute_ok rows=%d", sql_result.get("row_count", 0))

                # ── Step 5: post-execution semantic verification ─────────────
                if verifier:
                    exec_info = {
                        "success": True,
                        "row_count": sql_result.get("row_count", 0),
                        "rows": sql_result.get("rows", []),
                    }
                    post_verify = verifier.verify(
                        sql,
                        execution_result=exec_info,
                        level=VerificationLevel.BALANCED,
                    )
                    post_actionable = filter_actionable_issues(post_verify.issues)
                    if post_actionable:
                        post_repaired = self._attempt_repair(sql, post_actionable, schema_text, step)
                        if post_repaired and post_repaired != sql:
                            p_errors = self._validate_sql(post_repaired, context)
                            if not p_errors:
                                try:
                                    post_result = await asyncio.to_thread(
                                        self._sql_tool.execute, post_repaired
                                    )
                                    logger.info(
                                        "sql_post_repair_ok rows=%d",
                                        post_result.get("row_count", 0),
                                    )
                                    sql        = post_repaired
                                    sql_result = post_result
                                    reasoning  = f"[post-repair] {reasoning}"
                                except Exception as post_exc:
                                    logger.warning("sql_post_repair_exec_failed error=%s", post_exc)

                return {
                    "step": step,
                    "output": {
                        "analysis": self._interpret(step, sql_result),
                        "reasoning": reasoning,
                        "sql": sql,
                        "schema_context": schema_text,
                        "sql_result": sql_result,
                    },
                    "tool_results": [{"tool": "sql", "result": sql_result}],
                }
            except Exception as exc:
                last_error = f"Execution error: {str(exc)}"
                if not self._is_repairable_execution_error(str(exc)):
                    break
                logger.warning("sql_exec_error attempt=%d error=%s", attempt + 1, last_error)

        # ── Fallback ─────────────────────────────────────────────────────────
        fallback_sql = self._fallback_sql(state.task, step)
        if fallback_sql:
            logger.info("sql_fallback step=%s", step[:80])
            try:
                sql_result = await asyncio.to_thread(self._sql_tool.execute, fallback_sql)
                return {
                    "step": step,
                    "output": {
                        "analysis": self._interpret(step, sql_result),
                        "reasoning": f"All attempts failed ({last_error}). Used safe fallback SQL.",
                        "sql": fallback_sql,
                        "schema_context": schema_text,
                        "sql_result": sql_result,
                    },
                    "tool_results": [{"tool": "sql", "result": sql_result}],
                }
            except Exception:
                pass

        return {
            "step": step,
            "output": {
                "analysis": "Inspected schema context and business definitions.",
                "reasoning": reasoning,
                "sql": None,
                "schema_context": schema_text,
            },
            "tool_results": [],
        }

    # ── Phase 6 repair helper ─────────────────────────────────────────────────

    def _attempt_repair(
        self,
        sql: str,
        issues: list[Any],
        schema_text: list[str],
        step: str,
    ) -> str | None:
        """Issue ONE targeted repair LLM call.

        First tries the verifier's own programmatic repair (regex-based GROUP BY
        fix) — fast, free, and deterministic.  Only falls back to an LLM call if
        programmatic repair is unavailable or produces the same SQL.

        Returns the repaired SQL string, or None if repair was not possible.
        """
        verifier = self._sql_tool.verifier

        # 1. Try programmatic repair (no LLM cost).
        if verifier:
            for issue in issues:
                candidate = verifier.generate_repair(issue, sql)
                if candidate and candidate.strip() != sql.strip():
                    logger.info("sql_programmatic_repair category=%s", issue.category.value)
                    return candidate

        # 2. LLM repair — one call, no retries.
        if not self._llm_client.enabled:
            return None
        try:
            from agent_platform.llms.models import SQLOutput

            repair_user_prompt = build_repair_prompt(sql, issues, schema_text)
            result = self._llm_client.complete_json(
                system_prompt=REPAIR_SYSTEM_PROMPT,
                user_prompt=repair_user_prompt,
                response_model=SQLOutput,
            )
            if not isinstance(result, dict):
                return None
            repaired_sql = result.get("sql")
            if repaired_sql and isinstance(repaired_sql, str):
                logger.info("sql_llm_repair_ok step=%s", step[:80])
                return repaired_sql
        except Exception as exc:
            logger.warning("sql_llm_repair_failed error=%s", exc)
        return None

    def _validate_sql(self, sql: str, schema_context: list[Any]) -> list[str]:
        allowed_tables = {
            item.metadata["table"].lower()
            for item in schema_context
            if item.metadata.get("kind") == "table"
        }
        try:
            self._sql_tool.validate(sql, allowed_tables)
            return []
        except SQLValidationError as exc:
            return exc.errors

    @staticmethod
    def _is_repairable_execution_error(error: str) -> bool:
        lowered = error.lower()
        return any(
            marker in lowered
            for marker in (
                "ambiguous column", "misuse of", "no such column", "no such function",
                "no such table", "syntax error", "wrong number of arguments",
            )
        )

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
            return "SELECT name, type FROM sqlite_master WHERE type='table' ORDER BY name;"
        
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
            if col in ["product_category_name", "category", "product_name", "state", "month", "payment_type", "seller_id", "customer_unique_id", "name", "type"]:
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
