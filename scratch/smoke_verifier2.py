"""Debug: inspect what sqlglot gives us for the aggregation grain case."""
import sys
sys.path.insert(0, "src")
import sqlglot
from sqlglot import exp

sql = (
    "SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month, "
    "SUM(oi.price) AS revenue "
    "FROM orders o JOIN order_items oi ON o.order_id = oi.order_id"
)

tree = sqlglot.parse_one(sql, read="sqlite")
print("tree type:", type(tree).__name__)

# Find Select nodes
for select in tree.find_all(exp.Select):
    print("\n--- SELECT node ---")
    print("  expressions:", select.expressions)
    has_gb = bool(select.find(exp.Group))
    print("  has GROUP BY:", has_gb)
    # check for aggregates
    for expr in select.expressions:
        inner = expr.this if isinstance(expr, exp.Alias) else expr
        print(f"  expr: {type(expr).__name__} | inner: {type(inner).__name__} | is_agg:", bool(inner.find(exp.Sum, exp.Avg, exp.Count, exp.Max, exp.Min)))

# Check top-level Group
print("\ntop-level Group:", tree.find(exp.Group))
