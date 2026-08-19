"""Deterministic SQLite Database Builder for Olist Brazilian E-Commerce Dataset.

This script ingests the 9 raw CSV files from Kaggle and builds a normalized,
indexed SQLite database (data/analytics.db) for reproducible benchmarking.

License Note:
    The dataset is the "Brazilian E-Commerce Public Dataset by Olist"
    hosted on Kaggle under CC BY-NC-SA 4.0.
    Source: https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce

Usage:
    python data/build_database.py [--data-dir data/olist] [--output data/analytics.db]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import logging
import sqlite3
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("build_database")

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "data" / "olist"
DEFAULT_OUTPUT_DB = ROOT / "data" / "analytics.db"
SCHEMA_PATH = ROOT / "data" / "schema.sql"

TABLE_FILES = {
    "customers": "olist_customers_dataset.csv",
    "geolocation": "olist_geolocation_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "order_payments": "olist_order_payments_dataset.csv",
    "order_reviews": "olist_order_reviews_dataset.csv",
    "orders": "olist_orders_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "product_category_name_translation": "product_category_name_translation.csv",
}

EXPECTED_DB_SHA256 = "8550c4cc6d670aa0441bc898e47a57a40001858fc3f13dc5cb16fb90ca11c130"


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def build_database(data_dir: Path, output_db: Path) -> None:
    logger.info("Verifying source CSV files in %s...", data_dir)
    missing = []
    for table_name, filename in TABLE_FILES.items():
        csv_path = data_dir / filename
        if not csv_path.exists():
            missing.append(filename)

    if missing:
        logger.error("Missing required CSV files: %s", missing)
        logger.error(
            "Please download the dataset from Kaggle (CC BY-NC-SA 4.0): "
            "https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce "
            "and place all 9 CSV files in %s",
            data_dir,
        )
        sys.exit(1)

    output_db.parent.mkdir(parents=True, exist_ok=True)
    if output_db.exists():
        logger.warning("Output database %s already exists. Overwriting...", output_db)
        output_db.unlink()

    conn = sqlite3.connect(output_db)
    cursor = conn.cursor()

    # Load DDL schema if present
    if SCHEMA_PATH.exists():
        logger.info("Executing DDL schema from %s...", SCHEMA_PATH)
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            cursor.executescript(f.read())
        conn.commit()

    # Ingest CSVs
    for table_name, filename in TABLE_FILES.items():
        csv_path = data_dir / filename
        logger.info("Ingesting %s into table '%s'...", filename, table_name)
        with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            headers = next(reader)
            placeholders = ", ".join(["?"] * len(headers))
            cols_str = ", ".join([f'"{h}"' for h in headers])

            # If table was not created by DDL schema, create it dynamically
            cursor.execute(f"SELECT count(*) FROM sqlite_master WHERE type='table' AND name='{table_name}'")
            if cursor.fetchone()[0] == 0:
                col_defs = ", ".join([f'"{h}" TEXT' for h in headers])
                cursor.execute(f"CREATE TABLE IF NOT EXISTS {table_name} ({col_defs})")

            insert_sql = f"INSERT INTO {table_name} ({cols_str}) VALUES ({placeholders})"
            batch = []
            row_count = 0
            for row in reader:
                batch.append(row)
                row_count += 1
                if len(batch) >= 10000:
                    cursor.executemany(insert_sql, batch)
                    batch = []
            if batch:
                cursor.executemany(insert_sql, batch)
            conn.commit()
            logger.info("  -> Ingested %d rows into '%s'", row_count, table_name)

    # Create standard performance indexes
    logger.info("Creating index optimizations...")
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_orders_customer_id ON orders(customer_id)",
        "CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON order_items(order_id)",
        "CREATE INDEX IF NOT EXISTS idx_order_items_product_id ON order_items(product_id)",
        "CREATE INDEX IF NOT EXISTS idx_order_items_seller_id ON order_items(seller_id)",
        "CREATE INDEX IF NOT EXISTS idx_order_payments_order_id ON order_payments(order_id)",
        "CREATE INDEX IF NOT EXISTS idx_order_reviews_order_id ON order_reviews(order_id)",
    ]
    for idx_sql in indexes:
        try:
            cursor.execute(idx_sql)
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()

    db_hash = compute_sha256(output_db)
    logger.info("Database construction complete!")
    logger.info("  Location: %s", output_db)
    logger.info("  SHA-256:  %s", db_hash)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build analytics SQLite database from Olist CSVs")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="Path to raw CSV directory")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DB, help="Output SQLite database path")
    args = parser.parse_args()

    build_database(args.data_dir, args.output)
