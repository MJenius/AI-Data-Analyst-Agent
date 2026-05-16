from __future__ import annotations


SYSTEM_PROMPT = """You are a senior analytics planner agent.
Return only valid JSON. Do not include markdown.
Decompose the user's business question into SQL-backed analysis steps.
Use only the provided schema context. Avoid inventing tables or columns.
Output schema:
{
  "steps": ["..."],
  "reasoning": "brief trace explaining why these steps answer the question"
}
"""


def build_planner_prompt(question: str, schema_context: list[str]) -> str:
    return f"""Business question:
{question}

Schema context:
{chr(10).join(schema_context)}

Create a concise multi-step analytical plan. Each step must be independently executable and evidence-driven.
"""
