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
    JOIN_RELATIONSHIPS,
    TABLE_DESCRIPTIONS,
)

logger = logging.getLogger(__name__)

KNOWN_TABLES = set(TABLE_DESCRIPTIONS.keys())

# Build adjacency graph for schema relationships
SCHEMA_GRAPH: dict[str, dict[str, str]] = {}
for from_t, from_c, to_t, to_c, kind, note in JOIN_RELATIONSHIPS:
    if from_t not in SCHEMA_GRAPH:
        SCHEMA_GRAPH[from_t] = {}
    if to_t not in SCHEMA_GRAPH:
        SCHEMA_GRAPH[to_t] = {}
    SCHEMA_GRAPH[from_t][to_t] = f"{from_t}.{from_c} = {to_t}.{to_c}"
    SCHEMA_GRAPH[to_t][from_t] = f"{to_t}.{to_c} = {from_t}.{from_c}"


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


class PlanValidator:
    """Deterministic validator and automatic plan repairer for structured QueryPlans."""

    def __init__(self, known_tables: set[str] | None = None) -> None:
        self.known_tables = known_tables or KNOWN_TABLES

    def validate(self, plan: QueryPlan, question: str = "") -> PlanValidationResult:
        issues: list[PlanValidationIssue] = []
        repaired: QueryPlan = plan.model_copy(deep=True)
        q_low = question.lower()

        # 1. Metric check
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

        # 2. Required tables check
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

        # 3. Minimum required tables detection
        needed_tables = set(repaired.required_tables)
        if any(k in q_low for k in ["revenue", "price", "freight", "item"]):
            needed_tables.add("order_items")
        if any(k in q_low for k in ["month", "trend", "status", "delivered", "canceled", "cancelled", "year", "delay"]):
            needed_tables.add("orders")
        if any(k in q_low for k in ["customer", "buyer", "state", "city"]) and not any(k in q_low for k in ["seller"]):
            if "customer" in q_low or "state" in q_low:
                needed_tables.add("customers")
        if any(k in q_low for k in ["product", "category"]):
            needed_tables.add("products")
        if any(k in q_low for k in ["payment", "installment"]):
            needed_tables.add("order_payments")
        if any(k in q_low for k in ["review", "rating", "score"]):
            needed_tables.add("order_reviews")
        if any(k in q_low for k in ["seller"]):
            needed_tables.add("sellers")

        # Table reduction / prune disconnected or unneeded
        if "order_items" in needed_tables and "products" in needed_tables and "orders" not in needed_tables:
            # direct connection exists between order_items and products
            pass
        elif len(needed_tables) > 1:
            # Ensure bridge tables exist
            if "customers" in needed_tables and "order_items" in needed_tables and "orders" not in needed_tables:
                needed_tables.add("orders")
            if "order_reviews" in needed_tables and "order_items" in needed_tables and "orders" not in needed_tables:
                needed_tables.add("orders")

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

        # 4. Join path validation & completion
        join_path = find_minimum_join_path(repaired.required_tables)
        if join_path:
            repaired.join_path = join_path

        # 5. Superlative & Ranking semantics check
        superlative_keywords = [
            "highest", "lowest", "most", "least", "best", "worst", "top", "bottom",
            "fastest", "slowest", "maximum", "max", "minimum", "min", "largest", "smallest",
        ]
        is_superlative = any(re.search(rf"\b{k}\b", q_low) for k in superlative_keywords)
        is_singular = any(re.search(rf"\b{k}\b", q_low) for k in ["which", "what is the top", "highest", "lowest", "best", "worst", "largest", "most"]) and not re.search(r"\btop\s+(\d+)\b", q_low)

        if is_superlative:
            if not repaired.ranking_direction:
                if any(k in q_low for k in ["highest", "most", "best", "top", "fastest", "maximum", "max", "largest"]):
                    repaired.ranking_direction = "DESC"
                elif any(k in q_low for k in ["lowest", "least", "worst", "bottom", "slowest", "minimum", "min", "smallest"]):
                    repaired.ranking_direction = "ASC"

            # Check for explicit top N in question (e.g. "top 5", "top 10")
            top_n_match = re.search(r"\btop\s+(\d+)\b", q_low) or re.search(r"\bbottom\s+(\d+)\b", q_low) or re.search(r"\b(\d+)\s+most\b", q_low)
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
                # For singular superlative questions default to limit 1
                if not any(k in q_low for k in ["top 3", "top 5", "top 10", "all", "list", "each", "every"]):
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
                repaired.ordering = f"{repaired.metric or 'metric'} {direction}"

        # 6. Composite Metric Validation
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

        # 7. Time grain validation
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

        # 8. Result shape
        if repaired.limit == 1 and not repaired.group_by:
            repaired.result_shape = ResultShape.SINGLE_VALUE
        elif repaired.time_grain is not None:
            repaired.result_shape = ResultShape.TIME_SERIES
        elif repaired.limit is not None and repaired.limit > 1:
            repaired.result_shape = ResultShape.RANKED_LIST
        elif repaired.group_by:
            repaired.result_shape = ResultShape.AGGREGATED_TABLE
        else:
            repaired.result_shape = ResultShape.SINGLE_VALUE

        has_errors = any(i.severity == "error" for i in issues)
        return PlanValidationResult(
            is_valid=not has_errors,
            issues=issues,
            repaired_plan=repaired,
        )
