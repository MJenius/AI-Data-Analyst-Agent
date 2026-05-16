import sys
import asyncio
import json
from pathlib import Path
import os
from dotenv import load_dotenv

# Add src to path
sys.path.append(str(Path(__file__).parent / "src"))

from agent_platform.analytics.service import AnalyticsAgentService

async def main():
    load_dotenv()
    
    if len(sys.argv) < 2:
        print("Usage: python run_analysis.py \"Your analytical question here\"")
        sys.exit(1)
        
    question = sys.argv[1]
    db_path = os.getenv("ANALYTICS_DB_PATH", "runtime/analytics.db")
    
    if not Path(db_path).exists():
        print(f"Database not found at {db_path}. Please run seeding first or ensure the path is correct.")
        sys.exit(1)

    print(f"\n\033[1;34m[Agent]\033[0m Analyzing: \"{question}\"")
    print("\033[1;30mThinking...\033[0m\n")

    service = AnalyticsAgentService.from_sqlite(db_path)
    result = await service.analyze(question)

    # Pretty print the output
    print("\033[1;32m=== ANALYSIS SUMMARY ===\033[0m")
    print(f"{result['summary']}\n")

    print("\033[1;32m=== KEY FINDINGS ===\033[0m")
    for i, finding in enumerate(result['key_findings'], 1):
        print(f"{i}. {finding}")
    print()

    print("\033[1;32m=== SQL QUERIES ===\033[0m")
    for i, sql in enumerate(result['sql_queries'], 1):
        print(f"Query {i}:")
        print(f"\033[0;36m{sql}\033[0m\n")

    print("\033[1;32m=== EXECUTION TRACE ===\033[0m")
    for i, step in enumerate(result['steps'], 1):
        print(f"Step {i}: {step['step']}")
        print(f"  \033[1;30mReasoning:\033[0m {step['reasoning']}")
        if step['sql']:
            print(f"  \033[1;30mSQL:\033[0m {step['sql'][:100]}...")
        print(f"  \033[1;30mTime:\033[0m {step['execution_time_ms']}ms\n")

    print(f"\033[1;32m=== METADATA ===\033[0m")
    print(f"Confidence: {result['confidence'] * 100:.1f}%")
    print(f"Verdict: {result['verdict'].upper()}")
    print(f"Run ID: {result['run_id']}")

if __name__ == "__main__":
    asyncio.run(main())
