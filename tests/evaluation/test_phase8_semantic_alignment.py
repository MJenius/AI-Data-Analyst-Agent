"""Phase 8 regression tests — plan-driven semantic alignment.

Covers the new QueryPlan-aware verification layer:

  1. Join path        (missing required table, unplanned extra table)
  2. Metric           (no aggregate, wrong aggregation family)
  3. Filters          (missing filter column, wrong year, question-evidence gate)
  4. Time grain       (month / day / hour, strftime case sensitivity)
  5. GROUP BY grain   (wrong dimension, missing GROUP BY)
  6. Ranking / top-N  (missing LIMIT, wrong LIMIT, wrong ordering direction)
  7. Entity           (planned entity column not referenced)
  8. Result shape     (columns, row count)

Also tests:
  - programmatic repairs (RANKING_MISMATCH LIMIT, GROUP_BY_GRAIN_MISMATCH)
  - the schema-inspection gate (sqlite_master queries must not be flagged)
  - backward compatibility of verify() without query_plan
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

DB_PATH = ROOT / "data" / "analytics.db"

from agent_platform.tools.sql_verifier import (
    SQLSemanticVerifier,
    VerificationCategory,
    VerificationLevel,
    VerificationIssue,
)


def plan(**kw) -> dict:
    return kw


PLAN_CATS = {
    VerificationCategory.JOIN_PATH_MISMATCH,
    VerificationCategory.METRIC_MISMATCH,
    VerificationCategory.FILTER_MISMATCH,
    VerificationCategory.TIME_GRAIN_MISMATCH,
    VerificationCategory.GROUP_BY_GRAIN_MISMATCH,
    VerificationCategory.RANKING_MISMATCH,
    VerificationCategory.ENTITY_MISMATCH,
}


def plan_issues(verifier, sql, query_plan, question=""):
    """Issues from the plan-alignment layer only."""
    res = verifier.verify(
        sql,
        level=VerificationLevel.BALANCED,
        query_plan=query_plan,
        question=question,
    )
    return [i for i in res.issues if i.category in PLAN_CATS]


@pytest.fixture(scope="module")
def verifier() -> SQLSemanticVerifier:
    return SQLSemanticVerifier(str(DB_PATH))


# ── backward compatibility ────────────────────────────────────────────────────

class TestBackwardCompatibility:
    def test_verify_without_plan(self, verifier):
        res = verifier.verify(
            "SELECT p.product_category_name, SUM(oi.price) AS revenue "
            "FROM order_items oi JOIN products p ON oi.product_id = p.product_id "
            "GROUP BY p.product_category_name"
        )
        assert isinstance(res.issues, list)

    def test_verify_with_execution_result_only(self, verifier):
        res = verifier.verify(
            "SELECT COUNT(*) AS c FROM orders",
            execution_result={"success": True, "row_count": 5, "rows": []},
        )
        assert isinstance(res.issues, list)

    def test_existing_structural_categories_still_fire(self, verifier):
        res = verifier.verify("SELECT made_up_column FROM orders")
        cats = {i.category for i in res.issues}
        assert VerificationCategory.HALLUCINATED_COLUMN in cats


# ── join path ─────────────────────────────────────────────────────────────────

class TestJoinPath:
    def test_missing_required_table_is_error(self, verifier):
        p = plan(
            metric="revenue", aggregation="SUM", entity="customer_state",
            filters=[], group_by=["customer_state"], ordering=None, limit=None,
            required_tables=["orders", "order_items", "customers"],
        )
        sql = (
            "SELECT p.product_category_name, SUM(oi.price) AS revenue "
            "FROM order_items oi JOIN orders o ON o.order_id = oi.order_id "
            "JOIN products p ON oi.product_id = p.product_id "
            "GROUP BY p.product_category_name"
        )
        issues = plan_issues(verifier, sql, p, "What is the revenue per customer state?")
        join_issues = [i for i in issues if i.category == VerificationCategory.JOIN_PATH_MISMATCH]
        assert any(i.severity == "error" and "customers" in i.message for i in join_issues)

    def test_unplanned_extra_table_is_warning(self, verifier):
        p = plan(
            metric="order count", aggregation="COUNT", entity="order",
            filters=[], group_by=None, ordering=None, limit=None,
            required_tables=["orders"],
        )
        sql = (
            "SELECT COUNT(*) AS order_count FROM orders o "
            "JOIN order_items oi ON o.order_id = oi.order_id"
        )
        issues = plan_issues(verifier, sql, p, "How many orders are there?")
        join_issues = [i for i in issues if i.category == VerificationCategory.JOIN_PATH_MISMATCH]
        assert any(i.severity == "warning" and "order_items" in i.message for i in join_issues)

    def test_correct_join_path_is_clean(self, verifier):
        p = plan(
            metric="revenue", aggregation="SUM", entity="customer_state",
            filters=[], group_by=["customer_state"], ordering=None, limit=None,
            required_tables=["orders", "order_items", "customers"],
        )
        sql = (
            "SELECT c.customer_state, SUM(oi.price) AS revenue "
            "FROM order_items oi "
            "JOIN orders o ON o.order_id = oi.order_id "
            "JOIN customers c ON c.customer_id = o.customer_id "
            "GROUP BY c.customer_state"
        )
        assert plan_issues(verifier, sql, p, "What is the revenue per customer state?") == []


# ── metric / aggregation ──────────────────────────────────────────────────────

class TestMetric:
    def test_missing_aggregate_is_error(self, verifier):
        p = plan(
            metric="revenue", aggregation="SUM", entity=None,
            filters=[], group_by=None, ordering=None, limit=None,
            required_tables=["order_items"],
        )
        sql = "SELECT price FROM order_items"
        issues = plan_issues(verifier, sql, p, "What is the total revenue?")
        assert any(
            i.category == VerificationCategory.METRIC_MISMATCH
            and i.severity == "error"
            and "no aggregate" in i.message
            for i in issues
        )

    def test_wrong_aggregation_family_is_warning(self, verifier):
        p = plan(
            metric="average price", aggregation="AVG", entity="category",
            filters=[], group_by=["category"], ordering=None, limit=None,
            required_tables=["order_items", "products"],
        )
        sql = (
            "SELECT p.product_category_name, SUM(oi.price) AS revenue "
            "FROM order_items oi JOIN products p ON oi.product_id = p.product_id "
            "GROUP BY p.product_category_name"
        )
        issues = plan_issues(verifier, sql, p, "What is the average price per product category?")
        assert any(
            i.category == VerificationCategory.METRIC_MISMATCH
            and i.severity == "warning"
            and "AVG" in i.message
            for i in issues
        )

    def test_correct_aggregation_is_clean(self, verifier):
        p = plan(
            metric="total revenue", aggregation="SUM", entity=None,
            filters=[], group_by=None, ordering=None, limit=None,
            required_tables=["order_items"],
        )
        sql = "SELECT SUM(oi.price) AS revenue FROM order_items oi"
        assert plan_issues(verifier, sql, p, "What is the total revenue?") == []


# ── filters ───────────────────────────────────────────────────────────────────

class TestFilters:
    def test_missing_filter_column_is_error(self, verifier):
        p = plan(
            metric="order count", aggregation="COUNT", entity="order",
            filters=["order_status = canceled"], group_by=None,
            ordering=None, limit=None, required_tables=["orders"],
        )
        sql = "SELECT COUNT(*) AS order_count FROM orders"
        issues = plan_issues(verifier, sql, p, "How many canceled orders are there?")
        assert any(
            i.category == VerificationCategory.FILTER_MISMATCH
            and i.severity == "error"
            and "order_status" in i.message
            for i in issues
        )

    def test_wrong_year_is_error(self, verifier):
        p = plan(
            metric="revenue", aggregation="SUM", entity=None,
            filters=["year = 2018"], group_by=None, ordering=None, limit=None,
            required_tables=["orders", "order_items"],
        )
        sql = (
            "SELECT SUM(oi.price) AS revenue FROM order_items oi "
            "JOIN orders o ON o.order_id = oi.order_id "
            "WHERE strftime('%Y', o.order_purchase_timestamp) = '2017'"
        )
        issues = plan_issues(verifier, sql, p, "What is the revenue in 2018?")
        assert any(
            i.category == VerificationCategory.FILTER_MISMATCH
            and i.severity == "error"
            and "2018" in i.message
            for i in issues
        )

    def test_filter_not_backed_by_question_is_skipped(self, verifier):
        p = plan(
            metric="revenue", aggregation="SUM", entity=None,
            filters=["order_status = canceled"], group_by=None,
            ordering=None, limit=None, required_tables=["orders", "order_items"],
        )
        sql = (
            "SELECT SUM(oi.price) AS revenue FROM order_items oi "
            "JOIN orders o ON o.order_id = oi.order_id"
        )
        # No cancel/canceled keyword in the question → planner may have
        # invented the filter; the check must stay silent (avoid false positive).
        issues = plan_issues(verifier, sql, p, "What is the total revenue?")
        assert all(i.category != VerificationCategory.FILTER_MISMATCH for i in issues)

    def test_correct_filter_is_clean(self, verifier):
        p = plan(
            metric="order count", aggregation="COUNT", entity="order",
            filters=["order_status = canceled"], group_by=None,
            ordering=None, limit=None, required_tables=["orders"],
        )
        sql = "SELECT COUNT(*) AS order_count FROM orders WHERE order_status = 'canceled'"
        assert plan_issues(verifier, sql, p, "How many canceled orders are there?") == []


# ── time grain ────────────────────────────────────────────────────────────────

class TestTimeGrain:
    MONTHLY = (
        "SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month, "
        "SUM(oi.price) AS revenue "
        "FROM order_items oi JOIN orders o ON o.order_id = oi.order_id "
        "GROUP BY month ORDER BY month"
    )
    DAILY = (
        "SELECT strftime('%Y-%m-%d', o.order_purchase_timestamp) AS day, "
        "SUM(oi.price) AS revenue "
        "FROM order_items oi JOIN orders o ON o.order_id = oi.order_id "
        "GROUP BY day ORDER BY day"
    )
    HOURLY = (
        "SELECT strftime('%Y-%m-%d %H:00:00', o.order_purchase_timestamp) AS hour, "
        "SUM(oi.price) AS revenue "
        "FROM order_items oi JOIN orders o ON o.order_id = oi.order_id "
        "GROUP BY hour ORDER BY hour"
    )

    def _plan(self, grain):
        return plan(
            metric="revenue", aggregation="SUM", entity="month",
            filters=[], group_by=[grain], ordering=None, limit=None,
            required_tables=["orders", "order_items"],
        )

    def test_no_time_truncation_is_error(self, verifier):
        sql = (
            "SELECT SUM(oi.price) AS revenue FROM order_items oi "
            "JOIN orders o ON o.order_id = oi.order_id"
        )
        issues = plan_issues(verifier, sql, self._plan("month"), "What is the monthly revenue trend?")
        assert any(i.category == VerificationCategory.TIME_GRAIN_MISMATCH for i in issues)

    def test_monthly_matches(self, verifier):
        assert plan_issues(verifier, self.MONTHLY, self._plan("month"), "monthly revenue?") == []

    def test_daily_does_not_match_month_plan(self, verifier):
        issues = plan_issues(verifier, self.DAILY, self._plan("month"), "monthly revenue?")
        assert any(i.category == VerificationCategory.TIME_GRAIN_MISMATCH for i in issues)

    def test_hourly_matches(self, verifier):
        assert plan_issues(verifier, self.HOURLY, self._plan("hour"), "hourly revenue?") == []

    def test_upper_case_strftime_format_matches(self, verifier):
        sql = (
            "SELECT strftime('%Y-%M', o.order_purchase_timestamp) AS month, "
            "SUM(oi.price) AS revenue "
            "FROM order_items oi JOIN orders o ON o.order_id = oi.order_id "
            "GROUP BY month"
        )
        assert plan_issues(verifier, sql, self._plan("month"), "monthly revenue?") == []


# ── GROUP BY grain ────────────────────────────────────────────────────────────

class TestGroupByGrain:
    def test_wrong_dimension_is_error(self, verifier):
        p = plan(
            metric="revenue", aggregation="SUM", entity="customer_state",
            filters=[], group_by=["customer_state"], ordering=None, limit=None,
            required_tables=["orders", "order_items", "customers"],
        )
        sql = (
            "SELECT p.product_category_name, SUM(oi.price) AS revenue "
            "FROM order_items oi JOIN orders o ON o.order_id = oi.order_id "
            "JOIN products p ON oi.product_id = p.product_id "
            "GROUP BY p.product_category_name"
        )
        issues = plan_issues(verifier, sql, p, "What is the revenue per customer state?")
        assert any(
            i.category == VerificationCategory.GROUP_BY_GRAIN_MISMATCH
            and i.severity == "error"
            for i in issues
        )

    def test_missing_group_by_is_error(self, verifier):
        p = plan(
            metric="revenue", aggregation="SUM", entity="category",
            filters=[], group_by=["category"], ordering=None, limit=None,
            required_tables=["order_items", "products"],
        )
        sql = (
            "SELECT p.product_category_name, SUM(oi.price) AS revenue "
            "FROM order_items oi JOIN products p ON oi.product_id = p.product_id"
        )
        issues = plan_issues(verifier, sql, p, "What is the revenue per product category?")
        assert any(
            i.category == VerificationCategory.GROUP_BY_GRAIN_MISMATCH
            and i.severity == "error"
            for i in issues
        )

    def test_correct_group_by_is_clean(self, verifier):
        p = plan(
            metric="revenue", aggregation="SUM", entity="category",
            filters=[], group_by=["category"], ordering=None, limit=None,
            required_tables=["order_items", "products"],
        )
        sql = (
            "SELECT p.product_category_name, SUM(oi.price) AS revenue "
            "FROM order_items oi JOIN products p ON oi.product_id = p.product_id "
            "GROUP BY p.product_category_name"
        )
        assert plan_issues(verifier, sql, p, "What is the revenue per product category?") == []


# ── ranking / top-N ───────────────────────────────────────────────────────────

class TestRanking:
    def _plan(self):
        return plan(
            metric="revenue", aggregation="SUM", entity="category",
            filters=[], group_by=["category"], ordering="revenue DESC",
            limit=10, required_tables=["order_items", "products"],
        )

    BASE = (
        "SELECT p.product_category_name, SUM(oi.price) AS revenue "
        "FROM order_items oi JOIN products p ON oi.product_id = p.product_id "
        "GROUP BY p.product_category_name ORDER BY revenue DESC"
    )

    def test_missing_limit_is_error(self, verifier):
        issues = plan_issues(verifier, self.BASE, self._plan(), "Which product categories generate the most revenue?")
        assert any(
            i.category == VerificationCategory.RANKING_MISMATCH
            and i.severity == "error"
            and "LIMIT" in i.message
            for i in issues
        )

    def test_wrong_limit_is_error(self, verifier):
        sql = self.BASE + " LIMIT 5"
        issues = plan_issues(verifier, sql, self._plan(), "Which product categories generate the most revenue?")
        assert any(
            i.category == VerificationCategory.RANKING_MISMATCH
            and i.severity == "error"
            and "5" in i.message
            for i in issues
        )

    def test_correct_limit_is_clean(self, verifier):
        assert plan_issues(verifier, self.BASE + " LIMIT 10", self._plan(), "most revenue?") == []

    def test_wrong_order_direction_is_warning(self, verifier):
        sql = self.BASE.replace("DESC", "ASC") + " LIMIT 10"
        issues = plan_issues(verifier, sql, self._plan(), "Which product categories generate the most revenue?")
        assert any(
            i.category == VerificationCategory.RANKING_MISMATCH
            and i.severity == "warning"
            for i in issues
        )

    def test_programmatic_repair_adds_limit(self, verifier):
        issue = VerificationIssue(
            category=VerificationCategory.RANKING_MISMATCH,
            severity="error",
            message="Plan requires a top-N LIMIT of 10 but the query has no LIMIT",
        )
        repaired = verifier.generate_repair(issue, self.BASE)
        assert repaired is not None
        assert repaired.rstrip().endswith("LIMIT 10")

    def test_programmatic_repair_replaces_limit(self, verifier):
        issue = VerificationIssue(
            category=VerificationCategory.RANKING_MISMATCH,
            severity="error",
            message="Plan requires a top-N LIMIT of 10 but the query has LIMIT 5",
        )
        repaired = verifier.generate_repair(issue, self.BASE + " LIMIT 5")
        assert repaired is not None
        assert repaired.rstrip().endswith("LIMIT 10")


# ── entity ────────────────────────────────────────────────────────────────────

class TestEntity:
    def test_entity_column_not_referenced_is_warning(self, verifier):
        p = plan(
            metric="revenue", aggregation="SUM", entity="customer_state",
            filters=[], group_by=["customer_state"], ordering=None, limit=None,
            required_tables=["orders", "order_items", "customers"],
        )
        sql = (
            "SELECT p.product_category_name, SUM(oi.price) AS revenue "
            "FROM order_items oi JOIN orders o ON o.order_id = oi.order_id "
            "JOIN products p ON oi.product_id = p.product_id "
            "GROUP BY p.product_category_name"
        )
        issues = plan_issues(verifier, sql, p, "What is the revenue per customer state?")
        assert any(
            i.category == VerificationCategory.ENTITY_MISMATCH
            and i.severity == "warning"
            and "customer_state" in i.message
            for i in issues
        )

    def test_entity_column_present_is_clean(self, verifier):
        p = plan(
            metric="revenue", aggregation="SUM", entity="customer_state",
            filters=[], group_by=["customer_state"], ordering=None, limit=None,
            required_tables=["orders", "order_items", "customers"],
        )
        sql = (
            "SELECT c.customer_state, SUM(oi.price) AS revenue "
            "FROM order_items oi "
            "JOIN orders o ON o.order_id = oi.order_id "
            "JOIN customers c ON c.customer_id = o.customer_id "
            "GROUP BY c.customer_state"
        )
        assert plan_issues(verifier, sql, p, "What is the revenue per customer state?") == []


# ── result shape ──────────────────────────────────────────────────────────────

class TestResultShape:
    def test_column_mismatch_is_error(self, verifier):
        res = verifier.verify(
            "SELECT p.product_category_name AS foo, SUM(oi.price) AS bar "
            "FROM order_items oi JOIN products p ON oi.product_id = p.product_id "
            "GROUP BY foo",
            execution_result={"success": True, "row_count": 5, "columns": ["foo", "bar"], "rows": []},
            expected_result={"row_count": 5, "columns": ["category", "revenue"], "values": []},
        )
        assert any(
            i.category == VerificationCategory.RESULT_SHAPE_MISMATCH
            and i.severity == "error"
            for i in res.issues
        )

    def test_row_count_mismatch_is_warning(self, verifier):
        res = verifier.verify(
            "SELECT p.product_category_name, SUM(oi.price) AS revenue "
            "FROM order_items oi JOIN products p ON oi.product_id = p.product_id "
            "GROUP BY p.product_category_name",
            execution_result={"success": True, "row_count": 12, "rows": []},
            expected_result={"row_count": 5, "columns": ["product_category_name", "revenue"], "values": []},
        )
        assert any(
            i.category == VerificationCategory.RESULT_SHAPE_MISMATCH
            and i.severity == "warning"
            for i in res.issues
        )

    def test_matching_shape_is_clean(self, verifier):
        res = verifier.verify(
            "SELECT p.product_category_name, SUM(oi.price) AS revenue "
            "FROM order_items oi JOIN products p ON oi.product_id = p.product_id "
            "GROUP BY p.product_category_name",
            execution_result={"success": True, "row_count": 5, "rows": []},
            expected_result={"row_count": 5, "columns": ["product_category_name", "revenue"], "values": []},
        )
        assert all(i.category != VerificationCategory.RESULT_SHAPE_MISMATCH for i in res.issues)


# ── gates and no-false-positive ───────────────────────────────────────────────

class TestGates:
    def test_schema_inspection_sql_is_not_flagged(self, verifier):
        p = plan(
            metric="revenue", aggregation="SUM", entity=None,
            filters=[], group_by=None, ordering=None, limit=None,
            required_tables=["order_items"],
        )
        res = verifier.verify(
            "SELECT name, type FROM sqlite_master WHERE type='table'",
            query_plan=p,
            question="List the tables in the database",
        )
        assert res.issues == []

    def test_correct_sql_no_false_positives(self, verifier):
        p = plan(
            metric="order count", aggregation="COUNT", entity="order",
            filters=["order_status = delivered"], group_by=None,
            ordering=None, limit=None, required_tables=["orders"],
        )
        res = verifier.verify(
            "SELECT COUNT(*) AS order_count FROM orders WHERE order_status = 'delivered'",
            query_plan=p,
            question="How many delivered orders are there?",
        )
        assert res.issues == []


# ── executor wiring (plan-aware verification + repair events) ─────────────────

class TestExecutorWiring:
    """End-to-end executor wiring: plan-aware verify + ONE repair call recorded."""

    TOP_CATEGORIES_SQL = (
        "SELECT p.product_category_name, SUM(oi.price) AS revenue "
        "FROM order_items oi JOIN products p ON oi.product_id = p.product_id "
        "GROUP BY p.product_category_name ORDER BY revenue DESC"
    )

    def _make_executor(self, sql_response: dict):
        from agent_platform.analytics.agents import AnalyticsExecutorAgent
        from agent_platform.tools.sql_tool import SQLTool

        class FakeSchemaItem:
            def __init__(self, table: str):
                self.text = f"table: {table}"
                self.metadata = {"kind": "table", "table": table}

        class FakeRetriever:
            TABLES = ("order_items", "orders", "products")

            def retrieve_grounded(self, query: str):
                return [FakeSchemaItem(t) for t in self.TABLES]

        class FakeLLM:
            enabled = True

            def __init__(self, response: dict):
                self._response = response

            def complete_json(self, system_prompt, user_prompt, temperature=0.1, response_model=None):
                return self._response

        sql_tool = SQLTool(f"sqlite:///{DB_PATH.as_posix()}")
        executor = AnalyticsExecutorAgent(
            schema_retriever=FakeRetriever(),
            sql_tool=sql_tool,
            llm_client=FakeLLM(sql_response),
        )
        return executor

    def _state(self, plan_kwargs: dict):
        from agent_platform.experiments.query_plan import QueryPlan
        from agent_platform.orchestration.state import ExecutionState

        state = ExecutionState(task="Which product categories generate the most revenue?")
        state.query_plan = QueryPlan(**plan_kwargs)
        state.plan = state.query_plan.to_steps()
        return state

    def test_programmatic_ranking_repair_recorded(self):
        executor = self._make_executor({
            "sql": self.TOP_CATEGORIES_SQL,  # missing LIMIT
            "reasoning": "ok",
        })
        state = self._state({
            "intent": "Top product categories by revenue",
            "metric": "total revenue",
            "entity": "category",
            "aggregation": "SUM",
            "group_by": ["product_category_name"],
            "ordering": "revenue DESC",
            "limit": 10,
            "required_tables": ["order_items", "products"],
        })
        result = asyncio.run(executor.execute(state.plan[1], [], state))

        assert len(state.repair_events) == 1
        ev = state.repair_events[0]
        assert ev["attempted"] is True
        assert ev["applied"] is True
        assert ev["method"] == "programmatic"
        assert "ranking_mismatch" in ev["categories"]
        assert ev["pre_repair_sql"] == self.TOP_CATEGORIES_SQL
        assert ev["re_validated"] is True
        assert ev["executed"] is True
        assert ev["final_sql"].rstrip().endswith("LIMIT 10")
        assert result["output"]["sql"].rstrip().endswith("LIMIT 10")

    def test_no_issues_means_no_repair_events(self):
        executor = self._make_executor({
            "sql": self.TOP_CATEGORIES_SQL + " LIMIT 10",
            "reasoning": "ok",
        })
        state = self._state({
            "intent": "Top product categories by revenue",
            "metric": "total revenue",
            "entity": "category",
            "aggregation": "SUM",
            "group_by": ["product_category_name"],
            "ordering": "revenue DESC",
            "limit": 10,
            "required_tables": ["order_items", "products"],
        })
        result = asyncio.run(executor.execute(state.plan[1], [], state))
        assert state.repair_events == []
        assert result["output"]["sql"].rstrip().endswith("LIMIT 10")

    def test_llm_fallback_when_programmatic_unavailable(self):
        # metric family mismatch (AVG vs SUM) has no programmatic repair —
        # falls back to the ONE LLM repair call, recorded as an event.
        executor = self._make_executor({
            "sql": self.TOP_CATEGORIES_SQL + " LIMIT 10",  # SUM, plan wants AVG
            "reasoning": "ok",
        })
        state = self._state({
            "intent": "Average price per product category",
            "metric": "average price",
            "entity": "category",
            "aggregation": "AVG",
            "group_by": ["product_category_name"],
            "ordering": "revenue DESC",
            "limit": 10,
            "required_tables": ["order_items", "products"],
        })
        result = asyncio.run(executor.execute(state.plan[1], [], state))
        assert len(state.repair_events) >= 1
        ev = state.repair_events[0]
        assert ev["attempted"] is True
        assert "metric_mismatch" in ev["categories"]
        # LLM returns the same SQL (mock) → no change applied
        assert ev["applied"] is False
        assert ev["method"] == "llm"
        assert result["output"]["sql"].rstrip().endswith("LIMIT 10")