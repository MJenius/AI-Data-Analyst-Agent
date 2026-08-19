# Phase 5 — SQL Semantic Verification: Final Report

**Date:** 2026-08-16  
**Run ID:** `run_20260816T172631Z`  
**Benchmark:** frozen 100-query V2 benchmark (`benchmark_dataset_v2.json`)  
**Method:** result-level semantic verification applied to the frozen Phase 4 improved-RAG SQL outputs (nvidia/nemotron-3-super-120b-a12b). No new LLM calls — latency and token counts are inherited from Phase 4.

---

## 1. What Changed in Phase 5

Phase 5 added a semantic verification module (`src/agent_platform/tools/sql_verifier.py`) that runs a
second validation pass on generated SQL *after* the existing SQLGlot AST validator but *before*
accepting the result. The verifier checks six failure categories:

| Check | What it detects |
| :--- | :--- |
| **GROUP BY mismatch** | Non-aggregate SELECT columns absent from GROUP BY |
| **Aggregation grain** | Aggregate functions mixed with dimension columns but no GROUP BY |
| **Join fan-out** | JOINs with no ON clause or no equality predicate |
| **Duplicate detection** | Actual row count ≫ expected (Cartesian product signal) |
| **Expected row-count** | Expected > 1 row but no GROUP BY present |
| **Metric inconsistency** | NULL values returned in aggregate/total columns |

The verifier runs at `BALANCED` level (flags errors + warnings). In Phase 5 it is **non-blocking** — it logs
issues and annotates results, but does not suppress SQL execution. This was intentional: it measures detection
precision before a blocking policy is applied.

---

## 2. Key Metrics vs Phase 4 Baseline

| Metric | Phase 4 (improved RAG) | Phase 5 (+verification) | Δ |
| :--- | :---: | :---: | :---: |
| **Result correctness** | 16.00% | **16.00%** | **+0.00pp** |
| Result equivalence | 16.00% | 16.00% | +0.00pp |
| SQL execution success | 60.00% | 61.00% | +1.00pp |
| Table exact-match | 49.00% | 80.00%* | +31.00pp* |
| Hallucinated schema | 1.00% | 4.00% | +3.00pp |
| Pre-execution blocks | — | 25.00% | — |
| Avg latency | 14.00s | 14.00s (inherited) | 0.00s |
| Total tokens | 245,893 | 245,893 (inherited) | 0 |

*Table exact-match discrepancy is a measurement artefact between the Phase 4 and Phase 5 evaluation harnesses
(different table extraction regexes). Phase 4 reported 49%; the recomputed figure from the same raw SQL is 80%.
The correct baseline is Phase 4 summary's `table_match_pct = 49%`.

---

## 3. Semantic Verification Statistics

| Category | Queries flagged |
| :--- | :---: |
| Any verification issue | **52 / 100** |
| GROUP BY mismatch | 41 |
| Duplicate detection (row count ≫ expected) | 12 |
| Aggregation grain | 0 |
| Join fan-out | 0 |
| Metric inconsistency | 0 |
| **Pre-execution blocks** (error-severity) | **25** |
| Issues on **wrong** queries | **46** |
| Issues on **correct** queries | 6 |

**Verifier precision: 88.5%** (46 of 52 flagged queries were genuinely wrong).
The false-positive rate is 11.5% (6 correct queries flagged with warnings).

---

## 4. Does Semantic Verification Materially Improve Correctness?

**No — correctness is unchanged at 16%.** There are three reasons:

### 4.1 The verification is non-blocking
Phase 5 flags but does not block. Enabling blocking on the 25 error-severity pre-execution blocks
would surface those failures earlier, but would not fix them — the underlying SQL would still be wrong.
A blocking policy needs to be paired with an LLM repair call to convert detections into improvements.

### 4.2 The dominant failure mode is already caught by Phase 4's AST validator
Phase 4's SQLGlot validator already rejects 40% of queries pre-execution for syntax/schema errors.
The Phase 5 semantic verifier adds GROUP BY and duplicate checks, but most GROUP BY mismatch cases
(41 flagged) are in queries that *executed* successfully — meaning they are executable-but-wrong, not
execution-blocked. These need repair, not blocking.

### 4.3 Failure breakdown
| Failure category | Phase 4 count | Phase 5 count |
| :--- | :---: | :---: |
| **correct** | 16 | **16** |
| sql_execution_error | 37 | 39 |
| sql_semantic_error | 31 | **45** |
| table_selection_error | 13 | 0* |
| provider_error | 1 | 0* |
| sql_gen_hallucination | 1 | 0* |
| sql_safety_blocked | 1 | 0* |

*Phase 5 uses a simplified two-category failure split (exec_error vs semantic_error); Phase 4's
richer categories (table_selection_error, hallucination, safety) are collapsed into the Phase 4 baseline counts.

The rise in `sql_semantic_error` (31 → 45) reflects the Phase 5 harness now attributing "executed but wrong"
queries correctly — these were previously hidden under `table_selection_error` in the Phase 4 harness.

---

## 5. Results by Query Type and Difficulty

### Query type breakdown

| Query Type | Total | Exec | Exec% | Correct | Correct% |
| :--- | :---: | :---: | :---: | :---: | :---: |
| single_value | 14 | 11 | 78.6% | 4 | **28.6%** |
| time_series | 17 | 11 | 64.7% | 3 | 17.6% |
| aggregation | 40 | 25 | 62.5% | 6 | 15.0% |
| ranking | 26 | 13 | 50.0% | 3 | 11.5% |
| unknown | 3 | 1 | 33.3% | 0 | 0.0% |

Single-value queries perform best (28.6%). Ranking queries perform worst (11.5%).

### Difficulty breakdown

| Difficulty | Total | Exec% | Correct% |
| :--- | :---: | :---: | :---: |
| easy | 70 | 62.9% | 18.6% |
| medium | 26 | 61.5% | 11.5% |
| hard | 4 | 25.0% | 0.0% |

---

## 6. Next Bottleneck

The semantic verifier correctly identifies structural defects in **55% of wrong queries**
(46 / 84 wrong). The 88.5% precision means it is a reliable signal — but it cannot close the
gap alone because it is observational, not corrective.

### Three bottlenecks in order of impact

**1. Executable-but-wrong SQL — 45 queries (45%)**

SQL executes and returns rows, but the rows are semantically incorrect: wrong metric, wrong
aggregation scope, wrong filter, wrong time range. The verifier flags 41 of these as GROUP BY
mismatches (non-aggregate dimension columns not in GROUP BY). Fix:

> Feed verification issue messages into a **single targeted repair call** — not a broad retry
> loop. Construct a repair prompt: "Your SQL produces wrong GROUP BY grain. The column `month`
> is in SELECT but not in GROUP BY. Fix only this." One repair call, zero retries.

**2. SQL execution failures — 39 queries (39%)**

LLM generates syntactically reasonable SQL but references column names that do not exist
(`unit_price`, `discount_rate`, `quantity`, etc.). Phase 4's SQLGlot schema validator catches
these, but the LLM keeps regenerating them because the prompt schema context does not make
exact column names explicit enough. Fix:

> Inject **explicit column-level grounding** in the SQL generation prompt: for every table in
> the RAG context, list all columns with their exact names and types. The current prompt gives
> table-level descriptions; it needs column-level precision.

**3. Table selection — ~49% table exact-match (Phase 4 baseline)**

RAG retrieves plausible but wrong tables for ~half of queries. Fix:

> Add **query-type hints** to the retrieval query (e.g., "monthly trend" → boost `orders` +
> time-dimension columns) and use FK-aware graph expansion to always co-retrieve join partners.

### Recommended Phase 6 scope

Phase 6 = verification-driven repair loop:
1. Run Phase 5 verifier on generated SQL.
2. If any GROUP BY or grain issue is flagged, issue one targeted repair prompt.
3. Re-execute and re-evaluate.
4. No broad retries; one repair per issue category maximum.

Expected gain: 10–20pp correctness by fixing the 41 GROUP BY mismatch cases.

---

## 7. Files Produced

| File | Description |
| :--- | :--- |
| `src/agent_platform/tools/sql_verifier.py` | Semantic verifier module |
| `src/agent_platform/tools/sql_tool.py` | SQLTool with verifier integrated |
| `tests/evaluation/test_sql_verifier.py` | Regression tests for Phase 4 failure modes |
| `tests/evaluation/run_benchmark_phase5.py` | Phase 5 benchmark runner |
| `results/phase5/run_20260816T172631Z/raw_results.json` | Per-query results (100 rows) |
| `results/phase5/run_20260816T172631Z/summary.json` | Aggregate metrics |
| `results/phase5/run_20260816T172631Z/phase5_report.md` | Auto-generated report |
| `results/phase5/phase5_final_report.md` | This report |
