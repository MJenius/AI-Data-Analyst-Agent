# Research Paper Readiness & Scientific Evidence Audit

**Project:** Engineering Reliable LLM-Based Data Analysis: An Empirical Study of Schema Grounding, Planning, Verification, and SQL Repair  
**Author:** Mevin Jose  
**Benchmark:** Phase 10 Live 500-Query Benchmark on Olist Relational Data Warehouse  
**Audit Date:** August 19, 2026  
**Auditor:** Independent Research-Validation Pipeline  
**Target Manuscript:** `docs/research_paper/PAPER_DRAFT.md` & `docs/research_paper/latex/main.tex`  
**Artifact Package:** `docs/research_paper/` (Figures 1–7, LaTeX Tables, `macros.tex`)

---

## 1. Supported Empirical Claims & Grounding Matrix

Every empirical claim in the research manuscript has been verified directly against raw per-query benchmark records (`results/phase10/live_500_benchmark_run/summary.json` and `checkpoint.json`):

| # | Empirical Claim in Manuscript | Sample Size ($N$) | Metric Value | 95% Confidence Interval / Test | Grounding Source |
| :---: | :--- | :---: | :---: | :---: | :--- |
| **C1** | Overall Result Equivalence Rate | 500 | **73.40%** (367 / 500) | **[69.26%, 77.18%]** (Wilson cc)<br>[69.30%, 77.22%] (Clopper-Pearson) | `summary.json`, `final_research_validation_report.json` |
| **C2** | Overall Exact Match Accuracy | 500 | **31.00%** (155 / 500) | **[27.01%, 35.29%]** (Wilson cc) | `summary.json` |
| **C3** | SQL Execution Success Rate | 500 | **100.00%** (500 / 500) | **[99.05%, 100.00%]** (Wilson cc) | `summary.json` (0 database runtime exceptions) |
| **C4** | Table Exact Match Accuracy | 500 | **82.60%** (413 / 500) | **[78.96%, 85.74%]** (Wilson cc) | `summary.json` |
| **C5** | Table Retrieval Precision & Recall | 500 | **93.07%** / **95.33%** | Macro Precision / Recall | `summary.json` |
| **C6** | Latency Profile ($p50$, $p90$, $p95$, Mean) | 500 | Mean: **64.04s**, $p50$: **56.47s**,<br>$p90$: **105.77s**, $p95$: **121.92s** | Mean BCa Bootstrap 95% CI:<br>**[61.27s, 66.90s]** | `summary.json` |
| **C7** | Zero Provider Failure Guarantee | 500 | **0** Timeouts, **0** 429s, **0** Errors | Complete Request Convergence | `summary.json` |
| **C8** | Ablation: Verifier Accuracy Gain | 100 | **+11.0%** (15.0% $\rightarrow$ 26.0%) | **$p = 0.0192 < 0.05$**, Odds Ratio = 3.75 | Matched Paired McNemar Test (Config C vs Config B) |
| **C9** | Ablation: Verifier Execution Gain | 100 | **+31.0%** (34.0% $\rightarrow$ 65.0%) | **$p = 0.0001 < 0.001$**, Odds Ratio = 8.75 | Matched Paired McNemar Test (Config C vs Config B) |
| **C10** | Phase 10 vs Baseline Superiority | 500 vs 100 | **+73.4%** (0.0% $\rightarrow$ 73.40%) | **$p = 9.88 \times 10^{-48} < 0.001$**, $\chi^2 = 179.51$ | Independent 2-Sample Fisher's Exact Test |
| **C11** | Repair Cases: Triggered vs Applied | 101 | **101** Triggered, **88** Applied | 87.1% Application Rate | `repair_audit_cache.json` |
| **C12** | Repair Cases: Syntactic Validity | 101 | **97 / 101** Executable | **96.0%** Post-Repair Syntax Rate | SQLite live re-execution |
| **C13** | Repair Cases: True Semantic Recovery | 101 | **4** Queries Recovered | 4.0% True Recovery Rate (`q_291`, `q_346`, `q_442`, `q_476`) | Ground-truth row comparison |
| **C14** | Repair Cases: Correct Preserved | 101 | **49** Queries Maintained | 48.5% Maintained Correct Rate | Ground-truth row comparison |
| **C15** | Repair Cases: False-Positive Regression | 101 | **22** Queries Harmed | 21.8% Regression Rate (True $\rightarrow$ False) | Ground-truth row comparison |
| **C16** | Controlled Paraphrase/Synonym Invariance | 50 | **100.0%** Retention (Synonym/Ranking) | $\Delta\text{Acc} = 0.0\%$ | Robustness suite evaluation (`seed=42`) |
| **C17** | Dominant Failure Mode: Join Path Omission | 133 | **37 / 133** (27.8% of errors) | 7.4% of all 500 queries | AST diagnostic classifier |

---

## 2. Unsupported / Corrected Claims & Methodological Fixes

The following claims from earlier drafts were identified as methodologically invalid, ambiguous, or unsupported, and have been corrected:

### ❌ Correction 1: Equating "Execution Success" with "Repair Success"
- **Previous Overclaim:** *"The repair loop succeeded on 96% of triggered cases."*
- **Empirical Grounding:** In reality, while 97 of the 101 repair cases (96.0%) executed without SQLite syntax errors, only 53 of them (52.5%) produced semantically equivalent result rows. Crucially, across the 101 verifier-triggered cases, 71 were already semantically correct before repair was considered; among these, 22 were subsequently degraded by repair (the repair loop truly recovered **4 queries** from broken to correct, but degraded **22 queries** from correct to incorrect due to aggressive aliasing and grain transformations).
- **Fix in Manuscript:** Section 7 / 8 explicitly reports the 4-way semantic transition breakdown (+4 truly recovered, 49 maintained, 22 harmed/false positive, 26 unrecovered) as the primary scientific repair metric, explicitly warning that execution success must never be conflated with semantic repair.

### ❌ Correction 2: Running Paired McNemar Tests Across Unmatched Query Sets
- **Previous Flaw:** Running McNemar's test directly between the 500-query Phase 10 run and 100-query ablation runs.
- **Methodological Fix:** Paired McNemar tests are strictly restricted to identical query ID subsets (e.g. between Config C and Config B on the 100 identical queries, yielding $p=0.0192$). For comparisons between unequal samples (e.g. 500-query Phase 10 vs 100-query Baseline or Config C), independent 2-sample Fisher's Exact and Chi-Square tests are employed.

### ❌ Correction 3: Ambiguity Between Exact Match and Semantic Equivalence
- **Previous Ambiguity:** Using the term "accuracy" interchangeably for strict string match and numerical equivalence.
- **Fix in Manuscript:** The manuscript maintains a strict distinction between **Result Equivalence Rate (73.40%)** (row-order invariant, float-tolerant result set matching) and **Exact Match Rate (31.00%)** (character-level SQL result match).

---

## 3. Comprehensive Statistical Evidence Package

### 3.1 Confidence Intervals Summary (95% Confidence Level)
- **Phase 10 Result Equivalence (N=500):** $73.40\% \pm 3.96\%$ $\rightarrow$ Wilson (cc): `[69.26%, 77.18%]`, Clopper-Pearson: `[69.30%, 77.22%]`.
- **Phase 10 Exact Match (N=500):** $31.00\% \pm 4.14\%$ $\rightarrow$ Wilson (cc): `[27.01%, 35.29%]`.
- **Phase 10 SQL Execution (N=500):** $100.00\%$ $\rightarrow$ Wilson (cc): `[99.05%, 100.00%]`.
- **Phase 10 Mean Latency (N=500):** $64.04\text{s}$ $\rightarrow$ BCa Bootstrap: `[61.27s, 66.90s]`.

### 3.2 Hypothesis Testing Summary
- **Hypothesis 1 (AST Verifier Benefit):** Config C (RAG+Planner+Verifier) vs Config B (RAG+Planner).
  - *Design:* Matched paired McNemar test on $N=100$ identical queries.
  - *Discordant Counts:* $b = 15$ (solved only by C), $c = 4$ (solved only by B).
  - *Result:* Exact Binomial $p = 0.0192 < 0.05$, Odds Ratio = 3.75. **Statistically Significant.**
- **Hypothesis 2 (Phase 10 vs Phase 1 Baseline):** Phase 10 Live (500q) vs Baseline (100q).
  - *Design:* Independent 2-sample Fisher's Exact Test & $\chi^2$ with Yates' correction.
  - *Contingency Matrix:* Phase 10: 367/500, Baseline: 0/100.
  - *Result:* Fisher $p = 9.88 \times 10^{-48}$, $\chi^2 = 179.51$. **Statistically Significant.**

---

## 4. Remaining Weaknesses & Threats to Validity

1. **Hard Query Complexity Ceiling:** Accuracy on "Hard" difficulty queries drops to **44.55%** (49/110) due to complex multi-step CTEs, window functions, and nested ratio calculations.
2. **Aggregated Table Formulation:** Queries requesting wide multi-column aggregated breakdowns achieve only **23.26%** (10/43) accuracy, primarily due to column naming mismatches and pivot representations.
3. **Over-Aggressive Repair Regressions:** 22 out of 101 repair events degraded queries that were already producing correct results before repair, demonstrating that static verifier rules occasionally trigger on harmless syntax patterns.
4. **Vulnerability to Typographical Noise:** Under heavy typographical noise (typo injection), accuracy drops by 30.0% (57.1% retention rate), indicating that the schema retriever requires fuzzy-matching capabilities.
5. **Single-Database Evaluation:** The benchmark evaluates a single complex enterprise schema (Olist e-commerce warehouse). Cross-schema generalizability across medical or financial domains remains to be demonstrated.

---

## 5. Reproducibility & Artifact Integrity Verification

| Artifact / Asset | Verification Status | Cryptographic Hash / Path |
| :--- | :---: | :--- |
| **Benchmark Dataset (500q)** | Verified Bitwise | SHA-256: `0c9807d5867ff9cb6a9252437dab31660b62b2e6c9d09c5e54b1dfc7edc43e04` |
| **Relational Database (`analytics.db`)** | Verified Bitwise | SHA-256: `8550c4cc6d670aa0441bc898e47a57a40001858fc3f13dc5cb16fb90ca11c130` |
| **Raw Per-Query Records** | Frozen & Read-Only | `results/phase10/live_500_benchmark_run/summary.json` (500 items) |
| **Validation Report** | Auto-Generated | `results/phase10/final_research_validation_report.json` |
| **Publication Figures (1–7)** | Vector & 300 DPI | `docs/research_paper/figures/` (`.pdf`, `.png`, `.svg`) |
| **LaTeX Tables & Macros** | Auto-Generated | `docs/research_paper/tables/`, `docs/research_paper/macros.tex` |
| **Validation Runner** | Deterministic Execution | `tests/evaluation/run_final_research_validation.py` |

---

## 6. Necessary Future Experiments & Roadmap

1. **Uncertainty-Gated Repair:** Implement an entropy- or consistency-based gating mechanism to prevent the repair loop from firing on queries with high semantic confidence, eliminating the 22 false-positive regressions.
2. **Fuzzy Schema Retrieval:** Incorporate character n-gram and edit-distance indices into the schema RAG retriever to restore typo resilience.
3. **Cross-Engine Dialect Portability:** Deploy the AST semantic rewriter against PostgreSQL, BigQuery, and Snowflake dialect targets to benchmark cross-engine portability.
4. **Open-Weight Model Distillation:** Fine-tune 8B-parameter open-weight models on the verified multi-stage trajectories to achieve sub-10-second latencies and lower inference costs.

---

## 7. Audit Sign-Off

- **Audit Status:** **PASSED — READY FOR PUBLICATION SUBMISSION**
- **Discrepancies Remaining:** **0**
- **Unverified Claims:** **0**
- **Read-Only Data Integrity:** **Maintained 100%**
