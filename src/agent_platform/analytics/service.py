from __future__ import annotations

import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any

from agent_platform.analytics.agents import (
    AnalyticsEvaluatorAgent,
    AnalyticsExecutorAgent,
    AnalyticsPlannerAgent,
)
from agent_platform.analytics.report import AnalyticsReportBuilder
from agent_platform.llms.groq_client import GroqClient
from agent_platform.observability.traces import AnalyticsObserver, JsonlTraceStore
from agent_platform.orchestration.loop import ExecutionLoop
from agent_platform.rag.ingestion.schema_context import SchemaContextBuilder
from agent_platform.rag.retriever import SchemaRetriever
from agent_platform.tools.sql_tool import SQLTool


class RunStore:
    """In-memory run store for API lookups; replace with PostgreSQL repository later."""

    def __init__(self) -> None:
        self._runs: dict[str, dict[str, Any]] = {}

    def save(self, run: dict[str, Any]) -> None:
        self._runs[run["run_id"]] = run

    def get(self, run_id: str) -> dict[str, Any] | None:
        return self._runs.get(run_id)


class AnalyticsAgentService:
    """Coordinates the full AI Data Analyst flow for one business question."""

    def __init__(
        self,
        planner: AnalyticsPlannerAgent,
        executor: AnalyticsExecutorAgent,
        evaluator: AnalyticsEvaluatorAgent,
        observer: AnalyticsObserver,
        run_store: RunStore | None = None,
    ) -> None:
        self._observer = observer
        self._run_store = run_store or RunStore()
        self._loop = ExecutionLoop(
            planner=planner,
            step_executor=executor,
            evaluator=evaluator,
            observer=observer,
        )
        self._report_builder = AnalyticsReportBuilder()

    @classmethod
    def from_sqlite(
        cls,
        database_path: str | Path,
        trace_path: str | Path | None = None,
        run_store: RunStore | None = None,
        llm_client: GroqClient | None = None,
    ) -> "AnalyticsAgentService":
        connection = sqlite3.connect(database_path)
        try:
            schema_documents = SchemaContextBuilder(connection).build()
        finally:
            connection.close()
        retriever = SchemaRetriever.from_documents(schema_documents)
        sql_tool = SQLTool(database_url=f"sqlite:///{Path(database_path)}")
        observer = AnalyticsObserver(JsonlTraceStore(trace_path) if trace_path else None)
        shared_llm_client = llm_client or GroqClient()
        return cls(
            planner=AnalyticsPlannerAgent(retriever, shared_llm_client),
            executor=AnalyticsExecutorAgent(retriever, sql_tool, shared_llm_client),
            evaluator=AnalyticsEvaluatorAgent(shared_llm_client),
            observer=observer,
            run_store=run_store,
        )

    async def analyze(self, question: str) -> dict[str, Any]:
        state = await self._loop.run(question)
        report = self._report_builder.build(state)
        
        # New structured response format
        result = {
            "summary": report["summary"],
            "key_findings": report["key_findings"],
            "sql_queries": report["sql_queries"],
            "confidence": report["confidence"],
            "verdict": state.evaluation.get("verdict", "uncertain") if state.evaluation else "uncertain",
            "steps": report["execution_trace"]["steps"],
            # Keep metadata for internal use if needed, but the primary response is above
            "run_id": state.run_id,
            "status": state.status.value,
        }
        
        # Save full state to store for retrieval if needed
        full_run_data = {**result, "state": asdict(state)}
        self._run_store.save(full_run_data)
        
        return result

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        return self._run_store.get(run_id)
