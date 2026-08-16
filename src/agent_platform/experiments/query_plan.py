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
    reasoning: str = Field(default="", description="Explanation of how this plan answers the question")

    def to_steps(self) -> list[str]:
        """Derive executable analytical steps from this structured plan."""
        steps = [
            f"Inspect schema for {', '.join(self.required_tables)} to understand {self.intent}",
        ]
        if self.aggregation and self.metric.lower() != self.aggregation.lower():
            metric_part = f"{self.aggregation}({self.metric})"
        else:
            metric_part = self.metric
        entity = f" by {self.entity}" if self.entity else ""
        filters = f" with filters: {', '.join(self.filters)}" if self.filters else ""
        group = f" grouped by {', '.join(self.group_by)}" if self.group_by else ""
        order = f" ordered by {self.ordering}" if self.ordering else ""
        limit = f" limited to {self.limit}" if self.limit else ""
        steps.append(
            f"{metric_part}{entity}{filters}{group}{order}{limit}"
        )
        steps.append(
            f"Summarize findings for {self.intent} with supporting metrics"
        )
        return steps
