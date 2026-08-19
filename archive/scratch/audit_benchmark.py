import sqlite3
import json
from pathlib import Path

DB_PATH = r'C:\Users\mjeni\OneDrive\Desktop\Own Projects\Data Analyst Agent\runtime\analytics.db'
V2_BENCHMARK_PATH = Path(__file__).resolve().parents[1] / 'tests' / 'evaluation' / 'benchmark_dataset_v2.json'
AUDIT_REPORT_PATH = Path(__file__).resolve().parents[1] / 'tests' / 'evaluation' / 'benchmark_audit_report.json'

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

def run_sql(sql: str):
    cursor.execute(sql)
    cols = [d[0] for d in cursor.description]
    rows = cursor.fetchall()
    return cols, rows

def to_json_value(val):
    if val is None:
        return None
    if isinstance(val, float):
        return round(val, 4)
    return val

with open(V2_BENCHMARK_PATH, 'r', encoding='utf-8') as f:
    v2 = json.load(f)

issues = []
audit_results = []

for i, entry in enumerate(v2):
    question = entry['question']
    expected_sql = entry['expected_sql']
    expected_tables = entry['expected_tables']
    expected_result = entry.get('expected_result', {})
    query_type = entry.get('query_type', 'unknown')
    difficulty = entry.get('difficulty', 'unknown')
    correctness_checks = entry.get('correctness_checks', [])
    domain = entry.get('domain', entry.get('category', 'unknown'))
    
    entry_issues = []
    
    # 1. Execute gold SQL to verify it works
    try:
        cols, rows = run_sql(expected_sql)
        actual_row_count = len(rows)
        expected_row_count = expected_result.get('row_count', 0)
        
        if actual_row_count != expected_row_count:
            entry_issues.append({
                'type': 'row_count_mismatch',
                'severity': 'high',
                'detail': f'Gold SQL returned {actual_row_count} rows, expected_result says {expected_row_count}'
            })
        
        # Check if expected tables match what the SQL actually uses
        sql_lower = expected_sql.lower()
        actual_tables_used = []
        for t in ['customers', 'geolocation', 'order_items', 'order_payments', 'order_reviews', 'orders', 'products', 'sellers', 'product_category_name_translation']:
            if t in sql_lower:
                actual_tables_used.append(t)
        
        missing_tables = [t for t in expected_tables if t not in actual_tables_used]
        extra_tables = [t for t in actual_tables_used if t not in expected_tables]
        
        if missing_tables:
            entry_issues.append({
                'type': 'missing_expected_tables',
                'severity': 'medium',
                'detail': f'Expected tables {missing_tables} not found in gold SQL'
            })
        
        if extra_tables:
            entry_issues.append({
                'type': 'extra_tables_in_sql',
                'severity': 'low',
                'detail': f'Gold SQL uses additional tables {extra_tables}'
            })
        
        # Check query_type consistency
        q_lower = question.lower()
        if query_type == 'single_value':
            if actual_row_count != 1:
                entry_issues.append({
                    'type': 'query_type_row_count_mismatch',
                    'severity': 'medium',
                    'detail': f'Marked as single_value but returned {actual_row_count} rows'
                })
        elif query_type == 'ranking':
            if actual_row_count < 2:
                entry_issues.append({
                    'type': 'query_type_ranking_insufficient',
                    'severity': 'medium',
                    'detail': f'Marked as ranking but only returned {actual_row_count} rows'
                })
        elif query_type == 'time_series':
            if actual_row_count < 2:
                entry_issues.append({
                    'type': 'query_type_timeseries_insufficient',
                    'severity': 'medium',
                    'detail': f'Marked as time_series but only returned {actual_row_count} rows'
                })
        
        # Check difficulty consistency
        tables_needed = len(expected_tables)
        if difficulty == 'easy' and tables_needed >= 3:
            entry_issues.append({
                'type': 'difficulty_table_mismatch',
                'severity': 'low',
                'detail': f'Marked as easy but requires {tables_needed} tables'
            })
        
        # Check correctness_checks
        if 'percentage_range_0_100' in correctness_checks:
            # Verify the SQL actually returns percentages
            pass
        
        # Verify expected_result values match actual execution
        if expected_result.get('values'):
            actual_values = []
            for row in rows[:50]:
                actual_values.append({c: to_json_value(v) for c, v in zip(cols, row)})
            
            # Quick check: do the expected values match actual?
            mismatches = 0
            for j, (exp_val, act_val) in enumerate(zip(expected_result['values'], actual_values)):
                if exp_val != act_val:
                    mismatches += 1
                    if mismatches <= 3:
                        entry_issues.append({
                            'type': 'expected_value_mismatch',
                            'severity': 'high',
                            'detail': f'Row {j}: expected {exp_val}, got {act_val}'
                        })
            
            if mismatches > 3:
                entry_issues.append({
                    'type': 'expected_value_mismatch',
                    'severity': 'high',
                    'detail': f'... and {mismatches - 3} more value mismatches'
                })
        
    except Exception as e:
        entry_issues.append({
            'type': 'sql_execution_failed',
            'severity': 'critical',
            'detail': f'Gold SQL failed to execute: {str(e)}'
        })
    
    audit_results.append({
        'index': i,
        'question': question,
        'query_type': query_type,
        'difficulty': difficulty,
        'domain': domain,
        'issues': entry_issues,
        'status': 'PASS' if not entry_issues else 'ISSUES_FOUND'
    })
    
    if entry_issues:
        issues.append({
            'index': i,
            'question': question,
            'query_type': query_type,
            'difficulty': difficulty,
            'issues': entry_issues
        })

# Summary
total = len(v2)
passed = sum(1 for r in audit_results if r['status'] == 'PASS')
failed = total - passed

critical = sum(1 for r in issues for i in r['issues'] if i['severity'] == 'critical')
high = sum(1 for r in issues for i in r['issues'] if i['severity'] == 'high')
medium = sum(1 for r in issues for i in r['issues'] if i['severity'] == 'medium')
low = sum(1 for r in issues for i in r['issues'] if i['severity'] == 'low')

report = {
    'total_queries': total,
    'passed': passed,
    'failed': failed,
    'issues_by_severity': {
        'critical': critical,
        'high': high,
        'medium': medium,
        'low': low
    },
    'issues': issues[:50],  # First 50 issues for review
    'full_audit_results': audit_results
}

with open(AUDIT_REPORT_PATH, 'w', encoding='utf-8') as f:
    json.dump(report, f, indent=2, ensure_ascii=False)

print(f"=== BENCHMARK AUDIT SUMMARY ===")
print(f"Total queries: {total}")
print(f"Passed: {passed}")
print(f"Failed: {failed}")
print(f"Issues by severity: critical={critical}, high={high}, medium={medium}, low={low}")
print(f"\nTop issues:")
for issue in issues[:10]:
    print(f"  [{issue['index']+1}] {issue['question'][:60]}...")
    for i in issue['issues']:
        print(f"    - [{i['severity']}] {i['type']}: {i['detail']}")

print(f"\nFull audit report saved to: {AUDIT_REPORT_PATH}")

conn.close()
