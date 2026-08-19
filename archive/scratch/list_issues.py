import json
from pathlib import Path

p = Path(r'C:\Users\mjeni\OneDrive\Desktop\Own Projects\Data Analyst Agent\tests\evaluation\benchmark_audit_report.json')
r = json.loads(p.read_text(encoding='utf-8'))

print('Total issues:', len(r['issues']))
for i, x in enumerate(r['issues']):
    print(f'{i+1}. [{x["index"]+1}] {x["question"][:60]}... ({len(x["issues"])} issues)')
    for iss in x['issues']:
        print(f'   - [{iss["severity"]}] {iss["type"]}: {iss["detail"]}')
