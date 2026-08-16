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
    ) -> VerificationResult:
        """Run comprehensive semantic verification.

        Parameters
        ----------
        sql:              Generated SQL (may be empty string).
        execution_result: Dict with ``success``, ``row_count``, ``rows``.
        expected_result:  Dict with ``row_count``, ``columns``, ``values``.
        level:            Controls which severities block acceptance.

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

    def generate_repair(self, issue: VerificationIssue, sql: str) -> str | None:
        """Attempt a targeted SQL repair for the given issue.

        Returns repaired SQL string or None if automatic repair is not feasible.
        Hallucinated columns always return None (need LLM knowledge to pick the
        right replacement column).
        """
        if issue.category == VerificationCategory.GROUP_BY_MISMATCH:
            return self._repair_group_by(issue, sql)
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
        return f"{sql[:pos_gb]}{new_gb}{rest[end:]}"

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
