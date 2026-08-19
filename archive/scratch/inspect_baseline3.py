import json
from pathlib import Path

p = Path(r'C:\Users\mjeni\OneDrive\Desktop\Own Projects\Data Analyst Agent\results\baseline\raw_results.json')
data = json.loads(p.read_text(encoding='utf-8'))
r = data[0]
sql = r.get('generated_sql', '')
print('SQL for query 1:')
print(sql)
print()
print('---')
print('Split by semicolon:')
parts = [s.strip() for s in sql.split(';') if s.strip()]
for i, part in enumerate(parts):
    print(f'Part {i+1}: {repr(part[:100])}')
