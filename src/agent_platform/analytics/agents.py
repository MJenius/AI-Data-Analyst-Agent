from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from agent_platform.experiments.query_plan import QueryPlan
from agent_platform.infra.cache import global_cache
from agent_platform.llms.client import LLMClient, get_llm_client
from agent_platform.llms.evaluator_prompt import SYSTEM_PROMPT as EVALUATOR_SYSTEM_PROMPT
from agent_platform.llms.evaluator_prompt import build_evaluator_prompt
from agent_platform.llms.models import QueryPlanOutput
from agent_platform.llms.planner_prompt import SYSTEM_PROMPT as PLANNER_SYSTEM_PROMPT
from agent_platform.llms.planner_prompt import build_planner_prompt
from agent_platform.llms.repair_prompt import (
    SYSTEM_PROMPT as REPAIR_SYSTEM_PROMPT,
    build_repair_prompt,
    filter_actionable_issues,
)
from agent_platform.llms.sql_generation_prompt import SYSTEM_PROMPT as SQL_SYSTEM_PROMPT
from agent_platform.llms.sql_generation_prompt import build_sql_prompt
from agent_platform.llms.sql_truncation import is_sql_truncated
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

    async def plan(self, task: str) -> QueryPlan:
        """
        Generates a structured QueryPlan for a given business question.

        Uses semantic retrieval to find relevant table schemas and then leverages
        the LLM to produce an explicitly grounded query plan.
        """
        context = self._schema_retriever.retrieve_grounded(task)
        context_text = [item.text for item in context]
        logger.info(f"Planning query plan for: {task}")
        if self._llm_client.enabled:
            try:
                logger.info(f"Requesting plan from LLM (Provider: {type(self._llm_client).__name__})...")
                result = await asyncio.to_thread(
                    self._llm_client.complete_json,
                    system_prompt=PLANNER_SYSTEM_PROMPT,
                    user_prompt=build_planner_prompt(task, context_text),
                    response_model=QueryPlanOutput,
                )
                if not isinstance(result, dict):
                    raise ValueError("Planner did not return a valid JSON object.")
                plan = QueryPlanOutput(**result)
                self.last_reasoning = plan.reasoning
                
                from agent_platform.experiments.query_plan import CompositeMetric, MetricType
                comp_metric = None
                if plan.composite_metric:
                    comp_metric = CompositeMetric(
                        metric_type=MetricType(plan.composite_metric.metric_type) if plan.composite_metric.metric_type in MetricType.__members__.values() else MetricType.SIMPLE,
                        name=plan.composite_metric.name,
                        numerator=plan.composite_metric.numerator,
                        denominator=plan.composite_metric.denominator,
                        aggregation=plan.composite_metric.aggregation,
                        grouping_grain=plan.composite_metric.grouping_grain,
                        filter_scope=plan.composite_metric.filter_scope,
                        formula_template=plan.composite_metric.formula_template,
                        source_columns=getattr(plan.composite_metric, 'source_columns', []),
                    )

                raw_plan = QueryPlan(
                    intent=plan.intent,
                    entities=plan.entities or ([plan.entity] if plan.entity else []),
                    entity=plan.entity,
                    required_tables=plan.required_tables,
                    join_path=plan.join_path,
                    metric=plan.metric,
                    composite_metric=comp_metric,
                    aggregation=plan.aggregation,
                    filters=plan.filters,
                    time_column=plan.time_column,
                    time_range=plan.time_range,
                    time_grain=plan.time_grain,
                    group_by=plan.group_by,
                    ranking_dimension=plan.ranking_dimension,
                    ranking_metric=plan.ranking_metric,
                    ranking_direction=plan.ranking_direction,
                    ordering=plan.ordering,
                    limit=plan.limit,
                    result_shape=plan.result_shape,
                    metric_source_column=getattr(plan, 'metric_source_column', None),
                    reasoning=plan.reasoning,
                )

                # Pre-SQL PlanValidator: validate and deterministically repair
                from agent_platform.tools.plan_validator import PlanValidator
                validator = PlanValidator()
                val_res = validator.validate(raw_plan, question=task)
                if val_res.repaired_plan:
                    return val_res.repaired_plan
                return raw_plan
            except Exception as exc:
                logger.warning("planner_llm_fallback: %s", exc)
        self.last_reasoning = "Used deterministic fallback plan because LLM was unavailable."
        fallback_plan = self._fallback_plan(task, context)
        from agent_platform.tools.plan_validator import PlanValidator
        validator = PlanValidator()
        val_res = validator.validate(fallback_plan, question=task)
        return val_res.repaired_plan or fallback_plan

    def _derive_tables_from_question(self, task: str) -> list[str]:
        """Derive likely required tables from the question text."""
        lowered = task.lower()
        tables = []
        if any(k in lowered for k in ["customer", "state", "region", "aov", "repeat", "loyalty"]):
            tables.append("customers")
        if any(k in lowered for k in ["order", "month", "trend", "time", "drop", "decline", "cancel", "review", "seller"]):
            tables.append("orders")
        if any(k in lowered for k in ["item", "revenue", "sales", "price", "product", "category", "seller", "aov"]):
            tables.append("order_items")
        if any(k in lowered for k in ["product", "category"]):
            tables.append("products")
        if any(k in lowered for k in ["payment", "installment"]):
            tables.append("order_payments")
        if any(k in lowered for k in ["review", "rating", "score"]):
            tables.append("order_reviews")
        if any(k in lowered for k in ["seller", "state"]):
            tables.append("sellers")
        if any(k in lowered for k in ["geolocation", "zip", "density", "lat", "lng"]):
            tables.append("geolocation")
        if not tables:
            tables = ["order_items", "orders", "products"]
        return list(dict.fromkeys(tables))

    def _derive_metric_aggregation(self, task: str) -> tuple[str, str | None]:
        """Derive metric and aggregation from question text."""
        lowered = task.lower()
        if any(k in lowered for k in ["revenue", "sales", "gmv", "amount"]):
            return "total revenue", "SUM"
        if any(k in lowered for k in ["average order value", "aov"]):
            return "average order value", "AVG"
        if any(k in lowered for k in ["average", "avg", "mean"]):
            return "average value", "AVG"
        if any(k in lowered for k in ["count", "number of", "how many", "total orders", "total customers"]):
            return "count", "COUNT"
        if any(k in lowered for k in ["review", "rating", "score"]):
            return "average review score", "AVG"
        if any(k in lowered for k in ["payment", "installment"]):
            return "total payment value", "SUM"
        return "count", "COUNT"

    def _derive_filters(self, task: str) -> list[str]:
        """Derive filters from question text."""
        lowered = task.lower()
        filters = []
        if any(k in lowered for k in ["delivered", "shipped", "invoiced"]):
            filters.append("order_status IN ('delivered', 'shipped', 'invoiced')")
        if any(k in lowered for k in ["canceled", "cancelled", "cancellation"]):
            filters.append("order_status = 'canceled'")
        if re.search(r"20\d{2}", lowered):
            year_match = re.search(r"(20\d{2})", lowered)
            if year_match:
                year = year_match.group(1)
                filters.append(f"strftime('%Y', order_purchase_timestamp) = '{year}'")
        if any(k in lowered for k in ["month", "monthly", "per month"]):
            filters.append("group by month using substr(order_purchase_timestamp, 1, 7)")
        return filters

    def _derive_group_by(self, task: str) -> list[str] | None:
        """Derive group_by fields from question text."""
        lowered = task.lower()
        if any(k in lowered for k in ["month", "monthly", "per month", "over time"]):
            return ["month"]
        if any(k in lowered for k in ["state", "region", "location"]):
            return ["state"]
        if any(k in lowered for k in ["category", "categories"]):
            return ["product_category_name"]
        if any(k in lowered for k in ["seller", "sellers"]):
            return ["seller_id"]
        if any(k in lowered for k in ["payment", "payments"]):
            return ["payment_type"]
        if any(k in lowered for k in ["review", "rating", "score"]):
            return ["review_score"]
        if any(k in lowered for k in ["customer", "customers"]):
            return ["customer_state"]
        return None

    def _derive_ordering(self, task: str) -> str | None:
        """Derive ordering from question text."""
        lowered = task.lower()
        if any(k in lowered for k in ["top", "highest", "best", "most"]):
            return "metric DESC"
        if any(k in lowered for k in ["bottom", "lowest", "worst", "least"]):
            return "metric ASC"
        return None

    def _derive_limit(self, task: str) -> int | None:
        """Derive limit from question text."""
        lowered = task.lower()
        match = re.search(r"(top|bottom)\s+(\d+)", lowered)
        if match:
            return int(match.group(2))
        if any(k in lowered for k in ["top 5", "top five", "top 10", "top ten"]):
            return 10
        return None

    def _fallback_plan(self, task: str, context: list[Any]) -> QueryPlan:
        """Generate a deterministic question-specific QueryPlan when LLM is unavailable."""
        lowered = task.lower()
        tables = self._derive_tables_from_question(task)
        metric, aggregation = self._derive_metric_aggregation(task)
        filters = self._derive_filters(task)
        group_by = self._derive_group_by(task)
        ordering = self._derive_ordering(task)
        limit = self._derive_limit(task)

        entity = None
        if group_by:
            entity = group_by[0]
        elif tables:
            entity = tables[0].replace("_", " ")

        intent = f"Answer the question: {task}"

        return QueryPlan(
            intent=intent,
            metric=metric,
            entity=entity,
            aggregation=aggregation,
            filters=filters,
            group_by=group_by,
            ordering=ordering,
            limit=limit,
            required_tables=tables,
            reasoning=f"Deterministic fallback derived from question keywords for: {task}",
        )


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
        repair_event: dict[str, Any] | None = None
        query_plan_context = self._build_query_plan_context(state.query_plan) if state.query_plan else ""

        for attempt in range(2):   # attempt 0 = initial, attempt 1 = after execution error
            prompt_ctx = schema_text if attempt == 0 else schema_text + [f"FIX PREVIOUS ERROR: {last_error}"]
            logger.info("sql_generation attempt=%d step=%s", attempt + 1, step[:80])
            payload  = self._generate_sql_payload(state.task, step, prompt_ctx, query_plan_context)
            sql      = payload.get("sql")
            reasoning = payload.get("reasoning", "")
            if sql is None:
                break

            # ── Phase 7: truncation detection ───────────────────────────────
            is_trunc, trunc_reason = is_sql_truncated(sql)
            if is_trunc:
                last_error = f"SQL truncation detected: {trunc_reason}"
                logger.warning("sql_truncated attempt=%d reason=%s", attempt + 1, trunc_reason)
                continue  # retry with truncation error in context

            # ── Step 2: AST + schema validation ─────────────────────────────
            val_errors = self._validate_sql(sql, context)
            if val_errors:
                last_error = f"Validation errors: {', '.join(val_errors)}"
                logger.warning("sql_validation_failed attempt=%d errors=%s", attempt + 1, last_error)
                continue   # retry with error in context (only 1 retry)

            # ── Step 3: semantic verification (pre-execution) ────────────────
            verifier = self._sql_tool.verifier
            if verifier:
                pre_verify = verifier.verify(
                    sql,
                    level=VerificationLevel.BALANCED,
                    query_plan=state.query_plan,
                    question=state.task,
                )
                actionable = filter_actionable_issues(pre_verify.issues)
                if actionable:
                    repaired, repair_event = self._attempt_repair(
                        sql, actionable, schema_text, step,
                        query_plan=state.query_plan, context=context,
                    )
                    state.repair_events.append(repair_event)
                    if repaired and repaired != sql:
                        logger.info("sql_repair_applied step=%s", step[:80])
                        # Re-validate repaired SQL before accepting
                        r_errors = self._validate_sql(repaired, context)
                        if not r_errors:
                            sql = repaired
                            reasoning = f"[repaired] {reasoning}"
                            repair_event["re_validated"] = True
                        else:
                            logger.warning("sql_repair_validation_failed errors=%s", r_errors)
                            repair_event["re_validated"] = False
                            repair_event["reason"] = "repaired SQL failed re-validation"

            # ── Step 4: execute ──────────────────────────────────────────────
            try:
                logger.info("sql_execute sql=%s", sql.strip()[:120])
                sql_result = await asyncio.to_thread(self._sql_tool.execute, sql)
                logger.info("sql_execute_ok rows=%d", sql_result.get("row_count", 0))
                if repair_event is not None:
                    repair_event["executed"] = True
                    repair_event["final_sql"] = sql

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
                        query_plan=state.query_plan,
                        question=state.task,
                    )
                    post_actionable = filter_actionable_issues(post_verify.issues)
                    if post_actionable:
                        post_repaired, post_event = self._attempt_repair(
                            sql, post_actionable, schema_text, step,
                            query_plan=state.query_plan, context=context,
                        )
                        state.repair_events.append(post_event)
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
                                    post_event["re_validated"] = True
                                    post_event["executed"] = True
                                    post_event["final_sql"] = sql
                                except Exception as post_exc:
                                    logger.warning("sql_post_repair_exec_failed error=%s", post_exc)
                            else:
                                post_event["re_validated"] = False
                                post_event["reason"] = "repaired SQL failed re-validation"

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
        fallback_sql = self._fallback_sql(state.task, step, state.query_plan)
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

    @staticmethod
    def _build_query_plan_context(query_plan: QueryPlan | None) -> str:
        """Format QueryPlan into a grounding block for SQL generation."""
        if not query_plan:
            return ""
        parts = [
            f"Question-specific plan: {query_plan.intent}",
        ]
        if query_plan.composite_metric:
            cm = query_plan.composite_metric
            parts.append(f"Composite Metric: {cm.name} (type: {cm.metric_type.value if hasattr(cm.metric_type, 'value') else cm.metric_type})")
            if cm.formula_template:
                parts.append(f"Formula template: {cm.formula_template}")
            if cm.numerator:
                parts.append(f"Numerator: {cm.numerator}")
            if cm.denominator:
                parts.append(f"Denominator: {cm.denominator}")
        elif query_plan.aggregation and query_plan.metric.lower() != query_plan.aggregation.lower():
            parts.append(f"Metric: {query_plan.aggregation}({query_plan.metric})")
        else:
            parts.append(f"Metric: {query_plan.metric}")

        if query_plan.entities:
            parts.append(f"Entities: {', '.join(query_plan.entities)}")
        elif query_plan.entity:
            parts.append(f"Entity: {query_plan.entity}")

        if query_plan.time_grain:
            parts.append(f"Time Grain: {query_plan.time_grain} (on column {query_plan.time_column or 'order_purchase_timestamp'})")
        if query_plan.time_range:
            parts.append(f"Time Range: {query_plan.time_range}")

        if query_plan.filters:
            parts.append(f"Filters: {', '.join(query_plan.filters)}")
        if query_plan.group_by:
            parts.append(f"Group by: {', '.join(query_plan.group_by)}")
        if query_plan.ranking_direction:
            parts.append(f"Ranking: {query_plan.ranking_metric or query_plan.metric} {query_plan.ranking_direction}")
        if query_plan.ordering:
            parts.append(f"Ordering: {query_plan.ordering}")
        if query_plan.limit:
            parts.append(f"Limit: {query_plan.limit}")
        if query_plan.result_shape:
            parts.append(f"Expected Result Shape: {query_plan.result_shape.value if hasattr(query_plan.result_shape, 'value') else query_plan.result_shape}")
        if query_plan.join_path:
            parts.append(f"Join path: {', '.join(query_plan.join_path)}")
        parts.append(f"Required tables: {', '.join(query_plan.required_tables)}")
        return "\n".join(parts)

    # ── Phase 6/8 repair helper ───────────────────────────────────────────────

    def _attempt_repair(
        self,
        sql: str,
        issues: list[Any],
        schema_text: list[str],
        step: str,
        query_plan: Any = None,
        context: list[Any] | None = None,
    ) -> tuple[str | None, dict[str, Any]]:
        """Issue ONE targeted repair call.

        First tries the verifier's own programmatic repair (regex-based GROUP BY
        or LIMIT fix) — fast, free, and deterministic.  Only falls back to an
        LLM call if programmatic repair is unavailable, produces the same SQL,
        or fails structural re-validation.

        Returns (repaired_sql_or_None, repair_event_dict).
        """
        event: dict[str, Any] = {
            "step": step,
            "attempted": True,
            "applied": False,
            "method": None,
            "categories": sorted({i.category.value for i in issues}),
            "pre_repair_sql": sql,
            "re_validated": None,
            "executed": None,
        }
        verifier = self._sql_tool.verifier

        # 1. Try programmatic repair (no LLM cost).
        if verifier:
            for issue in issues:
                candidate = verifier.generate_repair(issue, sql)
                if candidate and candidate.strip() != sql.strip():
                    # Programmatic candidates must still pass structural validation.
                    if context is not None:
                        r_errors = self._validate_sql(candidate, context)
                        if r_errors:
                            logger.warning(
                                "sql_programmatic_repair_invalid category=%s errors=%s",
                                issue.category.value, r_errors,
                            )
                            break
                    logger.info("sql_programmatic_repair category=%s", issue.category.value)
                    event.update({
                        "method": "programmatic",
                        "category": issue.category.value,
                        "applied": True,
                        "post_repair_sql": candidate,
                    })
                    return candidate, event

        # 2. LLM repair — one call, no retries.
        if not self._llm_client.enabled:
            event["reason"] = "llm_disabled"
            return None, event
        try:
            from agent_platform.llms.models import SQLOutput

            repair_user_prompt = build_repair_prompt(sql, issues, schema_text, query_plan=query_plan)
            result = self._llm_client.complete_json(
                system_prompt=REPAIR_SYSTEM_PROMPT,
                user_prompt=repair_user_prompt,
                response_model=SQLOutput,
            )
            if not isinstance(result, dict):
                event["reason"] = "non_dict_llm_response"
                return None, event
            repaired_sql = result.get("sql")
            if repaired_sql and isinstance(repaired_sql, str) and repaired_sql.strip() != sql.strip():
                logger.info("sql_llm_repair_ok step=%s", step[:80])
                event.update({
                    "method": "llm",
                    "applied": True,
                    "post_repair_sql": repaired_sql,
                })
                return repaired_sql, event
            event["method"] = "llm"
            event["reason"] = "llm_returned_no_change"
        except Exception as exc:
            logger.warning("sql_llm_repair_failed error=%s", exc)
            event["reason"] = str(exc)[:200]
        return None, event

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

    def _generate_sql_payload(self, task: str, step: str, schema_context: list[str], query_plan_context: str = "") -> dict[str, Any]:
        if self._llm_client.enabled:
            try:
                from agent_platform.llms.models import SQLOutput
                enhanced_step = step
                if query_plan_context:
                    enhanced_step = f"{query_plan_context}\n\nStep: {step}"
                result = self._llm_client.complete_json(
                    system_prompt=SQL_SYSTEM_PROMPT,
                    user_prompt=build_sql_prompt(task, enhanced_step, schema_context),
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
            "sql": self._fallback_sql(task, step, None),
            "reasoning": "Used deterministic safe SQL fallback because Groq was unavailable.",
        }

    def _fallback_sql(self, task: str, step: str, query_plan: QueryPlan | None) -> str | None:
        core_step = step.split("|")[0].strip().lower()
        lowered = f"{task} {core_step}".lower()

        if "schema" in core_step and "calculate" not in core_step:
            return "SELECT name, type FROM sqlite_master WHERE type='table' ORDER BY name;"
        
        # Use query plan fields if available for grounding
        tables = query_plan.required_tables if query_plan and query_plan.required_tables else []
        metric = query_plan.metric if query_plan else None
        aggregation = query_plan.aggregation if query_plan else None
        group_by = query_plan.group_by if query_plan and query_plan.group_by else []
        ordering = query_plan.ordering if query_plan else None
        limit = query_plan.limit if query_plan else None
        filters = query_plan.filters if query_plan and query_plan.filters else []
        
        # Regional/state analysis
        if "regional" in lowered or "state" in lowered:
            where = "WHERE o.order_status IN ('delivered', 'shipped', 'invoiced')" if "order" in lowered else ""
            group_col = "c.customer_state" if "customer" in lowered else "o.customer_state"
            return f"""
            SELECT
                {group_col} AS state,
                ROUND(SUM(oi.price), 2) AS revenue
            FROM order_items oi
            JOIN orders o ON o.order_id = oi.order_id
            JOIN customers c ON c.customer_id = o.customer_id
            {where}
            GROUP BY state
            ORDER BY revenue DESC
            LIMIT 10
            """
        
        # Revenue/growth/category
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
        
        # Trend/month/time
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
        
        # AOV
        if "aov" in lowered or "average order value" in lowered or "average order" in lowered or "average value" in lowered:
            return """
            SELECT ROUND(SUM(price) / COUNT(DISTINCT order_id), 2) AS average_order_value
            FROM order_items
            """

        # Seller
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
        
        # Repeat/loyalty
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
            
        # Cancel
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
            
        # Rating/review
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
            
        # Geolocation
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
            
        # Payment
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
        findings = [
            f"Executed query returned {r.get('row_count', 0)} rows."
            for r in sql_results if r.get("row_count", 0) > 0
        ] or ["Analysis completed with SQL execution."]
        fallback = {
            "summary": "Analysis completed with supporting SQL metrics.",
            "key_findings": findings,
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
