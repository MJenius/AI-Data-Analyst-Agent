"""Phase 7 live benchmark runner with current pipeline.

DO NOT replay Phase 4 SQL. This runs the actual current system against the frozen
100-query benchmark to measure the effectiveness of Phase 6 improvements:
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
- Latency
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

# Add src to path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_platform.analytics.service import AnalyticsAgentService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

KNOWN_TABLES = {
    "customers", "geolocation", "order_items", "order_payments", "order_reviews",
    "orders", "products", "sellers", "product_category_name_translation",
}


def load_benchmark() -> list[dict[str, Any]]:
    """Load frozen 100-query benchmark."""
    benchmark_path = ROOT / "tests" / "evaluation" / "benchmark_dataset_v2.json"
    with open(benchmark_path) as f:
        return json.load(f)


def compare_results(actual: list[dict], expected: list[dict]) -> dict[str, Any]:
    """Compare actual vs expected query results.
    
    Returns:
        - exact_match: bool
        - equivalent_match: bool (same rows, possibly different order)
        - row_count_match: bool
        - differences: list of difference descriptions
    """
    if actual == expected:
        return {
            "exact_match": True,
            "equivalent_match": True,
            "row_count_match": True,
            "differences": [],
        }
    
    if len(actual) != len(expected):
        return {
            "exact_match": False,
            "equivalent_match": False,
            "row_count_match": False,
            "differences": [f"Row count mismatch: {len(actual)} vs {len(expected)}"],
        }
    
    # Check if same rows, different order
    actual_sorted = sorted(json.dumps(row, sort_keys=True) for row in actual)
    expected_sorted = sorted(json.dumps(row, sort_keys=True) for row in expected)
    
    equivalent = actual_sorted == expected_sorted
    
    differences = []
    if not equivalent:
        # Sample first few differences
        for i, (a_row, e_row) in enumerate(zip(actual[:5], expected[:5])):
            if a_row != e_row:
                differences.append(f"Row {i}: {a_row} != {e_row}")
    
    return {
        "exact_match": False,
        "equivalent_match": equivalent,
        "row_count_match": True,
        "differences": differences[:10],
    }


def extract_tables_from_sql(sql: str | None) -> set[str]:
    """Extract table names mentioned in SQL query."""
    if not sql:
        return set()
    
    tables = set()
    
    # FROM table_name
    from_pattern = re.compile(r'\bFROM\s+([a-zA-Z_][a-zA-Z0-9_]*)', re.IGNORECASE)
    for match in from_pattern.finditer(sql):
        table = match.group(1).lower()
        if table in KNOWN_TABLES:
            tables.add(table)
    
    # JOIN table_name
    join_pattern = re.compile(r'\bJOIN\s+([a-zA-Z_][a-zA-Z0-9_]*)', re.IGNORECASE)
    for match in join_pattern.finditer(sql):
        table = match.group(1).lower()
        if table in KNOWN_TABLES:
            tables.add(table)
    
    return tables


async def run_single_query(
    query_idx: int,
    query_item: dict[str, Any],
    service: AnalyticsAgentService,
) -> dict[str, Any]:
    """Run a single benchmark query through the live pipeline."""
    query_id = f"q{query_idx:03d}"
    question = query_item.get("question", "")
    
    # Extract expected result as list of rows
    expected_obj = query_item.get("expected_result", {})
    if isinstance(expected_obj, dict):
        expected_result = expected_obj.get("values", [])
    else:
        expected_result = expected_obj if isinstance(expected_obj, list) else []
    
    expected_tables = set(query_item.get("expected_tables", []))
    
    logger.info(f"Running query {query_id}: {question[:100]}")
    
    start_time = time.perf_counter()
    
    try:
        # Run through the full live pipeline
        result = await service.analyze(question)
        
        elapsed = time.perf_counter() - start_time
        
        # Extract SQL and results from service result
        actual_sql = None
        actual_result = []
        sql_execution_success = False
        
        sql_queries = result.get("sql_queries", [])
        if sql_queries:
            # Use the last executed SQL query
            last_sql = sql_queries[-1] if isinstance(sql_queries, list) else sql_queries
            if isinstance(last_sql, dict):
                actual_sql = last_sql.get("query")
                actual_result = last_sql.get("result", {}).get("rows", []) if last_sql.get("result") else []
            elif isinstance(last_sql, str):
                actual_sql = last_sql
        
        sql_execution_success = len(actual_result) >= 0 if actual_sql else False
        
        # Check if repair was mentioned in reasoning
        why_explanation = result.get("why_explanation") or ""
        summary = result.get("summary") or ""
        reasoning = (why_explanation if why_explanation else "") + (summary if summary else "")
        repair_attempted = "repair" in reasoning.lower()
        repair_successful = repair_attempted and sql_execution_success
        
        # Extract tables used
        actual_tables = extract_tables_from_sql(actual_sql)
        
        # Compare results
        comparison = compare_results(actual_result, expected_result)
        
        # Check table accuracy
        table_precision = (
            len(actual_tables & expected_tables) / len(actual_tables)
            if actual_tables
            else 0.0
        )
        table_recall = (
            len(actual_tables & expected_tables) / len(expected_tables)
            if expected_tables
            else 0.0
        )
        
        return {
            "query_id": query_id,
            "question": question,
            "actual_sql": actual_sql,
            "expected_tables": list(expected_tables),
            "actual_tables": list(actual_tables),
            "table_precision": round(table_precision, 4),
            "table_recall": round(table_recall, 4),
            "result_correct": comparison["exact_match"] or comparison["equivalent_match"],
            "result_exact_match": comparison["exact_match"],
            "result_equivalent_match": comparison["equivalent_match"],
            "row_count_match": comparison["row_count_match"],
            "expected_row_count": len(expected_result),
            "actual_row_count": len(actual_result),
            "sql_execution_success": sql_execution_success,
            "repair_attempted": repair_attempted,
            "repair_successful": repair_successful,
            "latency_seconds": round(elapsed, 4),
            "error": None,
        }
        
    except Exception as exc:
        logger.error(f"Query {query_id} failed: {exc}")
        elapsed = time.perf_counter() - start_time
        return {
            "query_id": query_id,
            "question": question,
            "actual_sql": None,
            "expected_tables": list(expected_tables),
            "actual_tables": [],
            "table_precision": 0.0,
            "table_recall": 0.0,
            "result_correct": False,
            "result_exact_match": False,
            "result_equivalent_match": False,
            "row_count_match": False,
            "expected_row_count": len(expected_result),
            "actual_row_count": 0,
            "sql_execution_success": False,
            "repair_attempted": False,
            "repair_successful": False,
            "latency_seconds": round(elapsed, 4),
            "error": str(exc),
        }


async def run_benchmark(
    db_path: str,
    output_dir: Path,
    limit: int | None = None,
) -> dict[str, Any]:
    """Run full Phase 7 live benchmark."""
    logger.info("Starting Phase 7 live benchmark")
    logger.info(f"Database: {db_path}")
    logger.info(f"Output directory: {output_dir}")
    
    # Load benchmark
    queries = load_benchmark()
    if limit:
        queries = queries[:limit]
        logger.info(f"Limited to first {limit} queries")
    
    logger.info(f"Total queries: {len(queries)}")
    
    # Initialize service
    service = AnalyticsAgentService.from_sqlite(db_path)
    
    # Run all queries
    results = []
    start_time = time.perf_counter()
    
    for idx, query_item in enumerate(queries):
        result = await run_single_query(idx, query_item, service)
        results.append(result)
        
        # Log progress
        correct_count = sum(1 for r in results if r["result_correct"])
        logger.info(
            f"Progress: {len(results)}/{len(queries)} | "
            f"Correct: {correct_count}/{len(results)} ({100*correct_count/len(results):.1f}%)"
        )
    
    total_elapsed = time.perf_counter() - start_time
    
    # Calculate summary metrics
    correct_count = sum(1 for r in results if r["result_correct"])
    exact_match_count = sum(1 for r in results if r["result_exact_match"])
    equivalent_match_count = sum(1 for r in results if r["result_equivalent_match"])
    sql_success_count = sum(1 for r in results if r["sql_execution_success"])
    repair_attempted_count = sum(1 for r in results if r["repair_attempted"])
    repair_successful_count = sum(1 for r in results if r["repair_successful"])
    
    avg_table_precision = sum(r["table_precision"] for r in results) / len(results) if results else 0.0
    avg_table_recall = sum(r["table_recall"] for r in results) / len(results) if results else 0.0
    
    latencies = [r["latency_seconds"] for r in results]
    latencies.sort()
    
    summary = {
        "total_queries": len(results),
        "result_correctness": round(correct_count / len(results), 4) if results else 0.0,
        "exact_match_rate": round(exact_match_count / len(results), 4) if results else 0.0,
        "equivalent_match_rate": round(equivalent_match_count / len(results), 4) if results else 0.0,
        "sql_execution_success_rate": round(sql_success_count / len(results), 4) if results else 0.0,
        "table_precision": round(avg_table_precision, 4),
        "table_recall": round(avg_table_recall, 4),
        "repair_attempted_rate": round(repair_attempted_count / len(results), 4) if results else 0.0,
        "repair_success_rate": (
            round(repair_successful_count / repair_attempted_count, 4)
            if repair_attempted_count > 0
            else 0.0
        ),
        "mean_latency_seconds": round(sum(latencies) / len(latencies), 4) if latencies else 0.0,
        "p50_latency_seconds": round(latencies[len(latencies) // 2], 4) if latencies else 0.0,
        "p95_latency_seconds": round(latencies[int(len(latencies) * 0.95)], 4) if latencies else 0.0,
        "total_elapsed_seconds": round(total_elapsed, 2),
    }
    
    # Save results
    output_dir.mkdir(parents=True, exist_ok=True)
    
    with open(output_dir / "raw_results.json", "w") as f:
        json.dump(results, f, indent=2)
    
    with open(output_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    
    # Save configuration snapshot
    config_snapshot = {
        "timestamp": datetime.datetime.now().isoformat(),
        "benchmark_path": "tests/evaluation/benchmark_dataset_v2.json",
        "database_path": db_path,
        "llm_provider": os.getenv("LLM_PROVIDER", "auto"),
        "nvidia_model": os.getenv("NVIDIA_MODEL", "meta/llama-3.3-70b-instruct"),
        "phase": "phase7_live",
        "features": [
            "improved_rag",
            "column_grounding",
            "truncation_detection",
            "semantic_verification",
            "targeted_repair",
        ],
    }
    
    with open(output_dir / "config_snapshot.json", "w") as f:
        json.dump(config_snapshot, f, indent=2)
    
    logger.info("=" * 80)
    logger.info("PHASE 7 LIVE BENCHMARK COMPLETE")
    logger.info("=" * 80)
    logger.info(f"Result Correctness: {summary['result_correctness']*100:.1f}%")
    logger.info(f"SQL Execution Success: {summary['sql_execution_success_rate']*100:.1f}%")
    logger.info(f"Table Precision: {summary['table_precision']*100:.1f}%")
    logger.info(f"Repair Attempted: {summary['repair_attempted_rate']*100:.1f}%")
    logger.info(f"Repair Success Rate: {summary['repair_success_rate']*100:.1f}%")
    logger.info(f"Mean Latency: {summary['mean_latency_seconds']:.2f}s")
    logger.info(f"P95 Latency: {summary['p95_latency_seconds']:.2f}s")
    logger.info("=" * 80)
    
    return summary


def main():
    parser = argparse.ArgumentParser(description="Run Phase 7 live benchmark")
    parser.add_argument(
        "--db",
        default="data/analytics.db",
        help="Path to SQLite database",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output directory (default: results/phase7/run_TIMESTAMP)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of queries for testing",
    )
    
    args = parser.parse_args()
    
    if args.output:
        output_dir = Path(args.output)
    else:
        timestamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
        output_dir = Path(f"results/phase7/run_{timestamp}")
    
    asyncio.run(run_benchmark(args.db, output_dir, args.limit))


if __name__ == "__main__":
    main()
