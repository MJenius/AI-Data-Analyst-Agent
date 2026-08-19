"""Unit Tests for Cost, Latency, and Pareto Profiling."""

import numpy as np
import pytest

from agent_platform.experiments.cost_latency import (
    ModelRateCard,
    ParetoPoint,
    RATE_CARDS,
    TokenCounter,
    analyze_repair_overhead,
    compute_latency_profile,
    compute_pareto_frontier,
    compute_tradeoff_gradients,
)


def test_token_counter_and_cost():
    tc = TokenCounter()
    text = "SELECT customer_id, COUNT(order_id) FROM orders GROUP BY customer_id;"
    cnt = tc.count_tokens(text)
    assert cnt > 5

    footprint = tc.estimate_query_tokens("What is total revenue?", "orders schema context", "SELECT SUM(price) FROM order_items;")
    assert footprint["prompt_tokens"] > 350
    assert footprint["completion_tokens"] > 0
    assert footprint["total_tokens"] == footprint["prompt_tokens"] + footprint["completion_tokens"]

    rc = RATE_CARDS["gpt-4o"]
    cost = rc.estimate_cost(prompt_tokens=1_000, completion_tokens=500)
    assert cost > 0.005  # $2.50/M input + $10/M output -> 0.0025 + 0.005 = 0.0075


def test_latency_distribution_profiler():
    latencies = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    prof = compute_latency_profile(latencies)
    assert prof.count == 10
    assert prof.mean == 55.0
    assert prof.p50 == 55.0
    assert prof.p95 > 85.0
    assert prof.iqr == 45.0


def test_repair_overhead_analyzer():
    entries = [
        {"latency_seconds": 10.0, "equivalent_match": True, "sql_execution_success": True, "repair_events": []},
        {"latency_seconds": 20.0, "equivalent_match": True, "sql_execution_success": True, "repair_events": []},
        {"latency_seconds": 35.0, "equivalent_match": True, "sql_execution_success": True, "repair_events": [{"reason": "fixed column"}]},
        {"latency_seconds": 40.0, "equivalent_match": False, "sql_execution_success": False, "repair_events": [{"reason": "timeout"}]},
    ]
    rep = analyze_repair_overhead(entries)
    assert rep.total_queries == 4
    assert rep.repaired_queries_count == 2
    assert rep.repair_trigger_rate == 0.5
    assert rep.rescued_queries_count == 1
    assert rep.repair_recovery_rate == 0.5
    assert rep.latency_overhead_seconds == 22.5  # Repaired mean (37.5) - Unrepaired mean (15.0)


def test_pareto_frontier_and_gradients():
    points = [
        ParetoPoint("Config A (RAG Only)", accuracy=0.19, latency_p50=150.0, latency_mean=150.0, cost_per_1k_queries=1.40),
        ParetoPoint("Config B (RAG+Plan)", accuracy=0.15, latency_p50=85.0, latency_mean=85.0, cost_per_1k_queries=1.80),
        ParetoPoint("Config C (RAG+Plan+Verify)", accuracy=0.26, latency_p50=200.0, latency_mean=200.0, cost_per_1k_queries=2.10),
        ParetoPoint("Config D (Worse all)", accuracy=0.10, latency_p50=300.0, latency_mean=300.0, cost_per_1k_queries=5.00),
    ]
    frontier = compute_pareto_frontier(points)
    
    # Config D must be dominated
    p_d = next(p for p in frontier if p.config_name == "Config D (Worse all)")
    assert not p_d.is_pareto_optimal
    assert len(p_d.dominated_by) > 0

    # Config C should be Pareto-optimal
    p_c = next(p for p in frontier if "Config C" in p.config_name)
    assert p_c.is_pareto_optimal

    gradients = compute_tradeoff_gradients(frontier)
    assert len(gradients) > 0
