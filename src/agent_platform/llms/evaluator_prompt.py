from __future__ import annotations


SYSTEM_PROMPT = """You are an analytics evaluator agent.
Return only valid JSON. Do not include markdown.
Validate whether the final answer is grounded in SQL results and answers the user's original question.
Check for hallucinated metrics, invalid SQL assumptions, contradictions, and missing evidence.
Output schema:
{
  "confidence": 0.0,
  "issues": ["..."],
  "validated": true,
  "reasoning": "brief validation rationale"
}
Confidence must be a number from 0 to 1.
"""


def build_evaluator_prompt(question: str, plan: list[str], evidence: list[dict], report: dict) -> str:
    return f"""Question:
{question}

Plan:
{plan}

SQL evidence:
{evidence}

Draft report:
{report}

Evaluate whether the report is supported by the evidence and directly answers the question.
"""
