from __future__ import annotations

from pydantic import BaseModel, Field


class QueryPlanOutput(BaseModel):
    """Schema for validating Planner agent output as a structured QueryPlan."""
    intent: str = Field(description="High-level analytical intent of the question")
    metric: str = Field(description="Primary metric being calculated")
    entity: str | None = Field(default=None, description="Primary entity being analyzed")
    aggregation: str | None = Field(default=None, description="Aggregation function used")
    filters: list[str] = Field(default_factory=list, description="Filters applied to the data")
    group_by: list[str] | None = Field(default=None, description="Fields to group by")
    ordering: str | None = Field(default=None, description="Ordering direction and field")
    limit: int | None = Field(default=None, description="Result limit if applicable")
    required_tables: list[str] = Field(description="Tables required to answer the question")
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
