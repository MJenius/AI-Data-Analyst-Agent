from __future__ import annotations

import re
import sqlite3
from typing import Any

from agent_platform.experiments.query_plan import QueryPlan


DB_PATH = None  # set by run_experiments

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

AGG_FUNCS = {"SUM", "COUNT", "AVG", "MIN", "MAX"}

QUERY_TYPE_INTENT_KEYWORDS = {
    "single_value": ["total", "value", "rate", "percentage", "average", "count", "what is", "how many", "how much", "measure", "metric"],
    "ranking": ["top", "rank", "highest", "lowest", "most", "best", "worst", "peak"],
    "time_series": ["trend", "over time", "monthly", "by month", "by day", "by hour", "distribution", "time", "history", "hour", "week"],
    "aggregation": ["by", "per", "distribution", "average", "aggregate", "breakdown", "group"],
    "unknown": [],
}


# ---------------------------------------------------------------------------
# SQL execution + validation helpers
# ---------------------------------------------------------------------------

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


def extract_first_sql(sql: str | None) -> str | None:
    if not sql:
        return None
    statements = re.split(r";\s*|\n(?=SELECT\s)", sql, flags=re.IGNORECASE)
    for stmt in statements:
        stmt = stmt.strip()
        if stmt and re.search(r"\bSELECT\b", stmt, re.IGNORECASE):
            return stmt
    for stmt in statements:
        stmt = stmt.strip()
        if stmt:
            return stmt
    return sql.strip() if sql else None


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


def execute_sql(sql: str) -> dict[str, Any]:
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
        return {"success": True, "columns": cols, "values": values, "row_count": len(rows)}
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


# ---------------------------------------------------------------------------
# Result comparison (query-type-aware, same logic as V3 harness)
# ---------------------------------------------------------------------------

def compare_single_value(gen_values, expected_values, tolerance=0.01) -> dict[str, Any]:
    if not gen_values or not expected_values:
        return {"match": False, "reason": "missing_values"}
    if len(expected_values) != 1:
        return {"match": False, "reason": f"expected 1 row, got {len(expected_values)}"}
    gen = gen_values[0]
    exp = expected_values[0]
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
    if not gen_values or not expected_values:
        return {"match": False, "reason": "missing_values"}
    if len(gen_values) < 2 or len(expected_values) < 2:
        return {"match": False, "reason": "insufficient_rows_for_ranking"}
    gen_entities = set(tuple(sorted(row.items())) for row in gen_values[:top_n])
    exp_entities = set(tuple(sorted(row.items())) for row in expected_values[:top_n])
    if gen_entities == exp_entities:
        return {"match": True, "reason": "ranking_exact_match"}
    overlap = len(gen_entities & exp_entities)
    if overlap >= len(exp_entities) * 0.8:
        return {"match": True, "reason": "ranking_partial_match", "overlap": overlap}
    return {"match": False, "reason": "ranking_mismatch", "overlap": overlap}


def compare_time_series(gen_values, expected_values, tolerance=0.01) -> dict[str, Any]:
    if not gen_values or not expected_values:
        return {"match": False, "reason": "missing_values"}
    if len(gen_values) != len(expected_values):
        return {"match": False, "reason": f"row_count_mismatch: got {len(gen_values)}, expected {len(expected_values)}"}
    gen_periods = [row.get(list(row.keys())[0]) for row in gen_values]
    exp_periods = [row.get(list(expected_values[0].keys())[0]) for row in expected_values]
    if gen_periods != exp_periods:
        return {"match": False, "reason": "time_period_mismatch"}
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
    if not gen_values or not expected_values:
        return {"match": False, "reason": "missing_values"}
    gen_cats = set()
    exp_cats = set()
    for row in gen_values:
        gen_cats.add(tuple(sorted((k, v) for k, v in row.items() if k not in ("count", "order_count", "product_count"))))
    for row in expected_values:
        exp_cats.add(tuple(sorted((k, v) for k, v in row.items() if k not in ("count", "order_count", "product_count"))))
    if gen_cats != exp_cats:
        return {"match": False, "reason": "distribution_categories_mismatch"}
    return {"match": True, "reason": "distribution_match"}


def compare_aggregation(gen_values, expected_values, tolerance=0.01) -> dict[str, Any]:
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
    if not gen_values:
        return {"match": False, "reason": "no_result"}
    if query_type == "single_value":
        return compare_single_value(gen_values, expected_values, tolerance)
    elif query_type == "ranking":
        return compare_ranking(gen_values, expected_values)
    elif query_type == "time_series":
        return compare_time_series(gen_values, expected_values, tolerance)
    elif query_type == "aggregation":
        return compare_aggregation(gen_values, expected_values, tolerance)
    elif "distribution" in question.lower():
        return compare_distribution(gen_values, expected_values, tolerance)
    else:
        return compare_aggregation(gen_values, expected_values, tolerance)


# ---------------------------------------------------------------------------
# Lenient LLM JSON output parsing
# ---------------------------------------------------------------------------

def clean_sql_text(raw: str | None) -> str | None:
    """Strip markdown fences and trailing text from raw LLM SQL."""
    if not raw:
        return None
    raw = raw.strip()
    raw = re.sub(r"^```(?:sql|SQL)?\s*", "", raw).strip()
    raw = re.sub(r"\s*```$", "", raw).strip()
    if not raw:
        return None
    return raw


def parse_sql_from_llm(payload: dict[str, Any]) -> str | None:
    """Lenient SQL extraction: accept 'sql' or 'query' keys; tolerate missing 'reasoning'."""
    if not isinstance(payload, dict):
        return None
    sql = payload.get("sql") or payload.get("query")
    if not isinstance(sql, str) or not sql.strip():
        return None
    return clean_sql_text(sql)


def parse_plan_loose(payload: Any) -> QueryPlan:
    """Lenient QueryPlan construction: missing required fields get defaults."""
    if not isinstance(payload, dict):
        payload = {}
    filled = {
        "intent": str(payload.get("intent") or ""),
        "metric": str(payload.get("metric") or ""),
        "entity": payload.get("entity") if payload.get("entity") is not None else None,
        "aggregation": payload.get("aggregation") if payload.get("aggregation") is not None else None,
        "filters": [str(f) for f in (payload.get("filters") or []) if isinstance(f, (str, int, float))],
        "group_by": [str(g) for g in (payload.get("group_by") or []) if isinstance(g, (str, int, float))] or None,
        "ordering": payload.get("ordering") if payload.get("ordering") is not None else None,
        "limit": payload.get("limit") if isinstance(payload.get("limit"), int) else None,
        "required_tables": [str(t) for t in (payload.get("required_tables") or []) if isinstance(t, (str, int, float))],
    }
    return QueryPlan(**filled)


# ---------------------------------------------------------------------------
# Plan correctness evaluation against benchmark metadata
# ---------------------------------------------------------------------------

def _expected_aggregation(expected_sql: str) -> str | None:
    upper = expected_sql.upper()
    for func in ("SUM", "COUNT", "AVG", "MIN", "MAX"):
        if re.search(rf"\b{func}\s*\(", upper):
            return func
    return None


def evaluate_plan(plan: QueryPlan, benchmark: dict[str, Any]) -> dict[str, Any]:
    expected_tables = set(benchmark.get("expected_tables", []))
    expected_metrics = [str(m).lower() for m in benchmark.get("expected_metrics", [])]
    expected_sql = benchmark.get("expected_sql", "") or ""
    expected_sql_upper = expected_sql.upper()
    query_type = benchmark.get("query_type", "unknown")
    question = benchmark.get("question", "")

    plan_metric = (plan.metric or "").lower().replace("_", " ").replace("-", " ")
    expected_normalized = [str(m).lower().replace("_", " ").replace("-", " ") for m in expected_metrics]
    metric_ok = any(
        em in plan_metric or plan_metric in em for em in expected_normalized
    ) if expected_metrics else True

    plan_tables = {t.lower() for t in (plan.required_tables or [])}
    tables_ok = expected_tables.issubset(plan_tables)
    missing_tables = sorted(expected_tables - plan_tables)
    extra_tables = sorted(plan_tables - expected_tables)

    expected_agg = _expected_aggregation(expected_sql)
    plan_agg = (plan.aggregation or "").upper()
    aggregation_ok = expected_agg in plan_agg if expected_agg else True

    group_by_ok = ("GROUP BY" in expected_sql_upper) == bool(plan.group_by)
    ordering_ok = ("ORDER BY" in expected_sql_upper) == bool(plan.ordering)
    limit_ok = ("LIMIT" in expected_sql_upper) == (plan.limit is not None)
    filters_ok = ("WHERE" in expected_sql_upper) == bool(plan.filters)

    intent_text = (plan.intent or "").lower()
    intent_ok = False
    for kw in QUERY_TYPE_INTENT_KEYWORDS.get(query_type, []):
        if kw in intent_text:
            intent_ok = True
            break
    if query_type == "unknown":
        intent_ok = True

    core_ok = tables_ok and metric_ok and aggregation_ok and group_by_ok
    full_ok = core_ok and ordering_ok and limit_ok and filters_ok and intent_ok

    return {
        "intent": plan.intent,
        "metric": plan.metric,
        "entity": plan.entity,
        "aggregation": plan.aggregation,
        "filters": plan.filters,
        "group_by": plan.group_by,
        "ordering": plan.ordering,
        "limit": plan.limit,
        "required_tables": plan.required_tables,
        "intent_ok": intent_ok,
        "metric_ok": metric_ok,
        "aggregation_ok": aggregation_ok,
        "group_by_ok": group_by_ok,
        "ordering_ok": ordering_ok,
        "limit_ok": limit_ok,
        "filters_ok": filters_ok,
        "tables_ok": tables_ok,
        "missing_tables": missing_tables,
        "extra_tables": extra_tables,
        "expected_aggregation": expected_agg,
        "plan_core_ok": core_ok,
        "plan_full_ok": full_ok,
    }


# ---------------------------------------------------------------------------
# Full per-query evaluation
# ---------------------------------------------------------------------------

def evaluate_query(
    gen_sql: str | None,
    benchmark: dict[str, Any],
    pre_execution_errors: list[str] | None = None,
) -> dict[str, Any]:
    expected_sql = benchmark.get("expected_sql", "")
    expected_tables = benchmark.get("expected_tables", [])
    expected_result = benchmark.get("expected_result", {})
    query_type = benchmark.get("query_type", "unknown")
    question = benchmark.get("question", "")

    gen_result = None
    sql_execution_success = False
    sql_execution_error = None

    ast_validated = pre_execution_errors is not None
    pre_execution_errors = pre_execution_errors or []
    if gen_sql and not pre_execution_errors:
        exec_result = execute_sql(gen_sql)
        if exec_result["success"]:
            sql_execution_success = True
            gen_result = exec_result
        else:
            sql_execution_error = exec_result.get("error")

    result_correctness = {"match": False, "reason": "not_evaluated"}
    if sql_execution_success and gen_result:
        tolerance = 0.05 if "percentage" in question.lower() or "rate" in question.lower() else 0.01
        result_correctness = compare_results_query_aware(
            gen_result.get("values", []), expected_result.get("values", []),
            query_type, question, tolerance,
        )

    gold_exec = execute_sql(expected_sql)
    result_equivalence = {"match": False, "reason": "not_evaluated"}
    if sql_execution_success and gold_exec["success"]:
        tolerance = 0.05 if "percentage" in question.lower() or "rate" in question.lower() else 0.01
        result_equivalence = compare_results_query_aware(
            gen_result.get("values", []), gold_exec.get("values", []),
            query_type, question, tolerance,
        )

    queried_tables = extract_tables_from_sql(gen_sql)
    correct_tables = [t for t in expected_tables if t in queried_tables]
    table_accuracy = (len(correct_tables) / len(expected_tables)) * 100.0 if expected_tables else 100.0
    table_match = set(queried_tables) == set(expected_tables)
    table_precision = (len(correct_tables) / len(queried_tables)) * 100.0 if queried_tables else (100.0 if not expected_tables else 0.0)
    schema_validation_errors = [
        error for error in pre_execution_errors
        if error.startswith(("nonexistent_column:", "nonexistent_table:"))
    ]

    return {
        "sql_execution_success": sql_execution_success,
        "sql_execution_error": sql_execution_error or ("; ".join(pre_execution_errors) if pre_execution_errors else None),
        "result_correctness": result_correctness.get("match", False),
        "result_correctness_reason": result_correctness.get("reason", ""),
        "result_equivalence": result_equivalence.get("match", False),
        "result_equivalence_reason": result_equivalence.get("reason", ""),
        "queried_tables": queried_tables,
        "table_accuracy_pct": round(table_accuracy, 2),
        "table_precision_pct": round(table_precision, 2),
        "table_match": table_match,
        "invalid_sql": bool(pre_execution_errors or sql_execution_error) or (gen_sql is not None and len(gen_sql.strip()) == 0),
        "hallucinated_schema": schema_validation_errors if ast_validated else check_hallucinated_schema(gen_sql),
        "unsafe_keywords": check_unsafe_sql(gen_sql),
        "validation_errors": pre_execution_errors,
        "pre_execution_blocked": bool(pre_execution_errors),
        "gold_exec_success": gold_exec.get("success", False),
    }


def classify_failure(eval_: dict[str, Any], plan_eval: dict[str, Any] | None) -> str:
    """Classify a query result into a primary failure category."""
    if eval_["result_correctness"]:
        return "correct"
    if not eval_["sql_execution_success"]:
        if eval_["hallucinated_schema"]:
            return "sql_gen_hallucination"
        if eval_["unsafe_keywords"]:
            return "sql_safety_blocked"
        return "sql_execution_error"
    if not eval_["table_match"]:
        return "table_selection_error"
    if plan_eval is not None and not plan_eval["plan_core_ok"]:
        return "planning_error"
    return "sql_semantic_error"
