"""Spider Benchmark Cross-Database Evaluation Harness.

Evaluates zero-shot cross-schema generalization of the multi-stage reliability
pipeline across the official Spider development set SQLite databases.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
load_dotenv()

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_platform.analytics.service import AnalyticsAgentService
from agent_platform.experiments.compare_results import compare_results
from agent_platform.llms.client import get_llm_client

logger = logging.getLogger(__name__)

def execute_sql_in_db(sql: str, db_path: Path) -> dict[str, Any]:
    if not sql or not sql.strip():
        return {"success": False, "error": "empty sql", "rows": [], "row_count": 0}
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(sql)
        cols = [d[0] for d in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
        values = [{c: (round(v, 4) if isinstance(v, float) else v) for c, v in zip(cols, row)} for row in rows]
        return {"success": True, "rows": values, "row_count": len(values), "columns": cols}
    except Exception as exc:
        return {"success": False, "error": str(exc), "rows": [], "row_count": 0}
    finally:
        conn.close()


SPIDER_DIR = ROOT / "data" / "spider"
SPIDER_DEV_FILE = SPIDER_DIR / "validation.json"
SPIDER_DB_DIR = SPIDER_DIR / "database"
RESULTS_DIR = ROOT / "results" / "spider"


def load_spider_dataset(sample_size: int | None = None, seed: int = 42) -> list[dict[str, Any]]:
    if not SPIDER_DEV_FILE.exists():
        raise FileNotFoundError(f"Spider validation file not found at {SPIDER_DEV_FILE}")
    with open(SPIDER_DEV_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    if sample_size is None or sample_size >= len(data):
        return data

    db_groups = defaultdict(list)
    for item in data:
        db_groups[item["db_id"]].append(item)

    selected = []
    import random
    rng = random.Random(seed)
    
    sorted_dbs = sorted(db_groups.keys())
    for db in sorted_dbs:
        items = db_groups[db]
        rng.shuffle(items)
    
    idx = 0
    while len(selected) < sample_size:
        added_in_round = 0
        for db in sorted_dbs:
            if len(selected) >= sample_size:
                break
            if idx < len(db_groups[db]):
                selected.append(db_groups[db][idx])
                added_in_round += 1
        if added_in_round == 0:
            break
        idx += 1

    return selected


async def run_spider_item(
    idx: int,
    item: dict[str, Any],
    service_cache: dict[str, AnalyticsAgentService],
    output_dir: Path,
) -> dict[str, Any]:
    db_id = item["db_id"]
    question = item["question"]
    gold_sql = item["query"]
    db_path = SPIDER_DB_DIR / db_id / f"{db_id}.sqlite"

    if not db_path.exists():
        return {
            "idx": idx,
            "db_id": db_id,
            "question": question,
            "gold_sql": gold_sql,
            "generated_sql": None,
            "execution_success": False,
            "equivalent_match": False,
            "exact_match": False,
            "error": f"Database file not found: {db_path}",
            "latency_seconds": 0.0,
        }

    if db_id not in service_cache:
        service_cache[db_id] = AnalyticsAgentService.from_sqlite(db_path, enable_evaluator=False)
    service = service_cache[db_id]

    start_time = time.perf_counter()
    gold_res = execute_sql_in_db(gold_sql, db_path)
    
    try:
        res = await service.analyze(question)
        elapsed = round(time.perf_counter() - start_time, 2)
        sql_queries = res.get("sql_queries", [])
        gen_sql = sql_queries[-1] if sql_queries else None
        
        if gen_sql:
            actual_res = execute_sql_in_db(gen_sql, db_path)
            exec_ok = actual_res["success"]
            cmp_res = compare_results(actual_res.get("rows", []), gold_res.get("rows", []))
            equiv_match = cmp_res["equivalent_match"]
            exact_match = cmp_res["exact_match"]
            err_msg = actual_res.get("error")
        else:
            exec_ok = False
            equiv_match = False
            exact_match = False
            err_msg = "No SQL generated"

        return {
            "idx": idx,
            "db_id": db_id,
            "question": question,
            "gold_sql": gold_sql,
            "generated_sql": gen_sql,
            "execution_success": exec_ok,
            "equivalent_match": equiv_match,
            "exact_match": exact_match,
            "error": err_msg,
            "latency_seconds": elapsed,
        }
    except Exception as exc:
        elapsed = round(time.perf_counter() - start_time, 2)
        return {
            "idx": idx,
            "db_id": db_id,
            "question": question,
            "gold_sql": gold_sql,
            "generated_sql": None,
            "execution_success": False,
            "equivalent_match": False,
            "exact_match": False,
            "error": str(exc),
            "latency_seconds": elapsed,
        }


async def main():
    parser = argparse.ArgumentParser(description="Run Spider cross-database evaluation")
    parser.add_argument("--sample-size", type=int, default=50, help="Number of queries (default: 50 stratified)")
    parser.add_argument("--concurrency", type=int, default=3, help="Concurrency limit")
    parser.add_argument("--output-dir", type=str, default=str(RESULTS_DIR), help="Results output directory")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    dataset = load_spider_dataset(sample_size=args.sample_size)
    num_dbs = len(set(x["db_id"] for x in dataset))
    logger.info(f"Loaded {len(dataset)} Spider queries across {num_dbs} databases.")

    service_cache: dict[str, AnalyticsAgentService] = {}
    sem = asyncio.Semaphore(args.concurrency)

    checkpoint_file = out_dir / "checkpoint.json"
    completed_records: list[dict[str, Any]] = []
    if checkpoint_file.exists():
        with open(checkpoint_file, "r", encoding="utf-8") as f:
            completed_records = json.load(f)
        logger.info(f"Loaded {len(completed_records)} existing records from checkpoint.")

    completed_indices = {r["idx"] for r in completed_records}

    async def worker(i: int, item: dict[str, Any]):
        if i in completed_indices:
            return
        async with sem:
            db_id = item["db_id"]
            q_text = item["question"][:60]
            logger.info(f"[{i+1}/{len(dataset)}] Running Spider query on db '{db_id}': {q_text}...")
            rec = await run_spider_item(i, item, service_cache, out_dir)
            completed_records.append(rec)
            with open(checkpoint_file, "w", encoding="utf-8") as f:
                json.dump(completed_records, f, indent=2)
            status_str = "EQUIV_MATCH" if rec["equivalent_match"] else ("EXEC_OK" if rec["execution_success"] else "FAILED")
            logger.info(f"[{i+1}/{len(dataset)}] DB: {rec['db_id']} -> {status_str} in {rec['latency_seconds']}s")

    tasks = [worker(i, item) for i, item in enumerate(dataset)]
    await asyncio.gather(*tasks)

    n_total = len(completed_records)
    n_equiv = sum(1 for r in completed_records if r["equivalent_match"])
    n_exact = sum(1 for r in completed_records if r["exact_match"])
    n_exec = sum(1 for r in completed_records if r["execution_success"])
    latencies = [r["latency_seconds"] for r in completed_records]

    per_db = defaultdict(lambda: {"total": 0, "equiv": 0, "exec": 0})
    for r in completed_records:
        db = r["db_id"]
        per_db[db]["total"] += 1
        if r["equivalent_match"]:
            per_db[db]["equiv"] += 1
        if r["execution_success"]:
            per_db[db]["exec"] += 1

    summary = {
        "benchmark": "Spider (Yale Text-to-SQL)",
        "split": "validation_stratified_subset" if args.sample_size < 1034 else "validation_full",
        "sample_size": n_total,
        "unique_databases": len(per_db),
        "equivalent_matches": n_equiv,
        "equivalent_rate": round(n_equiv / n_total, 4) if n_total > 0 else 0.0,
        "exact_matches": n_exact,
        "exact_rate": round(n_exact / n_total, 4) if n_total > 0 else 0.0,
        "execution_successes": n_exec,
        "execution_success_rate": round(n_exec / n_total, 4) if n_total > 0 else 0.0,
        "mean_latency_seconds": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
        "per_database_breakdown": dict(per_db),
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    summary_file = out_dir / "summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    equiv_pct = summary["equivalent_rate"] * 100
    exec_pct = summary["execution_success_rate"] * 100
    logger.info("=" * 70)
    logger.info(f"SPIDER EVALUATION COMPLETE: {n_equiv}/{n_total} ({equiv_pct:.1f}%) Equivalent Match, {exec_pct:.1f}% Exec")
    logger.info(f"Summary saved to {summary_file}")
    logger.info("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
