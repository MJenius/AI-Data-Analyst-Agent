import sqlite3

DB_PATH = r'C:\Users\mjeni\OneDrive\Desktop\Own Projects\Data Analyst Agent\runtime\analytics.db'
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cursor.fetchall()]
print("Tables:", tables)

for table in tables:
    cursor.execute(f"PRAGMA table_info({table})")
    cols = cursor.fetchall()
    print(f"\n{table}:")
    for col in cols:
        print(f"  {col[1]} ({col[2]})")
    cursor.execute(f"SELECT COUNT(*) FROM {table}")
    print(f"  rows: {cursor.fetchone()[0]}")

conn.close()
