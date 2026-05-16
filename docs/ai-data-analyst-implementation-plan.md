# AI Data Analyst Agent Implementation Plan

## Goal

Deliver the first production-ready vertical slice of the agent platform as an autonomous analytics agent.

## Scope

- Local SQLite analytics dataset with e-commerce schema and seed data.
- Schema-aware retrieval abstraction with a dependency-free vector fallback and FAISS-ready interface.
- Safe read-only SQL execution tool with validation, timing, retries, schema introspection, and query logging.
- Analytics planner, executor, evaluator, report builder, and service facade.
- FastAPI endpoints for `POST /tasks/analyze` and `GET /runs/{id}`.
- Tests covering SQL safety, schema retrieval, and the end-to-end agent flow.

## Architecture

The runtime flow is:

1. User submits a business question.
2. `AnalyticsPlannerAgent` retrieves schema context and decomposes the question into analysis steps.
3. `AnalyticsExecutorAgent` retrieves step-specific schema context, generates safe SQL, executes it, and interprets results.
4. `AnalyticsEvaluatorAgent` validates SQL-backed evidence and scores confidence.
5. `AnalyticsReportBuilder` produces structured analytical output.
6. `AnalyticsObserver` records run and step traces, optionally persisted as JSONL.

## Extensibility

- Replace SQLite SQL execution with a PostgreSQL implementation behind the same `SQLTool` interface.
- Replace keyword vector search with FAISS/Pinecone/Weaviate behind the `VectorIndex` interface.
- Replace deterministic planner and SQL generation with LLM providers while preserving agent interfaces.
- Replace `RunStore` with PostgreSQL persistence for production run lookup.
