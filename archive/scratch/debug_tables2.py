import json
import re
from pathlib import Path

baseline = json.loads(Path(r'C:\Users\mjeni\OneDrive\Desktop\Own Projects\Data Analyst Agent\results\baseline\raw_results.json').read_text(encoding='utf-8'))
v2_results = json.loads(Path(r'C:\Users\mjeni\OneDrive\Desktop\Own Projects\Data Analyst Agent\results\v2_benchmark\raw_results.json').read_text(encoding='utf-8'))
v2 = json.loads(Path(r'C:\Users\mjeni\OneDrive\Desktop\Own Projects\Data Analyst Agent\tests\evaluation\benchmark_dataset_v2.json').read_text(encoding='utf-8'))

KNOWN_TABLES = {
    "customers", "geolocation", "order_items", "order_payments",
    "order_reviews", "orders", "products", "sellers",
    "product_category_name_translation",
}

def extract_tables(sql):
    if not sql:
        return []
    cleaned = re.sub(r'\s+', ' ', sql.lower())
    return [t for t in KNOWN_TABLES if re.search(rf'\b{t}\b', cleaned)]

print('Query 0:')
print(f'  expected: {sorted(v2[0]["expected_tables"])}')
print(f'  baseline queried: {sorted(extract_tables(baseline[0]["generated_sql"]))}')
print(f'  v2 queried: {sorted(v2_results[0]["queried_tables"])}')

print()
print('Query 13 (revenue per customer):')
print(f'  expected: {sorted(v2[13]["expected_tables"])}')
print(f'  baseline queried: {sorted(extract_tables(baseline[13]["generated_sql"]))}')
print(f'  v2 queried: {sorted(v2_results[13]["queried_tables"])}')

print()
print('Query 29 (unique customers):')
print(f'  expected: {sorted(v2[29]["expected_tables"])}')
print(f'  baseline queried: {sorted(extract_tables(baseline[29]["generated_sql"]))}')
print(f'  v2 queried: {sorted(v2_results[29]["queried_tables"])}')

print()
# Count mismatches
mismatches = 0
for i in range(len(v2_results)):
    expected = set(v2[i]['expected_tables'])
    v2_queried = set(v2_results[i]['queried_tables'])
    base_queried = set(extract_tables(baseline[i]['generated_sql']))
    if v2_queried != base_queried:
        mismatches += 1
        if mismatches <= 5:
            print(f'Mismatch at {i}: v2={sorted(v2_queried)} base={sorted(base_queried)}')

print(f'\nTotal mismatches between v2 and baseline extraction: {mismatches}')
