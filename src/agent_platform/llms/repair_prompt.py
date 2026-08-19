"""Phase 6 — targeted SQL repair prompt.

Design contract:
- ONE repair call per flagged query, never a loop.
- The prompt contains the exact verification error message(s), the original SQL,
  and the minimal schema context needed to fix the issue.
- The LLM is asked to return the same JSON envelope as the normal SQL generation
  prompt (reasoning + grounding + sql) so the same parsing path can be reused.
- The prompt is deliberately narrow: fix only the stated issue; do not rewrite
  the query structure.
"""

from __future__ import annotations

from typing import Any

from agent_platform.tools.sql_verifier import VerificationCategory, VerificationIssue


# ── category → repair instruction ──────────────────────────────────────────

_REPAIR_INSTRUCTIONS: dict[VerificationCategory, str] = {
    VerificationCategory.GROUP_BY_MISMATCH: (
        "Every non-aggregate column in SELECT must appear in GROUP BY. "
        "Add the missing column(s) to the GROUP BY clause. "
        "Do not remove columns, change aggregations, or alter the WHERE/JOIN structure."
    ),
    VerificationCategory.AGGREGATION_GRAIN: (
        "The query mixes aggregate functions with non-aggregate SELECT columns but has no GROUP BY. "
        "Add a GROUP BY clause that lists all non-aggregate SELECT columns."
    ),
    VerificationCategory.JOIN_FAN_OUT: (
        "A JOIN is missing its ON equality condition, which creates a Cartesian product. "
        "Add the correct ON clause using the join keys listed in the schema context."
    ),
    VerificationCategory.METRIC_INCONSISTENCY: (
        "An aggregate column returned NULL. "
        "Check whether the JOIN conditions match any rows, or wrap the aggregate in COALESCE."
    ),
    VerificationCategory.DUPLICATE_DETECTION: (
        "The query returns far more rows than expected — likely a Cartesian product or missing filter. "
        "Review JOIN conditions and add or tighten WHERE predicates."
    ),
    VerificationCategory.HALLUCINATED_COLUMN: (
        "The query references a column that does not exist in the database schema. "
        "Replace the non-existent column reference with the exact column name shown in the "
        "COLUMN REFERENCE block below. Do NOT invent column names."
    ),
    # ── Phase 8: semantic alignment categories ─────────────────────────────
    VerificationCategory.METRIC_MISMATCH: (
        "The query's metric/aggregation does not match the planned metric. "
        "Apply the planned aggregation function to the exact metric column from the "
        "COLUMN REFERENCE block. Do not change the join structure."
    ),
    VerificationCategory.FILTER_MISMATCH: (
        "A filter required by the question (per the plan) is missing or wrong. "
        "Add the missing WHERE predicate using the exact column and filter value from the plan. "
        "Do not alter other clauses."
    ),
    VerificationCategory.TIME_GRAIN_MISMATCH: (
        "The time grain (month/day/hour/etc.) does not match the planned grain. "
        "Truncate the correct timestamp column (orders.order_purchase_timestamp is the canonical "
        "order date) to the planned grain using strftime/substr, and group by that truncation."
    ),
    VerificationCategory.GROUP_BY_GRAIN_MISMATCH: (
        "The GROUP BY grain does not match the planned dimension. "
        "Group by the planned dimension column from the COLUMN REFERENCE block. "
        "Every non-aggregate SELECT column must be in GROUP BY."
    ),
    VerificationCategory.RANKING_MISMATCH: (
        "The query is not ranked/truncated as the question requests. "
        "Add ORDER BY on the metric with the correct direction and the LIMIT from the plan "
        "(top-N means DESCENDING order)."
    ),
    VerificationCategory.ENTITY_MISMATCH: (
        "The intended entity columns are missing from the query. "
        "Reference the planned entity column(s) from the COLUMN REFERENCE block in SELECT or GROUP BY."
    ),
    VerificationCategory.JOIN_PATH_MISMATCH: (
        "The join path does not match the plan's required tables. "
        "Add missing tables with their exact join keys, or remove tables that are not in the plan "
        "unless they supply a selected field, filter, grouping, or metric. Use ONLY the join "
        "keys listed in the COLUMN REFERENCE block."
    ),
    VerificationCategory.RESULT_SHAPE_MISMATCH: (
        "The output shape does not match the expected result. "
        "Align SELECT output columns and row grain with the question's requested metric."
    ),
}

SYSTEM_PROMPT = """You are a careful SQL repair agent for an analytics system.
You will receive a broken SQL query, the exact verification error(s) it produced, and schema context.
Your job is to produce a minimally-changed corrected SQL query that fixes ONLY the stated error(s).

Rules:
- Fix ONLY the stated verification issue. Do not restructure, rename aliases, or add new columns.
- Use ONLY column names that appear in the COLUMN REFERENCE block.
- Every non-aggregate SELECT column MUST be in GROUP BY when aggregates are present.
- Return valid read-only SQLite SQL (SELECT / WITH only).
- Return only valid JSON. Do not include markdown code fences.

Output schema (same as SQL generation):
{
  "reasoning": "what was wrong and what you changed",
  "grounding": {
    "tables": ["exact_table"],
    "columns": ["exact_table.exact_column"],
    "joins": ["left_table.key = right_table.key"]
  },
  "sql": "SELECT ...",
  "expected_result": "what the repaired query should reveal"
}
"""


def build_repair_prompt(
    original_sql: str,
    issues: list[VerificationIssue],
    schema_context: list[str],
    query_plan: Any = None,
) -> str:
    """Build a targeted one-shot repair prompt.

    Parameters
    ----------
    original_sql:
        The SQL string that failed verification.
    issues:
        Verification issues that must be fixed (errors + warnings; pass only
        actionable ones — not info-level hints).
    schema_context:
        The same schema context strings already provided to the original
        SQL generation call.
    query_plan:
        Optional QueryPlan (model or dict) whose semantics the SQL must
        satisfy — injected so the repair model aligns the fix to the
        intended metric, filters, grain, and ranking (Phase 8).

    Returns
    -------
    str
        A user-message string ready to pass to ``LLMClient.complete_json()``
        with ``SYSTEM_PROMPT`` as the system message.
    """
    from agent_platform.rag.ingestion.schema_context import (
        build_column_grounding_block,
        tables_from_context,
    )

    # De-duplicate by category so we don't flood the prompt with 41 identical messages.
    seen_cats: set[VerificationCategory] = set()
    unique_issues: list[VerificationIssue] = []
    for issue in issues:
        if issue.category not in seen_cats:
            seen_cats.add(issue.category)
            unique_issues.append(issue)
        else:
            # Still collect distinct messages even within same category.
            if not any(ui.message == issue.message for ui in unique_issues):
                unique_issues.append(issue)

    # Build the error block.
    error_lines: list[str] = []
    for issue in unique_issues:
        instr = _REPAIR_INSTRUCTIONS.get(issue.category, "Fix the reported issue.")
        error_lines.append(
            f"[{issue.severity.upper()} — {issue.category.value}]\n"
            f"  Problem : {issue.message}\n"
            f"  Fix     : {instr}"
        )
        if issue.suggested_repair:
            error_lines.append(f"  Hint    : {issue.suggested_repair}")
    error_block = "\n\n".join(error_lines)

    # Column reference block for tables in the original context.
    tables = tables_from_context(schema_context)
    column_block = build_column_grounding_block(tables) if tables else ""
    column_section = f"\n{column_block}" if column_block else ""

    # Plan context block (Phase 8): the repaired SQL must satisfy this plan.
    plan_block = ""
    if query_plan is not None:
        if isinstance(query_plan, dict):
            pv = lambda key, default=None: query_plan.get(key, default)  # noqa: E731
        else:
            pv = lambda key, default=None: getattr(query_plan, key, default)  # noqa: E731
        plan_lines: list[str] = []
        if pv("intent"):
            plan_lines.append(f"- intent: {pv('intent')}")
        metric = pv("metric")
        if metric:
            aggregation = pv("aggregation")
            plan_lines.append(
                f"- metric: {aggregation}({metric})" if aggregation else f"- metric: {metric}"
            )
        if pv("entity"):
            plan_lines.append(f"- entity: {pv('entity')}")
        if pv("filters"):
            plan_lines.append(f"- filters: {', '.join(str(f) for f in pv('filters'))}")
        if pv("group_by"):
            plan_lines.append(f"- group_by: {', '.join(str(g) for g in pv('group_by'))}")
        if pv("ordering"):
            plan_lines.append(f"- ordering: {pv('ordering')}")
        if pv("limit") is not None:
            plan_lines.append(f"- limit: {pv('limit')}")
        if pv("required_tables"):
            plan_lines.append(f"- required_tables: {', '.join(str(t) for t in pv('required_tables'))}")
        if plan_lines:
            plan_block = (
                "Planned semantics (the corrected SQL MUST satisfy this plan):\n"
                + "\n".join(plan_lines)
            )

    plan_section = f"\n{plan_block}\n" if plan_block else ""

    return f"""Original SQL (broken):
```sql
{original_sql.strip()}
```

Verification error(s) to fix:
{error_block}

{plan_section}
Schema context:
{chr(10).join(schema_context)}
{column_section}
Produce the corrected SQL that fixes ONLY the error(s) listed above and stays aligned with the plan.
"""


def filter_actionable_issues(issues: list[VerificationIssue]) -> list[VerificationIssue]:
    """Return only issues that the LLM can act on in a repair call.

    Info-level hints (e.g. expected_row_count) are excluded because they do
    not indicate a concrete structural defect and would confuse the repair.
    """
    return [
        i for i in issues
        if i.severity in ("error", "warning")
        and i.category
        not in (
            VerificationCategory.DUPLICATE_DETECTION,   # symptom, not root cause
            VerificationCategory.METRIC_INCONSISTENCY,  # often runtime — better caught post-exec
        )
    ]
