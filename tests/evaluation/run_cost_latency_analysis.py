"""CLI Runner for Latency, Token Cost, Repair Overhead & Pareto Frontier Profiling."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_platform.experiments.cost_latency import (
    ParetoPoint,
    RATE_CARDS,
    TokenCounter,
    analyze_repair_overhead,
    compute_latency_profile,
    compute_pareto_frontier,
    compute_tradeoff_gradients,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("run_cost_latency")


def main() -> None:
    parser = argparse.ArgumentParser(description="Cost, Latency, and Repair Overhead Profiling")
    parser.add_argument("--checkpoint", type=str, default=None, help="Path to checkpoint.json")
    parser.add_argument("--provider-model", type=str, default="nvidia/llama-3.1-nemotron-70b-instruct", help="Model rate card key")
    args = parser.parse_args()

    target_path = Path(args.checkpoint) if args.checkpoint else ROOT / "results" / "phase10" / "ablation" / "rag_planner_verifier" / "checkpoint.json"
    if not target_path.exists():
        logger.error("Checkpoint not found: %s", target_path)
        sys.exit(1)

    with open(target_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    entries = list(data["entries"].values()) if isinstance(data, dict) and "entries" in data else (data if isinstance(data, list) else [])
    latencies = [float(e.get("latency_seconds", 0.0)) for e in entries if e.get("latency_seconds") is not None]

    lat_profile = compute_latency_profile(latencies)
    rc = RATE_CARDS.get(args.provider_model, RATE_CARDS["nvidia/llama-3.1-nemotron-70b-instruct"])
    repair_rep = analyze_repair_overhead(entries, rate_card=rc)

    print("\n" + "=" * 80)
    print(f"LATENCY DISTRIBUTION PROFILE (N={lat_profile.count})")
    print("=" * 80)
    print(f"Mean Latency:    {lat_profile.mean:.2f}s (Std: {lat_profile.std:.2f}s)")
    print(f"Quantiles:       p10={lat_profile.p10:.2f}s | p25={lat_profile.p25:.2f}s | p50={lat_profile.p50:.2f}s | p75={lat_profile.p75:.2f}s | p90={lat_profile.p90:.2f}s | p95={lat_profile.p95:.2f}s | p99={lat_profile.p99:.2f}s")
    print(f"Spread & Shape:  IQR={lat_profile.iqr:.2f}s | Skewness={lat_profile.skewness:.3f} | Kurtosis={lat_profile.kurtosis:.3f}")
    print("=" * 80)

    print("\n" + "=" * 80)
    print("REPAIR OVERHEAD & RECOVERY ANALYSIS")
    print("=" * 80)
    print(f"Repair Trigger Rate:        {repair_rep.repair_trigger_percent} ({repair_rep.repaired_queries_count}/{repair_rep.total_queries} queries)")
    print(f"Repair Recovery Rate:       {repair_rep.repair_recovery_percent} ({repair_rep.rescued_queries_count} rescued into success)")
    print(f"Latency Penalty:            +{repair_rep.latency_overhead_seconds:.2f}s (Repaired: {repair_rep.repaired_mean_latency:.2f}s vs Unrepaired: {repair_rep.unrepaired_mean_latency:.2f}s)")
    print(f"Total Repair Tokens:        {repair_rep.total_tokens_spent_on_repair:,} tokens")
    print(f"Estimated Repair Cost:      ${repair_rep.estimated_repair_cost_usd:.4f} USD")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
