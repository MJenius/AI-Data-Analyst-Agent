from __future__ import annotations

import time
from typing import Any, Callable

from agent_platform.llms.sql_generation_prompt import SYSTEM_PROMPT as SQL_SYSTEM_PROMPT
from agent_platform.llms.sql_generation_prompt import build_sql_prompt
from agent_platform.tools.sql_tool import SQLValidationError, SQLValidator
from tests.evaluation.phase3.common import parse_plan_loose, parse_sql_from_llm
from tests.evaluation.phase3.configs import (
    PLAN_SYSTEM_PROMPT,
    ProviderUnavailableError,
    _llm_json,
    _response_metadata,
    build_plan_prompt,
)


class Phase4Config:
    def __init__(
        self,
        config_id: str,
        name: str,
        client: Any,
        validator: SQLValidator,
        retrieve: Callable[[str], list[Any]],
        use_plan: bool = False,
    ) -> None:
        self.id = config_id
        self.name = name
        self._client = client
        self._validator = validator
        self._retrieve = retrieve
        self._use_plan = use_plan

    async def run(self, question: str, benchmark: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        llm_calls = 0
        context = []
        plan = None
        try:
            context = self._retrieve(question)
            context_text = [item.text for item in context]
            step = "Answer the business question with a single SQL query."
            plan_metadata = None
            if self._use_plan:
                plan_payload = _llm_json(
                    self._client,
                    PLAN_SYSTEM_PROMPT,
                    build_plan_prompt(question, context_text),
                )
                llm_calls += 1
                plan = parse_plan_loose(plan_payload)
                plan_metadata = _response_metadata(self._client)
                step = f"Execute this diagnostic QueryPlan exactly where it agrees with schema:\n{plan.model_dump_json()}"

            payload = _llm_json(
                self._client,
                SQL_SYSTEM_PROMPT,
                build_sql_prompt(question, step, context_text),
            )
            llm_calls += 1
            sql = parse_sql_from_llm(payload)
            validation_errors = self._validation_errors(sql, context)
            result = {
                "generated_sql": sql,
                "pre_execution_errors": validation_errors,
                "retrieved_tables": sorted(self._context_tables(context)),
                "retrieved_context_ids": [item.id for item in context],
                "raw_llm": {key: str(value)[:500] for key, value in payload.items()},
                "grounding": payload.get("grounding") if isinstance(payload, dict) else None,
                "latency_seconds": round(time.perf_counter() - started, 2),
                "llm_calls": llm_calls,
                "sql_response_metadata": _response_metadata(self._client),
                "error": None,
            }
            if plan is not None:
                result.update({"plan": plan.model_dump(), "plan_response_metadata": plan_metadata})
            return result
        except Exception as exc:
            return {
                "generated_sql": None,
                "pre_execution_errors": ["malformed_sql: no SQL generated"],
                "retrieved_tables": sorted(self._context_tables(context)),
                "retrieved_context_ids": [item.id for item in context],
                "plan": plan.model_dump() if plan is not None else None,
                "latency_seconds": round(time.perf_counter() - started, 2),
                "llm_calls": llm_calls,
                "provider_error": isinstance(exc, ProviderUnavailableError),
                "error": str(exc)[:500],
            }

    def _validation_errors(self, sql: str | None, context: list[Any]) -> list[str]:
        if not sql:
            return ["malformed_sql: no SQL generated"]
        try:
            self._validator.validate(sql, self._context_tables(context))
            return []
        except SQLValidationError as exc:
            return exc.errors

    @staticmethod
    def _context_tables(context: list[Any]) -> set[str]:
        tables = set()
        for item in context:
            metadata = item.metadata
            if metadata.get("table"):
                tables.add(metadata["table"])
            for key in ("from_table", "to_table"):
                if metadata.get(key):
                    tables.add(metadata[key])
            tables.update(table for table in metadata.get("tables", "").split(",") if table)
        return tables


def build_configs(client: Any, validator: SQLValidator, retriever) -> list[Phase4Config]:
    full_context = retriever.full_context()
    return [
        Phase4Config(
            "phase4_full_schema",
            "Full schema context",
            client,
            validator,
            lambda _question: full_context,
        ),
        Phase4Config(
            "phase4_current_top5",
            "Current top-5 schema RAG",
            client,
            validator,
            lambda question: retriever.retrieve(question, top_k=5),
        ),
        Phase4Config(
            "phase4_improved_rag",
            "Relationship-aware grounded schema RAG",
            client,
            validator,
            retriever.retrieve_grounded,
        ),
        Phase4Config(
            "phase4_plan_improved_rag",
            "Structured QueryPlan + relationship-aware grounded schema RAG",
            client,
            validator,
            retriever.retrieve_grounded,
            use_plan=True,
        ),
    ]
