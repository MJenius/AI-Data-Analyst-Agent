import json
from pathlib import Path

p = Path(r'C:\Users\mjeni\OneDrive\Desktop\Own Projects\Data Analyst Agent\tests\evaluation\benchmark_dataset.json')
data = json.loads(p.read_text(encoding='utf-8'))
print('Count:', len(data))
for i, d in enumerate(data):
    print(f'{i}: {d["question"][:80]}')
