import sqlite3

def verify_states():
    db_path = "runtime/analytics.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 1. Verify Revenue by State (Query used by the agent)
    revenue_query = """
    SELECT
        c.customer_state AS state,
        ROUND(SUM(oi.price), 2) AS revenue
    FROM order_items oi
    JOIN orders o ON o.order_id = oi.order_id
    JOIN customers c ON c.customer_id = o.customer_id
    WHERE o.order_status IN ('delivered', 'shipped', 'invoiced')
    GROUP BY state
    ORDER BY revenue DESC
    LIMIT 10
    """
    
    print("1. Running Agent's Revenue by State Query...")
    cursor.execute(revenue_query)
    revenue_rows = cursor.fetchall()
    
    print("-" * 45)
    print(f"{'State':<10} | {'Revenue ($)':<20} | {'Percentage (%)':<10}")
    print("-" * 45)
    total_rev = sum(row[1] for row in revenue_rows)
    # Let's get total overall revenue of all states first to compute accurate percentages
    cursor.execute("""
    SELECT ROUND(SUM(oi.price), 2) 
    FROM order_items oi 
    JOIN orders o ON o.order_id = oi.order_id 
    WHERE o.order_status IN ('delivered', 'shipped', 'invoiced')
    """)
    overall_total_rev = cursor.fetchone()[0]
    
    for row in revenue_rows:
        pct = (row[1] / overall_total_rev) * 100
        print(f"{row[0]:<10} | {row[1]:<20,} | {pct:<10.2f}%")
    print("-" * 45)
    print(f"Overall Total Revenue: {overall_total_rev:,.2f}")
    
    # 2. Query actual Order Count by State (The actual answer to the question)
    order_count_query = """
    SELECT 
        c.customer_state AS state, 
        COUNT(o.order_id) AS order_count
    FROM orders o
    JOIN customers c ON c.customer_id = o.customer_id
    GROUP BY state
    ORDER BY order_count DESC
    LIMIT 10;
    """
    
    print("\n2. Running Correct Order Count by State Query...")
    cursor.execute(order_count_query)
    order_rows = cursor.fetchall()
    
    # Get total overall order count
    cursor.execute("SELECT COUNT(*) FROM orders")
    overall_orders = cursor.fetchone()[0]
    
    print("-" * 45)
    print(f"{'State':<10} | {'Order Count':<20} | {'Percentage (%)':<10}")
    print("-" * 45)
    for row in order_rows:
        pct = (row[1] / overall_orders) * 100
        print(f"{row[0]:<10} | {row[1]:<20,} | {pct:<10.2f}%")
    print("-" * 45)
    print(f"Overall Total Orders: {overall_orders:,}")
    print("-" * 45)
    
    conn.close()

if __name__ == "__main__":
    verify_states()
