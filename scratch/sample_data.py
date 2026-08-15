import sqlite3
import pandas as pd

DB_PATH = r'C:\Users\mjeni\OneDrive\Desktop\Own Projects\Data Analyst Agent\runtime\analytics.db'
conn = sqlite3.connect(DB_PATH)

# Quick look at key tables
for table in ['orders', 'order_items', 'order_payments', 'order_reviews', 'products', 'customers', 'sellers']:
    df = pd.read_sql(f"SELECT * FROM {table} LIMIT 3", conn)
    print(f"\n=== {table} ===")
    print(df.to_string())
    print(f"Shape: {df.shape}")

conn.close()
