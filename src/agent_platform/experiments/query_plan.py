from __future__ import annotations

from pydantic import BaseModel, Field


class QueryPlan(BaseModel):
    """Structured intermediate query plan generated before SQL generation."""

    intent: str = Field(description="High-level analytical intent of the question")
    metric: str = Field(description="Primary metric being calculated (e.g., revenue, count, average)")
    entity: str | None = Field(default=None, description="Primary entity being analyzed (e.g., product, customer, order)")
    aggregation: str | None = Field(default=None, description="Aggregation function used (e.g., SUM, COUNT, AVG)")
    filters: list[str] = Field(default_factory=list, description="Filters applied to the data")
    group_by: list[str] | None = Field(default=None, description="Fields to group by")
    ordering: str | None = Field(default=None, description="Ordering direction and field")
    limit: int | None = Field(default=None, description="Result limit if applicable")
    required_tables: list[str] = Field(description="Tables required to answer the question")
