from __future__ import annotations

import sqlite3
from dataclasses import dataclass


TABLE_DESCRIPTIONS = {
    "customers": "Customer profile table with region, signup date, and segment for retention and regional analysis.",
    "products": "Product catalog table with SKU, category, cost, and active status for product performance analysis.",
    "orders": "Order header table with customer, order date, region, and status for revenue trend analysis.",
    "order_items": "Line item table joining orders to products with quantity, unit price, and discounts. Revenue is quantity times unit_price times one minus discount_rate.",
}

BUSINESS_TERMS = {
    "revenue": "Revenue is calculated from order_items.quantity * order_items.unit_price * (1 - order_items.discount_rate).",
    "growth": "Growth compares revenue between two time periods, typically month-over-month or quarter-over-quarter.",
    "retention": "Retention compares repeat ordering behavior by customer signup cohort or order history.",
    "region": "Regional insights use customers.region or orders.region depending on whether the question asks customer location or transaction region.",
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
        for table in tables:
            columns = self._columns_for(table)
            column_text = ", ".join(f"{name} {kind}" for name, kind in columns)
            description = TABLE_DESCRIPTIONS.get(table, f"Database table named {table}.")
            documents.append(
                SchemaDocument(
                    id=f"table:{table}",
                    text=f"Table {table}: {description} Columns: {column_text}.",
                    metadata={"kind": "table", "table": table},
                )
            )

        documents.extend(self._relationship_documents(tables))
        for term, description in BUSINESS_TERMS.items():
            documents.append(
                SchemaDocument(
                    id=f"term:{term}",
                    text=f"Business term {term}: {description}",
                    metadata={"kind": "business_term", "term": term},
                )
            )
        return documents

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
