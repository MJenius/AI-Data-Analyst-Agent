import sqlite3
import json
from pathlib import Path

DB_PATH = r'C:\Users\mjeni\OneDrive\Desktop\Own Projects\Data Analyst Agent\runtime\analytics.db'
BENCHMARK_PATH = Path(__file__).resolve().parents[1] / 'tests' / 'evaluation' / 'benchmark_dataset.json'
OUTPUT_PATH = Path(__file__).resolve().parents[1] / 'tests' / 'evaluation' / 'benchmark_dataset_v2.json'

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

def run_sql(sql: str):
    cursor.execute(sql)
    cols = [d[0] for d in cursor.description]
    rows = cursor.fetchall()
    return cols, rows

def to_json_value(val):
    if val is None:
        return None
    if isinstance(val, float):
        return round(val, 4)
    return val

def get_expected(sql: str, limit: int = 50) -> dict:
    cols, rows = run_sql(sql)
    result = []
    for row in rows[:limit]:
        result.append({c: to_json_value(v) for c, v in zip(cols, row)})
    return {
        'columns': cols,
        'values': result,
        'row_count': len(rows)
    }

with open(BENCHMARK_PATH, 'r', encoding='utf-8') as f:
    benchmarks = json.load(f)

QUESTION_TO_SQL = {}

def add(question, sql):
    QUESTION_TO_SQL[question] = sql

# Revenue
add("What is the total revenue generated?", "SELECT SUM(oi.price) AS total_revenue FROM order_items oi")
add("What is the monthly revenue trend?", "SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month, SUM(oi.price) AS revenue FROM orders o JOIN order_items oi ON o.order_id = oi.order_id GROUP BY month ORDER BY month")
add("Which month had the highest revenue?", "SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS peak_month, SUM(oi.price) AS revenue FROM orders o JOIN order_items oi ON o.order_id = oi.order_id GROUP BY peak_month ORDER BY revenue DESC LIMIT 1")
add("Which month had the lowest revenue?", "SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS lowest_month, SUM(oi.price) AS revenue FROM orders o JOIN order_items oi ON o.order_id = oi.order_id GROUP BY lowest_month ORDER BY revenue ASC LIMIT 1")
add("What is the average order value (AOV)?", "SELECT AVG(order_total) AS average_order_value FROM (SELECT oi.order_id, SUM(oi.price) AS order_total FROM order_items oi GROUP BY oi.order_id)")
add("How has AOV changed over time?", "SELECT month, AVG(monthly_total) AS average_order_value FROM (SELECT o.order_id, strftime('%Y-%m', o.order_purchase_timestamp) AS month, SUM(oi.price) AS monthly_total FROM orders o JOIN order_items oi ON o.order_id = oi.order_id GROUP BY o.order_id, month) GROUP BY month ORDER BY month")
add("What percentage of revenue comes from top 10% customers?", "WITH customer_revenue AS (SELECT o.customer_id, SUM(oi.price) AS total_spend FROM orders o JOIN order_items oi ON o.order_id = oi.order_id GROUP BY o.customer_id), ranked AS (SELECT total_spend, NTILE(10) OVER (ORDER BY total_spend DESC) AS decile FROM customer_revenue), top10 AS (SELECT SUM(total_spend) AS top_revenue FROM ranked WHERE decile = 1), total AS (SELECT SUM(total_spend) AS total_revenue FROM customer_revenue) SELECT ROUND(100.0 * (SELECT top_revenue FROM top10) / (SELECT total_revenue FROM total), 2) AS customer_revenue_percentage FROM total LIMIT 1")
add("Which days of the week generate the most revenue?", "SELECT CAST(strftime('%w', o.order_purchase_timestamp) AS INTEGER) AS day_of_week, SUM(oi.price) AS revenue FROM orders o JOIN order_items oi ON o.order_id = oi.order_id GROUP BY day_of_week ORDER BY revenue DESC")
add("What is the revenue distribution by hour of the day?", "SELECT CAST(strftime('%H', o.order_purchase_timestamp) AS INTEGER) AS hour, SUM(oi.price) AS revenue FROM orders o JOIN order_items oi ON o.order_id = oi.order_id GROUP BY hour ORDER BY hour")
add("What is the revenue growth rate month-over-month?", "WITH monthly AS (SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month, SUM(oi.price) AS revenue FROM orders o JOIN order_items oi ON o.order_id = oi.order_id GROUP BY month) SELECT month, revenue, ROUND(100.0 * (revenue - LAG(revenue) OVER (ORDER BY month)) / LAG(revenue) OVER (ORDER BY month), 2) AS revenue_growth_rate FROM monthly ORDER BY month")
add("What is the cumulative revenue over time?", "WITH monthly AS (SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month, SUM(oi.price) AS revenue FROM orders o JOIN order_items oi ON o.order_id = oi.order_id GROUP BY month) SELECT month, revenue, SUM(revenue) OVER (ORDER BY month) AS cumulative_revenue FROM monthly ORDER BY month")
add("Which payment type contributes most to revenue?", "SELECT op.payment_type, SUM(op.payment_value) AS total_revenue FROM order_payments op GROUP BY op.payment_type ORDER BY total_revenue DESC LIMIT 1")
add("What is the median order value?", "SELECT AVG(order_total) AS median_order_value FROM (SELECT order_total, ROW_NUMBER() OVER (ORDER BY order_total) AS rn, COUNT(*) OVER () AS cnt FROM (SELECT oi.order_id, SUM(oi.price) AS order_total FROM order_items oi GROUP BY oi.order_id)) WHERE rn IN (FLOOR((cnt + 1) / 2), CEIL((cnt + 1) / 2))")
add("What is the revenue per customer?", "SELECT o.customer_id, SUM(oi.price) AS revenue_per_customer FROM orders o JOIN order_items oi ON o.order_id = oi.order_id GROUP BY o.customer_id")

# Orders
add("What is the revenue per order?", "SELECT oi.order_id, SUM(oi.price) AS revenue_per_order FROM order_items oi GROUP BY oi.order_id")
add("How many total orders are there?", "SELECT COUNT(DISTINCT order_id) AS total_orders FROM orders")
add("How many orders per month?", "SELECT strftime('%Y-%m', order_purchase_timestamp) AS month, COUNT(*) AS order_count FROM orders GROUP BY month ORDER BY month")
add("What is the average number of items per order?", "SELECT AVG(item_count) AS average_items_per_order FROM (SELECT order_id, COUNT(*) AS item_count FROM order_items GROUP BY order_id)")
add("What is the distribution of order sizes?", "SELECT item_count AS items_per_order, COUNT(*) AS order_count FROM (SELECT order_id, COUNT(*) AS item_count FROM order_items GROUP BY order_id) GROUP BY item_count ORDER BY item_count")
add("How many orders are completed vs cancelled?", "SELECT order_status, COUNT(*) AS count FROM orders GROUP BY order_status")
add("What is the cancellation rate?", "SELECT ROUND(100.0 * SUM(CASE WHEN order_status = 'canceled' THEN 1 ELSE 0 END) / COUNT(*), 2) AS cancellation_rate FROM orders")
add("How long does it take to deliver orders on average?", "SELECT AVG(JULIANDAY(order_delivered_customer_date) - JULIANDAY(order_purchase_timestamp)) AS average_delivery_time_days FROM orders WHERE order_delivered_customer_date IS NOT NULL")
add("What is the order processing time (purchase -> shipped)?", "SELECT AVG(JULIANDAY(order_delivered_carrier_date) - JULIANDAY(order_purchase_timestamp)) * 24 AS average_processing_time_hours FROM orders WHERE order_delivered_carrier_date IS NOT NULL")
add("What percentage of orders are delivered late?", "SELECT ROUND(100.0 * SUM(CASE WHEN order_delivered_customer_date > order_estimated_delivery_date THEN 1 ELSE 0 END) / COUNT(*), 2) AS percentage_late_deliveries FROM orders WHERE order_delivered_customer_date IS NOT NULL")
add("What is the trend of late deliveries over time?", "SELECT strftime('%Y-%m', order_purchase_timestamp) AS month, ROUND(100.0 * SUM(CASE WHEN order_delivered_customer_date > order_estimated_delivery_date THEN 1 ELSE 0 END) / COUNT(*), 2) AS percentage_late_deliveries FROM orders WHERE order_delivered_customer_date IS NOT NULL GROUP BY month ORDER BY month")
add("What is the busiest day for orders?", "SELECT CAST(strftime('%w', order_purchase_timestamp) AS INTEGER) AS day_of_week, COUNT(*) AS order_count FROM orders GROUP BY day_of_week ORDER BY order_count DESC LIMIT 1")
add("What is the peak hour for order placement?", "SELECT CAST(strftime('%H', order_purchase_timestamp) AS INTEGER) AS hour, COUNT(*) AS order_count FROM orders GROUP BY hour ORDER BY order_count DESC LIMIT 1")
add("What is the average time between orders for a customer?", "WITH customer_orders AS (SELECT customer_id, order_purchase_timestamp, LAG(order_purchase_timestamp) OVER (PARTITION BY customer_id ORDER BY order_purchase_timestamp) AS prev_ts FROM orders) SELECT AVG(JULIANDAY(order_purchase_timestamp) - JULIANDAY(prev_ts)) AS average_time_between_orders_days FROM customer_orders WHERE prev_ts IS NOT NULL")
add("What is the repeat order rate?", "SELECT ROUND(100.0 * COUNT(CASE WHEN order_count > 1 THEN 1 END) / COUNT(*), 2) AS repeat_order_rate FROM (SELECT customer_id, COUNT(*) AS order_count FROM orders GROUP BY customer_id)")
add("How many orders contain multiple sellers?", "SELECT COUNT(*) AS multiple_seller_order_count FROM (SELECT order_id FROM order_items GROUP BY order_id HAVING COUNT(DISTINCT seller_id) > 1)")

# Customers
add("How many unique customers are there?", "SELECT COUNT(DISTINCT customer_unique_id) AS unique_customer_count FROM customers")
add("How many new customers per month?", "WITH first_orders AS (SELECT customer_id, MIN(strftime('%Y-%m', order_purchase_timestamp)) AS first_month FROM orders GROUP BY customer_id) SELECT first_month AS month, COUNT(*) AS new_customer_count FROM first_orders GROUP BY month ORDER BY month")
add("What is the customer retention rate?", "WITH monthly_customers AS (SELECT DISTINCT strftime('%Y-%m', o.order_purchase_timestamp) AS month, o.customer_id FROM orders o), retention AS (SELECT c1.month, c1.customer_id, COUNT(DISTINCT c2.month) AS subsequent_months FROM monthly_customers c1 LEFT JOIN monthly_customers c2 ON c1.customer_id = c2.customer_id AND c2.month > c1.month GROUP BY c1.month, c1.customer_id) SELECT month, ROUND(100.0 * SUM(CASE WHEN subsequent_months > 0 THEN 1 ELSE 0 END) / COUNT(*), 2) AS retention_rate FROM retention GROUP BY month ORDER BY month")
add("What is the churn rate?", "WITH customer_months AS (SELECT DISTINCT customer_id, strftime('%Y-%m', order_purchase_timestamp) AS month FROM orders), months AS (SELECT DISTINCT month FROM customer_months), churn AS (SELECT c.customer_id, m.month, MAX(c2.month) AS last_month FROM customer_months c CROSS JOIN months m LEFT JOIN customer_months c2 ON c.customer_id = c2.customer_id AND c2.month <= m.month GROUP BY c.customer_id, m.month HAVING m.month > last_month) SELECT month, COUNT(DISTINCT customer_id) AS churn_count FROM churn GROUP BY month ORDER BY month")
add("What is the average number of orders per customer?", "SELECT AVG(order_count) AS average_orders_per_customer FROM (SELECT customer_id, COUNT(*) AS order_count FROM orders GROUP BY customer_id)")
add("What percentage of customers are repeat buyers?", "SELECT ROUND(100.0 * COUNT(CASE WHEN order_count > 1 THEN 1 END) / COUNT(*), 2) AS percentage_repeat_buyers FROM (SELECT customer_id, COUNT(*) AS order_count FROM orders GROUP BY customer_id)")
add("Which regions have the most customers?", "SELECT customer_state, COUNT(DISTINCT customer_unique_id) AS customer_count FROM customers GROUP BY customer_state ORDER BY customer_count DESC")
add("What is the distribution of customers by state?", "SELECT customer_state, COUNT(DISTINCT customer_unique_id) AS customer_count FROM customers GROUP BY customer_state ORDER BY customer_count DESC")
add("What is the average revenue per customer (ARPU)?", "SELECT AVG(customer_spend) AS average_revenue_per_customer FROM (SELECT o.customer_id, SUM(oi.price) AS customer_spend FROM orders o JOIN order_items oi ON o.order_id = oi.order_id GROUP BY o.customer_id)")
add("Who are the top 10 customers by revenue?", "SELECT o.customer_id AS customer_unique_id, SUM(oi.price) AS total_spend FROM orders o JOIN order_items oi ON o.order_id = oi.order_id GROUP BY o.customer_id ORDER BY total_spend DESC LIMIT 10")
add("What is the lifetime value (LTV) of customers?", "SELECT o.customer_id, SUM(oi.price) AS customer_lifetime_value FROM orders o JOIN order_items oi ON o.order_id = oi.order_id GROUP BY o.customer_id")
add("How long do customers stay active?", "SELECT AVG(JULIANDAY(max_ts) - JULIANDAY(min_ts)) AS active_days_duration FROM (SELECT customer_id, MIN(order_purchase_timestamp) AS min_ts, MAX(order_purchase_timestamp) AS max_ts FROM orders GROUP BY customer_id)")
add("What is the average time between first and last purchase?", "SELECT AVG(JULIANDAY(max_ts) - JULIANDAY(min_ts)) AS average_days_between_first_last FROM (SELECT customer_id, MIN(order_purchase_timestamp) AS min_ts, MAX(order_purchase_timestamp) AS max_ts FROM orders GROUP BY customer_id)")
add("What percentage of customers make only one purchase?", "SELECT ROUND(100.0 * SUM(CASE WHEN order_count = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) AS percentage_single_purchase FROM (SELECT customer_id, COUNT(*) AS order_count FROM orders GROUP BY customer_id)")
add("What is the geographic distribution of high-value customers?", "WITH customer_spend AS (SELECT o.customer_id, c.customer_state, SUM(oi.price) AS total_spend FROM orders o JOIN order_items oi ON o.order_id = oi.order_id JOIN customers c ON o.customer_id = c.customer_id GROUP BY o.customer_id, c.customer_state), high_value AS (SELECT *, NTILE(4) OVER (ORDER BY total_spend DESC) AS quartile FROM customer_spend) SELECT customer_state, COUNT(*) AS high_value_customer_count FROM high_value WHERE quartile = 1 GROUP BY customer_state ORDER BY high_value_customer_count DESC")

# Products
add("Which product categories generate the most revenue?", "SELECT p.product_category_name, SUM(oi.price) AS total_revenue FROM order_items oi JOIN products p ON oi.product_id = p.product_id GROUP BY p.product_category_name ORDER BY total_revenue DESC LIMIT 10")
add("Which product categories have the most orders?", "SELECT p.product_category_name, COUNT(DISTINCT oi.order_id) AS order_count FROM order_items oi JOIN products p ON oi.product_id = p.product_id GROUP BY p.product_category_name ORDER BY order_count DESC LIMIT 10")
add("What is the average price per product category?", "SELECT p.product_category_name, AVG(oi.price) AS average_price FROM order_items oi JOIN products p ON oi.product_id = p.product_id GROUP BY p.product_category_name ORDER BY average_price DESC")
add("Which products are most frequently purchased?", "SELECT product_id, COUNT(*) AS purchase_frequency FROM order_items GROUP BY product_id ORDER BY purchase_frequency DESC LIMIT 10")
add("Which products generate the most revenue?", "SELECT product_id, SUM(price) AS total_revenue FROM order_items GROUP BY product_id ORDER BY total_revenue DESC LIMIT 10")
add("What is the distribution of product prices?", "SELECT CASE WHEN price < 50 THEN '0-50' WHEN price < 100 THEN '50-100' WHEN price < 200 THEN '100-200' WHEN price < 500 THEN '200-500' ELSE '500+' END AS price_bucket, COUNT(*) AS product_count FROM order_items GROUP BY price_bucket ORDER BY price_bucket")
add("Which categories have the highest AOV?", "SELECT product_category_name, AVG(monthly_total) AS average_order_value FROM (SELECT oi.order_id, p.product_category_name AS product_category_name, SUM(oi.price) AS monthly_total FROM order_items oi JOIN products p ON oi.product_id = p.product_id GROUP BY oi.order_id, product_category_name) GROUP BY product_category_name ORDER BY average_order_value DESC LIMIT 10")
add("Which categories have declining sales trends?", "WITH monthly_category AS (SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month, p.product_category_name AS product_category_name, SUM(oi.price) AS revenue FROM orders o JOIN order_items oi ON o.order_id = oi.order_id JOIN products p ON oi.product_id = p.product_id GROUP BY month, product_category_name), trends AS (SELECT product_category_name, month, revenue, LAG(revenue) OVER (PARTITION BY product_category_name ORDER BY month) AS prev_revenue FROM monthly_category) SELECT product_category_name, ROUND(AVG(CASE WHEN prev_revenue IS NOT NULL THEN 100.0 * (revenue - prev_revenue) / prev_revenue END), 2) AS decline_rate FROM trends GROUP BY product_category_name HAVING COUNT(*) > 1 ORDER BY decline_rate ASC LIMIT 10")
add("Which categories have the fastest growth?", "WITH monthly_category AS (SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month, p.product_category_name AS product_category_name, SUM(oi.price) AS revenue FROM orders o JOIN order_items oi ON o.order_id = oi.order_id JOIN products p ON oi.product_id = p.product_id GROUP BY month, product_category_name), trends AS (SELECT product_category_name, month, revenue, LAG(revenue) OVER (PARTITION BY product_category_name ORDER BY month) AS prev_revenue FROM monthly_category) SELECT product_category_name, ROUND(AVG(CASE WHEN prev_revenue IS NOT NULL AND prev_revenue > 0 THEN 100.0 * (revenue - prev_revenue) / prev_revenue END), 2) AS growth_rate FROM trends GROUP BY product_category_name HAVING COUNT(*) > 1 ORDER BY growth_rate DESC LIMIT 10")
add("What is the average number of items sold per product?", "SELECT AVG(item_count) AS average_items_sold FROM (SELECT product_id, SUM(order_item_id) AS item_count FROM order_items GROUP BY product_id)")
add("Which products are often bought together? (basic co-occurrence)", "WITH order_products AS (SELECT DISTINCT order_id, product_id FROM order_items), pairs AS (SELECT o1.product_id AS product_a, o2.product_id AS product_b FROM order_products o1 JOIN order_products o2 ON o1.order_id = o2.order_id AND o1.product_id < o2.product_id) SELECT product_a, product_b, COUNT(*) AS co_occurrence_count FROM pairs GROUP BY product_a, product_b ORDER BY co_occurrence_count DESC LIMIT 10")
add("What is the revenue contribution of top categories?", "WITH category_revenue AS (SELECT p.product_category_name, SUM(oi.price) AS total_revenue FROM order_items oi JOIN products p ON oi.product_id = p.product_id GROUP BY p.product_category_name), total AS (SELECT SUM(total_revenue) AS grand_total FROM category_revenue) SELECT product_category_name, ROUND(100.0 * total_revenue / (SELECT grand_total FROM total), 2) AS revenue_share_percentage FROM category_revenue ORDER BY total_revenue DESC LIMIT 10")
add("Which products have the highest return/cancellation rate?", "WITH order_status AS (SELECT oi.product_id, o.order_id, o.order_status FROM order_items oi JOIN orders o ON oi.order_id = o.order_id), product_orders AS (SELECT product_id, COUNT(*) AS total_orders, SUM(CASE WHEN order_status IN ('canceled', 'delivered') THEN 1 ELSE 0 END) AS non_returned FROM order_status GROUP BY product_id) SELECT product_id, ROUND(100.0 * (1.0 - 1.0 * non_returned / total_orders), 2) AS cancellation_rate FROM product_orders WHERE total_orders > 10 ORDER BY cancellation_rate DESC LIMIT 10")
add("What is the price vs sales relationship?", "SELECT CASE WHEN price < 50 THEN '0-50' WHEN price < 100 THEN '50-100' WHEN price < 200 THEN '100-200' WHEN price < 500 THEN '200-500' ELSE '500+' END AS price_range, SUM(order_item_id) AS units_sold FROM order_items GROUP BY price_range ORDER BY price_range")
add("Which categories have seasonal demand patterns?", "WITH monthly_category AS (SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month, p.product_category_name AS product_category_name, SUM(oi.price) AS revenue FROM orders o JOIN order_items oi ON o.order_id = oi.order_id JOIN products p ON oi.product_id = p.product_id GROUP BY month, product_category_name), monthly_stats AS (SELECT product_category_name, AVG(revenue) AS avg_revenue, MAX(revenue) AS max_revenue, MIN(revenue) AS min_revenue FROM monthly_category GROUP BY product_category_name) SELECT product_category_name, ROUND(max_revenue - min_revenue, 2) AS seasonal_variance FROM monthly_stats ORDER BY seasonal_variance DESC LIMIT 10")

# Logistics
add("What is the average delivery time?", "SELECT AVG(JULIANDAY(order_delivered_customer_date) - JULIANDAY(order_purchase_timestamp)) AS average_delivery_days FROM orders WHERE order_delivered_customer_date IS NOT NULL")
add("What is the average shipping delay?", "SELECT AVG(JULIANDAY(order_delivered_customer_date) - JULIANDAY(order_estimated_delivery_date)) AS average_delay_days FROM orders WHERE order_delivered_customer_date IS NOT NULL")
add("Which states have the longest delivery times?", "SELECT c.customer_state, AVG(JULIANDAY(o.order_delivered_customer_date) - JULIANDAY(o.order_purchase_timestamp)) AS average_delivery_days FROM orders o JOIN customers c ON o.customer_id = c.customer_id WHERE o.order_delivered_customer_date IS NOT NULL GROUP BY c.customer_state ORDER BY average_delivery_days DESC LIMIT 10")
add("Which sellers deliver the fastest?", "SELECT oi.seller_id, AVG(JULIANDAY(o.order_delivered_customer_date) - JULIANDAY(o.order_purchase_timestamp)) AS average_delivery_days FROM order_items oi JOIN orders o ON oi.order_id = o.order_id WHERE o.order_delivered_customer_date IS NOT NULL GROUP BY oi.seller_id ORDER BY average_delivery_days ASC LIMIT 10")
add("What percentage of deliveries are delayed?", "SELECT ROUND(100.0 * SUM(CASE WHEN order_delivered_customer_date > order_estimated_delivery_date THEN 1 ELSE 0 END) / COUNT(*), 2) AS delay_percentage FROM orders WHERE order_delivered_customer_date IS NOT NULL")
add("What is the trend of delivery delays over time?", "SELECT strftime('%Y-%m', order_purchase_timestamp) AS month, ROUND(100.0 * SUM(CASE WHEN order_delivered_customer_date > order_estimated_delivery_date THEN 1 ELSE 0 END) / COUNT(*), 2) AS delay_percentage FROM orders WHERE order_delivered_customer_date IS NOT NULL GROUP BY month ORDER BY month")
add("How does distance affect delivery time? (approx via location)", "SELECT ABS(c.customer_zip_code_prefix - s.seller_zip_code_prefix) AS approx_distance, AVG(JULIANDAY(o.order_delivered_customer_date) - JULIANDAY(o.order_purchase_timestamp)) AS delivery_days FROM orders o JOIN order_items oi ON o.order_id = oi.order_id JOIN customers c ON o.customer_id = c.customer_id JOIN sellers s ON oi.seller_id = s.seller_id WHERE o.order_delivered_customer_date IS NOT NULL GROUP BY approx_distance ORDER BY approx_distance")
add("Which regions have the best delivery performance?", "SELECT c.customer_state, ROUND(100.0 * SUM(CASE WHEN o.order_delivered_customer_date <= o.order_estimated_delivery_date THEN 1 ELSE 0 END) / COUNT(*), 2) AS on_time_delivery_percentage FROM orders o JOIN customers c ON o.customer_id = c.customer_id WHERE o.order_delivered_customer_date IS NOT NULL GROUP BY c.customer_state ORDER BY on_time_delivery_percentage DESC LIMIT 10")
add("What is the distribution of delivery times?", "SELECT CASE WHEN delivery_days < 5 THEN '0-5' WHEN delivery_days < 10 THEN '5-10' WHEN delivery_days < 15 THEN '10-15' WHEN delivery_days < 20 THEN '15-20' ELSE '20+' END AS delivery_days_bucket, COUNT(*) AS order_count FROM (SELECT JULIANDAY(order_delivered_customer_date) - JULIANDAY(order_purchase_timestamp) AS delivery_days FROM orders WHERE order_delivered_customer_date IS NOT NULL) GROUP BY delivery_days_bucket ORDER BY delivery_days_bucket")
add("Are late deliveries increasing or decreasing?", "SELECT strftime('%Y-%m', order_purchase_timestamp) AS month, SUM(CASE WHEN order_delivered_customer_date > order_estimated_delivery_date THEN 1 ELSE 0 END) AS late_order_count FROM orders WHERE order_delivered_customer_date IS NOT NULL GROUP BY month ORDER BY month")

# Sellers
add("How many sellers are there?", "SELECT COUNT(*) AS total_sellers FROM sellers")
add("Which sellers generate the most revenue?", "SELECT seller_id, SUM(price) AS total_revenue FROM order_items GROUP BY seller_id ORDER BY total_revenue DESC LIMIT 10")
add("Which sellers have the most orders?", "SELECT seller_id, COUNT(DISTINCT order_id) AS order_count FROM order_items GROUP BY seller_id ORDER BY order_count DESC LIMIT 10")
add("What is the average revenue per seller?", "SELECT AVG(seller_revenue) AS average_revenue_per_seller FROM (SELECT seller_id, SUM(price) AS seller_revenue FROM order_items GROUP BY seller_id)")
add("Which sellers have the highest ratings?", "SELECT oi.seller_id, AVG(or2.review_score) AS average_rating FROM order_items oi JOIN order_reviews or2 ON oi.order_id = or2.order_id GROUP BY oi.seller_id ORDER BY average_rating DESC LIMIT 10")
add("Which sellers have the most delayed deliveries?", "SELECT oi.seller_id, COUNT(*) AS delay_count FROM order_items oi JOIN orders o ON oi.order_id = o.order_id WHERE o.order_delivered_customer_date > o.order_estimated_delivery_date GROUP BY oi.seller_id ORDER BY delay_count DESC LIMIT 10")
add("What is the distribution of sellers by region?", "SELECT seller_state, COUNT(*) AS seller_count FROM sellers GROUP BY seller_state ORDER BY seller_count DESC")
add("Which sellers are growing fastest?", "WITH monthly_sales AS (SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month, oi.seller_id, SUM(oi.price) AS revenue FROM order_items oi JOIN orders o ON oi.order_id = o.order_id GROUP BY month, oi.seller_id), growth AS (SELECT seller_id, month, revenue, LAG(revenue) OVER (PARTITION BY seller_id ORDER BY month) AS prev_revenue FROM monthly_sales) SELECT seller_id, ROUND(AVG(CASE WHEN prev_revenue IS NOT NULL AND prev_revenue > 0 THEN 100.0 * (revenue - prev_revenue) / prev_revenue END), 2) AS sales_growth_rate FROM growth GROUP BY seller_id ORDER BY sales_growth_rate DESC LIMIT 10")
add("What is the average delivery time per seller?", "SELECT oi.seller_id, AVG(JULIANDAY(o.order_delivered_customer_date) - JULIANDAY(o.order_purchase_timestamp)) AS average_delivery_days FROM order_items oi JOIN orders o ON oi.order_id = o.order_id WHERE o.order_delivered_customer_date IS NOT NULL GROUP BY oi.seller_id ORDER BY average_delivery_days ASC LIMIT 10")
add("Which sellers have the highest cancellation rate?", "SELECT oi.seller_id, ROUND(100.0 * SUM(CASE WHEN o.order_status = 'canceled' THEN 1 ELSE 0 END) / COUNT(*), 2) AS cancellation_rate FROM order_items oi JOIN orders o ON oi.order_id = o.order_id GROUP BY oi.seller_id ORDER BY cancellation_rate DESC LIMIT 10")

# Payments
add("Which payment method is most used?", "SELECT payment_type, COUNT(*) AS payment_count FROM order_payments GROUP BY payment_type ORDER BY payment_count DESC LIMIT 1")
add("What is the revenue by payment type?", "SELECT payment_type, SUM(payment_value) AS total_payments_value FROM order_payments GROUP BY payment_type ORDER BY total_payments_value DESC")
add("What is the average payment value?", "SELECT AVG(payment_value) AS average_payment_value FROM order_payments")
add("How many installments are used on average?", "SELECT AVG(payment_installments) AS average_installments FROM order_payments")
add("What is the distribution of installment payments?", "SELECT payment_installments, COUNT(*) AS order_count FROM order_payments GROUP BY payment_installments ORDER BY payment_installments")
add("Do installment payments affect order value?", "SELECT payment_installments, AVG(payment_value) AS average_payment_value FROM order_payments GROUP BY payment_installments ORDER BY payment_installments")
add("What is the failure rate of payments?", "SELECT ROUND(100.0 * SUM(CASE WHEN payment_value <= 0 THEN 1 ELSE 0 END) / COUNT(*), 2) AS payment_failure_rate FROM order_payments")
add("Which payment types have highest order value?", "SELECT payment_type, AVG(payment_value) AS average_payment_value FROM order_payments GROUP BY payment_type ORDER BY average_payment_value DESC LIMIT 5")
add("How does payment method vary by region?", "SELECT c.customer_state, op.payment_type, COUNT(*) AS count FROM order_payments op JOIN orders o ON op.order_id = o.order_id JOIN customers c ON o.customer_id = c.customer_id GROUP BY c.customer_state, op.payment_type ORDER BY c.customer_state, count DESC")
add("What is the trend of payment methods over time?", "SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month, op.payment_type, COUNT(*) AS count FROM order_payments op JOIN orders o ON op.order_id = o.order_id GROUP BY month, op.payment_type ORDER BY month, count DESC")

# Reviews
add("What is the average review score?", "SELECT AVG(review_score) AS average_review_score FROM order_reviews")
add("What is the distribution of review scores?", "SELECT review_score, COUNT(*) AS count FROM order_reviews GROUP BY review_score ORDER BY review_score")
add("Which products have the best reviews?", "SELECT oi.product_id, AVG(or2.review_score) AS average_review_score FROM order_items oi JOIN order_reviews or2 ON oi.order_id = or2.order_id GROUP BY oi.product_id ORDER BY average_review_score DESC LIMIT 10")
add("Which sellers have the worst reviews?", "SELECT oi.seller_id, AVG(or2.review_score) AS average_review_score FROM order_items oi JOIN order_reviews or2 ON oi.order_id = or2.order_id GROUP BY oi.seller_id ORDER BY average_review_score ASC LIMIT 10")
add("What is the relationship between delivery time and review score?", "SELECT CAST(JULIANDAY(order_delivered_customer_date) - JULIANDAY(order_purchase_timestamp) AS INTEGER) AS delivery_days, AVG(or2.review_score) AS average_review_score FROM orders o JOIN order_reviews or2 ON o.order_id = or2.order_id WHERE o.order_delivered_customer_date IS NOT NULL GROUP BY delivery_days ORDER BY delivery_days")
add("Do late deliveries lead to lower ratings?", "SELECT CASE WHEN order_delivered_customer_date > order_estimated_delivery_date THEN 1 ELSE 0 END AS is_late, AVG(or2.review_score) AS average_review_score FROM orders o JOIN order_reviews or2 ON o.order_id = or2.order_id WHERE o.order_delivered_customer_date IS NOT NULL GROUP BY is_late")
add("What percentage of orders receive reviews?", "SELECT ROUND(100.0 * COUNT(DISTINCT or2.order_id) / COUNT(*), 2) AS review_response_rate FROM orders o LEFT JOIN order_reviews or2 ON o.order_id = or2.order_id")
add("What is the trend of review scores over time?", "SELECT strftime('%Y-%m', review_creation_date) AS month, AVG(review_score) AS average_review_score FROM order_reviews GROUP BY month ORDER BY month")
add("Which categories have the highest satisfaction?", "SELECT p.product_category_name, AVG(or2.review_score) AS average_review_score FROM order_reviews or2 JOIN order_items oi ON or2.order_id = oi.order_id JOIN products p ON oi.product_id = p.product_id GROUP BY p.product_category_name ORDER BY average_review_score DESC LIMIT 10")
add("Which categories have the lowest satisfaction?", "SELECT p.product_category_name, AVG(or2.review_score) AS average_review_score FROM order_reviews or2 JOIN order_items oi ON or2.order_id = oi.order_id JOIN products p ON oi.product_id = p.product_id GROUP BY p.product_category_name ORDER BY average_review_score ASC LIMIT 10")

enhanced = []
errors = []

for i, b in enumerate(benchmarks):
    sql = QUESTION_TO_SQL.get(b['question'])
    if not sql:
        errors.append(f"Missing gold SQL for query {i}: {b['question']}")
        continue
    
    try:
        cols, rows = run_sql(sql)
        result = get_expected(sql)
        
        q_text = b['question'].lower()
        if any(k in q_text for k in ['how many', 'what percentage', 'what is the average', 'what is the median', 'what is the trend', 'distribution']):
            if 'trend' in q_text or 'over time' in q_text or 'distribution' in q_text:
                query_type = 'time_series'
            else:
                query_type = 'aggregation'
        elif any(k in q_text for k in ['which', 'who are']):
            query_type = 'ranking'
        elif any(k in q_text for k in ['what is', 'how long', 'how does']):
            query_type = 'single_value'
        else:
            query_type = 'unknown'
        
        tables_needed = len(b['expected_tables'])
        if 'co-occurrence' in q_text or 'retention' in q_text or 'churn' in q_text or 'seasonal' in q_text:
            difficulty = 'hard'
        elif tables_needed >= 3 or 'trend' in q_text or 'distribution' in q_text:
            difficulty = 'medium'
        else:
            difficulty = 'easy'
        
        domain = b['category']
        
        correctness_checks = []
        if query_type == 'aggregation':
            correctness_checks.append('numeric_tolerance')
        if query_type == 'time_series':
            correctness_checks.append('temporal_ordering')
        if query_type == 'ranking':
            correctness_checks.append('top_n_ordering')
        if 'percentage' in q_text or 'rate' in q_text:
            correctness_checks.append('percentage_range_0_100')
        if 'distribution' in q_text:
            correctness_checks.append('completeness')
        
        entry = {
            **b,
            'expected_sql': sql,
            'expected_result': {
                'columns': result['columns'],
                'values': result['values'],
                'row_count': result['row_count']
            },
            'query_type': query_type,
            'difficulty': difficulty,
            'correctness_checks': correctness_checks,
            'domain': domain
        }
        enhanced.append(entry)
        print(f"[{i+1}/100] OK: {b['question'][:60]}... -> {result['row_count']} rows")
    except Exception as e:
        errors.append(f"[{i+1}] FAILED: {b['question']} | {e}")
        print(f"[{i+1}] FAILED: {b['question']} | {e}")

with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
    json.dump(enhanced, f, indent=2, ensure_ascii=False)

print(f"\n=== SUMMARY ===")
print(f"Total queries: {len(benchmarks)}")
print(f"Successfully enhanced: {len(enhanced)}")
print(f"Errors: {len(errors)}")
if errors:
    print("\nErrors:")
    for e in errors:
        print(f"  {e}")
print(f"\nSaved to: {OUTPUT_PATH}")

conn.close()
