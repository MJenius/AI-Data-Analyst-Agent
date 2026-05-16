# AI Data Analyst Agent

AI Data Analyst Agent - Autonomous data analysis using agentic AI.

Dashboards are useful for known questions, but they struggle when business teams ask open-ended questions like "Why did revenue drop in March?" or "Which products drove growth last quarter?" This project turns those questions into planned, schema-aware, SQL-backed analysis with validation and execution traces.

## Problem

Traditional analytics workflows are limited by:

- Static dashboards that only answer pre-modeled questions
- Manual SQL handoffs between business teams and data analysts
- Text-to-SQL systems that generate queries without validation
- Lack of traceability from question to query to conclusion

Production analytics agents need more than a chatbot. They need planning, tool use, evaluation, and observability.

## Solution

This repository implements a production-shaped AI Data Analyst Agent:

```text
User question
    |
    v
Planner Agent
    |
    v
Schema-aware RAG
    |
    v
SQL Generation
    |
    v
Safe SQL Tool
    |
    v
Result Analysis
    |
    v
Evaluator Agent
    |
    v
Structured Report + Trace
```

The system is modular: LLM providers, vector stores, SQL backends, tools, evaluators, and orchestration policies can be swapped independently.

## Features

- Schema-aware RAG over tables, columns, relationships, and business metrics
- Groq-powered planner, SQL generation, and evaluator agents
- Safe read-only SQL execution with destructive-query blocking
- Structured reports with summary, findings, SQL queries, metrics, confidence, and trace
- Observability hooks for LLM calls, SQL execution, step timing, and run traces
- FastAPI backend with `POST /tasks/analyze` and `GET /runs/{run_id}`
- Lightweight browser UI in `apps/ui`
- Local SQLite demo dataset with e-commerce revenue data
- Clean test coverage for SQL safety, retrieval quality, orchestration, and e2e flow

## Demo

Input:

```text
What products drove the highest revenue growth?
```

Example output:

```json
{
  "summary": "Insight Pro drove the highest revenue growth at 1685.0 incremental revenue.",
  "findings": [
    "Insight Pro drove the highest revenue growth at 1685.0 incremental revenue."
  ],
  "sql_queries": [
    "WITH product_period_revenue AS (...) SELECT product_name, category, prior_revenue, current_revenue, revenue_growth ..."
  ],
  "confidence": 0.92,
  "execution_trace": {
    "steps": [
      {
        "step": "calculate product revenue growth between prior and current periods",
        "reasoning": "Generated SQL from schema context.",
        "sql": "WITH product_period_revenue AS (...)",
        "result_preview": "[{'product_name': 'Insight Pro', ...}]",
        "execution_time_ms": 2.4
      }
    ]
  }
}
```

## Tech Stack

- Python
- FastAPI
- Groq API with `llama-3.3-70b-versatile`
- SQLite for local demo data
- PostgreSQL-ready SQL abstraction
- FAISS-ready vector index abstraction with local keyword fallback
- Plain HTML/CSS/JS frontend
- `unittest` test suite

## Setup

Create and activate a virtual environment:

```bash
python -m venv .venv
.venv\Scripts\activate
```

Install the project:

```bash
pip install -e .
```

Configure environment variables:

```powershell
$env:GROQ_API_KEY="your-groq-api-key"
$env:GROQ_MODEL="llama-3.3-70b-versatile"
$env:ANALYTICS_DB_PATH="runtime/analytics.db"
$env:TRACE_JSONL_PATH="runtime/traces.jsonl"
```

The repository ignores `.env` and `.env.*` files, so local secrets stay out of git.

## Run Backend

```bash
uvicorn apps.api.main:app --reload
```

Backend URL:

```text
http://localhost:8000
```

## Run UI

Open:

```text
apps/ui/index.html
```

The UI calls:

```text
http://localhost:8000/tasks/analyze
```

## API

Analyze a question:

```bash
curl -X POST http://localhost:8000/tasks/analyze ^
  -H "Content-Type: application/json" ^
  -d "{\"question\":\"What products drove the highest revenue growth?\"}"
```

Fetch a stored run:

```bash
curl http://localhost:8000/runs/{run_id}
```

## Project Structure

```text
apps/
  api/                  FastAPI backend
  ui/                   Lightweight demo UI
data/
  schema.sql            Local analytics schema
src/agent_platform/
  analytics/            Planner, executor, evaluator, report service
  data/                 Dataset seeding
  llms/                 Groq client and prompt templates
  observability/        Trace hooks and JSONL trace store
  orchestration/        Execution loop and state management
  rag/                  Schema context ingestion and retrieval
  tools/                Safe SQL execution tool
tests/                  Unit and e2e tests
```

## Testing

```bash
python -m unittest discover tests
```

## Future Improvements

- PostgreSQL execution backend
- FAISS/Pinecone/Weaviate vector index implementation
- Streaming agent traces over WebSockets or Server-Sent Events
- Chart generation and visualization recommendations
- Multi-agent decomposition for retention, forecasting, and anomaly analysis
- Persistent run storage in PostgreSQL
- Role-based access controls and query governance
