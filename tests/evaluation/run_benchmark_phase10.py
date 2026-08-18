"""Phase 10 Production Benchmark Runner.

Supports:
- 100-query benchmark dataset (`benchmark_dataset_v2.json`)
- 500-query benchmark dataset (`benchmark_dataset_500.json`)
- Bounded concurrency (--workers 4, 8, etc.)
- Granular per-query checkpointing & instant resumability
- SQL execution against SQLite ground-truth
- Programmatic semantic & equivalent result comparison
- Comprehensive performance metrics (exact, equivalent, SQL success, table recall/precision, latency, p50/p95)
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
from agent_platform.tools.sql_verifier import SQLSemanticVerifier

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("benchmark_phase10")

DB_PATH = ROOT / "data" / "analytics.db"
DEFAULT_DATASET = ROOT / "tests" / "evaluation" / "benchmark_dataset_v2.json"
KNOWN_TABLES = {
    "customers", "geolocation", "order_items", "order_payments", "order_reviews",
    "orders", "products", "sellers", "product_category_name_translation",
}


def load_dataset(path: Path) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
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


def compare_results(actual_rows: list[dict], expected_rows: list[dict]) -> dict[str, Any]:
    if not actual_rows and not expected_rows:
        return {"exact_match": True, "equivalent_match": True, "row_count_match": True}
    if not actual_rows or not expected_rows:
        return {"exact_match": False, "equivalent_match": False, "row_count_match": False}

    exact_match = (actual_rows == expected_rows)
    equivalent = True
    if len(actual_rows) != len(expected_rows):
        equivalent = False
    else:
        for a_row, e_row in zip(actual_rows, expected_rows):
            a_vals = [round(v, 2) if isinstance(v, (int, float)) else str(v).strip().lower() for v in a_row.values()]
            e_vals = [round(v, 2) if isinstance(v, (int, float)) else str(v).strip().lower() for v in e_row.values()]
            if sorted(a_vals, key=str) != sorted(e_vals, key=str):
                equivalent = False
                break

    return {
        "exact_match": exact_match,
        "equivalent_match": equivalent or exact_match,
        "row_count_match": len(actual_rows) == len(expected_rows),
    }


def extract_tables_from_sql(sql: str | None) -> list[str]:
    if not sql:
        return []
    cleaned = re.sub(r"\s+", " ", sql.lower())
    return [t for t in KNOWN_TABLES if re.search(rf"\b{t}\b", cleaned)]


async def run_single_query(
    idx: int,
    item: dict[str, Any],
    service: AnalyticsAgentService,
    db_path: Path,
) -> dict[str, Any]:
    qid = item.get("id", f"q{idx:03d}")
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
    precision = (len(correct_tables) / len(queried_tables)) if queried_tables else 0.0
    recall = (len(correct_tables) / len(expected_tables)) if expected_tables else 1.0

    return {
        "query_id": qid,
        "question": question,
        "category": item.get("category", item.get("domain", "unknown")),
        "difficulty": item.get("difficulty", "unknown"),
        "expected_tables": list(expected_tables),
        "queried_tables": queried_tables,
        "actual_sql": actual_sql,
        "sql_execution_success": sql_success,
        "exact_match": comp["exact_match"],
        "equivalent_match": comp["equivalent_match"],
        "table_precision": round(precision, 4),
        "table_recall": round(recall, 4),
        "table_exact_match": set(queried_tables) == expected_tables,
        "latency_seconds": elapsed,
        "error": error,
        "repair_events": response.get("repair_events", []) if response else [],
    }


async def run_benchmark(
    dataset_path: Path,
    output_dir: Path,
    workers: int = 4,
    limit: int | None = None,
    enable_evaluator: bool = False,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_file = output_dir / "checkpoint.json"

    dataset = load_dataset(dataset_path)
    if limit:
        dataset = dataset[:limit]

    total_queries = len(dataset)
    logger.info("Loaded benchmark dataset: %d queries from %s", total_queries, dataset_path)

    completed: dict[str, dict[str, Any]] = {}
    if checkpoint_file.exists():
        try:
            with open(checkpoint_file, "r", encoding="utf-8") as f:
                completed = json.load(f)
            logger.info("Resumed from checkpoint: %d/%d queries completed", len(completed), total_queries)
        except Exception:
            completed = {}

    service = AnalyticsAgentService.from_sqlite(DB_PATH, enable_evaluator=enable_evaluator)
    semaphore = asyncio.Semaphore(workers)

    async def _worker(idx: int, item: dict[str, Any]):
        qid = item.get("id", f"q{idx:03d}")
        if qid in completed:
            return completed[qid]
        async with semaphore:
            try:
                res = await asyncio.wait_for(run_single_query(idx, item, service, DB_PATH), timeout=300.0)
            except Exception as exc:
                logger.error("[%s/%s] %s failed with exception: %s", len(completed) + 1, total_queries, qid, exc)
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
                    "table_precision": 0.0,
                    "table_recall": 0.0,
                    "table_exact_match": False,
                    "latency_seconds": 300.0,
                    "error": str(exc),
                }
            completed[qid] = res
            with open(checkpoint_file, "w", encoding="utf-8") as f:
                json.dump(completed, f, indent=2)
            logger.info(
                "[%s/%s] %s done (equiv=%s, sql=%s, time=%.2fs)",
                len(completed), total_queries, qid, res["equivalent_match"], res["sql_execution_success"], res["latency_seconds"]
            )
            return res

    started_all = time.perf_counter()
    tasks = [_worker(i, item) for i, item in enumerate(dataset)]
    results = await asyncio.gather(*tasks)
    total_elapsed = round(time.perf_counter() - started_all, 2)

    total = len(results)
    equiv_matches = sum(1 for r in results if r["equivalent_match"])
    exact_matches = sum(1 for r in results if r["exact_match"])
    sql_successes = sum(1 for r in results if r["sql_execution_success"])
    table_exacts = sum(1 for r in results if r["table_exact_match"])
    avg_precision = sum(r["table_precision"] for r in results) / total if total else 0.0
    avg_recall = sum(r["table_recall"] for r in results) / total if total else 0.0
    latencies = sorted(r["latency_seconds"] for r in results)

    p50_lat = latencies[int(total * 0.50)] if latencies else 0.0
    p95_lat = latencies[int(total * 0.95)] if latencies else 0.0
    mean_lat = sum(latencies) / total if total else 0.0

    summary = {
        "timestamp": datetime.datetime.now().isoformat(),
        "dataset_path": str(dataset_path),
        "total_queries": total,
        "workers": workers,
        "total_elapsed_seconds": total_elapsed,
        "equivalent_match_rate": round(equiv_matches / total, 4) if total else 0.0,
        "exact_match_rate": round(exact_matches / total, 4) if total else 0.0,
        "sql_execution_success_rate": round(sql_successes / total, 4) if total else 0.0,
        "table_accuracy": round(table_exacts / total, 4) if total else 0.0,
        "table_precision": round(avg_precision, 4),
        "table_recall": round(avg_recall, 4),
        "mean_latency_seconds": round(mean_lat, 2),
        "p50_latency_seconds": round(p50_lat, 2),
        "p95_latency_seconds": round(p95_lat, 2),
        "results": results,
    }

    summary_file = output_dir / "summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    report_md = f"""# Phase 10 Benchmark Report

- **Date**: {summary['timestamp']}
- **Dataset**: `{dataset_path.name}` ({total} queries)
- **Workers**: {workers}
- **Total Elapsed**: {total_elapsed:.1f}s

## 📊 Summary Performance

| Metric | Phase 9 Baseline (100q) | Phase 10 Result ({total}q) | Status |
| :--- | :---: | :---: | :---: |
| **Equivalent Match Rate** | **29.0%** | **{summary['equivalent_match_rate']*100:.1f}%** | {'🚀 IMPROVED' if summary['equivalent_match_rate'] >= 0.29 else '⚠️ REGRESSED'} |
| **Exact Match Rate** | 12.0% | **{summary['exact_match_rate']*100:.1f}%** | — |
| **SQL Execution Success** | 100.0% | **{summary['sql_execution_success_rate']*100:.1f}%** | {'✅ 100%' if summary['sql_execution_success_rate'] == 1.0 else '⚠️'} |
| **Table Exact Accuracy** | 51.0% | **{summary['table_accuracy']*100:.1f}%** | — |
| **Table Recall** | 95.8% | **{summary['table_recall']*100:.1f}%** | — |
| **Table Precision** | 79.3% | **{summary['table_precision']*100:.1f}%** | — |
| **Mean Latency** | 173.3s | **{mean_lat:.2f}s** | {'⚡ FASTER' if mean_lat < 173.3 else '—'} |
| **P50 Latency** | 70.2s | **{p50_lat:.2f}s** | — |
| **P95 Latency** | 280.6s | **{p95_lat:.2f}s** | — |
"""

    with open(output_dir / "benchmark_report.md", "w", encoding="utf-8") as f:
        f.write(report_md)

    logger.info("Benchmark complete. Results written to %s", output_dir)
    return summary


def main():
    parser = argparse.ArgumentParser(description="Run Phase 10 benchmark")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET, help="Benchmark dataset JSON")
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "phase10" / "live_benchmark", help="Output directory")
    parser.add_argument("--workers", type=int, default=4, help="Concurrent workers")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of queries")
    parser.add_argument("--enable-evaluator", action="store_true", help="Enable LLM Evaluator synthesis")
    args = parser.parse_args()

    asyncio.run(run_benchmark(
        dataset_path=args.dataset,
        output_dir=args.output,
        workers=args.workers,
        limit=args.limit,
        enable_evaluator=args.enable_evaluator,
    ))


if __name__ == "__main__":
    main()
