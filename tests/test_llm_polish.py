import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_platform.analytics.service import AnalyticsAgentService
from agent_platform.data.seed_data import seed_database
from agent_platform.llms.groq_client import GroqClient


class FakeGroqTransport:
    def __init__(self):
        self.requests = []

    def __call__(self, request):
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
            db_path = Path(tmpdir) / "analytics.db"
            seed_database(db_path)
            service = AnalyticsAgentService.from_sqlite(db_path)

            result = asyncio.run(
                service.analyze("What products drove the highest revenue growth?")
            )

        self.assertIn("sql_queries", result["report"])
        self.assertIn("execution_trace", result["report"])
        self.assertGreater(len(result["report"]["sql_queries"]), 0)
        self.assertGreater(len(result["report"]["execution_trace"]["steps"]), 0)
        first_step = result["report"]["execution_trace"]["steps"][0]
        self.assertIn("reasoning", first_step)
        self.assertIn("execution_time_ms", first_step)

    def test_gitignore_excludes_env_files(self):
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".env", gitignore)
        self.assertIn(".env.*", gitignore)


if __name__ == "__main__":
    unittest.main()
