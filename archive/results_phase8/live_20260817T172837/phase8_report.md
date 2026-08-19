# Phase 8 Live Benchmark Report

**Date:** 2026-08-17T19:59:56.584460
**Run:** `live_20260817T172837`
**Benchmark:** frozen 100-query V2 (`benchmark_dataset_v2.json`)
**Method:** Live current pipeline (column grounding + SQLGlot + QueryPlan-aligned semantic verification + one targeted repair).

---

## 1. Summary Metrics

| Metric | Value |
| :--- | :---: |
| Result correctness | 10.00% |
| Exact match rate | 10.00% |
| Equivalent match rate | 10.00% |
| SQL execution success | 100.00% |
| Table accuracy | 53.00% |
| Table precision | 83.83% |
| Table recall | 92.50% |
| Invalid SQL | 0 |
| Hallucinated tables | 18 |
| Hallucinated columns | 0 |
| Unsafe SQL | 0 |
| Plan available | 100.0% (100/100) |

### Detection

| Metric | Value |
| :--- | :---: |
| Semantic detection rate (of incorrect, executable) | 48.89% |
| Detection precision | 97.78% |
| Detected mismatches | 44 / 90 |
| Flagged queries | 45 |
| Correct-but-flagged (flag FP rate) | 1 (2.22%) |

### Repair

| Metric | Value |
| :--- | :---: |
| Repair attempted | 46 (46.00%) |
| Repair applied | 30 (30.00%) |
| Repair success rate (applied & previously wrong) | 0.00% |
| Repaired-to-correct | 0 |
| False-positive repairs | 2 (6.67%) |
| Programmatic repairs | 6 |
| LLM repairs | 27 |

### Repair categories

| Category | Count |
| :--- | :---: |
| join_path_mismatch | 17 |
| metric_mismatch | 14 |
| group_by_grain_mismatch | 5 |
| ranking_mismatch | 4 |
| entity_mismatch | 4 |
| time_grain_mismatch | 3 |
| group_by_mismatch | 2 |
| filter_mismatch | 1 |

### Latency / Cost

| Metric | Value |
| :--- | :---: |
| Mean latency | 89.73s |
| P50 latency | 80.36s |
| P95 latency | 166.67s |
| Total elapsed | 9066.38s |
| Prompt tokens | 1301248 |
| Completion tokens | 287689 |
| Total tokens | 1588937 |

---

## 2. Per-Query Results

| # | Type | Exec | Correct | Detected | Repair | Pre-correct | Post-correct | Failure |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| q000 | single_value | Y | Y | - | - | - | - | None |
| q001 | time_series | Y | Y | - | - | - | - | None |
| q002 | single_value | Y | N | - | - | - | - | SQL generation |
| q003 | single_value | Y | N | - | Y | N | N | SQL generation |
| q004 | single_value | Y | Y | - | Y | Y | Y | None |
| q005 | unknown | Y | N | Y | Y | N | N | join_path_mismatch |
| q006 | aggregation | Y | N | - | T | - | - | column hallucination |
| q007 | ranking | Y | N | - | Y | N | N | schema retrieval |
| q008 | time_series | Y | N | - | Y | N | N | schema retrieval |
| q009 | time_series | Y | N | Y | - | - | - | join_path_mismatch |
| q010 | time_series | Y | N | Y | T | - | - | column hallucination |
| q011 | single_value | Y | N | - | Y | N | N | column hallucination |
| q012 | single_value | Y | Y | Y | T | - | - | None |
| q013 | aggregation | Y | N | Y | - | - | - | column hallucination |
| q014 | aggregation | Y | N | Y | - | - | - | join fan-out |
| q015 | aggregation | Y | Y | - | - | - | - | None |
| q016 | aggregation | Y | Y | - | Y | Y | Y | None |
| q017 | aggregation | Y | N | - | T | - | - | schema retrieval |
| q018 | time_series | Y | N | Y | - | - | - | join fan-out |
| q019 | aggregation | Y | N | Y | Y | N | N | join fan-out |
| q020 | single_value | Y | N | - | - | - | - | SQL generation |
| q021 | single_value | Y | N | - | - | - | - | SQL generation |
| q022 | single_value | Y | N | - | - | - | - | SQL generation |
| q023 | aggregation | Y | N | Y | Y | N | N | join_path_mismatch |
| q024 | time_series | Y | N | - | Y | N | N | SQL generation |
| q025 | single_value | Y | N | Y | T | - | - | join fan-out |
| q026 | single_value | Y | N | - | Y | N | N | SQL generation |
| q027 | aggregation | Y | N | - | - | - | - | column hallucination |
| q028 | single_value | Y | N | - | - | - | - | column hallucination |
| q029 | aggregation | Y | N | - | - | - | - | SQL generation |
| q030 | aggregation | Y | N | - | - | - | - | SQL generation |
| q031 | aggregation | Y | N | - | - | - | - | column hallucination |
| q032 | time_series | Y | N | Y | - | - | - | column hallucination |
| q033 | time_series | Y | N | Y | T | - | - | column hallucination |
| q034 | aggregation | Y | N | Y | - | - | - | column hallucination |
| q035 | aggregation | Y | N | - | - | - | - | column hallucination |
| q036 | ranking | Y | N | - | - | - | - | SQL generation |
| q037 | time_series | Y | Y | - | - | - | - | None |
| q038 | aggregation | Y | N | - | - | - | - | column hallucination |
| q039 | ranking | Y | N | - | - | - | - | schema retrieval |
| q040 | aggregation | Y | N | - | - | - | - | schema retrieval |
| q041 | aggregation | Y | N | - | - | - | - | column hallucination |
| q042 | aggregation | Y | N | - | - | - | - | column hallucination |
| q043 | aggregation | Y | N | - | - | - | - | column hallucination |
| q044 | time_series | Y | N | Y | Y | N | N | column hallucination |
| q045 | ranking | Y | N | Y | - | - | - | join fan-out |
| q046 | ranking | Y | N | Y | - | - | - | join fan-out |
| q047 | aggregation | Y | N | Y | - | - | - | join fan-out |
| q048 | ranking | Y | N | Y | - | - | - | join fan-out |
| q049 | ranking | Y | N | Y | - | - | - | join fan-out |
| q050 | time_series | Y | N | Y | - | - | - | join_path_mismatch |
| q051 | ranking | Y | N | Y | Y | N | N | join fan-out |
| q052 | ranking | Y | N | Y | T | - | - | entity_mismatch |
| q053 | ranking | Y | N | Y | T | - | - | join_path_mismatch |
| q054 | aggregation | Y | N | Y | Y | N | N | join fan-out |
| q055 | ranking | Y | N | - | Y | N | N | SQL generation |
| q056 | ranking | Y | N | Y | - | - | - | join fan-out |
| q057 | ranking | Y | N | Y | Y | N | N | join fan-out |
| q058 | aggregation | Y | N | Y | - | - | - | join fan-out |
| q059 | aggregation | Y | N | Y | Y | N | N | join fan-out |
| q060 | aggregation | Y | N | - | - | - | - | SQL generation |
| q061 | aggregation | Y | N | - | - | - | - | SQL generation |
| q062 | ranking | Y | N | Y | - | - | - | column hallucination |
| q063 | ranking | Y | N | Y | T | - | - | join_path_mismatch |
| q064 | aggregation | Y | N | - | - | - | - | SQL generation |
| q065 | time_series | Y | N | - | - | - | - | SQL generation |
| q066 | aggregation | Y | N | Y | T | - | - | join fan-out |
| q067 | aggregation | Y | N | - | Y | N | N | SQL generation |
| q068 | time_series | Y | N | Y | T | - | - | join fan-out |
| q069 | unknown | Y | N | - | - | - | - | SQL generation |
| q070 | aggregation | Y | N | - | Y | N | N | SQL generation |
| q071 | ranking | Y | N | Y | - | - | - | join fan-out |
| q072 | ranking | Y | N | Y | - | - | - | join fan-out |
| q073 | aggregation | Y | Y | - | - | - | - | None |
| q074 | ranking | Y | N | Y | Y | N | N | join_path_mismatch |
| q075 | ranking | Y | N | Y | Y | N | N | join_path_mismatch |
| q076 | time_series | Y | Y | - | - | - | - | None |
| q077 | ranking | Y | N | Y | - | - | - | join_path_mismatch |
| q078 | aggregation | Y | N | Y | T | - | - | join_path_mismatch |
| q079 | ranking | Y | N | Y | T | - | - | join_path_mismatch |
| q080 | single_value | Y | N | - | - | - | - | SQL generation |
| q081 | aggregation | Y | N | Y | T | - | - | join_path_mismatch |
| q082 | aggregation | Y | Y | - | - | - | - | None |
| q083 | aggregation | Y | N | - | Y | N | N | SQL generation |
| q084 | time_series | Y | N | - | Y | N | N | SQL generation |
| q085 | unknown | Y | N | Y | T | - | - | join fan-out |
| q086 | single_value | Y | N | - | - | - | - | SQL generation |
| q087 | ranking | Y | N | - | Y | N | N | schema retrieval |
| q088 | aggregation | Y | N | - | Y | N | N | SQL generation |
| q089 | aggregation | Y | N | - | Y | N | N | SQL generation |
| q090 | aggregation | Y | N | - | - | - | - | SQL generation |
| q091 | time_series | Y | N | - | - | - | - | SQL generation |
| q092 | ranking | Y | N | Y | Y | N | N | join fan-out |
| q093 | ranking | Y | N | - | Y | N | N | schema retrieval |
| q094 | aggregation | Y | N | Y | T | - | - | join fan-out |
| q095 | aggregation | Y | N | - | - | - | - | SQL generation |
| q096 | aggregation | Y | N | - | - | - | - | SQL generation |
| q097 | time_series | Y | N | - | - | - | - | schema retrieval |
| q098 | ranking | Y | N | Y | Y | N | N | join_path_mismatch |
| q099 | ranking | Y | N | Y | Y | N | N | join_path_mismatch |

---

## 3. Failure Breakdown

| Failure Cause | Count | Rate |
| :--- | :---: | :---: |
| SQL generation | 28 | 28.0% |
| join fan-out | 22 | 22.0% |
| column hallucination | 17 | 17.0% |
| join_path_mismatch | 14 | 14.0% |
| schema retrieval | 8 | 8.0% |
| entity_mismatch | 1 | 1.0% |

---

## 4. Latency Distribution

- Mean: 89.73s
- P50: 80.36s
- P95: 166.67s

---

*Generated by Phase 8 Live Benchmark Runner*
