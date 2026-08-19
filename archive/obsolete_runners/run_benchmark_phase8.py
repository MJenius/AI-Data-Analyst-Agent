"""Phase 8 live benchmark runner — plan-driven semantic alignment.

Runs the current system against the frozen 100-query benchmark to measure
the Phase 8 improvement: QueryPlan-aware semantic verification with ONE
targeted repair call per concrete mismatch.

Measures (beyond Phase 7):
- Result correctness (primary metric; compare vs Phase 7 10% / Phase 4 16%)
- Semantic detection rate: of incorrect queries, how many expose an
  actionable plan-alignment issue (join path / metric / filter / time grain /
  group-by grain / ranking / entity)
- Detection precision + false-positive rate (plan-alignment flags on queries
  whose SQL was actually correct)
- Repair attempt / applied rates from pipeline `repair_events`
- Pre-repair vs post-repair correctness (repair success rate, repaired-to-correct)
- False-positive repair rate (repair applied although pre-repair SQL was correct)
- Programmatic vs LLM repair split
- Latency (mean / p50 / p95) and token usage (when available)
- Failure-cause breakdown incl. new plan-alignment categories

The benchmark file and the expected answers are frozen: expected_sql /
expected_result are used ONLY for measurement, never fed into the pipeline.
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

BLOCKED_KEYWORDS = {
    "insert", "update", "delete", "drop", "alter", "create",
    "truncate", "replace", "attach", "detach", "vacuum", "pragma",
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
        if cat in PLAN_CATS:
            return cat
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
    error = None
    steps = []
    repair_events: list[dict[str, Any]] = []
    query_plan = None
    plan_available = False
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
            elif isinstance(last_sql, str):
                actual_sql = last_sql

        if not actual_sql and sql_queries:
            for sq in reversed(sql_queries):
                if isinstance(sq, str) and sq.strip():
                    actual_sql = sq
                    break

        steps = result.get("steps", [])
        repair_events = result.get("repair_events", []) or []
        query_plan = result.get("query_plan")
        plan_available = isinstance(query_plan, dict) and bool(query_plan)
        confidence = result.get("confidence")
        verdict = result.get("verdict")

    except Exception as exc:
        elapsed = time.perf_counter() - start_time
        error = str(exc)
        logger.error(f"Query {query_id} failed: {exc}")

    sql_execution_success = bool(actual_sql and actual_sql.strip())

    # ── run actual SQL in DB ────────────────────────────────────────────────
    comparison = {"exact_match": False, "equivalent_match": False, "row_count_match": False, "differences": []}
    if sql_execution_success:
        exec_result = run_query_in_db(actual_sql)
        if exec_result["success"]:
            actual_result = exec_result["rows"]
            comparison = compare_results(actual_result, expected_result)
        else:
            comparison["differences"] = [exec_result["error"]]
            sql_execution_success = False
    else:
        comparison["differences"] = ["no sql executed"]
    result_correct = comparison["exact_match"] or comparison["equivalent_match"]

    # ── harness-level semantic verification (detection measurement) ─────────
    verifier_issues: list[dict[str, Any]] = []
    actionable_plan_issues: list[dict[str, Any]] = []
    detected_plan_mismatch = False
    verifier_valid = None
    if verifier and sql_execution_success and actual_sql:
        try:
            exec_info = {
                "success": True,
                "row_count": len(actual_result),
                "rows": actual_result[:10],
            }
            exp_info = {
                "row_count": expected_obj.get("row_count") if isinstance(expected_obj, dict) else None,
                "columns": expected_obj.get("columns", []) if isinstance(expected_obj, dict) else [],
                "values": expected_result[:10],
            }
            vres = verifier.verify(
                actual_sql,
                execution_result=exec_info,
                expected_result=exp_info,
                level=VerificationLevel.BALANCED,
                query_plan=query_plan if plan_available else None,
                question=question,
            )
            verifier_valid = vres.is_valid
            verifier_issues = [
                {"category": i.category.value, "severity": i.severity, "message": i.message}
                for i in vres.issues
            ]
            actionable = filter_actionable_issues(vres.issues)
            actionable_plan_issues = [
                {"category": i.category.value, "severity": i.severity, "message": i.message}
                for i in actionable
                if i.category.value in PLAN_CATS
            ]
            detected_plan_mismatch = bool(actionable_plan_issues)
        except Exception as exc:
            logger.warning(f"Verifier error for {query_id}: {exc}")

    # ── pipeline repair events ──────────────────────────────────────────────
    applied_events = [e for e in repair_events if e.get("applied")]
    repair_attempted = bool(repair_events)
    repair_applied = bool(applied_events)

    pre_repair_sql = None
    pre_repair_correct = None
    post_repair_sql = None
    post_repair_correct = None
    repaired_to_correct = False
    false_positive_repair = False
    if applied_events:
        last_event = applied_events[-1]
        pre_repair_sql = last_event.get("pre_repair_sql")
        post_repair_sql = last_event.get("final_sql") or last_event.get("post_repair_sql")
        if pre_repair_sql and pre_repair_sql.strip():
            pre_res = run_query_in_db(pre_repair_sql)
            pre_repair_correct = pre_res["success"] and (
                compare_results(pre_res["rows"], expected_result)["equivalent_match"]
            )
            if not pre_repair_correct:
                repaired_to_correct = result_correct
            else:
                false_positive_repair = repair_applied
        if post_repair_sql and post_repair_sql.strip():
            post_res = run_query_in_db(post_repair_sql)
            post_repair_correct = post_res["success"] and (
                compare_results(post_res["rows"], expected_result)["equivalent_match"]
            )

    repair_methods = sorted({e.get("method") for e in applied_events if e.get("method")})
    repair_categories = sorted({
        c for e in applied_events for c in (e.get("categories") or [])
    })

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

    failure_cause = None
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
        "plan_available": plan_available,
        "verifier_issues": verifier_issues,
        "actionable_plan_issues": actionable_plan_issues,
        "detected_plan_mismatch": detected_plan_mismatch,
        "verifier_valid": verifier_valid,
        "repair_attempted": repair_attempted,
        "repair_applied": repair_applied,
        "repair_events_count": len(repair_events),
        "repair_methods": repair_methods,
        "repair_categories": repair_categories,
        "pre_repair_correct": pre_repair_correct,
        "post_repair_correct": post_repair_correct,
        "repaired_to_correct": repaired_to_correct,
        "false_positive_repair": false_positive_repair,
        "hallucinated_tables": check_hallucinated_schema(actual_sql),
        "hallucinated_columns": [i["message"] for i in verifier_issues if i["category"] == "hallucinated_column"],
        "unsafe_keywords": check_unsafe_sql(actual_sql),
        "invalid_sql": bool(error) or (not actual_sql or not actual_sql.strip()),
        "failure_cause": failure_cause,
        "latency_seconds": round(elapsed, 4),
        "confidence": confidence,
        "verdict": verdict,
        "error": error,
        "steps_count": len(steps),
        "differences": comparison.get("differences", []),
    }


async def run_benchmark(
    db_path: str | Path,
    output_dir: Path,
    limit: int | None = None,
) -> dict[str, Any]:
    logger.info("Starting Phase 8 live benchmark")
    logger.info(f"Database: {db_path}")
    logger.info(f"Output directory: {output_dir}")

    queries = load_benchmark()
    if limit:
        queries = queries[:limit]
        logger.info(f"Limited to first {limit} queries")

    logger.info(f"Total queries: {len(queries)}")

    llm_client = get_llm_client()
    service = AnalyticsAgentService.from_sqlite(db_path, llm_client=llm_client)
    verifier = SQLSemanticVerifier(str(db_path))

    results = []
    start_time = time.perf_counter()

    for idx, query_item in enumerate(queries):
        result = await run_single_query(idx, query_item, service, verifier)
        results.append(result)

        correct_count = sum(1 for r in results if r["result_correct"])
        exec_count = sum(1 for r in results if r["sql_execution_success"])
        repair_count = sum(1 for r in results if r["repair_applied"])
        logger.info(
            f"Progress: {len(results)}/{len(queries)} | "
            f"Correct: {correct_count}/{len(results)} ({100*correct_count/len(results):.1f}%) | "
            f"Exec: {exec_count}/{len(results)} ({100*exec_count/len(results):.1f}%) | "
            f"RepairApplied: {repair_count}/{len(results)}"
        )

    total_elapsed = time.perf_counter() - start_time

    n = len(results)
    correct_count = sum(1 for r in results if r["result_correct"])
    exact_match_count = sum(1 for r in results if r["result_exact_match"])
    equivalent_match_count = sum(1 for r in results if r["result_equivalent_match"])
    sql_success_count = sum(1 for r in results if r["sql_execution_success"])
    invalid_sql_count = sum(1 for r in results if r["invalid_sql"])
    hallucinated_table_count = sum(1 for r in results if r["hallucinated_tables"])
    hallucinated_col_count = sum(1 for r in results if r["hallucinated_columns"])
    unsafe_count = sum(1 for r in results if r["unsafe_keywords"])
    table_match_count = sum(1 for r in results if r["table_match"])
    plan_available_count = sum(1 for r in results if r["plan_available"])

    # ── Phase 8 detection metrics ───────────────────────────────────────────
    incorrect = [r for r in results if not r["result_correct"] and r["sql_execution_success"]]
    incorrect_total = len(incorrect)
    detected_incorrect = [r for r in incorrect if r["detected_plan_mismatch"]]
    flagged = [r for r in results if r["detected_plan_mismatch"]]
    correct_but_flagged = [r for r in flagged if r["result_correct"]]
    detection_rate = len(detected_incorrect) / incorrect_total if incorrect_total else 0.0
    detection_precision = len(detected_incorrect) / len(flagged) if flagged else 0.0
    false_positive_flag_rate = len(correct_but_flagged) / len(flagged) if flagged else 0.0

    # ── Phase 8 repair metrics ──────────────────────────────────────────────
    repair_attempted_count = sum(1 for r in results if r["repair_attempted"])
    repair_applied_count = sum(1 for r in results if r["repair_applied"])
    pre_repair_known = [r for r in results if r["pre_repair_correct"] is not None]
    false_positive_repairs = [r for r in pre_repair_known if r["false_positive_repair"]]
    repaired_to_correct_count = sum(1 for r in results if r["repaired_to_correct"])
    applied_not_pre_correct = [r for r in results if r["repair_applied"] and r["pre_repair_correct"] is False]
    repair_success_rate = (
        len([r for r in applied_not_pre_correct if r["result_correct"]]) / len(applied_not_pre_correct)
        if applied_not_pre_correct else 0.0
    )
    false_positive_repair_rate = (
        len(false_positive_repairs) / repair_applied_count if repair_applied_count else 0.0
    )
    programmatic_repairs = sum(
        1 for r in results if "programmatic" in r["repair_methods"]
    )
    llm_repairs = sum(1 for r in results if "llm" in r["repair_methods"])

    repair_category_counts: dict[str, int] = {}
    for r in results:
        for cat in r["repair_categories"]:
            repair_category_counts[cat] = repair_category_counts.get(cat, 0) + 1

    latencies = [r["latency_seconds"] for r in results]
    latencies_sorted = sorted(latencies)

    avg_table_precision = sum(r["table_precision"] for r in results) / n if n else 0.0
    avg_table_recall = sum(r["table_recall"] for r in results) / n if n else 0.0

    # ── token usage ─────────────────────────────────────────────────────────
    usage_totals: dict[str, int] = {}
    if llm_client is not None:
        usage_totals = dict(getattr(llm_client, "usage_totals", {}) or {})

    summary = {
        "phase": "phase8_live",
        "total_queries": n,
        "result_correctness": round(correct_count / n, 4) if n else 0.0,
        "exact_match_rate": round(exact_match_count / n, 4) if n else 0.0,
        "equivalent_match_rate": round(equivalent_match_count / n, 4) if n else 0.0,
        "sql_execution_success_rate": round(sql_success_count / n, 4) if n else 0.0,
        "table_accuracy": round(table_match_count / n, 4) if n else 0.0,
        "table_precision": round(avg_table_precision, 4),
        "table_recall": round(avg_table_recall, 4),
        "invalid_sql_count": invalid_sql_count,
        "invalid_sql_rate": round(invalid_sql_count / n, 4) if n else 0.0,
        "hallucinated_table_count": hallucinated_table_count,
        "hallucinated_column_count": hallucinated_col_count,
        "unsafe_sql_count": unsafe_count,
        "plan_available_count": plan_available_count,
        "plan_available_rate": round(plan_available_count / n, 4) if n else 0.0,
        # detection
        "semantic_detection_rate": round(detection_rate, 4),
        "detection_precision": round(detection_precision, 4),
        "detected_plan_mismatch_count": len(detected_incorrect),
        "incorrect_executable_count": incorrect_total,
        "flagged_count": len(flagged),
        "correct_but_flagged_count": len(correct_but_flagged),
        "false_positive_flag_rate": round(false_positive_flag_rate, 4),
        # repair
        "repair_attempted_count": repair_attempted_count,
        "repair_attempted_rate": round(repair_attempted_count / n, 4) if n else 0.0,
        "repair_applied_count": repair_applied_count,
        "repair_applied_rate": round(repair_applied_count / n, 4) if n else 0.0,
        "repair_success_rate": round(repair_success_rate, 4),
        "repaired_to_correct_count": repaired_to_correct_count,
        "false_positive_repair_count": len(false_positive_repairs),
        "false_positive_repair_rate": round(false_positive_repair_rate, 4),
        "programmatic_repair_count": programmatic_repairs,
        "llm_repair_count": llm_repairs,
        "repair_category_counts": dict(sorted(repair_category_counts.items(), key=lambda x: -x[1])),
        # latency
        "mean_latency_seconds": round(sum(latencies) / len(latencies), 4) if latencies else 0.0,
        "p50_latency_seconds": round(latencies_sorted[len(latencies_sorted) // 2], 4) if latencies_sorted else 0.0,
        "p95_latency_seconds": round(latencies_sorted[int(len(latencies_sorted) * 0.95)], 4) if latencies_sorted else 0.0,
        "total_elapsed_seconds": round(total_elapsed, 2),
        # tokens
        "token_usage": usage_totals,
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
        "phase": "phase8_live",
        "features": [
            "improved_rag",
            "column_grounding",
            "truncation_detection",
            "sqlglot_validation",
            "plan_alignment_verification",
            "one_targeted_repair",
            "programmatic_repairs",
        ],
    }

    with open(output_dir / "config_snapshot.json", "w", encoding="utf-8") as f:
        json.dump(config_snapshot, f, indent=2)

    _write_report(results, summary, output_dir)

    logger.info("=" * 80)
    logger.info("PHASE 8 LIVE BENCHMARK COMPLETE")
    logger.info("=" * 80)
    logger.info(f"Result Correctness: {summary['result_correctness']*100:.1f}%")
    logger.info(f"SQL Execution Success: {summary['sql_execution_success_rate']*100:.1f}%")
    logger.info(f"Semantic Detection Rate: {summary['semantic_detection_rate']*100:.1f}%")
    logger.info(f"Detection Precision: {summary['detection_precision']*100:.1f}%")
    logger.info(f"Repair Applied: {summary['repair_applied_count']}")
    logger.info(f"Repair Success Rate: {summary['repair_success_rate']*100:.1f}%")
    logger.info(f"Repaired-to-correct: {summary['repaired_to_correct_count']}")
    logger.info(f"False-positive repairs: {summary['false_positive_repair_count']}")
    logger.info(f"Mean Latency: {summary['mean_latency_seconds']:.2f}s")
    logger.info(f"P95 Latency: {summary['p95_latency_seconds']:.2f}s")
    logger.info(f"Total Elapsed: {summary['total_elapsed_seconds']:.2f}s")
    logger.info("=" * 80)

    return summary


def _write_report(results: list[dict[str, Any]], summary: dict[str, Any], output_dir: Path) -> None:
    lines = [
        "# Phase 8 Live Benchmark Report",
        "",
        f"**Date:** {datetime.datetime.now().isoformat()}",
        f"**Run:** `{output_dir.name}`",
        "**Benchmark:** frozen 100-query V2 (`benchmark_dataset_v2.json`)",
        "**Method:** Live current pipeline (column grounding + SQLGlot + QueryPlan-aligned semantic verification + one targeted repair).",
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
        f"| Invalid SQL | {summary['invalid_sql_count']} |",
        f"| Hallucinated tables | {summary['hallucinated_table_count']} |",
        f"| Hallucinated columns | {summary['hallucinated_column_count']} |",
        f"| Unsafe SQL | {summary['unsafe_sql_count']} |",
        f"| Plan available | {summary['plan_available_rate']*100:.1f}% ({summary['plan_available_count']}/{summary['total_queries']}) |",
        "",
        "### Detection",
        "",
        "| Metric | Value |",
        "| :--- | :---: |",
        f"| Semantic detection rate (of incorrect, executable) | {summary['semantic_detection_rate']*100:.2f}% |",
        f"| Detection precision | {summary['detection_precision']*100:.2f}% |",
        f"| Detected mismatches | {summary['detected_plan_mismatch_count']} / {summary['incorrect_executable_count']} |",
        f"| Flagged queries | {summary['flagged_count']} |",
        f"| Correct-but-flagged (flag FP rate) | {summary['correct_but_flagged_count']} ({summary['false_positive_flag_rate']*100:.2f}%) |",
        "",
        "### Repair",
        "",
        "| Metric | Value |",
        "| :--- | :---: |",
        f"| Repair attempted | {summary['repair_attempted_count']} ({summary['repair_attempted_rate']*100:.2f}%) |",
        f"| Repair applied | {summary['repair_applied_count']} ({summary['repair_applied_rate']*100:.2f}%) |",
        f"| Repair success rate (applied & previously wrong) | {summary['repair_success_rate']*100:.2f}% |",
        f"| Repaired-to-correct | {summary['repaired_to_correct_count']} |",
        f"| False-positive repairs | {summary['false_positive_repair_count']} ({summary['false_positive_repair_rate']*100:.2f}%) |",
        f"| Programmatic repairs | {summary['programmatic_repair_count']} |",
        f"| LLM repairs | {summary['llm_repair_count']} |",
        "",
        "### Repair categories",
        "",
        "| Category | Count |",
        "| :--- | :---: |",
    ]
    for cat, count in summary.get("repair_category_counts", {}).items():
        lines.append(f"| {cat} | {count} |")

    lines += [
        "",
        "### Latency / Cost",
        "",
        "| Metric | Value |",
        "| :--- | :---: |",
        f"| Mean latency | {summary['mean_latency_seconds']:.2f}s |",
        f"| P50 latency | {summary['p50_latency_seconds']:.2f}s |",
        f"| P95 latency | {summary['p95_latency_seconds']:.2f}s |",
        f"| Total elapsed | {summary['total_elapsed_seconds']:.2f}s |",
        f"| Prompt tokens | {summary.get('token_usage', {}).get('prompt_tokens', 'n/a')} |",
        f"| Completion tokens | {summary.get('token_usage', {}).get('completion_tokens', 'n/a')} |",
        f"| Total tokens | {summary.get('token_usage', {}).get('total_tokens', 'n/a')} |",
        "",
        "---",
        "",
        "## 2. Per-Query Results",
        "",
        "| # | Type | Exec | Correct | Detected | Repair | Pre-correct | Post-correct | Failure |",
        "| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |",
    ]

    for r in results:
        exec_icon = "Y" if r["sql_execution_success"] else "N"
        correct_icon = "Y" if r["result_correct"] else "N"
        detect_icon = "Y" if r["detected_plan_mismatch"] else "-"
        repair_icon = "Y" if r["repair_applied"] else ("T" if r["repair_attempted"] else "-")
        pre_icon = "Y" if r["pre_repair_correct"] else ("N" if r["pre_repair_correct"] is False else "-")
        post_icon = "Y" if r["post_repair_correct"] else ("N" if r["post_repair_correct"] is False else "-")

        failure = r.get("failure_cause") or ("None" if r["result_correct"] else "Unknown")
        if r.get("error") and (not failure or failure == "Unknown"):
            failure = f"Error: {r['error'][:50]}"

        lines.append(
            f"| {r['query_id']} | {r['query_type']} | {exec_icon} | {correct_icon} | "
            f"{detect_icon} | {repair_icon} | {pre_icon} | {post_icon} | {failure} |"
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
        "*Generated by Phase 8 Live Benchmark Runner*",
    ]

    report_path = output_dir / "phase8_report.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info(f"Report written: {report_path}")


def main():
    parser = argparse.ArgumentParser(description="Run Phase 8 live benchmark")
    parser.add_argument("--db", default=str(DB_PATH), help="Path to SQLite database")
    parser.add_argument("--output", default=None, help="Output directory")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of queries")
    args = parser.parse_args()

    if args.output:
        output_dir = Path(args.output)
    else:
        timestamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
        output_dir = ROOT / "results" / "phase8" / f"live_{timestamp}"

    asyncio.run(run_benchmark(args.db, output_dir, args.limit))


if __name__ == "__main__":
    main()
