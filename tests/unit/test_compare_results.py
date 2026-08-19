"""Unit tests for the corrected compare_results module.

Covers:
- Row permutation invariance (multiset semantics)
- Positional column semantics (preventing over-permissive column swaps)
- Numeric tolerance (rounding to 2 decimal places)
- Duplicate row handling with exact counts
- Semantic column alias invariance (different aliases with same projected values -> match)
- String normalization (case, whitespace)
- None values
- Genuine mismatches
"""

from __future__ import annotations

import pytest

from agent_platform.experiments.compare_results import (
    NUMERIC_TOLERANCE_DECIMALS,
    _canonicalize_row_tuple,
    _canonicalize_value,
    compare_results,
)


# ── Value canonicalization ────────────────────────────────────────────────────

class TestCanonicalizeValue:
    def test_none(self):
        assert _canonicalize_value(None) is None

    def test_int_becomes_float(self):
        assert _canonicalize_value(42) == 42.0

    def test_float_rounded(self):
        assert _canonicalize_value(3.14159) == 3.14

    def test_float_boundary(self):
        result = _canonicalize_value(0.005)
        assert result == round(0.005, NUMERIC_TOLERANCE_DECIMALS)

    def test_string_stripped_lowered(self):
        assert _canonicalize_value("  Hello World  ") == "hello world"

    def test_empty_string(self):
        assert _canonicalize_value("") == ""


# ── Row canonicalization ──────────────────────────────────────────────────────

class TestCanonicalizeRowTuple:
    def test_dict_projection(self):
        row = {"state": "SP", "revenue": 100.456}
        assert _canonicalize_row_tuple(row) == ("sp", 100.46)

    def test_tuple_projection(self):
        row = ("SP", 100.456)
        assert _canonicalize_row_tuple(row) == ("sp", 100.46)

    def test_column_positions_matter(self):
        """Positional column order matters: ('SP', 100) != (100, 'SP')."""
        row_a = {"col1": "SP", "col2": 100}
        row_b = {"col1": 100, "col2": "SP"}
        assert _canonicalize_row_tuple(row_a) != _canonicalize_row_tuple(row_b)


# ── compare_results: core cases ──────────────────────────────────────────────

class TestCompareResults:
    def test_both_empty(self):
        result = compare_results([], [])
        assert result == {"exact_match": True, "equivalent_match": True, "row_count_match": True}

    def test_actual_empty_expected_nonempty(self):
        result = compare_results([], [{"a": 1}])
        assert result == {"exact_match": False, "equivalent_match": False, "row_count_match": False}

    def test_actual_nonempty_expected_empty(self):
        result = compare_results([{"a": 1}], [])
        assert result == {"exact_match": False, "equivalent_match": False, "row_count_match": False}

    def test_exact_match_identical(self):
        rows = [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]
        result = compare_results(rows, rows.copy())
        assert result["exact_match"] is True
        assert result["equivalent_match"] is True

    def test_row_permutation_equivalent(self):
        """Swapping row order must still yield equivalent_match=True."""
        actual = [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]
        expected = [{"a": 2, "b": "y"}, {"a": 1, "b": "x"}]
        result = compare_results(actual, expected)
        assert result["exact_match"] is False  # order differs
        assert result["equivalent_match"] is True  # multiset matches

    def test_row_permutation_three_rows(self):
        actual = [{"v": 10}, {"v": 20}, {"v": 30}]
        expected = [{"v": 30}, {"v": 10}, {"v": 20}]
        result = compare_results(actual, expected)
        assert result["equivalent_match"] is True

    def test_numeric_within_tolerance(self):
        actual = [{"revenue": 123.456}]
        expected = [{"revenue": 123.459}]
        result = compare_results(actual, expected)
        assert result["equivalent_match"] is True

    def test_numeric_outside_tolerance(self):
        actual = [{"revenue": 123.45}]
        expected = [{"revenue": 123.46}]
        result = compare_results(actual, expected)
        assert result["equivalent_match"] is False

    def test_int_float_equivalence(self):
        actual = [{"count": 100}]
        expected = [{"count": 100.0}]
        result = compare_results(actual, expected)
        assert result["equivalent_match"] is True

    def test_duplicate_rows_same_count(self):
        actual = [{"a": 1}, {"a": 1}, {"a": 2}]
        expected = [{"a": 2}, {"a": 1}, {"a": 1}]
        result = compare_results(actual, expected)
        assert result["equivalent_match"] is True

    def test_duplicate_rows_different_count(self):
        actual = [{"a": 1}, {"a": 1}, {"a": 2}]
        expected = [{"a": 1}, {"a": 2}, {"a": 2}]
        result = compare_results(actual, expected)
        assert result["equivalent_match"] is False

    def test_semantic_column_alias_invariance(self):
        """Column aliases can differ (e.g., total_sellers vs distinct_seller_count) if projected values match."""
        actual = [{"distinct_seller_count": 3095}]
        expected = [{"total_sellers": 3095}]
        result = compare_results(actual, expected)
        assert result["exact_match"] is False
        assert result["equivalent_match"] is True

    def test_column_position_swap_not_equivalent(self):
        """Swapped column positions (state, count) vs (count, state) are NOT equivalent."""
        actual = [{"col1": "SP", "col2": 100}]
        expected = [{"col1": 100, "col2": "SP"}]
        result = compare_results(actual, expected)
        assert result["equivalent_match"] is False

    def test_string_case_insensitive(self):
        actual = [{"name": "São Paulo"}]
        expected = [{"name": "são paulo"}]
        result = compare_results(actual, expected)
        assert result["equivalent_match"] is True

    def test_string_whitespace_stripped(self):
        actual = [{"city": "  Rio  "}]
        expected = [{"city": "Rio"}]
        result = compare_results(actual, expected)
        assert result["equivalent_match"] is True

    def test_genuine_value_mismatch(self):
        actual = [{"a": 1, "b": "x"}]
        expected = [{"a": 1, "b": "y"}]
        result = compare_results(actual, expected)
        assert result["exact_match"] is False
        assert result["equivalent_match"] is False

    def test_different_row_count(self):
        actual = [{"a": 1}, {"a": 2}]
        expected = [{"a": 1}]
        result = compare_results(actual, expected)
        assert result["row_count_match"] is False
        assert result["equivalent_match"] is False

    def test_none_values_match(self):
        actual = [{"a": None}]
        expected = [{"a": None}]
        result = compare_results(actual, expected)
        assert result["equivalent_match"] is True

    def test_none_vs_string(self):
        actual = [{"a": None}]
        expected = [{"a": "none"}]
        result = compare_results(actual, expected)
        assert result["equivalent_match"] is False
