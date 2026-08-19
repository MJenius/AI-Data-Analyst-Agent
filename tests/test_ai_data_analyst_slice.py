import asyncio
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_platform.analytics.service import AnalyticsAgentService
from agent_platform.data.seed_data import seed_database
from agent_platform.rag.ingestion.schema_context import SchemaContextBuilder
from agent_platform.rag.retriever import SchemaRetriever
from agent_platform.tools.sql_tool import SQLSafetyError, SQLTool


_cached_db_path = None

def get_test_db(tmpdir_name: str) -> Path:
    """Creates a seeded DB once and returns rapid shutil copies for subsequent test runs."""
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
    """Mock LLM client to prevent live network dependency during local unit tests."""
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
                "entities": ["product_category_name"],
                "entity": "product_category_name",
                "metric": "total revenue",
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


class AIDataAnalystSliceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = get_test_db(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_sql_tool_executes_read_only_query_with_structured_output(self):
        tool = SQLTool(database_url=f"sqlite:///{self.db_path}")

        result = tool.execute(
            """
            SELECT p.product_category_name AS category, ROUND(SUM(oi.price), 2) AS revenue
            FROM order_items oi
            JOIN products p ON p.product_id = oi.product_id
            GROUP BY p.product_category_name
            ORDER BY revenue DESC
            LIMIT 3
            """
        )

        self.assertEqual(result["row_count"], 3)
        self.assertIn("execution_time_ms", result)
        self.assertTrue(len(result["rows"]) > 0)
        self.assertIn("category", result["rows"][0])
        self.assertGreater(result["rows"][0]["revenue"], 0)

    def test_sql_tool_blocks_destructive_queries(self):
        tool = SQLTool(database_url=f"sqlite:///{self.db_path}")

        with self.assertRaises(SQLSafetyError):
            tool.execute("DROP TABLE orders")

    def test_schema_retriever_returns_join_context_for_revenue_growth(self):
        connection = sqlite3.connect(self.db_path)
        try:
            schema_documents = SchemaContextBuilder(connection).build()
        finally:
            connection.close()
        retriever = SchemaRetriever.from_documents(schema_documents)

        context = retriever.retrieve(
            "What products drove the highest revenue growth by region?",
            top_k=4,
        )

        joined = "\n".join(item.text for item in context)
        self.assertIn("orders", joined)
        self.assertIn("order_items", joined)
        self.assertIn("products", joined)
        self.assertIn("revenue", joined.lower())

    def test_end_to_end_agent_generates_validated_analytics_report(self):
        mock_client = MockLLMClient()
        service = AnalyticsAgentService.from_sqlite(self.db_path, llm_client=mock_client)

        report = asyncio.run(
            service.analyze("What products drove the highest revenue growth?")
        )

        self.assertIn("summary", report)
        self.assertGreater(len(report["key_findings"]), 0)
        self.assertGreater(len(report["sql_queries"]), 0)
        self.assertGreater(len(report["steps"]), 0)
        self.assertGreaterEqual(report["confidence"], 0.7)


if __name__ == "__main__":
    unittest.main()
