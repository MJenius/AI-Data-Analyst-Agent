from __future__ import annotations

import sqlite3
from pathlib import Path
import pandas as pd
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = ROOT / "data" / "schema.sql"
DATA_DIR = ROOT / "data" / "olist"

CSV_MAPPING = {
    "olist_customers_dataset.csv": "customers",
    "olist_geolocation_dataset.csv": "geolocation",
    "olist_order_items_dataset.csv": "order_items",
    "olist_order_payments_dataset.csv": "order_payments",
    "olist_order_reviews_dataset.csv": "order_reviews",
    "olist_orders_dataset.csv": "orders",
    "olist_products_dataset.csv": "products",
    "olist_sellers_dataset.csv": "sellers",
    "product_category_name_translation.csv": "product_category_name_translation",
}

def seed_database(database_path: str | Path) -> Path:
    """Create a local SQLite analytics database with the Olist e-commerce dataset."""

    db_path = Path(database_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Seeding database at {db_path}")
    
    connection = sqlite3.connect(db_path)
    try:
        # Initialize schema
        logger.info("Initializing schema...")
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        
        # Load each CSV into the corresponding table
        for csv_file, table_name in CSV_MAPPING.items():
            csv_path = DATA_DIR / csv_file
            if not csv_path.exists():
                logger.warning(f"File {csv_file} not found in {DATA_DIR}. Skipping.")
                continue
            
            logger.info(f"Loading {csv_file} into table {table_name}...")
            # Use chunking if necessary for very large files, but for now direct load
            df = pd.read_csv(csv_path)
            df.to_sql(table_name, connection, if_exists="append", index=False)
            logger.info(f"Successfully loaded {len(df)} rows into {table_name}.")
            
        connection.commit()
    except Exception as e:
        logger.error(f"Error seeding database: {e}")
        raise
    finally:
        connection.close()
    
    logger.info("Database seeding completed.")
    return db_path

if __name__ == "__main__":
    # For testing purposes
    db_file = ROOT / "data" / "analytics.db"
    seed_database(db_file)
