# Phase 7 Live Benchmark Report

**Date:** 2026-08-17T16:55:22.146567
**Run:** `live_20260817T145542`
**Benchmark:** frozen 100-query V2 (`benchmark_dataset_v2.json`)
**Method:** Live current pipeline (column grounding + SQLGlot + semantic verification + targeted repair).

---

## 1. Summary Metrics

| Metric | Value |
| :--- | :---: |
| Result correctness | 10.00% |
| Exact match rate | 10.00% |
| Equivalent match rate | 10.00% |
| SQL execution success | 100.00% |
| Table accuracy | 61.00% |
| Table precision | 85.58% |
| Table recall | 95.00% |
| Repair attempted | 1.00% |
| Repair success rate | 100.00% |
| Truncation detected | 0 |
| Invalid SQL | 0 |
| Hallucinated tables | 17 |
| Hallucinated columns | 0 |
| Unsafe SQL | 0 |
| Verifier flagged | 1 |
| Verifier errors | 0 |
| Mean latency | 71.18s |
| P50 latency | 65.39s |
| P95 latency | 123.07s |
| Total elapsed | 7170.76s |

---

## 2. Per-Query Results

| # | Domain | Query Type | Difficulty | Exec | Correct | Tables | Repair | Failure |
| :--- | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| q000 | Revenue & Sales | single_value | easy | Y | Y | 100% | N | None |
| q001 | Revenue & Sales | time_series | medium | Y | N | 100% | N | SQL generation |
| q002 | Revenue & Sales | single_value | easy | Y | N | 100% | N | SQL generation |
| q003 | Revenue & Sales | single_value | easy | Y | N | 100% | N | SQL generation |
| q004 | Revenue & Sales | single_value | easy | Y | Y | 100% | N | None |
| q005 | Revenue & Sales | unknown | easy | Y | N | 100% | N | column hallucination |
| q006 | Revenue & Sales | aggregation | medium | Y | N | 67% | N | schema retrieval |
| q007 | Revenue & Sales | ranking | easy | Y | N | 100% | N | schema retrieval |
| q008 | Revenue & Sales | time_series | medium | Y | N | 100% | N | schema retrieval |
| q009 | Revenue & Sales | time_series | easy | Y | N | 100% | N | column hallucination |
| q010 | Revenue & Sales | time_series | easy | Y | N | 100% | Y | grouping |
| q011 | Revenue & Sales | single_value | easy | Y | N | 100% | N | SQL generation |
| q012 | Revenue & Sales | single_value | easy | Y | N | 33% | N | schema retrieval |
| q013 | Revenue & Sales | aggregation | medium | Y | N | 67% | N | schema retrieval |
| q014 | Revenue & Sales | aggregation | easy | Y | N | 50% | N | schema retrieval |
| q015 | Orders & Transaction | aggregation | easy | Y | Y | 100% | N | None |
| q016 | Orders & Transaction | aggregation | easy | Y | Y | 100% | N | None |
| q017 | Orders & Transaction | aggregation | easy | Y | Y | 100% | N | None |
| q018 | Orders & Transaction | time_series | medium | Y | N | 100% | N | SQL generation |
| q019 | Orders & Transaction | aggregation | easy | Y | N | 100% | N | SQL generation |
| q020 | Orders & Transaction | single_value | easy | Y | N | 100% | N | SQL generation |
| q021 | Orders & Transaction | single_value | easy | Y | N | 100% | N | SQL generation |
| q022 | Orders & Transaction | single_value | easy | Y | N | 100% | N | SQL generation |
| q023 | Orders & Transaction | aggregation | easy | Y | N | 100% | N | SQL generation |
| q024 | Orders & Transaction | time_series | medium | Y | N | 100% | N | SQL generation |
| q025 | Orders & Transaction | single_value | easy | Y | N | 100% | N | SQL generation |
| q026 | Orders & Transaction | single_value | easy | Y | N | 100% | N | SQL generation |
| q027 | Orders & Transaction | aggregation | easy | Y | N | 50% | N | column hallucination |
| q028 | Orders & Transaction | single_value | easy | Y | N | 50% | N | schema retrieval |
| q029 | Orders & Transaction | aggregation | easy | Y | N | 100% | N | SQL generation |
| q030 | Customers | aggregation | easy | Y | N | 100% | N | SQL generation |
| q031 | Customers | aggregation | easy | Y | N | 50% | N | column hallucination |
| q032 | Customers | time_series | hard | Y | N | 50% | N | column hallucination |
| q033 | Customers | time_series | hard | Y | N | 50% | N | column hallucination |
| q034 | Customers | aggregation | easy | Y | N | 50% | N | column hallucination |
| q035 | Customers | aggregation | easy | Y | N | 50% | N | column hallucination |
| q036 | Customers | ranking | easy | Y | Y | 100% | N | None |
| q037 | Customers | time_series | medium | Y | Y | 100% | N | None |
| q038 | Customers | aggregation | medium | Y | N | 67% | N | column hallucination |
| q039 | Customers | ranking | medium | Y | N | 67% | N | schema retrieval |
| q040 | Customers | aggregation | medium | Y | N | 50% | N | schema retrieval |
| q041 | Customers | aggregation | easy | Y | N | 50% | N | column hallucination |
| q042 | Customers | aggregation | easy | Y | N | 100% | N | column hallucination |
| q043 | Customers | aggregation | easy | Y | N | 50% | N | column hallucination |
| q044 | Customers | time_series | medium | Y | N | 33% | N | schema retrieval |
| q045 | Products & Categorie | ranking | easy | Y | N | 100% | N | SQL generation |
| q046 | Products & Categorie | ranking | easy | Y | N | 67% | N | schema retrieval |
| q047 | Products & Categorie | aggregation | easy | Y | N | 67% | N | schema retrieval |
| q048 | Products & Categorie | ranking | easy | Y | N | 33% | N | schema retrieval |
| q049 | Products & Categorie | ranking | easy | Y | N | 100% | N | SQL generation |
| q050 | Products & Categorie | time_series | medium | Y | N | 100% | N | SQL generation |
| q051 | Products & Categorie | ranking | easy | Y | N | 100% | N | SQL generation |
| q052 | Products & Categorie | ranking | medium | Y | N | 100% | N | schema retrieval |
| q053 | Products & Categorie | ranking | medium | Y | N | 100% | N | SQL generation |
| q054 | Products & Categorie | aggregation | easy | Y | N | 50% | N | schema retrieval |
| q055 | Products & Categorie | ranking | hard | Y | N | 33% | N | schema retrieval |
| q056 | Products & Categorie | ranking | easy | Y | N | 100% | N | SQL generation |
| q057 | Products & Categorie | ranking | easy | Y | N | 100% | N | SQL generation |
| q058 | Products & Categorie | aggregation | easy | Y | N | 33% | N | schema retrieval |
| q059 | Products & Categorie | aggregation | hard | Y | N | 100% | N | SQL generation |
| q060 | Logistics & Delivery | aggregation | easy | Y | N | 100% | N | SQL generation |
| q061 | Logistics & Delivery | aggregation | easy | Y | N | 100% | N | SQL generation |
| q062 | Logistics & Delivery | ranking | easy | Y | N | 100% | N | SQL generation |
| q063 | Logistics & Delivery | ranking | medium | Y | N | 67% | N | column hallucination |
| q064 | Logistics & Delivery | aggregation | easy | Y | N | 100% | N | SQL generation |
| q065 | Logistics & Delivery | time_series | medium | Y | N | 100% | N | SQL generation |
| q066 | Logistics & Delivery | aggregation | medium | Y | N | 100% | N | schema retrieval |
| q067 | Logistics & Delivery | aggregation | easy | Y | N | 100% | N | SQL generation |
| q068 | Logistics & Delivery | time_series | medium | Y | N | 100% | N | column hallucination |
| q069 | Logistics & Delivery | unknown | easy | Y | N | 100% | N | SQL generation |
| q070 | Sellers | aggregation | easy | Y | N | 100% | N | SQL generation |
| q071 | Sellers | ranking | easy | Y | N | 100% | N | SQL generation |
| q072 | Sellers | ranking | easy | Y | N | 33% | N | schema retrieval |
| q073 | Sellers | aggregation | easy | Y | Y | 50% | N | None |
| q074 | Sellers | ranking | easy | Y | N | 100% | N | SQL generation |
| q075 | Sellers | ranking | easy | Y | N | 100% | N | schema retrieval |
| q076 | Sellers | time_series | medium | Y | Y | 100% | N | None |
| q077 | Sellers | ranking | easy | Y | N | 100% | N | schema retrieval |
| q078 | Sellers | aggregation | easy | Y | N | 67% | N | column hallucination |
| q079 | Sellers | ranking | easy | Y | N | 100% | N | schema retrieval |
| q080 | Payments | single_value | easy | Y | N | 100% | N | SQL generation |
| q081 | Payments | aggregation | easy | Y | N | 100% | N | SQL generation |
| q082 | Payments | aggregation | easy | Y | Y | 100% | N | None |
| q083 | Payments | aggregation | easy | Y | N | 100% | N | SQL generation |
| q084 | Payments | time_series | medium | Y | N | 100% | N | SQL generation |
| q085 | Payments | unknown | easy | Y | N | 100% | N | SQL generation |
| q086 | Payments | single_value | easy | Y | N | 100% | N | SQL generation |
| q087 | Payments | ranking | easy | Y | N | 100% | N | SQL generation |
| q088 | Payments | aggregation | medium | Y | N | 100% | N | SQL generation |
| q089 | Payments | aggregation | medium | Y | N | 100% | N | SQL generation |
| q090 | Reviews & Satisfacti | aggregation | easy | Y | N | 100% | N | SQL generation |
| q091 | Reviews & Satisfacti | time_series | medium | Y | N | 100% | N | SQL generation |
| q092 | Reviews & Satisfacti | ranking | easy | Y | N | 50% | N | column hallucination |
| q093 | Reviews & Satisfacti | ranking | easy | Y | N | 100% | N | schema retrieval |
| q094 | Reviews & Satisfacti | aggregation | easy | Y | N | 100% | N | SQL generation |
| q095 | Reviews & Satisfacti | aggregation | easy | Y | N | 100% | N | column hallucination |
| q096 | Reviews & Satisfacti | aggregation | easy | Y | N | 100% | N | SQL generation |
| q097 | Reviews & Satisfacti | time_series | medium | Y | N | 50% | N | schema retrieval |
| q098 | Reviews & Satisfacti | ranking | medium | Y | N | 75% | N | schema retrieval |
| q099 | Reviews & Satisfacti | ranking | medium | Y | N | 100% | N | schema retrieval |

---

## 3. Failure Breakdown

| Failure Cause | Count | Rate |
| :--- | :---: | :---: |
| SQL generation | 46 | 46.0% |
| schema retrieval | 26 | 26.0% |
| column hallucination | 17 | 17.0% |
| grouping | 1 | 1.0% |

---

## 4. Latency Distribution

- Mean: 71.18s
- P50: 65.39s
- P95: 123.07s

---

*Generated by Phase 7 Live Benchmark Runner*
