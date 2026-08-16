"""Phase 7 live benchmark runner with current pipeline.

Runs the actual current system against the frozen 100-query benchmark to measure
the effectiveness of Phase 6 improvements:
- Column-level grounding
- Truncation detection
- Semantic verification
- Targeted repair pipeline

Measures:
- Result correctness
- Result equivalence
- SQL execution success
- Table accuracy
- Repair success rate
- Invalid SQL rate
- Hallucinated columns/tables
- Unsafe SQL
- Verifier detection rate
- Latency
- Token usage (when available)
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
from agent_platform.llms.sql_truncation import is_sql_truncated
from agent_platform.llms.repair_prompt import filter_actionable_issues
from agent_platform.rag.ingestion.schema_context import EXACT_COLUMNS
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

BLOCKED_KEYWORDS = {
    "insert", "update", "delete", "drop", "alter", "create",
    "truncate", "replace", "attach", "detach", "vacuum", "pragma",
}


def load_benchmark() -> list[dict[str, Any]]:
    with open(BENCHMARK_PATH, encoding="utf-8") as f:
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


def check_unsafe_sql(sql: str | None) -> list[str]:
    if not sql:
        return []
    tokens = set(re.findall(r"[a-zA-Z_]+", sql.lower()))
    return sorted(tokens & BLOCKED_KEYWORDS)


def compare_results(actual: list[dict], expected: list[dict], tolerance: float = 0.01) -> dict[str, Any]:
    if actual == expected:
        return {"exact_match": True, "equivalent_match": True, "row_count_match": True, "differences": []}

    if len(actual) != len(expected):
        return {
            "exact_match": False,
            "equivalent_match": False,
            "row_count_match": False,
            "differences": [f"Row count mismatch: {len(actual)} vs {len(expected)}"],
        }

    actual_sorted = sorted(json.dumps(row, sort_keys=True) for row in actual)
    expected_sorted = sorted(json.dumps(row, sort_keys=True) for row in expected)
    equivalent = actual_sorted == expected_sorted

    differences = []
    if not equivalent:
        for i, (a_row, e_row) in enumerate(zip(actual[:5], expected[:5])):
            if a_row != e_row:
                differences.append(f"Row {i}: {a_row} != {e_row}")

    return {
        "exact_match": False,
        "equivalent_match": equivalent,
        "row_count_match": True,
        "differences": differences[:10],
    }


def classify_failure(result: dict[str, Any], expected: dict[str, Any]) -> str:
    """Classify the primary failure cause for an incorrect query."""
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
        if "no such function" in error:
            return "SQL generation"
        return "execution"

    sql = result.get("actual_sql") or ""
    if not sql.strip():
        return "SQL generation"

    if result.get("hallucinated_tables"):
        return "column hallucination"
    if result.get("hallucinated_columns"):
        return "column hallucination"
    if result.get("unsafe_keywords"):
        return "unsafe SQL"

    verifier_issues = result.get("verifier_issues", [])
    for issue in verifier_issues:
        cat = issue.get("category", "")
        if cat == "group_by_mismatch":
            return "grouping"
        if cat == "aggregation_grain":
            return "aggregation"
        if cat == "join_fan_out":
            return "join selection"
        if cat == "hallucinated_column":
            return "column hallucination"
        if cat == "duplicate_detection":
            return "join fan-out"
        if cat == "metric_inconsistency":
            return "metric"

    if not result.get("table_match", True):
        return "schema retrieval"

    return "SQL generation"


def run_query_in_db(sql: str) -> dict[str, Any]:
    """Execute SQL directly against the database for result comparison."""
    if not sql or not sql.strip():
        return {"success": False, "error": "empty sql", "rows": [], "row_count": 0}
    conn = sqlite3.connect(DB_PATH)
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


async def run_single_query(
    query_idx: int,
    query_item: dict[str, Any],
    service: AnalyticsAgentService,
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

    logger.info(f"Running query {query_id}: {question[:100]}")

    start_time = time.perf_counter()

    actual_sql = None
    actual_result = []
    sql_execution_success = False
    error = None
    reasoning = ""
    steps = []
    truncation_detected = False
    truncation_reason = None
    repair_attempted = False
    repair_successful = False
    pre_repair_sql = None
    post_repair_sql = None
    verifier_issues = []
    verifier_pre_repair = None
    verifier_post_repair = None
    validation_errors = []
    token_usage = {}
    confidence = None
    verdict = None

    try:
        result = await service.analyze(question)
        elapsed = time.perf_counter() - start_time

        sql_queries = result.get("sql_queries", [])
        if sql_queries:
            last_sql = sql_queries[-1] if isinstance(sql_queries, list) else sql_queries
            if isinstance(last_sql, dict):
                actual_sql = last_sql.get("query")
                actual_result = last_sql.get("result", {}).get("rows", []) if last_sql.get("result") else []
            elif isinstance(last_sql, str):
                actual_sql = last_sql
                actual_result = []

        if not actual_sql and sql_queries:
            for sq in reversed(sql_queries):
                if isinstance(sq, str) and sq.strip():
                    actual_sql = sq
                    break

        sql_execution_success = bool(actual_sql and actual_sql.strip())

        why_exp = result.get("why_explanation") or ""
        summary = result.get("summary") or ""
        reasoning = (why_exp if why_exp else "") + " " + (summary if summary else "")
        steps = result.get("steps", [])

        confidence = result.get("confidence")
        verdict = result.get("verdict")

        if actual_sql:
            is_trunc, trunc_reason = is_sql_truncated(actual_sql)
            if is_trunc:
                truncation_detected = True
                truncation_reason = trunc_reason

        if verifier and actual_sql:
            try:
                exec_info = {
                    "success": sql_execution_success,
                    "row_count": len(actual_result),
                    "rows": actual_result[:10],
                }
                exp_info = {
                    "row_count": expected_obj.get("row_count") if isinstance(expected_obj, dict) else None,
                    "columns": expected_obj.get("columns", []) if isinstance(expected_obj, dict) else [],
                    "values": expected_result[:10],
                }
                verifier_pre_repair = verifier.verify(
                    actual_sql,
                    execution_result=exec_info if sql_execution_success else None,
                    expected_result=exp_info,
                    level=VerificationLevel.BALANCED,
                )
                verifier_issues = [
                    {"category": i.category.value, "severity": i.severity, "message": i.message}
                    for i in verifier_pre_repair.issues
                ]
                actionable = filter_actionable_issues(verifier_pre_repair.issues)
                if actionable:
                    repair_attempted = True
            except Exception as exc:
                logger.warning(f"Verifier error for {query_id}: {exc}")

        repair_attempted = repair_attempted or "repair" in reasoning.lower()
        repair_successful = repair_attempted and sql_execution_success

    except Exception as exc:
        elapsed = time.perf_counter() - start_time
        error = str(exc)
        logger.error(f"Query {query_id} failed: {exc}")

    actual_tables = extract_tables_from_sql(actual_sql)
    actual_tables_set = set(actual_tables)
    table_precision = (
        len(actual_tables_set & expected_tables) / len(actual_tables_set)
        if actual_tables_set else 0.0
    )
    table_recall = (
        len(actual_tables_set & expected_tables) / len(expected_tables)
        if expected_tables else 0.0
    )
    table_match = actual_tables_set == expected_tables

    if sql_execution_success and actual_sql:
        exec_result = run_query_in_db(actual_sql)
        if exec_result["success"]:
            actual_result = exec_result["rows"]
            comparison = compare_results(actual_result, expected_result)
        else:
            comparison = {"exact_match": False, "equivalent_match": False, "row_count_match": False, "differences": [exec_result["error"]]}
            sql_execution_success = False
    else:
        comparison = {"exact_match": False, "equivalent_match": False, "row_count_match": False, "differences": ["no sql executed"]}

    result_correct = comparison["exact_match"] or comparison["equivalent_match"]

    if not result_correct and not error:
        failure_cause = classify_failure({
            "actual_sql": actual_sql,
            "hallucinated_tables": check_hallucinated_schema(actual_sql),
            "hallucinated_columns": [i["message"] for i in verifier_issues if i["category"] == "hallucinated_column"],
            "unsafe_keywords": check_unsafe_sql(actual_sql),
            "table_match": table_match,
            "error": error,
            "verifier_issues": verifier_issues,
        }, expected_obj)
    else:
        failure_cause = None

    return {
        "query_id": query_id,
        "question": question,
        "domain": domain,
        "query_type": query_type,
        "difficulty": difficulty,
        "actual_sql": actual_sql,
        "expected_sql": expected_sql,
        "expected_tables": list(expected_tables),
        "actual_tables": actual_tables,
        "table_precision": round(table_precision, 4),
        "table_recall": round(table_recall, 4),
        "table_match": table_match,
        "result_correct": result_correct,
        "result_exact_match": comparison["exact_match"],
        "result_equivalent_match": comparison["equivalent_match"],
        "row_count_match": comparison["row_count_match"],
        "expected_row_count": len(expected_result),
        "actual_row_count": len(actual_result),
        "sql_execution_success": sql_execution_success,
        "repair_attempted": repair_attempted,
        "repair_successful": repair_successful,
        "truncation_detected": truncation_detected,
        "truncation_reason": truncation_reason,
        "validation_errors": validation_errors,
        "verifier_issues": verifier_issues,
        "verifier_pre_repair_valid": verifier_pre_repair.is_valid if verifier_pre_repair else None,
        "verifier_post_repair_valid": verifier_post_repair.is_valid if verifier_post_repair else None,
        "hallucinated_tables": check_hallucinated_schema(actual_sql),
        "hallucinated_columns": [i["message"] for i in verifier_issues if i["category"] == "hallucinated_column"],
        "unsafe_keywords": check_unsafe_sql(actual_sql),
        "invalid_sql": bool(error) or (not actual_sql or not actual_sql.strip()),
        "failure_cause": failure_cause,
        "latency_seconds": round(elapsed, 4),
        "confidence": confidence,
        "verdict": verdict,
        "error": error,
        "reasoning": reasoning[:500] if reasoning else "",
        "steps_count": len(steps),
        "differences": comparison.get("differences", []),
    }


async def run_benchmark(
    db_path: str | Path,
    output_dir: Path,
    limit: int | None = None,
) -> dict[str, Any]:
    logger.info("Starting Phase 7 live benchmark")
    logger.info(f"Database: {db_path}")
    logger.info(f"Output directory: {output_dir}")

    queries = load_benchmark()
    if limit:
        queries = queries[:limit]
        logger.info(f"Limited to first {limit} queries")

    logger.info(f"Total queries: {len(queries)}")

    service = AnalyticsAgentService.from_sqlite(db_path)
    verifier = SQLSemanticVerifier(str(db_path))

    results = []
    start_time = time.perf_counter()

    for idx, query_item in enumerate(queries):
        result = await run_single_query(idx, query_item, service, verifier)
        results.append(result)

        correct_count = sum(1 for r in results if r["result_correct"])
        exec_count = sum(1 for r in results if r["sql_execution_success"])
        logger.info(
            f"Progress: {len(results)}/{len(queries)} | "
            f"Correct: {correct_count}/{len(results)} ({100*correct_count/len(results):.1f}%) | "
            f"Exec: {exec_count}/{len(results)} ({100*exec_count/len(results):.1f}%)"
        )

    total_elapsed = time.perf_counter() - start_time

    correct_count = sum(1 for r in results if r["result_correct"])
    exact_match_count = sum(1 for r in results if r["result_exact_match"])
    equivalent_match_count = sum(1 for r in results if r["result_equivalent_match"])
    sql_success_count = sum(1 for r in results if r["sql_execution_success"])
    repair_attempted_count = sum(1 for r in results if r["repair_attempted"])
    repair_successful_count = sum(1 for r in results if r["repair_successful"])
    truncation_count = sum(1 for r in results if r["truncation_detected"])
    invalid_sql_count = sum(1 for r in results if r["invalid_sql"])
    hallucinated_table_count = sum(1 for r in results if r["hallucinated_tables"])
    hallucinated_col_count = sum(1 for r in results if r["hallucinated_columns"])
    unsafe_count = sum(1 for r in results if r["unsafe_keywords"])
    table_match_count = sum(1 for r in results if r["table_match"])

    verifier_flagged = sum(1 for r in results if r["verifier_issues"])
    verifier_errors = sum(
        1 for r in results
        for issue in r["verifier_issues"]
        if issue["severity"] == "error"
    )

    latencies = [r["latency_seconds"] for r in results]
    latencies_sorted = sorted(latencies)

    avg_table_precision = sum(r["table_precision"] for r in results) / len(results) if results else 0.0
    avg_table_recall = sum(r["table_recall"] for r in results) / len(results) if results else 0.0

    confidences = [r["confidence"] for r in results if r["confidence"] is not None]

    summary = {
        "phase": "phase7_live",
        "total_queries": len(results),
        "result_correctness": round(correct_count / len(results), 4) if results else 0.0,
        "exact_match_rate": round(exact_match_count / len(results), 4) if results else 0.0,
        "equivalent_match_rate": round(equivalent_match_count / len(results), 4) if results else 0.0,
        "sql_execution_success_rate": round(sql_success_count / len(results), 4) if results else 0.0,
        "table_accuracy": round(table_match_count / len(results), 4) if results else 0.0,
        "table_precision": round(avg_table_precision, 4),
        "table_recall": round(avg_table_recall, 4),
        "repair_attempted_rate": round(repair_attempted_count / len(results), 4) if results else 0.0,
        "repair_success_rate": (
            round(repair_successful_count / repair_attempted_count, 4)
            if repair_attempted_count > 0 else 0.0
        ),
        "truncation_detected_count": truncation_count,
        "truncation_rate": round(truncation_count / len(results), 4) if results else 0.0,
        "invalid_sql_count": invalid_sql_count,
        "invalid_sql_rate": round(invalid_sql_count / len(results), 4) if results else 0.0,
        "hallucinated_table_count": hallucinated_table_count,
        "hallucinated_table_rate": round(hallucinated_table_count / len(results), 4) if results else 0.0,
        "hallucinated_column_count": hallucinated_col_count,
        "hallucinated_column_rate": round(hallucinated_col_count / len(results), 4) if results else 0.0,
        "unsafe_sql_count": unsafe_count,
        "unsafe_sql_rate": round(unsafe_count / len(results), 4) if results else 0.0,
        "verifier_flagged_count": verifier_flagged,
        "verifier_error_count": verifier_errors,
        "mean_latency_seconds": round(sum(latencies) / len(latencies), 4) if latencies else 0.0,
        "p50_latency_seconds": round(latencies_sorted[len(latencies_sorted) // 2], 4) if latencies_sorted else 0.0,
        "p95_latency_seconds": round(latencies_sorted[int(len(latencies_sorted) * 0.95)], 4) if latencies_sorted else 0.0,
        "total_elapsed_seconds": round(total_elapsed, 2),
    }

    output_dir.mkdir(parents=True, exist_ok=True)

    with open(output_dir / "raw_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)

    with open(output_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    config_snapshot = {
        "timestamp": datetime.datetime.now().isoformat(),
        "benchmark_path": str(BENCHMARK_PATH),
        "benchmark_hash": __import__("hashlib").sha256(BENCHMARK_PATH.read_bytes()).hexdigest()[:16],
        "database_path": str(db_path),
        "llm_provider": os.getenv("LLM_PROVIDER", "nvidia"),
        "nvidia_model": os.getenv("NVIDIA_MODEL", "nvidia/llama-3.3-nemotron-super-49b-v1.5"),
        "phase": "phase7_live",
        "features": [
            "improved_rag",
            "column_grounding",
            "truncation_detection",
            "sqlglot_validation",
            "semantic_verification",
            "targeted_repair",
        ],
    }

    with open(output_dir / "config_snapshot.json", "w", encoding="utf-8") as f:
        json.dump(config_snapshot, f, indent=2)

    _write_report(results, summary, output_dir)

    logger.info("=" * 80)
    logger.info("PHASE 7 LIVE BENCHMARK COMPLETE")
    logger.info("=" * 80)
    logger.info(f"Result Correctness: {summary['result_correctness']*100:.1f}%")
    logger.info(f"SQL Execution Success: {summary['sql_execution_success_rate']*100:.1f}%")
    logger.info(f"Table Accuracy: {summary['table_accuracy']*100:.1f}%")
    logger.info(f"Repair Attempted: {summary['repair_attempted_rate']*100:.1f}%")
    logger.info(f"Repair Success Rate: {summary['repair_success_rate']*100:.1f}%")
    logger.info(f"Truncation Detected: {summary['truncation_detected_count']}")
    logger.info(f"Invalid SQL: {summary['invalid_sql_count']}")
    logger.info(f"Hallucinated Tables: {summary['hallucinated_table_count']}")
    logger.info(f"Hallucinated Columns: {summary['hallucinated_column_count']}")
    logger.info(f"Unsafe SQL: {summary['unsafe_sql_count']}")
    logger.info(f"Mean Latency: {summary['mean_latency_seconds']:.2f}s")
    logger.info(f"P95 Latency: {summary['p95_latency_seconds']:.2f}s")
    logger.info(f"Total Elapsed: {summary['total_elapsed_seconds']:.2f}s")
    logger.info("=" * 80)

    return summary


def _write_report(results: list[dict[str, Any]], summary: dict[str, Any], output_dir: Path) -> None:
    lines = [
        "# Phase 7 Live Benchmark Report",
        "",
        f"**Date:** {datetime.datetime.now().isoformat()}",
        f"**Run:** `{output_dir.name}`",
        "**Benchmark:** frozen 100-query V2 (`benchmark_dataset_v2.json`)",
        "**Method:** Live current pipeline (column grounding + SQLGlot + semantic verification + targeted repair).",
        "",
        "---",
        "",
        "## 1. Summary Metrics",
        "",
        "| Metric | Value |",
        "| :--- | :---: |",
        f"| Result correctness | {summary['result_correctness']*100:.2f}% |",
        f"| Exact match rate | {summary['exact_match_rate']*100:.2f}% |",
        f"| Equivalent match rate | {summary['equivalent_match_rate']*100:.2f}% |",
        f"| SQL execution success | {summary['sql_execution_success_rate']*100:.2f}% |",
        f"| Table accuracy | {summary['table_accuracy']*100:.2f}% |",
        f"| Table precision | {summary['table_precision']*100:.2f}% |",
        f"| Table recall | {summary['table_recall']*100:.2f}% |",
        f"| Repair attempted | {summary['repair_attempted_rate']*100:.2f}% |",
        f"| Repair success rate | {summary['repair_success_rate']*100:.2f}% |",
        f"| Truncation detected | {summary['truncation_detected_count']} |",
        f"| Invalid SQL | {summary['invalid_sql_count']} |",
        f"| Hallucinated tables | {summary['hallucinated_table_count']} |",
        f"| Hallucinated columns | {summary['hallucinated_column_count']} |",
        f"| Unsafe SQL | {summary['unsafe_sql_count']} |",
        f"| Verifier flagged | {summary['verifier_flagged_count']} |",
        f"| Verifier errors | {summary['verifier_error_count']} |",
        f"| Mean latency | {summary['mean_latency_seconds']:.2f}s |",
        f"| P50 latency | {summary['p50_latency_seconds']:.2f}s |",
        f"| P95 latency | {summary['p95_latency_seconds']:.2f}s |",
        f"| Total elapsed | {summary['total_elapsed_seconds']:.2f}s |",
        "",
        "---",
        "",
        "## 2. Per-Query Results",
        "",
        "| # | Domain | Query Type | Difficulty | Exec | Correct | Tables | Repair | Failure |",
        "| :--- | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- |",
    ]

    for r in results:
        exec_icon = "Y" if r["sql_execution_success"] else "N"
        correct_icon = "Y" if r["result_correct"] else "N"
        table_icon = f"{r['table_precision']*100:.0f}%"
        repair_icon = "Y" if r["repair_attempted"] else "N"

        failure = r.get("failure_cause") or ("None" if r["result_correct"] else "Unknown")
        if r.get("error") and not failure or failure == "Unknown":
            failure = f"Error: {r['error'][:50]}"

        lines.append(
            f"| {r['query_id']} | {r['domain'][:20]} | {r['query_type']} | {r['difficulty']} | "
            f"{exec_icon} | {correct_icon} | {table_icon} | {repair_icon} | {failure} |"
        )

    lines += [
        "",
        "---",
        "",
        "## 3. Failure Breakdown",
        "",
        "| Failure Cause | Count | Rate |",
        "| :--- | :---: | :---: |",
    ]

    failure_counts: dict[str, int] = {}
    for r in results:
        if not r["result_correct"]:
            cause = r.get("failure_cause") or "unknown"
            failure_counts[cause] = failure_counts.get(cause, 0) + 1

    for cause, count in sorted(failure_counts.items(), key=lambda x: -x[1]):
        lines.append(f"| {cause} | {count} | {count/len(results)*100:.1f}% |")

    lines += [
        "",
        "---",
        "",
        "## 4. Latency Distribution",
        "",
        f"- Mean: {summary['mean_latency_seconds']:.2f}s",
        f"- P50: {summary['p50_latency_seconds']:.2f}s",
        f"- P95: {summary['p95_latency_seconds']:.2f}s",
        "",
        "---",
        "",
        "*Generated by Phase 7 Live Benchmark Runner*",
    ]

    report_path = output_dir / "phase7_report.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info(f"Report written: {report_path}")


def main():
    parser = argparse.ArgumentParser(description="Run Phase 7 live benchmark")
    parser.add_argument("--db", default=str(DB_PATH), help="Path to SQLite database")
    parser.add_argument("--output", default=None, help="Output directory")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of queries")
    args = parser.parse_args()

    if args.output:
        output_dir = Path(args.output)
    else:
        timestamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
        output_dir = ROOT / "results" / "phase7" / f"live_{timestamp}"

    asyncio.run(run_benchmark(args.db, output_dir, args.limit))


if __name__ == "__main__":
    main()
