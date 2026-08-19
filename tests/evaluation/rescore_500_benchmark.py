"""Deterministic Re-scorer for 500-Query Benchmark Results.

Re-evaluates every actual_sql against data/analytics.db and compares against
expected results using the corrected compare_results module.

Usage:
    python tests/evaluation/rescore_500_benchmark.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_platform.experiments.compare_results import compare_results

DB_PATH = ROOT / "data" / "analytics.db"
SUMMARY_PATH = ROOT / "results" / "phase10" / "live_500_benchmark_run" / "summary.json"
DATASET_PATH = ROOT / "tests" / "evaluation" / "benchmark_dataset_500.json"
OUTPUT_PATH = ROOT / "results" / "phase10" / "live_500_benchmark_run" / "summary_rescored.json"


def main():
    start_time = time.perf_counter()
    print("Loading benchmark datasets...", flush=True)
    with open(SUMMARY_PATH, "r", encoding="utf-8") as f:
        summary = json.load(f)

    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    dataset_by_id = {item.get("id", f"q_{i+1:03d}"): item for i, item in enumerate(dataset)}
    records = summary["results"]
    total = len(records)
    print(f"Loaded {total} records. Connecting to SQLite...", flush=True)

    conn = sqlite3.connect(str(DB_PATH))
    rescored_results = []
    upgraded, downgraded, unchanged = 0, 0, 0

    for i, record in enumerate(records):
        qid = record["query_id"]
        actual_sql = record.get("actual_sql")
        old_equiv = record.get("equivalent_match", False)

        bench_item = dataset_by_id.get(qid, {})
        expected_obj = bench_item.get("expected_result", {})
        expected_rows = expected_obj.get("values", []) if isinstance(expected_obj, dict) else (
            expected_obj if isinstance(expected_obj, list) else []
        )

        actual_rows = []
        if actual_sql and record.get("sql_execution_success"):
            try:
                cur = conn.execute(actual_sql)
                cols = [d[0] for d in cur.description] if cur.description else []
                actual_rows = [{c: (round(v, 4) if isinstance(v, float) else v) for c, v in zip(cols, row)} for row in cur.fetchall()]
            except Exception:
                actual_rows = []

        comp = compare_results(actual_rows, expected_rows)
        new_equiv = comp["equivalent_match"]

        if new_equiv != old_equiv:
            if new_equiv:
                upgraded += 1
            else:
                downgraded += 1
        else:
            unchanged += 1

        updated = dict(record)
        updated["equivalent_match"] = comp["equivalent_match"]
        updated["exact_match"] = comp["exact_match"]
        updated["row_count_match"] = comp["row_count_match"]
        updated["rescore_note"] = "rescored_with_corrected_multiset_comparison"
        rescored_results.append(updated)

        if (i + 1) % 50 == 0 or (i + 1) == total:
            print(f"Processed {i+1}/{total} queries... (Upgraded: {upgraded}, Downgraded: {downgraded})", flush=True)

    conn.close()

    new_equiv_count = sum(1 for r in rescored_results if r["equivalent_match"])
    new_exact_count = sum(1 for r in rescored_results if r["exact_match"])
    sql_success = sum(1 for r in rescored_results if r.get("sql_execution_success", False))

    rescored_summary = dict(summary)
    rescored_summary["results"] = rescored_results
    rescored_summary["equivalent_match_count"] = new_equiv_count
    rescored_summary["equivalent_match_rate"] = round(new_equiv_count / total, 4) if total else 0.0
    rescored_summary["exact_match_count"] = new_exact_count
    rescored_summary["exact_match_rate"] = round(new_exact_count / total, 4) if total else 0.0
    rescored_summary["sql_execution_success_count"] = sql_success
    rescored_summary["sql_execution_success_rate"] = round(sql_success / total, 4) if total else 0.0
    rescored_summary["rescore_note"] = "Rescored with corrected row-multiset compare_results"

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(rescored_summary, f, indent=2)

    with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
        json.dump(rescored_summary, f, indent=2)

    elapsed = round(time.perf_counter() - start_time, 2)
    print("\n" + "=" * 60, flush=True)
    print(f"RESCORE COMPLETE IN {elapsed}s", flush=True)
    print(f"  Total queries:       {total}", flush=True)
    print(f"  Equivalent Match:    {new_equiv_count}/{total} ({rescored_summary['equivalent_match_rate']*100:.2f}%)", flush=True)
    print(f"  Exact Match:         {new_exact_count}/{total} ({rescored_summary['exact_match_rate']*100:.2f}%)", flush=True)
    print(f"  SQL Success:         {sql_success}/{total}", flush=True)
    print(f"  Upgraded (F -> T):   {upgraded}", flush=True)
    print(f"  Downgraded (T -> F): {downgraded}", flush=True)
    print(f"  Unchanged:           {unchanged}", flush=True)
    print(f"  Saved to:            {SUMMARY_PATH}", flush=True)
    print("=" * 60, flush=True)


if __name__ == "__main__":
    main()
