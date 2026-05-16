from __future__ import annotations

import sqlite3
from dataclasses import dataclass


TABLE_DESCRIPTIONS = {
    "customers": "Customer profiles including unique IDs, city, and state for demographic analysis.",
    "geolocation": "Coordinate mapping for Brazilian zip codes, used for spatial and mapping analysis.",
    "order_items": "Details for each product in an order including price, freight value, and shipping dates.",
    "order_payments": "Transaction details such as payment type, installments, and total value paid.",
    "order_reviews": "Customer feedback including scores and text comments for sentiment analysis.",
    "orders": "Primary order records with status and full lifecycle timestamps (purchase to delivery).",
    "products": "Product catalog with categories and physical dimensions.",
    "sellers": "Seller information including city and state.",
    "product_category_name_translation": "Lookup table translating Portuguese category names to English.",
}

BUSINESS_TERMS = {
    "revenue": "Total revenue is calculated as the sum of price in order_items. Do not include freight_value unless specifically asked for total value.",
    "freight": "Freight represents the shipping cost for an item. Total order cost is price + freight_value.",
    "delivery_time": "Delivery time is the duration between order_purchase_timestamp and order_delivered_customer_date.",
    "customer_satisfaction": "Measured by review_score in the order_reviews table, ranging from 1 to 5.",
    "region": "Regional analysis can be performed using customer_state or seller_state.",
}


@dataclass(slots=True)
class SchemaDocument:
    id: str
    text: str
    metadata: dict[str, str]


class SchemaContextBuilder:
    """Builds searchable schema documents from database metadata and business semantics."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def build(self) -> list[SchemaDocument]:
        documents: list[SchemaDocument] = []
        tables = self._table_names()
        
        # 1. Global Schema Summary
        all_tables_text = ", ".join(tables)
        
        # Add temporal bounds if orders table exists
        temporal_bounds = ""
        if "orders" in tables:
            try:
                row = self._connection.execute("SELECT MIN(order_purchase_timestamp), MAX(order_purchase_timestamp) FROM orders").fetchone()
                if row and row[0] and row[1]:
                    temporal_bounds = f" The dataset spans from {row[0]} to {row[1]}."
            except sqlite3.Error:
                pass

        documents.append(
            SchemaDocument(
                id="schema:summary",
                text=(
                    f"Database schema contains {len(tables)} tables: {all_tables_text}."
                    f"{temporal_bounds} Useful for high-level planning and year-specific filters."
                ),
                metadata={"kind": "schema_summary"}
            )
        )

        for table in tables:
            columns = self._columns_for(table)
            column_details = []
            for name, kind in columns:
                desc = self._infer_column_description(table, name)
                column_details.append(f"- {name} ({kind}): {desc}")
            
            column_text = "\n".join(column_details)
            table_desc = TABLE_DESCRIPTIONS.get(table, f"Database table named {table}.")
            
            # 2. Detailed Table Document
            documents.append(
                SchemaDocument(
                    id=f"table:{table}",
                    text=(
                        f"Table: {table}\n"
                        f"Description: {table_desc}\n"
                        f"Columns:\n{column_text}"
                    ),
                    metadata={"kind": "table", "table": table},
                )
            )

        # 3. Relationships
        documents.extend(self._relationship_documents(tables))

        # 4. Business Semantics
        for term, description in BUSINESS_TERMS.items():
            documents.append(
                SchemaDocument(
                    id=f"term:{term}",
                    text=f"Business Concept: {term}\nLogic: {description}",
                    metadata={"kind": "business_term", "term": term},
                )
            )
        return documents

    def _infer_column_description(self, table: str, column: str) -> str:
        lowered = column.lower()
        if lowered == "id": return "Primary key unique identifier."
        if "date" in lowered: return "Timestamp/date field for temporal analysis."
        if "price" in lowered or "cost" in lowered: return "Monetary value (REAL/NUMERIC)."
        if "rate" in lowered or "discount" in lowered: return "Percentage or multiplier."
        if "region" in lowered: return "Geographic category for regional segmentation."
        if "category" in lowered or "segment" in lowered: return "Categorical grouping field."
        if "status" in lowered: return "Operational state (e.g., active, paid, shipped)."
        return f"Attribute field in {table}."

    def _table_names(self) -> list[str]:
        rows = self._connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return [row[0] for row in rows]

    def _columns_for(self, table: str) -> list[tuple[str, str]]:
        rows = self._connection.execute(f"PRAGMA table_info({table})").fetchall()
        return [(row[1], row[2]) for row in rows]

    def _relationship_documents(self, tables: list[str]) -> list[SchemaDocument]:
        documents: list[SchemaDocument] = []
        for table in tables:
            foreign_keys = self._connection.execute(f"PRAGMA foreign_key_list({table})").fetchall()
            for key in foreign_keys:
                documents.append(
                    SchemaDocument(
                        id=f"relationship:{table}.{key[3]}->{key[2]}.{key[4]}",
                        text=f"Relationship: {table}.{key[3]} joins to {key[2]}.{key[4]}.",
                        metadata={"kind": "relationship", "from_table": table, "to_table": key[2]},
                    )
                )
        return documents
