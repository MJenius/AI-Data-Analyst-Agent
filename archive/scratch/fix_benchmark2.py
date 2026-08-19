import json
from pathlib import Path

V2_BENCHMARK_PATH = Path(__file__).resolve().parents[1] / 'tests' / 'evaluation' / 'benchmark_dataset_v2.json'

with open(V2_BENCHMARK_PATH, 'r', encoding='utf-8') as f:
    v2 = json.load(f)

# The audit report showed issues at 1-based positions [2], [3], [4], etc.
# These correspond to 0-based indices 1, 2, 3, etc.
# Let me fix based on the actual issues found, not a guessed index mapping.

# From audit output (1-based -> 0-based):
# [2] monthly revenue trend -> index 1: single_value -> time_series
# [3] highest revenue month -> index 2: ranking -> single_value  
# [4] lowest revenue month -> index 3: ranking -> single_value
# [10] revenue growth rate -> index 9: single_value -> time_series
# [11] cumulative revenue -> index 10: single_value -> time_series
# [12] payment type most revenue -> index 11: ranking -> single_value
# [14] revenue per customer -> index 13: single_value -> aggregation
# [15] revenue per order -> index 14: single_value -> aggregation
# [33] retention rate -> index 32: single_value -> time_series
# [34] churn rate -> index 33: aggregation -> time_series
# [41] LTV -> index 40: single_value -> aggregation
# [57] revenue contribution -> index 56: single_value -> ranking
# [59] price vs sales -> index 58: single_value -> aggregation
# [67] distance vs delivery -> index 66: single_value -> aggregation
# [82] revenue by payment type -> index 81: single_value -> aggregation
# [89] payment by region -> index 88: time_series -> aggregation
# [95] delivery vs review -> index 94: single_value -> aggregation
# [96] (unknown) -> index 95: unknown -> aggregation

query_type_fixes = {
    1: 'time_series',      # monthly revenue trend
    2: 'single_value',     # highest revenue month
    3: 'single_value',     # lowest revenue month
    9: 'time_series',      # revenue growth rate
    10: 'time_series',     # cumulative revenue
    11: 'single_value',    # payment type most revenue
    13: 'aggregation',     # revenue per customer
    14: 'aggregation',     # revenue per order
    32: 'time_series',     # retention rate
    33: 'time_series',     # churn rate
    40: 'aggregation',     # LTV
    56: 'ranking',         # revenue contribution
    58: 'aggregation',     # price vs sales
    66: 'aggregation',     # distance vs delivery
    81: 'aggregation',     # revenue by payment type
    88: 'aggregation',     # payment by region
    94: 'aggregation',     # delivery vs review
    95: 'aggregation',     # (unknown query at index 95)
}

expected_tables_fixes = {
    6: ['orders', 'order_items'],  # top 10% customers
    13: ['orders', 'order_items'],  # revenue per customer
    14: ['order_items'],           # revenue per order
    15: ['orders'],                # avg time between orders
    27: ['orders'],                # repeat order rate
    31: ['orders'],                # new customers per month
    33: ['orders'],                # retention rate
    34: ['orders'],                # churn rate
    34: ['orders'],                # churn rate (also missing)
    35: ['orders'],                # avg orders per customer
    36: ['orders'],                # repeat buyers
    38: ['orders', 'order_items'], # ARPU
    39: ['orders', 'order_items'], # top 10 customers
    40: ['orders', 'order_items'], # LTV
    41: ['orders'],                # active days
    42: ['orders'],                # avg time between first/last
    43: ['orders'],                # single purchase
    48: ['order_items'],           # most frequently purchased
    63: ['order_items', 'orders'], # fastest sellers
    73: ['order_items'],           # avg revenue per seller
    15: ['orders', 'order_items'], # total orders - also needs orders for COUNT(DISTINCT order_id)
}

# Apply fixes
fixed_count = 0
for idx, new_type in query_type_fixes.items():
    if v2[idx]['query_type'] != new_type:
        old = v2[idx]['query_type']
        v2[idx]['query_type'] = new_type
        fixed_count += 1
        print(f"Fixed query_type [{idx+1}]: {old} -> {new_type}")

for idx, new_tables in expected_tables_fixes.items():
    if set(v2[idx]['expected_tables']) != set(new_tables):
        old = v2[idx]['expected_tables']
        v2[idx]['expected_tables'] = new_tables
        fixed_count += 1
        print(f"Fixed expected_tables [{idx+1}]: {old} -> {new_tables}")

print(f"\nTotal fixes applied: {fixed_count}")

with open(V2_BENCHMARK_PATH, 'w', encoding='utf-8') as f:
    json.dump(v2, f, indent=2, ensure_ascii=False)

print(f"Saved fixed benchmark to: {V2_BENCHMARK_PATH}")
