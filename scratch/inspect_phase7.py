import json

data = json.load(open('results/phase7/run_20260817T003553/raw_results.json'))
print(f'Results count: {len(data)}')
print(f'Keys: {list(data[0].keys())}')
r = data[0]
print(f'query_id: {r.get("query_id")}')
print(f'actual_sql: {r.get("actual_sql", None)[:200] if r.get("actual_sql") else None}')
print(f'error: {r.get("error")}')
print(f'result_correct: {r.get("result_correct")}')
print(f'sql_execution_success: {r.get("sql_execution_success")}')
print(f'actual_row_count: {r.get("actual_row_count")}')
print(f'expected_row_count: {r.get("expected_row_count")}')
