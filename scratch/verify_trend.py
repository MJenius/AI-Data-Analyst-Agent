import sqlite3

def verify_monthly_trend():
    db_path = "runtime/analytics.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    query = """
    SELECT 
        strftime('%Y-%m', order_purchase_timestamp) AS month, 
        COUNT(order_id) AS order_count 
    FROM orders 
    WHERE strftime('%Y', order_purchase_timestamp) = '2017' 
    GROUP BY month 
    ORDER BY month;
    """
    
    print("Running Monthly Trend Query for 2017...")
    cursor.execute(query)
    rows = cursor.fetchall()
    
    print("\nMonthly Order Volume in 2017:")
    print("-" * 35)
    print(f"{'Month':<15} | {'Order Count':<15}")
    print("-" * 35)
    total_orders = 0
    for row in rows:
        print(f"{row[0]:<15} | {row[1]:<15,}")
        total_orders += row[1]
    print("-" * 35)
    print(f"{'Total 2017':<15} | {total_orders:<15,}")
    print("-" * 35)
    
    conn.close()

if __name__ == "__main__":
    verify_monthly_trend()
