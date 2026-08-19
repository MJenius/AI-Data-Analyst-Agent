import asyncio
import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_platform.analytics.service import AnalyticsAgentService

async def test():
    db_path = ROOT / "data" / "analytics.db"
    service = AnalyticsAgentService.from_sqlite(db_path)
    result = await service.analyze("What is the total revenue generated?")
    print(f"Status: {result.get('status')}")
    print(f"SQL queries: {result.get('sql_queries')}")
    print(f"Error: {result.get('error')}")
    print(f"Summary: {result.get('summary', '')[:200]}")
    
asyncio.run(test())
