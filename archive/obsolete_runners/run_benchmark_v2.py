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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("run_benchmark_v2")

DB_PATH = ROOT / "runtime" / "analytics.db"
BENCHMARK_PATH = ROOT / "tests" / "evaluation" / "benchmark_dataset_v2.json"
RESULTS_DIR = ROOT / "results" / "v2_benchmark"
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


def normalize_sql(sql: str | None) -> str:
    if not sql:
        return ""
    sql = sql.lower()
    sql = re.sub(r'\s+', ' ', sql)
    sql = re.sub(r"`", "", sql)
    sql = sql.strip()
    if sql.endswith(';'):
        sql = sql[:-1]
    return sql.strip()


def extract_tables_from_sql(sql: str | None) -> list[str]:
    if not sql:
        return []
    cleaned = re.sub(r'\s+', ' ', sql.lower())
    found = []
    for table in KNOWN_TABLES:
        if re.search(rf"\b{table}\b", cleaned):
            found.append(table)
    return found


def check_hallucinated_schema(sql: str | None) -> list[str]:
    if not sql:
        return []
    cleaned = re.sub(r'\s+', ' ', sql.lower())
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


def compare_sql(gen_sql: str | None, expected_sql: str) -> dict[str, Any]:
    if not gen_sql:
        return {"exact_match": False, "normalized_match": False, "reason": "no_sql_generated"}
    
    gen_norm = normalize_sql(gen_sql)
    exp_norm = normalize_sql(expected_sql)
    
    if gen_norm == exp_norm:
        return {"exact_match": True, "normalized_match": True, "reason": "exact_match"}
    
    # Check if it's semantically equivalent by normalizing whitespace and aliases
    # Simple heuristic: if normalized versions are very similar
    gen_tokens = set(gen_norm.split())
    exp_tokens = set(exp_norm.split())
    
    # Remove common SQL noise tokens for comparison
    noise = {'select', 'from', 'where', 'group', 'by', 'order', 'asc', 'desc', 
             'and', 'or', 'on', 'join', 'left', 'right', 'inner', 'outer', 'as',
             'into', 'values', 'limit', 'offset', 'having', 'distinct', 'case',
             'when', 'then', 'else', 'end', 'round', 'avg', 'sum', 'count', 'max',
             'min', 'cast', 'integer', 'real', 'text', 'bool', 'boolean', 'date',
             'timestamp', 'julianday', 'strftime', 'lag', 'row_number', 'ntile',
             'ceil', 'floor'}
    
    gen_semantic = gen_tokens - noise
    exp_semantic = exp_tokens - noise
    
    if gen_semantic == exp_semantic:
        return {"exact_match": False, "normalized_match": True, "reason": "semantic_match"}
    
    # Calculate token overlap
    if gen_semantic:
        overlap = len(gen_semantic & exp_semantic) / len(gen_semantic | exp_semantic)
    else:
        overlap = 0.0
    
    return {
        "exact_match": False, 
        "normalized_match": False, 
        "reason": "different_sql",
        "semantic_similarity": round(overlap, 3)
    }


def compare_results(gen_values: list[dict] | None, expected_values: list[dict], 
                     tolerance: float = 0.01) -> dict[str, Any]:
    if gen_values is None:
        return {"result_match": False, "reason": "no_result"}
    
    if len(gen_values) != len(expected_values):
        return {
            "result_match": False, 
            "reason": f"row_count_mismatch: got {len(gen_values)}, expected {len(expected_values)}"
        }
    
    mismatches = []
    tolerance_violations = []
    
    for i, (gen_row, exp_row) in enumerate(zip(gen_values, expected_values)):
        if set(gen_row.keys()) != set(exp_row.keys()):
            mismatches.append({
                "row": i,
                "reason": "column_mismatch",
                "got": list(gen_row.keys()),
                "expected": list(exp_row.keys())
            })
            continue
        
        for col in gen_row:
            gv = gen_row[col]
            ev = exp_row[col]
            
            if gv is None and ev is None:
                continue
            if gv is None or ev is None:
                mismatches.append({"row": i, "col": col, "got": gv, "expected": ev})
                continue
            
            if isinstance(gv, (int, float)) and isinstance(ev, (int, float)):
                if abs(gv - ev) > tolerance and abs(gv - ev) / max(abs(ev), 1e-9) > tolerance:
                    tolerance_violations.append({
                        "row": i, "col": col, "got": gv, "expected": ev, "diff": abs(gv - ev)
                    })
            elif str(gv) != str(ev):
                mismatches.append({"row": i, "col": col, "got": gv, "expected": ev})
    
    return {
        "result_match": len(mismatches) == 0 and len(tolerance_violations) == 0,
        "mismatches": mismatches[:10],
        "tolerance_violations": tolerance_violations[:10],
        "reason": "match" if (len(mismatches) == 0 and len(tolerance_violations) == 0) else "value_mismatch"
    }


def run_gold_sql(sql: str) -> dict[str, Any]:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute(sql)
        cols = [d[0] for d in cursor.description]
        rows = cursor.fetchall()
        values = []
        for row in rows[:50]:
            values.append({c: to_json_value(v) for c, v in zip(cols, row)})
        return {
            "success": True,
            "columns": cols,
            "values": values,
            "row_count": len(rows)
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        conn.close()


def to_json_value(val):
    if val is None:
        return None
    if isinstance(val, float):
        return round(val, 4)
    return val


async def evaluate_query_v2(service: AnalyticsAgentService, benchmark: dict[str, Any]) -> dict[str, Any]:
    question = benchmark["question"]
    category = benchmark["category"]
    expected_sql = benchmark["expected_sql"]
    expected_tables = benchmark["expected_tables"]
    expected_result = benchmark.get("expected_result", {})
    correctness_checks = benchmark.get("correctness_checks", [])
    query_type = benchmark.get("query_type", "unknown")
    difficulty = benchmark.get("difficulty", "unknown")
    
    logger.info(f"Running V2 Benchmark: [{category}] -> '{question}'")
    
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
        logger.error(f"Execution failed: {exc}")
    
    # 1. SQL execution success
    execution_success = success and not sql_error and generated_sql is not None
    
    # 2. Exact SQL match
    sql_comparison = compare_sql(generated_sql, expected_sql)
    
    # 3. Table selection correctness
    queried_tables = extract_tables_from_sql(generated_sql)
    correct_tables = [t for t in expected_tables if t in queried_tables]
    table_accuracy = (len(correct_tables) / len(expected_tables)) * 100.0 if expected_tables else 100.0
    table_match = set(correct_tables) == set(expected_tables)
    
    # 4. Result correctness
    result_correctness = {"result_match": False, "reason": "not_evaluated"}
    if execution_success and generated_sql:
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute(generated_sql)
            gen_cols = [d[0] for d in cursor.description]
            gen_rows = cursor.fetchall()
            gen_values = []
            for row in gen_rows[:50]:
                gen_values.append({c: to_json_value(v) for c, v in zip(gen_cols, row)})
            conn.close()
            
            tolerance = 0.05 if 'percentage' in question.lower() or 'rate' in question.lower() else 0.01
            result_correctness = compare_results(gen_values, expected_result.get("values", []), tolerance)
        except Exception as e:
            result_correctness = {"result_match": False, "reason": f"execution_error: {str(e)}"}
    
    # 5. Invalid SQL
    invalid_sql = bool(sql_error) or (generated_sql is not None and len(generated_sql.strip()) == 0)
    
    # 6. Schema hallucination
    hallucinated = check_hallucinated_schema(generated_sql)
    
    # 7. Unsafe SQL
    unsafe = check_unsafe_sql(generated_sql)
    
    # Determine numeric tolerance needed
    numeric_tolerance = "strict" if query_type == "aggregation" else "none"
    if 'percentage' in question.lower() or 'rate' in question.lower():
        numeric_tolerance = "0.05"
    
    return {
        "question": question,
        "category": category,
        "query_type": query_type,
        "difficulty": difficulty,
        "expected_tables": expected_tables,
        "queried_tables": queried_tables,
        "table_accuracy_pct": round(table_accuracy, 2),
        "table_match": table_match,
        "expected_sql": expected_sql,
        "generated_sql": generated_sql,
        "exact_sql_match": sql_comparison.get("exact_match", False),
        "normalized_sql_match": sql_comparison.get("normalized_match", False),
        "sql_comparison_reason": sql_comparison.get("reason", ""),
        "execution_success": execution_success,
        "result_correctness": result_correctness.get("result_match", False),
        "result_comparison": result_correctness,
        "invalid_sql": invalid_sql,
        "sql_error": sql_error,
        "hallucinated_schema": hallucinated,
        "unsafe_keywords": unsafe,
        "latency_seconds": round(elapsed, 2),
        "correctness_checks": correctness_checks,
        "numeric_tolerance": numeric_tolerance,
        "confidence": report_data.get("confidence") if report_data else None,
        "verdict": report_data.get("verdict") if report_data else None,
    }


def write_progressive_report_v2(eval_results: list[dict[str, Any]], all_selected: list[dict[str, Any]], completed: bool = False):
    total_runs = len(all_selected)
    completed_runs = len(eval_results)
    
    if completed_runs == 0:
        return
    
    execution_successes = sum(1 for r in eval_results if r["execution_success"])
    exact_matches = sum(1 for r in eval_results if r["exact_sql_match"])
    result_matches = sum(1 for r in eval_results if r["result_correctness"])
    table_matches = sum(1 for r in eval_results if r["table_match"])
    invalid_sql_count = sum(1 for r in eval_results if r["invalid_sql"])
    hallucinated_count = sum(1 for r in eval_results if r["hallucinated_schema"])
    unsafe_count = sum(1 for r in eval_results if r["unsafe_keywords"])
    
    avg_latency = sum(r["latency_seconds"] for r in eval_results) / completed_runs
    avg_confidence = sum(r["confidence"] for r in eval_results if r["confidence"] is not None) / completed_runs if any(r["confidence"] is not None for r in eval_results) else 0.0
    
    execution_rate = (execution_successes / completed_runs) * 100.0
    exact_match_rate = (exact_matches / completed_runs) * 100.0
    result_match_rate = (result_matches / completed_runs) * 100.0
    table_match_rate = (table_matches / completed_runs) * 100.0
    
    status_label = "✅ COMPLETED" if completed else "⚙️ IN PROGRESS..."
    
    markdown_content = f"""# 🧪 Research-Grade Benchmark Evaluation Report (Status: {status_label})

## 📊 High-Level Metrics (Completed {completed_runs}/{total_runs})

| Metric | Actual |
| :--- | :---: |
| **SQL Execution Success Rate** | **{execution_rate:.1f}%** |
| **Exact SQL Match Rate** | **{exact_match_rate:.1f}%** |
| **Result Correctness Rate** | **{result_match_rate:.1f}%** |
| **Table Selection Accuracy** | **{table_match_rate:.1f}%** |
| **Invalid SQL Rate** | **{invalid_sql_count / completed_runs * 100.0:.1f}%** |
| **Hallucinated Schema Rate** | **{hallucinated_count / completed_runs * 100.0:.1f}%** |
| **Unsafe SQL Rate** | **{unsafe_count / completed_runs * 100.0:.1f}%** |
| **Average Latency** | **{avg_latency:.2f}s** |
| **Average Confidence** | **{avg_confidence * 100.0:.1f}%** |

---

## 📁 Per-Query Results

| # | Category | Question | Exec | Exact | Result | Tables | Failure |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- |
"""
    
    for idx, r in enumerate(eval_results, 1):
        exec_icon = "✅" if r["execution_success"] else "❌"
        exact_icon = "✅" if r["exact_sql_match"] else "❌"
        result_icon = "✅" if r["result_correctness"] else "❌"
        table_icon = f"{r['table_accuracy_pct']:.0f}%"
        
        failure = "None"
        if not r["execution_success"]:
            failure = "Execution Failed"
        elif r["invalid_sql"]:
            failure = "Invalid SQL"
        elif r["hallucinated_schema"]:
            failure = "Hallucinated Schema"
        elif r["unsafe_keywords"]:
            failure = "Unsafe SQL"
        elif not r["table_match"]:
            failure = "Wrong Tables"
        elif not r["result_correctness"]:
            failure = r["result_comparison"].get("reason", "Wrong Result")
        
        markdown_content += f"| {idx} | {r['category']} | `{r['question'][:50]}` | {exec_icon} | {exact_icon} | {result_icon} | {table_icon} | {failure} |\n"
    
    markdown_content += """
---

## 🛠️ Failure Breakdown

| Failure Mode | Count | Rate |
| :--- | :---: | :---: |
"""
    
    failure_counts = {}
    for r in eval_results:
        if not r["execution_success"]:
            failure_counts["Execution Failed"] = failure_counts.get("Execution Failed", 0) + 1
        elif r["invalid_sql"]:
            failure_counts["Invalid SQL"] = failure_counts.get("Invalid SQL", 0) + 1
        elif r["hallucinated_schema"]:
            failure_counts["Hallucinated Schema"] = failure_counts.get("Hallucinated Schema", 0) + 1
        elif r["unsafe_keywords"]:
            failure_counts["Unsafe SQL"] = failure_counts.get("Unsafe SQL", 0) + 1
        elif not r["table_match"]:
            failure_counts["Wrong Tables"] = failure_counts.get("Wrong Tables", 0) + 1
        elif not r["result_correctness"]:
            failure_counts["Wrong Result"] = failure_counts.get("Wrong Result", 0) + 1
    
    for mode, count in sorted(failure_counts.items(), key=lambda x: -x[1]):
        markdown_content += f"| {mode} | {count} | {count / completed_runs * 100.0:.1f}% |\n"
    
    markdown_content += f"""
---

*Generated by Kilo Evaluation Harness*
"""
    
    report_path = RESULTS_DIR / "evaluation_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(markdown_content)


async def run_evaluation_v2():
    logger.info("Initializing V2 Research-Grade Evaluation Harness...")
    
    if not DB_PATH.exists():
        logger.error(f"Database not found at {DB_PATH}")
        return
    
    if not BENCHMARK_PATH.exists():
        logger.error(f"V2 benchmark not found at {BENCHMARK_PATH}")
        return
    
    with open(BENCHMARK_PATH, "r", encoding="utf-8") as f:
        benchmarks = json.load(f)
    
    logger.info(f"Loaded {len(benchmarks)} V2 benchmark queries.")
    
    write_progressive_report_v2([], benchmarks, completed=False)
    
    service = AnalyticsAgentService.from_sqlite(DB_PATH)
    
    eval_results = []
    for i, benchmark in enumerate(benchmarks, 1):
        res = await evaluate_query_v2(service, benchmark)
        eval_results.append(res)
        
        write_progressive_report_v2(eval_results, benchmarks, completed=False)
        logger.info(
            f"[{i}/{len(benchmarks)}] exec={res['execution_success']} "
            f"exact={res['exact_sql_match']} result={res['result_correctness']} "
            f"tables={res['table_accuracy_pct']}% "
            f"latency={res['latency_seconds']}s"
        )
        await asyncio.sleep(0.5)
    
    write_progressive_report_v2(eval_results, benchmarks, completed=True)
    
    # Save raw results
    raw_path = RESULTS_DIR / "raw_results.json"
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(eval_results, f, indent=2, default=str)
    
    # Compute summary
    total = len(eval_results)
    execution_successes = sum(1 for r in eval_results if r["execution_success"])
    exact_matches = sum(1 for r in eval_results if r["exact_sql_match"])
    result_matches = sum(1 for r in eval_results if r["result_correctness"])
    table_matches = sum(1 for r in eval_results if r["table_match"])
    invalid_sql_count = sum(1 for r in eval_results if r["invalid_sql"])
    hallucinated_count = sum(1 for r in eval_results if r["hallucinated_schema"])
    unsafe_count = sum(1 for r in eval_results if r["unsafe_keywords"])
    latencies = [r["latency_seconds"] for r in eval_results]
    confidences = [r["confidence"] for r in eval_results if r["confidence"] is not None]
    
    summary = {
        "total_queries": total,
        "execution_accuracy_pct": round(execution_successes / total * 100, 2) if total else 0.0,
        "exact_sql_accuracy_pct": round(exact_matches / total * 100, 2) if total else 0.0,
        "result_correctness_pct": round(result_matches / total * 100, 2) if total else 0.0,
        "table_accuracy_pct": round(table_matches / total * 100, 2) if total else 0.0,
        "invalid_sql_rate_pct": round(invalid_sql_count / total * 100, 2) if total else 0.0,
        "hallucinated_schema_rate_pct": round(hallucinated_count / total * 100, 2) if total else 0.0,
        "unsafe_sql_rate_pct": round(unsafe_count / total * 100, 2) if total else 0.0,
        "avg_latency_seconds": round(sum(latencies) / total, 2) if total else 0.0,
        "min_latency_seconds": min(latencies) if latencies else 0.0,
        "max_latency_seconds": max(latencies) if latencies else 0.0,
        "avg_confidence": round(sum(confidences) / len(confidences), 4) if confidences else 0.0,
        "model_version": get_config_snapshot(),
    }
    
    summary_path = RESULTS_DIR / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    
    print(f"\n{'='*60}")
    print(f"[SUCCESS] V2 BENCHMARK EVALUATION COMPLETED!")
    print(f"{'='*60}")
    print(f"Total queries: {total}")
    print(f"Execution accuracy: {summary['execution_accuracy_pct']}%")
    print(f"Exact SQL accuracy: {summary['exact_sql_accuracy_pct']}%")
    print(f"Result correctness: {summary['result_correctness_pct']}%")
    print(f"Table accuracy: {summary['table_accuracy_pct']}%")
    print(f"Invalid SQL rate: {summary['invalid_sql_rate_pct']}%")
    print(f"Hallucinated schema: {summary['hallucinated_schema_rate_pct']}%")
    print(f"Unsafe SQL rate: {summary['unsafe_sql_rate_pct']}%")
    print(f"Avg latency: {summary['avg_latency_seconds']}s")
    print(f"Report saved at: {RESULTS_DIR}")
    print(f"{'='*60}\n")
    
    return summary


if __name__ == "__main__":
    asyncio.run(run_evaluation_v2())
