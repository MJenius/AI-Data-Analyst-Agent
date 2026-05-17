# System Architecture: End-to-End AI Data Analyst Agent Platform

This document describes the production-ready technical architecture, components, data flows, and design systems powering the AI Data Analyst Agent Platform.

---

## 1. High-Level Architecture Overview

The platform is designed around a fully asynchronous, decoupled service model that coordinates multi-agent planning and database reasoning. It utilizes localized semantic search over relational schemas, executing analytical workflows with safe database sandboxing, real-time telemetry streaming, and a highly resilient multi-model LLM fallback chain.

```text
       +-------------------------------------------------------------+
       |                  Web Client (HTML5 / Vanilla JS)             |
       +------------------------------+------------------------------+
                                      | (EventSource SSE & JSON POST)
                                      v
       +-------------------------------------------------------------+
       |                FastAPI Gateway / Async API Server            |
       +------------------------------+------------------------------+
                                      | (Request-Scoped task_ids)
                                      v
       +-------------------------------------------------------------+
       |             Multi-Agent Analytics Service Loop              |
       |                                                             |
       |  +------------------+     +------------------+     +-----+  |
       |  |   Planner Agent  | --> |  Executor Agent  | --> | Eval|  |
       |  +--------+---------+     +--------+---------+     +--+--+  |
       |           |                        |                  |     |
       +-----------|------------------------|------------------|-----+
                   | (Semantic Search)      | (Read-Only SQL)  | (Verdict)
                   v                        v                  v
       +---------------------+    +-------------------+    +---------+
       |  Schema Retriever   |    | SQLite Sandboxed  |    | Cascade |
       | (FAISS + Embeddings)|    |  Database (Olist) |    | LLMs    |
       +---------------------+    +-------------------+    +---------+
```

---

## 2. Production Tech Stack vs. Speculative Roadmap

To maintain a responsive, low-overhead local profile, the platform strictly segregates its immediate operational stack from future scale-out architectures:

| Architectural Tier | Production-Ready Active Implementation (Current) | Future Scale-Out Roadmap (Speculative) |
| :--- | :--- | :--- |
| **API Gateway** | [FastAPI](https://fastapi.tiangolo.com/) (Asynchronous ASGI server with `uvicorn`) | Next.js API Router |
| **User Interface** | Single-page App (Vanilla HTML5 / CSS3 / ES6 Javascript) | React / Next.js Framework |
| **Database Engine** | [SQLite3](https://sqlite.org/) (Sandboxed, thread-safe memory/file-backed read-only connections) | PostgreSQL / Greenplum |
| **Vector Search (RAG)** | [FAISS](https://github.com/facebookresearch/faiss) (Flat L2 index) with local `all-MiniLM-L6-v2` embeddings | Pinecone / pgvector |
| **Orchestration Loop** | Pure Asynchronous CPython Task Loop (Stateless execution graph) | LangGraph / Temporal.io |
| **Observability/SSE** | `StreamingResponse` (Native ASGI Server-Sent Events) | Apache Kafka / RabbitMQ |
| **In-Memory Cache** | `collections.OrderedDict` (LRU Run Store capped at 1,000 runs) | Redis |
| **LLM Clients** | `GroqClient` $\rightarrow$ `GeminiClient` $\rightarrow$ `OllamaClient` Cascade | OpenAI API / Anthropic API |

---

## 3. Core Architectural Components

### A. FastAPI Gateway (`apps/api/main.py`)
Exposes non-blocking endpoints for analysis and previews:
- **`/tasks/analyze`**: Receives analysis requests containing `question` and a client-side generated UUID `task_id`. Dispatches the asynchronous service loop.
- **`/tasks/progress/{task_id}/stream`**: Server-Sent Events (SSE) route. Binds to a thread-safe `contextvars.ContextVar` containing request-scoped queues, streaming status frames under 100ms.
- **`/preview`**: Runs database introspection queries wrapped in `asyncio.to_thread` to prevent SQLite disk I/O from blocking the main async loop.

### B. Fallback LLM Cascade (`src/agent_platform/llms/`)
Orchestrates requests across API boundaries with automatic structural Pydantic validation:
1. **Primary (`GroqClient`)**: Executes `llama-3.3-70b-versatile` or `qwen-2.5-32b` over JSON-mode endpoints.
2. **Secondary (`GeminiClient`)**: Rest-based direct `gemini-1.5-flash` client utilizing standard `urllib.request` to operate under zero-dependency constraints.
3. **Tertiary (`OllamaClient`)**: Local safety-net hosting `llama3` for offline execution.

### C. FAISS RAG Retrieval (`src/agent_platform/rag/`)
Retrieves database schema tokens dynamically:
- **Semantic Representation**: Database schemas (DDL, table definitions) are encoded into 384-dimensional vectors using local sentence-transformers.
- **Disk-Cached Embeddings**: `EmbeddingModel.embed_batch` performs local cache lookups to completely bypass model inference passes for previously analyzed text, batching uncached tokens efficiently.
- **Proactive Schema Retrieve**: If a plan step executes without explicit schema tokens in the context, `SchemaRetriever` automatically fires a search targeting `"{step} tables"` to retrieve valid table mappings.

### D. Sandboxed SQL Tool (`src/agent_platform/tools/sql_tool.py`)
Validates and executes generated queries:
- **Safety Bounds**: Implements a fail-closed parser blocking DDL/DML actions (`DROP`, `INSERT`, `UPDATE`, `DELETE`, `ALTER`) and raising `SQLSafetyError`.
- **Hallucination Prevention**: Verifies every target table in the generated SQL statement against the retrieved schema documents in the active context, blocking invalid tables before query compile time.
- **Async DB Execution**: Wraps database calls using `asyncio.to_thread` to preserve thread-pool boundaries.

---

## 4. Multi-Agent Data and Control Flow

The orchestration follows a linear planning, execution, and validation pipeline:

```text
   [User Question]
          |
          v
   +--------------+
   |   Planner    | ---> Retrieves DDL schemas from FAISS RAG
   +------+-------+      Generates structured step-by-step reasoning plan
          |
          v
   +--------------+
   |   Executor   | ---> Performs up to 3 retries per plan step
   +------+-------+      Validates tables, runs sandboxed SQLite queries
          |
          v
   +--------------+
   |  Evaluator   | ---> Compares metrics against original plan steps
   +------+-------+      Verifies output consistency & assigns confidence score
          |
          +---> SUCCESS (verdict == "accurate") --> Render UI results Card
          |
          +---> FAILURE (verdict == "uncertain") --> Deploy deterministic SQL fallback
```

1. **Planner Agent**: Evaluates the question, performs RAG over database structures, and outputs a JSON `PlannerOutput` plan.
2. **Executor Agent**: Loops over planned steps. Generates sandboxed SQLite statements, validates table existence, and caches results. It attempts up to 3 SQL generations per step.
3. **Evaluator Agent**: Inspects the original question, active plan, intermediate database traces, and synthesizes the final report. Assigns a confidence score and structural validation verdict (`accurate` vs `uncertain`).
4. **Deterministic Fallback**: If LLM validation fails, the engine deploys a deterministic, pre-compiled high-coverage SQL statement to guarantee robust UI rendering.

---

## 5. Memory Management & Observability

- **OrderedDict LRU Store**: The `RunStore` is backed by a capped `OrderedDict`. Upon reaching 1,000 execution runs, the oldest run logs are evicted, maintaining strict $O(1)$ memory consumption and preventing memory leaks.
- **Server-Sent Events Telemetry**: The UI establishes a direct `EventSource` connection to the SSE stream. The backend observers stream standard JSON progress packets including execution times, active agent states, and database preview matrices.
