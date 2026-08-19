"""CLI Runner for Cryptographic Reproducibility Manifest Creation and Audit Verification."""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_platform.experiments.reproducibility import (
    DatabaseMetadata,
    DatasetMetadata,
    EnvironmentSnapshot,
    ExperimentManifest,
    ModelConfigManifest,
    verify_manifest_integrity,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("run_reproducibility_audit")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or Verify Reproducibility Manifest")
    parser.add_argument("--action", choices=["create", "verify"], default="create", help="Action to perform")
    parser.add_argument("--dataset", type=str, default=None, help="Dataset path")
    parser.add_argument("--database", type=str, default=None, help="Database path")
    parser.add_argument("--manifest", type=str, default=None, help="Manifest output / input path")
    args = parser.parse_args()

    ds_path = Path(args.dataset) if args.dataset else ROOT / "tests" / "evaluation" / "benchmark_dataset_500.json"
    db_path = Path(args.database) if args.database else ROOT / "data" / "analytics.db"
    manifest_path = Path(args.manifest) if args.manifest else ROOT / "results" / "phase10" / "experiment_manifest.json"

    if args.action == "create":
        logger.info("Creating reproducibility manifest...")
        ds_meta = DatasetMetadata.from_file(ds_path)
        db_meta = DatabaseMetadata.from_file(db_path)
        env_snap = EnvironmentSnapshot.capture(repo_root=ROOT)
        model_cfg = ModelConfigManifest(
            model_name="nvidia/llama-3.1-nemotron-70b-instruct",
            provider="nvidia_nim",
            temperature=0.0,
            concurrency_workers=4,
        )

        manifest = ExperimentManifest(
            experiment_id="phase10_500_benchmark_experiment",
            timestamp_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            title="Phase 10: 500-Query Benchmark Reproducibility Manifest",
            description="Cryptographically sealed configuration and environment manifest for the 500-query benchmark.",
            dataset=ds_meta,
            database=db_meta,
            model_config=model_cfg,
            environment=env_snap,
        )

        manifest.save(manifest_path)
        print(f"\nManifest created successfully: {manifest_path}")
        print(f"Dataset SHA-256:  {ds_meta.sha256}")
        print(f"Database SHA-256: {db_meta.sha256}")
        print(f"Git Commit SHA:   {env_snap.git_commit_sha}\n")

    elif args.action == "verify":
        if not manifest_path.exists():
            logger.error("Manifest not found: %s", manifest_path)
            sys.exit(1)

        result = verify_manifest_integrity(manifest_path, expected_dataset_path=ds_path, expected_db_path=db_path)
        print("\n" + "=" * 80)
        print("REPRODUCIBILITY AUDIT VERIFICATION")
        print("=" * 80)
        print(f"Overall Valid:    {'✅ PASSED' if result.is_valid else '❌ FAILED'}")
        print(f"Dataset Match:    {'✅ MATCHED' if result.dataset_match else '❌ MISMATCH'}")
        print(f"Database Match:   {'✅ MATCHED' if result.database_match else '❌ MISMATCH'}")
        print(f"Git Clean:        {'✅ CLEAN' if result.git_clean else '⚠️ UNCOMMITTED CHANGES'}")
        if result.discrepancies:
            print("Discrepancies:")
            for d in result.discrepancies:
                print(f"  - {d}")
        print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
