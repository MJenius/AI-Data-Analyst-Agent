from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class MetricType(str, Enum):
    SIMPLE = "simple"
    RATIO = "ratio"
    PERCENTAGE = "percentage"
    RATE = "rate"
    GROWTH_RATE = "growth_rate"
    AVERAGE = "average"
    COUNT = "count"
    DISTINCT_COUNT = "distinct_count"
    SUM = "sum"


class ResultShape(str, Enum):
    SINGLE_VALUE = "single_value"
    RANKED_LIST = "ranked_list"
    TIME_SERIES = "time_series"
    AGGREGATED_TABLE = "aggregated_table"
    RECORD_LIST = "record_list"


class RankingDirection(str, Enum):
    ASC = "ASC"
    DESC = "DESC"


class CompositeMetric(BaseModel):
    """Structured representation of composite or complex analytical metrics."""
    metric_type: MetricType = Field(default=MetricType.SIMPLE, description="Type of metric calculation")
    name: str = Field(description="Name or description of metric (e.g. cancellation_rate, aov, arpu)")
    numerator: str | None = Field(default=None, description="Numerator expression or metric name for ratio/percentage")
    denominator: str | None = Field(default=None, description="Denominator expression or metric name for ratio/percentage")
    aggregation: str | None = Field(default=None, description="Primary aggregation used (SUM, COUNT, AVG, COUNT_DISTINCT)")
    grouping_grain: list[str] = Field(default_factory=list, description="Grain at which metric is computed")
    filter_scope: list[str] = Field(default_factory=list, description="Specific filters bounding this metric")
    formula_template: str | None = Field(default=None, description="SQL/Math formula template (e.g. CAST(SUM(...) AS REAL) / COUNT(...))")
    source_columns: list[str] = Field(
        default_factory=list,
        description="Exact physical columns this metric reads from (e.g. ['order_items.price'])"
    )


class QueryPlan(BaseModel):
    """Structured intermediate query plan capturing full analytical intent before SQL generation."""

    intent: str = Field(description="High-level analytical intent of the question")
    entities: list[str] = Field(default_factory=list, description="Primary entities being analyzed (e.g., product, customer, seller)")
    entity: str | None = Field(default=None, description="Primary entity column or alias (for backward compatibility)")
    required_tables: list[str] = Field(description="Minimum tables required to answer the question")
    join_path: list[str] = Field(default_factory=list, description="Explicit join predicates linking required tables (e.g. orders.order_id = order_items.order_id)")
    metric: str = Field(default="", description="Primary metric being calculated (e.g., revenue, count, average)")
    composite_metric: CompositeMetric | None = Field(default=None, description="Detailed composite metric definition if applicable")
    aggregation: str | None = Field(default=None, description="Aggregation function used (e.g., SUM, COUNT, AVG, COUNT_DISTINCT)")
    filters: list[str] = Field(default_factory=list, description="Filters applied to the data")
    time_column: str | None = Field(default=None, description="Temporal column used for filtering or grouping (e.g. order_purchase_timestamp)")
    time_range: str | None = Field(default=None, description="Time range bounds (e.g. 2017, 2017-01 to 2017-12)")
    time_grain: str | None = Field(default=None, description="Time grouping grain (e.g. month, year, day, hour)")
    group_by: list[str] | None = Field(default=None, description="Fields to group by")
    ranking_dimension: str | None = Field(default=None, description="Dimension on which ranking is performed")
    ranking_metric: str | None = Field(default=None, description="Metric on which ranking is ordered")
    ranking_direction: str | None = Field(default=None, description="Ordering direction (ASC or DESC)")
    ordering: str | None = Field(default=None, description="Full ordering expression (e.g. revenue DESC)")
    limit: int | None = Field(default=None, description="Result limit if applicable")
    result_shape: ResultShape | str | None = Field(default=None, description="Expected shape of analytical output")
    metric_source_column: str | None = Field(default=None, description="Primary physical column for the metric (e.g. 'price', 'payment_value', 'review_score')")
    reasoning: str = Field(default="", description="Explanation of how this plan answers the question")

    def model_post_init(self, __context: Any) -> None:
        if not self.entities and self.entity:
            self.entities = [self.entity]
        elif self.entities and not self.entity:
            self.entity = self.entities[0]

        # Normalize ordering and ranking direction
        if self.ranking_direction and not self.ordering:
            metric_or_dim = self.ranking_metric or self.metric or "val"
            self.ordering = f"{metric_or_dim} {self.ranking_direction.upper()}"
        elif self.ordering and not self.ranking_direction:
            upper = self.ordering.upper()
            if "DESC" in upper:
                self.ranking_direction = "DESC"
            elif "ASC" in upper:
                self.ranking_direction = "ASC"

    def to_steps(self) -> list[str]:
        """Derive executable analytical steps from this structured plan."""
        steps = [
            f"Inspect schema for {', '.join(self.required_tables)} to understand {self.intent}",
        ]
        if self.composite_metric and self.composite_metric.formula_template:
            metric_part = f"{self.composite_metric.name} ({self.composite_metric.formula_template})"
        elif self.aggregation and self.metric.lower() != self.aggregation.lower():
            metric_part = f"{self.aggregation}({self.metric})"
        else:
            metric_part = self.metric

        entity_str = f" by {', '.join(self.entities)}" if self.entities else (f" by {self.entity}" if self.entity else "")
        filters_str = f" with filters: {', '.join(self.filters)}" if self.filters else ""
        grain_str = f" at {self.time_grain} grain" if self.time_grain else ""
        group_str = f" grouped by {', '.join(self.group_by)}" if self.group_by else ""
        order_str = f" ordered by {self.ordering}" if self.ordering else ""
        limit_str = f" limited to {self.limit}" if self.limit else ""
        
        steps.append(
            f"{metric_part}{entity_str}{grain_str}{filters_str}{group_str}{order_str}{limit_str}"
        )
        steps.append(
            f"Summarize findings for {self.intent} with supporting metrics"
        )
        return steps
