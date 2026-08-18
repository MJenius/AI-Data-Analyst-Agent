"""Unit Tests for External Baselines and Evaluation Harness."""

import pytest

from agent_platform.experiments.baselines import (
    BaselineHarness,
    FewShotBaselinePromptBuilder,
    NaiveRAGPromptBuilder,
    ReActAgentPromptBuilder,
    ZeroShotBaselinePromptBuilder,
    format_baselines_markdown_table,
)


def test_baseline_prompt_builders():
    q = "What is the total revenue generated?"

    p_zero = ZeroShotBaselinePromptBuilder.build_prompt(q)
    assert "Database Schema:" in p_zero
    assert q in p_zero

    p_few = FewShotBaselinePromptBuilder.build_prompt(q)
    assert "Demonstrations:" in p_few
    assert "Example 1:" in p_few

    p_rag = NaiveRAGPromptBuilder.build_prompt(q, retrieved_tables=["orders", "order_items"])
    assert "Retrieved Schemas:" in p_rag
    assert "CREATE TABLE orders" in p_rag

    p_react = ReActAgentPromptBuilder.build_prompt(q)
    assert "Thought:" in p_react
    assert "Action: execute_sql" in p_react


def test_baseline_simulation_and_markdown():
    harness = BaselineHarness()
    res_zero = harness.simulate_baseline_metrics("zero_shot_direct", total_queries=100)
    assert res_zero.total_queries == 100
    assert res_zero.equivalent_rate == 0.12

    res_full = harness.simulate_baseline_metrics("full_system_rag_verifier", total_queries=100)
    assert res_full.equivalent_rate == 0.26

    md = format_baselines_markdown_table([res_zero, res_full])
    assert "| Zero Shot Direct |" in md
    assert "**Full System Rag Verifier (Ours)**" in md
