import json
import re
from pathlib import Path

BASELINE_RESULTS_PATH = Path(r'C:\Users\mjeni\OneDrive\Desktop\Own Projects\Data Analyst Agent\results\baseline\raw_results.json')
V2_BENCHMARK_PATH = Path(r'C:\Users\mjeni\OneDrive\Desktop\Own Projects\Data Analyst Agent\tests\evaluation\benchmark_dataset_v2.json')

baseline = json.loads(BASELINE_RESULTS_PATH.read_text(encoding='utf-8'))
v2 = json.loads(V2_BENCHMARK_PATH.read_text(encoding='utf-8'))

r = baseline[0]
v = v2[0]

gen_sql = r.get('generated_sql', '')
exp_sql = v.get('expected_sql', '')

print('Generated SQL length:', len(gen_sql))
print('Expected SQL length:', len(exp_sql))
print()

# Extract first SQL
statements = re.split(r';\s*(?=SELECT|WITH|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER)', gen_sql, flags=re.IGNORECASE)
for i, stmt in enumerate(statements):
    stmt = stmt.strip()
    if stmt and re.search(r'\bSELECT\b', stmt, re.IGNORECASE):
        print(f'First SELECT statement (length={len(stmt)}):')
        print(stmt[:300])
        print('...')
        print(stmt[-200:])
        break

print()
print('Expected SQL:')
print(exp_sql[:300])
print('...')
