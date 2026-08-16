import asyncio
import logging
import sys
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

load_dotenv()

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

from agent_platform.analytics.service import AnalyticsAgentService

async def test():
    db_path = ROOT / "data" / "analytics.db"
    service = AnalyticsAgentService.from_sqlite(db_path)
    result = await service.analyze("What is the total revenue generated?")
    print(f"Status: {result.get('status')}")
    print(f"SQL queries count: {len(result.get('sql_queries', []))}")
    print(f"Verdict: {result.get('verdict')}")
    print(f"Confidence: {result.get('confidence')}")
    print(f"Summary: {result.get('summary', '')[:300]}")
    for i, step in enumerate(result.get('steps', [])):
        print(f"  Step {i}: {step.get('step', '')[:80]}")
        sql = step.get('sql')
        print(f"    SQL present: {sql is not None}")
        if sql:
            print(f"    SQL: {sql[:100]}")
    
asyncio.run(test())
