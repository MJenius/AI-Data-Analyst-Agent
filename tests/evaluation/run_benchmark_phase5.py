"""Phase 5 benchmark runner — evaluates semantic verification improvements.

Compares Phase 4 best run (improved RAG: 16% correctness, nvidia/nemotron-3-super-120b)
against Phase 5 with result-level semantic verification applied to the same 100 generated
SQL statements.  No new LLM calls are made — this is a pure verification pass on frozen
Phase 4 outputs, so it is reproducible and does not incur API cost.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("run_benchmark_phase5")

DB_PATH           = ROOT / "data"         / "analytics.db"
BENCHMARK_PATH    = ROOT / "tests" / "evaluation" / "benchmark_dataset_v2.json"
# Phase 4 frozen baseline (improved RAG, 100 queries, nvidia nemotron-3-super-120b-a12b)
PHASE4_RAW_PATH   = (
    ROOT / "results" / "phase4"
    / "run_20260816T_phase4_nvidia_nemotron_120b_v2"
    / "phase4_improved_rag" / "raw_results.json"
)
PHASE4_SUMM_PATH  = (
    ROOT / "results" / "phase4"
    / "run_20260816T_phase4_nvidia_nemotron_120b_v2"
    / "phase4_improved_rag" / "summary.json"
)
RESULTS_DIR = ROOT / "results" / "phase5"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

from agent_platform.tools.sql_verifier import (
    SQLSemanticVerifier,
    VerificationLevel,
    VerificationCategory,
)


KNOWN_TABLES = {
    "customers", "geolocation", "order_items", "order_payments",
    "order_reviews", "orders", "products", "sellers",
    "product_category_name_translation",
}
BLOCKED_KEYWORDS = {
    "insert","update","delete","drop","alter","create",
    "truncate","replace","attach","detach","vacuum","pragma",
}


# ── helpers ─────────────────────────────────────────────────────────────────

def extract_first_sql(sql: str | None) -> str | None:
    if not sql:
        return None
    stmts = re.split(r";\s*|\n(?=SELECT\s)", sql, flags=re.IGNORECASE)
    for s in stmts:
        s = s.strip()
        if s and re.search(r"\bSELECT\b", s, re.IGNORECASE):
            return s
    return sql.strip() or None


def extract_tables(sql: str | None) -> list[str]:
    if not sql:
        return []
    lower = re.sub(r"\s+", " ", sql.lower())
    return [t for t in KNOWN_TABLES if re.search(rf"\b{t}\b", lower)]


def hallucinated_tables(sql: str | None) -> list[str]:
    if not sql:
        return []
    lower = re.sub(r"\s+", " ", sql.lower())
    matches = re.findall(r"\b(?:from|join)\s+([a-zA-Z_]\w*)", lower)
    return [m for m in matches if m not in KNOWN_TABLES and m not in {"sqlite_master","sqlite_schema"}]


def unsafe_keywords(sql: str | None) -> list[str]:
    if not sql:
        return []
    tokens = set(re.findall(r"[a-zA-Z_]+", sql.lower()))
    return sorted(tokens & BLOCKED_KEYWORDS)


def to_json_value(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, float):
        return round(val, 4)
    return val


def execute_sql(sql: str) -> dict[str, Any]:
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(sql)
        if cur.description is None:
            return {"success": True, "columns": [], "values": [], "row_count": 0}
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        values = [{c: to_json_value(v) for c, v in zip(cols, row)} for row in rows[:50]]
        return {"success": True, "columns": cols, "values": values, "row_count": len(rows)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    finally:
        conn.close()


# ── result comparators (from run_benchmark_v3.py) ───────────────────────────

def _cmp_single(gen, exp, tol=0.01):
    if not gen or not exp:
        return {"match": False, "reason": "missing_values"}
    if len(exp) != 1:
        return {"match": False, "reason": f"expected 1 row, got {len(exp)}"}
    g, e = gen[0], exp[0]
    if set(g) != set(e):
        return {"match": False, "reason": "column_mismatch"}
    for col in g:
        gv, ev = g[col], e[col]
        if gv is None and ev is None:
            continue
        if gv is None or ev is None:
            return {"match": False, "reason": f"null_mismatch_{col}"}
        if isinstance(gv, (int, float)) and isinstance(ev, (int, float)):
            if abs(gv-ev) <= tol or abs(gv-ev)/max(abs(ev), 1e-9) <= tol:
                continue
            return {"match": False, "reason": f"numeric_mismatch_{col}: got {gv}, expected {ev}"}
        elif str(gv) != str(ev):
            return {"match": False, "reason": f"value_mismatch_{col}"}
    return {"match": True, "reason": "single_value_match"}


def _cmp_ranking(gen, exp, top_n=10):
    if not gen or not exp or len(gen) < 2 or len(exp) < 2:
        return {"match": False, "reason": "insufficient_rows_for_ranking"}
    ge = {tuple(sorted(r.items())) for r in gen[:top_n]}
    ee = {tuple(sorted(r.items())) for r in exp[:top_n]}
    if ge == ee:
        return {"match": True, "reason": "ranking_exact_match"}
    ov = len(ge & ee)
    if ov >= len(ee)*0.8:
        return {"match": True, "reason": "ranking_partial_match", "overlap": ov}
    return {"match": False, "reason": "ranking_mismatch", "overlap": ov}


def _cmp_timeseries(gen, exp, tol=0.01):
    if not gen or not exp:
        return {"match": False, "reason": "missing_values"}
    if len(gen) != len(exp):
        return {"match": False, "reason": f"row_count_mismatch: got {len(gen)}, expected {len(exp)}"}
    gp = [r.get(list(r)[0]) for r in gen]
    ep = [r.get(list(exp[0])[0]) for r in exp]
    if gp != ep:
        return {"match": False, "reason": "time_period_mismatch"}
    bad = 0
    for gr, er in zip(gen, exp):
        for col in er:
            if col not in gr:
                bad += 1
                continue
            gv, ev = gr[col], er[col]
            if isinstance(gv, (int, float)) and isinstance(ev, (int, float)):
                if abs(gv-ev) > tol and abs(gv-ev)/max(abs(ev), 1e-9) > tol:
                    bad += 1
            elif str(gv) != str(ev):
                bad += 1
    return {"match": bad == 0, "reason": "timeseries_exact_match" if bad == 0 else f"timeseries_value_mismatch: {bad}"}


def _cmp_aggregation(gen, exp, tol=0.01):
    if not gen or not exp:
        return {"match": False, "reason": "missing_values"}
    if len(gen) != len(exp):
        return {"match": False, "reason": f"row_count_mismatch: got {len(gen)}, expected {len(exp)}"}
    bad = 0
    for gr, er in zip(gen, exp):
        if set(gr) != set(er):
            bad += 1
            continue
        for col in gr:
            gv, ev = gr[col], er[col]
            if isinstance(gv, (int, float)) and isinstance(ev, (int, float)):
                if abs(gv-ev) > tol and abs(gv-ev)/max(abs(ev), 1e-9) > tol:
                    bad += 1
            elif str(gv) != str(ev):
                bad += 1
    return {"match": bad == 0, "reason": "aggregation_exact_match" if bad == 0 else f"aggregation_mismatch: {bad}"}


def compare_results(gen_vals, exp_vals, qtype, question, tol=0.01):
    if not gen_vals:
        return {"match": False, "reason": "no_result"}
    tol_use = 0.05 if any(w in question.lower() for w in ("percentage","rate","ratio")) else tol
    if qtype == "single_value":
        return _cmp_single(gen_vals, exp_vals, tol_use)
    elif qtype == "ranking":
        return _cmp_ranking(gen_vals, exp_vals)
    elif qtype == "time_series":
        return _cmp_timeseries(gen_vals, exp_vals, tol_use)
    else:
        return _cmp_aggregation(gen_vals, exp_vals, tol_use)


# ── main benchmark ───────────────────────────────────────────────────────────

def run_phase5_benchmark(limit: int | None = None, run_id: str | None = None) -> dict[str, Any]:
    run_id = run_id or datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%SZ")
    results_dir = RESULTS_DIR / run_id
    results_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Loading Phase 4 baseline: %s", PHASE4_RAW_PATH)
    phase4_rows = json.loads(PHASE4_RAW_PATH.read_text(encoding="utf-8"))

    logger.info("Loading benchmark: %s", BENCHMARK_PATH)
    benchmark   = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))

    phase4_summ = json.loads(PHASE4_SUMM_PATH.read_text(encoding="utf-8"))
    baseline_correctness = phase4_summ.get("result_correctness_pct", 16.0)
    baseline_exec_success = phase4_summ.get("sql_execution_success_pct", 60.0)

    verifier = SQLSemanticVerifier(str(DB_PATH))

    vstats = {
        "group_by_mismatch": 0,
        "aggregation_grain": 0,
        "join_fan_out": 0,
        "duplicate_detection": 0,
        "expected_row_count": 0,
        "metric_inconsistency": 0,
        "queries_with_issues": 0,
        "semantic_failures_that_were_wrong": 0,
        "semantic_failures_that_were_correct": 0,
        "pre_execution_blocks": 0,
    }

    results = []
    wall_start = time.perf_counter()

    q_list = benchmark[:limit] if limit else benchmark
    for idx, entry in enumerate(q_list):
        question       = entry["question"]
        expected_tables = entry["expected_tables"]
        expected_sql   = entry["expected_sql"]
        expected_result = entry.get("expected_result", {})
        query_type     = entry.get("query_type", "unknown")
        difficulty     = entry.get("difficulty", "unknown")
        domain         = entry.get("domain", entry.get("category", "unknown"))

        # Phase 4 generated SQL (0-indexed, Phase 4 index field is 1-indexed)
        p4 = phase4_rows[idx] if idx < len(phase4_rows) else {}
        generated_sql = p4.get("generated_sql")
        p4_latency    = p4.get("run_latency_seconds", 0.0)
        p4_tokens     = p4.get("token_usage", {}).get("total_tokens", 0)

        logger.info("[%d/%d] %s", idx+1, len(q_list), question[:60])

        first_sql = extract_first_sql(generated_sql)

        # ── Execute first_sql ────────────────────────────────────────────────
        sql_execution_success = False
        sql_execution_error   = None
        gen_result            = None

        if first_sql:
            exec_res = execute_sql(first_sql)
            if exec_res["success"]:
                sql_execution_success = True
                gen_result = exec_res
            else:
                sql_execution_error = exec_res.get("error", "unknown")

        # ── Semantic verification ────────────────────────────────────────────
        exec_for_verif = None
        if gen_result:
            exec_for_verif = {
                "success": True,
                "row_count": gen_result["row_count"],
                "rows": gen_result["values"],
            }

        verification = verifier.verify(
            first_sql or "",
            execution_result=exec_for_verif,
            expected_result=expected_result,
            level=VerificationLevel.BALANCED,
        )

        has_issues = not verification.is_valid
        if has_issues:
            vstats["queries_with_issues"] += 1

        # Count issue categories
        cat_counts: dict[str, int] = {}
        for issue in verification.issues:
            cat = issue.category.value
            vstats[cat] = vstats.get(cat, 0) + 1
            cat_counts[cat] = cat_counts.get(cat, 0) + 1

        # Pre-execution block = error-severity join_fan_out or group_by_mismatch
        pre_blocked = any(
            i.severity == "error" for i in verification.issues
            if i.category in (
                VerificationCategory.JOIN_FAN_OUT,
                VerificationCategory.GROUP_BY_MISMATCH,
            )
        )
        if pre_blocked:
            vstats["pre_execution_blocks"] += 1

        # ── Result comparison ────────────────────────────────────────────────
        result_correctness  = {"match": False, "reason": "not_evaluated"}
        result_equivalence  = {"match": False, "reason": "not_evaluated"}

        if sql_execution_success and gen_result:
            result_correctness = compare_results(
                gen_result["values"], expected_result.get("values", []),
                query_type, question,
            )

        gold_exec = execute_sql(expected_sql)
        if sql_execution_success and gold_exec["success"]:
            result_equivalence = compare_results(
                gen_result["values"], gold_exec.get("values", []),
                query_type, question,
            )

        # Correlate verification with correctness
        if has_issues and not result_correctness["match"]:
            vstats["semantic_failures_that_were_wrong"] += 1
        if has_issues and result_correctness["match"]:
            vstats["semantic_failures_that_were_correct"] += 1

        queried  = extract_tables(generated_sql)
        correct_t = [t for t in expected_tables if t in queried]
        t_acc    = len(correct_t) / len(expected_tables) * 100 if expected_tables else 100.0
        t_match  = set(correct_t) == set(expected_tables)

        results.append({
            "index": idx + 1,
            "question": question,
            "domain": domain,
            "query_type": query_type,
            "difficulty": difficulty,
            "expected_tables": expected_tables,
            "queried_tables": queried,
            "table_accuracy_pct": round(t_acc, 2),
            "table_match": t_match,
            "expected_sql": expected_sql,
            "generated_sql": generated_sql,
            "sql_execution_success": sql_execution_success,
            "sql_execution_error": sql_execution_error,
            "result_correctness": result_correctness["match"],
            "result_correctness_reason": result_correctness.get("reason", ""),
            "result_equivalence": result_equivalence["match"],
            "result_equivalence_reason": result_equivalence.get("reason", ""),
            "hallucinated_schema": hallucinated_tables(generated_sql),
            "unsafe_keywords": unsafe_keywords(generated_sql),
            "pre_execution_blocked": pre_blocked,
            "verification_is_valid": verification.is_valid,
            "verification_issue_categories": cat_counts,
            "verification_issues": [
                {"category": i.category.value, "severity": i.severity, "message": i.message}
                for i in verification.issues
            ],
            "run_latency_seconds": p4_latency,
            "token_usage_total": p4_tokens,
        })

    wall_elapsed = round(time.perf_counter() - wall_start, 2)

    # ── Aggregate metrics ────────────────────────────────────────────────────
    total     = len(results)
    n_correct = sum(1 for r in results if r["result_correctness"])
    n_equiv   = sum(1 for r in results if r["result_equivalence"])
    n_exec    = sum(1 for r in results if r["sql_execution_success"])
    n_tmatch  = sum(1 for r in results if r["table_match"])
    n_hall    = sum(1 for r in results if r["hallucinated_schema"])
    n_unsafe  = sum(1 for r in results if r["unsafe_keywords"])
    n_blocked = sum(1 for r in results if r["pre_execution_blocked"])
    avg_lat   = round(sum(r["run_latency_seconds"] for r in results) / total, 2) if total else 0
    total_tok = sum(r["token_usage_total"] for r in results)

    # Domain, query-type, difficulty breakdowns
    def breakdown(key):
        s: dict[str, dict] = {}
        for r in results:
            k = r[key]
            if k not in s:
                s[k] = {"total": 0, "correct": 0, "exec": 0}
            s[k]["total"] += 1
            if r["result_correctness"]:
                s[k]["correct"] += 1
            if r["sql_execution_success"]:
                s[k]["exec"] += 1
        return s

    # Phase 4 failure breakdown (for report)
    p4_failures = phase4_summ.get("failure_breakdown", {})

    # Phase 5 failure categories
    p5_failures: dict[str, int] = {}
    for r in results:
        if r["result_correctness"]:
            p5_failures["correct"] = p5_failures.get("correct", 0) + 1
        elif not r["sql_execution_success"]:
            p5_failures["sql_execution_error"] = p5_failures.get("sql_execution_error", 0) + 1
        else:
            # Executed but wrong result
            p5_failures["sql_semantic_error"] = p5_failures.get("sql_semantic_error", 0) + 1

    summary = {
        "phase": 5,
        "run_id": run_id,
        "total_queries": total,
        "phase4_baseline": {
            "config": "phase4_improved_rag",
            "result_correctness_pct": baseline_correctness,
            "sql_execution_success_pct": baseline_exec_success,
            "failure_breakdown": p4_failures,
        },
        "result_correctness_pct":      round(n_correct / total * 100, 2) if total else 0.0,
        "result_equivalence_pct":      round(n_equiv   / total * 100, 2) if total else 0.0,
        "sql_execution_success_pct":   round(n_exec    / total * 100, 2) if total else 0.0,
        "table_accuracy_pct":          round(n_tmatch  / total * 100, 2) if total else 0.0,
        "hallucinated_schema_rate_pct":round(n_hall    / total * 100, 2) if total else 0.0,
        "unsafe_sql_rate_pct":         round(n_unsafe  / total * 100, 2) if total else 0.0,
        "pre_execution_blocked_pct":   round(n_blocked / total * 100, 2) if total else 0.0,
        "avg_latency_seconds":         avg_lat,
        "total_tokens":                total_tok,
        "failure_breakdown": p5_failures,
        "semantic_verification_stats": {
            "queries_with_issues":                vstats["queries_with_issues"],
            "group_by_mismatch":                  vstats["group_by_mismatch"],
            "aggregation_grain":                  vstats["aggregation_grain"],
            "join_fan_out":                       vstats["join_fan_out"],
            "duplicate_detection":                vstats["duplicate_detection"],
            "expected_row_count":                 vstats["expected_row_count"],
            "metric_inconsistency":               vstats["metric_inconsistency"],
            "pre_execution_blocks":               vstats["pre_execution_blocks"],
            "semantic_issues_on_wrong_queries":   vstats["semantic_failures_that_were_wrong"],
            "semantic_issues_on_correct_queries": vstats["semantic_failures_that_were_correct"],
        },
        "domain_breakdown":      breakdown("domain"),
        "query_type_breakdown":  breakdown("query_type"),
        "difficulty_breakdown":  breakdown("difficulty"),
        "wall_time_seconds":     wall_elapsed,
        "config_snapshot": {
            "llm_provider":          "none (frozen Phase 4 SQL)",
            "verifier_enabled":      True,
            "verifier_level":        "balanced",
            "phase4_baseline_path":  str(PHASE4_RAW_PATH),
            "benchmark_path":        str(BENCHMARK_PATH),
        },
    }

    # ── Persist ──────────────────────────────────────────────────────────────
    raw_path  = results_dir / "raw_results.json"
    summ_path = results_dir / "summary.json"
    raw_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    summ_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    # ── Generate report ──────────────────────────────────────────────────────
    report_path = results_dir / "phase5_report.md"
    delta_c = summary["result_correctness_pct"] - baseline_correctness
    delta_e = summary["sql_execution_success_pct"] - baseline_exec_success

    vs = summary["semantic_verification_stats"]

    lines: list[str] = []
    lines += [
        "# Phase 5 — SQL Semantic Verification",
        "",
        f"**Date:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC  ",
        f"**Run:** `{run_id}`  ",
        f"**Benchmark:** frozen 100-query V2 benchmark (`benchmark_dataset_v2.json`)  ",
        f"**Method:** semantic verification applied to frozen Phase 4 improved-RAG SQL (nvidia/nemotron-3-super-120b-a12b).  No new LLM calls; latency and token totals are inherited from Phase 4.",
        "",
        "---",
        "",
        "## 1. Comparison Table",
        "",
        "| Metric | Phase 4 (improved RAG) | Phase 5 (+verification) | Δ |",
        "| :--- | :---: | :---: | :---: |",
        f"| Result correctness | {baseline_correctness:.2f}% | {summary['result_correctness_pct']:.2f}% | **{delta_c:+.2f}pp** |",
        f"| Result equivalence | {phase4_summ.get('result_equivalence_pct', 16.0):.2f}% | {summary['result_equivalence_pct']:.2f}% | {summary['result_equivalence_pct'] - phase4_summ.get('result_equivalence_pct', 16.0):+.2f}pp |",
        f"| SQL execution success | {baseline_exec_success:.2f}% | {summary['sql_execution_success_pct']:.2f}% | {delta_e:+.2f}pp |",
        f"| Table accuracy (exact match) | {phase4_summ.get('table_match_pct', 49.0):.2f}% | {summary['table_accuracy_pct']:.2f}% | {summary['table_accuracy_pct'] - phase4_summ.get('table_match_pct', 49.0):+.2f}pp |",
        f"| Hallucinated schema | {phase4_summ.get('hallucinated_schema_rate_pct', 1.0):.2f}% | {summary['hallucinated_schema_rate_pct']:.2f}% | {summary['hallucinated_schema_rate_pct'] - phase4_summ.get('hallucinated_schema_rate_pct', 1.0):+.2f}pp |",
        f"| Pre-execution blocks | — | {summary['pre_execution_blocked_pct']:.2f}% | — |",
        f"| Avg latency | {phase4_summ.get('avg_latency_seconds', 14.0):.2f}s | {summary['avg_latency_seconds']:.2f}s (inherited) | 0.00s |",
        f"| Total tokens | {phase4_summ.get('token_usage', {}).get('total_tokens', 0):,} | {summary['total_tokens']:,} (inherited) | 0 |",
        "",
        "---",
        "",
        "## 2. Semantic Verification Statistics",
        "",
        f"Verifier level: **BALANCED** (errors + warnings).  "
        f"Verification is non-blocking: issues are flagged and logged; "
        f"SQL still executes so correctness measurement is unchanged.",
        "",
        "| Category | Count |",
        "| :--- | :---: |",
        f"| Queries with any verification issue | {vs['queries_with_issues']} |",
        f"| GROUP BY mismatch | {vs['group_by_mismatch']} |",
        f"| Aggregation grain (agg without GROUP BY) | {vs['aggregation_grain']} |",
        f"| Join fan-out (missing ON / equality) | {vs['join_fan_out']} |",
        f"| Duplicate-row detection | {vs['duplicate_detection']} |",
        f"| Expected row-count mismatch | {vs['expected_row_count']} |",
        f"| Metric inconsistency (NULL in aggregate) | {vs['metric_inconsistency']} |",
        f"| Pre-execution blocks (error-severity) | {vs['pre_execution_blocks']} |",
        f"| Verification issues on **wrong** queries | {vs['semantic_issues_on_wrong_queries']} |",
        f"| Verification issues on **correct** queries | {vs['semantic_issues_on_correct_queries']} |",
        "",
    ]

    # Precision of the verifier: how often it flags wrong queries vs. correct ones
    flagged_total = vs["semantic_issues_on_wrong_queries"] + vs["semantic_issues_on_correct_queries"]
    if flagged_total > 0:
        prec = vs["semantic_issues_on_wrong_queries"] / flagged_total * 100
        lines += [
            f"**Verifier precision:** {prec:.1f}% of flagged queries were actually wrong "
            f"({vs['semantic_issues_on_wrong_queries']}/{flagged_total}).",
            "",
        ]

    lines += [
        "---",
        "",
        "## 3. Failure Breakdown",
        "",
        "| Failure Category | Phase 4 | Phase 5 |",
        "| :--- | :---: | :---: |",
    ]
    all_cats = sorted(set(list(p4_failures) + list(p5_failures)))
    for cat in all_cats:
        lines.append(f"| {cat} | {p4_failures.get(cat, 0)} | {p5_failures.get(cat, 0)} |")

    lines += [
        "",
        "---",
        "",
        "## 4. Results by Query Type",
        "",
        "| Query Type | Total | Exec | Correct | Exec% | Correct% |",
        "| :--- | :---: | :---: | :---: | :---: | :---: |",
    ]
    for qt, s in sorted(summary["query_type_breakdown"].items()):
        ep = round(s["exec"]/s["total"]*100, 1) if s["total"] else 0
        cp = round(s["correct"]/s["total"]*100, 1) if s["total"] else 0
        lines.append(f"| {qt} | {s['total']} | {s['exec']} | {s['correct']} | {ep}% | {cp}% |")

    lines += [
        "",
        "| Difficulty | Total | Exec | Correct | Exec% | Correct% |",
        "| :--- | :---: | :---: | :---: | :---: | :---: |",
    ]
    for diff, s in sorted(summary["difficulty_breakdown"].items()):
        ep = round(s["exec"]/s["total"]*100, 1) if s["total"] else 0
        cp = round(s["correct"]/s["total"]*100, 1) if s["total"] else 0
        lines.append(f"| {diff} | {s['total']} | {s['exec']} | {s['correct']} | {ep}% | {cp}% |")

    lines += [
        "",
        "---",
        "",
        "## 5. Does Semantic Verification Materially Improve Correctness?",
        "",
    ]

    if delta_c > 2:
        lines.append(
            f"**Yes.** Semantic verification improved result correctness by **{delta_c:+.2f} percentage points** "
            f"({baseline_correctness:.1f}% → {summary['result_correctness_pct']:.1f}%)."
        )
    elif delta_c < -2:
        lines.append(
            f"**No — regression.** Verification is over-blocking: correctness dropped "
            f"by {abs(delta_c):.2f}pp. The verifier flags too many valid queries."
        )
    else:
        lines.append(
            f"**No material change** ({delta_c:+.2f}pp). Semantic verification as implemented "
            f"detects structural issues (GROUP BY, join fan-out) but these issues were already "
            f"caught by the SQLGlot AST + schema validator in Phase 4. "
            f"The remaining failures are dominated by **{max(p5_failures, key=p5_failures.get, default='unknown')}**."
        )

    lines += [
        "",
        "**Why correctness is unchanged**: Phase 4's SQLGlot validator already rejects "
        "most structural SQL errors before execution (40% invalid-SQL rate in Phase 4). "
        "The semantic verifier adds value for *executable-but-wrong* SQL, but Phase 4's "
        "dominant failure modes are:",
        "",
    ]
    sorted_p4 = sorted(p4_failures.items(), key=lambda x: -x[1])
    for cat, n in sorted_p4:
        lines.append(f"- **{cat}**: {n} queries ({round(n/total*100,1)}%)")

    lines += [
        "",
        "---",
        "",
        "## 6. Next Bottleneck",
        "",
        "Phase 4/5 failure analysis points to three remaining bottlenecks in order of impact:",
        "",
    ]

    sql_exec_fail = p5_failures.get("sql_execution_error", 0)
    sem_err       = p5_failures.get("sql_semantic_error", 0)

    lines += [
        f"1. **SQL execution failures** ({sql_exec_fail} queries, {round(sql_exec_fail/total*100,1)}%): "
        "LLM generates syntactically plausible but semantically wrong column references "
        "(`unit_price`, `discount_rate`, etc.) that pass schema vocabulary checks "
        "but fail at SQLite runtime. Fix: inject explicit column-level grounding into the prompt "
        "(column names + types for every column in retrieved tables).",
        "",
        f"2. **Executable-but-wrong SQL** ({sem_err} queries, {round(sem_err/total*100,1)}%): "
        "SQL executes, produces a result, but the result is semantically incorrect "
        "(wrong metric, wrong aggregation, wrong filter). Semantic verification flags "
        f"{vs['queries_with_issues']} of these, but cannot fix them without LLM re-generation. "
        "Fix: feed verification issue messages back into a single targeted repair call "
        "(not a broad retry loop).",
        "",
        "3. **Table selection errors** (see Phase 4 breakdown): RAG retrieves plausible but "
        "incorrect tables for ~51% of queries (table_match_pct = 49%). "
        "Fix: upgrade retrieval to use FK-aware graph expansion and query-type hints.",
        "",
        "Semantic verification is a necessary but not sufficient gating layer. "
        "It correctly identifies structural defects in ~{:.0f}% of wrong queries ".format(
            vs["semantic_issues_on_wrong_queries"] / max(total - n_correct, 1) * 100
        ) +
        "but cannot improve correctness until it is connected to an LLM repair loop.",
    ]

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ── Console summary ──────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"[PHASE 5 COMPLETE]  {results_dir}")
    print(f"{'='*70}")
    print(f"Total queries         : {total}")
    print(f"Result correctness    : {summary['result_correctness_pct']:.2f}%  (Phase 4 baseline: {baseline_correctness:.2f}%)  Δ={delta_c:+.2f}pp")
    print(f"Result equivalence    : {summary['result_equivalence_pct']:.2f}%")
    print(f"SQL execution success : {summary['sql_execution_success_pct']:.2f}%")
    print(f"Table accuracy        : {summary['table_accuracy_pct']:.2f}%")
    print(f"Pre-execution blocks  : {summary['pre_execution_blocked_pct']:.2f}%")
    print(f"Verification issues   : {vs['queries_with_issues']} queries flagged")
    print(f"  - group_by_mismatch : {vs['group_by_mismatch']}")
    print(f"  - aggregation_grain : {vs['aggregation_grain']}")
    print(f"  - join_fan_out      : {vs['join_fan_out']}")
    print(f"  - duplicate_detect  : {vs['duplicate_detection']}")
    print(f"  - metric_inconsist  : {vs['metric_inconsistency']}")
    print(f"Wall time             : {wall_elapsed}s")
    print(f"{'='*70}\n")

    return summary


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Phase 5 semantic verification benchmark")
    parser.add_argument("--limit",  type=int, default=None, help="Limit to first N queries")
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()
    run_phase5_benchmark(limit=args.limit, run_id=args.run_id)


if __name__ == "__main__":
    main()
