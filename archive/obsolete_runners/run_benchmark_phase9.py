"""Phase 9 Concurrent and Resumable Benchmark Runner.

Features:
- Configurable bounded concurrency (--workers 4, --workers 8, etc.)
- Resumability: saves checkpoint after every query, continues seamlessly on resume
- Programmatic correctness & equivalence without LLM evaluator
- Semantic equivalence & multi-tier result metrics
- Detailed latency, token usage, repair metrics, failure breakdown
- Plan alignment auditing
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

from agent_platform.analytics.service import AnalyticsAgentService
from agent_platform.llms.client import get_llm_client
from agent_platform.llms.repair_prompt import filter_actionable_issues
from agent_platform.tools.sql_verifier import (
    SQLSemanticVerifier,
    VerificationCategory,
    VerificationLevel,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

DB_PATH = ROOT / "data" / "analytics.db"
BENCHMARK_PATH = ROOT / "tests" / "evaluation" / "benchmark_dataset_v2.json"

KNOWN_TABLES = {
    "customers", "geolocation", "order_items", "order_payments", "order_reviews",
    "orders", "products", "sellers", "product_category_name_translation",
}

PLAN_CATS = {
    "join_path_mismatch",
    "metric_mismatch",
    "filter_mismatch",
    "time_grain_mismatch",
    "group_by_grain_mismatch",
    "ranking_mismatch",
    "entity_mismatch",
    "result_shape_mismatch",
}


def load_benchmark(dataset_path: Path | None = None) -> list[dict[str, Any]]:
    path = dataset_path or BENCHMARK_PATH
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def normalize_sql(sql: str | None) -> str:
    if not sql:
        return ""
    sql = sql.lower()
    sql = re.sub(r"\s+", " ", sql)
    sql = re.sub(r"`", "", sql)
    sql = sql.strip()
    if sql.endswith(";"):
        sql = sql[:-1]
    return sql.strip()


def extract_tables_from_sql(sql: str | None) -> list[str]:
    if not sql:
        return []
    cleaned = re.sub(r"\s+", " ", sql.lower())
    return [t for t in KNOWN_TABLES if re.search(rf"\b{t}\b", cleaned)]


def check_hallucinated_schema(sql: str | None) -> list[str]:
    if not sql:
        return []
    cleaned = re.sub(r"\s+", " ", sql.lower())
    found = []
    table_matches = re.findall(r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)", cleaned)
    for tbl in table_matches:
        if tbl not in KNOWN_TABLES and tbl not in {"sqlite_master", "sqlite_schema"}:
            found.append(tbl)
    return found


def compare_results_extended(actual_rows: list[dict], expected_rows: list[dict], query_type: str = "unknown") -> dict[str, Any]:
    """Extended comparison: exact match, value/result equivalence, shape match."""
    if not actual_rows and not expected_rows:
        return {
            "exact_match": True,
            "equivalent_match": True,
            "row_count_match": True,
            "value_match": True,
            "shape_match": True,
            "differences": [],
        }
    if not actual_rows or not expected_rows:
        return {
            "exact_match": False,
            "equivalent_match": False,
            "row_count_match": False,
            "value_match": False,
            "shape_match": False,
            "differences": ["One result set is empty while the other is not"],
        }

    row_count_match = len(actual_rows) == len(expected_rows)
    differences = []

    # 1. Exact match (keys and values identical)
    exact_match = (actual_rows == expected_rows)

    # 2. Value equivalence (ignore column alias names, compare row-by-row tuples of values)
    equivalent = True
    if len(actual_rows) != len(expected_rows):
        equivalent = False
        differences.append(f"Row count mismatch: {len(actual_rows)} != {len(expected_rows)}")
    else:
        for i, (a_row, e_row) in enumerate(zip(actual_rows, expected_rows)):
            a_vals = [round(v, 2) if isinstance(v, (int, float)) else str(v).strip().lower() for v in a_row.values()]
            e_vals = [round(v, 2) if isinstance(v, (int, float)) else str(v).strip().lower() for v in e_row.values()]
            if sorted(a_vals, key=str) != sorted(e_vals, key=str):
                equivalent = False
                differences.append(f"Row {i}: values {a_vals} != {e_vals}")

    shape_match = (len(actual_rows) == len(expected_rows)) and (len(actual_rows[0].keys()) == len(expected_rows[0].keys()))

    return {
        "exact_match": exact_match,
        "equivalent_match": equivalent or exact_match,
        "value_match": equivalent or exact_match,
        "row_count_match": row_count_match,
        "shape_match": shape_match,
        "differences": differences[:5],
    }


def classify_failure(result: dict[str, Any]) -> str:
    if result.get("error"):
        error = result["error"].lower()
        if "truncat" in error:
            return "truncation"
        if "syntax" in error:
            return "syntax"
        if "no such column" in error or "no such table" in error:
            return "schema retrieval"
        if "ambiguous" in error:
            return "column hallucination"
        return "execution"

    sql = result.get("actual_sql") or ""
    if not sql.strip():
        return "SQL generation"

    if result.get("hallucinated_tables"):
        return "column hallucination"

    verifier_issues = result.get("verifier_issues", [])
    for issue in verifier_issues:
        cat = issue.get("category", "")
        if cat in PLAN_CATS:
            return cat
        if cat in {"group_by_mismatch", "aggregation_grain", "join_fan_out", "duplicate_detection"}:
            return cat

    if not result.get("table_match", True):
        return "schema retrieval"

    return "SQL generation"


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


async def run_single_benchmark_query(
    query_idx: int,
    query_item: dict[str, Any],
    service: AnalyticsAgentService,
    db_path: Path,
    verifier: SQLSemanticVerifier | None = None,
) -> dict[str, Any]:
    query_id = f"q{query_idx:03d}"
    question = query_item.get("question", "")

    expected_obj = query_item.get("expected_result", {})
    if isinstance(expected_obj, dict):
        expected_result = expected_obj.get("values", [])
    else:
        expected_result = expected_obj if isinstance(expected_obj, list) else []

    expected_tables = set(query_item.get("expected_tables", []))
    expected_sql = query_item.get("expected_sql", "")
    query_type = query_item.get("query_type", "unknown")
    difficulty = query_item.get("difficulty", "unknown")
    domain = query_item.get("domain", query_item.get("category", "unknown"))

    started = time.perf_counter()
    error = None
    response = None
    actual_sql = None
    actual_result: list[dict] = []
    sql_execution_success = False

    try:
        response = await service.analyze(question)
        sql_queries = response.get("sql_queries", [])
        actual_sql = sql_queries[-1] if sql_queries else None
    except Exception as exc:
        error = str(exc)
        logger.error(f"Error processing {query_id}: {exc}")

    elapsed = round(time.perf_counter() - started, 3)

    if actual_sql:
        db_exec = run_query_in_db(actual_sql, db_path)
        sql_execution_success = db_exec["success"]
        if sql_execution_success:
            actual_result = db_exec["rows"]
        else:
            error = db_exec["error"]

    actual_tables = extract_tables_from_sql(actual_sql)
    hallucinated_tables = check_hallucinated_schema(actual_sql)

    # Table metrics
    table_match = (set(actual_tables) == expected_tables) if actual_tables else False
    intersection = set(actual_tables) & expected_tables
    table_precision = len(intersection) / len(actual_tables) if actual_tables else 0.0
    table_recall = len(intersection) / len(expected_tables) if expected_tables else 0.0

    # Extended correctness comparisons
    cmp_res = compare_results_extended(actual_result, expected_result, query_type)
    result_correct = cmp_res["exact_match"] or cmp_res["equivalent_match"]

    # Plan alignment checks
    query_plan_dict = response.get("query_plan") if response else None
    verifier_issues = []
    detected_plan_mismatch = False
    if verifier and actual_sql:
        v_res = verifier.verify(
            actual_sql,
            level=VerificationLevel.BALANCED,
            query_plan=query_plan_dict,
            question=question,
        )
        verifier_issues = [{"category": i.category.value, "severity": i.severity, "message": i.message} for i in v_res.issues]
        actionable = filter_actionable_issues(v_res.issues)
        detected_plan_mismatch = any(i.category.value in PLAN_CATS for i in actionable)

    # Repair info
    repair_events = response.get("repair_events", []) if response else []
    repair_attempted = any(e.get("attempted") for e in repair_events)
    repair_applied = any(e.get("applied") for e in repair_events)
    repair_methods = [e.get("method") for e in repair_events if e.get("method")]
    repair_categories = [e.get("category") for e in repair_events if e.get("category")]

    result_data = {
        "query_id": query_id,
        "question": question,
        "domain": domain,
        "query_type": query_type,
        "difficulty": difficulty,
        "actual_sql": actual_sql,
        "expected_sql": expected_sql,
        "expected_tables": sorted(list(expected_tables)),
        "actual_tables": actual_tables,
        "table_precision": round(table_precision, 4),
        "table_recall": round(table_recall, 4),
        "table_match": table_match,
        "result_correct": result_correct,
        "result_exact_match": cmp_res["exact_match"],
        "result_equivalent_match": cmp_res["equivalent_match"],
        "result_shape_match": cmp_res["shape_match"],
        "row_count_match": cmp_res["row_count_match"],
        "expected_row_count": len(expected_result),
        "actual_row_count": len(actual_result),
        "sql_execution_success": sql_execution_success,
        "plan_available": bool(query_plan_dict),
        "query_plan": query_plan_dict,
        "verifier_issues": verifier_issues,
        "detected_plan_mismatch": detected_plan_mismatch,
        "repair_attempted": repair_attempted,
        "repair_applied": repair_applied,
        "repair_events": repair_events,
        "repair_methods": repair_methods,
        "repair_categories": repair_categories,
        "hallucinated_tables": hallucinated_tables,
        "elapsed_seconds": elapsed,
        "error": error,
    }
    result_data["failure_cause"] = classify_failure(result_data)
    return result_data


async def run_benchmark_concurrent(
    dataset_path: Path,
    out_dir: Path,
    concurrency: int = 5,
    db_path: Path = DB_PATH,
    limit: int | None = None,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    dataset = load_benchmark(dataset_path)
    if limit is not None:
        dataset = dataset[:limit]

    checkpoint_file = out_dir / "checkpoint_raw_results.json"
    results_map: dict[str, dict[str, Any]] = {}

    # Load existing checkpoint if present for resumability
    if checkpoint_file.exists():
        try:
            with open(checkpoint_file, encoding="utf-8") as f:
                cached_list = json.load(f)
                for item in cached_list:
                    results_map[item["query_id"]] = item
            logger.info(f"Resuming benchmark: loaded {len(results_map)} completed queries from checkpoint.")
        except Exception as exc:
            logger.warning(f"Could not load checkpoint: {exc}")

    service = AnalyticsAgentService.from_sqlite(database_path=db_path, enable_evaluator=False)
    verifier = SQLSemanticVerifier(str(db_path))

    semaphore = asyncio.Semaphore(concurrency)
    write_lock = asyncio.Lock()
    started_benchmark = datetime.datetime.now()

    async def worker(idx: int, q_item: dict[str, Any]):
        qid = f"q{idx:03d}"
        if qid in results_map:
            return  # Already completed

        async with semaphore:
            logger.info(f"[{idx+1}/{len(dataset)}] Running {qid}: {q_item['question'][:60]}...")
            res = await run_single_benchmark_query(idx, q_item, service, db_path, verifier)
            async with write_lock:
                results_map[qid] = res
                # Flush checkpoint to disk
                ordered = [results_map[f"q{i:03d}"] for i in range(len(dataset)) if f"q{i:03d}" in results_map]
                with open(checkpoint_file, "w", encoding="utf-8") as f:
                    json.dump(ordered, f, indent=2, default=str)

    await asyncio.gather(*(worker(i, item) for i, item in enumerate(dataset)))

    final_results = [results_map[f"q{i:03d}"] for i in range(len(dataset)) if f"q{i:03d}" in results_map]
    total = len(final_results)
    total_elapsed = (datetime.datetime.now() - started_benchmark).total_seconds()

    correct_count = sum(1 for r in final_results if r["result_correct"])
    exact_count = sum(1 for r in final_results if r["result_exact_match"])
    equiv_count = sum(1 for r in final_results if r["result_equivalent_match"])
    exec_success_count = sum(1 for r in final_results if r["sql_execution_success"])
    table_exact_count = sum(1 for r in final_results if r["table_match"])
    mean_precision = sum(r["table_precision"] for r in final_results) / total if total else 0.0
    mean_recall = sum(r["table_recall"] for r in final_results) / total if total else 0.0
    latencies = [r["elapsed_seconds"] for r in final_results]
    latencies.sort()
    mean_latency = sum(latencies) / total if total else 0.0
    p50_latency = latencies[int(total * 0.50)] if total else 0.0
    p95_latency = latencies[min(int(total * 0.95), total - 1)] if total else 0.0

    summary = {
        "timestamp": datetime.datetime.now().isoformat(),
        "total_queries": total,
        "concurrency": concurrency,
        "total_elapsed_seconds": round(total_elapsed, 2),
        "result_correctness": round(correct_count / total, 4) if total else 0.0,
        "exact_match_rate": round(exact_count / total, 4) if total else 0.0,
        "equivalent_match_rate": round(equiv_count / total, 4) if total else 0.0,
        "sql_execution_success_rate": round(exec_success_count / total, 4) if total else 0.0,
        "table_accuracy": round(table_exact_count / total, 4) if total else 0.0,
        "table_precision": round(mean_precision, 4),
        "table_recall": round(mean_recall, 4),
        "mean_latency_seconds": round(mean_latency, 2),
        "p50_latency_seconds": round(p50_latency, 2),
        "p95_latency_seconds": round(p95_latency, 2),
        "repair_applied_count": sum(1 for r in final_results if r["repair_applied"]),
        "repair_attempted_count": sum(1 for r in final_results if r["repair_attempted"]),
    }

    config_snapshot = {
        "timestamp": summary["timestamp"],
        "benchmark_path": str(dataset_path),
        "database_path": str(db_path),
        "llm_provider": os.getenv("LLM_PROVIDER", "nvidia"),
        "nvidia_model": os.getenv("NVIDIA_MODEL", "nvidia/nemotron-3-super-120b-a12b"),
        "concurrency": concurrency,
        "phase": "phase9_live",
        "features": [
            "improved_rag",
            "column_grounding",
            "structured_query_plan_v2",
            "deterministic_plan_validator",
            "superlative_limit_grounding",
            "join_path_synthesis",
            "composite_metrics",
            "truncation_detection",
            "sqlglot_validation",
            "plan_alignment_verification",
            "targeted_repair",
            "evaluator_disabled_benchmark_mode",
        ],
    }
    with open(out_dir / "config_snapshot.json", "w", encoding="utf-8") as f:
        json.dump(config_snapshot, f, indent=2)
    with open(out_dir / "raw_results.json", "w", encoding="utf-8") as f:
        json.dump(final_results, f, indent=2, default=str)
    with open(out_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    logger.info("=" * 50)
    logger.info("BENCHMARK COMPLETED")
    logger.info(f"Total Queries:         {total}")
    logger.info(f"Result Correctness:    {summary['result_correctness']*100:.1f}%")
    logger.info(f"Exact Match:           {summary['exact_match_rate']*100:.1f}%")
    logger.info(f"Semantic Equivalence:  {summary['equivalent_match_rate']*100:.1f}%")
    logger.info(f"SQL Exec Success:      {summary['sql_execution_success_rate']*100:.1f}%")
    logger.info(f"Table Precision:       {summary['table_precision']*100:.1f}%")
    logger.info(f"Table Recall:          {summary['table_recall']*100:.1f}%")
    logger.info(f"Mean Latency:          {summary['mean_latency_seconds']:.2f}s (P95: {summary['p95_latency_seconds']:.2f}s)")
    logger.info(f"Total Runtime:         {summary['total_elapsed_seconds']:.1f}s")
    logger.info("=" * 50)

    return summary


def main():
    parser = argparse.ArgumentParser(description="Run Phase 9 Concurrent Benchmark")
    parser.add_argument("--dataset", default=str(BENCHMARK_PATH), help="Path to benchmark JSON")
    parser.add_argument("--out", default=None, help="Output directory")
    parser.add_argument("--workers", type=int, default=5, help="Number of concurrent workers")
    parser.add_argument("--limit", type=int, default=None, help="Limit query count")
    args = parser.parse_args()

    out_dir = Path(args.out) if args.out else ROOT / "results" / "phase9" / f"live_{datetime.datetime.now().strftime('%Y%m%dT%H%M%S')}"
    asyncio.run(run_benchmark_concurrent(
        dataset_path=Path(args.dataset),
        out_dir=out_dir,
        concurrency=args.workers,
        limit=args.limit,
    ))


if __name__ == "__main__":
    main()
