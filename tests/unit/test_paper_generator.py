"""Unit Tests for Automated Paper Generator and Publication Figures."""

from pathlib import Path
import pytest

from agent_platform.experiments.cost_latency import ParetoPoint
from agent_platform.experiments.paper_generator import (
    PaperArtifactCompiler,
    plot_domain_difficulty_heatmap,
    plot_pareto_frontier,
    plot_phase_progression,
    plot_pipeline_architecture,
    plot_robustness_degradation,
)
from agent_platform.experiments.stat_analysis import ConfidenceInterval, PhaseBenchmarkRecord, SubgroupMetric


def test_figure_plotting(tmp_path: Path):
    # Figure 1: Pipeline
    fig1_path = tmp_path / "fig1_test"
    plot_pipeline_architecture(fig1_path)
    assert (tmp_path / "fig1_test.png").exists()
    assert (tmp_path / "fig1_test.pdf").exists()
    assert (tmp_path / "fig1_test.svg").exists()

    # Figure 2: Phase Progression
    dummy_rec = PhaseBenchmarkRecord(
        phase_id="p10", label="Phase 10", total_queries=100, equivalent_matches=26,
        exact_matches=13, sql_execution_successes=65,
        equivalent_rate_ci=ConfidenceInterval(0.26, 0.18, 0.35, sample_size=100),
        exact_rate_ci=ConfidenceInterval(0.13, 0.08, 0.20, sample_size=100),
        sql_success_rate_ci=ConfidenceInterval(0.65, 0.55, 0.74, sample_size=100),
        table_precision=0.8, table_recall=0.9, mean_latency=200.0, p50_latency=150.0, p95_latency=280.0
    )
    fig2_path = tmp_path / "fig2_test"
    plot_phase_progression([dummy_rec], fig2_path)
    assert (tmp_path / "fig2_test.png").exists()

    # Figure 3: Pareto Frontier
    pareto_pts = [
        ParetoPoint("A", 0.19, 150.0, 150.0, 1.4, is_pareto_optimal=True),
        ParetoPoint("B", 0.26, 200.0, 200.0, 2.1, is_pareto_optimal=True),
    ]
    fig3_path = tmp_path / "fig3_test"
    plot_pareto_frontier(pareto_pts, fig3_path)
    assert (tmp_path / "fig3_test.png").exists()

    # Figure 5: Domain Heatmap
    dummy_sub = {
        "Sales": SubgroupMetric("Sales", 20, 8, ConfidenceInterval(0.4, 0.2, 0.6), 150.0, 200.0, 0.8, 0.9, 0.95),
        "Customers": SubgroupMetric("Customers", 20, 4, ConfidenceInterval(0.2, 0.1, 0.4), 120.0, 180.0, 0.9, 0.85, 0.9),
    }
    fig5_path = tmp_path / "fig5_test"
    plot_domain_difficulty_heatmap(dummy_sub, fig5_path)
    assert (tmp_path / "fig5_test.png").exists()


def test_paper_artifact_compiler(tmp_path: Path):
    compiler = PaperArtifactCompiler(output_dir=tmp_path)
    workspace_root = Path(__file__).resolve().parents[2]
    res = compiler.compile_all(workspace_root=workspace_root)
    assert res["status"] == "success"
    assert (tmp_path / "macros.tex").exists()
    assert (tmp_path / "tables" / "tab_phase_progression.tex").exists()
    assert (tmp_path / "figures" / "fig1_pipeline_architecture.png").exists()
