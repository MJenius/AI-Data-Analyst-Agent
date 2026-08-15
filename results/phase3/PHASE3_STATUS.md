# Phase 3 status — controlled experiment not complete

## Completed engineering work

- Five controlled configurations are implemented in
  `tests/evaluation/phase3/`.
- Configurations 4 and 5 emit and evaluate a structured `QueryPlan` with
  intent, metric, entity, aggregation, filters, grouping, ordering, limit, and
  required tables.
- Each execution writes immutable per-run configuration, raw results, summaries,
  report, and provider status artifacts below this directory.
- Provider failures stop a configuration after three consecutive failures and
  are labelled `not_run_provider_unavailable`, rather than being counted as SQL
  or semantic failures.

## Live controlled run

`run_20260815T_phase3_full_e` attempted the requested five-way 100-query run.
It was stopped after repeated Groq HTTP 429 responses while Config 1 was still
in progress. The run did not reach any other configuration and is **NOT RUN**
for comparison purposes. See its `NOT_RUN.md` and adjacent stderr log.

## Available 100-query baseline evidence

The pre-existing V3 baseline is a complete 100-query current-system evaluation
at `results/v3_benchmark/`. It is useful only as a baseline observation, not as
a controlled comparison with configurations 2–5.

| Configuration | Queries | Correct | Equivalent | Table accuracy | SQL execution | Invalid SQL | Mean latency |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Current system (existing V3 baseline) | 100 | 1.0% | 1.0% | 86.0% | 100.0% | 0.0% | 7.09 s |
| LLM + full schema | NOT RUN | — | — | — | — | — | — |
| LLM + RAG | NOT RUN | — | — | — | — | — | — |
| Planner + RAG + SQL | NOT RUN | — | — | — | — | — | — |
| Planner + RAG + SQL + execution feedback | NOT RUN | — | — | — | — | — | — |

### Current-system baseline by query type

| Type | Queries | Correct | SQL execution |
| :--- | ---: | ---: | ---: |
| aggregation | 40 | 0 | 40 |
| ranking | 26 | 0 | 26 |
| single value | 14 | 1 | 14 |
| time series | 17 | 0 | 17 |
| unknown | 3 | 0 | 3 |

### Current-system baseline by difficulty

| Difficulty | Queries | Correct | SQL execution |
| :--- | ---: | ---: | ---: |
| easy | 70 | 1 | 70 |
| medium | 26 | 0 | 26 |
| hard | 4 | 0 | 4 |

### Baseline failure evidence

The frequent result-comparison failures were `ranking_mismatch` (24),
`column_mismatch` (13), and row-count mismatches (for example, 12 cases with
10 rows returned where one was expected). Because all 100 generated SQL
statements executed, this is preliminary evidence of an answer-shape/semantic
SQL-generation failure after mostly successful table selection—not evidence
that retrieval alone is the primary bottleneck. A completed controlled run is
required before attributing the failure to planning, RAG, or repair.

## Recommendation for Phase 4

Restore a provider quota that can complete the frozen experiment with one fixed
model, then re-run the immutable Phase 3 command. Do not change prompts,
retrieval parameters, repair policy, benchmark, or database between the five
configurations. Only after the plan-versus-SQL outcome matrix is complete should
Phase 4 target the dominant measured failure mode.
