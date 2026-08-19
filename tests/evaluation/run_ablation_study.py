"""4-Way Ablation Study Harness for Phase 10.

Scientifically measures component contributions across the 100 benchmark queries:
- Config A: RAG Only (Retriever + Fallback Plan, No Verifier, No Evaluator)
- Config B: RAG + Planner (Retriever + LLM Planner + PlanValidator, No Verifier, No Evaluator)
- Config C: RAG + Planner + Verifier (Retriever + LLM Planner + SQLSemanticVerifier + Auto-Repairs, No Evaluator)
- Config D: Full System (Retriever + LLM Planner + Verifier + Evaluator Synthesis)

Features:
- Configurable concurrency (--workers)
- Resumable checkpoints per configuration
- Direct execution against SQLite database
- Comprehensive comparison metrics (exact match, equivalent match, SQL success, table accuracy, latency)
- Auto-generates Markdown & JSON comparison reports
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import logging
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
load_dotenv()

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_platform.analytics.agents import (
    AnalyticsEvaluatorAgent,
    AnalyticsExecutorAgent,
    AnalyticsPlannerAgent,
)
from agent_platform.analytics.service import AnalyticsAgentService, RunStore
from agent_platform.llms.client import LLMClient, get_llm_client
from agent_platform.observability.traces import AnalyticsObserver
from agent_platform.rag.ingestion.schema_context import SchemaContextBuilder
from agent_platform.rag.retriever import SchemaRetriever
from agent_platform.tools.plan_validator import PlanValidator
from agent_platform.tools.sql_tool import SQLTool
from agent_platform.tools.sql_verifier import SQLSemanticVerifier

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("ablation_study")

DB_PATH = ROOT / "data" / "analytics.db"
BENCHMARK_PATH = ROOT / "tests" / "evaluation" / "benchmark_dataset_v2.json"
KNOWN_TABLES = {
    "customers", "geolocation", "order_items", "order_payments", "order_reviews",
    "orders", "products", "sellers", "product_category_name_translation",
}


def load_benchmark(path: Path = BENCHMARK_PATH) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def run_query_in_db(sql: str, db_path: Path) -> dict[str, Any]:
    if not sql or not sql.strip():
        return {"success": False, "error": "empty sql", "rows": [], "row_count": 0}
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(sql)
        cols = [d[0] for d in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
        values = [{c: (round(v, 4) if isinstance(v, float) else v) for c, v in zip(cols, row)} for row in rows]
        return {"success": True, "rows": values, "row_count": len(values), "columns": cols}
    except Exception as exc:
        return {"success": False, "error": str(exc), "rows": [], "row_count": 0}
    finally:
        conn.close()


from agent_platform.experiments.compare_results import compare_results  # noqa: E402


def extract_tables_from_sql(sql: str | None) -> list[str]:
    if not sql:
        return []
    cleaned = re.sub(r"\s+", " ", sql.lower())
    return [t for t in KNOWN_TABLES if re.search(rf"\b{t}\b", cleaned)]


class DummyFallbackPlannerAgent:
    """Fallback planner for RAG-only baseline: generates minimal single-table default plan."""
    def __init__(self, retriever: SchemaRetriever) -> None:
        self._retriever = retriever

    async def plan(self, task: str) -> Any:
        contexts = self._retriever.retrieve_grounded(task, max_tables=3)
        tables = [c.metadata.get("table") for c in contexts if c.metadata.get("table")]
        from agent_platform.experiments.query_plan import QueryPlan
        return QueryPlan(
            intent=task,
            required_tables=tables[:2] if tables else ["orders"],
            metric="count",
            reasoning="Fallback heuristic plan without LLM planner",
        )


def build_service_for_config(
    config_name: str,
    db_path: Path,
    llm_client: LLMClient,
    enable_evaluator: bool = False,
) -> AnalyticsAgentService:
    connection = sqlite3.connect(db_path)
    try:
        schema_documents = SchemaContextBuilder(connection).build()
    finally:
        connection.close()

    retriever = SchemaRetriever.from_documents(schema_documents)
    observer = AnalyticsObserver()

    if config_name == "rag_only":
        # Config A: RAG Only (No Planner LLM, No Verifier, No Evaluator)
        planner = DummyFallbackPlannerAgent(retriever)
        sql_tool = SQLTool(database_url=f"sqlite:///{db_path}", enable_semantic_verification=False)
        executor = AnalyticsExecutorAgent(retriever, sql_tool, llm_client)
    elif config_name == "rag_planner":
        # Config B: RAG + Planner (LLM Planner, No Verifier, No Evaluator)
        planner = AnalyticsPlannerAgent(retriever, llm_client)
        sql_tool = SQLTool(database_url=f"sqlite:///{db_path}", enable_semantic_verification=False)
        executor = AnalyticsExecutorAgent(retriever, sql_tool, llm_client)
    elif config_name == "rag_planner_verifier":
        # Config C: RAG + Planner + Verifier (LLM Planner + SQLSemanticVerifier, No Evaluator)
        planner = AnalyticsPlannerAgent(retriever, llm_client)
        sql_tool = SQLTool(database_url=f"sqlite:///{db_path}", enable_semantic_verification=True)
        executor = AnalyticsExecutorAgent(retriever, sql_tool, llm_client)
    elif config_name == "full_system":
        # Config D: Full System (Planner + Verifier + Evaluator)
        planner = AnalyticsPlannerAgent(retriever, llm_client)
        sql_tool = SQLTool(database_url=f"sqlite:///{db_path}", enable_semantic_verification=True)
        executor = AnalyticsExecutorAgent(retriever, sql_tool, llm_client)
        enable_evaluator = True
    else:
        raise ValueError(f"Unknown configuration: {config_name}")

    if not enable_evaluator:
        class FastAblationEvaluator:
            async def evaluate(self, state: Any) -> dict[str, Any]:
                return {
                    "summary": f"Ablation mode ({config_name})",
                    "key_findings": [],
                    "confidence": 1.0,
                    "validated": True,
                    "verdict": "accurate",
                }
        evaluator = FastAblationEvaluator()
    else:
        evaluator = AnalyticsEvaluatorAgent(llm_client)

    return AnalyticsAgentService(
        planner=planner,
        executor=executor,
        evaluator=evaluator,
        observer=observer,
        run_store=RunStore(),
    )


async def run_single_ablation_query(
    idx: int,
    item: dict[str, Any],
    service: AnalyticsAgentService,
    db_path: Path,
    config_name: str = "unknown",
) -> dict[str, Any]:
    qid = f"q{idx:03d}"
    question = item.get("question", "")
    expected_obj = item.get("expected_result", {})
    expected_result = expected_obj.get("values", []) if isinstance(expected_obj, dict) else (expected_obj if isinstance(expected_obj, list) else [])
    expected_tables = set(item.get("expected_tables", []))

    started = time.perf_counter()
    error = None
    actual_sql = None
    actual_result: list[dict] = []
    sql_success = False
    response = None

    try:
        response = await service.analyze(question)
        sql_queries = response.get("sql_queries", [])
        actual_sql = sql_queries[-1] if sql_queries else None
    except Exception as exc:
        error = str(exc)

    elapsed = round(time.perf_counter() - started, 3)

    if actual_sql:
        db_exec = run_query_in_db(actual_sql, db_path)
        sql_success = db_exec["success"]
        if sql_success:
            actual_result = db_exec["rows"]
        else:
            error = db_exec.get("error", "execution_failed")

    comp = compare_results(actual_result, expected_result)
    queried_tables = extract_tables_from_sql(actual_sql)
    correct_tables = [t for t in expected_tables if t in queried_tables]
    table_acc = (len(correct_tables) / len(expected_tables)) if expected_tables else 1.0

    # Provenance fields — derived from actual execution, never invented.
    repair_events = response.get("repair_events", []) if response else []
    verifier_triggered = len(repair_events) > 0 if response else False
    repair_used = any(e.get("applied", False) for e in repair_events) if repair_events else False
    fallback_used = response.get("fallback_used", False) if response else False

    return {
        "query_id": qid,
        "question": question,
        "category": item.get("category", "unknown"),
        "difficulty": item.get("difficulty", "unknown"),
        "expected_tables": list(expected_tables),
        "actual_sql": actual_sql,
        "sql_execution_success": sql_success,
        "exact_match": comp["exact_match"],
        "equivalent_match": comp["equivalent_match"],
        "table_accuracy": table_acc,
        "latency_seconds": elapsed,
        "error": error,
        # Per-query provenance
        "configuration": config_name,
        "verifier_triggered": verifier_triggered,
        "repair_used": repair_used,
        "fallback_used": fallback_used,
        "final_validity": "valid" if sql_success and comp["equivalent_match"] else ("sql_error" if not sql_success else "semantic_mismatch"),
    }


async def run_ablation_config(
    config_name: str,
    benchmark: list[dict[str, Any]],
    db_path: Path,
    output_dir: Path,
    workers: int = 4,
    enable_evaluator: bool = False,
) -> dict[str, Any]:
    config_dir = output_dir / config_name
    config_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_file = config_dir / "checkpoint.json"

    completed: dict[str, dict[str, Any]] = {}
    if checkpoint_file.exists():
        try:
            with open(checkpoint_file, "r", encoding="utf-8") as f:
                completed = json.load(f)
            logger.info("[%s] Resumed from checkpoint: %d/%d queries completed", config_name, len(completed), len(benchmark))
        except Exception:
            completed = {}

    llm_client = get_llm_client()
    service = build_service_for_config(config_name, db_path, llm_client, enable_evaluator=enable_evaluator)

    semaphore = asyncio.Semaphore(workers)

    async def _worker(idx: int, item: dict[str, Any]):
        qid = f"q{idx:03d}"
        if qid in completed:
            return completed[qid]
        async with semaphore:
            try:
                res = await asyncio.wait_for(run_single_ablation_query(idx, item, service, db_path, config_name=config_name), timeout=240.0)
            except Exception as exc:
                logger.error("[%s] %s failed with exception/timeout: %s", config_name, qid, exc)
                res = {
                    "query_id": qid,
                    "question": item.get("question", ""),
                    "category": item.get("category", "unknown"),
                    "difficulty": item.get("difficulty", "unknown"),
                    "expected_tables": item.get("expected_tables", []),
                    "actual_sql": None,
                    "sql_execution_success": False,
                    "exact_match": False,
                    "equivalent_match": False,
                    "table_accuracy": 0.0,
                    "latency_seconds": 240.0,
                    "error": str(exc),
                    "configuration": config_name,
                    "verifier_triggered": False,
                    "repair_used": False,
                    "fallback_used": False,
                    "final_validity": "timeout_or_error",
                }
            completed[qid] = res
            with open(checkpoint_file, "w", encoding="utf-8") as f:
                json.dump(completed, f, indent=2)
            logger.info("[%s] %s done (equiv=%s, sql=%s, time=%.2fs)", config_name, qid, res["equivalent_match"], res["sql_execution_success"], res["latency_seconds"])
            return res

    tasks = [_worker(i, item) for i, item in enumerate(benchmark)]
    results = await asyncio.gather(*tasks)

    total = len(results)
    equiv_matches = sum(1 for r in results if r["equivalent_match"])
    exact_matches = sum(1 for r in results if r["exact_match"])
    sql_successes = sum(1 for r in results if r["sql_execution_success"])
    avg_table_acc = sum(r["table_accuracy"] for r in results) / total if total else 0.0
    avg_latency = sum(r["latency_seconds"] for r in results) / total if total else 0.0

    summary = {
        "config_name": config_name,
        "total_queries": total,
        "equivalent_match_rate": round(equiv_matches / total, 4) if total else 0.0,
        "exact_match_rate": round(exact_matches / total, 4) if total else 0.0,
        "sql_execution_success_rate": round(sql_successes / total, 4) if total else 0.0,
        "average_table_accuracy": round(avg_table_acc, 4),
        "average_latency_seconds": round(avg_latency, 2),
        "results": results,
    }

    with open(config_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    return summary


def generate_ablation_report(summaries: list[dict[str, Any]], output_path: Path) -> str:
    md = "# Phase 10: 4-Way Ablation Study Report\n\n"
    md += f"Generated: {datetime.datetime.now().isoformat()}\n\n"
    md += "This ablation isolates component contributions across the frozen 100-query benchmark dataset.\n\n"
    md += "## Summary Comparison Table\n\n"
    md += "| Configuration | Equivalent Match | Exact Match | SQL Success | Table Accuracy | Mean Latency |\n"
    md += "| :--- | :---: | :---: | :---: | :---: | :---: |\n"

    for s in summaries:
        name = s["config_name"].replace("_", " ").title()
        eq = f"{s['equivalent_match_rate'] * 100:.1f}%"
        ex = f"{s['exact_match_rate'] * 100:.1f}%"
        sql = f"{s['sql_execution_success_rate'] * 100:.1f}%"
        tbl = f"{s['average_table_accuracy'] * 100:.1f}%"
        lat = f"{s['average_latency_seconds']:.2f}s"
        md += f"| **{name}** | **{eq}** | {ex} | {sql} | {tbl} | {lat} |\n"

    md += "\n## Key Findings & Component Impact\n\n"
    if len(summaries) >= 2:
        rag_eq = next((s["equivalent_match_rate"] for s in summaries if s["config_name"] == "rag_only"), 0.0)
        plan_eq = next((s["equivalent_match_rate"] for s in summaries if s["config_name"] == "rag_planner"), 0.0)
        ver_eq = next((s["equivalent_match_rate"] for s in summaries if s["config_name"] == "rag_planner_verifier"), 0.0)
        full_eq = next((s["equivalent_match_rate"] for s in summaries if s["config_name"] == "full_system"), 0.0)

        plan_gain = (plan_eq - rag_eq) * 100
        ver_gain = (ver_eq - plan_eq) * 100
        eval_gain = (full_eq - ver_eq) * 100

        md += f"1. **Planner Impact (Config B vs A)**: `+{plan_gain:.1f}%` equivalent match improvement.\n"
        md += f"2. **Verifier Impact (Config C vs B)**: `+{ver_gain:.1f}%` equivalent match improvement.\n"
        if "full_system" in [s["config_name"] for s in summaries]:
            md += f"3. **Evaluator Impact (Config D vs C)**: `+{eval_gain:.1f}%` equivalent match change.\n"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(md)

    return md


async def main():
    parser = argparse.ArgumentParser(description="Run 4-way ablation study")
    parser.add_argument("--configs", nargs="+", default=["rag_only", "rag_planner", "rag_planner_verifier", "full_system"], help="Configurations to evaluate")
    parser.add_argument("--workers", type=int, default=4, help="Concurrent workers per configuration")
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "phase10" / "ablation", help="Output directory")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of benchmark queries")
    args = parser.parse_args()

    benchmark = load_benchmark()
    if args.limit:
        benchmark = benchmark[:args.limit]

    summaries = []
    for cfg in args.configs:
        logger.info("Starting ablation configuration: %s", cfg)
        s = await run_ablation_config(cfg, benchmark, DB_PATH, args.output, workers=args.workers)
        summaries.append(s)

    report_path = args.output / "ablation_report.md"
    generate_ablation_report(summaries, report_path)
    logger.info("Ablation study completed. Report written to %s", report_path)


if __name__ == "__main__":
    asyncio.run(main())
