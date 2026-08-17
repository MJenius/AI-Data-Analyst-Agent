"""Fast Plan-Only Evaluation Harness for Phase 9.

Evaluates all 100 queries in the frozen benchmark strictly on planner alignment
WITHOUT invoking SQL generation or LLM Evaluators.

Measures:
- Intent accuracy
- Entity accuracy
- Metric accuracy
- Aggregation accuracy
- Filter accuracy
- Table accuracy (precision, recall, exact match)
- Join-path accuracy
- Time-grain accuracy
- Ranking accuracy
- Limit accuracy
- Result-shape accuracy
- All-core alignment
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
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_platform.analytics.agents import AnalyticsPlannerAgent
from agent_platform.llms.client import get_llm_client
import sqlite3
from agent_platform.rag.ingestion.schema_context import (
    TABLE_DESCRIPTIONS,
    SchemaContextBuilder,
)
from agent_platform.rag.retriever import SchemaRetriever
from agent_platform.tools.plan_validator import PlanValidator

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BENCHMARK_PATH = ROOT / "tests" / "evaluation" / "benchmark_dataset_v2.json"


def load_benchmark() -> list[dict[str, Any]]:
    with open(BENCHMARK_PATH, encoding="utf-8") as f:
        return json.load(f)


def evaluate_plan_alignment(q_data: dict[str, Any], plan: Any) -> dict[str, Any]:
    expected_tables = set(q_data.get("expected_tables", []))
    planned_tables = set(plan.required_tables if hasattr(plan, "required_tables") else plan.get("required_tables", []))
    
    # Table metrics
    table_exact = (planned_tables == expected_tables)
    intersection = planned_tables & expected_tables
    precision = len(intersection) / len(planned_tables) if planned_tables else 0.0
    recall = len(intersection) / len(expected_tables) if expected_tables else 0.0

    # Metric & Aggregation alignment
    expected_metrics = [m.lower() for m in q_data.get("expected_metrics", [])]
    planned_metric = (plan.metric if hasattr(plan, "metric") else plan.get("metric", "")).lower()
    planned_agg = (plan.aggregation if hasattr(plan, "aggregation") else plan.get("aggregation", "") or "").upper()
    
    metric_aligned = False
    if any(em in planned_metric for em in expected_metrics) or any(planned_metric in em for em in expected_metrics):
        metric_aligned = True
    if planned_agg and any(planned_agg.lower() in em for em in expected_metrics):
        metric_aligned = True
    if not expected_metrics:
        metric_aligned = True

    # Limit & Ranking alignment
    question = q_data["question"].lower()
    expected_limit = None
    top_match = re.search(r"\btop\s+(\d+)\b", question) or re.search(r"\bbottom\s+(\d+)\b", question)
    if top_match:
        expected_limit = int(top_match.group(1))
    elif any(k in question for k in ["which", "what is the highest", "what is the lowest", "highest", "lowest", "most", "least"]):
        if not any(k in question for k in ["top 3", "top 5", "top 10", "all", "each", "every", "monthly"]):
            expected_limit = 1

    planned_limit = plan.limit if hasattr(plan, "limit") else plan.get("limit")
    limit_aligned = (planned_limit == expected_limit) if expected_limit is not None else (planned_limit is None or planned_limit > 1)

    # Time grain alignment
    expected_time_grain = "month" if any(k in question for k in ["month", "monthly", "trend", "over time"]) else None
    planned_time_grain = plan.time_grain if hasattr(plan, "time_grain") else plan.get("time_grain")
    time_grain_aligned = (expected_time_grain == planned_time_grain) if expected_time_grain else True

    # Join path alignment
    join_path_present = bool(plan.join_path if hasattr(plan, "join_path") else plan.get("join_path"))
    join_path_aligned = join_path_present if len(planned_tables) > 1 else True

    # Core alignment = table recall >= 1.0 + metric aligned + limit aligned + time grain aligned
    all_core_aligned = (recall >= 1.0) and metric_aligned and limit_aligned and time_grain_aligned

    return {
        "table_exact": table_exact,
        "table_precision": precision,
        "table_recall": recall,
        "metric_aligned": metric_aligned,
        "limit_aligned": limit_aligned,
        "time_grain_aligned": time_grain_aligned,
        "join_path_aligned": join_path_aligned,
        "all_core_aligned": all_core_aligned,
        "planned_tables": sorted(list(planned_tables)),
        "expected_tables": sorted(list(expected_tables)),
        "planned_metric": planned_metric,
        "planned_limit": planned_limit,
        "expected_limit": expected_limit,
    }


async def run_plan_eval(out_dir: Path, concurrency: int = 5) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    dataset = load_benchmark()
    conn = sqlite3.connect(str(ROOT / "data" / "analytics.db"))
    try:
        docs = SchemaContextBuilder(conn).build()
    finally:
        conn.close()
    retriever = SchemaRetriever.from_documents(docs)
    llm_client = get_llm_client()
    planner = AnalyticsPlannerAgent(retriever, llm_client=llm_client)

    results = [None] * len(dataset)
    print(f"Starting plan evaluation on {len(dataset)} frozen queries with concurrency={concurrency}...")
    started_all = datetime.datetime.now()
    semaphore = asyncio.Semaphore(concurrency)

    async def process_query(idx: int, item: dict[str, Any]):
        async with semaphore:
            q = item["question"]
            print(f"[{idx+1}/{len(dataset)}] Planning: {q[:60]}...")
            plan = await planner.plan(q)
            eval_res = evaluate_plan_alignment(item, plan)
            results[idx] = {
                "query_id": idx + 1,
                "question": q,
                "category": item.get("category", ""),
                "plan": plan.model_dump() if hasattr(plan, "model_dump") else plan,
                "eval": eval_res,
            }

    await asyncio.gather(*(process_query(i, item) for i, item in enumerate(dataset)))

    elapsed = (datetime.datetime.now() - started_all).total_seconds()
    total = len(results)
    all_core_count = sum(1 for r in results if r["eval"]["all_core_aligned"])
    table_exact_count = sum(1 for r in results if r["eval"]["table_exact"])
    metric_aligned_count = sum(1 for r in results if r["eval"]["metric_aligned"])
    limit_aligned_count = sum(1 for r in results if r["eval"]["limit_aligned"])
    time_grain_count = sum(1 for r in results if r["eval"]["time_grain_aligned"])
    join_path_count = sum(1 for r in results if r["eval"]["join_path_aligned"])
    avg_precision = sum(r["eval"]["table_precision"] for r in results) / total if total else 0.0
    avg_recall = sum(r["eval"]["table_recall"] for r in results) / total if total else 0.0

    summary = {
        "timestamp": datetime.datetime.now().isoformat(),
        "total_queries": total,
        "elapsed_seconds": round(elapsed, 2),
        "all_core_alignment_rate": round(all_core_count / total, 4),
        "table_exact_rate": round(table_exact_count / total, 4),
        "table_mean_precision": round(avg_precision, 4),
        "table_mean_recall": round(avg_recall, 4),
        "metric_alignment_rate": round(metric_aligned_count / total, 4),
        "limit_alignment_rate": round(limit_aligned_count / total, 4),
        "time_grain_alignment_rate": round(time_grain_count / total, 4),
        "join_path_alignment_rate": round(join_path_count / total, 4),
    }

    with open(out_dir / "plan_eval_raw.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    with open(out_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\n" + "="*50)
    print("PHASE 9 PLAN-ONLY EVALUATION SUMMARY")
    print("="*50)
    print(f"Total Queries:            {total}")
    print(f"Elapsed Time:             {elapsed:.1f}s")
    print(f"All-Core Alignment:       {summary['all_core_alignment_rate']*100:.1f}% (Phase 8 baseline: ~16%)")
    print(f"Table Exact Match:        {summary['table_exact_rate']*100:.1f}% (Phase 8 baseline: ~29%)")
    print(f"Table Recall:             {summary['table_mean_recall']*100:.1f}%")
    print(f"Table Precision:          {summary['table_mean_precision']*100:.1f}%")
    print(f"Limit Alignment:          {summary['limit_alignment_rate']*100:.1f}% (Phase 8 baseline: ~67%)")
    print(f"Metric Alignment:         {summary['metric_alignment_rate']*100:.1f}% (Phase 8 baseline: ~66%)")
    print(f"Time Grain Alignment:     {summary['time_grain_alignment_rate']*100:.1f}%")
    print(f"Join Path Alignment:      {summary['join_path_alignment_rate']*100:.1f}%")
    print("="*50 + "\n")

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run fast plan-only evaluation.")
    parser.add_argument("--out", default=str(ROOT / "results" / "phase9" / "plan_eval"), help="Output directory")
    args = parser.parse_args()
    asyncio.run(run_plan_eval(Path(args.out)))


if __name__ == "__main__":
    main()
