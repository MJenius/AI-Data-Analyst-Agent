from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class CompositeMetricOutput(BaseModel):
    """Structured representation of composite metric output from LLM planner."""
    metric_type: str = Field(default="simple", description="Type of calculation: simple, ratio, percentage, rate, growth_rate, average, count, distinct_count, sum")
    name: str = Field(description="Name or description of metric (e.g. cancellation_rate, aov, arpu)")
    numerator: str | None = Field(default=None, description="Numerator expression or metric name for ratio/percentage")
    denominator: str | None = Field(default=None, description="Denominator expression or metric name for ratio/percentage")
    aggregation: str | None = Field(default=None, description="Primary aggregation used")
    grouping_grain: list[str] = Field(default_factory=list, description="Grain at which metric is computed")
    filter_scope: list[str] = Field(default_factory=list, description="Specific filters bounding this metric")
    formula_template: str | None = Field(default=None, description="SQL/Math formula template")


class QueryPlanOutput(BaseModel):
    """Schema for validating Planner agent output as a rich structured QueryPlan."""
    intent: str = Field(description="High-level analytical intent of the question")
    entities: list[str] = Field(default_factory=list, description="Primary entities being analyzed (e.g. product, customer, seller)")
    entity: str | None = Field(default=None, description="Primary entity column or alias")
    required_tables: list[str] = Field(description="Minimum tables required to answer the question")
    join_path: list[str] = Field(default_factory=list, description="Explicit join predicates linking required tables")
    metric: str = Field(description="Primary metric being calculated")
    composite_metric: CompositeMetricOutput | None = Field(default=None, description="Detailed composite metric definition if applicable")
    aggregation: str | None = Field(default=None, description="Aggregation function used (e.g., SUM, COUNT, AVG, COUNT_DISTINCT)")
    filters: list[str] = Field(default_factory=list, description="Filters applied to the data")
    time_column: str | None = Field(default=None, description="Temporal column used for filtering or grouping")
    time_range: str | None = Field(default=None, description="Time range bounds")
    time_grain: str | None = Field(default=None, description="Time grouping grain (month, year, day, hour)")
    group_by: list[str] | None = Field(default=None, description="Fields to group by")
    ranking_dimension: str | None = Field(default=None, description="Dimension on which ranking is performed")
    ranking_metric: str | None = Field(default=None, description="Metric on which ranking is ordered")
    ranking_direction: str | None = Field(default=None, description="Ordering direction (ASC or DESC)")
    ordering: str | None = Field(default=None, description="Ordering direction and field")
    limit: int | None = Field(default=None, description="Result limit if applicable")
    result_shape: str | None = Field(default=None, description="Expected shape: single_value, ranked_list, time_series, aggregated_table, record_list")
    reasoning: str = Field(description="Brief trace explaining why this plan answers the question")


class PlannerOutput(BaseModel):
    """Schema for validating Planner agent output (legacy steps-based)."""
    steps: list[str] = Field(description="Sequential execution plan steps")
    reasoning: str = Field(description="Detailed rationale behind the analytical approach")


class SQLOutput(BaseModel):
    """Schema for validating Executor SQL generation output."""
    sql: str | None = Field(default=None, description="Valid SQLite read-only query statement, or null if no database action is needed")
    reasoning: str = Field(description="Analytical reasoning explaining the database query design")


class EvaluatorOutput(BaseModel):
    """Schema for validating Evaluator final synthesis output."""
    summary: str = Field(description="Executive level summary of analytical insights")
    key_findings: list[str] = Field(description="Key findings supported by metric evidence")
    why_explanation: str | None = Field(default=None, description="Causal reasoning for identified outcomes")
    anomalies: list[str] = Field(default_factory=list, description="List of anomalies or outliers identified")
    confidence: float = Field(description="Grounded confidence level score from 0.0 to 1.0")
    confidence_explanation: str | None = Field(default=None, description="Structured rationale backing the assigned confidence level")
    issues: list[str] = Field(default_factory=list, description="Any trace validation, data scarcity, or quality issues identified")
    validated: bool = Field(description="True if query logic is correct and evidence is structurally grounded")
    reasoning: str = Field(description="Evaluation rationale behind validation status and score")
    verdict: str = Field(default="uncertain", description="Validation status verdict, e.g. accurate, uncertain")
    detected_contradictions: list[str] = Field(default_factory=list, description="Contradictions detected between different step executions")
