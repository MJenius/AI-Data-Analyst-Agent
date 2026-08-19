import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

from agent_platform.analytics.service import AnalyticsAgentService

async def test():
    db_path = ROOT / "data" / "analytics.db"
    service = AnalyticsAgentService.from_sqlite(db_path)
    result = await service.analyze("What is the total revenue generated?")
    print(f"Status: {result.get('status')}")
    print(f"SQL queries: {result.get('sql_queries')}")
    print(f"Verdict: {result.get('verdict')}")
    print(f"Confidence: {result.get('confidence')}")
    print(f"Summary: {result.get('summary', '')[:300]}")
    print(f"Steps count: {len(result.get('steps', []))}")
    for i, step in enumerate(result.get('steps', [])):
        print(f"  Step {i}: {step.get('step', '')[:80]}")
        print(f"    SQL: {step.get('sql', '')[:100] if step.get('sql') else 'None'}")
    
asyncio.run(test())
