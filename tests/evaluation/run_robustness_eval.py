"""CLI Runner for Robustness & OOD Perturbation Suite Generation and Evaluation."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_platform.experiments.robustness import (
    RobustnessSuiteBuilder,
    evaluate_robustness_drop,
    format_robustness_markdown_table,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("run_robustness_eval")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate OOD Perturbation Suite and Evaluate Robustness")
    parser.add_argument("--source-dataset", type=str, default=None, help="Path to clean benchmark dataset")
    parser.add_argument("--output-dataset", type=str, default=None, help="Path to save generated OOD dataset")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed")
    args = parser.parse_args()

    clean_path = Path(args.source_dataset) if args.source_dataset else ROOT / "tests" / "evaluation" / "benchmark_dataset_v2.json"
    if not clean_path.exists():
        logger.error("Dataset not found: %s", clean_path)
        sys.exit(1)

    with open(clean_path, "r", encoding="utf-8") as f:
        clean_data = json.load(f)

    builder = RobustnessSuiteBuilder(seed=args.seed)
    ood_data = builder.generate_suite(clean_data)

    out_path = Path(args.output_dataset) if args.output_dataset else ROOT / "results" / "phase10" / "ood_robustness_dataset.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(ood_data, f, indent=2)

    logger.info("Saved %d perturbed OOD queries to %s", len(ood_data), out_path)
    print(f"\nGenerated {len(ood_data)} Out-of-Distribution queries across 5 perturbation vectors.")
    print(f"File saved to: {out_path}\n")


if __name__ == "__main__":
    main()
