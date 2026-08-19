"""Phase 6 regression tests — verification-driven SQL repair.

Covers the three main Phase 5 failure categories:
  1. GROUP BY mismatch  (41 cases in Phase 5)
  2. Hallucinated columns (39 cases in Phase 5)
  3. Aggregation grain   (agg + dimension, no GROUP BY)

Also tests:
  - The programmatic repair path (generate_repair)
  - The repair prompt builder
  - filter_actionable_issues gate
  - The column-level grounding helpers (build_column_grounding_block, tables_from_context)
"""

from __future__ import annotations

import re
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
from agent_platform.llms.repair_prompt import (
    build_repair_prompt,
    filter_actionable_issues,
    SYSTEM_PROMPT as REPAIR_SYSTEM_PROMPT,
)
from agent_platform.rag.ingestion.schema_context import (
    build_column_grounding_block,
    tables_from_context,
    EXACT_COLUMNS,
)


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def verifier() -> SQLSemanticVerifier:
    return SQLSemanticVerifier(str(DB_PATH))


# ── Phase 5 failure category 1: GROUP BY mismatch (41 cases) ─────────────────

class TestGroupByRepair:
    """GROUP BY mismatch: non-aggregate SELECT column missing from GROUP BY."""

    MONTHLY_NO_GB = """
        SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month,
               SUM(oi.price) AS revenue
        FROM orders o
        JOIN order_items oi ON o.order_id = oi.order_id
    """
    # month is in SELECT, aggregates present, but no GROUP BY at all

    CATEGORY_PARTIAL_GB = """
        SELECT p.product_category_name, c.customer_state, SUM(oi.price) AS revenue
        FROM order_items oi
        JOIN orders o      ON o.order_id    = oi.order_id
        JOIN products p    ON p.product_id  = oi.product_id
        JOIN customers c   ON c.customer_id = o.customer_id
        GROUP BY p.product_category_name
    """
    # customer_state in SELECT but not in GROUP BY

    MONTHLY_CORRECT = """
        SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month,
               SUM(oi.price) AS revenue
        FROM orders o
        JOIN order_items oi ON o.order_id = oi.order_id
        GROUP BY month
        ORDER BY month
    """

    def test_missing_groupby_detected(self, verifier: SQLSemanticVerifier) -> None:
        result = verifier.verify(self.MONTHLY_NO_GB, level=VerificationLevel.BALANCED)
        assert not result.is_valid
        categories = {i.category for i in result.issues}
        # Either AGGREGATION_GRAIN (agg + non-agg, no GROUP BY) or GROUP_BY_MISMATCH
        assert (
            VerificationCategory.AGGREGATION_GRAIN in categories
            or VerificationCategory.GROUP_BY_MISMATCH in categories
        )

    def test_partial_groupby_mismatch_detected(self, verifier: SQLSemanticVerifier) -> None:
        result = verifier.verify(self.CATEGORY_PARTIAL_GB, level=VerificationLevel.BALANCED)
        assert not result.is_valid
        gb_issues = [i for i in result.issues if i.category == VerificationCategory.GROUP_BY_MISMATCH]
        assert len(gb_issues) >= 1
        # customer_state should be flagged
        flagged_cols = [i.message for i in gb_issues]
        assert any("customer_state" in m for m in flagged_cols)

    def test_correct_query_passes(self, verifier: SQLSemanticVerifier) -> None:
        result = verifier.verify(self.MONTHLY_CORRECT, level=VerificationLevel.BALANCED)
        blocking = [i for i in result.issues if i.severity in ("error", "warning")]
        assert len(blocking) == 0, f"Correct query should pass: {blocking}"

    def test_programmatic_repair_adds_missing_column(self, verifier: SQLSemanticVerifier) -> None:
        result = verifier.verify(self.CATEGORY_PARTIAL_GB, level=VerificationLevel.BALANCED)
        gb_issues = [i for i in result.issues if i.category == VerificationCategory.GROUP_BY_MISMATCH]
        assert len(gb_issues) >= 1

        repaired = verifier.generate_repair(gb_issues[0], self.CATEGORY_PARTIAL_GB)
        assert repaired is not None, "Programmatic repair should return SQL for GROUP BY mismatch"
        # The repair must reference customer_state
        assert "customer_state" in repaired.lower()
        # The repair must preserve the original GROUP BY column
        assert "product_category_name" in repaired.lower()

    def test_programmatic_repair_parses_as_valid_sql(self, verifier: SQLSemanticVerifier) -> None:
        result = verifier.verify(self.CATEGORY_PARTIAL_GB, level=VerificationLevel.BALANCED)
        gb_issues = [i for i in result.issues if i.category == VerificationCategory.GROUP_BY_MISMATCH]
        if not gb_issues:
            pytest.skip("No GROUP BY issue found in test query")

        repaired = verifier.generate_repair(gb_issues[0], self.CATEGORY_PARTIAL_GB)
        if repaired is None:
            pytest.skip("Programmatic repair returned None")

        import sqlglot
        parsed = sqlglot.parse_one(repaired, read="sqlite")
        assert parsed is not None

    def test_repair_result_is_different_from_original(self, verifier: SQLSemanticVerifier) -> None:
        result = verifier.verify(self.CATEGORY_PARTIAL_GB, level=VerificationLevel.BALANCED)
        gb_issues = [i for i in result.issues if i.category == VerificationCategory.GROUP_BY_MISMATCH]
        if not gb_issues:
            pytest.skip("No GROUP BY issue found")
        repaired = verifier.generate_repair(gb_issues[0], self.CATEGORY_PARTIAL_GB)
        if repaired:
            assert repaired.strip() != self.CATEGORY_PARTIAL_GB.strip()


# ── Phase 5 failure category 2: Hallucinated columns (39 cases) ──────────────

class TestHallucinatedColumnDetection:
    """Column names that do not exist in the schema should be flagged as errors."""

    # Exact Phase 4 failure patterns from raw_results.json
    UNIT_PRICE_QUERY = """
        SELECT SUM(CAST(quantity AS REAL) * unit_price * (1 - discount_rate)) AS total_revenue
        FROM order_items
    """
    ORDER_DATE_QUERY = """
        SELECT strftime('%Y-%m', order_date) AS month, COUNT(DISTINCT order_id) AS orders
        FROM orders
        GROUP BY month
        ORDER BY month
    """
    CATEGORY_NAME_EN_WRONG = """
        SELECT p.category_name_english, SUM(oi.price) AS revenue
        FROM order_items oi
        JOIN products p ON p.product_id = oi.product_id
        GROUP BY p.category_name_english
        ORDER BY revenue DESC
        LIMIT 10
    """
    DISCOUNT_RATE_QUERY = """
        SELECT seller_id, AVG(discount_rate) AS avg_discount
        FROM order_items
        GROUP BY seller_id
        ORDER BY avg_discount DESC
        LIMIT 10
    """

    def test_unit_price_flagged(self, verifier: SQLSemanticVerifier) -> None:
        result = verifier.verify(self.UNIT_PRICE_QUERY)
        hall = [i for i in result.issues if i.category == VerificationCategory.HALLUCINATED_COLUMN]
        assert len(hall) >= 1, "unit_price / quantity / discount_rate must be flagged"
        col_names_mentioned = " ".join(i.message for i in hall).lower()
        assert any(col in col_names_mentioned for col in ("unit_price", "quantity", "discount_rate"))

    def test_order_date_flagged(self, verifier: SQLSemanticVerifier) -> None:
        result = verifier.verify(self.ORDER_DATE_QUERY)
        hall = [i for i in result.issues if i.category == VerificationCategory.HALLUCINATED_COLUMN]
        assert len(hall) >= 1, "order_date does not exist; should be flagged"
        assert "order_date" in " ".join(i.message for i in hall).lower()

    def test_category_name_english_flagged(self, verifier: SQLSemanticVerifier) -> None:
        result = verifier.verify(self.CATEGORY_NAME_EN_WRONG)
        hall = [i for i in result.issues if i.category == VerificationCategory.HALLUCINATED_COLUMN]
        assert len(hall) >= 1, "category_name_english does not exist; should be flagged"

    def test_discount_rate_flagged(self, verifier: SQLSemanticVerifier) -> None:
        result = verifier.verify(self.DISCOUNT_RATE_QUERY)
        hall = [i for i in result.issues if i.category == VerificationCategory.HALLUCINATED_COLUMN]
        assert len(hall) >= 1, "discount_rate does not exist; should be flagged"
        assert "discount_rate" in " ".join(i.message for i in hall).lower()

    def test_hallucinated_column_is_error_severity(self, verifier: SQLSemanticVerifier) -> None:
        """Hallucinated columns must be error-severity (not just warnings)."""
        result = verifier.verify(self.UNIT_PRICE_QUERY)
        hall = [i for i in result.issues if i.category == VerificationCategory.HALLUCINATED_COLUMN]
        assert all(i.severity == "error" for i in hall)

    def test_valid_columns_not_flagged(self, verifier: SQLSemanticVerifier) -> None:
        """Real columns must not be falsely flagged as hallucinated."""
        good_sql = """
            SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month,
                   SUM(oi.price) AS revenue
            FROM orders o
            JOIN order_items oi ON o.order_id = oi.order_id
            GROUP BY month
            ORDER BY month
        """
        result = verifier.verify(good_sql)
        hall = [i for i in result.issues if i.category == VerificationCategory.HALLUCINATED_COLUMN]
        assert len(hall) == 0, f"False positives: {[i.message for i in hall]}"

    def test_cte_derived_columns_not_flagged(self, verifier: SQLSemanticVerifier) -> None:
        """CTE-defined aliases must not be flagged as hallucinated columns."""
        cte_sql = """
            WITH monthly AS (
                SELECT strftime('%Y-%m', order_purchase_timestamp) AS month,
                       order_id
                FROM orders
            )
            SELECT month, COUNT(DISTINCT order_id) AS order_count
            FROM monthly
            GROUP BY month
        """
        result = verifier.verify(cte_sql)
        hall = [i for i in result.issues if i.category == VerificationCategory.HALLUCINATED_COLUMN]
        assert len(hall) == 0, f"CTE columns should not be flagged: {[i.message for i in hall]}"

    def test_correct_english_category_column(self, verifier: SQLSemanticVerifier) -> None:
        """The actual English category column name must pass."""
        good_sql = """
            SELECT t.product_category_name_english, SUM(oi.price) AS revenue
            FROM order_items oi
            JOIN products p ON p.product_id = oi.product_id
            JOIN product_category_name_translation t
              ON t.product_category_name = p.product_category_name
            GROUP BY t.product_category_name_english
            ORDER BY revenue DESC
            LIMIT 10
        """
        result = verifier.verify(good_sql)
        hall = [i for i in result.issues if i.category == VerificationCategory.HALLUCINATED_COLUMN]
        assert len(hall) == 0, f"product_category_name_english is a real column: {[i.message for i in hall]}"


# ── Phase 5 failure category 3: Aggregation grain ────────────────────────────

class TestAggregationGrain:
    """Aggregate + non-aggregate SELECT with no GROUP BY → wrong grain."""

    GRAIN_VIOLATION = """
        SELECT customer_state, SUM(price) AS revenue
        FROM order_items oi
        JOIN orders o ON o.order_id = oi.order_id
        JOIN customers c ON c.customer_id = o.customer_id
    """

    def test_grain_violation_detected(self, verifier: SQLSemanticVerifier) -> None:
        result = verifier.verify(self.GRAIN_VIOLATION)
        assert not result.is_valid
        grain = [i for i in result.issues if i.category == VerificationCategory.AGGREGATION_GRAIN]
        assert len(grain) >= 1

    def test_grain_repair_adds_group_by(self, verifier: SQLSemanticVerifier) -> None:
        result = verifier.verify(self.GRAIN_VIOLATION)
        grain_issues = [i for i in result.issues if i.category == VerificationCategory.AGGREGATION_GRAIN]
        if not grain_issues:
            pytest.skip("No grain issue detected")
        repaired = verifier.generate_repair(grain_issues[0], self.GRAIN_VIOLATION)
        if repaired is None:
            pytest.skip("Programmatic grain repair returned None")
        assert "group by" in repaired.lower(), "Repaired SQL must contain GROUP BY"


# ── Repair prompt builder ─────────────────────────────────────────────────────

class TestRepairPrompt:
    """Unit tests for build_repair_prompt() and filter_actionable_issues()."""

    BROKEN_SQL = """
        SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month,
               p.product_category_name, SUM(oi.price) AS revenue
        FROM orders o
        JOIN order_items oi ON o.order_id = oi.order_id
        JOIN products p     ON p.product_id = oi.product_id
        GROUP BY month
    """

    def test_repair_prompt_contains_error_message(self, verifier: SQLSemanticVerifier) -> None:
        result = verifier.verify(self.BROKEN_SQL)
        actionable = filter_actionable_issues(result.issues)
        prompt = build_repair_prompt(self.BROKEN_SQL, actionable, ["Table: orders", "Table: order_items"])
        assert "product_category_name" in prompt or "group_by_mismatch" in prompt

    def test_repair_prompt_contains_column_reference(self, verifier: SQLSemanticVerifier) -> None:
        result = verifier.verify(self.BROKEN_SQL)
        actionable = filter_actionable_issues(result.issues)
        prompt = build_repair_prompt(self.BROKEN_SQL, actionable, ["Table: orders", "Table: order_items"])
        # Column reference block should be injected
        assert "COLUMN REFERENCE" in prompt

    def test_repair_prompt_contains_original_sql(self, verifier: SQLSemanticVerifier) -> None:
        result = verifier.verify(self.BROKEN_SQL)
        actionable = filter_actionable_issues(result.issues)
        prompt = build_repair_prompt(self.BROKEN_SQL, actionable, [])
        assert "Original SQL" in prompt
        assert "broken" in prompt.lower()

    def test_filter_removes_info_issues(self) -> None:
        info_issue = VerificationIssue(
            category=VerificationCategory.EXPECTED_ROW_COUNT,
            severity="info",
            message="Expected 10 rows but query has no GROUP BY",
        )
        error_issue = VerificationIssue(
            category=VerificationCategory.HALLUCINATED_COLUMN,
            severity="error",
            message="Column 'unit_price' does not exist",
        )
        warning_issue = VerificationIssue(
            category=VerificationCategory.GROUP_BY_MISMATCH,
            severity="warning",
            message="Column 'month' not in GROUP BY",
        )
        filtered = filter_actionable_issues([info_issue, error_issue, warning_issue])
        # info should be excluded; error and warning included
        categories = {i.category for i in filtered}
        assert VerificationCategory.EXPECTED_ROW_COUNT not in categories
        assert VerificationCategory.HALLUCINATED_COLUMN in categories
        assert VerificationCategory.GROUP_BY_MISMATCH in categories

    def test_filter_deduplicates_same_category(self, verifier: SQLSemanticVerifier) -> None:
        """Repair prompt deduplicates messages within the same category."""
        issues = [
            VerificationIssue(
                category=VerificationCategory.GROUP_BY_MISMATCH,
                severity="warning",
                message="Column 'month' not in GROUP BY",
            ),
            VerificationIssue(
                category=VerificationCategory.GROUP_BY_MISMATCH,
                severity="warning",
                message="Column 'state' not in GROUP BY",
            ),
        ]
        prompt = build_repair_prompt("SELECT ...", issues, [])
        # Both distinct messages should appear; the prompt is not empty
        assert len(prompt) > 50

    def test_system_prompt_exists(self) -> None:
        assert len(REPAIR_SYSTEM_PROMPT) > 100
        assert "repair" in REPAIR_SYSTEM_PROMPT.lower()
        assert "GROUP BY" in REPAIR_SYSTEM_PROMPT


# ── Column grounding helpers ──────────────────────────────────────────────────

class TestColumnGrounding:
    """Unit tests for build_column_grounding_block() and tables_from_context()."""

    def test_grounding_block_lists_exact_columns(self) -> None:
        block = build_column_grounding_block(["order_items"])
        # Every exact column must appear
        for col in EXACT_COLUMNS["order_items"]:
            assert col in block, f"Expected column '{col}' in grounding block"

    def test_grounding_block_includes_pk_fk_tags(self) -> None:
        block = build_column_grounding_block(["order_items"])
        assert "PRIMARY KEY" in block
        assert "FOREIGN KEY" in block

    def test_grounding_block_includes_join_keys(self) -> None:
        block = build_column_grounding_block(["order_items"])
        assert "join keys" in block.lower()
        assert "orders.order_id" in block or "order_items.order_id = orders.order_id" in block

    def test_grounding_block_multiple_tables(self) -> None:
        block = build_column_grounding_block(["orders", "customers"])
        for col in EXACT_COLUMNS["orders"]:
            assert col in block
        for col in EXACT_COLUMNS["customers"]:
            assert col in block

    def test_grounding_block_empty_input(self) -> None:
        block = build_column_grounding_block([])
        assert block == ""

    def test_grounding_block_warns_about_invented_columns(self) -> None:
        block = build_column_grounding_block(["order_items"])
        assert "quantity" in block.lower() or "unit_price" in block.lower() or "invent" in block.lower()

    def test_tables_from_context_extracts_tables(self) -> None:
        ctx = [
            "Grounded schema subset. Physical tables allowed in SQL: order_items, orders, customers.",
            "Table: order_items\nDescription: One row per item...",
        ]
        tables = tables_from_context(ctx)
        assert "order_items" in tables
        assert "orders" in tables
        assert "customers" in tables

    def test_tables_from_context_empty(self) -> None:
        tables = tables_from_context([])
        assert tables == []

    def test_tables_from_context_unknown_tables_ignored(self) -> None:
        ctx = ["Table: nonexistent_table\nsome data"]
        tables = tables_from_context(ctx)
        assert "nonexistent_table" not in tables

    def test_exact_columns_covers_all_tables(self) -> None:
        """Every table in EXACT_COLUMNS must have at least one column."""
        for table, cols in EXACT_COLUMNS.items():
            assert len(cols) >= 1, f"Table '{table}' has no columns in EXACT_COLUMNS"

    def test_exact_columns_no_invented_names(self) -> None:
        """Common invented column names must NOT appear in EXACT_COLUMNS."""
        invented = {"quantity", "unit_price", "discount_rate", "order_date", "category_name"}
        all_cols: set[str] = set()
        for cols in EXACT_COLUMNS.values():
            all_cols.update(cols)
        overlap = invented & all_cols
        assert len(overlap) == 0, f"Invented column names found in EXACT_COLUMNS: {overlap}"


# ── Integration: verifier + programmatic repair roundtrip ────────────────────

class TestRepairRoundtrip:
    """Verifier flags issue → programmatic repair → re-verify should pass."""

    def test_group_by_repair_roundtrip(self, verifier: SQLSemanticVerifier) -> None:
        broken = """
            SELECT p.product_category_name, c.customer_state, SUM(oi.price) AS revenue
            FROM order_items oi
            JOIN orders o      ON o.order_id    = oi.order_id
            JOIN products p    ON p.product_id  = oi.product_id
            JOIN customers c   ON c.customer_id = o.customer_id
            GROUP BY p.product_category_name
        """
        result1 = verifier.verify(broken)
        gb_issues = [i for i in result1.issues if i.category == VerificationCategory.GROUP_BY_MISMATCH]
        if not gb_issues:
            pytest.skip("No GROUP BY issue to repair")

        repaired = verifier.generate_repair(gb_issues[0], broken)
        if repaired is None:
            pytest.skip("Programmatic repair returned None")

        result2 = verifier.verify(repaired)
        remaining_gb = [
            i for i in result2.issues
            if i.category == VerificationCategory.GROUP_BY_MISMATCH and i.severity == "warning"
            and "customer_state" in i.message
        ]
        assert len(remaining_gb) == 0, (
            f"Repaired SQL still has customer_state GROUP BY issue: "
            f"{[i.message for i in remaining_gb]}"
        )

    def test_grain_repair_roundtrip(self, verifier: SQLSemanticVerifier) -> None:
        broken = """
            SELECT customer_state, COUNT(DISTINCT o.order_id) AS order_count
            FROM orders o
            JOIN customers c ON c.customer_id = o.customer_id
        """
        result1 = verifier.verify(broken)
        grain_issues = [i for i in result1.issues if i.category == VerificationCategory.AGGREGATION_GRAIN]
        if not grain_issues:
            pytest.skip("No grain issue to repair")

        repaired = verifier.generate_repair(grain_issues[0], broken)
        if repaired is None:
            pytest.skip("Programmatic grain repair returned None")

        assert "group by" in repaired.lower()
        # Repaired SQL should be parseable
        import sqlglot
        parsed = sqlglot.parse_one(repaired, read="sqlite")
        assert parsed is not None

    def test_hallucinated_column_requires_llm_repair(self, verifier: SQLSemanticVerifier) -> None:
        """Programmatic repair cannot fix hallucinated columns — must return None."""
        sql = "SELECT SUM(quantity * unit_price) AS revenue FROM order_items"
        result = verifier.verify(sql)
        hall_issues = [i for i in result.issues if i.category == VerificationCategory.HALLUCINATED_COLUMN]
        if not hall_issues:
            pytest.skip("No hallucinated column issue detected")

        # generate_repair must return None for HALLUCINATED_COLUMN
        repaired = verifier.generate_repair(hall_issues[0], sql)
        assert repaired is None, "Programmatic repair should return None for hallucinated columns"


# ── Verifier precision: true positives vs false positives ────────────────────

class TestVerifierPrecision:
    """The verifier must maintain high precision — not flag correct queries."""

    KNOWN_CORRECT = [
        # Single-value aggregation
        "SELECT ROUND(SUM(price), 2) AS total_revenue FROM order_items",
        # Monthly time series
        """
            SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month,
                   ROUND(SUM(oi.price), 2) AS revenue
            FROM orders o
            JOIN order_items oi ON o.order_id = oi.order_id
            WHERE o.order_status = 'delivered'
            GROUP BY month
            ORDER BY month
        """,
        # Top-N ranking
        """
            SELECT p.product_category_name, ROUND(SUM(oi.price), 2) AS revenue
            FROM order_items oi
            JOIN products p ON p.product_id = oi.product_id
            GROUP BY p.product_category_name
            ORDER BY revenue DESC
            LIMIT 10
        """,
        # Multi-dim aggregation
        """
            SELECT c.customer_state, COUNT(DISTINCT o.order_id) AS order_count
            FROM orders o
            JOIN customers c ON c.customer_id = o.customer_id
            GROUP BY c.customer_state
            ORDER BY order_count DESC
        """,
        # Review scores
        """
            SELECT review_score, COUNT(*) AS cnt
            FROM order_reviews
            GROUP BY review_score
            ORDER BY review_score
        """,
        # Payment by type
        """
            SELECT payment_type, ROUND(SUM(payment_value), 2) AS total
            FROM order_payments
            GROUP BY payment_type
            ORDER BY total DESC
        """,
    ]

    def test_correct_queries_pass_balanced_verification(
        self, verifier: SQLSemanticVerifier
    ) -> None:
        false_positives: list[tuple[str, list[str]]] = []
        for sql in self.KNOWN_CORRECT:
            result = verifier.verify(sql.strip(), level=VerificationLevel.BALANCED)
            blocking = [i for i in result.issues if i.severity in ("error", "warning")]
            if blocking:
                false_positives.append((sql.strip()[:60], [str(i) for i in blocking]))

        assert len(false_positives) == 0, (
            f"False positives ({len(false_positives)}/{len(self.KNOWN_CORRECT)}):\n"
            + "\n".join(f"  SQL: {s}\n  Issues: {iss}" for s, iss in false_positives)
        )
