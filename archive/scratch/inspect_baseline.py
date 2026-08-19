import json
from pathlib import Path

p = Path(r'C:\Users\mjeni\OneDrive\Desktop\Own Projects\Data Analyst Agent\results\baseline\raw_results.json')
data = json.loads(p.read_text(encoding='utf-8'))
for i, r in enumerate(data[:5]):
    sql = r.get('generated_sql', '')
    print(f'{i+1}: {repr(sql[:300])}')
    print(f'   success={r.get("success")}, error={r.get("sql_error")}')
    print()
