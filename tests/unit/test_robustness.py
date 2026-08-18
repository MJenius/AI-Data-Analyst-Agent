"""Unit Tests for Robustness and OOD Perturbation Suite."""

import pytest

from agent_platform.experiments.robustness import (
    AmbiguousSynonymPerturbation,
    ParaphrasePerturbation,
    RankingVariantPerturbation,
    RobustnessSuiteBuilder,
    TemporalVariantPerturbation,
    TypoPerturbation,
    evaluate_robustness_drop,
    format_robustness_markdown_table,
)


def test_perturbation_generators():
    item = {
        "id": "q_test",
        "question": "What is the total revenue in 2017 for top 5 products?",
        "category": "Revenue & Sales",
    }

    p_para = ParaphrasePerturbation(seed=42).perturb(item)
    assert p_para["id"] == "q_test_ood_paraphrase"
    assert p_para["question"] != item["question"]
    assert p_para["perturbation_type"] == "paraphrase"

    p_typo = TypoPerturbation(seed=42).perturb(item)
    assert p_typo["id"] == "q_test_ood_typo"
    assert p_typo["perturbation_type"] == "typo"

    p_syn = AmbiguousSynonymPerturbation(seed=42).perturb(item)
    assert p_syn["id"] == "q_test_ood_synonym"
    assert p_syn["perturbation_type"] == "synonym"
    # Should replace revenue with a synonym
    assert "revenue" not in p_syn["question"].lower() or "turnover" in p_syn["question"].lower()

    p_rank = RankingVariantPerturbation(seed=42).perturb(item)
    assert p_rank["perturbation_type"] == "ranking_variant"
    assert "top 5" not in p_rank["question"].lower()

    p_temp = TemporalVariantPerturbation(seed=42).perturb(item)
    assert p_temp["perturbation_type"] == "temporal_variant"


def test_robustness_suite_builder():
    clean_items = [
        {"id": f"q_{i:02d}", "question": f"Question {i} about total revenue"}
        for i in range(10)
    ]
    builder = RobustnessSuiteBuilder(seed=42)
    ood_suite = builder.generate_suite(clean_items)
    assert len(ood_suite) == 10
    types = {item["perturbation_type"] for item in ood_suite}
    assert len(types) == 5  # All 5 perturbation types utilized


def test_evaluate_robustness_drop():
    clean_results = [
        {"id": f"q_{i:02d}", "equivalent_match": True} for i in range(10)
    ]
    # Simulate some failures under perturbation
    perturbed_results = [
        {"id": f"q_{i:02d}_ood_paraphrase", "perturbation_type": "paraphrase", "equivalent_match": (i % 2 == 0)}
        for i in range(10)
    ]

    reports = evaluate_robustness_drop(clean_results, perturbed_results)
    assert "paraphrase" in reports
    rep = reports["paraphrase"]
    assert rep.clean_accuracy == 1.0
    assert rep.perturbed_accuracy == 0.5
    assert rep.absolute_drop == 0.5
    assert rep.retention_rate == 0.5

    md = format_robustness_markdown_table(reports)
    assert "| **Paraphrase** |" in md
    assert "-50.0%" in md
