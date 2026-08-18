import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECKPOINT_PATH = ROOT / "results" / "phase10" / "live_500_benchmark_run" / "checkpoint.json"

def check():
    if not CHECKPOINT_PATH.exists():
        print("Checkpoint file not found.")
        return

    try:
        with open(CHECKPOINT_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error reading checkpoint: {e}")
        return

    entries = data.get("entries", {})
    completed = len(entries)
    total = data.get("total_queries", 500)
    hash_val = data.get("dataset_sha256", "unknown")

    if completed == 0:
        print("Completed: 0/500")
        return

    equiv_count = sum(1 for e in entries.values() if e.get("equivalent_match"))
    sql_count = sum(1 for e in entries.values() if e.get("sql_execution_success"))
    provider_errs = sum(1 for e in entries.values() if e.get("is_provider_error"))
    rate_limits = sum(1 for e in entries.values() if e.get("error_category") == "rate_limited")
    timeouts = sum(1 for e in entries.values() if e.get("error_category") == "timeout")
    latencies = [e.get("latency_seconds", 0.0) for e in entries.values()]
    mean_lat = sum(latencies) / len(latencies) if latencies else 0.0

    rem_queries = max(0, total - completed)
    est_rem_seconds = rem_queries * mean_lat
    est_rem_min = est_rem_seconds / 60.0
    est_rem_hours = est_rem_min / 60.0

    rem_str = f"{est_rem_min:.1f}m ({est_rem_hours:.1f}h)" if est_rem_min > 60 else f"{est_rem_min:.1f}m"

    correctness_pct = (equiv_count / completed) * 100
    sql_pct = (sql_count / completed) * 100

    # Determine health
    health = "GREEN"
    reason = "Benchmark progressing normally with zero fatal errors."
    if provider_errs > 5 or rate_limits > 10:
        health = "YELLOW"
        reason = f"Observed {provider_errs} provider errors / {rate_limits} rate limits."
    if sql_pct < 70.0:
        health = "YELLOW"
        reason = f"SQL execution rate is {sql_pct:.1f}%."

    print(f"Completed: {completed}/{total}")
    print(f"Dataset Hash: {hash_val[:16]}...")
    print(f"Correctness: {correctness_pct:.1f}%")
    print(f"SQL execution: {sql_pct:.1f}%")
    print(f"Provider errors/429s/timeouts: {provider_errs} errors ({rate_limits} 429s, {timeouts} timeouts)")
    print(f"Mean latency: {mean_lat:.1f}s")
    print(f"Estimated remaining time: {rem_str}")
    print(f"Health: {health}")
    print(f"Reason: {reason}")

if __name__ == "__main__":
    check()
