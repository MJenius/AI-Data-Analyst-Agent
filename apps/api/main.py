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
    class GlobalProgressStore:
        latest_message: str = "Initializing..."
        plan_steps: list[str] = []
        completed_steps: list[dict] = []
        current_step: str | None = None
        error: str | None = None

    progress_store = GlobalProgressStore()

    db_path = Path(os.getenv("ANALYTICS_DB_PATH", "runtime/analytics.db"))
    if not db_path.exists():
        seed_database(db_path)

    run_store = RunStore()
    
    trace_path = os.getenv("TRACE_JSONL_PATH", "runtime/traces.jsonl")
    
    # We create the service but need to intercept the observer to send progress to the frontend
    service = AnalyticsAgentService.from_sqlite(
        db_path,
        trace_path=trace_path,
        run_store=run_store,
    )
    
    # Monkeypatch observer for real-time progress
    original_step_start = service._observer.on_step_start
    def custom_step_start(state, step):
        progress_store.latest_message = f"Executing: {step}"
        progress_store.plan_steps = list(state.plan) if state.plan else []
        progress_store.current_step = step
        original_step_start(state, step)
    service._observer.on_step_start = custom_step_start
    
    original_run_start = service._observer.on_run_start
    def custom_run_start(state):
        progress_store.latest_message = "Analyzing question and planning steps..."
        progress_store.plan_steps = []
        progress_store.completed_steps = []
        progress_store.current_step = None
        progress_store.error = None
        original_run_start(state)
    service._observer.on_run_start = custom_run_start
    
    original_step_end = service._observer.on_step_end
    def custom_step_end(state, step, result, elapsed):
        progress_store.latest_message = f"Completed: {step}"
        progress_store.completed_steps.append({
            "step": step,
            "elapsed": elapsed
        })
        original_step_end(state, step, result, elapsed)
    service._observer.on_step_end = custom_step_end

    original_run_error = service._observer.on_run_error
    def custom_run_error(state, step, error):
        progress_store.error = str(error)
        original_run_error(state, step, error)
    service._observer.on_run_error = custom_run_error

    @app.post("/tasks/analyze")
    async def analyze(request: AnalyzeRequest):
        import asyncio
        progress_store.latest_message = "Initializing..."
        try:
            # Run in a separate thread and event loop so we don't freeze the FastAPI server
            return await asyncio.to_thread(
                lambda: asyncio.run(service.analyze(request.question))
            )
        finally:
            progress_store.latest_message = "Finished."

    @app.get("/tasks/progress")
    async def get_progress():
        return {
            "message": progress_store.latest_message,
            "plan_steps": progress_store.plan_steps,
            "completed_steps": progress_store.completed_steps,
            "current_step": progress_store.current_step,
            "error": progress_store.error
        }

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
