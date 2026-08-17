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
- Ranking accuracy (direction)
- Limit accuracy
- Result-shape accuracy
- Composite metric alignment
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
    planned_metric = str(plan.metric if hasattr(plan, "metric") else plan.get("metric", "") or "").lower()
    planned_agg = str(plan.aggregation if hasattr(plan, "aggregation") else plan.get("aggregation", "") or "").upper()
    
    metric_aligned = False
    if any(em in planned_metric for em in expected_metrics) or any(planned_metric in em for em in expected_metrics):
        metric_aligned = True
    if planned_agg and any(planned_agg.lower() in em for em in expected_metrics):
        metric_aligned = True
    if not expected_metrics:
        metric_aligned = True

    # Aggregation alignment (separate from metric)
    expected_agg = q_data.get("expected_aggregation", "").upper()
    agg_aligned = True
    if expected_agg:
        agg_aligned = planned_agg == expected_agg

    # Limit & Ranking alignment
    question = q_data["question"].lower()
    expected_limit = None
    top_match = re.search(r"\btop\s+(\d+)\b", question) or re.search(r"\bbottom\s+(\d+)\b", question)
    if top_match:
        expected_limit = int(top_match.group(1))
    elif any(k in question for k in ["which", "what is the highest", "what is the lowest", "highest", "lowest", "most", "least"]):
        if not any(k in question for k in ["top 3", "top 5", "top 10", "all", "each", "every", "monthly", "trend", "distribution"]):
            expected_limit = 1

    planned_limit = plan.limit if hasattr(plan, "limit") else plan.get("limit")
    limit_aligned = (planned_limit == expected_limit) if expected_limit is not None else (planned_limit is None or planned_limit > 1)

    # Ranking direction alignment
    planned_direction = (plan.ranking_direction if hasattr(plan, "ranking_direction") else plan.get("ranking_direction")) or ""
    expected_direction = ""
    if any(k in question for k in ["highest", "most", "best", "top", "fastest", "maximum", "largest"]):
        expected_direction = "DESC"
    elif any(k in question for k in ["lowest", "least", "worst", "bottom", "slowest", "minimum", "smallest"]):
        expected_direction = "ASC"
    ranking_direction_aligned = True
    if expected_direction:
        ranking_direction_aligned = str(planned_direction).upper() == expected_direction

    # Time grain alignment
    expected_time_grain = None
    if any(k in question for k in ["month", "monthly", "per month"]):
        expected_time_grain = "month"
    elif any(k in question for k in ["trend", "over time"]):
        expected_time_grain = "month"  # Default grain for trends
    elif any(k in question for k in ["yearly", "annual", "per year"]):
        expected_time_grain = "year"
    planned_time_grain = plan.time_grain if hasattr(plan, "time_grain") else plan.get("time_grain")
    time_grain_aligned = (expected_time_grain == planned_time_grain) if expected_time_grain else True

    # Join path alignment
    join_path_present = bool(plan.join_path if hasattr(plan, "join_path") else plan.get("join_path"))
    join_path_aligned = join_path_present if len(planned_tables) > 1 else True

    # Result shape alignment
    planned_shape = plan.result_shape if hasattr(plan, "result_shape") else plan.get("result_shape")
    if hasattr(planned_shape, "value"):
        planned_shape = planned_shape.value
    expected_shape = q_data.get("expected_result_shape")
    result_shape_aligned = True
    if expected_shape:
        result_shape_aligned = str(planned_shape) == expected_shape

    # Composite metric alignment
    has_composite = bool(plan.composite_metric if hasattr(plan, "composite_metric") else plan.get("composite_metric"))
    needs_composite = any(k in question for k in ["rate", "ratio", "percentage", "aov", "average order value", "per", "arpu"])
    composite_aligned = has_composite if needs_composite else True

    # Entity alignment
    planned_entities = plan.entities if hasattr(plan, "entities") else plan.get("entities", [])
    expected_entities = q_data.get("expected_entities", [])
    entity_aligned = True
    if expected_entities:
        planned_entities_lower = [e.lower() for e in (planned_entities or [])]
        entity_aligned = any(e.lower() in " ".join(planned_entities_lower) for e in expected_entities)

    # Filter alignment
    planned_filters = plan.filters if hasattr(plan, "filters") else plan.get("filters", [])
    expected_filters = q_data.get("expected_filters", [])
    filter_aligned = True
    if expected_filters:
        planned_filter_str = " ".join(str(f).lower() for f in (planned_filters or []))
        filter_aligned = all(any(ef.lower() in planned_filter_str for ef in expected_filters[:1]) for _ in [1]) if expected_filters else True

    # Core alignment = table recall >= 1.0 + metric aligned + limit aligned + time grain aligned
    all_core_aligned = (recall >= 1.0) and metric_aligned and limit_aligned and time_grain_aligned

    return {
        "table_exact": table_exact,
        "table_precision": precision,
        "table_recall": recall,
        "metric_aligned": metric_aligned,
        "aggregation_aligned": agg_aligned,
        "limit_aligned": limit_aligned,
        "ranking_direction_aligned": ranking_direction_aligned,
        "time_grain_aligned": time_grain_aligned,
        "join_path_aligned": join_path_aligned,
        "result_shape_aligned": result_shape_aligned,
        "composite_aligned": composite_aligned,
        "entity_aligned": entity_aligned,
        "filter_aligned": filter_aligned,
        "all_core_aligned": all_core_aligned,
        "planned_tables": sorted(list(planned_tables)),
        "expected_tables": sorted(list(expected_tables)),
        "planned_metric": planned_metric,
        "planned_aggregation": planned_agg,
        "planned_limit": planned_limit,
        "expected_limit": expected_limit,
        "planned_direction": str(planned_direction),
        "expected_direction": expected_direction,
        "planned_shape": str(planned_shape),
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
    errors = []
    print(f"Starting plan evaluation on {len(dataset)} frozen queries with concurrency={concurrency}...")
    print(f"Provider: {type(llm_client).__name__}")
    started_all = datetime.datetime.now()
    semaphore = asyncio.Semaphore(concurrency)

    async def process_query(idx: int, item: dict[str, Any]):
        async with semaphore:
            q = item["question"]
            try:
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
            except Exception as exc:
                logger.error(f"Error planning query {idx+1}: {exc}")
                errors.append({"query_id": idx + 1, "question": q, "error": str(exc)})
                results[idx] = {
                    "query_id": idx + 1,
                    "question": q,
                    "category": item.get("category", ""),
                    "plan": None,
                    "eval": {k: False for k in ["table_exact", "metric_aligned", "limit_aligned",
                             "time_grain_aligned", "join_path_aligned", "all_core_aligned",
                             "ranking_direction_aligned", "result_shape_aligned", "composite_aligned",
                             "entity_aligned", "filter_aligned", "aggregation_aligned"]},
                    "error": str(exc),
                }
                results[idx]["eval"]["table_precision"] = 0.0
                results[idx]["eval"]["table_recall"] = 0.0

    await asyncio.gather(*(process_query(i, item) for i, item in enumerate(dataset)))

    elapsed = (datetime.datetime.now() - started_all).total_seconds()
    valid_results = [r for r in results if r is not None]
    total = len(valid_results)
    
    all_core_count = sum(1 for r in valid_results if r["eval"].get("all_core_aligned"))
    table_exact_count = sum(1 for r in valid_results if r["eval"].get("table_exact"))
    metric_aligned_count = sum(1 for r in valid_results if r["eval"].get("metric_aligned"))
    agg_aligned_count = sum(1 for r in valid_results if r["eval"].get("aggregation_aligned"))
    limit_aligned_count = sum(1 for r in valid_results if r["eval"].get("limit_aligned"))
    ranking_dir_count = sum(1 for r in valid_results if r["eval"].get("ranking_direction_aligned"))
    time_grain_count = sum(1 for r in valid_results if r["eval"].get("time_grain_aligned"))
    join_path_count = sum(1 for r in valid_results if r["eval"].get("join_path_aligned"))
    result_shape_count = sum(1 for r in valid_results if r["eval"].get("result_shape_aligned"))
    composite_count = sum(1 for r in valid_results if r["eval"].get("composite_aligned"))
    entity_count = sum(1 for r in valid_results if r["eval"].get("entity_aligned"))
    filter_count = sum(1 for r in valid_results if r["eval"].get("filter_aligned"))
    avg_precision = sum(r["eval"].get("table_precision", 0) for r in valid_results) / total if total else 0.0
    avg_recall = sum(r["eval"].get("table_recall", 0) for r in valid_results) / total if total else 0.0

    summary = {
        "timestamp": datetime.datetime.now().isoformat(),
        "provider": type(llm_client).__name__,
        "total_queries": total,
        "error_count": len(errors),
        "elapsed_seconds": round(elapsed, 2),
        "all_core_alignment_rate": round(all_core_count / total, 4) if total else 0.0,
        "table_exact_rate": round(table_exact_count / total, 4) if total else 0.0,
        "table_mean_precision": round(avg_precision, 4),
        "table_mean_recall": round(avg_recall, 4),
        "metric_alignment_rate": round(metric_aligned_count / total, 4) if total else 0.0,
        "aggregation_alignment_rate": round(agg_aligned_count / total, 4) if total else 0.0,
        "limit_alignment_rate": round(limit_aligned_count / total, 4) if total else 0.0,
        "ranking_direction_alignment_rate": round(ranking_dir_count / total, 4) if total else 0.0,
        "time_grain_alignment_rate": round(time_grain_count / total, 4) if total else 0.0,
        "join_path_alignment_rate": round(join_path_count / total, 4) if total else 0.0,
        "result_shape_alignment_rate": round(result_shape_count / total, 4) if total else 0.0,
        "composite_alignment_rate": round(composite_count / total, 4) if total else 0.0,
        "entity_alignment_rate": round(entity_count / total, 4) if total else 0.0,
        "filter_alignment_rate": round(filter_count / total, 4) if total else 0.0,
    }

    # Per-category breakdown
    categories: dict[str, list] = {}
    for r in valid_results:
        cat = r.get("category", "unknown")
        categories.setdefault(cat, []).append(r)
    category_breakdown = {}
    for cat, cat_results in sorted(categories.items()):
        cat_total = len(cat_results)
        category_breakdown[cat] = {
            "count": cat_total,
            "all_core_rate": round(sum(1 for r in cat_results if r["eval"].get("all_core_aligned")) / cat_total, 4),
            "table_exact_rate": round(sum(1 for r in cat_results if r["eval"].get("table_exact")) / cat_total, 4),
            "limit_rate": round(sum(1 for r in cat_results if r["eval"].get("limit_aligned")) / cat_total, 4),
            "metric_rate": round(sum(1 for r in cat_results if r["eval"].get("metric_aligned")) / cat_total, 4),
        }
    summary["category_breakdown"] = category_breakdown

    with open(out_dir / "plan_eval_raw.json", "w", encoding="utf-8") as f:
        json.dump(valid_results, f, indent=2, default=str)
    with open(out_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    if errors:
        with open(out_dir / "errors.json", "w", encoding="utf-8") as f:
            json.dump(errors, f, indent=2)

    print("\n" + "="*60)
    print("PHASE 9 PLAN-ONLY EVALUATION SUMMARY")
    print("="*60)
    print(f"Provider:                 {summary['provider']}")
    print(f"Total Queries:            {total}")
    print(f"Errors:                   {len(errors)}")
    print(f"Elapsed Time:             {elapsed:.1f}s")
    print("-"*60)
    print(f"All-Core Alignment:       {summary['all_core_alignment_rate']*100:.1f}% (Phase 8: ~16%)")
    print(f"Table Exact Match:        {summary['table_exact_rate']*100:.1f}% (Phase 8: ~29%)")
    print(f"Table Recall:             {summary['table_mean_recall']*100:.1f}%")
    print(f"Table Precision:          {summary['table_mean_precision']*100:.1f}%")
    print(f"Limit Alignment:          {summary['limit_alignment_rate']*100:.1f}% (Phase 8: ~67%)")
    print(f"Metric Alignment:         {summary['metric_alignment_rate']*100:.1f}% (Phase 8: ~66%)")
    print(f"Aggregation Alignment:    {summary['aggregation_alignment_rate']*100:.1f}%")
    print(f"Ranking Dir Alignment:    {summary['ranking_direction_alignment_rate']*100:.1f}%")
    print(f"Time Grain Alignment:     {summary['time_grain_alignment_rate']*100:.1f}%")
    print(f"Join Path Alignment:      {summary['join_path_alignment_rate']*100:.1f}%")
    print(f"Result Shape Alignment:   {summary['result_shape_alignment_rate']*100:.1f}%")
    print(f"Composite Alignment:      {summary['composite_alignment_rate']*100:.1f}%")
    print(f"Entity Alignment:         {summary['entity_alignment_rate']*100:.1f}%")
    print(f"Filter Alignment:         {summary['filter_alignment_rate']*100:.1f}%")
    print("-"*60)
    print("Category Breakdown:")
    for cat, stats in sorted(category_breakdown.items()):
        print(f"  {cat:30s} n={stats['count']:3d}  core={stats['all_core_rate']*100:.0f}%  table={stats['table_exact_rate']*100:.0f}%  limit={stats['limit_rate']*100:.0f}%  metric={stats['metric_rate']*100:.0f}%")
    print("="*60 + "\n")

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run fast plan-only evaluation.")
    parser.add_argument("--out", default=str(ROOT / "results" / "phase9" / "plan_eval"), help="Output directory")
    parser.add_argument("--concurrency", type=int, default=5, help="Number of concurrent planner calls")
    args = parser.parse_args()
    asyncio.run(run_plan_eval(Path(args.out), concurrency=args.concurrency))


if __name__ == "__main__":
    main()
