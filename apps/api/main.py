from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

from agent_platform.analytics.service import AnalyticsAgentService, RunStore
from agent_platform.data.seed_data import seed_database

load_dotenv()


class AnalyzeRequest(BaseModel):
    question: str


def create_app() -> FastAPI:
    app = FastAPI(title="AI Data Analyst Agent")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    db_path = Path(os.getenv("ANALYTICS_DB_PATH", "runtime/analytics.db"))
    if not db_path.exists():
        seed_database(db_path)

    run_store = RunStore()
    service = AnalyticsAgentService.from_sqlite(
        db_path,
        trace_path=os.getenv("TRACE_JSONL_PATH", "runtime/traces.jsonl"),
        run_store=run_store,
    )

    @app.post("/tasks/analyze")
    async def analyze(request: AnalyzeRequest):
        return await service.analyze(request.question)

    @app.get("/runs/{run_id}")
    async def get_run(run_id: str):
        run = service.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return run

    return app


app = create_app()
