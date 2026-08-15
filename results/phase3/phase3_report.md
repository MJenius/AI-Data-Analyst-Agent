# Phase 3 — NL-to-SQL Semantic Failure Diagnosis

**Date:** 2026-08-15 18:13:53

**Method:** Controlled ablation on the verified 100-query V3 benchmark (benchmark_dataset_v2.json). LLM: Groq `llama-3.1-8b-instant` (the configured `llama-3.3-70b-versatile` hit its daily token quota during pre-flight; Gemini key was rejected by the API). Config 1 runs the production pipeline untouched; configs 2-5 use a shared harness with lenient JSON parsing so the LLM's SQL output is actually exercised.

## 1. Comparison Table

| Metric | config1_current_system | config2_llm_full_schema | config3_llm_rag | config4_plan_rag_sql | config5_plan_rag_sql_feedback |
| :--- | :---: | :---: | :---: | :---: | :---: |
| Result correctness | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| Result equivalence | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| Table accuracy | 100.0% | 83.3% | 100.0% | 100.0% | 100.0% |
| SQL execution success | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| Invalid SQL | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| Latency (s) | 0.00s | 0.00s | 0.00s | 0.00s | 0.00s |
| Hallucinated schema | 0.0% | 66.7% | 0.0% | 66.7% | 66.7% |
| Table match (exact) | 100.0% | 66.7% | 100.0% | 100.0% | 100.0% |


## 2. Results by Query Type / Difficulty

### config1_current_system: Current system (planner + RAG + SQL gen + exec feedback + evaluator)

| Query Type | Total | Correct | % | Exec % |
| :--- | :---: | :---: | :---: | :---: |
| single_value | 2 | 0 | 0.0 | 100.0 |
| time_series | 1 | 0 | 0.0 | 100.0 |

| Difficulty | Total | Correct | % | Exec % |
| :--- | :---: | :---: | :---: | :---: |
| easy | 2 | 0 | 0.0 | 100.0 |
| medium | 1 | 0 | 0.0 | 100.0 |


### config2_llm_full_schema: LLM + full schema context (no RAG, no planner)

| Query Type | Total | Correct | % | Exec % |
| :--- | :---: | :---: | :---: | :---: |
| single_value | 2 | 1 | 50.0 | 50.0 |
| time_series | 1 | 0 | 0.0 | 0.0 |

| Difficulty | Total | Correct | % | Exec % |
| :--- | :---: | :---: | :---: | :---: |
| easy | 2 | 1 | 50.0 | 50.0 |
| medium | 1 | 0 | 0.0 | 0.0 |


### config3_llm_rag: LLM + RAG (no planner)

| Query Type | Total | Correct | % | Exec % |
| :--- | :---: | :---: | :---: | :---: |
| single_value | 2 | 0 | 0.0 | 0.0 |
| time_series | 1 | 0 | 0.0 | 0.0 |

| Difficulty | Total | Correct | % | Exec % |
| :--- | :---: | :---: | :---: | :---: |
| easy | 2 | 0 | 0.0 | 0.0 |
| medium | 1 | 0 | 0.0 | 0.0 |


### config4_plan_rag_sql: Planner + RAG + SQL generation (no exec feedback)

| Query Type | Total | Correct | % | Exec % |
| :--- | :---: | :---: | :---: | :---: |
| single_value | 2 | 0 | 0.0 | 0.0 |
| time_series | 1 | 0 | 0.0 | 0.0 |

| Difficulty | Total | Correct | % | Exec % |
| :--- | :---: | :---: | :---: | :---: |
| easy | 2 | 0 | 0.0 | 0.0 |
| medium | 1 | 0 | 0.0 | 0.0 |


### config5_plan_rag_sql_feedback: Planner + RAG + SQL generation + execution feedback

| Query Type | Total | Correct | % | Exec % |
| :--- | :---: | :---: | :---: | :---: |
| single_value | 2 | 0 | 0.0 | 0.0 |
| time_series | 1 | 0 | 0.0 | 0.0 |

| Difficulty | Total | Correct | % | Exec % |
| :--- | :---: | :---: | :---: | :---: |
| easy | 2 | 0 | 0.0 | 0.0 |
| medium | 1 | 0 | 0.0 | 0.0 |


## 3. Failure Breakdown

| Failure category | config1_current_system | config2_llm_full_schema | config3_llm_rag | config4_plan_rag_sql | config5_plan_rag_sql_feedback |
| :--- | :---: | :---: | :---: | :---: | :---: |
| correct | 0 | 1 | 0 | 0 | 0 |
| sql_execution_error | 0 | 0 | 3 | 1 | 1 |
| sql_gen_hallucination | 0 | 2 | 0 | 2 | 2 |
| sql_semantic_error | 3 | 0 | 0 | 0 | 0 |


## 4. Structured Query Plan Correctness (Configs 4 & 5)

### config4_plan_rag_sql

| Plan component | Correct % |
| :--- | :---: |
| Plan core (tables+metric+agg+group_by) | 0 |
| Plan full (all components) | 0 |
| Intent | 66.67 |
| Metric | 66.67 |
| Aggregation | 66.67 |
| Group by | 100.0 |
| Ordering | 100.0 |
| Limit | 66.67 |
| Filters | 33.33 |
| Required tables | 100.0 |

Plan vs outcome:
- Plan correct, result correct: **0**
- Plan correct, result WRONG: **1** (SQL generation bottleneck)
- Plan wrong, result wrong: **2** (planning/intent bottleneck)

Plan correctness by query type:

| Query Type | Total | Plan core OK | Metric OK | Tables OK | Agg OK |
| :--- | :---: | :---: | :---: | :---: | :---: |
| single_value | 2 | 0 | 1 | 2 | 1 |
| time_series | 1 | 1 | 1 | 1 | 1 |


### config5_plan_rag_sql_feedback

| Plan component | Correct % |
| :--- | :---: |
| Plan core (tables+metric+agg+group_by) | 0 |
| Plan full (all components) | 0 |
| Intent | 66.67 |
| Metric | 66.67 |
| Aggregation | 66.67 |
| Group by | 100.0 |
| Ordering | 100.0 |
| Limit | 100.0 |
| Filters | 33.33 |
| Required tables | 100.0 |

Plan vs outcome:
- Plan correct, result correct: **0**
- Plan correct, result WRONG: **1** (SQL generation bottleneck)
- Plan wrong, result wrong: **2** (planning/intent bottleneck)

Plan correctness by query type:

| Query Type | Total | Plan core OK | Metric OK | Tables OK | Agg OK |
| :--- | :---: | :---: | :---: | :---: | :---: |
| single_value | 2 | 0 | 1 | 2 | 1 |
| time_series | 1 | 1 | 1 | 1 | 1 |


## 5. Ablation Deltas (bottleneck evidence)

| Delta | Meaning | Value (pp) |
| :--- | :--- | :---: |
| C3 - C2 | Effect of RAG over full schema (no planner) | +33.3 |
| C4 - C3 | Effect of structured planner (RAG held) | -33.3 |
| C5 - C4 | Effect of execution feedback / repair | +0.0 |
| C1 - C5 | Production pipeline vs experimental (strict validation, prose planner, evaluator) | +0.0 |


## 6. Methodology Notes

- Result correctness: query-type-aware comparison of generated result vs gold `expected_result`.
- Result equivalence: generated result vs independently executed gold SQL result.
- Table accuracy: fraction of `expected_tables` present in generated SQL (avg over queries).
- Invalid SQL: generated SQL that fails to execute (syntax / unknown column / unknown table).
- Config 1 `generated_sql` is the first executed SQL statement from `sql_queries` (same extraction as the V3 harness).