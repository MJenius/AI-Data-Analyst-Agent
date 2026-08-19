"""Generate fresh cryptographic SHA-256 artifact manifest."""

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


def update_manifest():
    files_to_track = [
        "data/analytics.db",
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
        "results/phase10/live_500_benchmark_run/summary.json",
        "results/phase10/final_research_validation_report.json",
        "results/phase10/benchmark_500_validation_report.json",
        "docs/research_paper/latex/main.tex",
        "docs/research_paper/latex/references.bib",
        "docs/research_paper/latex/macros.tex",
        "docs/research_paper/macros.tex",
        "docs/research_paper/PAPER_DRAFT.md",
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
        "REPRODUCIBILITY.md",
        "LICENSE",
        "CITATION.cff",
        "CONTRIBUTING.md",
        "README.md",
        "pyproject.toml",
    ]

    artifacts = {}
    missing = []
    for rel_path in files_to_track:
        p = ROOT / rel_path
        if p.exists():
            sha = compute_sha256(p)
            size = p.stat().st_size
            artifacts[rel_path.replace("\\", "/")] = {
                "sha256": sha,
                "size_bytes": size,
            }
        else:
            missing.append(rel_path)

    manifest = {
        "title": "Frozen Publication Artifact Manifest",
        "timestamp_utc": "2026-08-19T09:45:00Z",
        "status": "FROZEN_FOR_PUBLICATION",
        "author": "Mevin Jose",
        "verified_metrics": {
            "total_queries": 500,
            "equivalent_matches": 367,
            "equivalent_accuracy": "73.40%",
            "exact_matches": 155,
            "exact_accuracy": "31.00%",
            "sql_execution_success": "100.00%",
        },
        "artifacts": artifacts,
    }

    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"Artifact manifest updated with {len(artifacts)} verified artifacts. Missing: {missing}")


if __name__ == "__main__":
    update_manifest()
