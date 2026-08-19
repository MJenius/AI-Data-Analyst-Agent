# Phase 4 — Schema Grounding and SQL Generation

Run: `run_20260816T_phase4_nvidia_nemotron_120b_v2`. Frozen benchmark SHA-256: `3B55106604BB4CE7E3580A4A838AC29F8EBCF6A2F1B49442644437698B79F209`.
No benchmark question or benchmark SQL was used by retrieval, prompts, validation, or repair logic.

Prior run (`run_20260816T_phase4_nvidia_nemotron_120b`) is preserved for comparison. This run adds column-aware retrieval refinements: business-term grounded column packets, lexical column matching, and English category translation boosting.

## What changed

- Schema packets now carry exact names/types, canonical and live keys, table grain, null/range/common-value statistics, business definitions, and complete allowed join edges.
- Improved RAG combines table/column/business evidence and expands the shortest valid relationship paths; current top-5 search remains the control.
- SQLGlot parses and qualifies every generated query against the live SQLite schema before execution, rejecting malformed/unsafe SQL, unknown tables/columns, out-of-context tables, and invalid physical joins.
- The SQL prompt requires an explicit table/column/join grounding manifest and discourages unnecessary tables and one-to-many fan-out.
- Structured QueryPlan is retained as a diagnostic ablation. Benchmark configurations use no execution retry; production allows one repair only for a concrete SQL/schema diagnostic.
- Regression tests (`tests/test_phase4_schema_grounding.py`) lock Phase 3 failure patterns: hallucinated columns (`order_date`, `quantity`), invalid join keys, out-of-context tables, and grounded retrieval for revenue/joins/categories.

## Phase 3 → Phase 4 delta (controlled baselines)

| Metric | Phase 3 full schema | Phase 3 top-5 RAG | Phase 3 planner+RAG | Phase 4 improved RAG |
| :--- | ---: | ---: | ---: | ---: |
| Result correctness | 14.0% | 1.0% | 2.0% | **16.0%** |
| Table accuracy | 97.0% | 48.5% | 58.2% | 82.0% |
| SQL execution success | 69.0% | 4.0% | — | 60.0% |
| Pre-exec blocked | — | — | — | 16.0% |

Improved RAG recovers most of the RAG correctness collapse (+15 points vs Phase 3 top-5) and exceeds full-schema correctness (+2 points) while retaining 82% table accuracy. Top-5 RAG also improved (1% → 12%) but still trails full schema on table grounding.

## Before/after metrics (Phase 4 ablations)

| Metric | Full schema | Current top-5 RAG | Improved RAG | Planner + improved RAG |
| :--- | ---: | ---: | ---: | ---: |
| Result correctness | 14.00% | 12.00% | **16.00%** | 11.00% |
| Result equivalence | 14.00% | 12.00% | **16.00%** | 11.00% |
| SQL table recall/accuracy | **93.00%** | 73.50% | 82.00% | 67.17% |
| SQL table precision | **77.47%** | 68.08% | 68.62% | 59.78% |
| SQL execution success | **60.00%** | 50.00% | 60.00% | 54.00% |
| Invalid SQL | 40.00% | 50.00% | 40.00% | 46.00% |
| Schema hallucination | 0.00% | 2.00% | 1.00% | 1.00% |
| Blocked before execution | **7.00%** | 32.00% | 16.00% | 31.00% |
| Average latency | 15.48s | **13.23s** | 14.00s | 25.34s |
| Total tokens | 547475 | **152434** | 245893 | 395947 |
| Provider errors | 3 | 8 | **1** | 21 |
| Correctness excl. provider failures | 14.43% | 13.04% | **16.16%** | 13.92% |

## Does improved RAG close the full-schema gap?

**No under a 3-point parity threshold.** Improved RAG is 2.00 points ahead of full schema on correctness and 11.00 points behind it on table accuracy. It is the best overall configuration on result correctness.

## Failure analysis

| Failure class | Full schema | Top-5 RAG | Improved RAG | Planner + improved RAG |
| :--- | ---: | ---: | ---: | ---: |
| Correct | 14 | 12 | **16** | 11 |
| SQL execution error | 37 | 40 | 37 | 24 |
| SQL semantic error | 32 | 31 | 31 | 14 |
| Table selection error | 14 | 9 | 12 | 14 |
| Planning error | — | — | — | 15 |
| Provider error | 3 | 8 | 1 | 21 |

**Pre-execution validation catches (improved RAG):** malformed_sql=14 (down from 27 in v1 run), nonexistent_column=1, table_not_in_context=1. AST validation is working — the remaining gap is semantic SQL generation, not schema hallucination.

**By query type (improved RAG correctness):** single_value 21.4%, aggregation 15.0%, ranking 19.2%, time_series 11.8%, hard queries 0%.

**Planner diagnostic:** core plan correctness 42.5%; 29 cases where plan was correct but SQL result was wrong — confirms SQL generation, not planning intent, is the remaining bottleneck.

## Phase 5 recommendation

Target the measured dominant improved-RAG failure (`sql_execution_error`) with **result-level semantic verification** and **aggregate-grain checks** (e.g., detect join fan-out, wrong GROUP BY grain, off-by-one aggregations). Keep AST/schema validation and the full-schema control fixed; do not add broad retries. Phase 5 was not started.
