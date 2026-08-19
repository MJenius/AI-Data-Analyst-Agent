from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path

from agent_platform.rag.ingestion.schema_context import SchemaContextBuilder
from agent_platform.rag.retriever import SchemaRetriever
from agent_platform.tools.sql_tool import SQLValidationError, SQLValidator


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "analytics.db"


def _retriever() -> SchemaRetriever:
    connection = sqlite3.connect(DB_PATH)
    try:
        documents = SchemaContextBuilder(connection).build()
    finally:
        connection.close()
    return SchemaRetriever.from_documents(documents, use_semantic=False)


def _validator() -> SQLValidator:
    return SQLValidator(DB_PATH)


class SQLValidatorRegressionTests(unittest.TestCase):
    """Regression tests for Phase 3 failure patterns: bad columns, joins, and tables."""

    def setUp(self) -> None:
        self.validator = _validator()
        self.allowed = {"orders", "order_items", "customers"}

    def test_rejects_nonexistent_table(self) -> None:
        sql = "SELECT COUNT(*) FROM order_line_items"
        with self.assertRaises(SQLValidationError) as ctx:
            self.validator.validate(sql)
        self.assertTrue(any("nonexistent_table" in error for error in ctx.exception.errors))

    def test_rejects_hallucinated_column_order_date(self) -> None:
        sql = (
            "SELECT COUNT(*) FROM orders "
            "WHERE DATE(orders.order_date) BETWEEN '2017-01-01' AND '2017-12-31'"
        )
        with self.assertRaises(SQLValidationError) as ctx:
            self.validator.validate(sql, self.allowed)
        self.assertTrue(any("nonexistent_column" in error for error in ctx.exception.errors))

    def test_rejects_hallucinated_quantity_column(self) -> None:
        sql = "SELECT SUM(quantity) FROM order_items"
        with self.assertRaises(SQLValidationError) as ctx:
            self.validator.validate(sql, {"order_items"})
        self.assertTrue(any("nonexistent_column" in error for error in ctx.exception.errors))

    def test_rejects_invalid_join_key(self) -> None:
        sql = (
            "SELECT SUM(oi.price) AS revenue "
            "FROM order_items oi "
            "JOIN orders o ON oi.product_id = o.order_id"
        )
        with self.assertRaises(SQLValidationError) as ctx:
            self.validator.validate(sql, {"order_items", "orders"})
        self.assertTrue(any("invalid_join" in error for error in ctx.exception.errors))

    def test_rejects_table_outside_retrieved_context(self) -> None:
        sql = "SELECT COUNT(*) FROM sellers"
        with self.assertRaises(SQLValidationError) as ctx:
            self.validator.validate(sql, {"orders"})
        self.assertTrue(any("table_not_in_context" in error for error in ctx.exception.errors))

    def test_accepts_canonical_revenue_query(self) -> None:
        sql = (
            "SELECT SUM(oi.price) AS revenue "
            "FROM order_items oi "
            "JOIN orders o ON oi.order_id = o.order_id "
            "WHERE o.order_purchase_timestamp >= '2017-01-01'"
        )
        result = self.validator.validate(sql, {"order_items", "orders"})
        self.assertIn("order_items", result.tables)
        self.assertIn("orders", result.tables)

    def test_rejects_malformed_sql(self) -> None:
        with self.assertRaises(SQLValidationError) as ctx:
            self.validator.validate("SELECT COUNT(*) FROM")
        self.assertTrue(any("malformed_sql" in error for error in ctx.exception.errors))

    def test_rejects_multiple_statements(self) -> None:
        sql = "SELECT 1; SELECT 2"
        with self.assertRaises(SQLValidationError) as ctx:
            self.validator.validate(sql)
        self.assertTrue(any("unsafe_sql" in error for error in ctx.exception.errors))


class GroundedRetrievalRegressionTests(unittest.TestCase):
    """Regression tests for column-aware retrieval and join-path preservation."""

    def setUp(self) -> None:
        self.retriever = _retriever()

    def _tables(self, question: str) -> set[str]:
        return {
            item.metadata["table"]
            for item in self.retriever.retrieve_grounded(question)
            if item.metadata.get("table")
        }

    def _relationships(self, question: str) -> list[str]:
        return [
            item.text
            for item in self.retriever.retrieve_grounded(question)
            if item.metadata.get("kind") == "relationship"
        ]

    def test_revenue_question_grounds_order_items(self) -> None:
        tables = self._tables("What is total revenue by month?")
        self.assertIn("order_items", tables)
        self.assertIn("orders", tables)

    def test_revenue_context_includes_price_column_packet(self) -> None:
        context = self.retriever.retrieve_grounded("What is total revenue by product category?")
        column_ids = {item.id for item in context if item.metadata.get("kind") == "column"}
        self.assertIn("column:order_items.price", column_ids)

    def test_customer_region_question_includes_customers_and_orders(self) -> None:
        tables = self._tables("What is average order value by customer state?")
        self.assertIn("customers", tables)
        self.assertIn("orders", tables)

    def test_product_category_question_includes_translation_path(self) -> None:
        tables = self._tables("Top product categories by revenue in English")
        self.assertIn("products", tables)
        self.assertIn("product_category_name_translation", tables)

    def test_multi_table_question_expands_join_relationships(self) -> None:
        relationships = self._relationships("Average review score by seller state")
        joined = " ".join(relationships)
        self.assertIn("order_items.seller_id = sellers.seller_id", joined)
        self.assertIn("order_items.order_id = orders.order_id", joined)

    def test_business_term_revenue_definition_in_context(self) -> None:
        context = self.retriever.retrieve_grounded("How much revenue did we make last year?")
        terms = [item.text for item in context if item.metadata.get("kind") == "business_term"]
        self.assertTrue(any("SUM(order_items.price)" in text for text in terms))

    def test_order_date_business_term_uses_purchase_timestamp(self) -> None:
        context = self.retriever.retrieve_grounded("Show monthly order count by order date")
        terms = [item.text for item in context if item.metadata.get("kind") == "business_term"]
        self.assertTrue(any("order_purchase_timestamp" in text for text in terms))

    def test_grounded_subset_caps_tables(self) -> None:
        tables = self._tables("Revenue, payments, reviews, sellers, and delivery time by state")
        self.assertLessEqual(len(tables), 6)


if __name__ == "__main__":
    unittest.main()
