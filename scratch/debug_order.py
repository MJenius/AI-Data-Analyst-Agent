import json
from pathlib import Path

BASELINE_RESULTS_PATH = Path(r'C:\Users\mjeni\OneDrive\Desktop\Own Projects\Data Analyst Agent\results\baseline\raw_results.json')
V2_BENCHMARK_PATH = Path(r'C:\Users\mjeni\OneDrive\Desktop\Own Projects\Data Analyst Agent\tests\evaluation\benchmark_dataset_v2.json')
ORIG_BENCHMARK_PATH = Path(r'C:\Users\mjeni\OneDrive\Desktop\Own Projects\Data Analyst Agent\tests\evaluation\benchmark_dataset.json')

baseline = json.loads(BASELINE_RESULTS_PATH.read_text(encoding='utf-8'))
v2 = json.loads(V2_BENCHMARK_PATH.read_text(encoding='utf-8'))
orig = json.loads(ORIG_BENCHMARK_PATH.read_text(encoding='utf-8'))

print('Baseline questions:')
for i, r in enumerate(baseline[:5]):
    print(f'  {i}: {r["question"][:80]}')

print()
print('Original benchmark questions:')
for i, b in enumerate(orig[:5]):
    print(f'  {i}: {b["question"][:80]}')

print()
print('V2 benchmark questions:')
for i, b in enumerate(v2[:5]):
    print(f'  {i}: {b["question"][:80]}')

print()
print('Are baseline questions same as original?')
for i in range(min(10, len(baseline))):
    match = baseline[i]['question'] == orig[i]['question']
    print(f'  {i}: {match}')
