"""Unit Tests for Statistical Analysis Engine."""

import math
import numpy as np
import pytest

from agent_platform.experiments.statistics import (
    BenchmarkStatisticalAnalyzer,
    ConfidenceInterval,
    SubgroupMetric,
    analyze_stratified_subgroups,
    bootstrap_ci,
    clopper_pearson_interval,
    format_latex_phase_table,
    format_markdown_phase_table,
    format_subgroup_markdown_table,
    mcnemar_test,
    wilcoxon_signed_rank_test,
    wilson_score_interval,
)


def test_wilson_score_interval_bounds():
    # Normal case: 26 successes out of 100
    ci = wilson_score_interval(26, 100, confidence=0.95)
    assert ci.estimate == 0.26
    assert 0.17 < ci.ci_lower < 0.20
    assert 0.33 < ci.ci_upper < 0.37
    assert ci.sample_size == 100
    assert ci.successes == 26

    # Boundary: 0 successes
    ci_zero = wilson_score_interval(0, 50, confidence=0.95)
    assert ci_zero.estimate == 0.0
    assert ci_zero.ci_lower == 0.0
    assert 0.0 < ci_zero.ci_upper < 0.10

    # Boundary: 100% successes
    ci_full = wilson_score_interval(50, 50, confidence=0.95)
    assert ci_full.estimate == 1.0
    assert ci_full.ci_upper == 1.0
    assert 0.90 < ci_full.ci_lower < 1.0


def test_clopper_pearson_interval():
    ci = clopper_pearson_interval(26, 100, confidence=0.95)
    assert ci.estimate == 0.26
    assert 0.17 < ci.ci_lower < 0.20
    assert 0.34 < ci.ci_upper < 0.38
    assert ci.method == "clopper_pearson"


def test_bootstrap_ci():
    data = [10.0, 12.0, 15.0, 14.0, 18.0, 20.0, 22.0, 19.0, 25.0, 30.0]
    ci_bca = bootstrap_ci(data, statistic_fn=np.mean, confidence=0.95, n_resamples=1000, seed=42, method="bca")
    assert 15.0 < ci_bca.estimate < 22.0
    assert ci_bca.ci_lower < ci_bca.estimate < ci_bca.ci_upper

    ci_perc = bootstrap_ci(data, statistic_fn=np.mean, confidence=0.95, n_resamples=1000, seed=42, method="percentile")
    assert ci_perc.ci_lower < ci_perc.estimate < ci_perc.ci_upper


def test_mcnemar_test_exact_and_corrected():
    # Identical outcomes -> no discordant pairs
    pairs_same = [True] * 50 + [False] * 50
    res_same = mcnemar_test(pairs_same, pairs_same)
    assert not res_same.is_significant
    assert res_same.p_value == 1.0

    # Small discordant count (exact binomial)
    # A wins 15 times where B loses; B wins 2 times where A loses
    pairs_a = [True] * 15 + [False] * 2 + [True] * 20 + [False] * 20
    pairs_b = [False] * 15 + [True] * 2 + [True] * 20 + [False] * 20
    res_exact = mcnemar_test(pairs_a, pairs_b)
    assert "Exact Binomial" in res_exact.test_name
    assert res_exact.is_significant
    assert res_exact.p_value < 0.01

    # Large discordant count (continuity corrected)
    pairs_a_large = [True] * 35 + [False] * 5 + [True] * 30 + [False] * 30
    pairs_b_large = [False] * 35 + [True] * 5 + [True] * 30 + [False] * 30
    res_large = mcnemar_test(pairs_a_large, pairs_b_large)
    assert "Continuity Corrected" in res_large.test_name
    assert res_large.is_significant
    assert res_large.p_value < 0.001


def test_wilcoxon_signed_rank_test():
    scores_a = [10.5, 12.0, 15.2, 8.4, 22.1, 19.3, 14.0, 16.5, 18.0, 25.0]
    scores_b = [8.0, 9.5, 12.0, 7.0, 18.0, 15.0, 11.2, 13.0, 14.5, 20.0]
    res = wilcoxon_signed_rank_test(scores_a, scores_b)
    assert res.is_significant
    assert res.p_value < 0.05


def test_stratified_subgroups():
    entries = [
        {"category": "Sales", "equivalent_match": True, "sql_execution_success": True, "latency_seconds": 10.0, "table_precision": 1.0, "table_recall": 1.0},
        {"category": "Sales", "equivalent_match": False, "sql_execution_success": True, "latency_seconds": 12.0, "table_precision": 0.5, "table_recall": 1.0},
        {"category": "Customers", "equivalent_match": True, "sql_execution_success": True, "latency_seconds": 8.0, "table_precision": 1.0, "table_recall": 1.0},
    ]
    subgroups = analyze_stratified_subgroups(entries, group_by_key="category")
    assert "Sales" in subgroups
    assert "Customers" in subgroups
    assert subgroups["Sales"].sample_size == 2
    assert subgroups["Sales"].success_count == 1
    assert subgroups["Customers"].success_count == 1

    md_table = format_subgroup_markdown_table(subgroups)
    assert "| **Sales** |" in md_table
    assert "| **Customers** |" in md_table


def test_benchmark_statistical_analyzer():
    analyzer = BenchmarkStatisticalAnalyzer(confidence=0.95)
    entries = [
        {"query_id": "q1", "equivalent_match": True, "exact_match": True, "sql_execution_success": True, "latency_seconds": 5.0, "table_precision": 1.0, "table_recall": 1.0},
        {"query_id": "q2", "equivalent_match": False, "exact_match": False, "sql_execution_success": True, "latency_seconds": 15.0, "table_precision": 1.0, "table_recall": 1.0},
    ]
    rec = analyzer.process_entries("test_phase", "Test Phase", entries)
    assert rec.total_queries == 2
    assert rec.equivalent_matches == 1
    assert rec.mean_latency == 10.0

    md = format_markdown_phase_table([rec])
    assert "| **Test Phase** |" in md

    latex = format_latex_phase_table([rec])
    assert r"\begin{table*}" in latex
    assert "Test Phase" in latex
