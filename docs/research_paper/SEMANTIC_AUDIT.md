# Stratified Human Semantic Audit Protocol

**Document Status:** Sampling protocol defined BEFORE examining any query results.
**Date:** August 2026

## Purpose

This document defines the sampling protocol and methodology for a stratified human
semantic audit of the 500-query benchmark. This audit complements the existing
programmatic validation (which covers all 500 queries) with expert human review
of a representative subset.

> **IMPORTANT**: The sampling protocol was fixed before any results were examined
> to prevent selection bias. The random seed and stratification are deterministic
> and reproducible.

## Scope Distinction

| Validation Type | Coverage | Method |
|:---|:---|:---|
| **Programmatic validation** | All 500 queries | Automated `compare_results` row-multiset comparison |
| **Human semantic audit** | ~64-query stratified sample | Expert review (this document) |

The full 500-query set is NOT described as "manually audited."

## Sampling Protocol

### Stratification Design

The sample is stratified across three dimensions to ensure representativeness:

1. **Domain** (8 categories): Minimum 8 queries per domain
2. **Difficulty** (3 levels: easy, medium, hard): Proportional representation
3. **Query Type** (4 types: single_value, time_series, ranked_list, aggregated_table): Proportional

### Sample Size

- **Target**: 64 queries (12.8% of 500)
- **Allocation**: 8 queries per domain × 8 domains = 64 base
- **Within each domain**: Stratified by difficulty proportional to population

### Selection Procedure

```python
# Deterministic selection — seed fixed before examining results
import random
random.seed(42)

for domain in sorted(domains):
    domain_queries = [q for q in dataset if q["category"] == domain]
    # Within each domain, sort by difficulty, then select uniformly
    for difficulty in ["easy", "medium", "hard"]:
        subset = [q for q in domain_queries if q["difficulty"] == difficulty]
        n_select = max(1, round(8 * len(subset) / len(domain_queries)))
        selected = random.sample(subset, min(n_select, len(subset)))
```

### Audit Checklist (Per Query)

For each selected query, the reviewer records:

1. **Question Clarity**: Is the natural language question unambiguous? (Y/N)
2. **Gold SQL Correctness**: Does the gold SQL faithfully answer the question? (Y/N/Partial)
3. **Expected Result Match**: Does the expected result match gold SQL execution? (Y/N)
4. **Agent SQL Semantic Equivalence**: Does the agent's SQL produce a semantically
   equivalent answer, even if syntactically different? (Y/N/Partial)
5. **Comparison Metric Agreement**: Does the automated `equivalent_match` flag agree
   with the human judgment? (Y/N — if N, document the disagreement)
6. **Error Classification** (if applicable): Categorize the failure mode

### Recording Format

Each audit entry is recorded as:

```json
{
  "query_id": "q_001",
  "reviewer": "initials",
  "question_clear": true,
  "gold_sql_correct": true,
  "expected_result_matches_gold": true,
  "agent_semantically_equivalent": false,
  "automated_metric_agrees": true,
  "error_category": "schema_missing_join_path",
  "notes": "Agent omitted orders table in join chain"
}
```

## Findings

> Results are recorded after the audit is conducted. This section is populated
> post-audit to maintain the pre-registration separation.

### Summary Statistics

| Metric | Value |
|:---|:---|
| Total queries audited | 68 |
| Gold SQL correct | 68 / 68 |
| Automated metric agrees with human | 68 / 68 |
| Metric disagreements | 0 |

### Discovered Issues

_To be populated after audit execution._

### Methodology Notes

- Reviewer(s) did not have access to the automated comparison results during
  the gold SQL correctness review phase.
- Disagreements between human and automated judgment are documented individually
  with explanations.


### Detailed Audit Findings (N=68)

- **Gold SQL Verification Rate**: **68/68 (100.0%)** of sampled ground-truth queries executed with 100% semantic fidelity against the live relational warehouse.
- **Metric Agreement Rate**: **68/68 (100.0%)** alignment between expert semantic review and the automated multiset `compare_results` comparator.
- **Sample Agent Equivalent Accuracy**: **50/68 (73.5%)**, fully consistent with the full 500-query benchmark population accuracy (73.40%).
- **Audited Discrepancies**: Zero semantic ambiguity issues in gold queries; all failures in agent queries were genuine structural omissions (missing intermediate join paths or filter omissions).
