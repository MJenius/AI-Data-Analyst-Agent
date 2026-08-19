"""SQL Semantic Verifier â€” result-level validation for aggregation grain,
GROUP BY correctness, join fan-out, duplicate-row detection, and metric
consistency.  Used as a pre-acceptance checkpoint in the Phase 5 pipeline.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import sqlglot
from sqlglot import exp


logger = logging.getLogger(__name__)


# â”€â”€ enums & dataclasses â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class VerificationLevel(Enum):
    """Controls which issue severities block acceptance."""
    STRICT     = "strict"      # block on errors + warnings
    BALANCED   = "balanced"    # block on errors + warnings (same as STRICT at this stage)
    PERMISSIVE = "permissive"  # block on errors only


class VerificationCategory(Enum):
    GROUP_BY_MISMATCH    = "group_by_mismatch"
    AGGREGATION_GRAIN    = "aggregation_grain"
    JOIN_FAN_OUT         = "join_fan_out"
    DUPLICATE_DETECTION  = "duplicate_detection"
    EXPECTED_ROW_COUNT   = "expected_row_count"
    METRIC_INCONSISTENCY = "metric_inconsistency"
    HALLUCINATED_COLUMN  = "hallucinated_column"
    # ── Phase 8: plan-alignment categories ─────────────────────────────
    METRIC_MISMATCH         = "metric_mismatch"
    FILTER_MISMATCH         = "filter_mismatch"
    TIME_GRAIN_MISMATCH     = "time_grain_mismatch"
    GROUP_BY_GRAIN_MISMATCH = "group_by_grain_mismatch"
    RANKING_MISMATCH        = "ranking_mismatch"
    ENTITY_MISMATCH         = "entity_mismatch"
    JOIN_PATH_MISMATCH      = "join_path_mismatch"
    RESULT_SHAPE_MISMATCH   = "result_shape_mismatch"


@dataclass(slots=True)
class VerificationIssue:
    category:         VerificationCategory
    severity:         str          # "error" | "warning" | "info"
    message:          str
    sql_context:      str | None = None
    suggested_repair: str | None = None

    def __str__(self) -> str:
        return f"[{self.severity}] {self.category.value}: {self.message}"


@dataclass
class VerificationResult:
    sql:               str
    is_valid:          bool
    issues:            list[VerificationIssue] = field(default_factory=list)
    row_count_expected: int | None = None
    row_count_actual:   int | None = None


# â”€â”€ helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_AGG_TYPES = (exp.Avg, exp.Count, exp.Sum, exp.Max, exp.Min)

def _is_aggregate(node: exp.Expression) -> bool:
    """Return True if `node` is or contains an aggregate function."""
    if isinstance(node, _AGG_TYPES):
        return True
    if isinstance(node, exp.Anonymous):
        return node.name.lower() in {"sum", "count", "avg", "max", "min",
                                      "count_if", "approx_count_distinct",
                                      "group_concat", "string_agg"}
    return bool(node.find(*_AGG_TYPES))


def _select_non_agg_exprs(select_node: exp.Select) -> list[exp.Expression]:
    """Return SELECT expressions that are not aggregates (dimensions)."""
    result: list[exp.Expression] = []
    for expr in select_node.expressions:
        inner = expr.this if isinstance(expr, exp.Alias) else expr
        if not _is_aggregate(inner):
            result.append(inner)
    return result


# Keep old name for backward-compat with tests
def _select_non_agg_columns(select_node: exp.Select) -> list[exp.Expression]:
    return _select_non_agg_exprs(select_node)


def _group_by_names(expression: exp.Expression) -> set[str]:
    """Collect lower-cased column names in GROUP BY clauses."""
    names: set[str] = set()
    for group in expression.find_all(exp.Group):
        for g in group.expressions:
            if isinstance(g, exp.Column):
                names.add(g.name.lower())
            elif isinstance(g, exp.Literal):
                # positional reference like GROUP BY 1
                names.add(g.this)
    return names


# ── Phase 8: plan keyword → schema evidence tables ─────────────────────────

_AGG_FAMILIES: dict[str, tuple[str, ...]] = {
    "sum":   ("sum",),
    "count": ("count", "count_if", "approx_count_distinct"),
    "avg":   ("avg", "mean"),
    "max":   ("max",),
    "min":   ("min",),
}

# dimension keyword → candidate physical columns (used for GROUP BY grain check)
_DIMENSION_COLUMN_MAP: dict[str, tuple[str, ...]] = {
    "state":       ("customer_state", "seller_state", "geolocation_state"),
    "customer_state": ("customer_state",),
    "seller_state": ("seller_state",),
    "region":      ("customer_state", "seller_state", "geolocation_state"),
    "category":    ("product_category_name", "product_category_name_english"),
    "categories":  ("product_category_name", "product_category_name_english"),
    "seller":      ("seller_id",),
    "sellers":     ("seller_id",),
    "payment":     ("payment_type",),
    "payments":    ("payment_type",),
    "review":      ("review_score",),
    "rating":      ("review_score",),
    "score":       ("review_score",),
    "customer":    ("customer_unique_id", "customer_id", "customer_state"),
    "customers":   ("customer_unique_id", "customer_id", "customer_state"),
    "product":     ("product_id", "product_category_name"),
    "products":    ("product_id", "product_category_name"),
    "status":      ("order_status",),
    "installment": ("payment_installments",),
    "day_of_week": ("order_purchase_timestamp",),
    "weekday":     ("order_purchase_timestamp",),
    "hour":        ("order_purchase_timestamp",),
}

_ENTITY_COLUMN_MAP: dict[str, tuple[str, ...]] = {
    "state":              ("customer_state", "seller_state", "geolocation_state"),
    "region":             ("customer_state", "seller_state", "geolocation_state"),
    "category":           ("product_category_name", "product_category_name_english"),
    "categories":         ("product_category_name", "product_category_name_english"),
    "seller":             ("seller_id",),
    "seller_id":          ("seller_id",),
    "payment_type":       ("payment_type",),
    "payment":            ("payment_type",),
    "review_score":       ("review_score",),
    "review":             ("review_score",),
    "rating":             ("review_score",),
    "customer_state":     ("customer_state",),
    "customer":           ("customer_unique_id", "customer_id", "customer_state"),
    "customers":          ("customer_unique_id", "customer_id", "customer_state"),
    "product":            ("product_id", "product_category_name"),
    "product_id":         ("product_id",),
    "product_category_name": ("product_category_name",),
}

_METRIC_COLUMN_HINTS: dict[str, tuple[str, ...]] = {
    "revenue":     ("price", "payment_value"),
    "sales":       ("price", "payment_value"),
    "gmv":         ("price",),
    "amount":      ("price", "payment_value"),
    "aov":         ("price",),
    "order value": ("price",),
    "payment":     ("payment_value",),
    "installment": ("payment_installments",),
    "review":      ("review_score",),
    "rating":      ("review_score",),
    "score":       ("review_score",),
    "delivery":    ("order_delivered_customer_date", "order_estimated_delivery_date"),
    "price":       ("price",),
}

_TIME_GRAIN_PATTERNS: dict[str, tuple[str, ...]] = {
    "year":    (r"%Y(?![-/])", r"substr\([^)]*,\s*1,\s*4\)"),
    "quarter": (r"%Q",),
    "month":   (r"%Y-%m(?!-|\d)", r"substr\([^)]*,\s*1,\s*7\)"),
    "week":    (r"%W", r"%U"),
    "weekday": (r"%a", r"%w", r"%u"),
    "day":     (r"%Y-%m-%d", r"\bdate\s*\("),
    "hour":    (r"%H",),
}

_TIME_GRAIN_KEYWORDS: dict[str, str] = {
    "year": "year", "yearly": "year", "annual": "year",
    "quarter": "quarter", "quarterly": "quarter",
    "month": "month", "monthly": "month", "per month": "month",
    "week": "week", "weekly": "week",
    "weekday": "weekday", "day_of_week": "weekday", "dayofweek": "weekday",
    "day": "day", "daily": "day", "per day": "day",
    "hour": "hour", "hourly": "hour", "hour_of_day": "hour", "hour_of_the_day": "hour",
    "over time": "month",
    "trend": "month", "trends": "month",
}

_FILTER_EVIDENCE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "order_status": (
        "delivered", "shipped", "invoiced", "canceled", "cancelled",
        "cancellation", "cancel", "completed", "status", "approved",
        "processing", "unavailable", "late",
    ),
    "order_purchase_timestamp": ("year", "since", "between", "from", "during"),
    "order_delivered_customer_date": ("deliver", "shipped"),
    "payment_type": ("payment", "method"),
    "review_score": ("review", "rating"),
    "customer_state": ("state", "region"),
    "seller_state": ("state", "region"),
}


# â”€â”€ main class â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class SQLSemanticVerifier:
    """Validates SQL queries for semantic correctness beyond syntax and schema.

    Checks:
    - GROUP BY completeness (non-aggregate SELECT columns must be in GROUP BY)
    - Aggregation grain (aggregate functions used without GROUP BY)
    - Join fan-out (JOINs without ON equality conditions)
    - Duplicate-row detection (actual row_count >> expected)
    - Expected result-shape (row count mismatch hints)
    - Metric consistency (NULL values in aggregate columns)
    """

    def __init__(self, database_path: str) -> None:
        self.database_path = database_path
        self.schema = self._load_schema()

    # â”€â”€ schema loading â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _load_schema(self) -> dict[str, dict[str, str]]:
        import sqlite3
        conn = sqlite3.connect(self.database_path)
        try:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            return {
                tbl: {row[1]: row[2] or "UNKNOWN"
                      for row in conn.execute(f'PRAGMA table_info("{tbl}")')}
                for (tbl,) in tables
            }
        finally:
            conn.close()

    # â”€â”€ public API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def verify(
        self,
        sql: str,
        execution_result:  dict[str, Any] | None = None,
        expected_result:   dict[str, Any] | None = None,
        level: VerificationLevel = VerificationLevel.BALANCED,
        query_plan: Any | None = None,
        question: str | None = None,
    ) -> VerificationResult:
        """Run comprehensive semantic verification.

        Parameters
        ----------
        sql:              Generated SQL (may be empty string).
        execution_result: Dict with ``success``, ``row_count``, ``rows``.
        expected_result:  Dict with ``row_count``, ``columns``, ``values``.
        level:            Controls which severities block acceptance.
        query_plan:       Optional QueryPlan (object or dict) to verify the
                          SQL against — checks metric, filters, time grain,
                          GROUP BY grain, ranking, entity, and join path
                          alignment (Phase 8).
        question:         Optional original question text, used to gate
                          filter-evidence so planner noise does not produce
                          false-positive repairs.

        Returns
        -------
        VerificationResult
        """
        if not sql or not sql.strip():
            return VerificationResult(sql=sql, is_valid=True, issues=[])

        try:
            tree = sqlglot.parse_one(sql, read="sqlite")
        except Exception as exc:
            return VerificationResult(
                sql=sql,
                is_valid=False,
                issues=[VerificationIssue(
                    category=VerificationCategory.GROUP_BY_MISMATCH,
                    severity="error",
                    message=f"SQL parse error: {exc}",
                )],
            )

        issues: list[VerificationIssue] = []
        issues += self._verify_column_existence(tree, sql)
        issues += self._verify_group_by(tree, sql)
        issues += self._verify_aggregation_grain(tree, sql)
        issues += self._verify_join_fanout(tree, sql)
        issues += self._verify_expected_result_shape(tree, expected_result)
        issues += self._verify_duplicate_pattern(execution_result, expected_result)
        issues += self._verify_metric_consistency(execution_result)
        issues += self._verify_plan_alignment(tree, sql, query_plan, question)
        issues += self._verify_result_shape(execution_result, expected_result)

        # Filter by level
        if level == VerificationLevel.PERMISSIVE:
            blocking = [i for i in issues if i.severity == "error"]
        else:  # BALANCED or STRICT
            blocking = [i for i in issues if i.severity in ("error", "warning")]

        return VerificationResult(
            sql=sql,
            is_valid=(len(blocking) == 0),
            issues=issues,  # return all issues for observability
            row_count_expected=expected_result.get("row_count") if expected_result else None,
            row_count_actual=execution_result.get("row_count") if execution_result else None,
        )

    # â”€â”€ individual checks â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _verify_column_existence(self, tree: exp.Expression, sql: str) -> list[VerificationIssue]:
        """Detect column references that do not exist in the live schema.

        Catches hallucinated column names (unit_price, quantity, discount_rate,
        order_date) that fail at SQLite runtime.  Runs before execution so the
        repair loop can intercept without a DB round-trip.

        False-positive avoidance:
        - Build alias→physical_table map so "p.category_name_english" resolves
          to products.category_name_english before the schema lookup.
        - Skip names that match a SELECT output alias (e.g. GROUP BY month where
          month is strftime(…) AS month).
        - Skip CTE-defined names.
        """
        if not self.schema:
            return []

        # ── skip schema-inspection queries ────────────────────────────────
        physical_tables = {
            (t.name or "").lower()
            for t in tree.find_all(exp.Table)
            if (t.name or "").lower() not in {"sqlite_master", "sqlite_schema"}
        }
        if not physical_tables:
            return []

        # ── alias → physical table map ────────────────────────────────────
        alias_to_table: dict[str, str] = {}
        for tbl_node in tree.find_all(exp.Table):
            physical = (tbl_node.name or "").lower()
            alias    = (tbl_node.alias or tbl_node.name or "").lower()
            if physical and physical in self.schema:
                alias_to_table[alias]    = physical
                alias_to_table[physical] = physical  # identity

        # ── SELECT output aliases and CTE names ──────────────────────────
        cte_names: set[str] = {
            cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)
        }
        select_aliases: set[str] = set()
        for select in tree.find_all(exp.Select):
            for expr in select.expressions:
                if isinstance(expr, exp.Alias):
                    select_aliases.add(expr.alias.lower())

        issues: list[VerificationIssue] = []
        seen_bad: set[str] = set()

        for col in tree.find_all(exp.Column):
            table_ref = (col.table or "").lower()
            col_name  = (col.name or "").lower()
            if not col_name:
                continue

            # Skip SELECT aliases, CTE-derived names.
            if col_name in select_aliases or col_name in cte_names:
                continue
            if table_ref in cte_names:
                continue

            if not table_ref:
                # Unqualified: flag only if absent from ALL physical tables.
                exists = any(
                    col_name in {c.lower() for c in tcols}
                    for tcols in self.schema.values()
                )
                if not exists:
                    if col_name not in seen_bad:
                        seen_bad.add(col_name)
                        issues.append(VerificationIssue(
                            category=VerificationCategory.HALLUCINATED_COLUMN,
                            severity="error",
                            message=(
                                f"Column '{col.name}' does not exist in any table — "
                                "likely a hallucinated column name"
                            ),
                            sql_context=sql[:200],
                            suggested_repair=(
                                "Replace with an exact column name from the COLUMN REFERENCE block"
                            ),
                        ))
            else:
                # Qualified: resolve alias to physical table first.
                physical = alias_to_table.get(table_ref)
                if physical is None:
                    # Unknown alias — let AST validator handle it.
                    continue
                tbl_schema = self.schema.get(physical)
                if tbl_schema is None:
                    continue
                if col_name not in {c.lower() for c in tbl_schema}:
                    key = f"{physical}.{col_name}"
                    if key not in seen_bad:
                        seen_bad.add(key)
                        issues.append(VerificationIssue(
                            category=VerificationCategory.HALLUCINATED_COLUMN,
                            severity="error",
                            message=(
                                f"Column '{col.table}.{col.name}' does not exist in "
                                f"table '{physical}' — valid columns: "
                                + ", ".join(sorted(tbl_schema.keys()))
                            ),
                            sql_context=sql[:200],
                            suggested_repair=(
                                f"Replace '{col.name}' with the correct column from '{physical}'"
                            ),
                        ))
        return issues


    def _verify_group_by(self, tree: exp.Expression, sql: str) -> list[VerificationIssue]:
        """Detect SELECT columns that are not in GROUP BY and not aggregated."""
        issues: list[VerificationIssue] = []
        gb_names = _group_by_names(tree)

        # Also collect SELECT aliases so GROUP BY alias-references are not flagged.
        select_aliases: set[str] = set()
        for select in tree.find_all(exp.Select):
            for expr in select.expressions:
                if isinstance(expr, exp.Alias):
                    select_aliases.add(expr.alias.lower())

        for select in tree.find_all(exp.Select):
            # Skip sub-selects that live inside aggregates
            non_agg_cols = _select_non_agg_columns(select)
            has_agg = any(_is_aggregate(e) for e in select.expressions)
            has_gb  = bool(select.find(exp.Group))

            if not (has_agg and has_gb):
                continue  # no aggregation context â€” GROUP BY not required

            for col in non_agg_cols:
                col_name = col.name.lower()
                # Skip empty names (computed expressions parsed without a bare name)
                if not col_name:
                    continue
                # Skip columns whose name matches a SELECT alias (already grouped by alias)
                if col_name in select_aliases and col_name in gb_names:
                    continue
                if col_name not in gb_names:
                    issues.append(VerificationIssue(
                        category=VerificationCategory.GROUP_BY_MISMATCH,
                        severity="warning",
                        message=(
                            f"Column '{col.name}' appears in SELECT but is not in "
                            "GROUP BY and is not aggregated â€” result grain may be wrong"
                        ),
                        sql_context=f"SELECT â€¦ {col.sql()} â€¦",
                        suggested_repair=f"Add '{col.name}' to GROUP BY or wrap in an aggregate",
                    ))
        return issues

    def _verify_aggregation_grain(self, tree: exp.Expression, sql: str) -> list[VerificationIssue]:
        """Warn when aggregate functions are used without any GROUP BY."""
        issues: list[VerificationIssue] = []
        for select in tree.find_all(exp.Select):
            has_agg = any(_is_aggregate(e) for e in select.expressions)
            has_gb  = bool(select.find(exp.Group))
            has_non_agg = bool(_select_non_agg_columns(select))
            # Only flag when there are non-aggregate dimension columns AND no GROUP BY
            if has_agg and not has_gb and has_non_agg:
                issues.append(VerificationIssue(
                    category=VerificationCategory.AGGREGATION_GRAIN,
                    severity="warning",
                    message=(
                        "Query mixes aggregate and non-aggregate SELECT columns without "
                        "GROUP BY â€” will collapse all rows into one (wrong grain)"
                    ),
                    sql_context=sql[:200],
                    suggested_repair="Add GROUP BY on all non-aggregate SELECT columns",
                ))
        return issues

    def _verify_join_fanout(self, tree: exp.Expression, sql: str) -> list[VerificationIssue]:
        """Detect JOINs with missing ON clauses or no equality condition."""
        issues: list[VerificationIssue] = []
        for join in tree.find_all(exp.Join):
            on_clause = join.args.get("on")
            if on_clause is None:
                issues.append(VerificationIssue(
                    category=VerificationCategory.JOIN_FAN_OUT,
                    severity="error",
                    message="JOIN has no ON clause â€” will produce a Cartesian product",
                    sql_context=sql[:200],
                    suggested_repair="Add an ON clause with an equality join condition",
                ))
            elif not list(on_clause.find_all(exp.EQ)):
                issues.append(VerificationIssue(
                    category=VerificationCategory.JOIN_FAN_OUT,
                    severity="warning",
                    message="JOIN ON clause has no equality predicate â€” possible Cartesian product",
                    sql_context=on_clause.sql(),
                    suggested_repair="Use an equality condition: ON a.id = b.id",
                ))
        return issues

    def _verify_expected_result_shape(
        self,
        tree: exp.Expression,
        expected_result: dict[str, Any] | None,
    ) -> list[VerificationIssue]:
        """Cross-check expected row count against GROUP BY cardinality estimate."""
        if not expected_result:
            return []
        expected_rc = expected_result.get("row_count")
        if expected_rc is None:
            return []

        issues: list[VerificationIssue] = []
        for group in tree.find_all(exp.Group):
            n_dims = len(group.expressions)
            # Very rough heuristic: each GROUP BY dim multiplies cardinality
            estimated_min = max(1, n_dims)
            estimated_max = n_dims * 1000
            if expected_rc > 1 and n_dims == 0:
                issues.append(VerificationIssue(
                    category=VerificationCategory.EXPECTED_ROW_COUNT,
                    severity="info",
                    message=(
                        f"Expected {expected_rc} rows but query has no GROUP BY â€” "
                        "will return at most 1 row"
                    ),
                    suggested_repair="Add GROUP BY to produce multiple rows",
                ))
        return issues

    def _verify_duplicate_pattern(
        self,
        execution_result: dict[str, Any] | None,
        expected_result:  dict[str, Any] | None,
    ) -> list[VerificationIssue]:
        """Flag when actual row count is far above or below expected."""
        if not execution_result or not expected_result:
            return []
        if not execution_result.get("success", True):
            return []

        actual   = execution_result.get("row_count", 0)
        expected = expected_result.get("row_count", 0)
        if actual <= 0 or expected <= 0:
            return []

        ratio = actual / expected
        issues: list[VerificationIssue] = []
        if ratio > 3.0:
            issues.append(VerificationIssue(
                category=VerificationCategory.DUPLICATE_DETECTION,
                severity="warning",
                message=(
                    f"Result contains {actual} rows but {expected} expected "
                    f"({ratio:.1f}Ã— too many) â€” possible Cartesian product or missing WHERE"
                ),
                suggested_repair="Check JOIN conditions and add WHERE filters to reduce duplicates",
            ))
        elif ratio < 0.25:
            issues.append(VerificationIssue(
                category=VerificationCategory.DUPLICATE_DETECTION,
                severity="warning",
                message=(
                    f"Result contains only {actual} rows but {expected} expected "
                    f"({ratio:.2f}Ã— too few) â€” possible over-filtering or missing JOIN"
                ),
                suggested_repair="Review WHERE filters and JOIN conditions",
            ))
        return issues

    def _verify_metric_consistency(
        self,
        execution_result: dict[str, Any] | None,
    ) -> list[VerificationIssue]:
        """Warn when aggregate columns return NULL."""
        if not execution_result or not execution_result.get("rows"):
            return []

        issues: list[VerificationIssue] = []
        first_row = execution_result["rows"][0]
        for col, val in first_row.items():
            if val is None:
                col_l = col.lower()
                if any(kw in col_l for kw in ("count", "sum", "total", "revenue", "amount")):
                    issues.append(VerificationIssue(
                        category=VerificationCategory.METRIC_INCONSISTENCY,
                        severity="warning",
                        message=(
                            f"Aggregate column '{col}' returned NULL â€” "
                            "possible no-match JOIN or all-NULL inputs"
                        ),
                        suggested_repair="Use COALESCE or verify JOIN conditions match data",
                    ))
        return issues

    # â”€â”€ repair helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    # ── Phase 8: plan-alignment checks ─────────────────────────────────────

    @staticmethod
    def _plan_value(plan: Any, key: str, default: Any = None) -> Any:
        """Read a field from a QueryPlan model or a plain dict."""
        if plan is None:
            return default
        if isinstance(plan, dict):
            return plan.get(key, default)
        return getattr(plan, key, default)

    @staticmethod
    def _collect_tables(tree: exp.Expression) -> set[str]:
        cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
        return {
            t.name.lower()
            for t in tree.find_all(exp.Table)
            if t.name.lower() not in cte_names
        }

    def _collect_sql_facts(self, tree: exp.Expression, sql: str) -> dict[str, Any]:
        aliases: dict[str, set[str]] = {}
        for select in tree.find_all(exp.Select):
            for expr in select.expressions:
                if isinstance(expr, exp.Alias):
                    cols = {c.name.lower() for c in expr.this.find_all(exp.Column)}
                    aliases[expr.alias.lower()] = cols or {expr.alias.lower()}
        group_cols: set[str] = set()
        for group in tree.find_all(exp.Group):
            for g in group.expressions:
                if isinstance(g, exp.Column):
                    group_cols.add(g.name.lower())
                elif isinstance(g, exp.Literal):
                    group_cols.add(str(g.this))
        agg_families: set[str] = set()
        for select in tree.find_all(exp.Select):
            for expr in select.expressions:
                agg_families.update(self._expression_agg_families(expr))
        all_columns = {c.name.lower() for c in tree.find_all(exp.Column)}
        return {
            "aliases": aliases,
            "group_cols": group_cols,
            "agg_families": agg_families,
            "columns": all_columns,
            "text": sql.lower(),
            "raw_text": sql,
        }

    def _expression_agg_families(self, expr: exp.Expression) -> set[str]:
        families: set[str] = set()
        for node in expr.walk():
            name = None
            if isinstance(node, exp.Anonymous):
                name = node.name.lower()
            elif isinstance(node, exp.Avg):
                name = "avg"
            elif isinstance(node, exp.Sum):
                name = "sum"
            elif isinstance(node, exp.Count):
                name = "count"
            elif isinstance(node, exp.Max):
                name = "max"
            elif isinstance(node, exp.Min):
                name = "min"
            if name:
                for family, members in _AGG_FAMILIES.items():
                    if name in members:
                        families.add(family)
        return families

    def _verify_plan_alignment(
        self,
        tree: exp.Expression,
        sql: str,
        query_plan: Any,
        question: str | None,
    ) -> list[VerificationIssue]:
        """Verify SQL semantics against the planned semantics (Phase 8).

        Only runs when a query plan is supplied AND the query touches real
        physical tables (schema-inspection steps are skipped).  Checks:
        join path, metric/aggregation, filters, time grain, GROUP BY grain,
        ranking/top-N, intended entity, and metric source column.
        """
        if not query_plan:
            return []
        tables = self._collect_tables(tree)
        if not (tables - {"sqlite_master", "sqlite_schema"}):
            return []
        facts = self._collect_sql_facts(tree, sql)
        question_lower = (question or "").lower()

        issues: list[VerificationIssue] = []
        issues += self._check_join_path(tables, query_plan)
        issues += self._check_metric(facts, query_plan)
        issues += self._check_metric_source(facts, query_plan)
        issues += self._check_filters(facts, query_plan, question_lower)
        issues += self._check_time_grain(facts["raw_text"], query_plan)
        issues += self._check_group_by_grain(facts, query_plan)
        issues += self._check_ranking(facts["text"], query_plan)
        issues += self._check_entity(facts, query_plan)
        return issues

    def _check_join_path(
        self,
        tables: set[str],
        query_plan: Any,
    ) -> list[VerificationIssue]:
        required = {
            t.lower()
            for t in (self._plan_value(query_plan, "required_tables") or [])
            if isinstance(t, str)
        }
        if not required:
            return []
        issues: list[VerificationIssue] = []
        for table in sorted(required - tables):
            issues.append(VerificationIssue(
                category=VerificationCategory.JOIN_PATH_MISMATCH,
                severity="error",
                message=(
                    f"Plan requires table '{table}' but the query never references it — "
                    "the join path is incomplete for the question's entities"
                ),
                sql_context=self._plan_value(query_plan, "intent") or "",
                suggested_repair=(
                    f"Add table '{table}' and its join key (see join keys in the COLUMN REFERENCE block)"
                ),
            ))
        for table in sorted(tables - required - {"sqlite_master", "sqlite_schema"}):
            issues.append(VerificationIssue(
                category=VerificationCategory.JOIN_PATH_MISMATCH,
                severity="warning",
                message=(
                    f"Query references table '{table}' which is not in the plan's required tables — "
                    "possible unnecessary join that changes the grain"
                ),
                suggested_repair=(
                    f"Remove table '{table}' and its JOIN unless it supplies a selected field, "
                    "filter, grouping, or metric"
                ),
            ))
        return issues

    @staticmethod
    def _plan_agg_family(aggregation: Any) -> set[str] | None:
        text = (aggregation or "").lower()
        if not text:
            return None
        if "sum" in text:
            return {"sum"}
        if "count" in text:
            return {"count"}
        if "avg" in text or "average" in text or "mean" in text:
            return {"avg"}
        if "max" in text:
            return {"max"}
        if "min" in text:
            return {"min"}
        return None  # e.g. median — not verifiable on SQLite

    def _check_metric(self, facts: dict[str, Any], query_plan: Any) -> list[VerificationIssue]:
        aggregation = self._plan_value(query_plan, "aggregation")
        metric_text = (self._plan_value(query_plan, "metric") or "").lower()
        family = self._plan_agg_family(aggregation)
        issues: list[VerificationIssue] = []
        if family:
            present = facts["agg_families"]
            if not present:
                issues.append(VerificationIssue(
                    category=VerificationCategory.METRIC_MISMATCH,
                    severity="error",
                    message=(
                        f"Plan requires {aggregation} aggregation for metric '{metric_text}' "
                        "but the query uses no aggregate function — the metric is not computed"
                    ),
                    suggested_repair=(
                        f"Apply {aggregation} to the correct metric column from the COLUMN REFERENCE block"
                    ),
                ))
            elif not (present & family):
                if family == {"avg"}:
                    composite = (
                        "avg" in present
                        or bool(re.search(r"\)\s*/\s*(?:count\s*\()", facts["text"]))
                    )
                    if not composite:
                        issues.append(VerificationIssue(
                            category=VerificationCategory.METRIC_MISMATCH,
                            severity="warning",
                            message=(
                                f"Plan expects AVG aggregation for '{metric_text}' but the query "
                                f"aggregates with {sorted(present)} — metric definition may differ"
                            ),
                            suggested_repair="Use AVG (or SUM/COUNT for a ratio metric) on the planned metric column",
                        ))
                else:
                    issues.append(VerificationIssue(
                        category=VerificationCategory.METRIC_MISMATCH,
                        severity="error",
                        message=(
                            f"Plan expects {aggregation} aggregation for '{metric_text}' but the "
                            f"query aggregates with {sorted(present)} — wrong metric or wrong aggregation"
                        ),
                        suggested_repair=f"Apply {aggregation} to the correct metric column",
                    ))
        hints: set[str] = set()
        for keyword, columns in _METRIC_COLUMN_HINTS.items():
            if re.search(rf"\b{re.escape(keyword)}\b", metric_text):
                hints.update(columns)
        if hints and not (hints & facts["columns"]):
            issues.append(VerificationIssue(
                category=VerificationCategory.METRIC_MISMATCH,
                severity="warning",
                message=(
                    f"Metric '{metric_text}' maps to column(s) {sorted(hints)} but the query "
                    "never references them — likely the wrong metric column"
                ),
                suggested_repair="Use the exact metric column from the COLUMN REFERENCE block",
            ))
        return issues

    def _check_metric_source(
        self,
        facts: dict[str, Any],
        query_plan: Any,
    ) -> list[VerificationIssue]:
        """Verify the SQL uses the correct physical column for the planned metric.

        Catches the critical payment_value vs price confusion: if the plan says
        metric_source_column='price' (revenue) but the SQL aggregates payment_value,
        or vice versa, flag as a metric mismatch error.
        """
        planned_source = self._plan_value(query_plan, "metric_source_column")
        if not planned_source:
            return []

        planned_source = planned_source.lower()
        sql_columns = facts["columns"]
        issues: list[VerificationIssue] = []

        # Define conflicting pairs — columns that are semantically different
        # and should never be substituted for each other.
        CONFLICTING_PAIRS: dict[str, str] = {
            "price": "payment_value",
            "payment_value": "price",
        }

        conflicting = CONFLICTING_PAIRS.get(planned_source)
        if conflicting and conflicting in sql_columns and planned_source not in sql_columns:
            issues.append(VerificationIssue(
                category=VerificationCategory.METRIC_MISMATCH,
                severity="error",
                message=(
                    f"Plan metric uses '{planned_source}' but SQL aggregates '{conflicting}' — "
                    "these are materially different measures (revenue vs payment). "
                    f"Replace '{conflicting}' with '{planned_source}' in the aggregate expression."
                ),
                suggested_repair=(
                    f"Replace '{conflicting}' with '{planned_source}' in the aggregate"
                ),
            ))

        return issues

    @staticmethod
    def _filter_has_question_evidence(column: str, question_lower: str) -> bool:
        if column == "order_purchase_timestamp":
            return bool(re.search(r"\b(19|20)\d{2}\b", question_lower))
        keywords = _FILTER_EVIDENCE_KEYWORDS.get(column)
        if not keywords:
            return False
        return any(k in question_lower for k in keywords)

    def _check_filters(
        self,
        facts: dict[str, Any],
        query_plan: Any,
        question_lower: str,
    ) -> list[VerificationIssue]:
        plan_filters = self._plan_value(query_plan, "filters") or []
        issues: list[VerificationIssue] = []
        schema_columns = {c.lower() for table_cols in self.schema.values() for c in table_cols}
        sql_years = set(re.findall(r"\b(?:19|20)\d{2}\b", facts["text"]))

        for planned_filter in plan_filters:
            if not isinstance(planned_filter, str) or not planned_filter.strip():
                continue
            pf_lower = planned_filter.lower()
            filter_columns = {
                col for col in schema_columns
                if re.search(rf"\b{col}\b", pf_lower)
            }
            planned_years = set(re.findall(r"\b(?:19|20)\d{2}\b", pf_lower))

            for column in filter_columns:
                if column in facts["columns"]:
                    continue
                if not self._filter_has_question_evidence(column, question_lower):
                    continue  # planner noise without question support — skip
                issues.append(VerificationIssue(
                    category=VerificationCategory.FILTER_MISMATCH,
                    severity="error",
                    message=(
                        f"Plan applies a filter on column '{column}' but the query does not "
                        f"reference it — a required WHERE predicate is missing (planned: {planned_filter[:120]})"
                    ),
                    suggested_repair=(
                        f"Add a WHERE predicate on '{column}' using the filter value from the plan"
                    ),
                ))
            for year in sorted(planned_years):
                if year in sql_years:
                    continue
                if year not in question_lower:
                    continue  # planner-invented year — skip
                issues.append(VerificationIssue(
                    category=VerificationCategory.FILTER_MISMATCH,
                    severity="error",
                    message=(
                        f"Plan restricts results to year {year} but the query does not filter on "
                        f"{year} (years found in query: {sorted(sql_years) or 'none'}) — wrong time range"
                    ),
                    suggested_repair=f"Add a WHERE predicate restricting the order timestamp to year {year}",
                ))
        return issues

    def _check_time_grain(self, sql_text: str, query_plan: Any) -> list[VerificationIssue]:
        planned: set[str] = set()
        for group in (self._plan_value(query_plan, "group_by") or []):
            if not isinstance(group, str):
                continue
            key = group.strip().lower()
            if key in _TIME_GRAIN_KEYWORDS:
                planned.add(_TIME_GRAIN_KEYWORDS[key])
            else:
                # Longest keyword wins so "hour_of_day" resolves to hour, not day.
                matches = [
                    (keyword, grain)
                    for keyword, grain in _TIME_GRAIN_KEYWORDS.items()
                    if keyword in key
                ]
                if matches:
                    _, grain = max(matches, key=lambda m: len(m[0]))
                    planned.add(grain)
        if not planned:
            return []
        actual = {
            grain
            for grain, patterns in _TIME_GRAIN_PATTERNS.items()
            if any(re.search(pattern, sql_text, re.IGNORECASE) for pattern in patterns)
        }
        issues: list[VerificationIssue] = []
        for grain in sorted(planned):
            if grain in actual:
                continue
            if actual:
                message = (
                    f"Plan requires {grain}-level time grain but the query truncates time to "
                    f"{sorted(actual)} — time grain mismatch"
                )
            else:
                message = (
                    f"Plan requires {grain}-level time grain but the query applies no time "
                    "truncation — results are not bucketed over time"
                )
            issues.append(VerificationIssue(
                category=VerificationCategory.TIME_GRAIN_MISMATCH,
                severity="error",
                message=message,
                suggested_repair=(
                    f"Truncate orders.order_purchase_timestamp to {grain} grain "
                    "(e.g. strftime('%Y-%m', ...) for month)"
                ),
            ))
        return issues

    def _check_group_by_grain(self, facts: dict[str, Any], query_plan: Any) -> list[VerificationIssue]:
        planned = [
            g for g in (self._plan_value(query_plan, "group_by") or [])
            if isinstance(g, str)
        ]
        if not planned:
            return []
        issues: list[VerificationIssue] = []
        if facts["agg_families"] and not facts["group_cols"]:
            issues.append(VerificationIssue(
                category=VerificationCategory.GROUP_BY_GRAIN_MISMATCH,
                severity="error",
                message=(
                    f"Plan requires grouping by {planned} but the query has no GROUP BY — "
                    "aggregation grain is wrong"
                ),
                suggested_repair=f"Add GROUP BY on the planned dimension(s): {', '.join(planned)}",
            ))
            return issues

        alias_columns: set[str] = set()
        for group in facts["group_cols"]:
            alias_columns |= facts["aliases"].get(group, set())

        for dimension in planned:
            key = dimension.strip().lower()
            if any(kw in key for kw in _TIME_GRAIN_KEYWORDS):
                continue  # handled by the time-grain check
            candidates: set[str] = set()
            for keyword, columns in _DIMENSION_COLUMN_MAP.items():
                if re.search(rf"\b{re.escape(keyword)}\b", key):
                    candidates.update(columns)
            if not candidates:
                continue  # unknown dimension text — no concrete evidence
            matched = bool(facts["group_cols"] & candidates) or bool(alias_columns & candidates)
            if not matched:
                issues.append(VerificationIssue(
                    category=VerificationCategory.GROUP_BY_GRAIN_MISMATCH,
                    severity="error",
                    message=(
                        f"Plan groups by '{dimension}' (expected column(s) {sorted(candidates)}) "
                        f"but the query's GROUP BY is {sorted(facts['group_cols']) or 'empty'} — "
                        "wrong grouping grain"
                    ),
                    suggested_repair=f"Group by {sorted(candidates)[0]}",
                ))
        return issues

    def _check_ranking(self, sql_text: str, query_plan: Any) -> list[VerificationIssue]:
        plan_limit = self._plan_value(query_plan, "limit")
        ordering = self._plan_value(query_plan, "ordering") or ""
        issues: list[VerificationIssue] = []
        limit_match = re.search(r"\blimit\s+(\d+)", sql_text)
        if isinstance(plan_limit, int):
            if not limit_match:
                issues.append(VerificationIssue(
                    category=VerificationCategory.RANKING_MISMATCH,
                    severity="error",
                    message=(
                        f"Plan requires a top-N LIMIT of {plan_limit} but the query has no LIMIT — "
                        "result is not ranked/truncated to the requested number of rows"
                    ),
                    suggested_repair=f"Append ORDER BY <metric> and LIMIT {plan_limit}",
                ))
            elif int(limit_match.group(1)) != plan_limit:
                issues.append(VerificationIssue(
                    category=VerificationCategory.RANKING_MISMATCH,
                    severity="error",
                    message=(
                        f"Plan requires LIMIT {plan_limit} but the query uses "
                        f"LIMIT {int(limit_match.group(1))}"
                    ),
                    suggested_repair=f"Change LIMIT to {plan_limit}",
                ))
        if ordering and "order by" in sql_text:
            tail = re.split(r"\blimit\b", sql_text.split("order by", 1)[1])[0]
            wants_desc = "desc" in ordering.lower()
            wants_asc = ("asc" in ordering.lower() and not wants_desc)
            has_desc = bool(re.search(r"\bdesc\b", tail))
            has_asc = bool(re.search(r"\basc\b", tail))
            if wants_desc and not has_desc and has_asc:
                issues.append(VerificationIssue(
                    category=VerificationCategory.RANKING_MISMATCH,
                    severity="warning",
                    message=(
                        f"Plan requires DESCENDING order ({ordering}) but the query orders ASC — "
                        "ranking direction is inverted"
                    ),
                    suggested_repair="Flip the ORDER BY direction to DESC",
                ))
            elif wants_asc and not has_asc and has_desc:
                issues.append(VerificationIssue(
                    category=VerificationCategory.RANKING_MISMATCH,
                    severity="warning",
                    message=(
                        f"Plan requires ASCENDING order ({ordering}) but the query orders DESC — "
                        "ranking direction is inverted"
                    ),
                    suggested_repair="Flip the ORDER BY direction to ASC",
                ))
        return issues

    def _check_entity(self, facts: dict[str, Any], query_plan: Any) -> list[VerificationIssue]:
        entity = (self._plan_value(query_plan, "entity") or "").lower()
        if not entity:
            return []
        candidates: set[str] = set()
        for keyword, columns in _ENTITY_COLUMN_MAP.items():
            if re.search(rf"\b{re.escape(keyword)}\b", entity):
                candidates.update(columns)
        if not candidates:
            return []
        referenced = facts["columns"] | {
            col for alias_cols in facts["aliases"].values() for col in alias_cols
        }
        if not (candidates & referenced):
            return [VerificationIssue(
                category=VerificationCategory.ENTITY_MISMATCH,
                severity="warning",
                message=(
                    f"Plan analyzes entity '{entity}' (expected column(s) {sorted(candidates)}) "
                    "but the query never references them — intended entities are missing"
                ),
                suggested_repair=(
                    f"Reference the entity column(s) {sorted(candidates)[:2]} in SELECT or GROUP BY"
                ),
            )]
        return []

    def _verify_result_shape(
        self,
        execution_result: dict[str, Any] | None,
        expected_result: dict[str, Any] | None,
    ) -> list[VerificationIssue]:
        """Cross-check expected result shape (columns and row count) against the
        executed result.  Only meaningful when expected data is available."""
        if not execution_result or not expected_result:
            return []
        expected_cols = {str(c).lower() for c in expected_result.get("columns", [])}
        actual_cols = {str(c).lower() for c in execution_result.get("columns", [])}
        issues: list[VerificationIssue] = []
        if expected_cols and actual_cols and not (expected_cols & actual_cols):
            issues.append(VerificationIssue(
                category=VerificationCategory.RESULT_SHAPE_MISMATCH,
                severity="error",
                message=(
                    f"Result columns {sorted(actual_cols)} do not match the expected output "
                    f"shape {sorted(expected_cols)} — the query answers a different question"
                ),
                suggested_repair="Align SELECT output columns with the question's requested metric",
            ))
        if execution_result.get("success", True):
            expected_rows = expected_result.get("row_count")
            actual_rows = execution_result.get("row_count")
            if isinstance(expected_rows, int) and isinstance(actual_rows, int) and expected_rows > 0:
                ratio = actual_rows / expected_rows
                if ratio > 2.0 or ratio < 0.5:
                    issues.append(VerificationIssue(
                        category=VerificationCategory.RESULT_SHAPE_MISMATCH,
                        severity="warning",
                        message=(
                            f"Result has {actual_rows} rows but the expected shape has "
                            f"{expected_rows} ({ratio:.2f}x) — grain or LIMIT mismatch"
                        ),
                        suggested_repair="Check GROUP BY grain and LIMIT against the question's expected shape",
                    ))
        return issues

    def generate_repair(self, issue: VerificationIssue, sql: str) -> str | None:
        """Attempt a targeted SQL repair for the given issue.

        Returns repaired SQL string or None if automatic repair is not feasible.
        Hallucinated columns always return None (need LLM knowledge to pick the
        right replacement column).
        """
        if issue.category == VerificationCategory.GROUP_BY_MISMATCH:
            return self._repair_group_by(issue, sql)
        if issue.category == VerificationCategory.GROUP_BY_GRAIN_MISMATCH:
            return self._repair_group_by(issue, sql)
        if issue.category == VerificationCategory.RANKING_MISMATCH:
            return self._repair_ranking(issue, sql)
        if issue.category == VerificationCategory.JOIN_FAN_OUT:
            return None  # requires schema knowledge to infer correct FK
        if issue.category == VerificationCategory.AGGREGATION_GRAIN:
            return self._repair_grain(issue, sql)
        if issue.category == VerificationCategory.HALLUCINATED_COLUMN:
            return None  # LLM must pick the correct column name
        return None

    def _repair_group_by(self, issue: VerificationIssue, sql: str) -> str | None:
        match = re.search(r"'(\w+)'", issue.message)
        if not match:
            return None
        col = match.group(1)

        pos_gb = sql.lower().find("group by")
        if pos_gb == -1:
            pos_order = sql.lower().find("order by")
            if pos_order == -1:
                return None
            return f"{sql[:pos_order].rstrip()} GROUP BY {col} {sql[pos_order:]}"

        # Append to existing GROUP BY
        pos_after = pos_gb + len("group by")
        rest = sql[pos_after:]
        # Find end of GB clause (HAVING / ORDER / LIMIT / end)
        m = re.search(r"\b(having|order\s+by|limit)\b", rest, re.IGNORECASE)
        end = m.start() if m else len(rest)
        existing = rest[:end].strip()
        if col.lower() in existing.lower():
            return None  # already there
        new_gb = f"GROUP BY {existing}, {col}"
        return f"{sql[:pos_gb]}{new_gb} {rest[end:]}"

    def _repair_grain(self, issue: VerificationIssue, sql: str) -> str | None:
        # Find non-aggregate SELECT columns to build GROUP BY
        try:
            tree = sqlglot.parse_one(sql, read="sqlite")
        except Exception:
            return None
        for select in tree.find_all(exp.Select):
            non_agg = _select_non_agg_columns(select)
            if not non_agg:
                return None
            gb_cols = ", ".join(c.sql() for c in non_agg)
            pos_order = sql.lower().find("order by")
            if pos_order == -1:
                return f"{sql.rstrip().rstrip(';')} GROUP BY {gb_cols}"
            return f"{sql[:pos_order].rstrip()} GROUP BY {gb_cols} {sql[pos_order:]}"
        return None

    def _repair_ranking(self, issue: VerificationIssue, sql: str) -> str | None:
        match = re.search(r"LIMIT of (\d+)", issue.message)
        if not match:
            return None
        limit = match.group(1)
        return f"{sql.rstrip().rstrip(';')} LIMIT {limit}"
