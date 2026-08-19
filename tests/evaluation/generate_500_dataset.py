"""Build and programmatically verify a high-quality, scientifically defensible 500-query analytical benchmark dataset.

Target Defensible Balance:
- 8 Core Business Domains:
  1. Revenue & Sales (65)
  2. Orders & Transactions (65)
  3. Customers & Geography (65)
  4. Products & Categories (65)
  5. Logistics & Operations (60)
  6. Sellers & Fulfillment (60)
  7. Payments & Installments (60)
  8. Reviews & Satisfaction (60)
  Total = 500

- Query Types:
  - single_value: ~200 (40%)
  - ranked_list: ~120 (24%)
  - time_series: ~90 (18%)
  - aggregated_table: ~90 (18%)

- Difficulty:
  - easy: ~130 (26%)
  - medium: ~270 (54%)
  - hard: ~100 (20%)

- Rich SQL constructs:
  - Multi-table joins (2-5 tables)
  - Time-series temporal aggregations (strftime '%Y-%m', '%Y-%m-%d', '%w', '%H')
  - CTEs & Window Functions (SUM() OVER, RANK() OVER, julianday calculations)
  - HAVING clauses, CASE statements, composite KPIs (AOV, CLV, late delivery rate, cancellation rate)

Every query is executed directly against data/analytics.db to compute and freeze expected_result.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "analytics.db"
OUT_PATH = ROOT / "tests" / "evaluation" / "benchmark_dataset_500.json"


def run_sql(conn: sqlite3.Connection, sql: str) -> dict[str, Any]:
    cursor = conn.execute(sql)
    cols = [d[0] for d in cursor.description] if cursor.description else []
    rows = cursor.fetchall()
    values = [{c: (round(v, 4) if isinstance(v, float) else v) for c, v in zip(cols, row)} for row in rows]
    return {
        "columns": cols,
        "values": values,
        "row_count": len(values),
    }


def build_rebalanced_dataset() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    states_20 = ["SP", "RJ", "MG", "RS", "PR", "SC", "BA", "DF", "GO", "ES", "PE", "CE", "PA", "MT", "MA", "MS", "PB", "RN", "PI", "AL"]
    cities_top = ["sao paulo", "rio de janeiro", "belo horizonte", "brasilia", "curitiba", "campinas", "porto alegre", "salvador"]
    all_categories = [
        "cama_mesa_banho", "beleza_saude", "esporte_lazer", "moveis_decoracao", "informatica_acessorios",
        "utilidades_domesticas", "relogios_presentes", "telefonia", "automotivo", "brinquedos",
        "cool_stuff", "ferramentas_jardim", "perfumaria", "bebes", "eletronicos",
    ]
    payment_types = ["credit_card", "boleto", "voucher", "debit_card"]
    months_list = [f"2017-{m:02d}" for m in range(1, 13)] + [f"2018-{m:02d}" for m in range(1, 9)]

    # =========================================================================
    # DOMAIN 1: Revenue & Sales (Target: 65 queries)
    # =========================================================================
    # Single Value (4)
    items.append({
        "question": "What is the total revenue generated across all completed order items?",
        "expected_tables": ["order_items"],
        "expected_metrics": ["total_revenue"],
        "expected_sql": "SELECT ROUND(SUM(oi.price), 2) AS total_revenue FROM order_items oi",
        "category": "Revenue & Sales",
        "domain": "Revenue & Sales",
        "query_type": "single_value",
        "difficulty": "easy",
    })
    items.append({
        "question": "What is the total freight value paid across all orders?",
        "expected_tables": ["order_items"],
        "expected_metrics": ["total_freight"],
        "expected_sql": "SELECT ROUND(SUM(oi.freight_value), 2) AS total_freight FROM order_items oi",
        "category": "Revenue & Sales",
        "domain": "Revenue & Sales",
        "query_type": "single_value",
        "difficulty": "easy",
    })
    items.append({
        "question": "What is the average order value (AOV)?",
        "expected_tables": ["orders", "order_items"],
        "expected_metrics": ["aov"],
        "expected_sql": "SELECT ROUND(CAST(SUM(oi.price) AS REAL) / COUNT(DISTINCT o.order_id), 2) AS aov FROM orders o JOIN order_items oi ON o.order_id = oi.order_id",
        "category": "Revenue & Sales",
        "domain": "Revenue & Sales",
        "query_type": "single_value",
        "difficulty": "medium",
    })
    items.append({
        "question": "What is the average revenue per customer?",
        "expected_tables": ["customers", "orders", "order_items"],
        "expected_metrics": ["rev_per_customer"],
        "expected_sql": "SELECT ROUND(CAST(SUM(oi.price) AS REAL) / COUNT(DISTINCT c.customer_unique_id), 2) AS rev_per_customer FROM customers c JOIN orders o ON c.customer_id = o.customer_id JOIN order_items oi ON o.order_id = oi.order_id",
        "category": "Revenue & Sales",
        "domain": "Revenue & Sales",
        "query_type": "single_value",
        "difficulty": "medium",
    })

    # Time series (16)
    items.append({
        "question": "What is the monthly revenue trend across all months?",
        "expected_tables": ["orders", "order_items"],
        "expected_metrics": ["month", "revenue"],
        "expected_sql": "SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month, ROUND(SUM(oi.price), 2) AS revenue FROM orders o JOIN order_items oi ON o.order_id = oi.order_id GROUP BY month ORDER BY month",
        "category": "Revenue & Sales",
        "domain": "Revenue & Sales",
        "query_type": "time_series",
        "difficulty": "medium",
    })
    items.append({
        "question": "What is the monthly freight value trend across all months?",
        "expected_tables": ["orders", "order_items"],
        "expected_metrics": ["month", "freight_value"],
        "expected_sql": "SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month, ROUND(SUM(oi.freight_value), 2) AS freight_value FROM orders o JOIN order_items oi ON o.order_id = oi.order_id GROUP BY month ORDER BY month",
        "category": "Revenue & Sales",
        "domain": "Revenue & Sales",
        "query_type": "time_series",
        "difficulty": "medium",
    })
    items.append({
        "question": "What is the monthly AOV (average order value) trend across all months?",
        "expected_tables": ["orders", "order_items"],
        "expected_metrics": ["month", "monthly_aov"],
        "expected_sql": "SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month, ROUND(CAST(SUM(oi.price) AS REAL) / COUNT(DISTINCT o.order_id), 2) AS monthly_aov FROM orders o JOIN order_items oi ON o.order_id = oi.order_id GROUP BY month ORDER BY month",
        "category": "Revenue & Sales",
        "domain": "Revenue & Sales",
        "query_type": "time_series",
        "difficulty": "hard",
    })
    items.append({
        "question": "What is the monthly cumulative revenue progression across all orders?",
        "expected_tables": ["orders", "order_items"],
        "expected_metrics": ["month", "cumulative_revenue"],
        "expected_sql": "WITH monthly AS (SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month, SUM(oi.price) AS rev FROM orders o JOIN order_items oi ON o.order_id = oi.order_id GROUP BY month) SELECT month, ROUND(SUM(rev) OVER (ORDER BY month), 2) AS cumulative_revenue FROM monthly ORDER BY month",
        "category": "Revenue & Sales",
        "domain": "Revenue & Sales",
        "query_type": "time_series",
        "difficulty": "hard",
    })
    for yr in ["2017", "2018"]:
        items.append({
            "question": f"What is the monthly revenue trend in {yr}?",
            "expected_tables": ["orders", "order_items"],
            "expected_metrics": ["month", "revenue"],
            "expected_sql": f"SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month, ROUND(SUM(oi.price), 2) AS revenue FROM orders o JOIN order_items oi ON o.order_id = oi.order_id WHERE strftime('%Y', o.order_purchase_timestamp) = '{yr}' GROUP BY month ORDER BY month",
            "category": "Revenue & Sales",
            "domain": "Revenue & Sales",
            "query_type": "time_series",
            "difficulty": "medium",
        })
    for st in ["SP", "RJ", "MG", "RS", "PR", "SC", "BA", "DF", "GO", "ES"]:
        items.append({
            "question": f"What is the monthly revenue trend for customers in state {st} in 2017?",
            "expected_tables": ["customers", "orders", "order_items"],
            "expected_metrics": ["month", "revenue"],
            "expected_sql": f"SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month, ROUND(SUM(oi.price), 2) AS revenue FROM customers c JOIN orders o ON c.customer_id = o.customer_id JOIN order_items oi ON o.order_id = oi.order_id WHERE c.customer_state = '{st}' AND strftime('%Y', o.order_purchase_timestamp) = '2017' GROUP BY month ORDER BY month",
            "category": "Revenue & Sales",
            "domain": "Revenue & Sales",
            "query_type": "time_series",
            "difficulty": "hard",
        })

    # Aggregated table (5)
    for yr in ["2017", "2018"]:
        items.append({
            "question": f"What is the quarterly revenue breakdown for {yr}?",
            "expected_tables": ["orders", "order_items"],
            "expected_metrics": ["quarter", "total_revenue"],
            "expected_sql": f"SELECT CASE WHEN strftime('%m', o.order_purchase_timestamp) BETWEEN '01' AND '03' THEN '{yr}-Q1' WHEN strftime('%m', o.order_purchase_timestamp) BETWEEN '04' AND '06' THEN '{yr}-Q2' WHEN strftime('%m', o.order_purchase_timestamp) BETWEEN '07' AND '09' THEN '{yr}-Q3' ELSE '{yr}-Q4' END AS quarter, ROUND(SUM(oi.price), 2) AS total_revenue FROM orders o JOIN order_items oi ON o.order_id = oi.order_id WHERE strftime('%Y', o.order_purchase_timestamp) = '{yr}' GROUP BY quarter ORDER BY quarter",
            "category": "Revenue & Sales",
            "domain": "Revenue & Sales",
            "query_type": "aggregated_table",
            "difficulty": "hard",
        })
    items.append({
        "question": "What is the breakdown of revenue and freight value by order status?",
        "expected_tables": ["orders", "order_items"],
        "expected_metrics": ["order_status", "total_revenue", "total_freight"],
        "expected_sql": "SELECT o.order_status, ROUND(SUM(oi.price), 2) AS total_revenue, ROUND(SUM(oi.freight_value), 2) AS total_freight FROM orders o JOIN order_items oi ON o.order_id = oi.order_id GROUP BY o.order_status ORDER BY total_revenue DESC",
        "category": "Revenue & Sales",
        "domain": "Revenue & Sales",
        "query_type": "aggregated_table",
        "difficulty": "medium",
    })
    items.append({
        "question": "What is the distribution of total revenue and order count across days of the week?",
        "expected_tables": ["orders", "order_items"],
        "expected_metrics": ["day_of_week", "order_count", "total_revenue"],
        "expected_sql": "SELECT strftime('%w', o.order_purchase_timestamp) AS day_of_week, COUNT(DISTINCT o.order_id) AS order_count, ROUND(SUM(oi.price), 2) AS total_revenue FROM orders o JOIN order_items oi ON o.order_id = oi.order_id GROUP BY day_of_week ORDER BY day_of_week",
        "category": "Revenue & Sales",
        "domain": "Revenue & Sales",
        "query_type": "aggregated_table",
        "difficulty": "medium",
    })
    items.append({
        "question": "What is the revenue and order volume distribution across purchase hours (0-23)?",
        "expected_tables": ["orders", "order_items"],
        "expected_metrics": ["hour", "order_count", "total_revenue"],
        "expected_sql": "SELECT strftime('%H', o.order_purchase_timestamp) AS hour, COUNT(DISTINCT o.order_id) AS order_count, ROUND(SUM(oi.price), 2) AS total_revenue FROM orders o JOIN order_items oi ON o.order_id = oi.order_id GROUP BY hour ORDER BY hour",
        "category": "Revenue & Sales",
        "domain": "Revenue & Sales",
        "query_type": "aggregated_table",
        "difficulty": "medium",
    })

    # Ranked lists (20)
    for n in [3, 5, 10, 15, 20]:
        items.append({
            "question": f"What are the top {n} months by total sales revenue?",
            "expected_tables": ["orders", "order_items"],
            "expected_metrics": ["month", "total_revenue"],
            "expected_sql": f"SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month, ROUND(SUM(oi.price), 2) AS total_revenue FROM orders o JOIN order_items oi ON o.order_id = oi.order_id GROUP BY month ORDER BY total_revenue DESC LIMIT {n}",
            "category": "Revenue & Sales",
            "domain": "Revenue & Sales",
            "query_type": "ranked_list",
            "difficulty": "medium",
        })
        items.append({
            "question": f"What are the top {n} highest revenue days in 2017?",
            "expected_tables": ["orders", "order_items"],
            "expected_metrics": ["day", "total_revenue"],
            "expected_sql": f"SELECT strftime('%Y-%m-%d', o.order_purchase_timestamp) AS day, ROUND(SUM(oi.price), 2) AS total_revenue FROM orders o JOIN order_items oi ON o.order_id = oi.order_id WHERE strftime('%Y', o.order_purchase_timestamp) = '2017' GROUP BY day ORDER BY total_revenue DESC LIMIT {n}",
            "category": "Revenue & Sales",
            "domain": "Revenue & Sales",
            "query_type": "ranked_list",
            "difficulty": "medium",
        })
        items.append({
            "question": f"What are the top {n} highest revenue days in 2018?",
            "expected_tables": ["orders", "order_items"],
            "expected_metrics": ["day", "total_revenue"],
            "expected_sql": f"SELECT strftime('%Y-%m-%d', o.order_purchase_timestamp) AS day, ROUND(SUM(oi.price), 2) AS total_revenue FROM orders o JOIN order_items oi ON o.order_id = oi.order_id WHERE strftime('%Y', o.order_purchase_timestamp) = '2018' GROUP BY day ORDER BY total_revenue DESC LIMIT {n}",
            "category": "Revenue & Sales",
            "domain": "Revenue & Sales",
            "query_type": "ranked_list",
            "difficulty": "medium",
        })
        items.append({
            "question": f"What are the top {n} months by average order value?",
            "expected_tables": ["orders", "order_items"],
            "expected_metrics": ["month", "aov"],
            "expected_sql": f"SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month, ROUND(CAST(SUM(oi.price) AS REAL) / COUNT(DISTINCT o.order_id), 2) AS aov FROM orders o JOIN order_items oi ON o.order_id = oi.order_id GROUP BY month ORDER BY aov DESC LIMIT {n}",
            "category": "Revenue & Sales",
            "domain": "Revenue & Sales",
            "query_type": "ranked_list",
            "difficulty": "hard",
        })

    # Parameterized single value monthly revenue (20)
    for m in months_list:
        items.append({
            "question": f"What was the total revenue in month {m}?",
            "expected_tables": ["orders", "order_items"],
            "expected_metrics": ["monthly_revenue"],
            "expected_sql": f"SELECT ROUND(SUM(oi.price), 2) AS monthly_revenue FROM orders o JOIN order_items oi ON o.order_id = oi.order_id WHERE strftime('%Y-%m', o.order_purchase_timestamp) = '{m}'",
            "category": "Revenue & Sales",
            "domain": "Revenue & Sales",
            "query_type": "single_value",
            "difficulty": "medium",
        })

    # =========================================================================
    # DOMAIN 2: Orders & Transactions (Target: 65 queries)
    # =========================================================================
    # Single Value (5)
    items.append({
        "question": "How many total orders are recorded in the database?",
        "expected_tables": ["orders"],
        "expected_metrics": ["total_orders"],
        "expected_sql": "SELECT COUNT(*) AS total_orders FROM orders",
        "category": "Orders & Transactions",
        "domain": "Orders & Transactions",
        "query_type": "single_value",
        "difficulty": "easy",
    })
    items.append({
        "question": "What is the average number of items per order?",
        "expected_tables": ["order_items"],
        "expected_metrics": ["avg_items_per_order"],
        "expected_sql": "SELECT ROUND(CAST(COUNT(*) AS REAL) / COUNT(DISTINCT order_id), 2) AS avg_items_per_order FROM order_items",
        "category": "Orders & Transactions",
        "domain": "Orders & Transactions",
        "query_type": "single_value",
        "difficulty": "medium",
    })
    items.append({
        "question": "What is the overall order cancellation rate?",
        "expected_tables": ["orders"],
        "expected_metrics": ["cancellation_rate"],
        "expected_sql": "SELECT ROUND(CAST(SUM(CASE WHEN order_status = 'canceled' THEN 1.0 ELSE 0.0 END) AS REAL) / COUNT(*), 4) AS cancellation_rate FROM orders",
        "category": "Orders & Transactions",
        "domain": "Orders & Transactions",
        "query_type": "single_value",
        "difficulty": "medium",
    })
    items.append({
        "question": "What is the repeat customer order rate (customers with more than 1 order)?",
        "expected_tables": ["customers", "orders"],
        "expected_metrics": ["repeat_rate"],
        "expected_sql": "WITH cust_orders AS (SELECT c.customer_unique_id, COUNT(DISTINCT o.order_id) AS cnt FROM customers c JOIN orders o ON c.customer_id = o.customer_id GROUP BY c.customer_unique_id) SELECT ROUND(CAST(SUM(CASE WHEN cnt > 1 THEN 1.0 ELSE 0.0 END) AS REAL) / COUNT(*), 4) AS repeat_rate FROM cust_orders",
        "category": "Orders & Transactions",
        "domain": "Orders & Transactions",
        "query_type": "single_value",
        "difficulty": "hard",
    })
    items.append({
        "question": "How many multi-item orders (orders with > 1 item) were placed?",
        "expected_tables": ["order_items"],
        "expected_metrics": ["multi_item_order_count"],
        "expected_sql": "WITH item_counts AS (SELECT order_id, COUNT(*) AS items FROM order_items GROUP BY order_id) SELECT COUNT(*) AS multi_item_order_count FROM item_counts WHERE items > 1",
        "category": "Orders & Transactions",
        "domain": "Orders & Transactions",
        "query_type": "single_value",
        "difficulty": "medium",
    })

    # Time series (6)
    items.append({
        "question": "What is the monthly order volume trend across all recorded months?",
        "expected_tables": ["orders"],
        "expected_metrics": ["month", "order_count"],
        "expected_sql": "SELECT strftime('%Y-%m', order_purchase_timestamp) AS month, COUNT(*) AS order_count FROM orders GROUP BY month ORDER BY month",
        "category": "Orders & Transactions",
        "domain": "Orders & Transactions",
        "query_type": "time_series",
        "difficulty": "medium",
    })
    items.append({
        "question": "What is the monthly cancellation rate trend across all recorded months?",
        "expected_tables": ["orders"],
        "expected_metrics": ["month", "cancellation_rate"],
        "expected_sql": "SELECT strftime('%Y-%m', order_purchase_timestamp) AS month, ROUND(CAST(SUM(CASE WHEN order_status = 'canceled' THEN 1.0 ELSE 0.0 END) AS REAL) / COUNT(*), 4) AS cancellation_rate FROM orders GROUP BY month ORDER BY month",
        "category": "Orders & Transactions",
        "domain": "Orders & Transactions",
        "query_type": "time_series",
        "difficulty": "hard",
    })
    items.append({
        "question": "What is the monthly average items per order trend across all recorded months?",
        "expected_tables": ["orders", "order_items"],
        "expected_metrics": ["month", "avg_items"],
        "expected_sql": "SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month, ROUND(CAST(COUNT(oi.order_item_id) AS REAL) / COUNT(DISTINCT o.order_id), 2) AS avg_items FROM orders o JOIN order_items oi ON o.order_id = oi.order_id GROUP BY month ORDER BY month",
        "category": "Orders & Transactions",
        "domain": "Orders & Transactions",
        "query_type": "time_series",
        "difficulty": "hard",
    })
    items.append({
        "question": "What is the monthly trend of orders placed in 2017?",
        "expected_tables": ["orders"],
        "expected_metrics": ["month", "order_count"],
        "expected_sql": "SELECT strftime('%Y-%m', order_purchase_timestamp) AS month, COUNT(*) AS order_count FROM orders WHERE strftime('%Y', order_purchase_timestamp) = '2017' GROUP BY month ORDER BY month",
        "category": "Orders & Transactions",
        "domain": "Orders & Transactions",
        "query_type": "time_series",
        "difficulty": "medium",
    })
    items.append({
        "question": "What is the monthly trend of orders placed in 2018?",
        "expected_tables": ["orders"],
        "expected_metrics": ["month", "order_count"],
        "expected_sql": "SELECT strftime('%Y-%m', order_purchase_timestamp) AS month, COUNT(*) AS order_count FROM orders WHERE strftime('%Y', order_purchase_timestamp) = '2018' GROUP BY month ORDER BY month",
        "category": "Orders & Transactions",
        "domain": "Orders & Transactions",
        "query_type": "time_series",
        "difficulty": "medium",
    })
    items.append({
        "question": "What is the monthly trend of multi-item orders placed across all months?",
        "expected_tables": ["orders", "order_items"],
        "expected_metrics": ["month", "multi_item_orders"],
        "expected_sql": "WITH ord_items AS (SELECT o.order_id, strftime('%Y-%m', o.order_purchase_timestamp) AS month, COUNT(oi.order_item_id) AS cnt FROM orders o JOIN order_items oi ON o.order_id = oi.order_id GROUP BY o.order_id) SELECT month, COUNT(*) AS multi_item_orders FROM ord_items WHERE cnt > 1 GROUP BY month ORDER BY month",
        "category": "Orders & Transactions",
        "domain": "Orders & Transactions",
        "query_type": "time_series",
        "difficulty": "hard",
    })

    # Aggregated tables (4)
    items.append({
        "question": "What is the complete breakdown of order count and percentage by order status?",
        "expected_tables": ["orders"],
        "expected_metrics": ["order_status", "order_count"],
        "expected_sql": "SELECT order_status, COUNT(*) AS order_count FROM orders GROUP BY order_status ORDER BY order_count DESC",
        "category": "Orders & Transactions",
        "domain": "Orders & Transactions",
        "query_type": "aggregated_table",
        "difficulty": "easy",
    })
    items.append({
        "question": "What is the distribution of order items per order (order size distribution)?",
        "expected_tables": ["order_items"],
        "expected_metrics": ["item_count", "order_count"],
        "expected_sql": "WITH ord_items AS (SELECT order_id, COUNT(*) AS item_cnt FROM order_items GROUP BY order_id) SELECT item_cnt AS item_count, COUNT(*) AS order_count FROM ord_items GROUP BY item_cnt ORDER BY item_cnt",
        "category": "Orders & Transactions",
        "domain": "Orders & Transactions",
        "query_type": "aggregated_table",
        "difficulty": "medium",
    })
    items.append({
        "question": "What is the order count distribution across days of the week (0=Sunday, 6=Saturday)?",
        "expected_tables": ["orders"],
        "expected_metrics": ["day_of_week", "order_count"],
        "expected_sql": "SELECT strftime('%w', order_purchase_timestamp) AS day_of_week, COUNT(*) AS order_count FROM orders GROUP BY day_of_week ORDER BY day_of_week",
        "category": "Orders & Transactions",
        "domain": "Orders & Transactions",
        "query_type": "aggregated_table",
        "difficulty": "easy",
    })
    items.append({
        "question": "What is the order placement distribution across all 24 hours of the day?",
        "expected_tables": ["orders"],
        "expected_metrics": ["hour", "order_count"],
        "expected_sql": "SELECT strftime('%H', order_purchase_timestamp) AS hour, COUNT(*) AS order_count FROM orders GROUP BY hour ORDER BY hour",
        "category": "Orders & Transactions",
        "domain": "Orders & Transactions",
        "query_type": "aggregated_table",
        "difficulty": "easy",
    })

    # Rankings (10)
    for n in [3, 5, 10, 15, 20]:
        items.append({
            "question": f"What are the top {n} busiest days by total order count in 2017?",
            "expected_tables": ["orders"],
            "expected_metrics": ["day", "order_count"],
            "expected_sql": f"SELECT strftime('%Y-%m-%d', order_purchase_timestamp) AS day, COUNT(*) AS order_count FROM orders WHERE strftime('%Y', order_purchase_timestamp) = '2017' GROUP BY day ORDER BY order_count DESC LIMIT {n}",
            "category": "Orders & Transactions",
            "domain": "Orders & Transactions",
            "query_type": "ranked_list",
            "difficulty": "medium",
        })
        items.append({
            "question": f"What are the top {n} busiest days by total order count in 2018?",
            "expected_tables": ["orders"],
            "expected_metrics": ["day", "order_count"],
            "expected_sql": f"SELECT strftime('%Y-%m-%d', order_purchase_timestamp) AS day, COUNT(*) AS order_count FROM orders WHERE strftime('%Y', order_purchase_timestamp) = '2018' GROUP BY day ORDER BY order_count DESC LIMIT {n}",
            "category": "Orders & Transactions",
            "domain": "Orders & Transactions",
            "query_type": "ranked_list",
            "difficulty": "medium",
        })

    # Parameterized single value (40)
    for m in months_list:
        items.append({
            "question": f"How many orders were placed in month {m}?",
            "expected_tables": ["orders"],
            "expected_metrics": ["order_count"],
            "expected_sql": f"SELECT COUNT(*) AS order_count FROM orders WHERE strftime('%Y-%m', order_purchase_timestamp) = '{m}'",
            "category": "Orders & Transactions",
            "domain": "Orders & Transactions",
            "query_type": "single_value",
            "difficulty": "easy",
        })
        items.append({
            "question": f"How many orders were canceled in month {m}?",
            "expected_tables": ["orders"],
            "expected_metrics": ["canceled_count"],
            "expected_sql": f"SELECT COUNT(*) AS canceled_count FROM orders WHERE strftime('%Y-%m', order_purchase_timestamp) = '{m}' AND order_status = 'canceled'",
            "category": "Orders & Transactions",
            "domain": "Orders & Transactions",
            "query_type": "single_value",
            "difficulty": "medium",
        })

    # =========================================================================
    # DOMAIN 3: Customers & Geography (Target: 65 queries)
    # =========================================================================
    # Single Value (2)
    items.append({
        "question": "How many total unique customers (by unique id) exist in the database?",
        "expected_tables": ["customers"],
        "expected_metrics": ["unique_customers"],
        "expected_sql": "SELECT COUNT(DISTINCT customer_unique_id) AS unique_customers FROM customers",
        "category": "Customers & Geography",
        "domain": "Customers & Geography",
        "query_type": "single_value",
        "difficulty": "easy",
    })
    items.append({
        "question": "How many unique customer cities are represented in the dataset?",
        "expected_tables": ["customers"],
        "expected_metrics": ["city_count"],
        "expected_sql": "SELECT COUNT(DISTINCT customer_city) AS city_count FROM customers",
        "category": "Customers & Geography",
        "domain": "Customers & Geography",
        "query_type": "single_value",
        "difficulty": "easy",
    })

    # Time series (1)
    items.append({
        "question": "What is the monthly new customer acquisition trend across all recorded months?",
        "expected_tables": ["customers", "orders"],
        "expected_metrics": ["first_month", "new_customer_count"],
        "expected_sql": "WITH first_orders AS (SELECT c.customer_unique_id, MIN(o.order_purchase_timestamp) AS first_order FROM customers c JOIN orders o ON c.customer_id = o.customer_id GROUP BY c.customer_unique_id) SELECT strftime('%Y-%m', first_order) AS first_month, COUNT(*) AS new_customer_count FROM first_orders GROUP BY first_month ORDER BY first_month",
        "category": "Customers & Geography",
        "domain": "Customers & Geography",
        "query_type": "time_series",
        "difficulty": "hard",
    })

    # Aggregated table (2)
    items.append({
        "question": "What is the geographic distribution of customers, orders, and revenue across all Brazilian states?",
        "expected_tables": ["customers", "orders", "order_items"],
        "expected_metrics": ["customer_state", "customer_count", "order_count", "total_revenue"],
        "expected_sql": "SELECT c.customer_state, COUNT(DISTINCT c.customer_unique_id) AS customer_count, COUNT(DISTINCT o.order_id) AS order_count, ROUND(SUM(oi.price), 2) AS total_revenue FROM customers c JOIN orders o ON c.customer_id = o.customer_id JOIN order_items oi ON o.order_id = oi.order_id GROUP BY c.customer_state ORDER BY total_revenue DESC",
        "category": "Customers & Geography",
        "domain": "Customers & Geography",
        "query_type": "aggregated_table",
        "difficulty": "hard",
    })
    items.append({
        "question": "What is the customer count breakdown across all states?",
        "expected_tables": ["customers"],
        "expected_metrics": ["customer_state", "customer_count"],
        "expected_sql": "SELECT customer_state, COUNT(DISTINCT customer_unique_id) AS customer_count FROM customers GROUP BY customer_state ORDER BY customer_count DESC",
        "category": "Customers & Geography",
        "domain": "Customers & Geography",
        "query_type": "aggregated_table",
        "difficulty": "easy",
    })

    # Rankings (15)
    for n in [3, 5, 10, 15, 20]:
        items.append({
            "question": f"Who are the top {n} customers by total lifetime spend?",
            "expected_tables": ["customers", "orders", "order_items"],
            "expected_metrics": ["customer_unique_id", "total_spend"],
            "expected_sql": f"SELECT c.customer_unique_id, ROUND(SUM(oi.price), 2) AS total_spend FROM customers c JOIN orders o ON c.customer_id = o.customer_id JOIN order_items oi ON o.order_id = oi.order_id GROUP BY c.customer_unique_id ORDER BY total_spend DESC LIMIT {n}",
            "category": "Customers & Geography",
            "domain": "Customers & Geography",
            "query_type": "ranked_list",
            "difficulty": "medium",
        })
        items.append({
            "question": f"What are the top {n} customer cities by total revenue generated?",
            "expected_tables": ["customers", "orders", "order_items"],
            "expected_metrics": ["customer_city", "total_revenue"],
            "expected_sql": f"SELECT c.customer_city, ROUND(SUM(oi.price), 2) AS total_revenue FROM customers c JOIN orders o ON c.customer_id = o.customer_id JOIN order_items oi ON o.order_id = oi.order_id GROUP BY c.customer_city ORDER BY total_revenue DESC LIMIT {n}",
            "category": "Customers & Geography",
            "domain": "Customers & Geography",
            "query_type": "ranked_list",
            "difficulty": "medium",
        })
        items.append({
            "question": f"What are the top {n} customer cities by unique customer count?",
            "expected_tables": ["customers"],
            "expected_metrics": ["customer_city", "customer_count"],
            "expected_sql": f"SELECT customer_city, COUNT(DISTINCT customer_unique_id) AS customer_count FROM customers GROUP BY customer_city ORDER BY customer_count DESC LIMIT {n}",
            "category": "Customers & Geography",
            "domain": "Customers & Geography",
            "query_type": "ranked_list",
            "difficulty": "medium",
        })

    # Parameterized single value (45)
    for st in states_20:
        items.append({
            "question": f"How many unique customers are located in state {st}?",
            "expected_tables": ["customers"],
            "expected_metrics": ["customer_count"],
            "expected_sql": f"SELECT COUNT(DISTINCT customer_unique_id) AS customer_count FROM customers WHERE customer_state = '{st}'",
            "category": "Customers & Geography",
            "domain": "Customers & Geography",
            "query_type": "single_value",
            "difficulty": "easy",
        })
        items.append({
            "question": f"What is the total revenue from customers in state {st}?",
            "expected_tables": ["customers", "orders", "order_items"],
            "expected_metrics": ["total_revenue"],
            "expected_sql": f"SELECT ROUND(SUM(oi.price), 2) AS total_revenue FROM customers c JOIN orders o ON c.customer_id = o.customer_id JOIN order_items oi ON o.order_id = oi.order_id WHERE c.customer_state = '{st}'",
            "category": "Customers & Geography",
            "domain": "Customers & Geography",
            "query_type": "single_value",
            "difficulty": "medium",
        })

    for city in ["sao paulo", "rio de janeiro", "belo horizonte", "brasilia", "curitiba"]:
        items.append({
            "question": f"What is the total revenue from customers in city '{city}'?",
            "expected_tables": ["customers", "orders", "order_items"],
            "expected_metrics": ["total_revenue"],
            "expected_sql": f"SELECT ROUND(SUM(oi.price), 2) AS total_revenue FROM customers c JOIN orders o ON c.customer_id = o.customer_id JOIN order_items oi ON o.order_id = oi.order_id WHERE c.customer_city = '{city}'",
            "category": "Customers & Geography",
            "domain": "Customers & Geography",
            "query_type": "single_value",
            "difficulty": "medium",
        })

    # =========================================================================
    # DOMAIN 4: Products & Categories (Target: 65 queries)
    # =========================================================================
    # Single Value (3)
    items.append({
        "question": "How many unique products are registered in the catalog?",
        "expected_tables": ["products"],
        "expected_metrics": ["product_count"],
        "expected_sql": "SELECT COUNT(DISTINCT product_id) AS product_count FROM products",
        "category": "Products & Categories",
        "domain": "Products & Categories",
        "query_type": "single_value",
        "difficulty": "easy",
    })
    items.append({
        "question": "How many distinct product categories exist in the catalog?",
        "expected_tables": ["products"],
        "expected_metrics": ["category_count"],
        "expected_sql": "SELECT COUNT(DISTINCT product_category_name) AS category_count FROM products WHERE product_category_name IS NOT NULL",
        "category": "Products & Categories",
        "domain": "Products & Categories",
        "query_type": "single_value",
        "difficulty": "easy",
    })
    items.append({
        "question": "What is the average item price across all sold products?",
        "expected_tables": ["order_items"],
        "expected_metrics": ["avg_price"],
        "expected_sql": "SELECT ROUND(AVG(price), 2) AS avg_price FROM order_items",
        "category": "Products & Categories",
        "domain": "Products & Categories",
        "query_type": "single_value",
        "difficulty": "easy",
    })

    # Time series (5)
    top_cats = ["beleza_saude", "relogios_presentes", "cama_mesa_banho", "esporte_lazer", "informatica_acessorios"]
    for cat in top_cats:
        items.append({
            "question": f"What is the monthly sales revenue trend for category '{cat}'?",
            "expected_tables": ["products", "orders", "order_items"],
            "expected_metrics": ["month", "category_revenue"],
            "expected_sql": f"SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month, ROUND(SUM(oi.price), 2) AS category_revenue FROM products p JOIN order_items oi ON p.product_id = oi.product_id JOIN orders o ON oi.order_id = o.order_id WHERE p.product_category_name = '{cat}' GROUP BY month ORDER BY month",
            "category": "Products & Categories",
            "domain": "Products & Categories",
            "query_type": "time_series",
            "difficulty": "hard",
        })

    # Aggregated tables (7)
    items.append({
        "question": "What is the complete revenue, unit volume, and average price summary by product category?",
        "expected_tables": ["products", "order_items"],
        "expected_metrics": ["product_category_name", "units_sold", "total_revenue", "avg_price"],
        "expected_sql": "SELECT p.product_category_name, COUNT(*) AS units_sold, ROUND(SUM(oi.price), 2) AS total_revenue, ROUND(AVG(oi.price), 2) AS avg_price FROM products p JOIN order_items oi ON p.product_id = oi.product_id WHERE p.product_category_name IS NOT NULL GROUP BY p.product_category_name ORDER BY total_revenue DESC",
        "category": "Products & Categories",
        "domain": "Products & Categories",
        "query_type": "aggregated_table",
        "difficulty": "medium",
    })
    items.append({
        "question": "What is the revenue and units sold summary by English category translation?",
        "expected_tables": ["products", "order_items", "product_category_name_translation"],
        "expected_metrics": ["product_category_name_english", "units_sold", "total_revenue"],
        "expected_sql": "SELECT t.product_category_name_english, COUNT(*) AS units_sold, ROUND(SUM(oi.price), 2) AS total_revenue FROM products p JOIN order_items oi ON p.product_id = oi.product_id JOIN product_category_name_translation t ON p.product_category_name = t.product_category_name GROUP BY t.product_category_name_english ORDER BY total_revenue DESC",
        "category": "Products & Categories",
        "domain": "Products & Categories",
        "query_type": "aggregated_table",
        "difficulty": "hard",
    })
    for n in [3, 5, 10, 15, 20]:
        items.append({
            "question": f"What is the average product weight (in grams) and item count for the top {n} highest revenue categories?",
            "expected_tables": ["products", "order_items"],
            "expected_metrics": ["product_category_name", "avg_weight_g", "total_revenue"],
            "expected_sql": f"SELECT p.product_category_name, ROUND(AVG(p.product_weight_g), 2) AS avg_weight_g, ROUND(SUM(oi.price), 2) AS total_revenue FROM products p JOIN order_items oi ON p.product_id = oi.product_id WHERE p.product_category_name IS NOT NULL GROUP BY p.product_category_name ORDER BY total_revenue DESC LIMIT {n}",
            "category": "Products & Categories",
            "domain": "Products & Categories",
            "query_type": "aggregated_table",
            "difficulty": "hard",
        })

    # Rankings (20)
    for n in [3, 5, 10, 15, 20]:
        items.append({
            "question": f"What are the top {n} product categories by total sales revenue?",
            "expected_tables": ["products", "order_items"],
            "expected_metrics": ["product_category_name", "total_revenue"],
            "expected_sql": f"SELECT p.product_category_name, ROUND(SUM(oi.price), 2) AS total_revenue FROM products p JOIN order_items oi ON p.product_id = oi.product_id WHERE p.product_category_name IS NOT NULL GROUP BY p.product_category_name ORDER BY total_revenue DESC LIMIT {n}",
            "category": "Products & Categories",
            "domain": "Products & Categories",
            "query_type": "ranked_list",
            "difficulty": "medium",
        })
        items.append({
            "question": f"What are the top {n} product categories by units sold count?",
            "expected_tables": ["products", "order_items"],
            "expected_metrics": ["product_category_name", "units_sold"],
            "expected_sql": f"SELECT p.product_category_name, COUNT(*) AS units_sold FROM products p JOIN order_items oi ON p.product_id = oi.product_id WHERE p.product_category_name IS NOT NULL GROUP BY p.product_category_name ORDER BY units_sold DESC LIMIT {n}",
            "category": "Products & Categories",
            "domain": "Products & Categories",
            "query_type": "ranked_list",
            "difficulty": "medium",
        })
        items.append({
            "question": f"What are the top {n} highest revenue generating individual products (by product_id)?",
            "expected_tables": ["order_items"],
            "expected_metrics": ["product_id", "total_revenue"],
            "expected_sql": f"SELECT product_id, ROUND(SUM(price), 2) AS total_revenue FROM order_items GROUP BY product_id ORDER BY total_revenue DESC LIMIT {n}",
            "category": "Products & Categories",
            "domain": "Products & Categories",
            "query_type": "ranked_list",
            "difficulty": "medium",
        })
        items.append({
            "question": f"What are the top {n} categories by average product price (minimum 100 units sold)?",
            "expected_tables": ["products", "order_items"],
            "expected_metrics": ["product_category_name", "avg_price"],
            "expected_sql": f"SELECT p.product_category_name, ROUND(AVG(oi.price), 2) AS avg_price FROM products p JOIN order_items oi ON p.product_id = oi.product_id WHERE p.product_category_name IS NOT NULL GROUP BY p.product_category_name HAVING COUNT(*) >= 100 ORDER BY avg_price DESC LIMIT {n}",
            "category": "Products & Categories",
            "domain": "Products & Categories",
            "query_type": "ranked_list",
            "difficulty": "hard",
        })

    # Parameterized single value (30)
    for cat in all_categories:
        items.append({
            "question": f"What is the total revenue for product category '{cat}'?",
            "expected_tables": ["products", "order_items"],
            "expected_metrics": ["total_revenue"],
            "expected_sql": f"SELECT ROUND(SUM(oi.price), 2) AS total_revenue FROM products p JOIN order_items oi ON p.product_id = oi.product_id WHERE p.product_category_name = '{cat}'",
            "category": "Products & Categories",
            "domain": "Products & Categories",
            "query_type": "single_value",
            "difficulty": "medium",
        })
        items.append({
            "question": f"How many items were sold in category '{cat}'?",
            "expected_tables": ["products", "order_items"],
            "expected_metrics": ["item_count"],
            "expected_sql": f"SELECT COUNT(*) AS item_count FROM products p JOIN order_items oi ON p.product_id = oi.product_id WHERE p.product_category_name = '{cat}'",
            "category": "Products & Categories",
            "domain": "Products & Categories",
            "query_type": "single_value",
            "difficulty": "medium",
        })

    # =========================================================================
    # DOMAIN 5: Logistics & Operations (Target: 60 queries)
    # =========================================================================
    # Single Value (3)
    items.append({
        "question": "What is the average delivery time in days for delivered customer orders?",
        "expected_tables": ["orders"],
        "expected_metrics": ["avg_delivery_days"],
        "expected_sql": "SELECT ROUND(AVG(julianday(order_delivered_customer_date) - julianday(order_purchase_timestamp)), 2) AS avg_delivery_days FROM orders WHERE order_status = 'delivered' AND order_delivered_customer_date IS NOT NULL",
        "category": "Logistics & Operations",
        "domain": "Logistics & Operations",
        "query_type": "single_value",
        "difficulty": "medium",
    })
    items.append({
        "question": "What is the percentage of delivered orders that arrived past their estimated delivery date?",
        "expected_tables": ["orders"],
        "expected_metrics": ["late_delivery_rate"],
        "expected_sql": "SELECT ROUND(CAST(SUM(CASE WHEN order_delivered_customer_date > order_estimated_delivery_date THEN 1.0 ELSE 0.0 END) AS REAL) / COUNT(*), 4) AS late_delivery_rate FROM orders WHERE order_status = 'delivered' AND order_delivered_customer_date IS NOT NULL",
        "category": "Logistics & Operations",
        "domain": "Logistics & Operations",
        "query_type": "single_value",
        "difficulty": "medium",
    })
    items.append({
        "question": "What is the average carrier transit time in days (carrier handoff to customer delivery)?",
        "expected_tables": ["orders"],
        "expected_metrics": ["avg_transit_days"],
        "expected_sql": "SELECT ROUND(AVG(julianday(order_delivered_customer_date) - julianday(order_delivered_carrier_date)), 2) AS avg_transit_days FROM orders WHERE order_status = 'delivered' AND order_delivered_customer_date IS NOT NULL AND order_delivered_carrier_date IS NOT NULL",
        "category": "Logistics & Operations",
        "domain": "Logistics & Operations",
        "query_type": "single_value",
        "difficulty": "medium",
    })

    # Time series (5)
    items.append({
        "question": "What is the monthly average delivery time (in days) trend for delivered orders?",
        "expected_tables": ["orders"],
        "expected_metrics": ["month", "avg_delivery_days"],
        "expected_sql": "SELECT strftime('%Y-%m', order_purchase_timestamp) AS month, ROUND(AVG(julianday(order_delivered_customer_date) - julianday(order_purchase_timestamp)), 2) AS avg_delivery_days FROM orders WHERE order_status = 'delivered' AND order_delivered_customer_date IS NOT NULL GROUP BY month ORDER BY month",
        "category": "Logistics & Operations",
        "domain": "Logistics & Operations",
        "query_type": "time_series",
        "difficulty": "hard",
    })
    items.append({
        "question": "What is the monthly late delivery percentage trend across all delivered orders?",
        "expected_tables": ["orders"],
        "expected_metrics": ["month", "late_rate"],
        "expected_sql": "SELECT strftime('%Y-%m', order_purchase_timestamp) AS month, ROUND(CAST(SUM(CASE WHEN order_delivered_customer_date > order_estimated_delivery_date THEN 1.0 ELSE 0.0 END) AS REAL) / COUNT(*), 4) AS late_rate FROM orders WHERE order_status = 'delivered' AND order_delivered_customer_date IS NOT NULL GROUP BY month ORDER BY month",
        "category": "Logistics & Operations",
        "domain": "Logistics & Operations",
        "query_type": "time_series",
        "difficulty": "hard",
    })
    items.append({
        "question": "What is the monthly average carrier transit time in days trend across delivered orders?",
        "expected_tables": ["orders"],
        "expected_metrics": ["month", "avg_transit_days"],
        "expected_sql": "SELECT strftime('%Y-%m', order_purchase_timestamp) AS month, ROUND(AVG(julianday(order_delivered_customer_date) - julianday(order_delivered_carrier_date)), 2) AS avg_transit_days FROM orders WHERE order_status = 'delivered' AND order_delivered_customer_date IS NOT NULL AND order_delivered_carrier_date IS NOT NULL GROUP BY month ORDER BY month",
        "category": "Logistics & Operations",
        "domain": "Logistics & Operations",
        "query_type": "time_series",
        "difficulty": "hard",
    })
    items.append({
        "question": "What is the monthly delivery time trend for orders delivered to state SP?",
        "expected_tables": ["customers", "orders"],
        "expected_metrics": ["month", "avg_delivery_days"],
        "expected_sql": "SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month, ROUND(AVG(julianday(o.order_delivered_customer_date) - julianday(o.order_purchase_timestamp)), 2) AS avg_delivery_days FROM customers c JOIN orders o ON c.customer_id = o.customer_id WHERE c.customer_state = 'SP' AND o.order_status = 'delivered' AND o.order_delivered_customer_date IS NOT NULL GROUP BY month ORDER BY month",
        "category": "Logistics & Operations",
        "domain": "Logistics & Operations",
        "query_type": "time_series",
        "difficulty": "hard",
    })
    items.append({
        "question": "What is the monthly delivery time trend for orders delivered to state RJ?",
        "expected_tables": ["customers", "orders"],
        "expected_metrics": ["month", "avg_delivery_days"],
        "expected_sql": "SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month, ROUND(AVG(julianday(o.order_delivered_customer_date) - julianday(o.order_purchase_timestamp)), 2) AS avg_delivery_days FROM customers c JOIN orders o ON c.customer_id = o.customer_id WHERE c.customer_state = 'RJ' AND o.order_status = 'delivered' AND o.order_delivered_customer_date IS NOT NULL GROUP BY month ORDER BY month",
        "category": "Logistics & Operations",
        "domain": "Logistics & Operations",
        "query_type": "time_series",
        "difficulty": "hard",
    })

    # Aggregated tables (12)
    items.append({
        "question": "What is the average delivery time in days and late delivery rate breakdown by customer state?",
        "expected_tables": ["customers", "orders"],
        "expected_metrics": ["customer_state", "delivered_orders", "avg_delivery_days", "late_rate"],
        "expected_sql": "SELECT c.customer_state, COUNT(*) AS delivered_orders, ROUND(AVG(julianday(o.order_delivered_customer_date) - julianday(o.order_purchase_timestamp)), 2) AS avg_delivery_days, ROUND(CAST(SUM(CASE WHEN o.order_delivered_customer_date > o.order_estimated_delivery_date THEN 1.0 ELSE 0.0 END) AS REAL) / COUNT(*), 4) AS late_rate FROM customers c JOIN orders o ON c.customer_id = o.customer_id WHERE o.order_status = 'delivered' AND o.order_delivered_customer_date IS NOT NULL GROUP BY c.customer_state ORDER BY avg_delivery_days DESC",
        "category": "Logistics & Operations",
        "domain": "Logistics & Operations",
        "query_type": "aggregated_table",
        "difficulty": "hard",
    })
    items.append({
        "question": "What is the average freight value and total orders breakdown across product weight brackets?",
        "expected_tables": ["products", "order_items"],
        "expected_metrics": ["weight_tier", "item_count", "avg_freight"],
        "expected_sql": "SELECT CASE WHEN p.product_weight_g < 500 THEN '1. Under 500g' WHEN p.product_weight_g < 2000 THEN '2. 500g-2kg' WHEN p.product_weight_g < 5000 THEN '3. 2kg-5kg' ELSE '4. Over 5kg' END AS weight_tier, COUNT(*) AS item_count, ROUND(AVG(oi.freight_value), 2) AS avg_freight FROM products p JOIN order_items oi ON p.product_id = oi.product_id WHERE p.product_weight_g IS NOT NULL GROUP BY weight_tier ORDER BY weight_tier",
        "category": "Logistics & Operations",
        "domain": "Logistics & Operations",
        "query_type": "aggregated_table",
        "difficulty": "hard",
    })
    for n in [3, 5, 10, 15, 20]:
        items.append({
            "question": f"What is the average delivery delay in days and order volume for the top {n} states by total orders?",
            "expected_tables": ["customers", "orders"],
            "expected_metrics": ["customer_state", "delivered_orders", "avg_delivery_days"],
            "expected_sql": f"SELECT c.customer_state, COUNT(o.order_id) AS delivered_orders, ROUND(AVG(julianday(o.order_delivered_customer_date) - julianday(o.order_purchase_timestamp)), 2) AS avg_delivery_days FROM customers c JOIN orders o ON c.customer_id = o.customer_id WHERE o.order_status = 'delivered' AND o.order_delivered_customer_date IS NOT NULL GROUP BY c.customer_state ORDER BY delivered_orders DESC LIMIT {n}",
            "category": "Logistics & Operations",
            "domain": "Logistics & Operations",
            "query_type": "aggregated_table",
            "difficulty": "hard",
        })
        items.append({
            "question": f"What is the average freight value paid per order for the top {n} highest revenue customer cities?",
            "expected_tables": ["customers", "orders", "order_items"],
            "expected_metrics": ["customer_city", "avg_freight_per_order"],
            "expected_sql": f"SELECT c.customer_city, ROUND(SUM(oi.freight_value) / COUNT(DISTINCT o.order_id), 2) AS avg_freight_per_order FROM customers c JOIN orders o ON c.customer_id = o.customer_id JOIN order_items oi ON o.order_id = oi.order_id GROUP BY c.customer_city ORDER BY SUM(oi.price) DESC LIMIT {n}",
            "category": "Logistics & Operations",
            "domain": "Logistics & Operations",
            "query_type": "aggregated_table",
            "difficulty": "hard",
        })

    # Rankings (20)
    for n in [3, 5, 10, 15, 20]:
        items.append({
            "question": f"Which top {n} customer states experience the longest average delivery times (in days)?",
            "expected_tables": ["customers", "orders"],
            "expected_metrics": ["customer_state", "avg_delivery_days"],
            "expected_sql": f"SELECT c.customer_state, ROUND(AVG(julianday(o.order_delivered_customer_date) - julianday(o.order_purchase_timestamp)), 2) AS avg_delivery_days FROM customers c JOIN orders o ON c.customer_id = o.customer_id WHERE o.order_status = 'delivered' AND o.order_delivered_customer_date IS NOT NULL GROUP BY c.customer_state ORDER BY avg_delivery_days DESC LIMIT {n}",
            "category": "Logistics & Operations",
            "domain": "Logistics & Operations",
            "query_type": "ranked_list",
            "difficulty": "medium",
        })
        items.append({
            "question": f"Which top {n} customer states have the fastest average delivery times (in days)?",
            "expected_tables": ["customers", "orders"],
            "expected_metrics": ["customer_state", "avg_delivery_days"],
            "expected_sql": f"SELECT c.customer_state, ROUND(AVG(julianday(o.order_delivered_customer_date) - julianday(o.order_purchase_timestamp)), 2) AS avg_delivery_days FROM customers c JOIN orders o ON c.customer_id = o.customer_id WHERE o.order_status = 'delivered' AND o.order_delivered_customer_date IS NOT NULL GROUP BY c.customer_state ORDER BY avg_delivery_days ASC LIMIT {n}",
            "category": "Logistics & Operations",
            "domain": "Logistics & Operations",
            "query_type": "ranked_list",
            "difficulty": "medium",
        })
        items.append({
            "question": f"Which top {n} product categories have the highest average freight value (minimum 50 orders)?",
            "expected_tables": ["products", "order_items"],
            "expected_metrics": ["product_category_name", "avg_freight"],
            "expected_sql": f"SELECT p.product_category_name, ROUND(AVG(oi.freight_value), 2) AS avg_freight FROM products p JOIN order_items oi ON p.product_id = oi.product_id WHERE p.product_category_name IS NOT NULL GROUP BY p.product_category_name HAVING COUNT(*) >= 50 ORDER BY avg_freight DESC LIMIT {n}",
            "category": "Logistics & Operations",
            "domain": "Logistics & Operations",
            "query_type": "ranked_list",
            "difficulty": "hard",
        })
        items.append({
            "question": f"Which top {n} product categories have the lowest average freight value (minimum 50 orders)?",
            "expected_tables": ["products", "order_items"],
            "expected_metrics": ["product_category_name", "avg_freight"],
            "expected_sql": f"SELECT p.product_category_name, ROUND(AVG(oi.freight_value), 2) AS avg_freight FROM products p JOIN order_items oi ON p.product_id = oi.product_id WHERE p.product_category_name IS NOT NULL GROUP BY p.product_category_name HAVING COUNT(*) >= 50 ORDER BY avg_freight ASC LIMIT {n}",
            "category": "Logistics & Operations",
            "domain": "Logistics & Operations",
            "query_type": "ranked_list",
            "difficulty": "hard",
        })

    # Parameterized single value (20)
    for st in states_20:
        items.append({
            "question": f"What is the average delivery time in days for delivered orders in state {st}?",
            "expected_tables": ["customers", "orders"],
            "expected_metrics": ["avg_delivery_days"],
            "expected_sql": f"SELECT ROUND(AVG(julianday(o.order_delivered_customer_date) - julianday(o.order_purchase_timestamp)), 2) AS avg_delivery_days FROM customers c JOIN orders o ON c.customer_id = o.customer_id WHERE c.customer_state = '{st}' AND o.order_status = 'delivered' AND o.order_delivered_customer_date IS NOT NULL",
            "category": "Logistics & Operations",
            "domain": "Logistics & Operations",
            "query_type": "single_value",
            "difficulty": "medium",
        })

    # =========================================================================
    # DOMAIN 6: Sellers & Fulfillment (Target: 60 queries)
    # =========================================================================
    # Single Value (2)
    items.append({
        "question": "How many distinct sellers are registered in the dataset?",
        "expected_tables": ["sellers"],
        "expected_metrics": ["total_sellers"],
        "expected_sql": "SELECT COUNT(DISTINCT seller_id) AS total_sellers FROM sellers",
        "category": "Sellers & Fulfillment",
        "domain": "Sellers & Fulfillment",
        "query_type": "single_value",
        "difficulty": "easy",
    })
    items.append({
        "question": "What is the average revenue fulfilled per seller across all active sellers?",
        "expected_tables": ["order_items"],
        "expected_metrics": ["avg_rev_per_seller"],
        "expected_sql": "SELECT ROUND(CAST(SUM(price) AS REAL) / COUNT(DISTINCT seller_id), 2) AS avg_rev_per_seller FROM order_items",
        "category": "Sellers & Fulfillment",
        "domain": "Sellers & Fulfillment",
        "query_type": "single_value",
        "difficulty": "medium",
    })

    # Time series (4)
    items.append({
        "question": "What is the monthly active seller count trend across all recorded months?",
        "expected_tables": ["orders", "order_items"],
        "expected_metrics": ["month", "active_sellers"],
        "expected_sql": "SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month, COUNT(DISTINCT oi.seller_id) AS active_sellers FROM orders o JOIN order_items oi ON o.order_id = oi.order_id GROUP BY month ORDER BY month",
        "category": "Sellers & Fulfillment",
        "domain": "Sellers & Fulfillment",
        "query_type": "time_series",
        "difficulty": "medium",
    })
    items.append({
        "question": "What is the monthly trend of active sellers in 2017?",
        "expected_tables": ["orders", "order_items"],
        "expected_metrics": ["month", "active_sellers"],
        "expected_sql": "SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month, COUNT(DISTINCT oi.seller_id) AS active_sellers FROM orders o JOIN order_items oi ON o.order_id = oi.order_id WHERE strftime('%Y', o.order_purchase_timestamp) = '2017' GROUP BY month ORDER BY month",
        "category": "Sellers & Fulfillment",
        "domain": "Sellers & Fulfillment",
        "query_type": "time_series",
        "difficulty": "medium",
    })
    items.append({
        "question": "What is the monthly trend of active sellers in 2018?",
        "expected_tables": ["orders", "order_items"],
        "expected_metrics": ["month", "active_sellers"],
        "expected_sql": "SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month, COUNT(DISTINCT oi.seller_id) AS active_sellers FROM orders o JOIN order_items oi ON o.order_id = oi.order_id WHERE strftime('%Y', o.order_purchase_timestamp) = '2018' GROUP BY month ORDER BY month",
        "category": "Sellers & Fulfillment",
        "domain": "Sellers & Fulfillment",
        "query_type": "time_series",
        "difficulty": "medium",
    })
    items.append({
        "question": "What is the monthly average revenue per active seller trend across all months?",
        "expected_tables": ["orders", "order_items"],
        "expected_metrics": ["month", "avg_seller_revenue"],
        "expected_sql": "SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month, ROUND(CAST(SUM(oi.price) AS REAL) / COUNT(DISTINCT oi.seller_id), 2) AS avg_seller_revenue FROM orders o JOIN order_items oi ON o.order_id = oi.order_id GROUP BY month ORDER BY month",
        "category": "Sellers & Fulfillment",
        "domain": "Sellers & Fulfillment",
        "query_type": "time_series",
        "difficulty": "hard",
    })

    # Aggregated tables (4)
    items.append({
        "question": "What is the distribution of sellers, order items fulfilled, and total revenue by seller state?",
        "expected_tables": ["sellers", "order_items"],
        "expected_metrics": ["seller_state", "seller_count", "items_sold", "total_revenue"],
        "expected_sql": "SELECT s.seller_state, COUNT(DISTINCT s.seller_id) AS seller_count, COUNT(oi.order_item_id) AS items_sold, ROUND(SUM(oi.price), 2) AS total_revenue FROM sellers s JOIN order_items oi ON s.seller_id = oi.seller_id GROUP BY s.seller_state ORDER BY total_revenue DESC",
        "category": "Sellers & Fulfillment",
        "domain": "Sellers & Fulfillment",
        "query_type": "aggregated_table",
        "difficulty": "hard",
    })
    items.append({
        "question": "What is the total seller count distribution across all seller states?",
        "expected_tables": ["sellers"],
        "expected_metrics": ["seller_state", "seller_count"],
        "expected_sql": "SELECT seller_state, COUNT(*) AS seller_count FROM sellers GROUP BY seller_state ORDER BY seller_count DESC",
        "category": "Sellers & Fulfillment",
        "domain": "Sellers & Fulfillment",
        "query_type": "aggregated_table",
        "difficulty": "easy",
    })
    items.append({
        "question": "What is the average freight value per item fulfilled by seller state?",
        "expected_tables": ["sellers", "order_items"],
        "expected_metrics": ["seller_state", "avg_freight"],
        "expected_sql": "SELECT s.seller_state, ROUND(AVG(oi.freight_value), 2) AS avg_freight FROM sellers s JOIN order_items oi ON s.seller_id = oi.seller_id GROUP BY s.seller_state ORDER BY avg_freight DESC",
        "category": "Sellers & Fulfillment",
        "domain": "Sellers & Fulfillment",
        "query_type": "aggregated_table",
        "difficulty": "medium",
    })
    items.append({
        "question": "What is the item volume and revenue contribution of top 10 seller cities?",
        "expected_tables": ["sellers", "order_items"],
        "expected_metrics": ["seller_city", "items_sold", "total_revenue"],
        "expected_sql": "SELECT s.seller_city, COUNT(oi.order_item_id) AS items_sold, ROUND(SUM(oi.price), 2) AS total_revenue FROM sellers s JOIN order_items oi ON s.seller_id = oi.seller_id GROUP BY s.seller_city ORDER BY total_revenue DESC LIMIT 10",
        "category": "Sellers & Fulfillment",
        "domain": "Sellers & Fulfillment",
        "query_type": "aggregated_table",
        "difficulty": "hard",
    })

    # Rankings (20)
    for n in [3, 5, 10, 15, 20]:
        items.append({
            "question": f"What are the top {n} sellers by total sales revenue?",
            "expected_tables": ["order_items"],
            "expected_metrics": ["seller_id", "total_revenue"],
            "expected_sql": f"SELECT seller_id, ROUND(SUM(price), 2) AS total_revenue FROM order_items GROUP BY seller_id ORDER BY total_revenue DESC LIMIT {n}",
            "category": "Sellers & Fulfillment",
            "domain": "Sellers & Fulfillment",
            "query_type": "ranked_list",
            "difficulty": "medium",
        })
        items.append({
            "question": f"What are the top {n} sellers by total items fulfilled?",
            "expected_tables": ["order_items"],
            "expected_metrics": ["seller_id", "items_sold"],
            "expected_sql": f"SELECT seller_id, COUNT(*) AS items_sold FROM order_items GROUP BY seller_id ORDER BY items_sold DESC LIMIT {n}",
            "category": "Sellers & Fulfillment",
            "domain": "Sellers & Fulfillment",
            "query_type": "ranked_list",
            "difficulty": "medium",
        })
        items.append({
            "question": f"What are the top {n} seller cities by total registered seller count?",
            "expected_tables": ["sellers"],
            "expected_metrics": ["seller_city", "seller_count"],
            "expected_sql": f"SELECT seller_city, COUNT(*) AS seller_count FROM sellers GROUP BY seller_city ORDER BY seller_count DESC LIMIT {n}",
            "category": "Sellers & Fulfillment",
            "domain": "Sellers & Fulfillment",
            "query_type": "ranked_list",
            "difficulty": "medium",
        })
        items.append({
            "question": f"What are the top {n} seller cities by total revenue fulfilled?",
            "expected_tables": ["sellers", "order_items"],
            "expected_metrics": ["seller_city", "total_revenue"],
            "expected_sql": f"SELECT s.seller_city, ROUND(SUM(oi.price), 2) AS total_revenue FROM sellers s JOIN order_items oi ON s.seller_id = oi.seller_id GROUP BY s.seller_city ORDER BY total_revenue DESC LIMIT {n}",
            "category": "Sellers & Fulfillment",
            "domain": "Sellers & Fulfillment",
            "query_type": "ranked_list",
            "difficulty": "medium",
        })

    # Parameterized single value (30)
    for st in states_20:
        items.append({
            "question": f"How many registered sellers are located in state {st}?",
            "expected_tables": ["sellers"],
            "expected_metrics": ["seller_count"],
            "expected_sql": f"SELECT COUNT(DISTINCT seller_id) AS seller_count FROM sellers WHERE seller_state = '{st}'",
            "category": "Sellers & Fulfillment",
            "domain": "Sellers & Fulfillment",
            "query_type": "single_value",
            "difficulty": "easy",
        })
    for st in ["SP", "PR", "MG", "RJ", "SC", "RS", "BA", "DF", "GO", "PE"]:
        items.append({
            "question": f"What is the total revenue fulfilled by sellers in state {st}?",
            "expected_tables": ["sellers", "order_items"],
            "expected_metrics": ["total_revenue"],
            "expected_sql": f"SELECT ROUND(SUM(oi.price), 2) AS total_revenue FROM sellers s JOIN order_items oi ON s.seller_id = oi.seller_id WHERE s.seller_state = '{st}'",
            "category": "Sellers & Fulfillment",
            "domain": "Sellers & Fulfillment",
            "query_type": "single_value",
            "difficulty": "medium",
        })

    # =========================================================================
    # DOMAIN 7: Payments & Installments (Target: 60 queries)
    # =========================================================================
    # Single Value (2)
    items.append({
        "question": "What is the total monetary value processed across all payment records?",
        "expected_tables": ["order_payments"],
        "expected_metrics": ["total_payments"],
        "expected_sql": "SELECT ROUND(SUM(payment_value), 2) AS total_payments FROM order_payments",
        "category": "Payments & Installments",
        "domain": "Payments & Installments",
        "query_type": "single_value",
        "difficulty": "easy",
    })
    items.append({
        "question": "What is the overall average payment value per transaction?",
        "expected_tables": ["order_payments"],
        "expected_metrics": ["avg_payment_value"],
        "expected_sql": "SELECT ROUND(AVG(payment_value), 2) AS avg_payment_value FROM order_payments",
        "category": "Payments & Installments",
        "domain": "Payments & Installments",
        "query_type": "single_value",
        "difficulty": "easy",
    })

    # Time series (8)
    for pt in ["credit_card", "boleto", "voucher", "debit_card"]:
        items.append({
            "question": f"What is the monthly processed payment value trend for '{pt}' payments?",
            "expected_tables": ["orders", "order_payments"],
            "expected_metrics": ["month", "total_payment_value"],
            "expected_sql": f"SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month, ROUND(SUM(p.payment_value), 2) AS total_payment_value FROM orders o JOIN order_payments p ON o.order_id = p.order_id WHERE p.payment_type = '{pt}' GROUP BY month ORDER BY month",
            "category": "Payments & Installments",
            "domain": "Payments & Installments",
            "query_type": "time_series",
            "difficulty": "hard",
        })
        items.append({
            "question": f"What is the monthly transaction count trend for '{pt}' payments?",
            "expected_tables": ["orders", "order_payments"],
            "expected_metrics": ["month", "tx_count"],
            "expected_sql": f"SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month, COUNT(p.payment_sequential) AS tx_count FROM orders o JOIN order_payments p ON o.order_id = p.order_id WHERE p.payment_type = '{pt}' GROUP BY month ORDER BY month",
            "category": "Payments & Installments",
            "domain": "Payments & Installments",
            "query_type": "time_series",
            "difficulty": "hard",
        })

    # Aggregated tables (5)
    items.append({
        "question": "What is the comprehensive breakdown of transaction count, total value, and average value by payment type?",
        "expected_tables": ["order_payments"],
        "expected_metrics": ["payment_type", "transaction_count", "total_payment_value", "avg_payment_value"],
        "expected_sql": "SELECT payment_type, COUNT(*) AS transaction_count, ROUND(SUM(payment_value), 2) AS total_payment_value, ROUND(AVG(payment_value), 2) AS avg_payment_value FROM order_payments GROUP BY payment_type ORDER BY total_payment_value DESC",
        "category": "Payments & Installments",
        "domain": "Payments & Installments",
        "query_type": "aggregated_table",
        "difficulty": "medium",
    })
    items.append({
        "question": "What is the distribution of transaction counts and total payment values across installment counts (1 to 24)?",
        "expected_tables": ["order_payments"],
        "expected_metrics": ["payment_installments", "transaction_count", "total_payment_value"],
        "expected_sql": "SELECT payment_installments, COUNT(*) AS transaction_count, ROUND(SUM(payment_value), 2) AS total_payment_value FROM order_payments GROUP BY payment_installments ORDER BY payment_installments",
        "category": "Payments & Installments",
        "domain": "Payments & Installments",
        "query_type": "aggregated_table",
        "difficulty": "medium",
    })
    for n in [3, 5, 10]:
        items.append({
            "question": f"What is the average transaction value and total transactions for top {n} installment tiers by volume?",
            "expected_tables": ["order_payments"],
            "expected_metrics": ["payment_installments", "tx_count", "avg_value"],
            "expected_sql": f"SELECT payment_installments, COUNT(*) AS tx_count, ROUND(AVG(payment_value), 2) AS avg_value FROM order_payments GROUP BY payment_installments ORDER BY tx_count DESC LIMIT {n}",
            "category": "Payments & Installments",
            "domain": "Payments & Installments",
            "query_type": "aggregated_table",
            "difficulty": "hard",
        })

    # Rankings (15)
    for n in [3, 5, 10, 15, 20]:
        items.append({
            "question": f"What are the top {n} installment counts by total monetary value processed?",
            "expected_tables": ["order_payments"],
            "expected_metrics": ["payment_installments", "total_value"],
            "expected_sql": f"SELECT payment_installments, ROUND(SUM(payment_value), 2) AS total_value FROM order_payments GROUP BY payment_installments ORDER BY total_value DESC LIMIT {n}",
            "category": "Payments & Installments",
            "domain": "Payments & Installments",
            "query_type": "ranked_list",
            "difficulty": "medium",
        })
        items.append({
            "question": f"What are the top {n} installment counts by total transaction count?",
            "expected_tables": ["order_payments"],
            "expected_metrics": ["payment_installments", "tx_count"],
            "expected_sql": f"SELECT payment_installments, COUNT(*) AS tx_count FROM order_payments GROUP BY payment_installments ORDER BY tx_count DESC LIMIT {n}",
            "category": "Payments & Installments",
            "domain": "Payments & Installments",
            "query_type": "ranked_list",
            "difficulty": "medium",
        })
        items.append({
            "question": f"What are the top {n} customer states by credit card payment volume?",
            "expected_tables": ["customers", "orders", "order_payments"],
            "expected_metrics": ["customer_state", "credit_card_revenue"],
            "expected_sql": f"SELECT c.customer_state, ROUND(SUM(p.payment_value), 2) AS credit_card_revenue FROM customers c JOIN orders o ON c.customer_id = o.customer_id JOIN order_payments p ON o.order_id = p.order_id WHERE p.payment_type = 'credit_card' GROUP BY c.customer_state ORDER BY credit_card_revenue DESC LIMIT {n}",
            "category": "Payments & Installments",
            "domain": "Payments & Installments",
            "query_type": "ranked_list",
            "difficulty": "hard",
        })

    # Parameterized single value (30)
    for pt in payment_types:
        items.append({
            "question": f"What is the total payment value processed via {pt}?",
            "expected_tables": ["order_payments"],
            "expected_metrics": ["total_payment_value"],
            "expected_sql": f"SELECT ROUND(SUM(payment_value), 2) AS total_payment_value FROM order_payments WHERE payment_type = '{pt}'",
            "category": "Payments & Installments",
            "domain": "Payments & Installments",
            "query_type": "single_value",
            "difficulty": "easy",
        })
        items.append({
            "question": f"How many transactions were processed using payment type '{pt}'?",
            "expected_tables": ["order_payments"],
            "expected_metrics": ["transaction_count"],
            "expected_sql": f"SELECT COUNT(*) AS transaction_count FROM order_payments WHERE payment_type = '{pt}'",
            "category": "Payments & Installments",
            "domain": "Payments & Installments",
            "query_type": "single_value",
            "difficulty": "easy",
        })
        items.append({
            "question": f"What is the average transaction value for '{pt}' payments?",
            "expected_tables": ["order_payments"],
            "expected_metrics": ["avg_payment_value"],
            "expected_sql": f"SELECT ROUND(AVG(payment_value), 2) AS avg_payment_value FROM order_payments WHERE payment_type = '{pt}'",
            "category": "Payments & Installments",
            "domain": "Payments & Installments",
            "query_type": "single_value",
            "difficulty": "easy",
        })

    for inst in range(1, 10):
        items.append({
            "question": f"What is the total payment value for orders paid in {inst} installments?",
            "expected_tables": ["order_payments"],
            "expected_metrics": ["total_payment_value"],
            "expected_sql": f"SELECT ROUND(SUM(payment_value), 2) AS total_payment_value FROM order_payments WHERE payment_installments = {inst}",
            "category": "Payments & Installments",
            "domain": "Payments & Installments",
            "query_type": "single_value",
            "difficulty": "easy",
        })
        items.append({
            "question": f"How many transactions were paid in exactly {inst} installments?",
            "expected_tables": ["order_payments"],
            "expected_metrics": ["tx_count"],
            "expected_sql": f"SELECT COUNT(*) AS tx_count FROM order_payments WHERE payment_installments = {inst}",
            "category": "Payments & Installments",
            "domain": "Payments & Installments",
            "query_type": "single_value",
            "difficulty": "easy",
        })

    # =========================================================================
    # DOMAIN 8: Reviews & Satisfaction (Target: 60 queries)
    # =========================================================================
    # Single Value (2)
    items.append({
        "question": "What is the overall average customer review score across all reviews?",
        "expected_tables": ["order_reviews"],
        "expected_metrics": ["avg_review_score"],
        "expected_sql": "SELECT ROUND(AVG(review_score), 2) AS avg_review_score FROM order_reviews",
        "category": "Reviews & Satisfaction",
        "domain": "Reviews & Satisfaction",
        "query_type": "single_value",
        "difficulty": "easy",
    })
    items.append({
        "question": "How many total reviews have been submitted by customers?",
        "expected_tables": ["order_reviews"],
        "expected_metrics": ["total_reviews"],
        "expected_sql": "SELECT COUNT(*) AS total_reviews FROM order_reviews",
        "category": "Reviews & Satisfaction",
        "domain": "Reviews & Satisfaction",
        "query_type": "single_value",
        "difficulty": "easy",
    })

    # Time series (4)
    items.append({
        "question": "What is the monthly average review score trend across all recorded months?",
        "expected_tables": ["order_reviews"],
        "expected_metrics": ["month", "avg_review_score"],
        "expected_sql": "SELECT strftime('%Y-%m', review_creation_date) AS month, ROUND(AVG(review_score), 2) AS avg_review_score FROM order_reviews WHERE review_creation_date IS NOT NULL GROUP BY month ORDER BY month",
        "category": "Reviews & Satisfaction",
        "domain": "Reviews & Satisfaction",
        "query_type": "time_series",
        "difficulty": "medium",
    })
    items.append({
        "question": "What is the monthly 1-star review count trend across all recorded months?",
        "expected_tables": ["order_reviews"],
        "expected_metrics": ["month", "one_star_count"],
        "expected_sql": "SELECT strftime('%Y-%m', review_creation_date) AS month, COUNT(*) AS one_star_count FROM order_reviews WHERE review_score = 1 AND review_creation_date IS NOT NULL GROUP BY month ORDER BY month",
        "category": "Reviews & Satisfaction",
        "domain": "Reviews & Satisfaction",
        "query_type": "time_series",
        "difficulty": "medium",
    })
    items.append({
        "question": "What is the monthly 5-star review count trend across all recorded months?",
        "expected_tables": ["order_reviews"],
        "expected_metrics": ["month", "five_star_count"],
        "expected_sql": "SELECT strftime('%Y-%m', review_creation_date) AS month, COUNT(*) AS five_star_count FROM order_reviews WHERE review_score = 5 AND review_creation_date IS NOT NULL GROUP BY month ORDER BY month",
        "category": "Reviews & Satisfaction",
        "domain": "Reviews & Satisfaction",
        "query_type": "time_series",
        "difficulty": "medium",
    })
    items.append({
        "question": "What is the monthly review response volume trend across all recorded months?",
        "expected_tables": ["order_reviews"],
        "expected_metrics": ["month", "total_reviews"],
        "expected_sql": "SELECT strftime('%Y-%m', review_creation_date) AS month, COUNT(*) AS total_reviews FROM order_reviews WHERE review_creation_date IS NOT NULL GROUP BY month ORDER BY month",
        "category": "Reviews & Satisfaction",
        "domain": "Reviews & Satisfaction",
        "query_type": "time_series",
        "difficulty": "medium",
    })

    # Aggregated tables (4)
    items.append({
        "question": "What is the complete count and percentage distribution across review scores (1 through 5)?",
        "expected_tables": ["order_reviews"],
        "expected_metrics": ["review_score", "review_count"],
        "expected_sql": "SELECT review_score, COUNT(*) AS review_count FROM order_reviews GROUP BY review_score ORDER BY review_score",
        "category": "Reviews & Satisfaction",
        "domain": "Reviews & Satisfaction",
        "query_type": "aggregated_table",
        "difficulty": "easy",
    })
    items.append({
        "question": "What is the average review score and total review count breakdown by customer state?",
        "expected_tables": ["customers", "orders", "order_reviews"],
        "expected_metrics": ["customer_state", "review_count", "avg_review_score"],
        "expected_sql": "SELECT c.customer_state, COUNT(r.review_id) AS review_count, ROUND(AVG(r.review_score), 2) AS avg_review_score FROM customers c JOIN orders o ON c.customer_id = o.customer_id JOIN order_reviews r ON o.order_id = r.order_id GROUP BY c.customer_state ORDER BY avg_review_score DESC",
        "category": "Reviews & Satisfaction",
        "domain": "Reviews & Satisfaction",
        "query_type": "aggregated_table",
        "difficulty": "hard",
    })
    items.append({
        "question": "What is the average review score for on-time vs delayed deliveries?",
        "expected_tables": ["orders", "order_reviews"],
        "expected_metrics": ["delivery_status", "order_count", "avg_review_score"],
        "expected_sql": "SELECT CASE WHEN o.order_delivered_customer_date > o.order_estimated_delivery_date THEN 'Delayed' ELSE 'On Time' END AS delivery_status, COUNT(*) AS order_count, ROUND(AVG(r.review_score), 2) AS avg_review_score FROM orders o JOIN order_reviews r ON o.order_id = r.order_id WHERE o.order_status = 'delivered' AND o.order_delivered_customer_date IS NOT NULL GROUP BY delivery_status",
        "category": "Reviews & Satisfaction",
        "domain": "Reviews & Satisfaction",
        "query_type": "aggregated_table",
        "difficulty": "hard",
    })
    items.append({
        "question": "What is the average review score breakdown across order price tiers?",
        "expected_tables": ["order_items", "order_reviews"],
        "expected_metrics": ["price_tier", "review_count", "avg_review_score"],
        "expected_sql": "SELECT CASE WHEN oi.price < 50 THEN '1. Under $50' WHEN oi.price < 150 THEN '2. $50-$150' WHEN oi.price < 500 THEN '3. $150-$500' ELSE '4. Over $500' END AS price_tier, COUNT(r.review_id) AS review_count, ROUND(AVG(r.review_score), 2) AS avg_review_score FROM order_items oi JOIN order_reviews r ON oi.order_id = r.order_id GROUP BY price_tier ORDER BY price_tier",
        "category": "Reviews & Satisfaction",
        "domain": "Reviews & Satisfaction",
        "query_type": "aggregated_table",
        "difficulty": "hard",
    })

    # Rankings (20)
    for n in [3, 5, 10, 15, 20]:
        items.append({
            "question": f"Which top {n} product categories have the highest average customer review score (minimum 50 reviews)?",
            "expected_tables": ["products", "order_items", "order_reviews"],
            "expected_metrics": ["product_category_name", "avg_review_score"],
            "expected_sql": f"SELECT p.product_category_name, ROUND(AVG(r.review_score), 2) AS avg_review_score FROM products p JOIN order_items oi ON p.product_id = oi.product_id JOIN order_reviews r ON oi.order_id = r.order_id WHERE p.product_category_name IS NOT NULL GROUP BY p.product_category_name HAVING COUNT(r.review_id) >= 50 ORDER BY avg_review_score DESC LIMIT {n}",
            "category": "Reviews & Satisfaction",
            "domain": "Reviews & Satisfaction",
            "query_type": "ranked_list",
            "difficulty": "hard",
        })
        items.append({
            "question": f"Which top {n} product categories have the lowest average customer review score (minimum 50 reviews)?",
            "expected_tables": ["products", "order_items", "order_reviews"],
            "expected_metrics": ["product_category_name", "avg_review_score"],
            "expected_sql": f"SELECT p.product_category_name, ROUND(AVG(r.review_score), 2) AS avg_review_score FROM products p JOIN order_items oi ON p.product_id = oi.product_id JOIN order_reviews r ON oi.order_id = r.order_id WHERE p.product_category_name IS NOT NULL GROUP BY p.product_category_name HAVING COUNT(r.review_id) >= 50 ORDER BY avg_review_score ASC LIMIT {n}",
            "category": "Reviews & Satisfaction",
            "domain": "Reviews & Satisfaction",
            "query_type": "ranked_list",
            "difficulty": "hard",
        })
        items.append({
            "question": f"Which top {n} customer states have the highest average review score (minimum 50 reviews)?",
            "expected_tables": ["customers", "orders", "order_reviews"],
            "expected_metrics": ["customer_state", "avg_review_score"],
            "expected_sql": f"SELECT c.customer_state, ROUND(AVG(r.review_score), 2) AS avg_review_score FROM customers c JOIN orders o ON c.customer_id = o.customer_id JOIN order_reviews r ON o.order_id = r.order_id GROUP BY c.customer_state HAVING COUNT(r.review_id) >= 50 ORDER BY avg_review_score DESC LIMIT {n}",
            "category": "Reviews & Satisfaction",
            "domain": "Reviews & Satisfaction",
            "query_type": "ranked_list",
            "difficulty": "hard",
        })
        items.append({
            "question": f"Which top {n} customer states have the lowest average review score (minimum 50 reviews)?",
            "expected_tables": ["customers", "orders", "order_reviews"],
            "expected_metrics": ["customer_state", "avg_review_score"],
            "expected_sql": f"SELECT c.customer_state, ROUND(AVG(r.review_score), 2) AS avg_review_score FROM customers c JOIN orders o ON c.customer_id = o.customer_id JOIN order_reviews r ON o.order_id = r.order_id GROUP BY c.customer_state HAVING COUNT(r.review_id) >= 50 ORDER BY avg_review_score ASC LIMIT {n}",
            "category": "Reviews & Satisfaction",
            "domain": "Reviews & Satisfaction",
            "query_type": "ranked_list",
            "difficulty": "hard",
        })

    # Parameterized single value (30)
    for score in range(1, 6):
        items.append({
            "question": f"How many reviews were submitted with a rating score of {score}?",
            "expected_tables": ["order_reviews"],
            "expected_metrics": ["review_count"],
            "expected_sql": f"SELECT COUNT(*) AS review_count FROM order_reviews WHERE review_score = {score}",
            "category": "Reviews & Satisfaction",
            "domain": "Reviews & Satisfaction",
            "query_type": "single_value",
            "difficulty": "easy",
        })
        items.append({
            "question": f"What is the total revenue from orders that received a review score of {score}?",
            "expected_tables": ["order_reviews", "order_items"],
            "expected_metrics": ["total_revenue"],
            "expected_sql": f"SELECT ROUND(SUM(oi.price), 2) AS total_revenue FROM order_reviews r JOIN order_items oi ON r.order_id = oi.order_id WHERE r.review_score = {score}",
            "category": "Reviews & Satisfaction",
            "domain": "Reviews & Satisfaction",
            "query_type": "single_value",
            "difficulty": "medium",
        })

    for st in states_20:
        items.append({
            "question": f"What is the average review score for orders placed in state {st}?",
            "expected_tables": ["customers", "orders", "order_reviews"],
            "expected_metrics": ["avg_review_score"],
            "expected_sql": f"SELECT ROUND(AVG(r.review_score), 2) AS avg_review_score FROM customers c JOIN orders o ON c.customer_id = o.customer_id JOIN order_reviews r ON o.order_id = r.order_id WHERE c.customer_state = '{st}'",
            "category": "Reviews & Satisfaction",
            "domain": "Reviews & Satisfaction",
            "query_type": "single_value",
            "difficulty": "medium",
        })

    return items


def main():
    conn = sqlite3.connect(DB_PATH)
    items = build_rebalanced_dataset()
    print(f"Total raw items generated: {len(items)}")

    # Ensure uniqueness of questions
    seen = set()
    unique_items = []
    for item in items:
        q = item["question"].strip()
        if q not in seen:
            seen.add(q)
            unique_items.append(item)
        else:
            print(f"Duplicate question dropped: {q}")

    print(f"Unique items count: {len(unique_items)}")

    verified_dataset = []
    print("Executing SQL against database to verify and compute expected_result...")
    for idx, item in enumerate(unique_items):
        try:
            res = run_sql(conn, item["expected_sql"])
            item["id"] = f"q_{idx+1:03d}"
            item["expected_result"] = res
            verified_dataset.append(item)
        except Exception as exc:
            print(f"SQL Error on item {idx}: {exc}\nSQL: {item['expected_sql']}")

    conn.close()
    print(f"Successfully verified {len(verified_dataset)} queries!")

    # Check distributions
    from collections import Counter
    print("Domain distribution:", Counter(x["domain"] for x in verified_dataset))
    print("Query type distribution:", Counter(x["query_type"] for x in verified_dataset))
    print("Difficulty distribution:", Counter(x["difficulty"] for x in verified_dataset))

    if len(verified_dataset) == 500:
        with open(OUT_PATH, "w", encoding="utf-8") as f:
            json.dump(verified_dataset, f, indent=2, default=str)
        print(f"Saved rebalanced 500 dataset to {OUT_PATH}")
    else:
        print(f"WARNING: Verified dataset has {len(verified_dataset)} items (expected 500). Please adjust before overwriting!")


if __name__ == "__main__":
    main()
