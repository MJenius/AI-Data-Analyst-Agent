"""Regression tests for Phase 10 ranking semantics.

Covers:
- Singular superlative → LIMIT 1 (singular noun + singular verb)
- Plural superlative → ranked list (plural noun + plural verb)
- Explicit "top N" / "bottom N" → authoritative limit
- Non-superlative questions → no limit
- Trend/distribution/list exclusions
- Metric source column resolution
"""

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
)


@pytest.fixture
def v():
    return PlanValidator()


def _plan(metric="revenue", tables=None, group_by=None, **kw):
    return QueryPlan(
        intent="test",
        metric=metric,
        required_tables=tables or ["order_items"],
        group_by=group_by,
        **kw,
    )


# ═══ Singular superlatives → LIMIT 1 ═══════════════════════════════════════

class TestSingularSuperlatives:
    def test_which_category_has_highest(self, v):
        res = v.validate(_plan(group_by=["product_category_name"], tables=["order_items", "products"]),
                         question="Which category has the highest revenue?")
        assert res.repaired_plan.limit == 1
        assert res.repaired_plan.ranking_direction == "DESC"

    def test_what_is_the_most_popular(self, v):
        res = v.validate(_plan(metric="order_count", group_by=["product_category_name"], tables=["order_items", "products"]),
                         question="What is the most popular product category?")
        assert res.repaired_plan.limit == 1
        assert res.repaired_plan.ranking_direction == "DESC"

    def test_what_is_the_lowest_rated(self, v):
        res = v.validate(_plan(metric="average_review_score", group_by=["product_category_name"],
                               tables=["order_reviews", "orders", "order_items", "products"]),
                         question="What is the lowest rated product category?")
        assert res.repaired_plan.limit == 1
        assert res.repaired_plan.ranking_direction == "ASC"

    def test_which_state_has_least_orders(self, v):
        res = v.validate(_plan(metric="order_count", group_by=["customer_state"], tables=["orders", "customers"]),
                         question="Which state has the least number of orders?")
        assert res.repaired_plan.limit == 1
        assert res.repaired_plan.ranking_direction == "ASC"

    def test_what_product_has_best_rating(self, v):
        res = v.validate(_plan(metric="rating", group_by=["product_category_name"],
                               tables=["order_reviews", "orders", "order_items", "products"]),
                         question="What product category has the best average rating?")
        assert res.repaired_plan.limit == 1
        assert res.repaired_plan.ranking_direction == "DESC"

    def test_which_seller_has_worst_score(self, v):
        res = v.validate(_plan(metric="rating", group_by=["seller_id"],
                               tables=["order_reviews", "orders", "order_items", "sellers"]),
                         question="Which seller has the worst review score?")
        assert res.repaired_plan.limit == 1
        assert res.repaired_plan.ranking_direction == "ASC"

    def test_what_is_the_largest_order(self, v):
        res = v.validate(_plan(metric="order_value"),
                         question="What is the largest order by total value?")
        assert res.repaired_plan.limit == 1
        assert res.repaired_plan.ranking_direction == "DESC"

    def test_what_is_the_smallest_category(self, v):
        res = v.validate(_plan(metric="order_count", group_by=["product_category_name"], tables=["order_items", "products"]),
                         question="What is the smallest product category by order count?")
        assert res.repaired_plan.limit == 1
        assert res.repaired_plan.ranking_direction == "ASC"


# ═══ Plural superlatives → ranked list ═════════════════════════════════════

class TestPluralSuperlatives:
    def test_which_categories_have_most(self, v):
        res = v.validate(_plan(metric="order_count", group_by=["product_category_name"], tables=["order_items", "products"]),
                         question="Which categories have the most orders?")
        assert res.repaired_plan.limit is None or res.repaired_plan.limit > 1
        assert res.repaired_plan.ranking_direction == "DESC"

    def test_what_are_the_least_popular(self, v):
        res = v.validate(_plan(metric="order_count", group_by=["product_category_name"], tables=["order_items", "products"]),
                         question="What are the least popular categories?")
        assert res.repaired_plan.limit is None or res.repaired_plan.limit > 1
        assert res.repaired_plan.ranking_direction == "ASC"

    def test_what_are_worst_performing_sellers(self, v):
        res = v.validate(_plan(metric="rating", group_by=["seller_id"], tables=["order_items", "sellers"]),
                         question="What are the worst performing sellers?")
        assert res.repaired_plan.limit is None or res.repaired_plan.limit > 1
        assert res.repaired_plan.ranking_direction == "ASC"

    def test_which_states_have_highest_revenue(self, v):
        """Plural 'states' + 'have' → NOT limit 1."""
        res = v.validate(_plan(group_by=["customer_state"], tables=["order_items", "orders", "customers"]),
                         question="Which states have the highest revenue?")
        assert res.repaired_plan.limit is None or res.repaired_plan.limit > 1

    def test_what_products_have_the_best_ratings(self, v):
        res = v.validate(_plan(metric="rating", group_by=["product_category_name"],
                               tables=["order_reviews", "orders", "order_items", "products"]),
                         question="What products have the best ratings?")
        assert res.repaired_plan.limit is None or res.repaired_plan.limit > 1


# ═══ Explicit top-N → authoritative ════════════════════════════════════════

class TestExplicitTopN:
    def test_top_5(self, v):
        res = v.validate(_plan(group_by=["product_category_name"], tables=["order_items", "products"]),
                         question="What are the top 5 product categories by revenue?")
        assert res.repaired_plan.limit == 5
        assert res.repaired_plan.ranking_direction == "DESC"

    def test_top_10(self, v):
        res = v.validate(_plan(group_by=["seller_id"], tables=["order_items", "sellers"]),
                         question="What are the top 10 sellers by revenue?")
        assert res.repaired_plan.limit == 10
        assert res.repaired_plan.ranking_direction == "DESC"

    def test_bottom_3(self, v):
        res = v.validate(_plan(metric="order_count", group_by=["customer_state"], tables=["orders", "customers"]),
                         question="What are the bottom 3 states by order count?")
        assert res.repaired_plan.limit == 3
        assert res.repaired_plan.ranking_direction == "ASC"

    def test_top_20(self, v):
        res = v.validate(_plan(group_by=["product_category_name"], tables=["order_items", "products"]),
                         question="Show the top 20 categories by total revenue.")
        assert res.repaired_plan.limit == 20

    def test_explicit_overrides_plan(self, v):
        """Explicit top-N should override whatever the plan had."""
        plan = _plan(group_by=["seller_id"], tables=["order_items", "sellers"], limit=100)
        res = v.validate(plan, question="What are the top 5 sellers?")
        assert res.repaired_plan.limit == 5

    def test_n_most_pattern(self, v):
        """'5 most popular' should be parsed as top-5."""
        res = v.validate(_plan(group_by=["product_category_name"], tables=["order_items", "products"]),
                         question="What are the 5 most popular categories?")
        assert res.repaired_plan.limit == 5


# ═══ Non-superlative → no limit ════════════════════════════════════════════

class TestNonSuperlative:
    def test_distribution_no_limit(self, v):
        res = v.validate(_plan(metric="count", group_by=["review_score"], tables=["order_reviews"]),
                         question="What is the distribution of review scores?")
        assert res.repaired_plan.limit is None

    def test_each_category_no_limit(self, v):
        res = v.validate(_plan(group_by=["product_category_name"], tables=["order_items", "products"]),
                         question="What is the revenue for each product category?")
        assert res.repaired_plan.limit is None

    def test_all_categories_no_limit(self, v):
        res = v.validate(_plan(group_by=["product_category_name"], tables=["order_items", "products"]),
                         question="List all categories by revenue.")
        assert res.repaired_plan.limit is None

    def test_monthly_trend_no_limit(self, v):
        res = v.validate(_plan(time_grain="month", group_by=["month"], tables=["order_items", "orders"]),
                         question="What is the monthly revenue trend?")
        assert res.repaired_plan.limit is None or res.repaired_plan.limit != 1

    def test_total_revenue_no_limit(self, v):
        res = v.validate(_plan(), question="What is the total revenue?")
        assert res.repaired_plan.limit is None

    def test_breakdown_by_payment_no_limit(self, v):
        res = v.validate(_plan(metric="payment_value", group_by=["payment_type"], tables=["order_payments"]),
                         question="Show the breakdown of payment value by payment type.")
        assert res.repaired_plan.limit is None


# ═══ Trend with superlative words → no limit 1 ═════════════════════════════

class TestTrendExclusions:
    def test_monthly_with_highest_word(self, v):
        """'Highest' in a monthly trend context should NOT trigger limit=1."""
        res = v.validate(_plan(time_grain="month", group_by=["month"], tables=["order_items", "orders"]),
                         question="Which month has the highest revenue over time?")
        # This is a time series, not a singular superlative
        assert res.repaired_plan.result_shape in (ResultShape.TIME_SERIES, "time_series") or \
               res.repaired_plan.limit is None or res.repaired_plan.limit != 1

    def test_compare_categories_no_limit(self, v):
        res = v.validate(_plan(group_by=["product_category_name"], tables=["order_items", "products"]),
                         question="Compare the most popular categories by revenue.")
        assert res.repaired_plan.limit is None


# ═══ Metric source column resolution ═══════════════════════════════════════

class TestMetricSourceResolution:
    def test_revenue_maps_to_price(self, v):
        res = v.validate(_plan(metric="revenue"), question="What is total revenue?")
        assert res.repaired_plan.metric_source_column == "price"

    def test_sales_maps_to_price(self, v):
        res = v.validate(_plan(metric="total_sales"), question="What are total sales?")
        assert res.repaired_plan.metric_source_column == "price"

    def test_payment_value_maps_correctly(self, v):
        res = v.validate(_plan(metric="payment_value", tables=["order_payments"]),
                         question="What is total payment value?")
        assert res.repaired_plan.metric_source_column == "payment_value"

    def test_rating_maps_to_review_score(self, v):
        res = v.validate(_plan(metric="average_review_score", tables=["order_reviews"]),
                         question="What is the average review score?")
        assert res.repaired_plan.metric_source_column == "review_score"

    def test_aov_maps_to_price(self, v):
        res = v.validate(_plan(metric="aov"), question="What is the AOV?")
        assert res.repaired_plan.metric_source_column == "price"

    def test_freight_maps_to_freight_value(self, v):
        res = v.validate(_plan(metric="freight"), question="What is total freight?")
        assert res.repaired_plan.metric_source_column == "freight_value"

    def test_no_source_for_count(self, v):
        """Count metrics don't have a specific source column."""
        res = v.validate(_plan(metric="count", tables=["orders"]),
                         question="How many orders?")
        assert res.repaired_plan.metric_source_column is None
