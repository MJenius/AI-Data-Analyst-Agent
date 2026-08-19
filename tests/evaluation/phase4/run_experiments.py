from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sqlglot
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SRC))
load_dotenv(ROOT / ".env", override=False)

from agent_platform.rag.ingestion.schema_context import SchemaContextBuilder
from agent_platform.rag.retriever import SchemaRetriever
from agent_platform.tools.sql_tool import SQLValidator
from tests.evaluation.phase3 import common
from tests.evaluation.phase3 import run_experiments as shared
from tests.evaluation.phase4.configs import build_configs


DB_PATH = ROOT / "data" / "analytics.db"
BENCHMARK_PATH = ROOT / "tests" / "evaluation" / "benchmark_dataset_v2.json"
RESULTS_ROOT = ROOT / "results" / "phase4"
PHASE3_SUMMARIES = (
    ROOT / "results" / "phase3" / "run_20260815T_phase3_nvidia_nemotron_120b_controlled" / "all_summaries.json"
)


def _snapshot(run_id: str, config_ids: list[str]) -> dict[str, Any]:
    provider = os.getenv("EXPERIMENT_LLM_PROVIDER", "groq").lower()
    model = os.getenv("NVIDIA_MODEL") if provider == "nvidia" else os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    return {
        "phase": 4,
        "run_id": run_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "provider": provider,
        "model": model,
        "database": str(DB_PATH),
        "benchmark": str(BENCHMARK_PATH),
        "benchmark_sha256": hashlib.sha256(BENCHMARK_PATH.read_bytes()).hexdigest().upper(),
        "benchmark_queries": 100,
        "sqlglot_version": sqlglot.__version__,
        "configs": config_ids,
        "retrieval": {
            "current": "unchanged vector index search with top_k=5",
            "improved": "hybrid table/column/business-term evidence + shortest relationship paths; max_tables=6",
            "full": "all table packets, relationships, business terms, and schema summary; duplicate column search documents omitted",
        },
        "execution_feedback": "No benchmark retry. Production permits one repair only for concrete AST/schema/SQLite diagnostics.",
    }


def _augment_summary(summary: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    if not total:
        return summary
    summary["table_precision_pct"] = round(sum(row.get("table_precision_pct", 0) for row in rows) / total, 2)
    summary["pre_execution_blocked_pct"] = round(
        sum(bool(row.get("pre_execution_blocked")) for row in rows) / total * 100, 2
    )
    expected_recall = []
    retrieval_precision = []
    unnecessary = 0
    for row in rows:
        expected = set(row.get("expected_tables") or [])
        retrieved = set(row.get("retrieved_tables") or [])
        expected_recall.append(len(expected & retrieved) / len(expected) if expected else 1.0)
        retrieval_precision.append(len(expected & retrieved) / len(retrieved) if retrieved else (1.0 if not expected else 0.0))
        unnecessary += bool(retrieved - expected)
    summary["retrieval_table_recall_pct"] = round(sum(expected_recall) / total * 100, 2)
    summary["retrieval_table_precision_pct"] = round(sum(retrieval_precision) / total * 100, 2)
    summary["retrieval_unnecessary_table_rate_pct"] = round(unnecessary / total * 100, 2)
    categories = Counter()
    for row in rows:
        for error in row.get("validation_errors") or []:
            categories[error.split(":", 1)[0]] += 1
    summary["validation_failure_breakdown"] = dict(sorted(categories.items()))
    scored = [row for row in rows if not row.get("provider_error")]
    if scored:
        summary["provider_adjusted"] = {
            "scored_queries": len(scored),
            "result_correctness_pct": round(sum(row["result_correctness"] for row in scored) / len(scored) * 100, 2),
            "result_equivalence_pct": round(sum(row["result_equivalence"] for row in scored) / len(scored) * 100, 2),
            "table_accuracy_pct": round(sum(row["table_accuracy_pct"] for row in scored) / len(scored), 2),
            "sql_execution_success_pct": round(sum(row["sql_execution_success"] for row in scored) / len(scored) * 100, 2),
            "invalid_sql_rate_pct": round(sum(row["invalid_sql"] for row in scored) / len(scored) * 100, 2),
            "avg_latency_seconds": round(sum(row["run_latency_seconds"] for row in scored) / len(scored), 2),
        }
    return summary


def _phase3_baselines() -> dict[str, Any]:
    if not PHASE3_SUMMARIES.exists():
        return {}
    payload = json.loads(PHASE3_SUMMARIES.read_text(encoding="utf-8"))
    return payload.get("summaries", payload)


def _report(summaries: dict[str, dict], plan_summaries: dict[str, dict], run_id: str) -> str:
    order = [
        "phase4_full_schema",
        "phase4_current_top5",
        "phase4_improved_rag",
        "phase4_plan_improved_rag",
    ]
    names = {
        "phase4_full_schema": "Full schema",
        "phase4_current_top5": "Current top-5 RAG",
        "phase4_improved_rag": "Improved RAG",
        "phase4_plan_improved_rag": "Planner + improved RAG",
    }
    available = [config_id for config_id in order if config_id in summaries]
    lines = [
        "# Phase 4 — Schema Grounding and SQL Generation",
        "",
        f"Run: `{run_id}`. Frozen benchmark SHA-256: `{hashlib.sha256(BENCHMARK_PATH.read_bytes()).hexdigest().upper()}`.",
        "No benchmark question or benchmark SQL was used by retrieval, prompts, validation, or repair logic.",
        "",
        "## What changed",
        "",
        "- Schema packets now carry exact names/types, canonical and live keys, table grain, null/range/common-value statistics, business definitions, and complete allowed join edges.",
        "- Improved RAG combines table/column/business evidence and expands the shortest valid relationship paths; current top-5 search remains the control.",
        "- SQLGlot parses and qualifies every generated query against the live SQLite schema before execution, rejecting malformed/unsafe SQL, unknown tables/columns, out-of-context tables, and invalid physical joins.",
        "- The SQL prompt requires an explicit table/column/join grounding manifest and discourages unnecessary tables and one-to-many fan-out.",
        "- Structured QueryPlan is retained as a diagnostic ablation. Benchmark configurations use no execution retry; production allows one repair only for a concrete SQL/schema diagnostic.",
        "",
        "## Before/after metrics",
        "",
        "| Metric | " + " | ".join(names[config_id] for config_id in available) + " |",
        "| :--- | " + " | ".join("---:" for _ in available) + " |",
    ]
    metrics = [
        ("result_correctness_pct", "Result correctness", "%"),
        ("result_equivalence_pct", "Result equivalence", "%"),
        ("table_accuracy_pct", "SQL table recall/accuracy", "%"),
        ("table_precision_pct", "SQL table precision", "%"),
        ("sql_execution_success_pct", "SQL execution success", "%"),
        ("invalid_sql_rate_pct", "Invalid SQL", "%"),
        ("hallucinated_schema_rate_pct", "Schema hallucination", "%"),
        ("pre_execution_blocked_pct", "Blocked before execution", "%"),
        ("avg_latency_seconds", "Average latency", "s"),
    ]
    for key, label, suffix in metrics:
        lines.append(
            f"| {label} | " + " | ".join(f"{summaries[config_id].get(key, 0):.2f}{suffix}" for config_id in available) + " |"
        )
    lines.append(
        "| Total tokens | "
        + " | ".join(str(summaries[config_id].get("token_usage", {}).get("total_tokens", 0)) for config_id in available)
        + " |"
    )
    lines.append(
        "| Provider errors | " + " | ".join(str(summaries[config_id].get("provider_error_count", 0)) for config_id in available) + " |"
    )
    lines.append(
        "| Correctness excl. provider failures | "
        + " | ".join(f"{summaries[config_id].get('provider_adjusted', {}).get('result_correctness_pct', 0):.2f}%" for config_id in available)
        + " |"
    )

    phase3 = _phase3_baselines()
    if phase3:
        lines.extend([
            "",
            "Phase 3 controlled references: full schema **{:.1f}%** correct / **{:.1f}%** table accuracy; current top-5 RAG **{:.1f}%** / **{:.1f}%**; planner + top-5 RAG **{:.1f}%** / **{:.1f}%**.".format(
                phase3.get("config2_llm_full_schema", {}).get("result_correctness_pct", 0),
                phase3.get("config2_llm_full_schema", {}).get("table_accuracy_pct", 0),
                phase3.get("config3_llm_rag", {}).get("result_correctness_pct", 0),
                phase3.get("config3_llm_rag", {}).get("table_accuracy_pct", 0),
                phase3.get("config4_plan_rag_sql", {}).get("result_correctness_pct", 0),
                phase3.get("config4_plan_rag_sql", {}).get("table_accuracy_pct", 0),
            ),
        ])

    if "phase4_full_schema" in summaries and "phase4_improved_rag" in summaries:
        full = summaries["phase4_full_schema"]
        improved = summaries["phase4_improved_rag"]
        correctness_gap = full["result_correctness_pct"] - improved["result_correctness_pct"]
        table_gap = full["table_accuracy_pct"] - improved["table_accuracy_pct"]
        closes = correctness_gap <= 3 and table_gap <= 3
        lines.extend([
            "",
            "## Does improved RAG close the full-schema gap?",
            "",
            f"**{'Yes' if closes else 'No'} under a 3-point parity threshold.** Improved RAG is "
            f"{abs(correctness_gap):.2f} points {'behind' if correctness_gap > 0 else 'ahead of'} full schema on correctness and "
            f"{abs(table_gap):.2f} points {'behind' if table_gap > 0 else 'ahead of'} it on table accuracy.",
        ])

    lines.extend(["", "## Remaining dominant failure modes", ""])
    for config_id in available:
        summary = summaries[config_id]
        failures = sorted(summary.get("failure_breakdown", {}).items(), key=lambda item: -item[1])[:3]
        validation = sorted(summary.get("validation_failure_breakdown", {}).items(), key=lambda item: -item[1])[:3]
        lines.append(
            f"- **{names[config_id]}:** outcomes {', '.join(f'{key}={value}' for key, value in failures) or 'none'}; "
            f"pre-execution validation {', '.join(f'{key}={value}' for key, value in validation) or 'none'}."
        )
    plan = plan_summaries.get("phase4_plan_improved_rag", {})
    if plan:
        lines.append(
            f"- Planner diagnostic: core plan correctness {plan.get('plan_core_ok_pct', 0):.2f}%; "
            f"plan-correct/result-wrong cases {plan.get('plan_ok_sql_wrong', 0)}."
        )

    dominant = {
        key: value
        for key, value in summaries.get("phase4_improved_rag", {}).get("failure_breakdown", {}).items()
        if key != "correct"
    }
    top_failure = max(dominant, key=dominant.get) if dominant else "unknown"
    lines.extend([
        "",
        "## Phase 5 recommendation",
        "",
        f"Target the measured dominant improved-RAG failure (`{top_failure}`) with result-level semantic verification and aggregate-grain checks. Keep AST/schema validation and the full-schema control fixed; do not add broad retries. Phase 5 was not started.",
    ])
    return "\n".join(lines) + "\n"


async def main(limit: int | None, run_id: str | None, selected: list[str] | None, resume: bool = False) -> Path:
    run_id = run_id or datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%SZ")
    results_dir = RESULTS_ROOT / run_id
    if results_dir.exists() and not resume:
        raise SystemExit(f"Experiment output already exists: {results_dir}")
    if resume and not results_dir.exists():
        raise SystemExit(f"Cannot resume missing experiment output: {results_dir}")
    benchmarks = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))
    connection = sqlite3.connect(DB_PATH)
    try:
        documents = SchemaContextBuilder(connection).build()
    finally:
        connection.close()
    retriever = SchemaRetriever.from_documents(documents)
    validator = SQLValidator(DB_PATH)
    client = shared.build_experiment_client()
    configs = build_configs(client, validator, retriever)
    if selected:
        configs = [config for config in configs if config.id in selected]
    config_ids = [config.id for config in configs]

    if not resume:
        results_dir.mkdir(parents=True)
        (results_dir / "config_snapshot.json").write_text(
            json.dumps(_snapshot(run_id, config_ids), indent=2), encoding="utf-8"
        )
    shared.RESULTS_DIR = results_dir
    common.DB_PATH = str(DB_PATH)
    existing_summary_path = results_dir / "all_summaries.json"
    existing_summaries = json.loads(existing_summary_path.read_text(encoding="utf-8")) if resume and existing_summary_path.exists() else {}
    summaries = existing_summaries.get("summaries", {})
    plan_summaries = existing_summaries.get("plan_summaries", {})
    for config in configs:
        print(f"\nRUNNING {config.id}: {config.name}", flush=True)
        raw_path = results_dir / config.id / "raw_results.json"
        initial_rows = json.loads(raw_path.read_text(encoding="utf-8")) if resume and raw_path.exists() else []
        while initial_rows and initial_rows[-1].get("provider_error"):
            initial_rows.pop()
        rows, status = await shared.run_config(config, benchmarks, limit, initial_results=initial_rows)
        summary = _augment_summary(shared.compute_summary(rows, config.id, status), rows)
        summaries[config.id] = summary
        if config.id == "phase4_plan_improved_rag":
            plan_summaries[config.id] = shared.plan_summary(rows)
        (results_dir / config.id / "summary.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )

    (results_dir / "all_summaries.json").write_text(
        json.dumps({"summaries": summaries, "plan_summaries": plan_summaries}, indent=2), encoding="utf-8"
    )
    (results_dir / "phase4_report.md").write_text(
        _report(summaries, plan_summaries, run_id), encoding="utf-8"
    )
    print(f"\nPHASE 4 COMPLETE: {results_dir}", flush=True)
    return results_dir


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 4 schema-grounding benchmark")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--configs",
        nargs="+",
        choices=[
            "phase4_full_schema",
            "phase4_current_top5",
            "phase4_improved_rag",
            "phase4_plan_improved_rag",
        ],
    )
    args = parser.parse_args()
    asyncio.run(main(args.limit, args.run_id, args.configs, args.resume))
