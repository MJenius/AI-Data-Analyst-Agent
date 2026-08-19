"""Unit Tests for Failure Taxonomy and Error Analysis."""

import pytest

from agent_platform.experiments.failure_taxonomy import (
    FailureCategory,
    FailureClassifier,
    analyze_sql_ast_diff,
    format_taxonomy_markdown_report,
    generate_taxonomy_summary,
)


def test_sql_ast_diff():
    expected_sql = "SELECT SUM(price) FROM order_items WHERE price > 50 GROUP BY product_id;"
    actual_sql = "SELECT AVG(price) FROM order_items JOIN fake_table ON order_items.id = fake_table.id;"

    diff = analyze_sql_ast_diff(expected_sql, actual_sql)
    assert "fake_table" in diff.hallucinated_tables
    assert diff.aggregation_mismatch  # SUM vs AVG
    assert diff.where_predicate_mismatch  # WHERE present in expected, absent in actual
    assert diff.has_group_by_expected and not diff.has_group_by_actual


def test_failure_classifier_categories():
    classifier = FailureClassifier()

    # Success case
    e_succ = {"query_id": "q1", "equivalent_match": True, "actual_sql": "SELECT 1"}
    d_succ = classifier.classify(e_succ)
    assert d_succ.primary_failure == FailureCategory.SUCCESS

    # Provider rate limit
    e_rate = {"query_id": "q2", "error": "HTTP 429 Too Many Requests: Rate limit exceeded", "is_provider_error": True}
    d_rate = classifier.classify(e_rate)
    assert d_rate.primary_failure == FailureCategory.INFRA_RATE_LIMITED

    # Non-existent column
    e_col = {"query_id": "q3", "error": "sqlite3.OperationalError: no such column: invalid_col"}
    d_col = classifier.classify(e_col)
    assert d_col.primary_failure == FailureCategory.SCHEMA_HALLUCINATED_COLUMN

    # Dialect error
    e_func = {
        "query_id": "q4",
        "error": "syntax error",
        "actual_sql": "SELECT EXTRACT(year FROM order_purchase_timestamp) FROM orders;",
        "expected_sql": "SELECT strftime('%Y', order_purchase_timestamp) FROM orders;",
    }
    d_func = classifier.classify(e_func)
    assert d_func.primary_failure == FailureCategory.SQL_DIALECT_INCOMPATIBILITY

    # Semantic aggregation mismatch
    e_agg = {
        "query_id": "q5",
        "sql_execution_success": True,
        "equivalent_match": False,
        "actual_sql": "SELECT COUNT(price) FROM order_items;",
        "expected_sql": "SELECT SUM(price) FROM order_items;",
    }
    d_agg = classifier.classify(e_agg)
    assert d_agg.primary_failure == FailureCategory.SEMANTIC_AGGREGATION_MISMATCH


def test_taxonomy_summary_and_report():
    classifier = FailureClassifier()
    entries = [
        {"query_id": "q1", "equivalent_match": True, "category": "Sales"},
        {"query_id": "q2", "error": "no such column: abc", "category": "Sales"},
        {"query_id": "q3", "error": "HTTP 429", "is_provider_error": True, "category": "Logistics"},
    ]
    diagnostics = [classifier.classify(e) for e in entries]
    summary = generate_taxonomy_summary(diagnostics)

    assert summary["total_analyzed"] == 3
    assert "schema_hallucinated_column" in summary["failure_counts"]

    md = format_taxonomy_markdown_report(summary)
    assert "Scientific Failure Taxonomy" in md
    assert "Schema Hallucinated Column" in md
