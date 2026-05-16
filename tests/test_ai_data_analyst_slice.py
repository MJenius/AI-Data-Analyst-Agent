import asyncio
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_platform.analytics.service import AnalyticsAgentService
from agent_platform.data.seed_data import seed_database
from agent_platform.rag.ingestion.schema_context import SchemaContextBuilder
from agent_platform.rag.retriever import SchemaRetriever
from agent_platform.tools.sql_tool import SQLSafetyError, SQLTool


class AIDataAnalystSliceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "analytics.db"
        seed_database(self.db_path)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_sql_tool_executes_read_only_query_with_structured_output(self):
        tool = SQLTool(database_url=f"sqlite:///{self.db_path}")

        result = tool.execute(
            """
            SELECT p.category, ROUND(SUM(oi.quantity * oi.unit_price), 2) AS revenue
            FROM order_items oi
            JOIN products p ON p.id = oi.product_id
            GROUP BY p.category
            ORDER BY revenue DESC
            LIMIT 3
            """
        )

        self.assertEqual(result["row_count"], 3)
        self.assertIn("execution_time_ms", result)
        self.assertEqual(result["rows"][0]["category"], "Analytics")
        self.assertGreater(result["rows"][0]["revenue"], 0)

    def test_sql_tool_blocks_destructive_queries(self):
        tool = SQLTool(database_url=f"sqlite:///{self.db_path}")

        with self.assertRaises(SQLSafetyError):
            tool.execute("DROP TABLE orders")

    def test_schema_retriever_returns_join_context_for_revenue_question(self):
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
        service = AnalyticsAgentService.from_sqlite(self.db_path)

        report = asyncio.run(
            service.analyze("What products drove the highest revenue growth?")
        )

        self.assertTrue(report["evaluation"]["validated"])
        self.assertGreaterEqual(report["evaluation"]["confidence"], 0.7)
        self.assertIn("summary", report["report"])
        self.assertGreater(len(report["report"]["key_findings"]), 0)
        self.assertGreater(len(report["generated_sql"]), 0)
        self.assertGreater(len(report["trace"]), 0)


if __name__ == "__main__":
    unittest.main()
