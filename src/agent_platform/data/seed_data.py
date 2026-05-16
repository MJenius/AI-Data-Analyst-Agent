from __future__ import annotations

import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = ROOT / "data" / "schema.sql"


CUSTOMERS = [
    (1, "Northwind Labs", "ops@northwind.example", "North America", "2025-01-05", "Enterprise"),
    (2, "Bright Retail", "data@bright.example", "North America", "2025-01-18", "SMB"),
    (3, "EuroStyle", "team@eurostyle.example", "Europe", "2025-02-04", "Mid-Market"),
    (4, "Pacific Apps", "hello@pacific.example", "APAC", "2025-02-20", "SMB"),
    (5, "Atlas Commerce", "ops@atlas.example", "Europe", "2025-03-10", "Enterprise"),
    (6, "Zenith Stores", "analytics@zenith.example", "APAC", "2025-03-28", "Mid-Market"),
]

PRODUCTS = [
    (1, "ANL-001", "Insight Pro", "Analytics", 42.0, 1),
    (2, "ANL-002", "Dashboard Studio", "Analytics", 35.0, 1),
    (3, "AUT-001", "Workflow Automator", "Automation", 28.0, 1),
    (4, "SEC-001", "Compliance Shield", "Security", 55.0, 1),
    (5, "DAT-001", "Data Sync", "Data Platform", 31.0, 1),
]

ORDERS = [
    (1, 1, "2025-01-12", "North America", "paid"),
    (2, 2, "2025-01-21", "North America", "paid"),
    (3, 3, "2025-02-08", "Europe", "paid"),
    (4, 4, "2025-02-19", "APAC", "paid"),
    (5, 5, "2025-03-05", "Europe", "paid"),
    (6, 6, "2025-03-15", "APAC", "paid"),
    (7, 1, "2025-04-04", "North America", "paid"),
    (8, 3, "2025-04-17", "Europe", "paid"),
    (9, 4, "2025-05-03", "APAC", "paid"),
    (10, 2, "2025-05-19", "North America", "paid"),
    (11, 5, "2025-06-07", "Europe", "paid"),
    (12, 6, "2025-06-22", "APAC", "paid"),
]

ORDER_ITEMS = [
    (1, 1, 1, 4, 120.0, 0.00),
    (2, 1, 3, 2, 80.0, 0.05),
    (3, 2, 2, 3, 95.0, 0.00),
    (4, 3, 4, 2, 150.0, 0.00),
    (5, 3, 5, 2, 110.0, 0.10),
    (6, 4, 1, 2, 120.0, 0.00),
    (7, 4, 3, 4, 82.0, 0.00),
    (8, 5, 2, 2, 95.0, 0.00),
    (9, 5, 5, 3, 112.0, 0.05),
    (10, 6, 4, 1, 150.0, 0.00),
    (11, 7, 1, 8, 125.0, 0.00),
    (12, 7, 2, 5, 99.0, 0.00),
    (13, 8, 1, 6, 125.0, 0.00),
    (14, 8, 5, 5, 115.0, 0.00),
    (15, 9, 3, 8, 85.0, 0.05),
    (16, 9, 1, 4, 125.0, 0.00),
    (17, 10, 2, 7, 99.0, 0.00),
    (18, 10, 4, 2, 155.0, 0.00),
    (19, 11, 1, 9, 128.0, 0.00),
    (20, 11, 5, 6, 118.0, 0.00),
    (21, 12, 3, 9, 86.0, 0.00),
    (22, 12, 2, 6, 101.0, 0.00),
]


def seed_database(database_path: str | Path) -> Path:
    """Create a local SQLite analytics database with realistic e-commerce data."""

    db_path = Path(database_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    try:
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        connection.executemany("INSERT OR REPLACE INTO customers VALUES (?, ?, ?, ?, ?, ?)", CUSTOMERS)
        connection.executemany("INSERT OR REPLACE INTO products VALUES (?, ?, ?, ?, ?, ?)", PRODUCTS)
        connection.executemany("INSERT OR REPLACE INTO orders VALUES (?, ?, ?, ?, ?)", ORDERS)
        connection.executemany(
            "INSERT OR REPLACE INTO order_items VALUES (?, ?, ?, ?, ?, ?)",
            ORDER_ITEMS,
        )
        connection.commit()
    finally:
        connection.close()
    return db_path
