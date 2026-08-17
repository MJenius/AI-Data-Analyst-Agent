import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import pytest
from agent_platform.experiments.query_plan import (
    QueryPlan,
    CompositeMetric,
    MetricType,
    ResultShape,
)
from agent_platform.tools.plan_validator import (
    PlanValidator,
    PlanValidationCategory,
    find_minimum_join_path,
)


@pytest.fixture
def validator():
    return PlanValidator()


def test_missing_metric_repaired(validator):
    plan = QueryPlan(
        intent="Count orders",
        metric="",
        required_tables=["orders"],
    )
    res = validator.validate(plan, question="How many orders were placed?")
    assert res.repaired_plan.metric == "count"
    assert res.repaired_plan.aggregation == "COUNT"


def test_singular_superlative_default_limit(validator):
    plan = QueryPlan(
        intent="Find state with highest revenue",
        metric="revenue",
        required_tables=["order_items", "customers", "orders"],
        group_by=["customer_state"],
    )
    res = validator.validate(plan, question="Which state generated the highest revenue?")
    assert res.repaired_plan.limit == 1
    assert res.repaired_plan.ranking_direction == "DESC"
    assert res.repaired_plan.ordering == "revenue DESC"


def test_explicit_top_n_limit(validator):
    plan = QueryPlan(
        intent="Find top 5 categories",
        metric="revenue",
        required_tables=["order_items", "products"],
        group_by=["product_category_name"],
    )
    res = validator.validate(plan, question="What are the top 5 product categories by revenue?")
    assert res.repaired_plan.limit == 5
    assert res.repaired_plan.ranking_direction == "DESC"


def test_composite_metric_cancellation_rate(validator):
    plan = QueryPlan(
        intent="Compute cancellation rate",
        metric="cancellation rate",
        required_tables=["orders"],
    )
    res = validator.validate(plan, question="What is the monthly cancellation rate?")
    assert res.repaired_plan.composite_metric is not None
    assert res.repaired_plan.composite_metric.name == "cancellation_rate"
    assert "canceled" in res.repaired_plan.composite_metric.numerator


def test_time_grain_monthly_trend(validator):
    plan = QueryPlan(
        intent="Track revenue over time",
        metric="revenue",
        required_tables=["order_items", "orders"],
    )
    res = validator.validate(plan, question="What is the monthly revenue trend?")
    assert res.repaired_plan.time_grain == "month"
    assert "month" in res.repaired_plan.group_by
    assert res.repaired_plan.time_column == "order_purchase_timestamp"


def test_minimum_join_path_resolution(validator):
    # order_items and customers need orders as bridge
    joins = find_minimum_join_path(["order_items", "customers"])
    assert any("order_items.order_id = orders.order_id" in j or "orders.order_id = order_items.order_id" in j for j in joins)
    assert any("orders.customer_id = customers.customer_id" in j or "customers.customer_id = orders.customer_id" in j for j in joins)
