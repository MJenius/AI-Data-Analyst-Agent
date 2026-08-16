# Phase 5 — SQL Semantic Verification

**Date:** 2026-08-16 17:27:24 UTC  
**Run:** `run_20260816T172631Z`  
**Benchmark:** frozen 100-query V2 benchmark (`benchmark_dataset_v2.json`)  
**Method:** semantic verification applied to frozen Phase 4 improved-RAG SQL (nvidia/nemotron-3-super-120b-a12b).  No new LLM calls; latency and token totals are inherited from Phase 4.

---

## 1. Comparison Table

| Metric | Phase 4 (improved RAG) | Phase 5 (+verification) | Δ |
| :--- | :---: | :---: | :---: |
| Result correctness | 16.00% | 16.00% | **+0.00pp** |
| Result equivalence | 16.00% | 16.00% | +0.00pp |
| SQL execution success | 60.00% | 61.00% | +1.00pp |
| Table accuracy (exact match) | 49.00% | 80.00% | +31.00pp |
| Hallucinated schema | 1.00% | 4.00% | +3.00pp |
| Pre-execution blocks | — | 25.00% | — |
| Avg latency | 14.00s | 14.00s (inherited) | 0.00s |
| Total tokens | 245,893 | 245,893 (inherited) | 0 |

---

## 2. Semantic Verification Statistics

Verifier level: **BALANCED** (errors + warnings).  Verification is non-blocking: issues are flagged and logged; SQL still executes so correctness measurement is unchanged.

| Category | Count |
| :--- | :---: |
| Queries with any verification issue | 52 |
| GROUP BY mismatch | 41 |
| Aggregation grain (agg without GROUP BY) | 0 |
| Join fan-out (missing ON / equality) | 0 |
| Duplicate-row detection | 12 |
| Expected row-count mismatch | 0 |
| Metric inconsistency (NULL in aggregate) | 0 |
| Pre-execution blocks (error-severity) | 25 |
| Verification issues on **wrong** queries | 46 |
| Verification issues on **correct** queries | 6 |

**Verifier precision:** 88.5% of flagged queries were actually wrong (46/52).

---

## 3. Failure Breakdown

| Failure Category | Phase 4 | Phase 5 |
| :--- | :---: | :---: |
| correct | 16 | 16 |
| provider_error | 1 | 0 |
| sql_execution_error | 37 | 39 |
| sql_gen_hallucination | 1 | 0 |
| sql_safety_blocked | 1 | 0 |
| sql_semantic_error | 31 | 45 |
| table_selection_error | 13 | 0 |

---

## 4. Results by Query Type

| Query Type | Total | Exec | Correct | Exec% | Correct% |
| :--- | :---: | :---: | :---: | :---: | :---: |
| aggregation | 40 | 25 | 6 | 62.5% | 15.0% |
| ranking | 26 | 13 | 3 | 50.0% | 11.5% |
| single_value | 14 | 11 | 4 | 78.6% | 28.6% |
| time_series | 17 | 11 | 3 | 64.7% | 17.6% |
| unknown | 3 | 1 | 0 | 33.3% | 0.0% |

| Difficulty | Total | Exec | Correct | Exec% | Correct% |
| :--- | :---: | :---: | :---: | :---: | :---: |
| easy | 70 | 44 | 13 | 62.9% | 18.6% |
| hard | 4 | 1 | 0 | 25.0% | 0.0% |
| medium | 26 | 16 | 3 | 61.5% | 11.5% |

---

## 5. Does Semantic Verification Materially Improve Correctness?

**No material change** (+0.00pp). Semantic verification as implemented detects structural issues (GROUP BY, join fan-out) but these issues were already caught by the SQLGlot AST + schema validator in Phase 4. The remaining failures are dominated by **sql_semantic_error**.

**Why correctness is unchanged**: Phase 4's SQLGlot validator already rejects most structural SQL errors before execution (40% invalid-SQL rate in Phase 4). The semantic verifier adds value for *executable-but-wrong* SQL, but Phase 4's dominant failure modes are:

- **sql_execution_error**: 37 queries (37.0%)
- **sql_semantic_error**: 31 queries (31.0%)
- **correct**: 16 queries (16.0%)
- **table_selection_error**: 13 queries (13.0%)
- **provider_error**: 1 queries (1.0%)
- **sql_gen_hallucination**: 1 queries (1.0%)
- **sql_safety_blocked**: 1 queries (1.0%)

---

## 6. Next Bottleneck

Phase 4/5 failure analysis points to three remaining bottlenecks in order of impact:

1. **SQL execution failures** (39 queries, 39.0%): LLM generates syntactically plausible but semantically wrong column references (`unit_price`, `discount_rate`, etc.) that pass schema vocabulary checks but fail at SQLite runtime. Fix: inject explicit column-level grounding into the prompt (column names + types for every column in retrieved tables).

2. **Executable-but-wrong SQL** (45 queries, 45.0%): SQL executes, produces a result, but the result is semantically incorrect (wrong metric, wrong aggregation, wrong filter). Semantic verification flags 52 of these, but cannot fix them without LLM re-generation. Fix: feed verification issue messages back into a single targeted repair call (not a broad retry loop).

3. **Table selection errors** (see Phase 4 breakdown): RAG retrieves plausible but incorrect tables for ~51% of queries (table_match_pct = 49%). Fix: upgrade retrieval to use FK-aware graph expansion and query-type hints.

Semantic verification is a necessary but not sufficient gating layer. It correctly identifies structural defects in ~55% of wrong queries but cannot improve correctness until it is connected to an LLM repair loop.
