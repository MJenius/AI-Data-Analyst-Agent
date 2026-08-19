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
logger = logging.getLogger("run_benchmark_v3")

DB_PATH = ROOT / "runtime" / "analytics.db"
BASELINE_RESULTS_PATH = ROOT / "results" / "baseline" / "raw_results.json"
V2_BENCHMARK_PATH = ROOT / "tests" / "evaluation" / "benchmark_dataset_v2.json"
RESULTS_DIR = ROOT / "results" / "v3_benchmark"
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
    "insert", "update", "delete", "drop", "alter", "create",
    "truncate", "replace", "attach", "detach", "vacuum", "pragma",
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


def compare_sql_form(gen_sql: str | None, expected_sql: str) -> dict[str, Any]:
    """Compare SQL form similarity - NOT semantic correctness."""
    if not gen_sql:
        return {"exact_match": False, "normalized_match": False, "similarity": 0.0}
    
    gen_norm = normalize_sql(gen_sql)
    exp_norm = normalize_sql(expected_sql)
    
    if gen_norm == exp_norm:
        return {"exact_match": True, "normalized_match": True, "similarity": 1.0}
    
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
        return {"exact_match": False, "normalized_match": True, "similarity": 0.9}
    
    if gen_semantic:
        overlap = len(gen_semantic & exp_semantic) / len(gen_semantic | exp_semantic)
    else:
        overlap = 0.0
    
    return {
        "exact_match": False,
        "normalized_match": False,
        "similarity": round(overlap, 3)
    }


def execute_sql(sql: str) -> dict[str, Any]:
    """Execute SQL and return result set."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute(sql)
        if cursor.description is None:
            return {"success": True, "columns": [], "values": [], "row_count": 0}
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


def compare_single_value(gen_values, expected_values, tolerance=0.01) -> dict[str, Any]:
    """Compare single-value query results."""
    if not gen_values or not expected_values:
        return {"match": False, "reason": "missing_values"}
    
    if len(expected_values) != 1:
        return {"match": False, "reason": f"expected 1 row, got {len(expected_values)}"}
    
    exp = expected_values[0]
    if not gen_values:
        return {"match": False, "reason": "no_result"}
    
    gen = gen_values[0]
    if set(gen.keys()) != set(exp.keys()):
        return {"match": False, "reason": "column_mismatch"}
    
    for col in gen:
        gv, ev = gen[col], exp[col]
        if gv is None and ev is None:
            continue
        if gv is None or ev is None:
            return {"match": False, "reason": f"null_mismatch_{col}"}
        if isinstance(gv, (int, float)) and isinstance(ev, (int, float)):
            if abs(gv - ev) <= tolerance or abs(gv - ev) / max(abs(ev), 1e-9) <= tolerance:
                continue
            return {"match": False, "reason": f"numeric_mismatch_{col}: got {gv}, expected {ev}"}
        elif str(gv) != str(ev):
            return {"match": False, "reason": f"value_mismatch_{col}: got {gv}, expected {ev}"}
    
    return {"match": True, "reason": "single_value_match"}


def compare_ranking(gen_values, expected_values, top_n=10) -> dict[str, Any]:
    """Compare ranking/top-N query results."""
    if not gen_values or not expected_values:
        return {"match": False, "reason": "missing_values"}
    
    if len(gen_values) < 2 or len(expected_values) < 2:
        return {"match": False, "reason": "insufficient_rows_for_ranking"}
    
    # Check if top-N entities match (order-independent for top-N)
    gen_entities = set(tuple(sorted(row.items())) for row in gen_values[:top_n])
    exp_entities = set(tuple(sorted(row.items())) for row in expected_values[:top_n])
    
    if gen_entities == exp_entities:
        return {"match": True, "reason": "ranking_exact_match"}
    
    # Check partial overlap
    overlap = len(gen_entities & exp_entities)
    if overlap >= len(exp_entities) * 0.8:
        return {"match": True, "reason": "ranking_partial_match", "overlap": overlap}
    
    return {"match": False, "reason": "ranking_mismatch", "overlap": overlap}


def compare_time_series(gen_values, expected_values, tolerance=0.01) -> dict[str, Any]:
    """Compare time-series query results."""
    if not gen_values or not expected_values:
        return {"match": False, "reason": "missing_values"}
    
    if len(gen_values) != len(expected_values):
        return {"match": False, "reason": f"row_count_mismatch: got {len(gen_values)}, expected {len(expected_values)}"}
    
    # Check ordering by first column (usually time period)
    gen_periods = [row.get(list(row.keys())[0]) for row in gen_values]
    exp_periods = [row.get(list(expected_values[0].keys())[0]) for row in expected_values]
    
    if gen_periods != exp_periods:
        return {"match": False, "reason": "time_period_mismatch"}
    
    # Check values with tolerance
    mismatches = 0
    for g_row, e_row in zip(gen_values, expected_values):
        for col in e_row:
            if col not in g_row:
                mismatches += 1
                continue
            gv, ev = g_row[col], e_row[col]
            if isinstance(gv, (int, float)) and isinstance(ev, (int, float)):
                if abs(gv - ev) > tolerance and abs(gv - ev) / max(abs(ev), 1e-9) > tolerance:
                    mismatches += 1
            elif str(gv) != str(ev):
                mismatches += 1
    
    if mismatches == 0:
        return {"match": True, "reason": "timeseries_exact_match"}
    
    return {"match": False, "reason": f"timeseries_value_mismatch: {mismatches} differences"}


def compare_distribution(gen_values, expected_values, tolerance=0.01) -> dict[str, Any]:
    """Compare distribution query results."""
    if not gen_values or not expected_values:
        return {"match": False, "reason": "missing_values"}
    
    # Check if categories/buckets match
    gen_cats = set()
    exp_cats = set()
    for row in gen_values:
        gen_cats.add(tuple(sorted((k, v) for k, v in row.items() if k != 'count' and k != 'order_count' and k != 'product_count')))
    for row in expected_values:
        exp_cats.add(tuple(sorted((k, v) for k, v in row.items() if k != 'count' and k != 'order_count' and k != 'product_count')))
    
    if gen_cats != exp_cats:
        return {"match": False, "reason": "distribution_categories_mismatch"}
    
    return {"match": True, "reason": "distribution_match"}


def compare_aggregation(gen_values, expected_values, tolerance=0.01) -> dict[str, Any]:
    """Compare aggregation query results."""
    if not gen_values or not expected_values:
        return {"match": False, "reason": "missing_values"}
    
    if len(gen_values) != len(expected_values):
        return {"match": False, "reason": f"row_count_mismatch: got {len(gen_values)}, expected {len(expected_values)}"}
    
    mismatches = 0
    for g_row, e_row in zip(gen_values, expected_values):
        if set(g_row.keys()) != set(e_row.keys()):
            mismatches += 1
            continue
        for col in g_row:
            gv, ev = g_row[col], e_row[col]
            if isinstance(gv, (int, float)) and isinstance(ev, (int, float)):
                if abs(gv - ev) > tolerance and abs(gv - ev) / max(abs(ev), 1e-9) > tolerance:
                    mismatches += 1
            elif str(gv) != str(ev):
                mismatches += 1
    
    if mismatches == 0:
        return {"match": True, "reason": "aggregation_exact_match"}
    
    return {"match": False, "reason": f"aggregation_mismatch: {mismatches} differences"}


def compare_results_query_aware(gen_values, expected_values, query_type, question, tolerance=0.01) -> dict[str, Any]:
    """Query-type-aware result comparison."""
    if not gen_values:
        return {"match": False, "reason": "no_result"}
    
    if query_type == 'single_value':
        return compare_single_value(gen_values, expected_values, tolerance)
    elif query_type == 'ranking':
        return compare_ranking(gen_values, expected_values)
    elif query_type == 'time_series':
        return compare_time_series(gen_values, expected_values, tolerance)
    elif query_type == 'aggregation':
        return compare_aggregation(gen_values, expected_values, tolerance)
    elif 'distribution' in question.lower():
        return compare_distribution(gen_values, expected_values, tolerance)
    else:
        return compare_aggregation(gen_values, expected_values, tolerance)


def to_json_value(val):
    if val is None:
        return None
    if isinstance(val, float):
        return round(val, 4)
    return val


def evaluate_baseline_v3():
    logger.info("Loading baseline results and V3 benchmark...")
    
    with open(BASELINE_RESULTS_PATH, "r", encoding="utf-8") as f:
        baseline_results = json.load(f)
    
    with open(V2_BENCHMARK_PATH, "r", encoding="utf-8") as f:
        v2_benchmark = json.load(f)
    
    logger.info(f"Loaded {len(baseline_results)} baseline results and {len(v2_benchmark)} V3 queries.")
    
    eval_results = []
    
    for i, (baseline, v2) in enumerate(zip(baseline_results, v2_benchmark)):
        question = v2["question"]
        expected_sql = v2["expected_sql"]
        expected_tables = v2["expected_tables"]
        expected_result = v2.get("expected_result", {})
        query_type = v2.get("query_type", "unknown")
        difficulty = v2.get("difficulty", "unknown")
        domain = v2.get("domain", v2.get("category", "unknown"))
        correctness_checks = v2.get("correctness_checks", [])
        generated_sql = baseline.get("generated_sql")
        baseline_success = baseline.get("success", False)
        sql_error = baseline.get("sql_error")
        latency = baseline.get("latency_seconds", 0)
        confidence = baseline.get("confidence")
        verdict = baseline.get("verdict")
        
        logger.info(f"[{i+1}/100] Evaluating: {question[:60]}...")
        
        # 1. Service completion rate
        service_completed = baseline_success
        
        # 2. SQL execution success rate
        single_sql = extract_first_sql(generated_sql)
        sql_execution_success = False
        sql_execution_error = None
        gen_result = None
        
        if single_sql:
            exec_result = execute_sql(single_sql)
            if exec_result["success"]:
                sql_execution_success = True
                gen_result = exec_result
            else:
                sql_execution_error = exec_result.get("error")
        
        # 3. Result correctness (query-type-aware)
        result_correctness = {"match": False, "reason": "not_evaluated"}
        if sql_execution_success and single_sql:
            tolerance = 0.05 if 'percentage' in question.lower() or 'rate' in question.lower() else 0.01
            result_correctness = compare_results_query_aware(
                gen_result.get("values", []),
                expected_result.get("values", []),
                query_type,
                question,
                tolerance
            )
        
        # 4. Table selection accuracy
        queried_tables = extract_tables_from_sql(generated_sql)
        correct_tables = [t for t in expected_tables if t in queried_tables]
        table_accuracy = (len(correct_tables) / len(expected_tables)) * 100.0 if expected_tables else 100.0
        table_match = set(correct_tables) == set(expected_tables)
        
        # 5. SQL form similarity (NOT semantic correctness)
        sql_form_comparison = compare_sql_form(generated_sql, expected_sql)
        
        # 6. Result equivalence via gold SQL execution
        gold_exec = execute_sql(expected_sql)
        result_equivalence = {"match": False, "reason": "not_evaluated"}
        if sql_execution_success and gold_exec["success"]:
            tolerance = 0.05 if 'percentage' in question.lower() or 'rate' in question.lower() else 0.01
            result_equivalence = compare_results_query_aware(
                gen_result.get("values", []),
                gold_exec.get("values", []),
                query_type,
                question,
                tolerance
            )
        
        # 7. Invalid SQL
        invalid_sql = bool(sql_error) or (generated_sql is not None and len(generated_sql.strip()) == 0)
        
        # 8. Schema hallucination
        hallucinated = check_hallucinated_schema(generated_sql)
        
        # 9. Unsafe SQL
        unsafe = check_unsafe_sql(generated_sql)
        
        eval_results.append({
            "question": question,
            "category": v2.get("category", domain),
            "domain": domain,
            "query_type": query_type,
            "difficulty": difficulty,
            "expected_tables": expected_tables,
            "queried_tables": queried_tables,
            "table_accuracy_pct": round(table_accuracy, 2),
            "table_match": table_match,
            "expected_sql": expected_sql,
            "generated_sql": generated_sql,
            "sql_form_exact_match": sql_form_comparison.get("exact_match", False),
            "sql_form_normalized_match": sql_form_comparison.get("normalized_match", False),
            "sql_form_similarity": sql_form_comparison.get("similarity", 0.0),
            "service_completed": service_completed,
            "sql_execution_success": sql_execution_success,
            "sql_execution_error": sql_execution_error,
            "result_correctness": result_correctness.get("match", False),
            "result_correctness_reason": result_correctness.get("reason", ""),
            "result_equivalence": result_equivalence.get("match", False),
            "result_equivalence_reason": result_equivalence.get("reason", ""),
            "invalid_sql": invalid_sql,
            "hallucinated_schema": hallucinated,
            "unsafe_keywords": unsafe,
            "latency_seconds": latency,
            "correctness_checks": correctness_checks,
            "confidence": confidence,
            "verdict": verdict,
        })
    
    # Save raw results
    raw_path = RESULTS_DIR / "raw_results.json"
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(eval_results, f, indent=2, default=str)
    
    # Compute summary
    total = len(eval_results)
    service_completed = sum(1 for r in eval_results if r["service_completed"])
    sql_exec_success = sum(1 for r in eval_results if r["sql_execution_success"])
    result_correct = sum(1 for r in eval_results if r["result_correctness"])
    result_equiv = sum(1 for r in eval_results if r["result_equivalence"])
    table_match = sum(1 for r in eval_results if r["table_match"])
    sql_exact = sum(1 for r in eval_results if r["sql_form_exact_match"])
    sql_norm = sum(1 for r in eval_results if r["sql_form_normalized_match"])
    invalid_sql_count = sum(1 for r in eval_results if r["invalid_sql"])
    hallucinated_count = sum(1 for r in eval_results if r["hallucinated_schema"])
    unsafe_count = sum(1 for r in eval_results if r["unsafe_keywords"])
    latencies = [r["latency_seconds"] for r in eval_results]
    confidences = [r["confidence"] for r in eval_results if r["confidence"] is not None]
    
    # Breakdown by domain
    domain_stats = {}
    for r in eval_results:
        d = r["domain"]
        if d not in domain_stats:
            domain_stats[d] = {"total": 0, "correct": 0, "exec": 0}
        domain_stats[d]["total"] += 1
        if r["result_correctness"]:
            domain_stats[d]["correct"] += 1
        if r["sql_execution_success"]:
            domain_stats[d]["exec"] += 1
    
    # Breakdown by query type
    query_type_stats = {}
    for r in eval_results:
        qt = r["query_type"]
        if qt not in query_type_stats:
            query_type_stats[qt] = {"total": 0, "correct": 0, "exec": 0}
        query_type_stats[qt]["total"] += 1
        if r["result_correctness"]:
            query_type_stats[qt]["correct"] += 1
        if r["sql_execution_success"]:
            query_type_stats[qt]["exec"] += 1
    
    # Breakdown by difficulty
    difficulty_stats = {}
    for r in eval_results:
        d = r["difficulty"]
        if d not in difficulty_stats:
            difficulty_stats[d] = {"total": 0, "correct": 0, "exec": 0}
        difficulty_stats[d]["total"] += 1
        if r["result_correctness"]:
            difficulty_stats[d]["correct"] += 1
        if r["sql_execution_success"]:
            difficulty_stats[d]["exec"] += 1
    
    summary = {
        "total_queries": total,
        "service_completion_rate_pct": round(service_completed / total * 100, 2) if total else 0.0,
        "sql_execution_success_rate_pct": round(sql_exec_success / total * 100, 2) if total else 0.0,
        "result_correctness_pct": round(result_correct / total * 100, 2) if total else 0.0,
        "result_equivalence_pct": round(result_equiv / total * 100, 2) if total else 0.0,
        "table_accuracy_pct": round(table_match / total * 100, 2) if total else 0.0,
        "sql_form_exact_match_pct": round(sql_exact / total * 100, 2) if total else 0.0,
        "sql_form_normalized_match_pct": round(sql_norm / total * 100, 2) if total else 0.0,
        "invalid_sql_rate_pct": round(invalid_sql_count / total * 100, 2) if total else 0.0,
        "hallucinated_schema_rate_pct": round(hallucinated_count / total * 100, 2) if total else 0.0,
        "unsafe_sql_rate_pct": round(unsafe_count / total * 100, 2) if total else 0.0,
        "avg_latency_seconds": round(sum(latencies) / total, 2) if total else 0.0,
        "min_latency_seconds": min(latencies) if latencies else 0.0,
        "max_latency_seconds": max(latencies) if latencies else 0.0,
        "avg_confidence": round(sum(confidences) / len(confidences), 4) if confidences else 0.0,
        "domain_breakdown": domain_stats,
        "query_type_breakdown": query_type_stats,
        "difficulty_breakdown": difficulty_stats,
        "model_version": get_config_snapshot(),
        "evaluation_notes": {
            "service_completion": "Agent returned a response (may include fallback SQL)",
            "sql_execution_success": "Generated SQL was independently executed against DB without error",
            "result_correctness": "Query-type-aware comparison of generated result vs gold result",
            "result_equivalence": "Generated result vs gold SQL result (both executed independently)",
            "sql_form_similarity": "Text-level SQL similarity, NOT semantic correctness"
        }
    }
    
    summary_path = RESULTS_DIR / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    
    # Generate markdown report
    report_path = RESULTS_DIR / "evaluation_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# 🧪 Research-Grade Benchmark Evaluation Report (V3)\n\n")
        f.write("## 📊 Aggregate Metrics\n\n")
        f.write("| Metric | Value |\n| :--- | :--- |\n")
        f.write(f"| Total Queries | {summary['total_queries']} |\n")
        f.write(f"| Service Completion Rate | {summary['service_completion_rate_pct']}% |\n")
        f.write(f"| SQL Execution Success Rate | {summary['sql_execution_success_rate_pct']}% |\n")
        f.write(f"| Result Correctness | {summary['result_correctness_pct']}% |\n")
        f.write(f"| Result Equivalence (vs gold SQL) | {summary['result_equivalence_pct']}% |\n")
        f.write(f"| Table Selection Accuracy | {summary['table_accuracy_pct']}% |\n")
        f.write(f"| SQL Form Exact Match | {summary['sql_form_exact_match_pct']}% |\n")
        f.write(f"| SQL Form Normalized Match | {summary['sql_form_normalized_match_pct']}% |\n")
        f.write(f"| Invalid SQL Rate | {summary['invalid_sql_rate_pct']}% |\n")
        f.write(f"| Hallucinated Schema Rate | {summary['hallucinated_schema_rate_pct']}% |\n")
        f.write(f"| Unsafe SQL Rate | {summary['unsafe_sql_rate_pct']}% |\n")
        f.write(f"| Avg Latency | {summary['avg_latency_seconds']}s |\n")
        f.write(f"| Avg Confidence | {summary['avg_confidence']} |\n\n")
        
        f.write("## Breakdown by Domain\n\n")
        f.write("| Domain | Total | Exec | Correct |\n| :--- | :---: | :---: | :---: |\n")
        for d, s in sorted(domain_stats.items()):
            f.write(f"| {d} | {s['total']} | {s['exec']} | {s['correct']} |\n")
        
        f.write("\n## Breakdown by Query Type\n\n")
        f.write("| Query Type | Total | Exec | Correct |\n| :--- | :---: | :---: | :---: |\n")
        for qt, s in sorted(query_type_stats.items()):
            f.write(f"| {qt} | {s['total']} | {s['exec']} | {s['correct']} |\n")
        
        f.write("\n## Breakdown by Difficulty\n\n")
        f.write("| Difficulty | Total | Exec | Correct |\n| :--- | :---: | :---: | :---: |\n")
        for d, s in sorted(difficulty_stats.items()):
            f.write(f"| {d} | {s['total']} | {s['exec']} | {s['correct']} |\n")
        
        f.write("\n## Per-Query Results\n\n")
        f.write("| # | Domain | Query Type | Question | Service | Exec | Correct | Equiv | Tables | Failure |\n")
        f.write("| :--- | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |\n")
        
        for idx, r in enumerate(eval_results, 1):
            svc = "Yes" if r["service_completed"] else "No"
            exec_icon = "Yes" if r["sql_execution_success"] else "No"
            correct_icon = "Yes" if r["result_correctness"] else "No"
            equiv_icon = "Yes" if r["result_equivalence"] else "No"
            table_icon = f"{r['table_accuracy_pct']:.0f}%"
            
            failure = "None"
            if not r["sql_execution_success"]:
                failure = r.get("sql_execution_error", "Execution Failed")[:40]
            elif not r["result_correctness"]:
                failure = r.get("result_correctness_reason", "Wrong Result")[:40]
            elif not r["table_match"]:
                failure = "Wrong Tables"
            
            f.write(f"| {idx} | {r['domain']} | {r['query_type']} | `{r['question'][:45]}` | {svc} | {exec_icon} | {correct_icon} | {equiv_icon} | {table_icon} | {failure} |\n")
        
        f.write("\n## Evaluation Methodology Notes\n\n")
        for k, v in summary["evaluation_notes"].items():
            f.write(f"- **{k}**: {v}\n")
    
    print(f"\n{'='*70}")
    print(f"[SUCCESS] V3 BENCHMARK EVALUATION COMPLETED!")
    print(f"{'='*70}")
    print(f"Total queries: {total}")
    print(f"Service completion: {summary['service_completion_rate_pct']}%")
    print(f"SQL execution success: {summary['sql_execution_success_rate_pct']}%")
    print(f"Result correctness: {summary['result_correctness_pct']}%")
    print(f"Result equivalence: {summary['result_equivalence_pct']}%")
    print(f"Table accuracy: {summary['table_accuracy_pct']}%")
    print(f"SQL exact match: {summary['sql_form_exact_match_pct']}%")
    print(f"SQL normalized match: {summary['sql_form_normalized_match_pct']}%")
    print(f"Invalid SQL: {summary['invalid_sql_rate_pct']}%")
    print(f"Hallucinated schema: {summary['hallucinated_schema_rate_pct']}%")
    print(f"Unsafe SQL: {summary['unsafe_sql_rate_pct']}%")
    print(f"Avg latency: {summary['avg_latency_seconds']}s")
    print(f"Report saved at: {RESULTS_DIR}")
    print(f"{'='*70}\n")
    
    return summary


if __name__ == "__main__":
    evaluate_baseline_v3()
