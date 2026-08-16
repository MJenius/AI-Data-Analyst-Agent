from __future__ import annotations


SYSTEM_PROMPT = """You are a careful SQL generation agent for an analytics system.
Return only valid JSON. Do not include markdown.
Generate safe, read-only SQLite SQL using ONLY the columns and tables provided in the schema context below.
Never generate INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, PRAGMA, VACUUM, ATTACH, DETACH, or multiple statements.
Grounding contract:
- List every physical table in grounding.tables using its exact supplied name.
- List every physical column in grounding.columns as exact table.column. Do not translate a business word into a plausible column name.
- List every join predicate in grounding.joins. Each physical-table join must exactly match an allowed relationship in context.
- Qualify physical columns with table aliases. Derived CTE names and calculated aliases are allowed only when defined by the query.
- Use the supplied grain and business definitions for metrics. Protect aggregates from one-to-many join multiplication.
- When using GROUP BY: every non-aggregate SELECT column MUST appear in GROUP BY.
- Do not add a table unless it supplies a selected field, filter, grouping, metric, or necessary join path.
- Check temporal bounds and sample values before writing literal filters.
- If the requested concept is absent from the supplied schema, return sql=null instead of inventing it.

CRITICAL: Use ONLY the column names listed in the COLUMN REFERENCE block below. Column names like
'quantity', 'unit_price', 'discount_rate', 'order_date', 'product_name', 'category_name' do NOT exist.

Output schema:
{
  "reasoning": "brief grounding rationale",
  "grounding": {
    "tables": ["exact_table"],
    "columns": ["exact_table.exact_column"],
    "joins": ["left_table.key = right_table.key"]
  },
  "sql": "SELECT ...",
  "expected_result": "what the query should reveal"
}
If the step only asks to inspect schema and no SQL is needed, set "sql" to null.
"""


def build_sql_prompt(question: str, step: str, schema_context: list[str]) -> str:
    """Build a SQL generation prompt with explicit column-level grounding.

    Phase 6 change: extract physical tables from the retrieved schema context
    and inject a compact COLUMN REFERENCE block that lists every exact column
    name, type, and PK/FK tag so the LLM cannot invent plausible-but-wrong
    column names (the dominant Phase 4/5 failure mode: 39 hallucinated-column
    execution errors).
    """
    import datetime
    from agent_platform.rag.ingestion.schema_context import (
        build_column_grounding_block,
        tables_from_context,
    )

    today = datetime.date.today().isoformat()
    tables = tables_from_context(schema_context)
    column_block = build_column_grounding_block(tables) if tables else ""

    column_section = f"\n{column_block}\n" if column_block else ""

    return f"""Today's Date: {today}

Business question:
{question}

Current analysis step:
{step}

Schema context:
{chr(10).join(schema_context)}
{column_section}
First ground the required tables, columns, and join path against this context. Then generate one SQL query for this step, or null if the step requires schema inspection only.
"""
