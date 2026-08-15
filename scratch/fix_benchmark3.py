import json
from pathlib import Path

V2_BENCHMARK_PATH = Path(__file__).resolve().parents[1] / 'tests' / 'evaluation' / 'benchmark_dataset_v2.json'

with open(V2_BENCHMARK_PATH, 'r', encoding='utf-8') as f:
    v2 = json.load(f)

# Remaining issues from audit:
# [16] total orders - expected_tables should be ['orders']
# [30] multiple sellers - expected_tables should be ['order_items']
# [33] retention rate - extra_tables is false positive (CTE named monthly_customers)
# [35] avg orders per customer - query_type should be 'aggregation'
# [37] regions most customers - expected_tables should be ['customers']
# [45] geo distribution high-value - extra_tables is false positive
# [56] products bought together - extra_tables is false positive (products used in subquery)
# [65] percentage delayed - expected_tables should be ['orders']
# [75] sellers highest ratings - extra_tables is false positive (order_reviews is legit)
# [81] payment method most used - query_type should be 'single_value'

query_type_fixes = {
    34: 'aggregation',     # avg number of orders per customer (index 34)
    80: 'single_value',    # payment method most used (index 80)
}

expected_tables_fixes = {
    15: ['orders'],                # total orders
    29: ['order_items'],           # multiple sellers
    36: ['customers'],             # regions most customers
    64: ['orders'],                # percentage delayed
}

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
