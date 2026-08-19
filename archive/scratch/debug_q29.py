import json
from pathlib import Path

orig = json.loads(Path(r'C:\Users\mjeni\OneDrive\Desktop\Own Projects\Data Analyst Agent\tests\evaluation\benchmark_dataset.json').read_text(encoding='utf-8'))
v2 = json.loads(Path(r'C:\Users\mjeni\OneDrive\Desktop\Own Projects\Data Analyst Agent\tests\evaluation\benchmark_dataset_v2.json').read_text(encoding='utf-8'))

print('Query 29 original:', orig[29]['question'])
print('Query 29 v2:', v2[29]['question'])
print('Query 29 original expected_tables:', orig[29]['expected_tables'])
print('Query 29 v2 expected_tables:', v2[29]['expected_tables'])
print()
print('Query 30 original:', orig[30]['question'])
print('Query 30 v2:', v2[30]['question'])
print('Query 30 original expected_tables:', orig[30]['expected_tables'])
print('Query 30 v2 expected_tables:', v2[30]['expected_tables'])
