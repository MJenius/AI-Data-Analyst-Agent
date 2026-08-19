import json
from pathlib import Path

V2_BENCHMARK_PATH = Path(__file__).resolve().parents[1] / 'tests' / 'evaluation' / 'benchmark_dataset_v2.json'
AUDIT_REPORT_PATH = Path(__file__).resolve().parents[1] / 'tests' / 'evaluation' / 'benchmark_audit_report.json'

with open(V2_BENCHMARK_PATH, 'r', encoding='utf-8') as f:
    v2 = json.load(f)

with open(AUDIT_REPORT_PATH, 'r', encoding='utf-8') as f:
    audit = json.load(f)

# Build fix plan
fixes = []
for issue_group in audit['issues']:
    idx = issue_group['index']
    q = issue_group['question']
    for iss in issue_group['issues']:
        fixes.append({
            'index': idx,
            'question': q[:60],
            'type': iss['type'],
            'severity': iss['severity'],
            'detail': iss['detail']
        })

print(f"Total fixes needed: {len(fixes)}")
print("\nBreakdown by type:")
from collections import Counter
c = Counter(f['type'] for f in fixes)
for k, v in c.items():
    print(f"  {k}: {v}")

print("\nBreakdown by severity:")
c = Counter(f['severity'] for f in fixes)
for k, v in c.items():
    print(f"  {k}: {v}")

# Specific fixes needed:
# 1. query_type fixes for single_value → time_series/aggregation/ranking
# 2. query_type fixes for ranking → single_value  
# 3. expected_tables fixes to match gold SQL

query_type_fixes = {
    2: 'time_series',      # monthly revenue trend
    3: 'single_value',     # highest revenue month
    4: 'single_value',     # lowest revenue month
    10: 'time_series',     # revenue growth rate
    11: 'time_series',     # cumulative revenue
    12: 'single_value',    # payment type most revenue
    14: 'aggregation',     # revenue per customer
    15: 'aggregation',     # revenue per order
    33: 'time_series',     # retention rate
    34: 'time_series',     # churn rate
    41: 'aggregation',     # LTV
    57: 'ranking',         # revenue contribution
    59: 'aggregation',     # price vs sales
    67: 'aggregation',     # distance vs delivery
    82: 'aggregation',     # revenue by payment type
    89: 'aggregation',     # payment by region
    95: 'aggregation',     # delivery time vs review
}

# expected_tables fixes - match what gold SQL actually uses
expected_tables_fixes = {
    7: ['orders', 'order_items'],  # top 10% customers - uses orders + order_items, not customers
    14: ['orders', 'order_items'],  # revenue per customer - doesn't need customers table
    15: ['order_items'],           # revenue per order - only needs order_items
    28: ['orders'],                # avg time between orders - only needs orders
    29: ['orders'],                # repeat order rate - only needs orders
    32: ['orders'],                # new customers per month - only needs orders
    34: ['orders'],                # churn rate - only needs orders
    35: ['orders'],                # avg orders per customer - only needs orders
    36: ['orders'],                # repeat buyers - only needs orders
    39: ['orders', 'order_items'], # ARPU - doesn't need customers table
    40: ['orders', 'order_items'], # top 10 customers - doesn't need customers table
    41: ['orders', 'order_items'], # LTV - doesn't need customers table
    42: ['orders'],                # active days - only needs orders
    43: ['orders'],                # avg time between first/last - only needs orders
    44: ['orders'],                # single purchase - only needs orders
    49: ['order_items'],           # most frequently purchased - only needs order_items
    64: ['order_items', 'orders'], # fastest sellers - doesn't need sellers table
    74: ['order_items'],           # avg revenue per seller - only needs order_items
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

# Save fixed benchmark
with open(V2_BENCHMARK_PATH, 'w', encoding='utf-8') as f:
    json.dump(v2, f, indent=2, ensure_ascii=False)

print(f"Saved fixed benchmark to: {V2_BENCHMARK_PATH}")
