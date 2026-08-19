# Phase 4 — Schema Grounding and SQL Generation

Run: `run_20260816T_phase4_nvidia_nemotron_120b`. Frozen benchmark SHA-256: `3B55106604BB4CE7E3580A4A838AC29F8EBCF6A2F1B49442644437698B79F209`.
No benchmark question or benchmark SQL was used by retrieval, prompts, validation, or repair logic.

## What changed

- Schema packets now carry exact names/types, canonical and live keys, table grain, null/range/common-value statistics, business definitions, and complete allowed join edges.
- Improved RAG combines table/column/business evidence and expands the shortest valid relationship paths; current top-5 search remains the control.
- SQLGlot parses and qualifies every generated query against the live SQLite schema before execution, rejecting malformed/unsafe SQL, unknown tables/columns, out-of-context tables, and invalid physical joins.
- The SQL prompt requires an explicit table/column/join grounding manifest and discourages unnecessary tables and one-to-many fan-out.
- Structured QueryPlan is retained as a diagnostic ablation. Benchmark configurations use no execution retry; production allows one repair only for a concrete SQL/schema diagnostic.

## Before/after metrics

| Metric | Full schema | Current top-5 RAG | Improved RAG | Planner + improved RAG |
| :--- | ---: | ---: | ---: | ---: |
| Result correctness | 11.00% | 11.00% | 16.00% | 15.00% |
| Result equivalence | 11.00% | 11.00% | 16.00% | 15.00% |
| SQL table recall/accuracy | 95.33% | 74.50% | 71.50% | 73.67% |
| SQL table precision | 83.88% | 65.68% | 59.62% | 63.03% |
| SQL execution success | 59.00% | 57.00% | 50.00% | 62.00% |
| Invalid SQL | 41.00% | 43.00% | 50.00% | 38.00% |
| Schema hallucination | 1.00% | 0.00% | 2.00% | 0.00% |
| Blocked before execution | 3.00% | 28.00% | 29.00% | 24.00% |
| Average latency | 13.14s | 12.96s | 12.52s | 21.63s |
| Total tokens | 573619 | 147678 | 191690 | 398842 |
| Provider errors | 0 | 7 | 13 | 11 |
| Correctness excl. provider failures | 0.00% | 0.00% | 0.00% | 16.85% |

Phase 3 controlled references: full schema **14.0%** correct / **97.0%** table accuracy; current top-5 RAG **1.0%** / **48.5%**; planner + top-5 RAG **2.0%** / **58.2%**.

## Does improved RAG close the full-schema gap?

**No under a 3-point parity threshold.** Improved RAG is 5.00 points ahead of full schema on correctness and 23.83 points behind it on table accuracy.

## Remaining dominant failure modes

- **Full schema:** outcomes sql_execution_error=40, sql_semantic_error=40, correct=11; pre-execution validation malformed_sql=2, nonexistent_column=1.
- **Current top-5 RAG:** outcomes sql_semantic_error=37, sql_execution_error=36, correct=11; pre-execution validation malformed_sql=25, table_not_in_context=5.
- **Improved RAG:** outcomes sql_execution_error=35, sql_semantic_error=22, correct=16; pre-execution validation malformed_sql=27, nonexistent_column=2.
- **Planner + improved RAG:** outcomes sql_execution_error=27, planning_error=19, correct=15; pre-execution validation malformed_sql=24.
- Planner diagnostic: core plan correctness 38.71%; plan-correct/result-wrong cases 24.

## Phase 5 recommendation

Target the measured dominant improved-RAG failure (`sql_execution_error`) with result-level semantic verification and aggregate-grain checks. Keep AST/schema validation and the full-schema control fixed; do not add broad retries. Phase 5 was not started.
