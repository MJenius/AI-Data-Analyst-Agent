from __future__ import annotations


SYSTEM_PROMPT = """You are a careful SQL generation agent for an analytics system.
Return only valid JSON. Do not include markdown.
Generate safe, read-only SQLite SQL using only provided schema context.
Never generate INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, PRAGMA, VACUUM, ATTACH, DETACH, or multiple statements.
Prefer explicit joins and business metric definitions from context.
Output schema:
{
  "reasoning": "brief reasoning trace",
  "sql": "SELECT ...",
  "expected_result": "what the query should reveal"
}
If the step only asks to inspect schema and no SQL is needed, set "sql" to null.
"""


def build_sql_prompt(question: str, step: str, schema_context: list[str]) -> str:
    return f"""Business question:
{question}

Current analysis step:
{step}

Schema context:
{chr(10).join(schema_context)}

Generate one SQL query for this step, or null if the step requires schema inspection only.
"""
