"""Shared result comparison logic for benchmark evaluation.

Equivalent Match Semantics:
- **Row-order invariant**: Result rows are compared as multisets (using collections.Counter),
  so row ordering differences (e.g., from un-ordered SELECT queries or tie-breaking in ORDER BY)
  do not cause false negatives.
- **Positional Column Preservation**: Within each row, column values are compared by their
  projection position: (v_1, v_2, ..., v_k). This ensures that (state='SP', count=100) is
  never confused with (state=100, count='SP'), preventing over-permissive matching while
  allowing semantic column aliases (e.g., AS total_revenue vs AS revenue).
- **Value Normalization**:
  - Floating point numbers are rounded to NUMERIC_TOLERANCE_DECIMALS (2 decimal places).
  - Integers and floats of equal value (e.g., 100 vs 100.0) are treated as equivalent.
  - Strings are stripped of leading/trailing whitespace and lowercased.
  - None values only match None.
- **Multiset Multiplicity**: Duplicate rows are tracked with exact counts:
  {row_A: 2, row_B: 1} != {row_A: 1, row_B: 2}.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

# Numeric tolerance: values are rounded to this many decimal places before comparison.
NUMERIC_TOLERANCE_DECIMALS: int = 2


def _canonicalize_value(value: Any) -> Any:
    """Normalize a single cell value for comparison.

    - int/float -> rounded float
    - str -> stripped, lowercased
    - None -> None
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return round(float(value), NUMERIC_TOLERANCE_DECIMALS)
    return str(value).strip().lower()


def _canonicalize_row_tuple(row: dict[str, Any] | tuple | list) -> tuple[Any, ...]:
    """Convert a row to a canonical positional tuple of normalized values.

    If row is a dict, values are taken in dictionary iteration (projection) order.
    If row is a tuple/list, elements are taken in positional order.
    """
    if isinstance(row, dict):
        return tuple(_canonicalize_value(v) for v in row.values())
    return tuple(_canonicalize_value(v) for v in row)


def compare_results(
    actual_rows: list[dict[str, Any]] | list[tuple],
    expected_rows: list[dict[str, Any]] | list[tuple],
) -> dict[str, Any]:
    """Compare two result sets for exact and equivalent match.

    Returns a dict with:
      - ``exact_match``: strict equality (original dicts/tuples, original order).
      - ``equivalent_match``: row-multiset equivalence under value normalization.
      - ``row_count_match``: whether row counts agree.
    """
    # --- Trivial cases ---------------------------------------------------------
    if not actual_rows and not expected_rows:
        return {"exact_match": True, "equivalent_match": True, "row_count_match": True}
    if not actual_rows or not expected_rows:
        return {"exact_match": False, "equivalent_match": False, "row_count_match": False}

    # --- Exact match (strict, order-sensitive) ---------------------------------
    exact_match = actual_rows == expected_rows

    # --- Row count gate --------------------------------------------------------
    row_count_match = len(actual_rows) == len(expected_rows)

    # --- Equivalent match (row-multiset, order-invariant) ----------------------
    if not row_count_match:
        equivalent = False
    else:
        actual_tuples = [_canonicalize_row_tuple(r) for r in actual_rows]
        expected_tuples = [_canonicalize_row_tuple(r) for r in expected_rows]
        equivalent = Counter(actual_tuples) == Counter(expected_tuples)

    return {
        "exact_match": exact_match,
        "equivalent_match": equivalent or exact_match,
        "row_count_match": row_count_match,
    }
