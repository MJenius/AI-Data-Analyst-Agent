"""CLI Runner for Automated Failure Taxonomy and Root-Cause Classification."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_platform.experiments.failure_taxonomy import (
    FailureClassifier,
    format_taxonomy_markdown_report,
    generate_taxonomy_summary,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("run_error_analysis")


def main() -> None:
    parser = argparse.ArgumentParser(description="Automated Failure Taxonomy & Diagnostic Analysis")
    parser.add_argument("--checkpoint", type=str, default=None, help="Path to checkpoint.json")
    parser.add_argument("--output-report", type=str, default=None, help="Path to save markdown failure report")
    args = parser.parse_args()

    target_path = Path(args.checkpoint) if args.checkpoint else ROOT / "results" / "phase10" / "ablation" / "rag_planner_verifier" / "checkpoint.json"
    if not target_path.exists():
        logger.error("Checkpoint not found: %s", target_path)
        sys.exit(1)

    with open(target_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    entries = list(data["entries"].values()) if isinstance(data, dict) and "entries" in data else (data if isinstance(data, list) else [])

    classifier = FailureClassifier()
    diagnostics = [classifier.classify(e) for e in entries]
    summary = generate_taxonomy_summary(diagnostics)

    report_md = format_taxonomy_markdown_report(summary)
    print("\n" + report_md + "\n")

    if args.output_report:
        out_p = Path(args.output_report)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with open(out_p, "w", encoding="utf-8") as f:
            f.write(f"# Automated Failure Taxonomy Report\n\n**Source:** `{target_path}`\n\n")
            f.write(report_md + "\n")
        logger.info("Saved failure taxonomy report to %s", out_p)


if __name__ == "__main__":
    main()
