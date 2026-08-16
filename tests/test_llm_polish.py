import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from agent_platform.analytics.service import AnalyticsAgentService
from agent_platform.data.seed_data import seed_database
from agent_platform.llms.groq_client import GroqClient
import shutil

_cached_db_path = None

def get_test_db(tmpdir_name: str) -> Path:
    global _cached_db_path
    if _cached_db_path is None or not Path(_cached_db_path).exists():
        temp_cache_dir = Path(tempfile.gettempdir()) / "agent_platform_test_cache"
        temp_cache_dir.mkdir(parents=True, exist_ok=True)
        cached_file = temp_cache_dir / "analytics_test.db"
        if not cached_file.exists():
            seed_database(cached_file)
        _cached_db_path = cached_file
        
    db_path = Path(tmpdir_name) / "analytics.db"
    shutil.copy(_cached_db_path, db_path)
    return db_path


class MockLLMClient:
    @property
    def enabled(self) -> bool:
        return True

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
        response_model: Any | None = None
    ) -> dict[str, Any]:
        model_name = response_model.__name__ if response_model else ""
        
        if model_name == "QueryPlanOutput":
            return {
                "intent": "Identify top products by revenue growth",
                "metric": "total revenue",
                "entity": "product_category_name",
                "aggregation": "SUM",
                "filters": ["order_status IN ('delivered', 'shipped', 'invoiced')"],
                "group_by": ["product_category_name"],
                "ordering": "revenue DESC",
                "limit": 10,
                "required_tables": ["order_items", "orders", "products"],
                "reasoning": "Question asks for top products by revenue, so sum price grouped by category."
            }
        elif model_name == "SQLOutput":
            return {
                "sql": "SELECT p.product_category_name AS category, ROUND(SUM(oi.price), 2) AS revenue FROM order_items oi JOIN products p ON p.product_id = oi.product_id GROUP BY p.product_category_name ORDER BY revenue DESC LIMIT 3",
                "reasoning": "Generate read-only SQL join targeting order items and products."
            }
        elif model_name == "EvaluatorOutput":
            return {
                "summary": "Revenue has grown strongly due to the leading categories.",
                "key_findings": ["Top categories grew by 15%", "Regional contribution is robust"],
                "why_explanation": "Strong causal drivers in product distribution.",
                "anomalies": ["Outlier in category X"],
                "confidence": 0.95,
                "confidence_explanation": "High confidence due to verified read-only metrics.",
                "issues": [],
                "validated": True,
                "reasoning": "Outputs match planning and evidence metrics.",
                "verdict": "accurate",
                "detected_contradictions": []
            }
            
        # Fallbacks for non-model completion calls
        if "plan" in system_prompt.lower() and "evaluator" not in system_prompt.lower():
            return {
                "intent": "Identify top products by revenue growth",
                "metric": "total revenue",
                "entity": "product_category_name",
                "aggregation": "SUM",
                "filters": ["order_status IN ('delivered', 'shipped', 'invoiced')"],
                "group_by": ["product_category_name"],
                "ordering": "revenue DESC",
                "limit": 10,
                "required_tables": ["order_items", "orders", "products"],
                "reasoning": "Question asks for top products by revenue, so sum price grouped by category."
            }
        elif "sql" in system_prompt.lower() and "evaluator" not in system_prompt.lower():
            return {
                "sql": "SELECT p.product_category_name AS category, ROUND(SUM(oi.price), 2) AS revenue FROM order_items oi JOIN products p ON p.product_id = oi.product_id GROUP BY p.product_category_name ORDER BY revenue DESC LIMIT 3",
                "reasoning": "Generate read-only SQL join targeting order items and products."
            }
        else:
            return {
                "summary": "Revenue has grown strongly due to the leading categories.",
                "key_findings": ["Top categories grew by 15%", "Regional contribution is robust"],
                "why_explanation": "Strong causal drivers in product distribution.",
                "anomalies": ["Outlier in category X"],
                "confidence": 0.95,
                "confidence_explanation": "High confidence due to verified read-only metrics.",
                "issues": [],
                "validated": True,
                "reasoning": "Outputs match planning and evidence metrics.",
                "verdict": "accurate",
                "detected_contradictions": []
            }


class FakeGroqTransport:
    def __init__(self):
        self.requests = []

    def __call__(self, request, *args, **kwargs):
        self.requests.append(request)
        body = json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "steps": ["inspect schema", "calculate revenue growth"],
                                    "reasoning": "Need schema first, then SQL-backed metrics.",
                                    "sql": "SELECT 1 AS metric",
                                    "confidence": 0.88,
                                    "issues": [],
                                    "validated": True,
                                }
                              )
                        }
                    }
                ]
            }
        ).encode("utf-8")

        class Response:
            def read(self):
                return body

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        return Response()


class LLMPolishTests(unittest.TestCase):
    def test_groq_client_sends_configurable_model_and_parses_json(self):
        transport = FakeGroqTransport()
        client = GroqClient(
            api_key="test-key",
            model="llama-3.3-70b-versatile",
            transport=transport,
        )

        result = client.complete_json(
            system_prompt="Return JSON.",
            user_prompt="Plan this.",
        )

        self.assertEqual(result["steps"], ["inspect schema", "calculate revenue growth"])
        sent_body = json.loads(transport.requests[0].data.decode("utf-8"))
        self.assertEqual(sent_body["model"], "llama-3.3-70b-versatile")
        self.assertEqual(sent_body["response_format"], {"type": "json_object"})

    def test_report_shape_contains_sql_queries_and_execution_trace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = get_test_db(tmpdir)
            mock_client = MockLLMClient()
            service = AnalyticsAgentService.from_sqlite(db_path, llm_client=mock_client)

            result = asyncio.run(
                service.analyze("What products drove the highest revenue growth?")
            )

        self.assertIn("sql_queries", result)
        self.assertIn("steps", result)
        self.assertGreater(len(result["sql_queries"]), 0)
        self.assertGreater(len(result["steps"]), 0)
        first_step = result["steps"][0]
        self.assertIn("reasoning", first_step)
        self.assertIn("execution_time_ms", first_step)

    def test_gitignore_excludes_env_files(self):
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".env", gitignore)
        self.assertIn(".env.*", gitignore)


if __name__ == "__main__":
    unittest.main()
