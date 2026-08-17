"""PlanValidator — deterministic pre-SQL validation for QueryPlan.

Validates the structured query plan against analytical rules, schema graphs,
and metric consistency BEFORE invoking expensive SQL generation.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from agent_platform.experiments.query_plan import QueryPlan, MetricType, ResultShape, CompositeMetric
from agent_platform.rag.ingestion.schema_context import (
    CANONICAL_PRIMARY_KEYS,
    EXACT_COLUMNS,
    JOIN_RELATIONSHIPS,
    TABLE_DESCRIPTIONS,
)

logger = logging.getLogger(__name__)

KNOWN_TABLES = set(TABLE_DESCRIPTIONS.keys())

# Flat set of all known column names per table
ALL_COLUMNS: dict[str, set[str]] = {
    table: set(cols) for table, cols in EXACT_COLUMNS.items()
}

# Build adjacency graph for schema relationships
SCHEMA_GRAPH: dict[str, dict[str, str]] = {}
for from_t, from_c, to_t, to_c, kind, note in JOIN_RELATIONSHIPS:
    if from_t not in SCHEMA_GRAPH:
        SCHEMA_GRAPH[from_t] = {}
    if to_t not in SCHEMA_GRAPH:
        SCHEMA_GRAPH[to_t] = {}
    SCHEMA_GRAPH[from_t][to_t] = f"{from_t}.{from_c} = {to_t}.{to_c}"
    SCHEMA_GRAPH[to_t][from_t] = f"{to_t}.{to_c} = {from_t}.{from_c}"

# Table → semantic concepts mapping for determining necessity
TABLE_CONCEPTS: dict[str, set[str]] = {
    "order_items": {"revenue", "price", "freight", "item", "sales", "gmv", "seller_id", "product_id", "aov", "average order value"},
    "orders": {"order", "status", "delivered", "canceled", "cancelled", "cancellation", "month", "trend", "time", "delay", "year", "timestamp", "date"},
    "customers": {"customer", "buyer", "customer_state", "customer_city", "repeat", "loyalty", "unique_id"},
    "products": {"product", "category", "weight", "dimension", "photo"},
    "order_payments": {"payment", "installment", "boleto", "credit_card", "voucher", "debit_card"},
    "order_reviews": {"review", "rating", "score", "satisfaction"},
    "sellers": {"seller", "seller_state", "seller_city"},
    "geolocation": {"geolocation", "zip", "density", "lat", "lng", "coordinate"},
    "product_category_name_translation": {"english", "translation", "category_english"},
}


class PlanValidationCategory(str, Enum):
    MISSING_METRIC = "missing_metric"
    MISSING_ENTITY = "missing_entity"
    MISSING_REQUIRED_TABLE = "missing_required_table"
    UNNECESSARY_TABLE = "unnecessary_table"
    DISCONNECTED_TABLES = "disconnected_tables"
    IMPOSSIBLE_JOIN = "impossible_join"
    MISSING_RANKING_LIMIT = "missing_ranking_limit"
    INVALID_AGGREGATION = "invalid_aggregation"
    MALFORMED_COMPOSITE_METRIC = "malformed_composite_metric"
    MISSING_TIME_GRAIN = "missing_time_grain"
    INCONSISTENT_FILTERS = "inconsistent_filters"
    INCOMPATIBLE_RESULT_SHAPE = "incompatible_result_shape"
    GROUPBY_CONSISTENCY = "groupby_consistency"


@dataclass(slots=True)
class PlanValidationIssue:
    category: PlanValidationCategory
    severity: str  # "error" | "warning" | "info"
    message: str
    suggested_repair: str | None = None

    def __str__(self) -> str:
        return f"[{self.severity}] {self.category.value}: {self.message}"


@dataclass
class PlanValidationResult:
    is_valid: bool
    issues: list[PlanValidationIssue] = field(default_factory=list)
    repaired_plan: QueryPlan | None = None


def find_minimum_join_path(tables: set[str] | list[str]) -> list[str]:
    """Find minimum join predicates connecting the given set of tables using BFS/Steiner tree heuristic."""
    tbls = list(dict.fromkeys(tables))
    if len(tbls) <= 1:
        return []

    # If only 2 tables and directly connected:
    if len(tbls) == 2:
        t1, t2 = tbls[0], tbls[1]
        if t2 in SCHEMA_GRAPH.get(t1, {}):
            return [SCHEMA_GRAPH[t1][t2]]
        # Check 1-hop intermediary
        for mid in SCHEMA_GRAPH.get(t1, {}):
            if t2 in SCHEMA_GRAPH.get(mid, {}):
                return [SCHEMA_GRAPH[t1][mid], SCHEMA_GRAPH[mid][t2]]

    # Connect all pairs via shortest paths
    connected_joins: list[str] = []
    visited_edges: set[str] = set()
    root = tbls[0]
    
    for target in tbls[1:]:
        # BFS from root to target
        queue: list[tuple[str, list[str]]] = [(root, [])]
        seen = {root}
        found_path: list[str] = []
        while queue:
            curr, path = queue.pop(0)
            if curr == target:
                found_path = path
                break
            for neighbor, pred in SCHEMA_GRAPH.get(curr, {}).items():
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append((neighbor, path + [pred]))
        for pred in found_path:
            edge_key = " AND ".join(sorted(pred.split(" = ")))
            if edge_key not in visited_edges:
                visited_edges.add(edge_key)
                connected_joins.append(pred)

    return connected_joins


def _tables_reachable_from(start: str, table_set: set[str]) -> set[str]:
    """BFS to find all tables reachable from start within the table_set via SCHEMA_GRAPH."""
    if start not in table_set:
        return set()
    visited = {start}
    queue = [start]
    while queue:
        curr = queue.pop(0)
        for neighbor in SCHEMA_GRAPH.get(curr, {}):
            if neighbor in table_set and neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)
    return visited


def _question_needs_table(question_lower: str, table: str) -> bool:
    """Check if the question text semantically requires a given table."""
    concepts = TABLE_CONCEPTS.get(table, set())
    return any(concept in question_lower for concept in concepts)


class PlanValidator:
    """Deterministic validator and automatic plan repairer for structured QueryPlans."""

    def __init__(self, known_tables: set[str] | None = None) -> None:
        self.known_tables = known_tables or KNOWN_TABLES

    def validate(self, plan: QueryPlan, question: str = "") -> PlanValidationResult:
        issues: list[PlanValidationIssue] = []
        repaired: QueryPlan = plan.model_copy(deep=True)
        q_low = question.lower()

        # ── 1. Metric check ──────────────────────────────────────────────────
        if not plan.metric or plan.metric.strip() == "":
            issues.append(
                PlanValidationIssue(
                    category=PlanValidationCategory.MISSING_METRIC,
                    severity="error",
                    message="Query plan has empty metric definition.",
                )
            )
            repaired.metric = "count"
            repaired.aggregation = "COUNT"

        # ── 2. Required tables: remove unknown ────────────────────────────────
        unknown_tables = set(plan.required_tables) - self.known_tables
        if unknown_tables:
            issues.append(
                PlanValidationIssue(
                    category=PlanValidationCategory.UNNECESSARY_TABLE,
                    severity="error",
                    message=f"Plan contains unknown physical tables: {unknown_tables}",
                )
            )
            repaired.required_tables = [t for t in plan.required_tables if t in self.known_tables]

        # ── 3. Minimum required tables: add missing ──────────────────────────
        needed_tables = set(repaired.required_tables)
        if any(k in q_low for k in ["revenue", "price", "freight", "item"]):
            needed_tables.add("order_items")
        if any(k in q_low for k in ["month", "trend", "status", "delivered", "canceled", "cancelled", "year", "delay"]):
            needed_tables.add("orders")
        if any(k in q_low for k in ["customer", "buyer"]) and not any(k in q_low for k in ["seller"]):
            if any(k in q_low for k in ["customer_state", "state", "city", "customer"]):
                needed_tables.add("customers")
        if any(k in q_low for k in ["product", "category"]):
            needed_tables.add("products")
        if any(k in q_low for k in ["payment", "installment"]):
            needed_tables.add("order_payments")
        if any(k in q_low for k in ["review", "rating", "score"]):
            needed_tables.add("order_reviews")
        if any(k in q_low for k in ["seller"]):
            needed_tables.add("sellers")

        # Bridge table insertion: if two tables need a bridge (e.g. customers ↔ order_items needs orders)
        if "customers" in needed_tables and "order_items" in needed_tables and "orders" not in needed_tables:
            needed_tables.add("orders")
        if "order_reviews" in needed_tables and "order_items" in needed_tables and "orders" not in needed_tables:
            needed_tables.add("orders")
        if "order_payments" in needed_tables and "order_items" in needed_tables and "orders" not in needed_tables:
            needed_tables.add("orders")
        if "sellers" in needed_tables and "orders" in needed_tables and "order_items" not in needed_tables:
            # sellers connect via order_items, not directly to orders
            if not any(k in q_low for k in ["item", "revenue", "price"]):
                needed_tables.add("order_items")

        missing_tables = needed_tables - set(repaired.required_tables)
        if missing_tables:
            issues.append(
                PlanValidationIssue(
                    category=PlanValidationCategory.MISSING_REQUIRED_TABLE,
                    severity="warning",
                    message=f"Plan missing tables strongly implied by question: {missing_tables}",
                )
            )
            repaired.required_tables = list(dict.fromkeys(repaired.required_tables + list(missing_tables)))

        # ── 4. Unnecessary table pruning ─────────────────────────────────────
        if len(repaired.required_tables) > 1:
            essential_tables: set[str] = set()
            for t in repaired.required_tables:
                if _question_needs_table(q_low, t):
                    essential_tables.add(t)
            # Also keep tables referenced by plan fields
            metric_lower = (repaired.metric or "").lower()
            for t in repaired.required_tables:
                if t in metric_lower:
                    essential_tables.add(t)
                if repaired.group_by and any(t in g for g in repaired.group_by):
                    essential_tables.add(t)
                if repaired.entities and any(t.replace("_", " ") in e.lower() or e.lower() in ALL_COLUMNS.get(t, set()) for e in repaired.entities):
                    essential_tables.add(t)

            # If we can determine essential tables, find the minimum connected set
            # that includes all essential tables plus required bridge tables
            if len(essential_tables) >= 2:
                # Find all tables needed to connect essential tables via BFS paths
                connected_set = set(essential_tables)
                essential_list = list(essential_tables)
                for i, t1 in enumerate(essential_list):
                    for t2 in essential_list[i+1:]:
                        # BFS from t1 to t2, finding shortest path through SCHEMA_GRAPH
                        queue: list[tuple[str, list[str]]] = [(t1, [t1])]
                        seen = {t1}
                        while queue:
                            curr, path = queue.pop(0)
                            if curr == t2:
                                connected_set.update(path)
                                break
                            for neighbor in SCHEMA_GRAPH.get(curr, {}):
                                if neighbor not in seen:
                                    seen.add(neighbor)
                                    queue.append((neighbor, path + [neighbor]))

                prunable = set(repaired.required_tables) - connected_set
                if prunable:
                    # Verify prunable tables aren't referenced in filters or group_by
                    truly_unnecessary = set()
                    for t in prunable:
                        t_referenced = False
                        for f in (repaired.filters or []):
                            if t in f.lower():
                                t_referenced = True
                        for g in (repaired.group_by or []):
                            if any(c in g for c in ALL_COLUMNS.get(t, set())):
                                t_referenced = True
                        if not t_referenced and not _question_needs_table(q_low, t):
                            truly_unnecessary.add(t)
                    if truly_unnecessary:
                        issues.append(
                            PlanValidationIssue(
                                category=PlanValidationCategory.UNNECESSARY_TABLE,
                                severity="info",
                                message=f"Tables not needed by question/plan: {truly_unnecessary}",
                            )
                        )
                        repaired.required_tables = [t for t in repaired.required_tables if t not in truly_unnecessary]

        # ── 5. Disconnected table detection ──────────────────────────────────
        if len(repaired.required_tables) > 1:
            table_set = set(repaired.required_tables)
            reachable = _tables_reachable_from(repaired.required_tables[0], table_set)
            disconnected = table_set - reachable
            if disconnected:
                issues.append(
                    PlanValidationIssue(
                        category=PlanValidationCategory.DISCONNECTED_TABLES,
                        severity="warning",
                        message=f"Tables {disconnected} are not reachable from {repaired.required_tables[0]} via known joins.",
                    )
                )

        # ── 6. Join path validation & completion ─────────────────────────────
        join_path = find_minimum_join_path(repaired.required_tables)
        if join_path:
            repaired.join_path = join_path

        # ── 7. Superlative & Ranking semantics check ─────────────────────────
        superlative_keywords = [
            "highest", "lowest", "most", "least", "best", "worst", "top", "bottom",
            "fastest", "slowest", "maximum", "max", "minimum", "min", "largest", "smallest",
        ]
        singular_superlative_keywords = [
            "which", "what is the", "highest", "lowest", "best", "worst",
            "largest", "smallest", "most", "least", "fastest", "slowest",
            "maximum", "minimum",
        ]
        is_superlative = any(re.search(rf"\b{k}\b", q_low) for k in superlative_keywords)
        
        # Check for explicit top N in question first
        top_n_match = re.search(r"\btop\s+(\d+)\b", q_low) or re.search(r"\bbottom\s+(\d+)\b", q_low) or re.search(r"\b(\d+)\s+most\b", q_low)
        
        is_singular = False
        if not top_n_match:
            is_singular = any(re.search(rf"\b{k}\b", q_low) for k in singular_superlative_keywords)
            # But exclude cases that request "all" or lists
            if is_singular and any(k in q_low for k in ["all", "list", "each", "every", "distribution"]):
                is_singular = False
            # Monthly/trend questions are not singular superlatives
            if is_singular and any(k in q_low for k in ["monthly", "per month", "trend", "over time"]):
                is_singular = False

        if is_superlative:
            if not repaired.ranking_direction:
                if any(k in q_low for k in ["highest", "most", "best", "top", "fastest", "maximum", "max", "largest"]):
                    repaired.ranking_direction = "DESC"
                elif any(k in q_low for k in ["lowest", "least", "worst", "bottom", "slowest", "minimum", "min", "smallest"]):
                    repaired.ranking_direction = "ASC"

            if top_n_match:
                explicit_limit = int(top_n_match.group(1))
                if repaired.limit != explicit_limit:
                    issues.append(
                        PlanValidationIssue(
                            category=PlanValidationCategory.MISSING_RANKING_LIMIT,
                            severity="warning",
                            message=f"Question requested top {explicit_limit}, but plan had limit={repaired.limit}.",
                        )
                    )
                    repaired.limit = explicit_limit
            elif is_singular and (repaired.limit is None or repaired.limit > 1):
                issues.append(
                    PlanValidationIssue(
                        category=PlanValidationCategory.MISSING_RANKING_LIMIT,
                        severity="warning",
                        message="Singular superlative query should default to LIMIT 1.",
                    )
                )
                repaired.limit = 1

            if repaired.limit is not None and not repaired.ordering:
                direction = repaired.ranking_direction or "DESC"
                repaired.ordering = f"{repaired.ranking_metric or repaired.metric or 'metric'} {direction}"

        # ── 8. Composite Metric Validation ───────────────────────────────────
        if any(k in q_low for k in ["cancellation rate", "cancel rate", "cancellation %"]):
            repaired.composite_metric = CompositeMetric(
                metric_type=MetricType.RATE,
                name="cancellation_rate",
                numerator="SUM(CASE WHEN o.order_status = 'canceled' THEN 1.0 ELSE 0.0 END)",
                denominator="COUNT(*)",
                aggregation="RATIO",
                formula_template="CAST(SUM(CASE WHEN order_status = 'canceled' THEN 1.0 ELSE 0.0 END) AS REAL) / COUNT(*)",
            )
        elif any(k in q_low for k in ["average order value", "aov"]):
            repaired.composite_metric = CompositeMetric(
                metric_type=MetricType.AVERAGE,
                name="aov",
                numerator="SUM(oi.price)",
                denominator="COUNT(DISTINCT o.order_id)",
                aggregation="AVG",
                formula_template="SUM(oi.price) / COUNT(DISTINCT o.order_id)",
            )
        elif any(k in q_low for k in ["delivery delay rate", "late delivery rate"]):
            repaired.composite_metric = CompositeMetric(
                metric_type=MetricType.RATE,
                name="delivery_delay_rate",
                numerator="SUM(CASE WHEN o.order_delivered_customer_date > o.order_estimated_delivery_date THEN 1.0 ELSE 0.0 END)",
                denominator="COUNT(*)",
                aggregation="RATIO",
                formula_template="CAST(SUM(CASE WHEN order_delivered_customer_date > order_estimated_delivery_date THEN 1.0 ELSE 0.0 END) AS REAL) / COUNT(*)",
            )

        # Composite metric completeness check
        if repaired.composite_metric:
            cm = repaired.composite_metric
            if cm.metric_type in (MetricType.RATIO, MetricType.RATE, MetricType.PERCENTAGE):
                if not cm.numerator or not cm.denominator:
                    issues.append(
                        PlanValidationIssue(
                            category=PlanValidationCategory.MALFORMED_COMPOSITE_METRIC,
                            severity="error",
                            message=f"Composite metric '{cm.name}' of type {cm.metric_type.value} requires both numerator and denominator.",
                        )
                    )

        # ── 9. Time grain validation ─────────────────────────────────────────
        if any(k in q_low for k in ["monthly", "per month", "by month", "month-over-month", "monthly trend"]):
            if repaired.time_grain != "month":
                issues.append(
                    PlanValidationIssue(
                        category=PlanValidationCategory.MISSING_TIME_GRAIN,
                        severity="warning",
                        message="Monthly trend requested; setting time_grain to 'month'.",
                    )
                )
                repaired.time_grain = "month"
            if not repaired.time_column:
                repaired.time_column = "order_purchase_timestamp"
            if not repaired.group_by:
                repaired.group_by = ["month"]
            elif "month" not in [g.lower() for g in repaired.group_by]:
                repaired.group_by.insert(0, "month")
        elif any(k in q_low for k in ["yearly", "annual", "per year", "year-over-year"]):
            if repaired.time_grain != "year":
                issues.append(
                    PlanValidationIssue(
                        category=PlanValidationCategory.MISSING_TIME_GRAIN,
                        severity="warning",
                        message="Yearly trend requested; setting time_grain to 'year'.",
                    )
                )
                repaired.time_grain = "year"
            if not repaired.time_column:
                repaired.time_column = "order_purchase_timestamp"

        # ── 10. Group-by consistency ─────────────────────────────────────────
        if repaired.group_by and repaired.result_shape:
            shape_str = repaired.result_shape.value if hasattr(repaired.result_shape, 'value') else str(repaired.result_shape)
            if shape_str == "single_value" and len(repaired.group_by) > 0 and repaired.limit != 1:
                issues.append(
                    PlanValidationIssue(
                        category=PlanValidationCategory.GROUPBY_CONSISTENCY,
                        severity="warning",
                        message=f"result_shape is single_value but group_by has {repaired.group_by}. Adjusting result_shape.",
                    )
                )
                # Don't clear group_by — adjust result_shape instead
                if repaired.limit and repaired.limit > 1:
                    repaired.result_shape = ResultShape.RANKED_LIST
                else:
                    repaired.result_shape = ResultShape.AGGREGATED_TABLE

        # ── 11. Result shape assignment ──────────────────────────────────────
        if repaired.limit == 1 and not repaired.time_grain:
            repaired.result_shape = ResultShape.SINGLE_VALUE
        elif repaired.time_grain is not None:
            repaired.result_shape = ResultShape.TIME_SERIES
        elif repaired.limit is not None and repaired.limit > 1:
            repaired.result_shape = ResultShape.RANKED_LIST
        elif repaired.group_by:
            repaired.result_shape = ResultShape.AGGREGATED_TABLE
        elif not repaired.group_by and not repaired.limit:
            repaired.result_shape = ResultShape.SINGLE_VALUE

        has_errors = any(i.severity == "error" for i in issues)
        return PlanValidationResult(
            is_valid=not has_errors,
            issues=issues,
            repaired_plan=repaired,
        )
