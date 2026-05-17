from __future__ import annotations

import os
import uuid
import json
import logging
import asyncio
import contextvars
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

from agent_platform.analytics.service import AnalyticsAgentService, RunStore
from agent_platform.data.seed_data import seed_database

load_dotenv()


class AnalyzeRequest(BaseModel):
    question: str
    task_id: str | None = None


class TaskProgress:
    """Thread-safe request-scoped progress data."""
    def __init__(self) -> None:
        self.latest_message: str = "Initializing..."
        self.plan_steps: list[str] = []
        self.completed_steps: list[dict] = []
        self.current_step: str | None = None
        self.error: str | None = None
        self.created_at: float = time.time()
        self.finished_at: float | None = None


# Thread-safe ContextVar to store task_id for active request execution contexts
active_task_id: contextvars.ContextVar[str] = contextvars.ContextVar("active_task_id", default="")

progress_registry: dict[str, TaskProgress] = {}
task_queues: dict[str, asyncio.Queue] = {}


def push_progress_update(t_id: str, store: TaskProgress):
    """Safely enqueues a progress update to the respective SSE task queue."""
    queue = task_queues.get(t_id)
    if queue:
        payload = {
            "message": store.latest_message,
            "plan_steps": store.plan_steps,
            "completed_steps": store.completed_steps,
            "current_step": store.current_step,
            "error": store.error
        }
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.call_soon_threadsafe(queue.put_nowait, payload)
            else:
                queue.put_nowait(payload)
        except RuntimeError:
            queue.put_nowait(payload)


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
    trace_path = os.getenv("TRACE_JSONL_PATH", "runtime/traces.jsonl")
    
    # Instantiate the analytics agent service coordinator
    service = AnalyticsAgentService.from_sqlite(
        db_path,
        trace_path=trace_path,
        run_store=run_store,
    )
    
    # Intercept and redirect the coordinator execution loop observer to the registry
    original_step_start = service._observer.on_step_start
    def custom_step_start(state, step):
        t_id = active_task_id.get()
        if t_id:
            store = progress_registry.get(t_id)
            if store:
                store.latest_message = f"Executing: {step}"
                store.plan_steps = list(state.plan) if state.plan else []
                store.current_step = step
                push_progress_update(t_id, store)
        original_step_start(state, step)
    service._observer.on_step_start = custom_step_start
    
    original_run_start = service._observer.on_run_start
    def custom_run_start(state):
        t_id = active_task_id.get()
        if t_id:
            store = progress_registry.get(t_id)
            if store:
                store.latest_message = "Analyzing question and planning steps..."
                store.plan_steps = []
                store.completed_steps = []
                store.current_step = None
                store.error = None
                push_progress_update(t_id, store)
        original_run_start(state)
    service._observer.on_run_start = custom_run_start
    
    original_step_end = service._observer.on_step_end
    def custom_step_end(state, step, result, elapsed):
        t_id = active_task_id.get()
        if t_id:
            store = progress_registry.get(t_id)
            if store:
                store.latest_message = f"Completed: {step}"
                store.completed_steps.append({
                    "step": step,
                    "elapsed": elapsed
                })
                push_progress_update(t_id, store)
        original_step_end(state, step, result, elapsed)
    service._observer.on_step_end = custom_step_end

    original_run_error = service._observer.on_run_error
    def custom_run_error(state, step, error):
        t_id = active_task_id.get()
        if t_id:
            store = progress_registry.get(t_id)
            if store:
                store.error = str(error)
                push_progress_update(t_id, store)
        original_run_error(state, step, error)
    service._observer.on_run_error = custom_run_error

    @app.post("/tasks/analyze")
    async def analyze(request: AnalyzeRequest):
        task_id = request.task_id or str(uuid.uuid4())
        active_task_id.set(task_id)
        
        # Initialize thread-safe progress store and SSE queue entries
        store = TaskProgress()
        progress_registry[task_id] = store
        task_queues[task_id] = asyncio.Queue()
        
        try:
            # Genuinely await service.analyze() directly in the FastAPI event loop
            result = await service.analyze(request.question)
            return result
        except Exception as e:
            store.error = str(e)
            push_progress_update(task_id, store)
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            store.latest_message = "Finished."
            store.finished_at = time.time()
            push_progress_update(task_id, store)

    @app.get("/tasks/progress/{task_id}")
    async def get_progress_by_id(task_id: str):
        store = progress_registry.get(task_id)
        if store is None:
            raise HTTPException(status_code=404, detail="Task not found or already cleaned up")
        return {
            "message": store.latest_message,
            "plan_steps": store.plan_steps,
            "completed_steps": store.completed_steps,
            "current_step": store.current_step,
            "error": store.error
        }

    @app.get("/tasks/progress/{task_id}/stream")
    async def get_progress_stream(task_id: str):
        queue = task_queues.get(task_id)
        if queue is None:
            # If requesting stream and it doesn't exist yet, initialize it
            store = TaskProgress()
            progress_registry[task_id] = store
            queue = asyncio.Queue()
            task_queues[task_id] = queue
            
        async def event_generator():
            # Seed the connection with the current registry snapshot
            store = progress_registry.get(task_id)
            if store:
                initial_payload = {
                    "message": store.latest_message,
                    "plan_steps": store.plan_steps,
                    "completed_steps": store.completed_steps,
                    "current_step": store.current_step,
                    "error": store.error
                }
                yield f"data: {json.dumps(initial_payload)}\n\n"
                
            while True:
                try:
                    data = await queue.get()
                    yield f"data: {json.dumps(data)}\n\n"
                    if data.get("message") == "Finished." or data.get("error"):
                        break
                except asyncio.CancelledError:
                    break
                except Exception:
                    break
                    
        return StreamingResponse(event_generator(), media_type="text/event-stream")

    @app.get("/runs/{run_id}")
    async def get_run(run_id: str):
        run = service.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return run

    @app.get("/data/tables/{table_name}/preview")
    async def get_table_preview(table_name: str):
        api_logger = logging.getLogger("api")
        table_name = table_name.strip().lower()
        api_logger.info(f"Table preview requested for: '{table_name}'")
        try:
            allowed_tables = [
                "customers", "geolocation", "order_items", "order_payments", 
                "order_reviews", "orders", "products", "sellers", "product_category_name_translation"
            ]
            if table_name not in allowed_tables:
                api_logger.warning(f"Invalid table name requested: '{table_name}'")
                raise HTTPException(status_code=400, detail=f"Invalid table name: {table_name}")
                
            def fetch_rows():
                import sqlite3
                conn = sqlite3.connect(db_path)
                try:
                    cursor = conn.cursor()
                    cursor.execute(f"SELECT * FROM {table_name} LIMIT 30")
                    columns = [description[0] for description in cursor.description]
                    rows = cursor.fetchall()
                    return columns, rows
                finally:
                    conn.close()
                    
            columns, rows = await asyncio.to_thread(fetch_rows)
            api_logger.info(f"Successfully fetched {len(rows)} rows for {table_name}")
            return {"columns": columns, "rows": rows}
        except HTTPException:
            raise
        except Exception as e:
            api_logger.error(f"Error fetching preview for {table_name}: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.on_event("startup")
    async def startup_event():
        async def periodic_cleanup():
            while True:
                await asyncio.sleep(10)
                now = time.time()
                to_remove = []
                for t_id, store in list(progress_registry.items()):
                    if store.finished_at and (now - store.finished_at > 30):
                        to_remove.append(t_id)
                for t_id in to_remove:
                    progress_registry.pop(t_id, None)
                    task_queues.pop(t_id, None)
        asyncio.create_task(periodic_cleanup())

    ui_path = Path(__file__).parent.parent / "ui"
    if ui_path.exists():
        app.mount("/ui", StaticFiles(directory=str(ui_path), html=True), name="ui")

    return app


app = create_app()
