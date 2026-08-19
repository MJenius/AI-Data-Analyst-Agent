import json

data = json.load(open('tests/evaluation/benchmark_dataset_v2.json'))
print(f'Total queries: {len(data)}')
print(f'Keys: {list(data[0].keys())}')
print(f'Sample question: {data[0]["question"][:100]}')
expected = data[0].get("expected_result", {})
print(f'Expected result type: {type(expected)}')
if isinstance(expected, dict):
    print(f'Expected result keys: {list(expected.keys())}')
else:
    print(f'Expected result is list of length: {len(expected)}')
