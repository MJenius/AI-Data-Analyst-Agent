"""CLI Runner for Benchmark Statistical Analysis & Multi-Phase Comparisons."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_platform.experiments.stat_analysis import (
    BenchmarkStatisticalAnalyzer,
    analyze_stratified_subgroups,
    format_markdown_phase_table,
    format_subgroup_markdown_table,
    wilson_score_interval,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("run_statistical_analysis")


def main() -> None:
    parser = argparse.ArgumentParser(description="Statistical Analysis & Longitudinal Phase Comparison")
    parser.add_argument("--checkpoint", type=str, default=None, help="Path to checkpoint.json to analyze")
    parser.add_argument("--output-report", type=str, default=None, help="Path to output Markdown report")
    parser.add_argument("--confidence", type=float, default=0.95, help="Confidence level (default 0.95)")
    args = parser.parse_args()

    analyzer = BenchmarkStatisticalAnalyzer(confidence=args.confidence)
    target_path = Path(args.checkpoint) if args.checkpoint else ROOT / "results" / "phase10" / "ablation" / "rag_planner_verifier" / "checkpoint.json"

    if not target_path.exists():
        logger.error("Target checkpoint file not found: %s", target_path)
        sys.exit(1)

    record = analyzer.load_checkpoint(target_path, "target_run", target_path.parent.name)
    logger.info("Loaded run: %s (%d queries)", record.label, record.total_queries)

    print("\n" + "=" * 80)
    print(f"STATISTICAL SUMMARY: {record.label} (N={record.total_queries})")
    print("=" * 80)
    print(f"Equivalent Match Rate:  {record.equivalent_rate_ci.estimate*100:.2f}% (95% CI: [{record.equivalent_rate_ci.ci_lower*100:.2f}%, {record.equivalent_rate_ci.ci_upper*100:.2f}%])")
    print(f"Exact Match Rate:       {record.exact_rate_ci.estimate*100:.2f}% (95% CI: [{record.exact_rate_ci.ci_lower*100:.2f}%, {record.exact_rate_ci.ci_upper*100:.2f}%])")
    print(f"SQL Exec Success Rate:  {record.sql_success_rate_ci.estimate*100:.2f}% (95% CI: [{record.sql_success_rate_ci.ci_lower*100:.2f}%, {record.sql_success_rate_ci.ci_upper*100:.2f}%])")
    print(f"Table Recall:           {record.table_recall*100:.2f}%")
    print(f"Table Precision:        {record.table_precision*100:.2f}%")
    print(f"Latency Profile:        Mean={record.mean_latency:.2f}s | p50={record.p50_latency:.2f}s | p95={record.p95_latency:.2f}s")
    print("=" * 80 + "\n")

    if record.raw_entries:
        subgroups = analyze_stratified_subgroups(record.raw_entries, group_by_key="category", confidence=args.confidence)
        subgroup_md = format_subgroup_markdown_table(subgroups, title=f"Domain Breakdown: {record.label}")
        print(subgroup_md)

        if args.output_report:
            out_p = Path(args.output_report)
            out_p.parent.mkdir(parents=True, exist_ok=True)
            with open(out_p, "w", encoding="utf-8") as f:
                f.write(f"# Statistical Analysis Report: {record.label}\n\n")
                f.write(format_markdown_phase_table([record]))
                f.write("\n\n" + subgroup_md + "\n")
            logger.info("Saved report to %s", out_p)


if __name__ == "__main__":
    main()
