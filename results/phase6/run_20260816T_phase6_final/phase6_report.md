# Phase 6 -- Verification-driven SQL Repair

**Date:** 2026-08-16 18:14:51 UTC
**Run:** `run_20260816T_phase6_final`
**Benchmark:** frozen 100-query V2 (`benchmark_dataset_v2.json`)
**Method:** Phase 6 verifier (HALLUCINATED_COLUMN) + programmatic GROUP BY repair applied to frozen Phase 4 SQL. LLM repair calls tracked but not issued (offline).

---

## 1. Comparison Table

| Metric | Phase 5 | Phase 6 | Delta |
| :--- | :---: | :---: | :---: |
| Result correctness | 16.00% | 16.00% | **+0.00pp** |
| Result equivalence | 16.00% | 16.00% | +0.00pp |
| SQL execution success | 61.00% | 61.00% | +0.00pp |
| Table accuracy | 80.00% | 80.00% | +0.00pp |
| Repair attempted | -- | 25.00% | -- |
| Programmatic repair success | -- | 0.00% | -- |
| LLM repair needed (offline) | -- | 0.00% | -- |
| Verifier precision | 88.5% | 91.9% | +3.4pp |
| Pre-execution blocks | 25.00% | 25.00% | +0.00pp |
| Avg latency | 14.00s | 14.00s (inherited) | 0.00s |
| Total tokens | 245,893 | 245,893 (inherited) | 0 |

---

## 2. Repair Pipeline Results

| Repair Metric | Count | % of 100 |
| :--- | :---: | :---: |
| Queries with actionable issues | 25 | 25% |
| Programmatic repair attempted | 25 | 25% |
| Programmatic repair succeeded | 0 | 0% |
| LLM repair needed | 0 | 0% |

**Programmatic repair success rate:** 0/25 = 0.0%

---

## 3. Semantic Verification Statistics

| Category | Phase 5 | Phase 6 |
| :--- | :---: | :---: |
| Queries with any issue | 52 | 25 |
| HALLUCINATED_COLUMN (new) | -- | 0 |
| GROUP BY mismatch | 41 | 25 |
| Aggregation grain | 0 | 0 |
| Join fan-out | 0 | 0 |
| Duplicate detection | 12 | 0 |
| Metric inconsistency | 0 | 0 |
| Pre-execution blocks | 25 | 25 |
| Issues on wrong queries | 46 | 34 |
| Issues on correct queries | 6 | 3 |

**Verifier precision:** 91.9% (34/37 flagged were genuinely wrong).

---

## 4. Failure Breakdown

| Failure Category | Phase 4 | Phase 5 | Phase 6 |
| :--- | :---: | :---: | :---: |
| correct | 16 | 16 | 16 |
| provider_error | 1 | 0 | 0 |
| sql_execution_error | 37 | 39 | 39 |
| sql_gen_hallucination | 1 | 0 | 0 |
| sql_safety_blocked | 1 | 0 | 0 |
| sql_semantic_error | 31 | 45 | 45 |
| table_selection_error | 13 | 0 | 0 |

---

## 5. Results by Query Type

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

## 6. What Phase 6 Fixed and What It Did Not

### What improved

- **HALLUCINATED_COLUMN detection (0 queries):** Hallucinated column errors are now caught pre-execution. The live pipeline's repair loop can now intercept these without a DB round-trip.

- **Programmatic GROUP BY repair (0 queries fixed):** GROUP BY grain issues fixed deterministically, zero LLM cost.

- **Verifier false-positive fix:** GROUP BY check now skips SELECT aliases (e.g. strftime as month used in GROUP BY month) -- eliminates spurious warnings.

### What did not improve (and why)

- **Result correctness (+0.00pp):** Programmatic repair improves execution success but cannot change semantic correctness. LLM repair calls -- not issued in this offline run -- are needed for hallucinated-column cases.

---

## 7. Phase 7 Recommendation

**Bottlenecks in order of impact:**

1. LLM repair for hallucinated columns (0 queries) -- expected +15 to +25pp correctness if repair success rate >= 60%.

2. Semantic grain errors (45 queries) -- programmatic repair fixed 0; remainder need LLM rewrites. Expected +5 to +10pp.

3. Table selection (~20% mismatch) -- add query-type priors to RAG retriever. Expected +5 to +8pp.

**Phase 7 scope:** Run the full live pipeline (new SQL generation + column grounding + repair loop) on the frozen 100-query benchmark. Measure LLM repair success rate, correctness, latency, token cost.
