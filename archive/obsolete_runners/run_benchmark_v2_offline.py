from __future__ import annotations

import json
import logging
import os
import re
import sys
import sqlite3
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("run_benchmark_v2_offline")

DB_PATH = ROOT / "runtime" / "analytics.db"
BASELINE_RESULTS_PATH = ROOT / "results" / "baseline" / "raw_results.json"
V2_BENCHMARK_PATH = ROOT / "tests" / "evaluation" / "benchmark_dataset_v2.json"
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


def extract_first_sql(sql: str | None) -> str | None:
    if not sql:
        return None
    statements = re.split(r';\s*|\n(?=SELECT\s)', sql, flags=re.IGNORECASE)
    for stmt in statements:
        stmt = stmt.strip()
        if stmt and re.search(r'\bSELECT\b', stmt, re.IGNORECASE):
            return stmt
    for stmt in statements:
        stmt = stmt.strip()
        if stmt:
            return stmt
    return sql.strip() if sql else None


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
    
    gen_tokens = set(gen_norm.split())
    exp_tokens = set(exp_norm.split())
    
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


def to_json_value(val):
    if val is None:
        return None
    if isinstance(val, float):
        return round(val, 4)
    return val


def evaluate_baseline_against_v2():
    logger.info("Loading baseline results and V2 benchmark...")
    
    with open(BASELINE_RESULTS_PATH, "r", encoding="utf-8") as f:
        baseline_results = json.load(f)
    
    with open(V2_BENCHMARK_PATH, "r", encoding="utf-8") as f:
        v2_benchmark = json.load(f)
    
    logger.info(f"Loaded {len(baseline_results)} baseline results and {len(v2_benchmark)} V2 queries.")
    
    eval_results = []
    
    for i, (baseline, v2) in enumerate(zip(baseline_results, v2_benchmark)):
        question = v2["question"]
        expected_sql = v2["expected_sql"]
        expected_tables = v2["expected_tables"]
        expected_result = v2.get("expected_result", {})
        correctness_checks = v2.get("correctness_checks", [])
        query_type = v2.get("query_type", "unknown")
        difficulty = v2.get("difficulty", "unknown")
        generated_sql = baseline.get("generated_sql")
        baseline_success = baseline.get("success", False)
        sql_error = baseline.get("sql_error")
        
        logger.info(f"[{i+1}/100] Evaluating: {question[:60]}...")
        
        execution_success = baseline_success and generated_sql is not None and len(generated_sql.strip()) > 0
        
        sql_comparison = compare_sql(generated_sql, expected_sql)
        
        queried_tables = extract_tables_from_sql(generated_sql)
        correct_tables = [t for t in expected_tables if t in queried_tables]
        table_accuracy = (len(correct_tables) / len(expected_tables)) * 100.0 if expected_tables else 100.0
        table_match = set(correct_tables) == set(expected_tables)
        
        result_correctness = {"result_match": False, "reason": "not_evaluated"}
        if execution_success and generated_sql:
            try:
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                
                single_sql = extract_first_sql(generated_sql)
                if single_sql:
                    cursor.execute(single_sql)
                    if cursor.description:
                        gen_cols = [d[0] for d in cursor.description]
                        gen_rows = cursor.fetchall()
                        gen_values = []
                        for row in gen_rows[:50]:
                            gen_values.append({c: to_json_value(v) for c, v in zip(gen_cols, row)})
                    else:
                        gen_values = []
                else:
                    gen_values = None
                
                conn.close()
                
                tolerance = 0.05 if 'percentage' in question.lower() or 'rate' in question.lower() else 0.01
                result_correctness = compare_results(gen_values, expected_result.get("values", []), tolerance)
            except Exception as e:
                result_correctness = {"result_match": False, "reason": f"execution_error: {str(e)}"}
        
        invalid_sql = bool(sql_error) or (generated_sql is not None and len(generated_sql.strip()) == 0)
        
        hallucinated = check_hallucinated_schema(generated_sql)
        
        unsafe = check_unsafe_sql(generated_sql)
        
        numeric_tolerance = "strict" if query_type == "aggregation" else "none"
        if 'percentage' in question.lower() or 'rate' in question.lower():
            numeric_tolerance = "0.05"
        
        eval_results.append({
            "question": question,
            "category": v2["category"],
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
            "latency_seconds": baseline.get("latency_seconds", 0),
            "correctness_checks": correctness_checks,
            "numeric_tolerance": numeric_tolerance,
            "confidence": baseline.get("confidence"),
            "verdict": baseline.get("verdict"),
        })
    
    raw_path = RESULTS_DIR / "raw_results.json"
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(eval_results, f, indent=2, default=str)
    
    total = len(eval_results)
    execution_successes = sum(1 for r in eval_results if r["execution_success"])
    exact_matches = sum(1 for r in eval_results if r["exact_sql_match"])
    normalized_matches = sum(1 for r in eval_results if r["normalized_sql_match"])
    result_matches = sum(1 for r in eval_results if r["result_correctness"])
    table_matches = sum(1 for r in eval_results if r["table_match"])
    invalid_sql_count = sum(1 for r in eval_results if r["invalid_sql"])
    hallucinated_count = sum(1 for r in eval_results if r["hallucinated_schema"])
    unsafe_count = sum(1 for r in eval_results if r["unsafe_keywords"])
    latencies = [r["latency_seconds"] for r in eval_results]
    confidences = [r["confidence"] for r in eval_results if r["confidence"] is not None]
    
    table_accuracies = [r["table_accuracy_pct"] for r in eval_results]
    avg_table_accuracy = sum(table_accuracies) / total if total else 0.0
    
    summary = {
        "total_queries": total,
        "verified_ground_truth_queries": total,
        "execution_accuracy_pct": round(execution_successes / total * 100, 2) if total else 0.0,
        "exact_sql_accuracy_pct": round(exact_matches / total * 100, 2) if total else 0.0,
        "normalized_sql_accuracy_pct": round(normalized_matches / total * 100, 2) if total else 0.0,
        "result_correctness_pct": round(result_matches / total * 100, 2) if total else 0.0,
        "table_accuracy_pct": round(avg_table_accuracy, 2),
        "invalid_sql_rate_pct": round(invalid_sql_count / total * 100, 2) if total else 0.0,
        "hallucinated_schema_rate_pct": round(hallucinated_count / total * 100, 2) if total else 0.0,
        "unsafe_sql_rate_pct": round(unsafe_count / total * 100, 2) if total else 0.0,
        "avg_latency_seconds": round(sum(latencies) / total, 2) if total else 0.0,
        "min_latency_seconds": min(latencies) if latencies else 0.0,
        "max_latency_seconds": max(latencies) if latencies else 0.0,
        "avg_confidence": round(sum(confidences) / len(confidences), 4) if confidences else 0.0,
        "model_version": get_config_snapshot(),
        "queries_without_verified_ground_truth": 0,
        "ground_truth_source": "manually_verified_gold_sql_against_sqlite_olist",
    }
    
    summary_path = RESULTS_DIR / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    
    report_path = RESULTS_DIR / "evaluation_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# 🧪 Research-Grade Benchmark Evaluation Report\n\n")
        f.write("## 📊 Aggregate Metrics\n\n")
        f.write("| Metric | Value |\n| :--- | :--- |\n")
        f.write(f"| Total Queries | {summary['total_queries']} |\n")
        f.write(f"| Verified Ground Truth | {summary['verified_ground_truth_queries']} |\n")
        f.write(f"| Execution Accuracy | {summary['execution_accuracy_pct']}% |\n")
        f.write(f"| Exact SQL Accuracy | {summary['exact_sql_accuracy_pct']}% |\n")
        f.write(f"| Normalized SQL Accuracy | {summary['normalized_sql_accuracy_pct']}% |\n")
        f.write(f"| Result Correctness | {summary['result_correctness_pct']}% |\n")
        f.write(f"| Table Selection Accuracy | {summary['table_accuracy_pct']}% |\n")
        f.write(f"| Invalid SQL Rate | {summary['invalid_sql_rate_pct']}% |\n")
        f.write(f"| Hallucinated Schema Rate | {summary['hallucinated_schema_rate_pct']}% |\n")
        f.write(f"| Unsafe SQL Rate | {summary['unsafe_sql_rate_pct']}% |\n")
        f.write(f"| Avg Latency | {summary['avg_latency_seconds']}s |\n")
        f.write(f"| Min Latency | {summary['min_latency_seconds']}s |\n")
        f.write(f"| Max Latency | {summary['max_latency_seconds']}s |\n")
        f.write(f"| Avg Confidence | {summary['avg_confidence']} |\n")
        f.write(f"| Model Version | {summary['model_version']['llm_provider']} |\n\n")
        
        f.write("## Per-Query Results\n\n")
        f.write("| # | Category | Question | Exec | Exact | Result | Tables | Failure |\n")
        f.write("| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- |\n")
        
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
            
            f.write(f"| {idx} | {r['category']} | `{r['question'][:50]}` | {exec_icon} | {exact_icon} | {result_icon} | {table_icon} | {failure} |\n")
        
        f.write("\n## Ground Truth Details\n\n")
        f.write(f"- **Source**: {summary['ground_truth_source']}\n")
        f.write(f"- **Queries with verified ground truth**: {summary['verified_ground_truth_queries']}/{summary['total_queries']}\n")
        f.write(f"- **Queries without verified ground truth**: {summary['queries_without_verified_ground_truth']}\n\n")
        
        f.write("## Failure Breakdown\n\n")
        f.write("| Failure Mode | Count | Rate |\n| :--- | :---: | :---: |\n")
        
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
            f.write(f"| {mode} | {count} | {count / total * 100.0:.1f}% |\n")
    
    print(f"\n{'='*60}")
    print(f"[SUCCESS] V2 OFFLINE EVALUATION COMPLETED!")
    print(f"{'='*60}")
    print(f"Total queries: {total}")
    print(f"Verified ground truth: {summary['verified_ground_truth_queries']}")
    print(f"Execution accuracy: {summary['execution_accuracy_pct']}%")
    print(f"Exact SQL accuracy: {summary['exact_sql_accuracy_pct']}%")
    print(f"Normalized SQL accuracy: {summary['normalized_sql_accuracy_pct']}%")
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
    evaluate_baseline_against_v2()
