import sqlite3
import json

def verify_revenues():
    db_path = "runtime/analytics.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    query = """
    SELECT
        p.product_category_name,
        ROUND(SUM(oi.price), 2) AS revenue
    FROM order_items oi
    JOIN orders o ON o.order_id = oi.order_id
    JOIN products p ON p.product_id = oi.product_id
    WHERE o.order_status IN ('delivered', 'shipped', 'invoiced')
    GROUP BY p.product_category_name
    ORDER BY revenue DESC
    LIMIT 10
    """
    
    print("Running Verification Query...")
    cursor.execute(query)
    rows = cursor.fetchall()
    
    print("\nTop Product Categories by Revenue:")
    print("-" * 50)
    print(f"{'Category Name':<30} | {'Revenue':<15}")
    print("-" * 50)
    for row in rows:
        print(f"{str(row[0]):<30} | {row[1]:<15,}")
    print("-" * 50)
    
    # Let's count order statuses as well
    status_query = "SELECT order_status, COUNT(*) FROM orders GROUP BY order_status"
    cursor.execute(status_query)
    status_rows = cursor.fetchall()
    print("\nOrder Status Distribution:")
    print("-" * 35)
    print(f"{'Status':<20} | {'Count':<10}")
    print("-" * 35)
    for row in status_rows:
        print(f"{row[0]:<20} | {row[1]:<10,}")
    print("-" * 35)
    
    conn.close()

if __name__ == "__main__":
    verify_revenues()
