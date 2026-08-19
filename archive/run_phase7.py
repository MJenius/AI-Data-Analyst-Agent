import sys
import os
import asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(dotenv_path='.env', override=True)

# Verify env vars
print('LLM_PROVIDER:', os.getenv('LLM_PROVIDER'))
print('NVIDIA_MODEL:', os.getenv('NVIDIA_MODEL'))

# Now run the experiment
from tests.evaluation.phase3.run_experiments import main
import argparse

parser = argparse.ArgumentParser()
parser.add_argument('--limit', type=int, default=5, help='Run only the first N queries')
parser.add_argument('--run-id', default=None, help='Run ID')
args = parser.parse_args()

try:
    asyncio.run(main(args.limit, args.run_id))
except Exception as e:
    print(f'Error: {e}')
    import traceback
    traceback.print_exc()