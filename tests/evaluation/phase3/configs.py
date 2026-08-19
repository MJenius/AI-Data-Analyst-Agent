from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from agent_platform.experiments.query_plan import QueryPlan
from agent_platform.llms.sql_generation_prompt import SYSTEM_PROMPT as SQL_SYSTEM_PROMPT
from agent_platform.llms.sql_generation_prompt import build_sql_prompt

from tests.evaluation.phase3.common import (
    check_unsafe_sql,
    execute_sql,
    parse_plan_loose,
    parse_sql_from_llm,
    extract_tables_from_sql,
)

logger = logging.getLogger("phase3_configs")


PLAN_SYSTEM_PROMPT = """You are a senior analytics query planner.
Return only valid JSON. Do not include markdown.
Given a business question and schema context, produce a structured query plan describing the single SQL query that answers the question.
Use ONLY tables and columns present in the schema context. Do not invent tables.
Rules:
- intent: one short phrase describing the analytical intent (e.g., "rank product categories by revenue", "compute total revenue", "monthly trend of order counts").
- metric: the primary metric being computed (e.g., "total revenue", "average review score", "order count").
- entity: the primary entity analyzed (e.g., "product category", "customer", "order", "seller") or null.
- aggregation: one of SUM, COUNT, AVG, MIN, MAX if the query aggregates, else null.
- filters: list of filter conditions (e.g., ["order_status = 'delivered'"]) or empty list.
- group_by: list of grouping fields (column names only) or null.
- ordering: "field ASC|DESC" or null.
- limit: integer if a LIMIT applies, else null.
- required_tables: the list of table names needed (use exact table names from the schema context).

Output schema:
{
  "intent": "...",
  "metric": "...",
  "entity": "...",
  "aggregation": "...",
  "filters": [...],
  "group_by": [...],
  "ordering": "...",
  "limit": ...,
  "required_tables": [...]
}
"""


class ProviderUnavailableError(RuntimeError):
    """Raised when the controlled LLM cannot service an experimental call."""


def build_plan_prompt(question: str, schema_context: list[str]) -> str:
    return f"""Business question:
{question}

Schema context:
{chr(10).join(schema_context)}

Produce the structured query plan for the single SQL query that answers the question.
"""


def _llm_json(client: Any, system_prompt: str, user_prompt: str) -> dict[str, Any]:
    try:
        return client.complete_json(system_prompt, user_prompt)
    except Exception as exc:
        if getattr(exc, "is_provider_failure", False):
            raise ProviderUnavailableError(str(exc)) from exc
        raise RuntimeError(f"Model/request failed: {exc}") from exc


def _response_metadata(client: Any) -> dict[str, Any]:
    metadata = getattr(client, "last_response_metadata", {})
    return dict(metadata) if isinstance(metadata, dict) else {}


class ExperimentConfig:
    """Base class for an experiment configuration."""

    id: str
    name: str

    def __init__(self, config_id: str, name: str) -> None:
        self.id = config_id
        self.name = name

    async def run(self, question: str, benchmark: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class ConfigCurrentSystem(ExperimentConfig):
    """Config 1: the production pipeline (Planner + RAG + SQL gen + exec feedback + evaluator), untouched."""

    def __init__(self, service, client: Any) -> None:
        super().__init__("config1_current_system", "Current system (planner + RAG + SQL gen + exec feedback + evaluator)")
        self._service = service
        self._client = client

    async def run(self, question: str, benchmark: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        try:
            result = await self._service.analyze(question)
            latency = time.perf_counter() - start
            sql_queries = result.get("sql_queries", [])
            gen_sql = "\n".join(sql_queries) if sql_queries else None
            return {
                "generated_sql": gen_sql,
                "all_sql": sql_queries,
                "latency_seconds": round(latency, 2),
                "status": result.get("status"),
                "verdict": result.get("verdict"),
                "confidence": result.get("confidence"),
                "error": None,
            }
        except Exception as exc:
            return {
                "generated_sql": None,
                "all_sql": [],
                "latency_seconds": round(time.perf_counter() - start, 2),
                "status": "error",
                "verdict": None,
                "confidence": None,
                "error": str(exc)[:300],
            }


class ConfigDirectSQLFullSchema(ExperimentConfig):
    """Config 2: LLM + full schema context, no RAG, no planner, no execution feedback."""

    def __init__(self, client: Any, full_schema_text: list[str]) -> None:
        super().__init__("config2_llm_full_schema", "LLM + full schema context (no RAG, no planner)")
        self._client = client
        self._full_schema_text = full_schema_text

    async def run(self, question: str, benchmark: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        try:
            payload = _llm_json(
                self._client,
                SQL_SYSTEM_PROMPT,
                build_sql_prompt(question, "Answer the business question with a single SQL query.", self._full_schema_text),
            )
            sql = parse_sql_from_llm(payload)
            latency = time.perf_counter() - start
            return {
                "generated_sql": sql,
                "raw_llm": {k: str(v)[:300] for k, v in payload.items()},
                "latency_seconds": round(latency, 2),
                "llm_calls": 1,
                "llm_response_metadata": _response_metadata(self._client),
                "error": None,
            }
        except Exception as exc:
            return {
                "generated_sql": None,
                "raw_llm": {},
                "latency_seconds": round(time.perf_counter() - start, 2),
                "llm_calls": 1,
                "provider_error": isinstance(exc, ProviderUnavailableError),
                "error": str(exc)[:300],
            }


class ConfigDirectSQLRag(ExperimentConfig):
    """Config 3: LLM + RAG retrieval, no planner, no execution feedback."""

    def __init__(self, client: Any, retriever) -> None:
        super().__init__("config3_llm_rag", "LLM + RAG (no planner)")
        self._client = client
        self._retriever = retriever

    async def run(self, question: str, benchmark: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        try:
            context = self._retriever.retrieve(question, top_k=5)
            context_text = [item.text for item in context]
            payload = _llm_json(
                self._client,
                SQL_SYSTEM_PROMPT,
                build_sql_prompt(question, "Answer the business question with a single SQL query.", context_text),
            )
            sql = parse_sql_from_llm(payload)
            latency = time.perf_counter() - start
            return {
                "generated_sql": sql,
                "retrieved_tables": [item.metadata.get("table") for item in context if item.metadata.get("kind") == "table"],
                "raw_llm": {k: str(v)[:300] for k, v in payload.items()},
                "latency_seconds": round(latency, 2),
                "llm_calls": 1,
                "llm_response_metadata": _response_metadata(self._client),
                "error": None,
            }
        except Exception as exc:
            return {
                "generated_sql": None,
                "retrieved_tables": [],
                "raw_llm": {},
                "latency_seconds": round(time.perf_counter() - start, 2),
                "llm_calls": 1,
                "provider_error": isinstance(exc, ProviderUnavailableError),
                "error": str(exc)[:300],
            }


class ConfigPlanRagSQL(ExperimentConfig):
    """Config 4: Planner (structured QueryPlan) + RAG + SQL generation, no execution feedback."""

    def __init__(self, client: Any, retriever) -> None:
        super().__init__("config4_plan_rag_sql", "Planner + RAG + SQL generation (no exec feedback)")
        self._client = client
        self._retriever = retriever

    async def run(self, question: str, benchmark: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        try:
            context = self._retriever.retrieve(question, top_k=5)
            context_text = [item.text for item in context]

            plan_payload = _llm_json(self._client, PLAN_SYSTEM_PROMPT, build_plan_prompt(question, context_text))
            plan = parse_plan_loose(plan_payload)
            plan_metadata = _response_metadata(self._client)

            plan_text = plan.model_dump_json()
            sql_payload = _llm_json(
                self._client,
                SQL_SYSTEM_PROMPT,
                build_sql_prompt(question, f"Execute the following query plan:\n{plan_text}", context_text),
            )
            sql = parse_sql_from_llm(sql_payload)
            latency = time.perf_counter() - start
            return {
                "generated_sql": sql,
                "plan": plan.model_dump(),
                "plan_raw": {k: str(v)[:200] for k, v in plan_payload.items()},
                "retrieved_tables": [item.metadata.get("table") for item in context if item.metadata.get("kind") == "table"],
                "raw_llm": {k: str(v)[:300] for k, v in sql_payload.items()},
                "latency_seconds": round(latency, 2),
                "llm_calls": 2,
                "plan_response_metadata": plan_metadata,
                "sql_response_metadata": _response_metadata(self._client),
                "error": None,
            }
        except Exception as exc:
            return {
                "generated_sql": None,
                "plan": None,
                "plan_raw": {},
                "retrieved_tables": [],
                "raw_llm": {},
                "latency_seconds": round(time.perf_counter() - start, 2),
                "llm_calls": 2,
                "provider_error": isinstance(exc, ProviderUnavailableError),
                "error": str(exc)[:300],
            }


class ConfigPlanRagSQLFeedback(ExperimentConfig):
    """Config 5: Planner (structured QueryPlan) + RAG + SQL generation + execution feedback (repair loop)."""

    def __init__(self, client: Any, retriever, max_repair_attempts: int = 2) -> None:
        super().__init__("config5_plan_rag_sql_feedback", "Planner + RAG + SQL generation + execution feedback")
        self._client = client
        self._retriever = retriever
        self._max_repair_attempts = max_repair_attempts

    def _validate(self, sql: str, context) -> list[str]:
        errors = []
        lowered = sql.lower()
        allowed_tables = set()
        for item in context:
            if item.metadata.get("kind") == "table":
                allowed_tables.add(item.metadata["table"].lower())
        table_matches = extract_tables_from_sql(sql)
        for tbl in table_matches:
            if tbl not in allowed_tables:
                errors.append(f"Table '{tbl}' is not in retrieved schema context (hallucination prevention).")
        unsafe = check_unsafe_sql(sql)
        if unsafe:
            errors.append(f"Destructive SQL keyword(s): {', '.join(unsafe)}.")
        return errors

    async def run(self, question: str, benchmark: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        llm_calls = 0
        attempts = []
        try:
            context = self._retriever.retrieve(question, top_k=5)
            context_text = [item.text for item in context]

            plan_payload = _llm_json(self._client, PLAN_SYSTEM_PROMPT, build_plan_prompt(question, context_text))
            llm_calls += 1
            plan = parse_plan_loose(plan_payload)
            plan_metadata = _response_metadata(self._client)
            plan_text = plan.model_dump_json()

            last_error = None
            sql = None
            for attempt in range(self._max_repair_attempts + 1):
                prompt_context = context_text
                if last_error:
                    prompt_context = context_text + [f"FIX PREVIOUS ERROR: {last_error}"]
                sql_payload = _llm_json(
                    self._client,
                    SQL_SYSTEM_PROMPT,
                    build_sql_prompt(question, f"Execute the following query plan:\n{plan_text}", prompt_context),
                )
                llm_calls += 1
                sql = parse_sql_from_llm(sql_payload)
                if sql is None:
                    last_error = "No SQL generated by LLM."
                    attempts.append({"attempt": attempt + 1, "sql": sql, "error": last_error})
                    continue

                validation_errors = self._validate(sql, context)
                if validation_errors:
                    last_error = f"Validation errors: {', '.join(validation_errors)}"
                    attempts.append({"attempt": attempt + 1, "sql": sql, "error": last_error})
                    continue

                exec_result = execute_sql(sql)
                if exec_result["success"]:
                    attempts.append({"attempt": attempt + 1, "sql": sql, "error": None, "rows": exec_result["row_count"]})
                    latency = time.perf_counter() - start
                    return {
                        "generated_sql": sql,
                        "plan": plan.model_dump(),
                        "plan_raw": {k: str(v)[:200] for k, v in plan_payload.items()},
                        "retrieved_tables": [item.metadata.get("table") for item in context if item.metadata.get("kind") == "table"],
                        "raw_llm": {k: str(v)[:300] for k, v in sql_payload.items()},
                        "latency_seconds": round(latency, 2),
                        "llm_calls": llm_calls,
                        "plan_response_metadata": plan_metadata,
                        "sql_response_metadata": _response_metadata(self._client),
                        "attempts": attempts,
                        "repair_succeeded": attempt > 0,
                        "error": None,
                    }
                last_error = f"Execution error: {exec_result.get('error')}"
                attempts.append({"attempt": attempt + 1, "sql": sql, "error": last_error})

            latency = time.perf_counter() - start
            return {
                "generated_sql": sql,
                "plan": plan.model_dump(),
                "plan_raw": {k: str(v)[:200] for k, v in plan_payload.items()},
                "retrieved_tables": [item.metadata.get("table") for item in context if item.metadata.get("kind") == "table"],
                "raw_llm": {k: str(v)[:300] for k, v in sql_payload.items()},
                "latency_seconds": round(latency, 2),
                "llm_calls": llm_calls,
                "plan_response_metadata": plan_metadata,
                "sql_response_metadata": _response_metadata(self._client),
                "attempts": attempts,
                "repair_succeeded": False,
                "error": last_error,
            }
        except Exception as exc:
            return {
                "generated_sql": None,
                "plan": None,
                "plan_raw": {},
                "retrieved_tables": [],
                "raw_llm": {},
                "latency_seconds": round(time.perf_counter() - start, 2),
                "llm_calls": llm_calls,
                "attempts": attempts,
                "repair_succeeded": False,
                "provider_error": isinstance(exc, ProviderUnavailableError),
                "error": str(exc)[:300],
            }


CONFIG_REGISTRY: dict[str, type[ExperimentConfig]] = {}


def build_configs(service, client: Any, retriever, full_schema_text: list[str]) -> list[ExperimentConfig]:
    return [
        ConfigCurrentSystem(service, client),
        ConfigDirectSQLFullSchema(client, full_schema_text),
        ConfigDirectSQLRag(client, retriever),
        ConfigPlanRagSQL(client, retriever),
        ConfigPlanRagSQLFeedback(client, retriever),
    ]
