from __future__ import annotations

import asyncio
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

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_platform.analytics.service import AnalyticsAgentService

DB_PATH = ROOT / "runtime" / "analytics.db"
DATASET_PATH = Path(__file__).resolve().parent / "benchmark_dataset.json"
RESULTS_DIR = ROOT / "results" / "baseline"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

KNOWN_TABLES = {
    "customers",
    "geolocation",
    "order_items",
    "order_payments",
    "order_reviews",
    "orders",
    "products",
    "sellers",
    "product_category_name_translation",
}

BLOCKED_KEYWORDS = {
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "create",
    "truncate",
    "replace",
    "attach",
    "detach",
    "vacuum",
    "pragma",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("run_baseline")


def get_config_snapshot() -> dict[str, Any]:
    return {
        "llm_provider": os.getenv("LLM_PROVIDER", "auto"),
        "groq_model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        "groq_api_key_present": bool(os.getenv("GROQ_API_KEY")),
        "gemini_model": os.getenv("GEMINI_MODEL", "gemini-1.5-flash"),
        "gemini_api_key_present": bool(os.getenv("GEMINI_API_KEY")),
        "ollama_model": os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b"),
        "db_path": str(DB_PATH),
        "log_level": os.getenv("LOG_LEVEL", "INFO"),
    }


def extract_tables_from_sql(sql: str | None) -> list[str]:
    if not sql:
        return []
    cleaned = re.sub(r"\s+", " ", sql.lower())
    found = []
    for table in KNOWN_TABLES:
        if re.search(rf"\b{table}\b", cleaned):
            found.append(table)
    return found


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


async def evaluate_query(service: AnalyticsAgentService, benchmark: dict[str, Any]) -> dict[str, Any]:
    question = benchmark["question"]
    category = benchmark["category"]
    expected_tables = benchmark["expected_tables"]

    start_time = time.perf_counter()
    sql_error = None
    generated_sql = None
    report_data = None
    success = False

    try:
        result = await service.analyze(question)
        elapsed = time.perf_counter() - start_time

        sql_queries_list = result.get("sql_queries", [])
        generated_sql = "\n".join(sql_queries_list) if sql_queries_list else None
        report_data = result
        success = result.get("status") == "completed" or len(sql_queries_list) > 0

    except Exception as exc:
        elapsed = time.perf_counter() - start_time
        sql_error = str(exc)
        logger.error(f"Query failed: {exc}")

    queried_tables = extract_tables_from_sql(generated_sql)
    correct_tables = [t for t in expected_tables if t in queried_tables]
    table_accuracy = (len(correct_tables) / len(expected_tables)) * 100.0 if expected_tables else 100.0

    hallucinated = check_hallucinated_schema(generated_sql)
    unsafe = check_unsafe_sql(generated_sql)

    return {
        "question": question,
        "category": category,
        "expected_tables": expected_tables,
        "queried_tables": queried_tables,
        "table_accuracy_pct": round(table_accuracy, 2),
        "generated_sql": generated_sql,
        "success": success and not sql_error,
        "sql_error": sql_error,
        "latency_seconds": round(elapsed, 2),
        "hallucinated_schema": hallucinated,
        "unsafe_keywords": unsafe,
        "confidence": report_data.get("confidence") if report_data else None,
        "verdict": report_data.get("verdict") if report_data else None,
    }


async def main() -> None:
    logger.info("Loading baseline benchmark dataset...")

    if not DB_PATH.exists():
        logger.error(f"Database not found at {DB_PATH}")
        sys.exit(1)

    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        benchmarks = json.load(f)

    logger.info(f"Loaded {len(benchmarks)} benchmark queries.")

    service = AnalyticsAgentService.from_sqlite(DB_PATH)

    results = []
    for i, benchmark in enumerate(benchmarks, 1):
        logger.info(
            f"[{i}/{len(benchmarks)}] Running: [{benchmark['category']}] {benchmark['question']}"
        )
        res = await evaluate_query(service, benchmark)
        results.append(res)
        logger.info(
            f"  -> success={res['success']}, latency={res['latency_seconds']}s, "
            f"table_acc={res['table_accuracy_pct']}%, "
            f"hallucinated={res['hallucinated_schema']}, "
            f"unsafe={res['unsafe_keywords']}"
        )
        await asyncio.sleep(0.5)

    raw_path = RESULTS_DIR / "raw_results.json"
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info(f"Raw results saved to {raw_path}")

    total = len(results)
    successful = sum(1 for r in results if r["success"])
    failed = total - successful
    invalid_sql = sum(1 for r in results if r["sql_error"] is not None)
    hallucinated_count = sum(1 for r in results if r["hallucinated_schema"])
    unsafe_count = sum(1 for r in results if r["unsafe_keywords"])
    latencies = [r["latency_seconds"] for r in results]
    avg_latency = sum(latencies) / total if total else 0.0
    confidences = [r["confidence"] for r in results if r["confidence"] is not None]
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
    table_accuracies = [r["table_accuracy_pct"] for r in results]
    avg_table_accuracy = sum(table_accuracies) / total if total else 0.0

    summary = {
        "total_queries": total,
        "execution_accuracy_pct": round(successful / total * 100, 2) if total else 0.0,
        "exact_sql_accuracy": "UNAVAILABLE - no expected SQL strings in benchmark dataset",
        "invalid_sql_rate_pct": round(invalid_sql / total * 100, 2) if total else 0.0,
        "hallucinated_schema_rate_pct": round(hallucinated_count / total * 100, 2) if total else 0.0,
        "unsafe_sql_rate_pct": round(unsafe_count / total * 100, 2) if total else 0.0,
        "avg_latency_seconds": round(avg_latency, 2),
        "min_latency_seconds": min(latencies) if latencies else 0.0,
        "max_latency_seconds": max(latencies) if latencies else 0.0,
        "avg_confidence": round(avg_confidence, 4),
        "avg_table_accuracy_pct": round(avg_table_accuracy, 2),
        "token_usage": "UNAVAILABLE - LLM clients do not expose token counts in current implementation",
        "model_version": get_config_snapshot(),
    }

    summary_path = RESULTS_DIR / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    logger.info(f"Summary saved to {summary_path}")

    config_path = RESULTS_DIR / "config_snapshot.json"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(get_config_snapshot(), f, indent=2)
    logger.info(f"Config saved to {config_path}")

    report_path = RESULTS_DIR / "baseline_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# NL-to-SQL Baseline Report\n\n")
        f.write(f"**Date:** {time.strftime('%Y-%m-%d %H:%M:%S %Z')}\n\n")
        f.write("## Aggregate Metrics\n\n")
        f.write("| Metric | Value |\n| :--- | :--- |\n")
        f.write(f"| Total Queries | {summary['total_queries']} |\n")
        f.write(f"| Execution Accuracy | {summary['execution_accuracy_pct']}% |\n")
        f.write(f"| Exact SQL Accuracy | {summary['exact_sql_accuracy']} |\n")
        f.write(f"| Invalid SQL Rate | {summary['invalid_sql_rate_pct']}% |\n")
        f.write(f"| Hallucinated Schema Rate | {summary['hallucinated_schema_rate_pct']}% |\n")
        f.write(f"| Unsafe SQL Rate | {summary['unsafe_sql_rate_pct']}% |\n")
        f.write(f"| Avg Latency | {summary['avg_latency_seconds']}s |\n")
        f.write(f"| Avg Confidence | {summary['avg_confidence']} |\n")
        f.write(f"| Avg Table Accuracy | {summary['avg_table_accuracy_pct']}% |\n")
        f.write(f"| Token Usage | {summary['token_usage']} |\n\n")
        f.write("## Model/Version\n\n")
        for k, v in get_config_snapshot().items():
            f.write(f"- **{k}**: {v}\n")
        f.write("\n## Per-Query Results\n\n")
        for r in results:
            status = "✅" if r["success"] else "❌"
            f.write(
                f"- {status} `{r['question']}` | {r['category']} | "
                f"{r['latency_seconds']}s | tables={r['table_accuracy_pct']}% | "
                f"hallucinated={r['hallucinated_schema']} | unsafe={r['unsafe_keywords']}\n"
            )

    logger.info(f"Report saved to {report_path}")

    print(f"\nBaseline complete: {successful}/{total} successful ({summary['execution_accuracy_pct']}%)")
    print(f"Results in: {RESULTS_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
