import json
from pathlib import Path

orig = json.loads(Path(r'C:\Users\mjeni\OneDrive\Desktop\Own Projects\Data Analyst Agent\tests\evaluation\benchmark_dataset.json').read_text(encoding='utf-8'))
v2 = json.loads(Path(r'C:\Users\mjeni\OneDrive\Desktop\Own Projects\Data Analyst Agent\tests\evaluation\benchmark_dataset_v2.json').read_text(encoding='utf-8'))

print('Comparing expected_tables between v1 and v2:')
diffs = 0
for i in range(len(orig)):
    o = set(orig[i].get('expected_tables', []))
    v = set(v2[i].get('expected_tables', []))
    if o != v:
        diffs += 1
        print(f'  {i}: {orig[i]["question"][:60]}')
        print(f'      v1: {sorted(o)}')
        print(f'      v2: {sorted(v)}')

print(f'\nTotal differences: {diffs}')
