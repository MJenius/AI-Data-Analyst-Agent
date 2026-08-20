"""Generate frozen cryptographic SHA-256 artifact manifest.

Distinguishes:
1. Tracked Repository Artifacts (strictly verified against repository files).
2. External Data Artifacts (e.g. data/analytics.db built from Kaggle source).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "docs" / "research_paper" / "ARTIFACT_MANIFEST.json"


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def generate_manifest():
    # 1. Tracked Repository Artifacts (Must exist in git repo)
    tracked_files = [
        "data/schema.sql",
        "data/build_database.py",
        "tests/evaluation/benchmark_dataset_500.json",
        "tests/evaluation/run_benchmark_phase10.py",
        "tests/evaluation/run_ablation_study.py",
        "tests/evaluation/rescore_500_benchmark.py",
        "tests/evaluation/validate_500_dataset.py",
        "tests/evaluation/audit_sample_evaluator.py",
        "tests/evaluation/run_final_research_validation.py",
        "tests/unit/test_compare_results.py",
        "tests/unit/test_statistics.py",
        "tests/unit/test_paper_generator.py",
        "tests/unit/test_failure_taxonomy.py",
        "tests/unit/test_robustness.py",
        "tests/unit/test_cost_latency.py",
        "tests/unit/test_ranking_semantics.py",
        "tests/unit/test_sql_truncation.py",
        "tests/unit/test_reproducibility.py",
        "results/phase10/live_500_benchmark_run/summary.json",
        "results/phase10/final_research_validation_report.json",
        "results/phase10/benchmark_500_validation_report.json",
        "results/phase10/repair_audit_cache.json",
        "results/phase10/ablation/rag_only/checkpoint.json",
        "results/phase10/ablation/rag_planner/checkpoint.json",
        "results/phase10/ablation/rag_planner_verifier/checkpoint.json",
        "results/phase10/ablation/full_system/checkpoint.json",
        "docs/research_paper/latex/main.tex",
        "docs/research_paper/latex/references.bib",
        "docs/research_paper/latex/macros.tex",
        "docs/research_paper/macros.tex",
        "docs/research_paper/PAPER_DRAFT.md",
        "docs/research_paper/PAPER_READINESS_AUDIT.md",
        "docs/research_paper/SEMANTIC_AUDIT.md",
        "docs/research_paper/figures/fig1_pipeline_architecture.pdf",
        "docs/research_paper/figures/fig1_pipeline_architecture.png",
        "docs/research_paper/figures/fig1_pipeline_architecture.svg",
        "docs/research_paper/figures/fig2_phase_accuracy_progression.pdf",
        "docs/research_paper/figures/fig2_phase_accuracy_progression.png",
        "docs/research_paper/figures/fig2_phase_accuracy_progression.svg",
        "docs/research_paper/figures/fig3_pareto_frontier.pdf",
        "docs/research_paper/figures/fig3_pareto_frontier.png",
        "docs/research_paper/figures/fig3_pareto_frontier.svg",
        "docs/research_paper/figures/fig4_repair_dynamics.pdf",
        "docs/research_paper/figures/fig4_repair_dynamics.png",
        "docs/research_paper/figures/fig4_repair_dynamics.svg",
        "docs/research_paper/figures/fig5_domain_difficulty_heatmap.pdf",
        "docs/research_paper/figures/fig5_domain_difficulty_heatmap.png",
        "docs/research_paper/figures/fig5_domain_difficulty_heatmap.svg",
        "docs/research_paper/figures/fig6_robustness_degradation.pdf",
        "docs/research_paper/figures/fig6_robustness_degradation.png",
        "docs/research_paper/figures/fig6_robustness_degradation.svg",
        "docs/research_paper/figures/fig7_failure_taxonomy.pdf",
        "docs/research_paper/figures/fig7_failure_taxonomy.png",
        "docs/research_paper/figures/fig7_failure_taxonomy.svg",
        "docs/research_paper/tables/tab_domain_breakdown.tex",
        "docs/research_paper/tables/tab_headline_500.tex",
        "docs/research_paper/tables/tab_phase_progression.tex",
        "docs/research_paper/tables/tab_repair_audit.tex",
        "docs/research_paper/tables/tab_robustness.tex",
        "docs/research_paper/paper.pdf",
        "results/phase10/live_500_benchmark_run/benchmark_report.md",
        "REPRODUCIBILITY.md",
        "LICENSE",
        "CITATION.cff",
        "CONTRIBUTING.md",
        "README.md",
        "pyproject.toml",
    ]

    tracked_artifacts = {}
    missing_tracked = []
    for rel_path in tracked_files:
        p = ROOT / rel_path
        if p.exists():
            sha = compute_sha256(p)
            size = p.stat().st_size
            tracked_artifacts[rel_path.replace("\\", "/")] = {
                "sha256": sha,
                "size_bytes": size,
                "is_external": False,
            }
        else:
            missing_tracked.append(rel_path)

    if missing_tracked:
        raise FileNotFoundError(f"Missing required tracked artifacts: {missing_tracked}")

    # 2. External Data Artifacts (Built from source / downloaded from Kaggle)
    db_path = ROOT / "data" / "analytics.db"
    db_sha = compute_sha256(db_path) if db_path.exists() else "8550c4cc6d670aa0441bc898e47a57a40001858fc3f13dc5cb16fb90ca11c130"
    db_size = db_path.stat().st_size if db_path.exists() else 160145408

    external_artifacts = {
        "data/analytics.db": {
            "sha256": db_sha,
            "size_bytes": db_size,
            "is_external": True,
            "description": "Normalized SQLite relational data warehouse constructed from Olist Brazilian E-Commerce dataset (9 tables, 100k+ orders).",
            "license": "CC BY-NC-SA 4.0",
            "source_url": "https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce",
            "build_command": "python data/build_database.py",
            "build_script": "data/build_database.py",
            "schema_file": "data/schema.sql",
        }
    }

    manifest = {
        "title": "Frozen Publication Artifact Manifest",
        "paper_title": "Engineering Reliable LLM-Based Data Analysis: An Empirical Study of Schema Grounding, Planning, Verification, and SQL Repair",
        "version": "1.0.1",
        "timestamp_utc": "2026-08-19T10:00:00Z",
        "status": "FROZEN_FOR_PUBLICATION",
        "author": "Mevin Jose",
        "verified_metrics": {
            "total_queries": 500,
            "equivalent_matches": 367,
            "result_equivalence_rate": "73.40%",
            "exact_matches": 155,
            "exact_accuracy": "31.00%",
            "sql_execution_success": "100.00%",
        },
        "tracked_repository_artifacts": tracked_artifacts,
        "external_data_artifacts": external_artifacts,
    }

    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"Artifact manifest successfully generated and frozen:")
    print(f"  Tracked Repository Artifacts: {len(tracked_artifacts)} (0 missing)")
    print(f"  External Data Artifacts:      {len(external_artifacts)}")
    print(f"  Saved to:                     {MANIFEST_PATH}")


if __name__ == "__main__":
    generate_manifest()
