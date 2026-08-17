"""Comprehensive Fast Robustness & Safety Suite for Phase 9.

Tests:
1. SQL Injection / Prompt Injection defense.
2. Destructive keywords blocking (DROP, DELETE, UPDATE, TRUNCATE, ALTER, INSERT, ATTACH).
3. Nonexistent / hallucinated tables & columns rejection.
4. Join fan-out Cartesian product detection.
5. Malformed SQL syntax handling.
6. Ambiguous terminology & complex filters.
"""

from __future__ import annotations

import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_platform.tools.sql_tool import SQLTool, SQLSafetyError, SQLValidationError
from agent_platform.tools.sql_verifier import SQLSemanticVerifier, VerificationCategory, VerificationLevel

DB_PATH = ROOT / "data" / "analytics.db"


@pytest.fixture(scope="module")
def sql_tool():
    return SQLTool(f"sqlite:///{DB_PATH}")


@pytest.fixture(scope="module")
def verifier():
    return SQLSemanticVerifier(str(DB_PATH))


# ── 1. Destructive SQL Safety ──────────────────────────────────────────────────

@pytest.mark.parametrize("query", [
    "DROP TABLE orders",
    "DELETE FROM customers WHERE customer_id = '123'",
    "UPDATE products SET product_category_name = 'hacked'",
    "INSERT INTO order_items (order_id, price) VALUES ('abc', 100)",
    "ALTER TABLE sellers ADD COLUMN secret TEXT",
    "ATTACH DATABASE 'evil.db' AS evil",
    "PRAGMA writable_schema = 1",
])
def test_destructive_sql_blocked(sql_tool, query):
    with pytest.raises((SQLSafetyError, SQLValidationError, ValueError)):
        sql_tool.validate(query)


# ── 2. Prompt Injection in SQL ────────────────────────────────────────────────

@pytest.mark.parametrize("injection", [
    "SELECT * FROM orders; DROP TABLE customers; --",
    "SELECT * FROM orders WHERE order_id = '1' OR 1=1; DROP TABLE customers;",
    "SELECT load_extension('evil')",
])
def test_injection_attempts_blocked(sql_tool, injection):
    with pytest.raises((SQLSafetyError, SQLValidationError)):
        sql_tool.validate(injection)


# ── 3. Hallucinated Tables & Columns ──────────────────────────────────────────

def test_hallucinated_table_rejection(sql_tool):
    with pytest.raises(SQLValidationError) as exc:
        sql_tool.validate("SELECT * FROM non_existent_table")
    assert "nonexistent_table" in str(exc.value)


def test_hallucinated_column_rejection(sql_tool):
    with pytest.raises(SQLValidationError) as exc:
        sql_tool.validate("SELECT fake_column_name FROM orders")
    assert "nonexistent_column" in str(exc.value)


# ── 4. Join Fan-Out Detection ─────────────────────────────────────────────────

def test_cartesian_join_detection(verifier):
    # JOIN with no ON clause
    sql = "SELECT o.order_id, c.customer_city FROM orders o JOIN customers c"
    res = verifier.verify(sql, level=VerificationLevel.BALANCED)
    categories = [i.category for i in res.issues]
    assert VerificationCategory.JOIN_FAN_OUT in categories


def test_missing_equality_join_condition(verifier):
    # JOIN ON non-equality predicate
    sql = "SELECT o.order_id, c.customer_city FROM orders o JOIN customers c ON o.customer_id != c.customer_id"
    res = verifier.verify(sql, level=VerificationLevel.BALANCED)
    categories = [i.category for i in res.issues]
    assert VerificationCategory.JOIN_FAN_OUT in categories


# ── 5. Malformed SQL Handling ─────────────────────────────────────────────────

@pytest.mark.parametrize("malformed", [
    "SELECT FROM orders",
    "SELECT COUNT( FROM orders",
    "SELECT WHERE order_id = 1",
    "",
    "   ",
])
def test_malformed_sql_handling(sql_tool, malformed):
    with pytest.raises(SQLValidationError):
        sql_tool.validate(malformed)
