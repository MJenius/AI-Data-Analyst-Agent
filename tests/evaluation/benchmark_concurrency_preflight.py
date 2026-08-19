"""Benchmark NVIDIA NIM throughput at 1, 2, 4, and 8 workers on a 10-query preflight sample.

Measures:
- queries/minute
- mean/P50/P95 latency
- timeout rate
- 429 rate
- provider errors
- token usage
- successful SQL execution
- correctness (equivalent match rate)
- Estimated 500-query runtime
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
load_dotenv()

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from tests.evaluation.run_benchmark_phase10 import run_benchmark

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("preflight_concurrency")

DATASET_PATH = ROOT / "tests" / "evaluation" / "benchmark_dataset_500.json"
SAMPLE_SIZE = 10
WORKER_CONFIGS = [1, 2, 4, 8]
OUT_DIR_BASE = ROOT / "results" / "phase10" / "preflight_concurrency_tests"


async def test_concurrency_level(workers: int) -> dict[str, Any]:
    out_dir = OUT_DIR_BASE / f"workers_{workers}"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    os.environ["LLM_PROVIDER"] = "nvidia"
    logger.info("=== Running Concurrency Preflight Test: %d Workers (%d queries) ===", workers, SAMPLE_SIZE)

    started = time.perf_counter()
    summary = await run_benchmark(
        dataset_path=DATASET_PATH,
        output_dir=out_dir,
        workers=workers,
        limit=SAMPLE_SIZE,
        enable_evaluator=False,
        dry_run=False,
    )
    total_time = round(time.perf_counter() - started, 2)

    total_q = summary["total_queries"]
    qpm = round((total_q / total_time) * 60.0, 2) if total_time > 0 else 0.0

    # Estimate 500-query runtime
    est_500_seconds = round(500 * (total_time / total_q), 1)
    est_500_minutes = round(est_500_seconds / 60.0, 1)

    res = {
        "workers": workers,
        "sample_size": total_q,
        "total_elapsed_seconds": total_time,
        "queries_per_minute": qpm,
        "mean_latency_seconds": summary["mean_latency_seconds"],
        "p50_latency_seconds": summary["p50_latency_seconds"],
        "p95_latency_seconds": summary["p95_latency_seconds"],
        "timeout_count": summary["timeout_count"],
        "rate_limited_count": summary["rate_limited_count"],
        "provider_errors_count": summary["provider_errors_count"],
        "sql_execution_success_rate": summary["sql_execution_success_rate"],
        "equivalent_match_rate": summary["equivalent_match_rate"],
        "exact_match_rate": summary["exact_match_rate"],
        "estimated_500q_runtime_seconds": est_500_seconds,
        "estimated_500q_runtime_minutes": est_500_minutes,
        "output_dir": str(out_dir),
    }

    logger.info(
        "Workers %d: time=%.1fs, qpm=%.1f, mean_lat=%.1fs, 429s=%d, timeouts=%d, errors=%d, equiv=%.1f%%, est_500q=%.1f min",
        workers, total_time, qpm, summary["mean_latency_seconds"], summary["rate_limited_count"],
        summary["timeout_count"], summary["provider_errors_count"], summary["equivalent_match_rate"] * 100,
        est_500_minutes
    )
    return res


async def run_all_preflight_concurrency_tests():
    OUT_DIR_BASE.mkdir(parents=True, exist_ok=True)
    all_results = []

    for w in WORKER_CONFIGS:
        try:
            res = await test_concurrency_level(w)
            all_results.append(res)
            # Brief pause between test runs to avoid lingering rate limits
            await asyncio.sleep(2.0)
        except Exception as exc:
            logger.error("Concurrency test failed for %d workers: %s", w, exc)
            all_results.append({
                "workers": w,
                "error": str(exc),
                "status": "failed",
            })

    report_path = ROOT / "results" / "phase10" / "concurrency_preflight_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)

    print("\n" + "=" * 80)
    print(" NVIDIA NIM CONCURRENCY PREFLIGHT BENCHMARK REPORT")
    print("=" * 80)
    print(f"{'Workers':<8} | {'Elapsed':<8} | {'QPM':<8} | {'Mean Lat':<10} | {'P50 Lat':<10} | {'P95 Lat':<10} | {'429s':<6} | {'SQL%':<6} | {'Equiv%':<8} | {'Est 500q Time':<12}")
    print("-" * 80)
    for r in all_results:
        if "error" in r:
            print(f"{r['workers']:<8} | FAILED: {r['error']}")
        else:
            print(
                f"{r['workers']:<8} | "
                f"{r['total_elapsed_seconds']:<6.1f}s | "
                f"{r['queries_per_minute']:<8.1f} | "
                f"{r['mean_latency_seconds']:<8.1f}s | "
                f"{r['p50_latency_seconds']:<8.1f}s | "
                f"{r['p95_latency_seconds']:<8.1f}s | "
                f"{r['rate_limited_count']:<6} | "
                f"{r['sql_execution_success_rate']*100:<5.0f}% | "
                f"{r['equivalent_match_rate']*100:<7.1f}% | "
                f"{r['estimated_500q_runtime_minutes']:<6.1f} min ({r['estimated_500q_runtime_seconds']:.0f}s)"
            )
    print("=" * 80)

    # Determine recommended worker count
    valid_runs = [r for r in all_results if "error" not in r and r.get("rate_limited_count", 0) == 0 and r.get("provider_errors_count", 0) == 0]
    if valid_runs:
        best = max(valid_runs, key=lambda x: x["queries_per_minute"])
        print(f"\n RECOMMENDED CONFIGURATION: {best['workers']} Workers ({best['queries_per_minute']:.1f} QPM, ~{best['estimated_500q_runtime_minutes']:.1f} min for 500 queries)\n")
    else:
        fallback = max([r for r in all_results if "error" not in r], key=lambda x: x["queries_per_minute"])
        print(f"\n RECOMMENDED CONFIGURATION (best with retries): {fallback['workers']} Workers\n")


if __name__ == "__main__":
    asyncio.run(run_all_preflight_concurrency_tests())
