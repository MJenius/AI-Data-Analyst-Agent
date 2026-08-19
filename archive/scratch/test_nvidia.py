from dotenv import load_dotenv
import os, json, urllib.request, time
load_dotenv()

api_key = os.getenv('NVIDIA_API_KEY')
model = os.getenv('NVIDIA_MODEL', 'meta/llama-3.3-70b-instruct')
url = 'https://integrate.api.nvidia.com/v1/chat/completions'

payload = json.dumps({
    'model': model,
    'messages': [{'role': 'user', 'content': 'Say hello in JSON'}],
    'temperature': 0.1,
    'max_tokens': 50,
    'response_format': {'type': 'json_object'}
}).encode()

req = urllib.request.Request(url, data=payload, headers={
    'Authorization': f'Bearer {api_key}',
    'Content-Type': 'application/json'
})

start = time.time()
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
        print(f'Success in {time.time()-start:.1f}s')
        print(data['choices'][0]['message']['content'][:200])
except Exception as e:
    print(f'Failed in {time.time()-start:.1f}s: {e}')
