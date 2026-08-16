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

    return f"""Original SQL (broken):
```sql
{original_sql.strip()}
```

Verification error(s) to fix:
{error_block}

Schema context:
{chr(10).join(schema_context)}
{column_section}
Produce the corrected SQL that fixes ONLY the error(s) listed above.
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
