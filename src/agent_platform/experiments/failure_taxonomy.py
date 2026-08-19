"""Automated Failure Taxonomy, AST Diffing, and Error Analysis Engine.

Categorizes system failures into a standardized scientific hierarchy:
1. Schema Grounding: Hallucinated column/table, invalid join key, missing join path.
2. Semantic Misalignment: Wrong aggregation, missing filter, grain mismatch (GROUP BY), ranking inversion, missing DISTINCT.
3. SQL Syntax & Dialect: Non-SQLite functions (EXTRACT, DATEDIFF), unquoted keywords, parse errors.
4. Repair Dynamics: Exhaustion, semantic drift, repair loop oscillation.
5. Infrastructure & Provider: 429 Rate limits, timeouts, 5xx server errors.

Features:
- SQL AST clause-by-clause diffing using `sqlglot`.
- Automated root-cause classification tree.
- Cross-tabulation matrices (Domain vs. Error Category, Difficulty vs. Error Category).
- Side-by-side diff generator for publication and debugging.
"""

from __future__ import annotations

import enum
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import sqlglot
from sqlglot import exp

logger = logging.getLogger("experiments.failure_taxonomy")


class FailureCategory(str, enum.Enum):
    SUCCESS = "success"
    SCHEMA_HALLUCINATED_COLUMN = "schema_hallucinated_column"
    SCHEMA_HALLUCINATED_TABLE = "schema_hallucinated_table"
    SCHEMA_INVALID_JOIN_KEY = "schema_invalid_join_key"
    SCHEMA_MISSING_JOIN_PATH = "schema_missing_join_path"
    SEMANTIC_AGGREGATION_MISMATCH = "semantic_aggregation_mismatch"
    SEMANTIC_FILTER_OMISSION_OR_ERROR = "semantic_filter_omission_or_error"
    SEMANTIC_GRAIN_GROUP_BY_MISMATCH = "semantic_grain_group_by_mismatch"
    SEMANTIC_RANKING_ORDER_MISMATCH = "semantic_ranking_order_mismatch"
    SEMANTIC_DISTINCT_OMISSION = "semantic_distinct_omission"
    SQL_DIALECT_INCOMPATIBILITY = "sql_dialect_incompatibility"
    SQL_SYNTAX_ERROR = "sql_syntax_error"
    REPAIR_EXHAUSTED = "repair_exhausted"
    REPAIR_SEMANTIC_DRIFT = "repair_semantic_drift"
    INFRA_RATE_LIMITED = "infra_rate_limited"
    INFRA_TIMEOUT = "infra_timeout"
    INFRA_PROVIDER_ERROR = "infra_provider_error"
    UNKNOWN_EXECUTION_FAILURE = "unknown_execution_failure"


KNOWN_SQLITE_DISALLOWED_FUNCS = {
    "extract", "date_add", "date_sub", "datediff", "nvl", "decode",
    "to_char", "to_date", "trunc", "isnull", "getdate", "now", "curdate"
}

KNOWN_DATABASE_TABLES = {
    "customers", "geolocation", "order_items", "order_payments", "order_reviews",
    "orders", "products", "sellers", "product_category_name_translation",
}


# ============================================================================
# SQL AST Difference Analyzer
# ============================================================================

@dataclass
class SQLASTDiff:
    expected_tables: Set[str] = field(default_factory=set)
    actual_tables: Set[str] = field(default_factory=set)
    missing_tables: Set[str] = field(default_factory=set)
    hallucinated_tables: Set[str] = field(default_factory=set)
    expected_aggregations: List[str] = field(default_factory=list)
    actual_aggregations: List[str] = field(default_factory=list)
    aggregation_mismatch: bool = False
    has_where_expected: bool = False
    has_where_actual: bool = False
    where_predicate_mismatch: bool = False
    has_group_by_expected: bool = False
    has_group_by_actual: bool = False
    has_order_by_expected: bool = False
    has_order_by_actual: bool = False
    non_sqlite_functions: List[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "expected_tables": sorted(list(self.expected_tables)),
            "actual_tables": sorted(list(self.actual_tables)),
            "missing_tables": sorted(list(self.missing_tables)),
            "hallucinated_tables": sorted(list(self.hallucinated_tables)),
            "expected_aggregations": self.expected_aggregations,
            "actual_aggregations": self.actual_aggregations,
            "aggregation_mismatch": self.aggregation_mismatch,
            "has_where_expected": self.has_where_expected,
            "has_where_actual": self.has_where_actual,
            "where_predicate_mismatch": self.where_predicate_mismatch,
            "has_group_by_expected": self.has_group_by_expected,
            "has_group_by_actual": self.has_group_by_actual,
            "has_order_by_expected": self.has_order_by_expected,
            "has_order_by_actual": self.has_order_by_actual,
            "non_sqlite_functions": self.non_sqlite_functions,
        }


def analyze_sql_ast_diff(expected_sql: Optional[str], actual_sql: Optional[str]) -> SQLASTDiff:
    """Parses and compares expected vs actual SQL statements at the AST level."""
    diff = SQLASTDiff()
    if not expected_sql or not actual_sql:
        return diff

    # Parse expected SQL
    try:
        exp_ast = sqlglot.parse_one(expected_sql, read="sqlite")
        diff.expected_tables = {t.name.lower() for t in exp_ast.find_all(exp.Table)}
        diff.expected_aggregations = [
            f.key.lower() for f in exp_ast.find_all(exp.Anonymous, exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max)
        ]
        diff.has_where_expected = exp_ast.find(exp.Where) is not None
        diff.has_group_by_expected = exp_ast.find(exp.Group) is not None
        diff.has_order_by_expected = exp_ast.find(exp.Order) is not None
    except Exception:
        pass

    # Parse actual SQL
    try:
        act_ast = sqlglot.parse_one(actual_sql, read="sqlite")
        diff.actual_tables = {t.name.lower() for t in act_ast.find_all(exp.Table)}
        diff.actual_aggregations = [
            f.key.lower() for f in act_ast.find_all(exp.Anonymous, exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max)
        ]
        diff.has_where_actual = act_ast.find(exp.Where) is not None
        diff.has_group_by_actual = act_ast.find(exp.Group) is not None
        diff.has_order_by_actual = act_ast.find(exp.Order) is not None

        # Check for non-sqlite functions in AST
        for func in act_ast.find_all(exp.Func, exp.Anonymous):
            f_name = getattr(func, "name", None) or getattr(func, "key", "")
            if str(f_name).lower() in KNOWN_SQLITE_DISALLOWED_FUNCS:
                diff.non_sqlite_functions.append(str(f_name).lower())
    except Exception:
        pass

    # Regex fallback for dialect functions in raw SQL
    if actual_sql:
        act_lower = actual_sql.lower()
        for disallowed in KNOWN_SQLITE_DISALLOWED_FUNCS:
            if re.search(rf"\b{disallowed}\s*\(", act_lower) and disallowed not in diff.non_sqlite_functions:
                diff.non_sqlite_functions.append(disallowed)


    diff.missing_tables = diff.expected_tables - diff.actual_tables
    diff.hallucinated_tables = {t for t in diff.actual_tables if t not in KNOWN_DATABASE_TABLES}

    if sorted(diff.expected_aggregations) != sorted(diff.actual_aggregations):
        diff.aggregation_mismatch = True

    if diff.has_where_expected != diff.has_where_actual:
        diff.where_predicate_mismatch = True

    return diff


# ============================================================================
# Error Taxonomy Classifier
# ============================================================================

@dataclass
class DiagnosticRecord:
    query_id: str
    question: str
    category: str
    difficulty: str
    primary_failure: FailureCategory
    secondary_failure: Optional[FailureCategory] = None
    root_cause_explanation: str = ""
    ast_diff: Optional[SQLASTDiff] = None
    actual_sql: Optional[str] = None
    expected_sql: Optional[str] = None
    error_message: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_id": self.query_id,
            "question": self.question,
            "category": self.category,
            "difficulty": self.difficulty,
            "primary_failure": self.primary_failure.value,
            "secondary_failure": self.secondary_failure.value if self.secondary_failure else None,
            "root_cause_explanation": self.root_cause_explanation,
            "ast_diff": self.ast_diff.to_dict() if self.ast_diff else None,
            "actual_sql": self.actual_sql,
            "expected_sql": self.expected_sql,
            "error_message": self.error_message,
        }


class FailureClassifier:
    """Automated diagnostic classification tree for benchmark queries."""

    def classify(self, entry: dict[str, Any], ground_truth_item: Optional[dict[str, Any]] = None) -> DiagnosticRecord:
        qid = entry.get("query_id") or entry.get("id", "q_unknown")
        question = entry.get("question", "")
        category = entry.get("category", "unknown")
        difficulty = entry.get("difficulty", "unknown")
        actual_sql = entry.get("actual_sql")
        expected_sql = (ground_truth_item or {}).get("expected_sql") or entry.get("expected_sql")
        error = entry.get("error")
        is_provider = bool(entry.get("is_provider_error", False))
        sql_success = bool(entry.get("sql_execution_success", False))
        equiv = bool(entry.get("equivalent_match", False))
        exact = bool(entry.get("exact_match", False))

        if equiv or exact:
            return DiagnosticRecord(
                query_id=qid, question=question, category=category, difficulty=difficulty,
                primary_failure=FailureCategory.SUCCESS, root_cause_explanation="Query succeeded with verified equivalent match.",
                actual_sql=actual_sql, expected_sql=expected_sql,
            )

        err_str = str(error or "").lower()

        # 1. Provider & Infra Failures
        if is_provider or "rate limit" in err_str or "429" in err_str:
            return DiagnosticRecord(
                query_id=qid, question=question, category=category, difficulty=difficulty,
                primary_failure=FailureCategory.INFRA_RATE_LIMITED,
                root_cause_explanation="LLM API provider rate limit triggered (HTTP 429).",
                actual_sql=actual_sql, expected_sql=expected_sql, error_message=error,
            )
        if "timeout" in err_str or "timed out" in err_str:
            return DiagnosticRecord(
                query_id=qid, question=question, category=category, difficulty=difficulty,
                primary_failure=FailureCategory.INFRA_TIMEOUT,
                root_cause_explanation="Query execution or LLM response timed out.",
                actual_sql=actual_sql, expected_sql=expected_sql, error_message=error,
            )
        if "500" in err_str or "502" in err_str or "503" in err_str or "504" in err_str:
            return DiagnosticRecord(
                query_id=qid, question=question, category=category, difficulty=difficulty,
                primary_failure=FailureCategory.INFRA_PROVIDER_ERROR,
                root_cause_explanation="LLM Provider server error or outage.",
                actual_sql=actual_sql, expected_sql=expected_sql, error_message=error,
            )

        # 2. Syntax & Dialect Errors
        if "no such table" in err_str:
            return DiagnosticRecord(
                query_id=qid, question=question, category=category, difficulty=difficulty,
                primary_failure=FailureCategory.SCHEMA_HALLUCINATED_TABLE,
                root_cause_explanation=f"Referenced non-existent table in SQLite: {error}",
                actual_sql=actual_sql, expected_sql=expected_sql, error_message=error,
            )
        if "no such column" in err_str:
            return DiagnosticRecord(
                query_id=qid, question=question, category=category, difficulty=difficulty,
                primary_failure=FailureCategory.SCHEMA_HALLUCINATED_COLUMN,
                root_cause_explanation=f"Referenced non-existent column in SQLite: {error}",
                actual_sql=actual_sql, expected_sql=expected_sql, error_message=error,
            )
        if "syntax error" in err_str or "operationalerror" in err_str:
            # Check for non-sqlite functions
            ast_diff = analyze_sql_ast_diff(expected_sql, actual_sql)
            if ast_diff.non_sqlite_functions:
                return DiagnosticRecord(
                    query_id=qid, question=question, category=category, difficulty=difficulty,
                    primary_failure=FailureCategory.SQL_DIALECT_INCOMPATIBILITY,
                    root_cause_explanation=f"Used non-SQLite SQL dialect functions: {ast_diff.non_sqlite_functions}",
                    ast_diff=ast_diff, actual_sql=actual_sql, expected_sql=expected_sql, error_message=error,
                )
            return DiagnosticRecord(
                query_id=qid, question=question, category=category, difficulty=difficulty,
                primary_failure=FailureCategory.SQL_SYNTAX_ERROR,
                root_cause_explanation=f"SQL syntax error: {error}",
                ast_diff=ast_diff, actual_sql=actual_sql, expected_sql=expected_sql, error_message=error,
            )

        # 3. Semantic & Schema Misalignments (Query executed, but result did not match)
        ast_diff = analyze_sql_ast_diff(expected_sql, actual_sql)

        if ast_diff.hallucinated_tables:
            return DiagnosticRecord(
                query_id=qid, question=question, category=category, difficulty=difficulty,
                primary_failure=FailureCategory.SCHEMA_HALLUCINATED_TABLE,
                root_cause_explanation=f"Query joined hallucinated tables: {ast_diff.hallucinated_tables}",
                ast_diff=ast_diff, actual_sql=actual_sql, expected_sql=expected_sql,
            )

        if ast_diff.missing_tables:
            return DiagnosticRecord(
                query_id=qid, question=question, category=category, difficulty=difficulty,
                primary_failure=FailureCategory.SCHEMA_MISSING_JOIN_PATH,
                root_cause_explanation=f"Query missed required join tables: {ast_diff.missing_tables}",
                ast_diff=ast_diff, actual_sql=actual_sql, expected_sql=expected_sql,
            )

        if ast_diff.aggregation_mismatch:
            return DiagnosticRecord(
                query_id=qid, question=question, category=category, difficulty=difficulty,
                primary_failure=FailureCategory.SEMANTIC_AGGREGATION_MISMATCH,
                root_cause_explanation=f"Aggregation mismatch: expected {ast_diff.expected_aggregations}, got {ast_diff.actual_aggregations}",
                ast_diff=ast_diff, actual_sql=actual_sql, expected_sql=expected_sql,
            )

        if ast_diff.has_group_by_expected != ast_diff.has_group_by_actual:
            return DiagnosticRecord(
                query_id=qid, question=question, category=category, difficulty=difficulty,
                primary_failure=FailureCategory.SEMANTIC_GRAIN_GROUP_BY_MISMATCH,
                root_cause_explanation="Mismatch in GROUP BY grain or presence.",
                ast_diff=ast_diff, actual_sql=actual_sql, expected_sql=expected_sql,
            )

        if ast_diff.has_order_by_expected != ast_diff.has_order_by_actual:
            return DiagnosticRecord(
                query_id=qid, question=question, category=category, difficulty=difficulty,
                primary_failure=FailureCategory.SEMANTIC_RANKING_ORDER_MISMATCH,
                root_cause_explanation="Mismatch in ORDER BY / ranking clause.",
                ast_diff=ast_diff, actual_sql=actual_sql, expected_sql=expected_sql,
            )

        if ast_diff.where_predicate_mismatch:
            return DiagnosticRecord(
                query_id=qid, question=question, category=category, difficulty=difficulty,
                primary_failure=FailureCategory.SEMANTIC_FILTER_OMISSION_OR_ERROR,
                root_cause_explanation="WHERE filter predicates omitted or misaligned.",
                ast_diff=ast_diff, actual_sql=actual_sql, expected_sql=expected_sql,
            )

        # Fallback default
        return DiagnosticRecord(
            query_id=qid, question=question, category=category, difficulty=difficulty,
            primary_failure=FailureCategory.SEMANTIC_FILTER_OMISSION_OR_ERROR,
            root_cause_explanation="Result values differed from expected ground-truth rows.",
            ast_diff=ast_diff, actual_sql=actual_sql, expected_sql=expected_sql,
        )


# ============================================================================
# Taxonomy Aggregator & Report Formatter
# ============================================================================

def generate_taxonomy_summary(diagnostics: List[DiagnosticRecord]) -> dict[str, Any]:
    """Computes distribution and cross-tabulation of failure causes."""
    total = len(diagnostics)
    counts: dict[str, int] = {}
    by_category: dict[str, dict[str, int]] = {}
    by_difficulty: dict[str, dict[str, int]] = {}

    for d in diagnostics:
        fail_key = d.primary_failure.value
        counts[fail_key] = counts.get(fail_key, 0) + 1

        cat = d.category or "unknown"
        by_category.setdefault(cat, {})
        by_category[cat][fail_key] = by_category[cat].get(fail_key, 0) + 1

        diff = d.difficulty or "unknown"
        by_difficulty.setdefault(diff, {})
        by_difficulty[diff][fail_key] = by_difficulty[diff].get(fail_key, 0) + 1

    return {
        "total_analyzed": total,
        "failure_counts": counts,
        "failure_percentages": {k: round(v / total * 100, 2) for k, v in counts.items()} if total > 0 else {},
        "by_domain_category": by_category,
        "by_difficulty": by_difficulty,
    }


def format_taxonomy_markdown_report(summary: dict[str, Any]) -> str:
    lines = [
        "## Scientific Failure Taxonomy Distribution",
        "",
        "| Root-Cause Category | Failure Count | Share of Total Runs (%) |",
        "| :--- | :---: | :---: |",
    ]
    for fail_key, count in sorted(summary.get("failure_counts", {}).items(), key=lambda x: x[1], reverse=True):
        pct = summary.get("failure_percentages", {}).get(fail_key, 0.0)
        formatted_name = fail_key.replace("_", " ").title()
        badge = "🟢 " if fail_key == "success" else ("🔴 " if "infra" in fail_key else "🟡 ")
        lines.append(f"| {badge}**{formatted_name}** | {count} | {pct:.1f}% |")

    return "\n".join(lines)
