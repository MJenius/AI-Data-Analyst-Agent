from __future__ import annotations

from pydantic import BaseModel, Field


class PlannerOutput(BaseModel):
    """Schema for validating Planner agent output."""
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
