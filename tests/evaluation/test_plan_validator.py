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
    _tables_reachable_from,
)


@pytest.fixture
def validator():
    return PlanValidator()


# ── Existing tests (preserved) ─────────────────────────────────────────────

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


# ── New superlative regression tests ────────────────────────────────────────

def test_superlative_lowest(validator):
    plan = QueryPlan(
        intent="Find category with lowest revenue",
        metric="revenue",
        required_tables=["order_items", "products"],
        group_by=["product_category_name"],
    )
    res = validator.validate(plan, question="What category has the lowest revenue?")
    assert res.repaired_plan.limit == 1
    assert res.repaired_plan.ranking_direction == "ASC"


def test_superlative_most_popular(validator):
    plan = QueryPlan(
        intent="Find most popular category",
        metric="order_count",
        required_tables=["order_items", "products"],
        group_by=["product_category_name"],
    )
    res = validator.validate(plan, question="What is the most popular product category?")
    assert res.repaired_plan.limit == 1
    assert res.repaired_plan.ranking_direction == "DESC"


def test_superlative_least_orders(validator):
    plan = QueryPlan(
        intent="Find state with least orders",
        metric="order_count",
        required_tables=["orders", "customers"],
        group_by=["customer_state"],
    )
    res = validator.validate(plan, question="Which state has the least number of orders?")
    assert res.repaired_plan.limit == 1
    assert res.repaired_plan.ranking_direction == "ASC"


def test_superlative_best_rated(validator):
    plan = QueryPlan(
        intent="Find best rated product",
        metric="average_review_score",
        required_tables=["order_reviews", "orders", "order_items", "products"],
        group_by=["product_category_name"],
    )
    res = validator.validate(plan, question="What product category has the best rating?")
    assert res.repaired_plan.limit == 1
    assert res.repaired_plan.ranking_direction == "DESC"


def test_superlative_worst_rated(validator):
    plan = QueryPlan(
        intent="Find worst rated product",
        metric="average_review_score",
        required_tables=["order_reviews", "orders", "order_items", "products"],
        group_by=["product_category_name"],
    )
    res = validator.validate(plan, question="Which category has the worst average review score?")
    assert res.repaired_plan.limit == 1
    assert res.repaired_plan.ranking_direction == "ASC"


def test_superlative_largest(validator):
    plan = QueryPlan(
        intent="Find largest order",
        metric="order_value",
        required_tables=["order_items"],
    )
    res = validator.validate(plan, question="What is the largest order by total value?")
    assert res.repaired_plan.limit == 1
    assert res.repaired_plan.ranking_direction == "DESC"


def test_top_10_explicit(validator):
    plan = QueryPlan(
        intent="Find top 10 sellers",
        metric="revenue",
        required_tables=["order_items", "sellers"],
        group_by=["seller_id"],
    )
    res = validator.validate(plan, question="What are the top 10 sellers by revenue?")
    assert res.repaired_plan.limit == 10
    assert res.repaired_plan.ranking_direction == "DESC"


def test_bottom_3_explicit(validator):
    plan = QueryPlan(
        intent="Find bottom 3 states",
        metric="order_count",
        required_tables=["orders", "customers"],
        group_by=["customer_state"],
    )
    res = validator.validate(plan, question="What are the bottom 3 states by order count?")
    assert res.repaired_plan.limit == 3
    assert res.repaired_plan.ranking_direction == "ASC"


# ── Monthly trend should NOT set limit=1 ────────────────────────────────────

def test_monthly_trend_no_limit_1(validator):
    """Monthly trend with 'highest' in context should NOT get limit=1."""
    plan = QueryPlan(
        intent="Monthly revenue trend",
        metric="revenue",
        required_tables=["order_items", "orders"],
        time_grain="month",
        group_by=["month"],
    )
    res = validator.validate(plan, question="What is the monthly revenue trend?")
    assert res.repaired_plan.limit is None or res.repaired_plan.limit != 1
    assert res.repaired_plan.result_shape == ResultShape.TIME_SERIES


# ── Composite metric completeness ──────────────────────────────────────────

def test_composite_metric_incomplete_ratio(validator):
    """A ratio composite metric without denominator should raise an error."""
    plan = QueryPlan(
        intent="Compute conversion rate",
        metric="conversion_rate",
        required_tables=["orders"],
        composite_metric=CompositeMetric(
            metric_type=MetricType.RATIO,
            name="conversion_rate",
            numerator="COUNT(DISTINCT converted)",
            denominator=None,  # Missing!
        ),
    )
    res = validator.validate(plan, question="What is the conversion rate?")
    malformed = [i for i in res.issues if i.category == PlanValidationCategory.MALFORMED_COMPOSITE_METRIC]
    assert len(malformed) > 0


def test_composite_metric_aov(validator):
    plan = QueryPlan(
        intent="Compute AOV",
        metric="aov",
        required_tables=["order_items"],
    )
    res = validator.validate(plan, question="What is the average order value?")
    assert res.repaired_plan.composite_metric is not None
    assert res.repaired_plan.composite_metric.name == "aov"
    assert res.repaired_plan.composite_metric.numerator is not None
    assert res.repaired_plan.composite_metric.denominator is not None


# ── Join path and table connectivity ────────────────────────────────────────

def test_join_path_three_tables(validator):
    """Three tables should produce a connected join path."""
    joins = find_minimum_join_path(["customers", "orders", "order_items"])
    assert len(joins) >= 2


def test_join_path_single_table():
    """Single table needs no joins."""
    joins = find_minimum_join_path(["orders"])
    assert joins == []


def test_disconnected_table_detection(validator):
    """Geolocation is connected to customers but not directly to order_items."""
    reachable = _tables_reachable_from("order_items", {"order_items", "geolocation"})
    # geolocation is not directly connected to order_items
    assert "geolocation" not in reachable


# ── Bridge table insertion ──────────────────────────────────────────────────

def test_bridge_table_customers_order_items(validator):
    """Customers + order_items should automatically add orders as bridge."""
    plan = QueryPlan(
        intent="Revenue by customer state",
        metric="revenue",
        required_tables=["order_items", "customers"],
        group_by=["customer_state"],
    )
    res = validator.validate(plan, question="What is the revenue by customer state?")
    assert "orders" in res.repaired_plan.required_tables


def test_bridge_table_reviews_items(validator):
    """Reviews + order_items should automatically add orders as bridge."""
    plan = QueryPlan(
        intent="Rating by product",
        metric="rating",
        required_tables=["order_reviews", "order_items"],
    )
    res = validator.validate(plan, question="What is the average review score by product?")
    assert "orders" in res.repaired_plan.required_tables


# ── Result shape assignment ─────────────────────────────────────────────────

def test_result_shape_single_value(validator):
    plan = QueryPlan(
        intent="Total revenue",
        metric="total_revenue",
        required_tables=["order_items"],
    )
    res = validator.validate(plan, question="What is the total revenue?")
    assert res.repaired_plan.result_shape == ResultShape.SINGLE_VALUE


def test_result_shape_ranked_list(validator):
    plan = QueryPlan(
        intent="Top 5 categories",
        metric="revenue",
        required_tables=["order_items", "products"],
        group_by=["product_category_name"],
        limit=5,
        ranking_direction="DESC",
    )
    res = validator.validate(plan, question="What are the top 5 product categories?")
    assert res.repaired_plan.result_shape == ResultShape.RANKED_LIST


def test_result_shape_time_series(validator):
    plan = QueryPlan(
        intent="Monthly trend",
        metric="revenue",
        required_tables=["order_items", "orders"],
        time_grain="month",
        group_by=["month"],
    )
    res = validator.validate(plan, question="Show monthly revenue trend.")
    assert res.repaired_plan.result_shape == ResultShape.TIME_SERIES


def test_result_shape_aggregated_table(validator):
    plan = QueryPlan(
        intent="Revenue by payment type",
        metric="revenue",
        required_tables=["order_payments"],
        group_by=["payment_type"],
    )
    res = validator.validate(plan, question="What is the revenue by payment type?")
    assert res.repaired_plan.result_shape == ResultShape.AGGREGATED_TABLE


# ── No false positive on non-superlative questions ──────────────────────────

def test_no_limit_for_distribution_question(validator):
    """Distribution questions should not get limit=1."""
    plan = QueryPlan(
        intent="Distribution of review scores",
        metric="count",
        required_tables=["order_reviews"],
        group_by=["review_score"],
    )
    res = validator.validate(plan, question="What is the distribution of review scores?")
    assert res.repaired_plan.limit is None


def test_no_limit_for_all_categories(validator):
    """'All categories' should not get limit=1."""
    plan = QueryPlan(
        intent="Revenue for all categories",
        metric="revenue",
        required_tables=["order_items", "products"],
        group_by=["product_category_name"],
    )
    res = validator.validate(plan, question="What is the revenue for each product category?")
    assert res.repaired_plan.limit is None
