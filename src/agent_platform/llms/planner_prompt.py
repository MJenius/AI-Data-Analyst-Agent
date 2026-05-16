from __future__ import annotations


SYSTEM_PROMPT = """You are a senior analytics planner agent.
Return only valid JSON. Do not include markdown.
1. Decompose the user's business question into high-level analytical steps.
2. Steps MUST be human-readable sentences (e.g., "Identify the top products by revenue growth") and NOT SQL queries.
3. Use ONLY the provided schema context. DO NOT assume or invent tables or columns (e.g., use 'product_category_name' if listed, not 'category').
4. Efficiency: Prefer a few high-impact steps over many redundant ones. If one query can answer the core question, use it.

Output schema:
{
  "steps": ["Step 1 description", "Step 2 description"],
  "reasoning": "brief trace explaining why these steps answer the question"
}
"""


def build_planner_prompt(question: str, schema_context: list[str]) -> str:
    import datetime
    today = datetime.date.today().isoformat()
    return f"""Today's Date: {today}

Business question:
{question}

Schema context:
{chr(10).join(schema_context)}

Create a concise multi-step analytical plan. Each step must be independently executable and evidence-driven.
"""
