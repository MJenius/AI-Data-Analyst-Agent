from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(dotenv_path=ROOT / ".env", override=False)

from agent_platform.analytics.service import AnalyticsAgentService
from tests.evaluation.phase3.single_model_groq import SingleModelGroqClient as GroqClient
from agent_platform.llms.nvidia_client import NvidiaClient
from agent_platform.rag.ingestion.schema_context import SchemaContextBuilder
from agent_platform.rag.retriever import SchemaRetriever

from tests.evaluation.phase3 import common
from tests.evaluation.phase3.common import evaluate_query, evaluate_plan, extract_first_sql, classify_failure, parse_plan_loose
from tests.evaluation.phase3.configs import build_configs

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("run_phase3")

DB_PATH = ROOT / "runtime" / "analytics.db"
BENCHMARK_PATH = ROOT / "tests" / "evaluation" / "benchmark_dataset_v2.json"
RESULTS_ROOT = ROOT / "results" / "phase3"
RESULTS_DIR = RESULTS_ROOT

QUERY_TYPES = ["single_value", "aggregation", "ranking", "time_series", "unknown"]
DIFFICULTIES = ["easy", "medium", "hard"]
METRICS = [
    ("result_correctness_pct", "Result correctness"),
    ("result_equivalence_pct", "Result equivalence"),
    ("table_accuracy_pct", "Table accuracy"),
    ("sql_execution_success_pct", "SQL execution success"),
    ("invalid_sql_rate_pct", "Invalid SQL"),
    ("avg_latency_seconds", "Latency (s)"),
]


def get_config_snapshot(run_id: str, config_ids: list[str] | None = None) -> dict[str, Any]:
    provider = os.getenv("EXPERIMENT_LLM_PROVIDER", "groq").lower()
    model = os.getenv("NVIDIA_MODEL") if provider == "nvidia" else os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    return {
        "experiment": "phase3_nl2sql_failure_diagnosis",
        "run_id": run_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "llm_provider": provider,
        "model": model,
        "request_timeout_seconds": float(os.getenv("NVIDIA_TIMEOUT_SECONDS", "60")) if provider == "nvidia" else None,
        "max_output_tokens": int(os.getenv("NVIDIA_MAX_TOKENS", "2048")) if provider == "nvidia" else None,
        "groq_api_key_present": bool(os.getenv("GROQ_API_KEY")),
        "gemini_api_key_present": bool(os.getenv("GEMINI_API_KEY")),
        "db_path": str(DB_PATH),
        "benchmark": str(BENCHMARK_PATH),
        "benchmark_queries": 100,
        "selected_configs": config_ids,
        "configs": {
            "config1_current_system": "Production pipeline untouched: AnalyticsPlannerAgent (LLM) + RAG + AnalyticsExecutorAgent (LLM, 2 retries w/ exec feedback) + AnalyticsEvaluatorAgent. Strict Pydantic validation on all LLM outputs.",
            "config2_llm_full_schema": "LLM + FULL schema context (all SchemaContextBuilder documents). Single SQL gen call, lenient JSON parsing, no planner, no RAG, no feedback.",
            "config3_llm_rag": "LLM + SchemaRetriever.retrieve(top_k=5). Single SQL gen call, lenient parsing, no planner, no feedback.",
            "config4_plan_rag_sql": "Structured QueryPlan (intent/metric/entity/aggregation/filters/group_by/ordering/limit/required_tables) + RAG + SQL gen. Lenient parsing, no execution feedback.",
            "config5_plan_rag_sql_feedback": "Config 4 + execution feedback loop (up to 2 repair attempts with error message). Lenient parsing.",
        },
    }


def build_experiment_client() -> Any:
    provider = os.getenv("EXPERIMENT_LLM_PROVIDER", "groq").lower()
    if provider == "nvidia":
        return NvidiaClient(
            timeout_seconds=float(os.getenv("NVIDIA_TIMEOUT_SECONDS", "60")),
            max_tokens=int(os.getenv("NVIDIA_MAX_TOKENS", "2048")),
        )
    if provider == "groq":
        return GroqClient(model=os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"), max_rpm=30)
    raise ValueError("EXPERIMENT_LLM_PROVIDER must be 'groq' or 'nvidia'.")


def build_full_schema_text() -> list[str]:
    conn = sqlite3.connect(DB_PATH)
    try:
        docs = SchemaContextBuilder(conn).build()
    finally:
        conn.close()
    return [doc.text for doc in docs]


async def run_config(
    config,
    benchmarks: list[dict[str, Any]],
    limit: int | None,
    max_consecutive_provider_errors: int = 3,
    initial_results: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    results = list(initial_results or [])
    n = len(benchmarks) if limit is None else min(limit, len(benchmarks))
    out_path = RESULTS_DIR / config.id / "raw_results.json"
    run_status = {
        "status": "completed",
        "planned_queries": n,
        "completed_queries": len(results),
        "provider_error_count": sum(bool(row.get("provider_error")) for row in results),
        "reason": None,
    }
    consecutive_provider_errors = 0
    for i, bench in enumerate(benchmarks[len(results):n], len(results) + 1):
        q = bench["question"]
        client = getattr(config, "_client", None)
        usage_before = dict(getattr(client, "usage_totals", {}))
        t0 = time.perf_counter()
        outcome = await config.run(q, bench)
        run_latency = outcome.get("latency_seconds", round(time.perf_counter() - t0, 2))

        gen_sql_raw = outcome.get("generated_sql")
        gen_sql = extract_first_sql(gen_sql_raw)
        eval_ = evaluate_query(gen_sql, bench, outcome.get("pre_execution_errors"))

        plan_eval = None
        if outcome.get("plan"):
            plan_eval = evaluate_plan(parse_plan_loose(outcome["plan"]), bench)

        failure = "provider_error" if outcome.get("provider_error") else classify_failure(eval_, plan_eval)

        record = {
            "config": config.id,
            "index": i,
            "question": q,
            "domain": bench.get("domain", bench.get("category")),
            "query_type": bench.get("query_type"),
            "difficulty": bench.get("difficulty"),
            "expected_tables": bench.get("expected_tables"),
            "expected_sql": bench.get("expected_sql"),
            "generated_sql": gen_sql,
            "run_latency_seconds": run_latency,
            "failure_category": failure,
            **eval_,
        }
        usage_after = getattr(client, "usage_totals", {})
        record["token_usage"] = {
            key: usage_after.get(key, 0) - usage_before.get(key, 0)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        }
        if plan_eval is not None:
            record["plan_eval"] = plan_eval
        for k, v in outcome.items():
            if k not in record and k != "error":
                record[k] = v
        if outcome.get("error"):
            record["config_error"] = outcome["error"]
        if outcome.get("provider_error"):
            run_status["provider_error_count"] += 1
            consecutive_provider_errors += 1
        else:
            consecutive_provider_errors = 0

        results.append(record)
        run_status["completed_queries"] = len(results)
        logger.info(
            f"[{config.id}] {i}/{n} correct={eval_['result_correctness']} exec={eval_['sql_execution_success']} "
            f"tables={eval_['table_accuracy_pct']:.0f}% fail={failure} {q[:50]}"
        )
        print(f"[{config.id}] {i}/{n} correct={eval_['result_correctness']} exec={eval_['sql_execution_success']} fail={failure} {q[:60]}")

        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, default=str)
        if consecutive_provider_errors >= max_consecutive_provider_errors:
            run_status.update(
                {
                    "status": "not_run_provider_unavailable",
                    "reason": (
                        f"Stopped after {consecutive_provider_errors} consecutive provider failures; "
                        "these are infrastructure failures, not model-scored benchmark outcomes."
                    ),
                }
            )
            break
        await asyncio.sleep(0.15)
    status_path = RESULTS_DIR / config.id / "run_status.json"
    with open(status_path, "w", encoding="utf-8") as f:
        json.dump(run_status, f, indent=2)
    return results, run_status


def compute_summary(
    results: list[dict[str, Any]], config_id: str, run_status: dict[str, Any] | None = None
) -> dict[str, Any]:
    total = len(results)
    if total == 0:
        return {"config": config_id, "total_queries": 0}

    def pct(cond):
        return round(sum(1 for r in results if cond(r)) / total * 100, 2)

    latencies = [r["run_latency_seconds"] for r in results]
    table_accs = [r["table_accuracy_pct"] for r in results]

    summary = {
        "config": config_id,
        "total_queries": total,
        "run_status": (run_status or {}).get("status", "completed"),
        "planned_queries": (run_status or {}).get("planned_queries", total),
        "provider_error_count": (run_status or {}).get("provider_error_count", 0),
        "result_correctness_pct": pct(lambda r: r["result_correctness"]),
        "result_equivalence_pct": pct(lambda r: r["result_equivalence"]),
        "table_accuracy_pct": round(sum(table_accs) / total, 2),
        "table_match_pct": pct(lambda r: r["table_match"]),
        "sql_execution_success_pct": pct(lambda r: r["sql_execution_success"]),
        "invalid_sql_rate_pct": pct(lambda r: r["invalid_sql"]),
        "hallucinated_schema_rate_pct": pct(lambda r: bool(r["hallucinated_schema"])),
        "unsafe_sql_rate_pct": pct(lambda r: bool(r["unsafe_keywords"])),
        "avg_latency_seconds": round(sum(latencies) / total, 2),
        "min_latency_seconds": round(min(latencies), 2) if latencies else 0,
        "max_latency_seconds": round(max(latencies), 2) if latencies else 0,
        "token_usage": {
            key: sum(r.get("token_usage", {}).get(key, 0) for r in results)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        },
        "failure_breakdown": {},
    }

    for cat in sorted({r["failure_category"] for r in results}):
        summary["failure_breakdown"][cat] = sum(1 for r in results if r["failure_category"] == cat)

    summary["by_query_type"] = {}
    for qt in QUERY_TYPES:
        subset = [r for r in results if r["query_type"] == qt]
        if subset:
            summary["by_query_type"][qt] = {
                "total": len(subset),
                "correct": sum(1 for r in subset if r["result_correctness"]),
                "correct_pct": round(sum(1 for r in subset if r["result_correctness"]) / len(subset) * 100, 2),
                "exec": sum(1 for r in subset if r["sql_execution_success"]),
            }

    summary["by_difficulty"] = {}
    for d in DIFFICULTIES:
        subset = [r for r in results if r["difficulty"] == d]
        if subset:
            summary["by_difficulty"][d] = {
                "total": len(subset),
                "correct": sum(1 for r in subset if r["result_correctness"]),
                "correct_pct": round(sum(1 for r in subset if r["result_correctness"]) / len(subset) * 100, 2),
                "exec": sum(1 for r in subset if r["sql_execution_success"]),
            }
    return summary


def plan_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    with_plan = [r for r in results if "plan_eval" in r]
    total = len(with_plan)
    if total == 0:
        return {"total_with_plan": 0}

    def pct(key):
        return round(sum(1 for r in with_plan if r["plan_eval"][key]) / total * 100, 2)

    summary = {
        "total_with_plan": total,
        "plan_core_ok_pct": pct("plan_core_ok"),
        "plan_full_ok_pct": pct("plan_full_ok"),
        "intent_ok_pct": pct("intent_ok"),
        "metric_ok_pct": pct("metric_ok"),
        "aggregation_ok_pct": pct("aggregation_ok"),
        "group_by_ok_pct": pct("group_by_ok"),
        "ordering_ok_pct": pct("ordering_ok"),
        "limit_ok_pct": pct("limit_ok"),
        "filters_ok_pct": pct("filters_ok"),
        "tables_ok_pct": pct("tables_ok"),
        "plan_ok_sql_wrong": sum(1 for r in with_plan if r["plan_eval"]["plan_core_ok"] and not r["result_correctness"]),
        "plan_wrong_sql_wrong": sum(1 for r in with_plan if not r["plan_eval"]["plan_core_ok"] and not r["result_correctness"]),
        "plan_ok_sql_correct": sum(1 for r in with_plan if r["plan_eval"]["plan_core_ok"] and r["result_correctness"]),
        "by_query_type": {},
    }
    for qt in QUERY_TYPES:
        subset = [r for r in with_plan if r["query_type"] == qt]
        if subset:
            summary["by_query_type"][qt] = {
                "total": len(subset),
                "plan_core_ok": sum(1 for r in subset if r["plan_eval"]["plan_core_ok"]),
                "metric_ok": sum(1 for r in subset if r["plan_eval"]["metric_ok"]),
                "tables_ok": sum(1 for r in subset if r["plan_eval"]["tables_ok"]),
                "aggregation_ok": sum(1 for r in subset if r["plan_eval"]["aggregation_ok"]),
            }
    return summary


def build_report(all_summaries: dict[str, dict], plan_summaries: dict[str, dict], configs_meta: list[dict]) -> str:
    lines = []
    lines.append("# Phase 3 — NL-to-SQL Semantic Failure Diagnosis\n")
    lines.append(f"**Date:** {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    provider = os.getenv("EXPERIMENT_LLM_PROVIDER", "groq")
    model = os.getenv("NVIDIA_MODEL") if provider == "nvidia" else os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    lines.append("**Method:** Controlled ablation on the verified 100-query V3 benchmark (benchmark_dataset_v2.json). "
                 f"LLM: `{model}` via `{provider}`. Config 1 runs the production pipeline untouched; configs 2-5 use a shared "
                 "harness with lenient JSON parsing so the LLM's SQL output is actually exercised.\n")

    lines.append("## 1. Comparison Table\n")
    lines.append("| Metric | " + " | ".join(f"{m['id']}" for m in configs_meta) + " |")
    lines.append("| :--- | " + " | ".join(":---:" for _ in configs_meta) + " |")
    for key, label in METRICS:
        vals = []
        for meta in configs_meta:
            s = all_summaries[meta["id"]]
            if key == "table_accuracy_pct":
                vals.append(f"{s.get(key, 0):.1f}%")
            elif key == "avg_latency_seconds":
                vals.append(f"{s.get(key, 0):.2f}s")
            else:
                vals.append(f"{s.get(key, 0):.1f}%")
        lines.append(f"| {label} | " + " | ".join(vals) + " |")
    lines.append(f"| Hallucinated schema | " + " | ".join(f"{all_summaries[m['id']].get('hallucinated_schema_rate_pct', 0):.1f}%" for m in configs_meta) + " |")
    lines.append(f"| Table match (exact) | " + " | ".join(f"{all_summaries[m['id']].get('table_match_pct', 0):.1f}%" for m in configs_meta) + " |")
    lines.append(f"| Total tokens | " + " | ".join(str(all_summaries[m['id']].get('token_usage', {}).get('total_tokens', 0)) for m in configs_meta) + " |")
    lines.append("\n")

    lines.append("## 2. Results by Query Type / Difficulty\n")
    for meta in configs_meta:
        s = all_summaries[meta["id"]]
        lines.append(f"### {meta['id']}: {meta['name']}\n")
        lines.append("| Query Type | Total | Correct | % | Exec % |")
        lines.append("| :--- | :---: | :---: | :---: | :---: |")
        for qt in QUERY_TYPES:
            b = s["by_query_type"].get(qt)
            if b:
                lines.append(f"| {qt} | {b['total']} | {b['correct']} | {b['correct_pct']} | {round(b['exec'] / b['total'] * 100, 1)} |")
        lines.append("\n| Difficulty | Total | Correct | % | Exec % |")
        lines.append("| :--- | :---: | :---: | :---: | :---: |")
        for d in DIFFICULTIES:
            b = s["by_difficulty"].get(d)
            if b:
                lines.append(f"| {d} | {b['total']} | {b['correct']} | {b['correct_pct']} | {round(b['exec'] / b['total'] * 100, 1)} |")
        lines.append("\n")

    lines.append("## 3. Failure Breakdown\n")
    lines.append("| Failure category | " + " | ".join(f"{m['id']}" for m in configs_meta) + " |")
    lines.append("| :--- | " + " | ".join(":---:" for _ in configs_meta) + " |")
    all_cats = sorted({cat for meta in configs_meta for cat in all_summaries[meta["id"]]["failure_breakdown"]})
    for cat in all_cats:
        lines.append(f"| {cat} | " + " | ".join(str(all_summaries[m["id"]]["failure_breakdown"].get(cat, 0)) for m in configs_meta) + " |")
    lines.append("\n")

    lines.append("## 4. Structured Query Plan Correctness (Configs 4 & 5)\n")
    for meta in configs_meta:
        if meta["id"] not in plan_summaries or plan_summaries[meta["id"]].get("total_with_plan", 0) == 0:
            continue
        ps = plan_summaries[meta["id"]]
        lines.append(f"### {meta['id']}\n")
        lines.append("| Plan component | Correct % |")
        lines.append("| :--- | :---: |")
        for key, label in [
            ("plan_core_ok_pct", "Plan core (tables+metric+agg+group_by)"),
            ("plan_full_ok_pct", "Plan full (all components)"),
            ("intent_ok_pct", "Intent"),
            ("metric_ok_pct", "Metric"),
            ("aggregation_ok_pct", "Aggregation"),
            ("group_by_ok_pct", "Group by"),
            ("ordering_ok_pct", "Ordering"),
            ("limit_ok_pct", "Limit"),
            ("filters_ok_pct", "Filters"),
            ("tables_ok_pct", "Required tables"),
        ]:
            lines.append(f"| {label} | {ps.get(key, 0)} |")
        lines.append("\nPlan vs outcome:")
        lines.append(f"- Plan correct, result correct: **{ps['plan_ok_sql_correct']}**")
        lines.append(f"- Plan correct, result WRONG: **{ps['plan_ok_sql_wrong']}** (SQL generation bottleneck)")
        lines.append(f"- Plan wrong, result wrong: **{ps['plan_wrong_sql_wrong']}** (planning/intent bottleneck)")
        lines.append("\nPlan correctness by query type:\n")
        lines.append("| Query Type | Total | Plan core OK | Metric OK | Tables OK | Agg OK |")
        lines.append("| :--- | :---: | :---: | :---: | :---: | :---: |")
        for qt in QUERY_TYPES:
            b = ps["by_query_type"].get(qt)
            if b:
                lines.append(f"| {qt} | {b['total']} | {b['plan_core_ok']} | {b['metric_ok']} | {b['tables_ok']} | {b['aggregation_ok']} |")
        lines.append("\n")

    lines.append("## 5. Ablation Deltas (bottleneck evidence)\n")
    lines.append("| Delta | Meaning | Value (pp) |")
    lines.append("| :--- | :--- | :---: |")
    deltas = [
        ("config3_llm_rag", "config2_llm_full_schema", "C3 - C2", "Effect of RAG over full schema (no planner)"),
        ("config4_plan_rag_sql", "config3_llm_rag", "C4 - C3", "Effect of structured planner (RAG held)"),
        ("config5_plan_rag_sql_feedback", "config4_plan_rag_sql", "C5 - C4", "Effect of execution feedback / repair"),
        ("config1_current_system", "config5_plan_rag_sql_feedback", "C1 - C5", "Production pipeline vs experimental"),
    ]
    for left, right, label, meaning in deltas:
        if left in all_summaries and right in all_summaries:
            value = all_summaries[left]["result_correctness_pct"] - all_summaries[right]["result_correctness_pct"]
            lines.append(f"| {label} | {meaning} | {value:+.1f} |")
    lines.append("\n")

    lines.append("## 6. Methodology Notes\n")
    lines.append("- Result correctness: query-type-aware comparison of generated result vs gold `expected_result`.")
    lines.append("- Result equivalence: generated result vs independently executed gold SQL result.")
    lines.append("- Table accuracy: fraction of `expected_tables` present in generated SQL (avg over queries).")
    lines.append("- Invalid SQL: generated SQL that fails to execute (syntax / unknown column / unknown table).")
    lines.append("- Config 1 `generated_sql` is the first executed SQL statement from `sql_queries` (same extraction as the V3 harness).")
    return "\n".join(lines)


async def main(limit: int | None, run_id: str | None = None, config_ids: list[str] | None = None) -> None:
    global RESULTS_DIR
    if not DB_PATH.exists():
        logger.error(f"Database not found at {DB_PATH}")
        sys.exit(1)
    if not BENCHMARK_PATH.exists():
        logger.error(f"Benchmark not found at {BENCHMARK_PATH}")
        sys.exit(1)

    run_id = run_id or datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%SZ")
    RESULTS_DIR = RESULTS_ROOT / run_id
    if RESULTS_DIR.exists():
        logger.error("Experiment output directory already exists: %s", RESULTS_DIR)
        logger.error("Choose a new --run-id; raw experiment artifacts are immutable.")
        sys.exit(2)

    common.DB_PATH = str(DB_PATH)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_DIR / "config_snapshot.json", "w", encoding="utf-8") as f:
        json.dump(get_config_snapshot(run_id, config_ids), f, indent=2)

    with open(BENCHMARK_PATH, "r", encoding="utf-8") as f:
        benchmarks = json.load(f)
    logger.info(f"Loaded {len(benchmarks)} benchmark queries.")

    full_schema_text = build_full_schema_text()
    conn = sqlite3.connect(DB_PATH)
    try:
        docs = SchemaContextBuilder(conn).build()
    finally:
        conn.close()
    retriever = SchemaRetriever.from_documents(docs)

    client = build_experiment_client()
    service = AnalyticsAgentService.from_sqlite(DB_PATH, llm_client=client)

    configs = build_configs(service, client, retriever, full_schema_text)
    if config_ids:
        configs = [config for config in configs if config.id in config_ids]
    configs_meta = [{"id": c.id, "name": c.name} for c in configs]

    all_summaries: dict[str, dict] = {}
    plan_summaries: dict[str, dict] = {}

    for config in configs:
        print(f"\n{'='*80}\nRUNNING {config.id}: {config.name}\n{'='*80}")
        results, run_status = await run_config(config, benchmarks, limit)
        summary = compute_summary(results, config.id, run_status)
        all_summaries[config.id] = summary
        if config.id in ("config4_plan_rag_sql", "config5_plan_rag_sql_feedback"):
            plan_summaries[config.id] = plan_summary(results)
        with open(RESULTS_DIR / config.id / "summary.json", "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)

    with open(RESULTS_DIR / "all_summaries.json", "w", encoding="utf-8") as f:
        json.dump({"summaries": all_summaries, "plan_summaries": plan_summaries, "configs": configs_meta}, f, indent=2)

    report = build_report(all_summaries, plan_summaries, configs_meta)
    with open(RESULTS_DIR / "phase3_report.md", "w", encoding="utf-8") as f:
        f.write(report)

    print("\n" + "=" * 80)
    print("PHASE 3 COMPLETE")
    print("=" * 80)
    for meta in configs_meta:
        s = all_summaries[meta["id"]]
        print(f"{meta['id']}: correct={s['result_correctness_pct']}% equiv={s['result_equivalence_pct']}% "
              f"tables={s['table_accuracy_pct']}% exec={s['sql_execution_success_pct']}% "
              f"invalid={s['invalid_sql_rate_pct']}% latency={s['avg_latency_seconds']}s")
    print(f"Report: {RESULTS_DIR / 'phase3_report.md'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 3 controlled NL-to-SQL experiments")
    parser.add_argument("--limit", type=int, default=None, help="Run only the first N queries (sanity mode)")
    parser.add_argument(
        "--run-id",
        default=None,
        help="Immutable artifact directory name under results/phase3 (default: UTC timestamp).",
    )
    parser.add_argument(
        "--configs",
        nargs="+",
        choices=[
            "config1_current_system",
            "config2_llm_full_schema",
            "config3_llm_rag",
            "config4_plan_rag_sql",
            "config5_plan_rag_sql_feedback",
        ],
        help="Run only the selected configurations.",
    )
    args = parser.parse_args()
    asyncio.run(main(args.limit, args.run_id, args.configs))
