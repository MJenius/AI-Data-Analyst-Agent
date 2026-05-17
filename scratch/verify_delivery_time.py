import sqlite3

def verify_delivery_time():
    db_path = "runtime/analytics.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Calculate average delivery time in days for SP and RJ
    delivery_time_query = """
    SELECT
        c.customer_state AS state,
        ROUND(AVG(julianday(o.order_delivered_customer_date) - julianday(o.order_purchase_timestamp)), 2) AS avg_delivery_time_days,
        COUNT(o.order_id) AS order_count
    FROM orders o
    JOIN customers c ON c.customer_id = o.customer_id
    WHERE o.order_status = 'delivered'
      AND o.order_delivered_customer_date IS NOT NULL
      AND c.customer_state IN ('SP', 'RJ')
    GROUP BY state;
    """
    
    print("Running Delivery Time Comparison Query...")
    cursor.execute(delivery_time_query)
    rows = cursor.fetchall()
    
    print("-" * 55)
    print(f"{'State':<10} | {'Avg Delivery Time (Days)':<25} | {'Delivered Order Count':<15}")
    print("-" * 55)
    for row in rows:
        print(f"{row[0]:<10} | {row[1]:<25} | {row[2]:<15,}")
    print("-" * 55)
    
    # Let's also do it for SP vs RJ with a bit more detail, like median or range, or see the difference
    if len(rows) == 2:
        sp_time = rows[0][1] if rows[0][0] == 'SP' else rows[1][1]
        rj_time = rows[1][1] if rows[1][0] == 'RJ' else rows[0][1]
        diff = rj_time - sp_time
        pct = (diff / sp_time) * 100
        print(f"Analysis: Rio de Janeiro (RJ) deliveries take {diff:.2f} days longer than São Paulo (SP) on average.")
        print(f"This is a {pct:.1f}% increase in delivery duration for RJ.")
        print("-" * 55)
        
    conn.close()

if __name__ == "__main__":
    verify_delivery_time()
