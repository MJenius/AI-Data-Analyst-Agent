import json
from pathlib import Path

p = Path(r'C:\Users\mjeni\OneDrive\Desktop\Own Projects\Data Analyst Agent\results\baseline\raw_results.json')
data = json.loads(p.read_text(encoding='utf-8'))
for i, r in enumerate(data[:5]):
    sql = r.get('generated_sql', '')
    print(f'{i+1}: length={len(sql)}')
    print(f'   success={r.get("success")}')
    sq = r.get('sql_queries', [])
    print(f'   sql_queries count in result: {len(sq)}')
    print()
