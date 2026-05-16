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

    @app.get("/data/tables/{table_name}/preview")
    async def get_table_preview(table_name: str):
        import logging
        api_logger = logging.getLogger("api")
        table_name = table_name.strip().lower()
        api_logger.info(f"Table preview requested for: '{table_name}'")
        try:
            import sqlite3
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            allowed_tables = [
                "customers", "geolocation", "order_items", "order_payments", 
                "order_reviews", "orders", "products", "sellers", "product_category_name_translation"
            ]
            if table_name not in allowed_tables:
                api_logger.warning(f"Invalid table name requested: '{table_name}'")
                raise HTTPException(status_code=400, detail=f"Invalid table name: {table_name}")
                
            cursor.execute(f"SELECT * FROM {table_name} LIMIT 30")
            columns = [description[0] for description in cursor.description]
            rows = cursor.fetchall()
            conn.close()
            api_logger.info(f"Successfully fetched {len(rows)} rows for {table_name}")
            return {"columns": columns, "rows": rows}
        except Exception as e:
            api_logger.error(f"Error fetching preview for {table_name}: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    from fastapi.staticfiles import StaticFiles
    ui_path = Path(__file__).parent.parent / "ui"
    if ui_path.exists():
        app.mount("/ui", StaticFiles(directory=str(ui_path), html=True), name="ui")

    return app


app = create_app()
