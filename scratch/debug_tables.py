import json
from pathlib import Path

baseline = json.loads(Path(r'C:\Users\mjeni\OneDrive\Desktop\Own Projects\Data Analyst Agent\results\baseline\raw_results.json').read_text(encoding='utf-8'))
orig = json.loads(Path(r'C:\Users\mjeni\OneDrive\Desktop\Own Projects\Data Analyst Agent\tests\evaluation\benchmark_dataset.json').read_text(encoding='utf-8'))

# Recompute table accuracy using baseline's own extraction
import re
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

total_acc = 0
for i in range(len(baseline)):
    expected = set(orig[i].get('expected_tables', []))
    queried = set(extract_tables(baseline[i].get('generated_sql')))
    correct = expected & queried
    acc = len(correct) / len(expected) * 100 if expected else 100
    total_acc += acc

print(f'Baseline table accuracy (recomputed): {total_acc / len(baseline):.2f}%')

# Now check v2
v2 = json.loads(Path(r'C:\Users\mjeni\OneDrive\Desktop\Own Projects\Data Analyst Agent\tests\evaluation\benchmark_dataset_v2.json').read_text(encoding='utf-8'))
v2_results = json.loads(Path(r'C:\Users\mjeni\OneDrive\Desktop\Own Projects\Data Analyst Agent\results\v2_benchmark\raw_results.json').read_text(encoding='utf-8'))

v2_acc = 0
for i in range(len(v2_results)):
    expected = set(v2[i].get('expected_tables', []))
    queried = set(v2_results[i].get('queried_tables', []))
    correct = expected & queried
    acc = len(correct) / len(expected) * 100 if expected else 100
    v2_acc += acc

print(f'V2 table accuracy: {v2_acc / len(v2_results):.2f}%')
