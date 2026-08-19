import json
import re
from pathlib import Path

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

total_acc = 0
for i in range(len(v2_results)):
    expected = set(v2[i].get('expected_tables', []))
    queried = set(v2_results[i].get('queried_tables', []))
    correct = expected & queried
    acc = len(correct) / len(expected) * 100 if expected else 100
    total_acc += acc

print(f'V2 table accuracy from raw_results: {total_acc / len(v2_results):.2f}%')

# Show some examples
for i in [0, 13, 29, 30, 31, 37]:
    expected = set(v2[i]['expected_tables'])
    queried = set(v2_results[i]['queried_tables'])
    correct = expected & queried
    acc = len(correct) / len(expected) * 100 if expected else 100
    print(f'  {i}: expected={sorted(expected)} queried={sorted(queried)} acc={acc:.0f}%')
