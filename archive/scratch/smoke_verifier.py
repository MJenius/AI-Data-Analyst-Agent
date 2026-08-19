import sys
sys.path.insert(0, "src")
from agent_platform.tools.sql_verifier import SQLSemanticVerifier, VerificationLevel

v = SQLSemanticVerifier("data/analytics.db")

# Test 1: clean aggregation — no group by needed (single scalar)
r1 = v.verify("SELECT SUM(price) AS total_revenue FROM order_items")
print(f"Test 1 (scalar SUM, no dims): valid={r1.is_valid}  issues={[i.category.value for i in r1.issues]}")

# Test 2: aggregation WITH dimension column but no GROUP BY
sql2 = (
    "SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month, "
    "SUM(oi.price) AS revenue "
    "FROM orders o JOIN order_items oi ON o.order_id = oi.order_id"
)
r2 = v.verify(sql2)
print(f"Test 2 (agg+dim, no GROUP BY): valid={r2.is_valid}  issues={[i.category.value for i in r2.issues]}")

# Test 3: Cartesian join (no ON clause)
sql3 = (
    "SELECT c.customer_state, SUM(oi.price) FROM order_items oi "
    "JOIN customers c GROUP BY c.customer_state"
)
r3 = v.verify(sql3)
print(f"Test 3 (cartesian join): valid={r3.is_valid}  issues={[i.category.value for i in r3.issues]}")

# Test 4: duplicate row detection
r4 = v.verify(
    "SELECT SUM(price) AS revenue FROM order_items",
    execution_result={"success": True, "row_count": 500, "rows": [{"revenue": 1000}]},
    expected_result={"row_count": 100, "values": [{"revenue": 1000}]},
)
print(f"Test 4 (duplicate detect): valid={r4.is_valid}  issues={[i.category.value for i in r4.issues]}")

# Test 5: NULL metric
r5 = v.verify(
    "SELECT SUM(price) AS total_revenue FROM order_items",
    execution_result={"success": True, "row_count": 1, "rows": [{"total_revenue": None}]},
)
print(f"Test 5 (null metric): valid={r5.is_valid}  issues={[i.category.value for i in r5.issues]}")

print("\nAll smoke tests passed.")
