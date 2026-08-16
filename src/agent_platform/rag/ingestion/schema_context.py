from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any


TABLE_DESCRIPTIONS = {
    "customers": "One row per order-level customer ID; customer_unique_id links the same buyer across orders.",
    "geolocation": "Many coordinate observations per Brazilian zip-code prefix; aggregate to one row per prefix before joining.",
    "order_items": "One row per item position in an order. Row count is item quantity; price is item revenue excluding freight.",
    "order_payments": "One row per payment attempt/sequence for an order; an order can have multiple payment rows.",
    "order_reviews": "Customer review facts keyed by review_id and linked to an order.",
    "orders": "One row per order with customer, status, purchase, approval, shipping, delivery, and estimated-delivery timestamps.",
    "products": "One row per product with Portuguese category and physical/catalog attributes.",
    "sellers": "One row per seller with city, state, and zip-code prefix.",
    "product_category_name_translation": "One row per Portuguese product category with its English translation.",
}

TABLE_GRAINS = {
    "customers": "customer_id",
    "geolocation": "geolocation observation (not unique by zip-code prefix)",
    "order_items": "(order_id, order_item_id)",
    "order_payments": "(order_id, payment_sequential)",
    "order_reviews": "review_id",
    "orders": "order_id",
    "products": "product_id",
    "sellers": "seller_id",
    "product_category_name_translation": "product_category_name",
}

# pandas.to_sql(..., if_exists="replace") removed constraints from the existing
# benchmark database. These are the canonical keys declared by data/schema.sql.
CANONICAL_PRIMARY_KEYS = {
    "customers": ("customer_id",),
    "order_items": ("order_id", "order_item_id"),
    "order_payments": ("order_id", "payment_sequential"),
    "order_reviews": ("review_id",),
    "orders": ("order_id",),
    "products": ("product_id",),
    "sellers": ("seller_id",),
    "product_category_name_translation": ("product_category_name",),
}

# from_table, from_column, to_table, to_column, relationship kind, usage note
JOIN_RELATIONSHIPS = (
    ("orders", "customer_id", "customers", "customer_id", "many-to-one", "order customer"),
    ("order_items", "order_id", "orders", "order_id", "many-to-one", "items in an order"),
    ("order_items", "product_id", "products", "product_id", "many-to-one", "item product"),
    ("order_items", "seller_id", "sellers", "seller_id", "many-to-one", "item seller"),
    ("order_payments", "order_id", "orders", "order_id", "many-to-one", "payments for an order"),
    ("order_reviews", "order_id", "orders", "order_id", "many-to-one", "reviews for an order"),
    (
        "products",
        "product_category_name",
        "product_category_name_translation",
        "product_category_name",
        "many-to-one",
        "Portuguese-to-English category lookup",
    ),
    (
        "customers",
        "customer_zip_code_prefix",
        "geolocation",
        "geolocation_zip_code_prefix",
        "many-to-many lookup",
        "aggregate geolocation by prefix first to avoid multiplying rows",
    ),
    (
        "sellers",
        "seller_zip_code_prefix",
        "geolocation",
        "geolocation_zip_code_prefix",
        "many-to-many lookup",
        "aggregate geolocation by prefix first to avoid multiplying rows",
    ),
)

COLUMN_DESCRIPTIONS = {
    "order_items.order_item_id": "1-based item position within an order; COUNT(*) represents item quantity.",
    "order_items.price": "Item selling price and canonical revenue measure; excludes freight_value.",
    "order_items.freight_value": "Shipping charge for the item; include only when the question asks for freight or total paid cost.",
    "orders.order_purchase_timestamp": "Order placement timestamp and canonical order date.",
    "orders.order_status": "Order lifecycle status.",
    "orders.order_delivered_customer_date": "Actual customer delivery timestamp.",
    "orders.order_estimated_delivery_date": "Promised/estimated customer delivery timestamp.",
    "customers.customer_id": "Order-level customer identifier used by orders.customer_id.",
    "customers.customer_unique_id": "Stable buyer identifier used for repeat-customer analysis.",
    "products.product_category_name": "Portuguese product category; join the translation table for English names.",
    "order_payments.payment_value": "Amount recorded for one payment sequence; aggregate at order grain before joining item facts.",
    "order_reviews.review_score": "Integer customer rating from 1 through 5.",
}

BUSINESS_TERMS = {
    "revenue": {
        "description": "SUM(order_items.price). Do not multiply by a quantity column and do not include freight unless requested.",
        "tables": ("order_items",),
        "columns": ("order_items.price",),
    },
    "item quantity": {
        "description": "There is no quantity column. Each order_items row is one item position; use COUNT(*) or COUNT(order_item_id).",
        "tables": ("order_items",),
        "columns": ("order_items.order_item_id",),
    },
    "order date": {
        "description": "orders.order_purchase_timestamp is the canonical order placement date; there is no order_date column.",
        "tables": ("orders",),
        "columns": ("orders.order_purchase_timestamp",),
    },
    "order count": {
        "description": "COUNT(DISTINCT orders.order_id), or COUNT(*) when querying only the one-row-per-order orders table.",
        "tables": ("orders",),
        "columns": ("orders.order_id",),
    },
    "order value aov": {
        "description": "SUM(order_items.price) divided by COUNT(DISTINCT order_items.order_id), after aggregating item revenue at order grain when needed.",
        "tables": ("order_items",),
        "columns": ("order_items.price", "order_items.order_id"),
    },
    "delivery time": {
        "description": "Elapsed time from orders.order_purchase_timestamp to orders.order_delivered_customer_date.",
        "tables": ("orders",),
        "columns": ("orders.order_purchase_timestamp", "orders.order_delivered_customer_date"),
    },
    "late delivery": {
        "description": "Actual orders.order_delivered_customer_date later than orders.order_estimated_delivery_date.",
        "tables": ("orders",),
        "columns": ("orders.order_delivered_customer_date", "orders.order_estimated_delivery_date"),
    },
    "customer": {
        "description": "Use customers.customer_unique_id for a stable buyer across orders; customer_id is order-level.",
        "tables": ("customers", "orders"),
        "columns": ("customers.customer_unique_id", "customers.customer_id", "orders.customer_id"),
    },
    "product category": {
        "description": "products.product_category_name is Portuguese; translate only when English labels are requested.",
        "tables": ("products",),
        "columns": ("products.product_category_name",),
    },
    "product purchase bought item": {
        "description": "Products purchased in the same order are represented by separate order_items rows sharing order_id.",
        "tables": ("products", "order_items"),
        "columns": ("products.product_id", "order_items.product_id", "order_items.order_id"),
    },
    "payment": {
        "description": "order_payments can contain multiple rows per order. Aggregate payment rows before joining another one-to-many fact table.",
        "tables": ("order_payments", "orders"),
        "columns": ("order_payments.order_id", "order_payments.payment_type", "order_payments.payment_value"),
    },
    "review rating": {
        "description": "Customer satisfaction is order_reviews.review_score on a 1-to-5 scale.",
        "tables": ("order_reviews", "orders"),
        "columns": ("order_reviews.review_score", "order_reviews.order_id"),
    },
    "seller": {
        "description": "Seller attributes are in sellers and sales facts link through order_items.seller_id.",
        "tables": ("sellers",),
        "columns": ("sellers.seller_id",),
    },
    "customer region state": {
        "description": "Customer geography uses customers.customer_state.",
        "tables": ("customers",),
        "columns": ("customers.customer_state",),
    },
    "seller region state": {
        "description": "Seller geography uses sellers.seller_state.",
        "tables": ("sellers",),
        "columns": ("sellers.seller_state",),
    },
    "payment order region state": {
        "description": "Payment/order geography uses the order's customer via orders.customer_id, then customers.customer_state.",
        "tables": ("order_payments", "orders", "customers"),
        "columns": ("order_payments.order_id", "orders.customer_id", "customers.customer_state"),
    },
    "delivery order region state": {
        "description": "Delivery geography uses the order's customer via orders.customer_id, then customers.customer_state.",
        "tables": ("orders", "customers"),
        "columns": ("orders.customer_id", "customers.customer_state"),
    },
    "distance location": {
        "description": "Geolocation has repeated rows per zip prefix and must be aggregated before a coordinate join.",
        "tables": ("geolocation", "customers", "sellers"),
        "columns": ("geolocation.geolocation_lat", "geolocation.geolocation_lng", "customers.customer_zip_code_prefix", "sellers.seller_zip_code_prefix"),
    },
    "month trend": {
        "description": "Order time-series analysis uses orders.order_purchase_timestamp unless another lifecycle timestamp is explicitly requested.",
        "tables": ("orders",),
        "columns": ("orders.order_purchase_timestamp",),
    },
}

CATEGORICAL_COLUMNS = {
    "customer_state",
    "seller_state",
    "order_status",
    "payment_type",
    "payment_installments",
    "review_score",
}


@dataclass(slots=True)
class SchemaDocument:
    id: str
    text: str
    metadata: dict[str, str]


class SchemaContextBuilder:
    """Build exact, searchable schema packets from SQLite metadata and business semantics."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def build(self) -> list[SchemaDocument]:
        tables = self._table_names()
        table_columns = {table: self._columns_for(table) for table in tables}
        relationships = [rel for rel in JOIN_RELATIONSHIPS if rel[0] in tables and rel[2] in tables]
        documents = [self._summary_document(tables)]

        for table in tables:
            columns = table_columns[table]
            row_count, null_counts = self._table_stats(table, columns)
            column_lines = []
            for column in columns:
                name, kind, declared_pk = column["name"], column["type"], column["pk"]
                qualified = f"{table}.{name}"
                tags = []
                if declared_pk or name in CANONICAL_PRIMARY_KEYS.get(table, ()):
                    tags.append("PRIMARY KEY")
                for from_table, from_col, to_table, to_col, _, _ in relationships:
                    if (table, name) == (from_table, from_col):
                        tags.append(f"FOREIGN KEY -> {to_table}.{to_col}")
                stats = self._column_stats(table, name, kind, row_count, null_counts.get(name, 0))
                tag_text = f" [{'; '.join(tags)}]" if tags else ""
                description = self._column_description(table, name)
                column_lines.append(f"- {name} {kind or 'UNKNOWN'}{tag_text}: {description}{stats}")
                documents.append(
                    SchemaDocument(
                        id=f"column:{qualified}",
                        text=f"Column: {qualified}\nType: {kind or 'UNKNOWN'}{tag_text}\nMeaning: {description}{stats}",
                        metadata={"kind": "column", "table": table, "column": name},
                    )
                )

            primary_keys = [column["name"] for column in columns if column["pk"]]
            if not primary_keys:
                primary_keys = list(CANONICAL_PRIMARY_KEYS.get(table, ()))
            table_relationships = [rel for rel in relationships if table in (rel[0], rel[2])]
            joins = "\n".join(
                f"- {left}.{left_col} = {right}.{right_col} ({kind}; {note})"
                for left, left_col, right, right_col, kind, note in table_relationships
            ) or "- none"
            documents.append(
                SchemaDocument(
                    id=f"table:{table}",
                    text=(
                        f"Table: {table}\n"
                        f"Description: {TABLE_DESCRIPTIONS.get(table, f'Database table named {table}.')}\n"
                        f"Grain: {TABLE_GRAINS.get(table, 'one database row')}\n"
                        f"Rows: {row_count}\n"
                        f"Primary key: {', '.join(primary_keys) if primary_keys else 'none declared'}\n"
                        f"Exact columns:\n{'\n'.join(column_lines)}\n"
                        f"Allowed join relationships:\n{joins}"
                    ),
                    metadata={"kind": "table", "table": table},
                )
            )

        documents.extend(self._relationship_documents(relationships))
        for term, definition in BUSINESS_TERMS.items():
            documents.append(
                SchemaDocument(
                    id=f"term:{term.replace(' ', '_')}",
                    text=(
                        f"Business concept: {term}\n"
                        f"Definition: {definition['description']}\n"
                        f"Grounded tables: {', '.join(definition['tables'])}\n"
                        f"Grounded columns: {', '.join(definition['columns'])}"
                    ),
                    metadata={
                        "kind": "business_term",
                        "term": term,
                        "tables": ",".join(definition["tables"]),
                        "columns": ",".join(definition["columns"]),
                    },
                )
            )
        return documents

    def _summary_document(self, tables: list[str]) -> SchemaDocument:
        temporal_bounds = ""
        if "orders" in tables:
            row = self._connection.execute(
                "SELECT MIN(order_purchase_timestamp), MAX(order_purchase_timestamp) FROM orders"
            ).fetchone()
            if row and row[0] and row[1]:
                temporal_bounds = f" Dataset order dates span {row[0]} through {row[1]}."
        return SchemaDocument(
            id="schema:summary",
            text=f"Database tables ({len(tables)}): {', '.join(tables)}.{temporal_bounds}",
            metadata={"kind": "schema_summary"},
        )

    def _table_names(self) -> list[str]:
        rows = self._connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        return [row[0] for row in rows]

    def _columns_for(self, table: str) -> list[dict[str, Any]]:
        rows = self._connection.execute(f"PRAGMA table_info({self._quote(table)})").fetchall()
        return [{"name": row[1], "type": row[2], "pk": bool(row[5])} for row in rows]

    def _table_stats(self, table: str, columns: list[dict[str, Any]]) -> tuple[int, dict[str, int]]:
        null_exprs = ", ".join(
            f"SUM(CASE WHEN {self._quote(column['name'])} IS NULL THEN 1 ELSE 0 END)" for column in columns
        )
        row = self._connection.execute(
            f"SELECT COUNT(*){', ' + null_exprs if null_exprs else ''} FROM {self._quote(table)}"
        ).fetchone()
        return int(row[0]), {column["name"]: int(value or 0) for column, value in zip(columns, row[1:])}

    def _column_stats(self, table: str, column: str, kind: str, rows: int, nulls: int) -> str:
        details = [f"nulls={nulls} ({(nulls / rows * 100 if rows else 0):.1f}%)"]
        quoted_table, quoted_column = self._quote(table), self._quote(column)
        lowered = column.lower()
        if kind.upper() in {"INTEGER", "REAL", "NUMERIC", "DECIMAL", "FLOAT"} or any(
            marker in lowered for marker in ("date", "timestamp")
        ):
            minimum, maximum = self._connection.execute(
                f"SELECT MIN({quoted_column}), MAX({quoted_column}) FROM {quoted_table}"
            ).fetchone()
            details.append(f"range={self._display(minimum)}..{self._display(maximum)}")
        if column in CATEGORICAL_COLUMNS:
            values = self._connection.execute(
                f"SELECT {quoted_column}, COUNT(*) AS n FROM {quoted_table} "
                f"WHERE {quoted_column} IS NOT NULL GROUP BY {quoted_column} ORDER BY n DESC, {quoted_column} LIMIT 5"
            ).fetchall()
            details.append("common_values=" + ", ".join(f"{self._display(value)} ({count})" for value, count in values))
        return f" Stats: {'; '.join(details)}."

    def _column_description(self, table: str, column: str) -> str:
        exact = COLUMN_DESCRIPTIONS.get(f"{table}.{column}")
        if exact:
            return exact
        lowered = column.lower()
        if lowered.endswith("_id"):
            return f"Identifier at the {TABLE_GRAINS.get(table, table)} grain."
        if "date" in lowered or "timestamp" in lowered or lowered.endswith("_at"):
            return "Timestamp/date field for temporal analysis."
        if any(word in lowered for word in ("price", "value", "freight")):
            return "Monetary value stored as a numeric field."
        if any(word in lowered for word in ("city", "state", "zip", "lat", "lng")):
            return "Geographic attribute."
        if "status" in lowered:
            return "Operational state."
        return f"Attribute in {table}."

    def _relationship_documents(self, relationships: list[tuple[str, str, str, str, str, str]]) -> list[SchemaDocument]:
        return [
            SchemaDocument(
                id=f"relationship:{left}.{left_col}->{right}.{right_col}",
                text=(
                    f"Allowed join: {left}.{left_col} = {right}.{right_col}\n"
                    f"Cardinality: {kind}\nUsage: {note}"
                ),
                metadata={
                    "kind": "relationship",
                    "from_table": left,
                    "from_column": left_col,
                    "to_table": right,
                    "to_column": right_col,
                },
            )
            for left, left_col, right, right_col, kind, note in relationships
        ]

    @staticmethod
    def _quote(identifier: str) -> str:
        return '"' + identifier.replace('"', '""') + '"'

    @staticmethod
    def _display(value: Any) -> str:
        text = "NULL" if value is None else str(value)
        return repr(text[:40])


# ── Phase 6: explicit column-level grounding block ─────────────────────────

# Exhaustive column catalogue keyed by table.  Generated from schema.sql /
# PRAGMA table_info so it is guaranteed to match the live database.
# Each entry: (type_string, tags, description)
# tags is a list of "PRIMARY KEY" | "FOREIGN KEY -> table.col" strings.
_COLUMN_CATALOGUE: dict[str, list[tuple[str, list[str], str]]] = {
    "customers": [
        ("TEXT", ["PRIMARY KEY"],
         "Order-level customer ID; links orders.customer_id to this table."),
        ("TEXT", [],
         "Stable buyer identifier shared across all orders placed by the same person."),
        ("TEXT", [],
         "Customer zip-code prefix (5 digits); may join geolocation on geolocation_zip_code_prefix."),
        ("TEXT", [], "City of the customer."),
        ("TEXT", [], "Brazilian state abbreviation (2 letters) for the customer."),
    ],
    "geolocation": [
        ("TEXT", [],
         "5-digit zip-code prefix; NOT unique — many rows share the same prefix."),
        ("REAL", [], "Latitude coordinate observation."),
        ("REAL", [], "Longitude coordinate observation."),
        ("TEXT", [], "City name for this observation."),
        ("TEXT", [], "State abbreviation for this observation."),
    ],
    "order_items": [
        ("TEXT", ["PRIMARY KEY", "FOREIGN KEY -> orders.order_id"],
         "Parent order identifier."),
        ("INTEGER", ["PRIMARY KEY"],
         "1-based position of this item within its order; COUNT(*) on this table counts items, not orders."),
        ("TEXT", ["FOREIGN KEY -> products.product_id"],
         "Product purchased in this line."),
        ("TEXT", ["FOREIGN KEY -> sellers.seller_id"],
         "Seller who fulfilled this item."),
        ("TEXT", [],
         "Shipping limit date for the seller."),
        ("REAL", [],
         "Item selling price — canonical revenue measure. Do NOT multiply by a quantity column (none exists). Do NOT include freight_value unless the question asks for total paid cost."),
        ("REAL", [], "Freight / shipping charge for this item."),
    ],
    "order_payments": [
        ("TEXT", ["PRIMARY KEY", "FOREIGN KEY -> orders.order_id"],
         "Parent order; an order may have multiple payment rows (one per payment_sequential)."),
        ("INTEGER", ["PRIMARY KEY"],
         "1-based payment sequence number within the order."),
        ("TEXT", [], "Payment method (credit_card, boleto, voucher, debit_card)."),
        ("INTEGER", [], "Number of installments chosen by the buyer."),
        ("REAL", [],
         "Amount for this payment sequence. SUM over all sequences to get full order payment value; aggregate at order grain before joining another one-to-many table."),
    ],
    "order_reviews": [
        ("TEXT", ["PRIMARY KEY"], "Unique review identifier."),
        ("TEXT", ["FOREIGN KEY -> orders.order_id"], "Parent order for this review."),
        ("INTEGER", [], "Customer rating from 1 (worst) to 5 (best)."),
        ("TEXT", [], "Optional short title left by the reviewer."),
        ("TEXT", [], "Optional free-text review message."),
        ("TEXT", [], "Date the review was created."),
        ("TEXT", [], "Date the review was answered."),
    ],
    "orders": [
        ("TEXT", ["PRIMARY KEY"], "Unique order identifier."),
        ("TEXT", ["FOREIGN KEY -> customers.customer_id"],
         "Order-level customer ID; links to customers.customer_id."),
        ("TEXT", [],
         "Order lifecycle status: approved, canceled, delivered, invoiced, processing, shipped, unavailable."),
        ("TEXT", [],
         "Canonical order date — use for all time-series and date-range analysis. Column name: order_purchase_timestamp."),
        ("TEXT", [],
         "Timestamp when the order was approved for processing."),
        ("TEXT", [],
         "Timestamp when the order was dispatched to the carrier."),
        ("TEXT", [],
         "Estimated delivery date promised to the customer."),
        ("TEXT", [],
         "Actual delivery timestamp to the customer. NULL if not yet delivered."),
    ],
    "products": [
        ("TEXT", ["PRIMARY KEY"], "Unique product identifier."),
        ("TEXT", [],
         "Product category in Portuguese; join product_category_name_translation for English names."),
        ("TEXT", [], "Product name length in characters."),
        ("TEXT", [], "Product description length in characters."),
        ("INTEGER", [], "Number of photos in the product listing."),
        ("REAL", [], "Product weight in grams."),
        ("REAL", [], "Product length in centimetres."),
        ("REAL", [], "Product height in centimetres."),
        ("REAL", [], "Product width in centimetres."),
    ],
    "sellers": [
        ("TEXT", ["PRIMARY KEY"], "Unique seller identifier."),
        ("TEXT", [], "Seller zip-code prefix."),
        ("TEXT", [], "City of the seller."),
        ("TEXT", [], "State abbreviation for the seller."),
    ],
    "product_category_name_translation": [
        ("TEXT", ["PRIMARY KEY"],
         "Portuguese product category name; matches products.product_category_name exactly."),
        ("TEXT", [],
         "English translation of the category name; use this for English-language output."),
    ],
}

# Exact column name list per table (must stay in sync with _COLUMN_CATALOGUE order).
EXACT_COLUMNS: dict[str, list[str]] = {
    "customers": [
        "customer_id", "customer_unique_id", "customer_zip_code_prefix",
        "customer_city", "customer_state",
    ],
    "geolocation": [
        "geolocation_zip_code_prefix", "geolocation_lat", "geolocation_lng",
        "geolocation_city", "geolocation_state",
    ],
    "order_items": [
        "order_id", "order_item_id", "product_id", "seller_id",
        "shipping_limit_date", "price", "freight_value",
    ],
    "order_payments": [
        "order_id", "payment_sequential", "payment_type",
        "payment_installments", "payment_value",
    ],
    "order_reviews": [
        "review_id", "order_id", "review_score",
        "review_comment_title", "review_comment_message",
        "review_creation_date", "review_answer_timestamp",
    ],
    "orders": [
        "order_id", "customer_id", "order_status",
        "order_purchase_timestamp", "order_approved_at",
        "order_delivered_carrier_date", "order_estimated_delivery_date",
        "order_delivered_customer_date",
    ],
    "products": [
        "product_id", "product_category_name", "product_name_lenght",
        "product_description_lenght", "product_photos_qty",
        "product_weight_g", "product_length_cm",
        "product_height_cm", "product_width_cm",
    ],
    "sellers": ["seller_id", "seller_zip_code_prefix", "seller_city", "seller_state"],
    "product_category_name_translation": [
        "product_category_name", "product_category_name_english",
    ],
}


def build_column_grounding_block(tables: list[str]) -> str:
    """Return a tightly formatted column reference block for every requested table.

    This block is injected verbatim into the SQL generation prompt so the LLM
    cannot confuse business concepts (quantity, unit_price, discount_rate) with
    actual column names.

    Example output (for order_items):
    ──────────────────────────────────
    COLUMN REFERENCE (use ONLY these exact column names):

    Table order_items  grain=(order_id, order_item_id)
      order_id         TEXT  [PK, FK->orders.order_id]  Parent order.
      order_item_id    INTEGER  [PK]  1-based item position; COUNT(*) counts items.
      product_id       TEXT  [FK->products.product_id]  Product purchased.
      seller_id        TEXT  [FK->sellers.seller_id]  Seller who fulfilled item.
      shipping_limit_date  TEXT  Shipping limit date.
      price            REAL  Item selling price — canonical revenue measure.
      freight_value    REAL  Freight/shipping charge.

    Join keys for order_items:
      order_items.order_id = orders.order_id
      order_items.product_id = products.product_id
      order_items.seller_id = sellers.seller_id
    ──────────────────────────────────
    """
    if not tables:
        return ""

    lines: list[str] = [
        "COLUMN REFERENCE — use ONLY the exact column names listed below.",
        "Do NOT invent column names like 'quantity', 'unit_price', 'discount_rate', 'order_date', etc.",
        "",
    ]

    for table in sorted(tables):
        col_names = EXACT_COLUMNS.get(table, [])
        col_meta  = _COLUMN_CATALOGUE.get(table, [])
        grain     = TABLE_GRAINS.get(table, "one row")
        lines.append(f"Table: {table}  |  grain: {grain}")

        for i, col_name in enumerate(col_names):
            if i < len(col_meta):
                col_type, col_tags, col_desc = col_meta[i]
            else:
                col_type, col_tags, col_desc = "UNKNOWN", [], ""
            tag_str = f"  [{', '.join(col_tags)}]" if col_tags else ""
            lines.append(f"  {col_name:<40} {col_type:<8}{tag_str}  {col_desc}")

        # Join keys for this table
        join_lines = [
            f"  {left}.{lc} = {right}.{rc}"
            for left, lc, right, rc, _, _ in JOIN_RELATIONSHIPS
            if left == table or right == table
        ]
        if join_lines:
            lines.append(f"  -- join keys --")
            lines.extend(join_lines)
        lines.append("")

    return "\n".join(lines)


def tables_from_context(schema_context: list[str]) -> list[str]:
    """Extract physical table names mentioned in a list of schema-context strings."""
    known = set(EXACT_COLUMNS.keys())
    found: set[str] = set()
    import re
    pattern = re.compile(r"\bTable:\s*(\w+)", re.IGNORECASE)
    for chunk in schema_context:
        for match in pattern.finditer(chunk):
            t = match.group(1).lower()
            if t in known:
                found.add(t)
    # Also scan for bare table names in "Physical tables allowed" header lines
    summary_pattern = re.compile(r"\b(" + "|".join(re.escape(t) for t in known) + r")\b")
    for chunk in schema_context:
        if "Physical tables allowed" in chunk or "Grounded schema" in chunk:
            for m in summary_pattern.finditer(chunk):
                found.add(m.group(1))
    return sorted(found)
