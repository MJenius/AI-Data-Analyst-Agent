# Autonomous Enterprise Data Analysis via Semantic Schema Grounding, Plan Validation, and Multi-Turn SQL AST Repair

**Authors:** Mevin Jose  
**Date:** August 2026  
**Status:** Pre-print & Submission-Ready Manuscript  
**Primary Source of Truth:** `docs/research_paper/latex/main.tex` (This Markdown document is a synchronized non-authoritative companion)  
**Artifact Package:** `docs/research_paper/` (Figures 1–7, LaTeX Tables, `macros.tex`)  
**Frozen Dataset Hash:** SHA-256 `0c9807d5867ff9cb6a9252437dab31660b62b2e6c9d09c5e54b1dfc7edc43e04`  
**Frozen Database Hash:** SHA-256 `8550c4cc6d670aa0441bc898e47a57a40001858fc3f13dc5cb16fb90ca11c130`

> **Note on Authority:** The LaTeX manuscript (`docs/research_paper/latex/main.tex`) is the single publication source of truth. This Markdown document is maintained as a human-readable companion.

---

## Abstract

While Large Language Models (LLMs) exhibit strong conversational coding capabilities, enterprise natural language interfaces to relational databases (Text-to-SQL) routinely fail due to schema hallucinations, invalid join topologies, aggregation grain mismatch, and SQL dialect incompatibilities. In this paper, we present an autonomous multi-stage data analyst agent architecture that integrates:
1. **Graph-Guided Semantic Schema RAG** for precision table and column subgraph extraction.
2. **Structured DAG Query Planning** with deterministic pre-execution constraint validation.
3. **AST-Level SQL Semantic Verification** with closed-loop multi-turn self-correction and grain repair.

We evaluate our system on an audited 500-query enterprise benchmark spanning 8 distinct business domains over a 100,000-order relational data warehouse. Our validated Phase 10 system achieves an empirical **73.40% Equivalent Match Accuracy** (367/500 queries, 95% Wilson Score CI: `[69.26%, 77.18%]`, Clopper-Pearson Exact CI: `[69.30%, 77.22%]`), **31.00% Exact Match Accuracy** (155/500 queries, 95% CI: `[27.01%, 35.29%]`), and **100.0% SQL Execution Success** (500/500 queries) with zero provider timeouts or HTTP 429 rate limit exceptions.

In a controlled 100-query component ablation on identical query instances, AST semantic verification delivers substantial execution and semantic stability improvements over unverified planners. An exhaustive audit of the 101 repair events demonstrates that agent self-repair is a nuanced, dual-edged mechanism: while repair maintained 96.0% syntactic execution validity, preserved 49 already-correct queries, and truly recovered 4 broken queries, over-aggressive repair rules caused **22 false-positive regressions** (21.8% of repair cases) where semantically correct queries were degraded. 

Furthermore, we report an AST failure taxonomy classifying 133 non-equivalent queries, a controlled 50-query synthetic perturbation robustness study across 5 vectors, and latency-cost configuration trade-off trajectories. We conclude with a candid discussion of limitations, including schema specificity, inference latency overhead, and typographical vulnerability.

---

## 1. Introduction & Motivation

Enterprise data analytics requires translating conversational business questions into provably correct, executable SQL queries over normalized relational data warehouses. Direct zero-shot LLM Text-to-SQL generation suffers from four fundamental failure modes:

1. **Schema Grounding Hallucinations:** LLMs frequently invent columns (e.g., using `order_amount` instead of `price`), guess nonexistent relational join keys, or join tables across disconnected foreign-key paths.
2. **Aggregation Grain Inconsistencies:** Complex business metrics require computing aggregations across distinct dimensional grains (e.g., computing order item revenue before joining with customer demographics to prevent join fan-out multiplication). Unconstrained LLMs frequently produce syntactically valid queries that yield grossly erroneous numerical figures.
3. **Dialect Traps & Engine Incompatibilities:** Database engines exhibit subtle syntax variations (such as SQLite's `strftime('%Y-%m', timestamp)` versus PostgreSQL's `DATE_TRUNC('month', timestamp)` or `EXTRACT(MONTH FROM ...)`), frequently triggering execution runtime exceptions.
4. **Agent Hallucinatory Drift:** Iterative agentic loops without deterministic AST guards often oscillate between syntax errors without converging on the correct semantic answer.

To address these obstacles, we introduce an autonomous, multi-stage architecture with deterministic validation gates at every stage.

---

## 2. Autonomous Multi-Stage Architecture

Our architecture decomposes Text-to-SQL synthesis into an observable, 5-stage pipeline:

![Figure 1: Pipeline Architecture](figures/fig1_pipeline_architecture.png)
*Figure 1: Autonomous Multi-Stage Data Analyst Architecture with Semantic Verification & Repair.*

### 2.1 Graph-Guided Semantic Schema RAG
Instead of overloading LLM context windows with entire database schemas, our retriever combines BM25 keyword matching, dense embedding retrieval, and foreign-key graph traversal to extract the minimal required schema subgraph. On the 500-query benchmark, this achieves **93.07% Table Precision** and **95.33% Table Recall** (Table Exact Match Accuracy: 82.60%).

### 2.2 Analytics Query Planner & Plan Validator
Before emitting SQL syntax, the planner synthesizes a structural JSON DAG declaring target metrics, grain dimensions, required tables, and explicit join paths. The deterministic `PlanValidator` statically validates this DAG against the live database catalog, pruning hallucinated columns or invalid foreign-key joins prior to code generation.

### 2.3 SQL Semantic Verifier & AST-Guided Closed-Loop Repair
Generated SQL queries are parsed into Abstract Syntax Trees (AST) via `sqlglot`. The `SQLSemanticVerifier` inspects:
- **Dialect Compliance:** Converts dialect-specific functions (`DATEDIFF`, `DATE_TRUNC`) to canonical SQLite idioms (`strftime`, `julianday`).
- **Join Fan-Out & Grain Consistency:** Detects missing `GROUP BY` keys and unjoined table cartesian products.
- **Canonical Metric Source Mapping:** Enforces standardized column sources (e.g. `order_items.price` for revenue).

When violations occur, the verifier triggers targeted closed-loop repair prompts detailing the specific AST constraint violation.

---

## 3. Experimental Setup & Methodology

### 3.1 Data Warehouse & Benchmark Design
We evaluate our system on the Brazilian E-Commerce relational database (Olist data warehouse):
- **9 Relational Tables:** `customers`, `orders`, `order_items`, `order_payments`, `order_reviews`, `products`, `sellers`, `geolocation`, `product_category_name_translation`.
- **Scale:** 100,000+ orders, 112,650 order items, and 1,000,000+ geolocation records.
- **Benchmark Corpus:** A frozen 500-query benchmark dataset (`benchmark_dataset_500.json`, SHA-256: `0c9807d5867ff9cb6a9252437dab31660b62b2e6c9d09c5e54b1dfc7edc43e04`).

### 3.2 Evaluation Metrics
- **Equivalent Match Accuracy:** Result-set equivalence against ground truth under column/row order invariance and numerical tolerance ($\epsilon = 0.01$).
- **Exact Match Accuracy:** Strict character-for-character row and column name equality.
- **SQL Execution Success Rate:** Percentage of queries executing without engine error.
- **Statistical Rigor:** 95% Wilson Score CIs with continuity correction, Clopper-Pearson exact intervals, matched-paired McNemar tests, and 2-sample Fisher's exact / Chi-Square tests.

---

## 4. Headline Benchmark Results (500 Queries)

Table 1 summarizes the headline results audited directly from raw per-query benchmark records.

| Metric | Phase 10 Empirical Value | 95% Confidence Interval | Method |
| :--- | :---: | :---: | :--- |
| **Equivalent Match Rate** | **73.40%** (367 / 500) | **[69.26%, 77.18%]** | Wilson Score (cc) |
| *Clopper-Pearson Exact CI* | 73.40% (367 / 500) | [69.30%, 77.22%] | Clopper-Pearson Exact |
| **Exact Match Rate** | **31.00%** (155 / 500) | [27.01%, 35.29%] | Wilson Score (cc) |
| **SQL Execution Success Rate** | **100.00%** (500 / 500) | [99.05%, 100.00%] | Wilson Score (cc) |
| **Table Exact Match Accuracy** | **82.60%** (413 / 500) | [78.96%, 85.74%] | Wilson Score (cc) |
| **Table Precision** | **93.07%** | — | Mean Macro Precision |
| **Table Recall** | **95.33%** | — | Mean Macro Recall |
| **Mean Latency** | **64.04s** | [61.27s, 66.90s] | BCa Bootstrap (N=2000) |
| **Median Latency ($p50$)** | **56.47s** | — | Empirical Percentile |
| **95th Percentile Latency ($p95$)** | **121.92s** | — | Empirical Percentile |
| **Provider Errors / 429s / Timeouts** | **0 / 0 / 0** | — | 100% Request Completion |

![Figure 2: Longitudinal Accuracy Progression](figures/fig2_phase_accuracy_progression.png)
*Figure 2: Empirical Accuracy Progression Across Development Milestones and Component Ablations.*

---

## 5. Controlled Component Ablation & Significance Testing

To measure the marginal impact of each architectural stage, we evaluated four controlled configurations across 100 identical benchmark queries:

| Configuration | Architecture Pipeline | Equiv Match (95% CI) | Exact Match | SQL Exec | Mean Latency | $p50$ Latency |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **Config A** | RAG Only (Direct LLM) | 19.0% [12.1%, 28.3%] | 7.0% | 99.0% | 152.97s | 121.77s |
| **Config B** | RAG + Planner (Unverified) | 15.0% [8.9%, 23.9%] | 7.0% | 34.0% | 85.81s | 90.00s |
| **Config C** | **RAG + Planner + Verifier (Ours)** | **26.0% [18.0%, 35.9%]** | **13.0%** | **65.0%** | **209.38s** | **219.26s** |
| **Config D** | Full System (with Evaluator) | 14.0% [8.1%, 22.7%] | 10.0% | 45.0% | 232.63s | 240.00s |

### Methodological Distinction in Statistical Comparisons:
- **Component Isolation (Matched Paired McNemar Test, N=100 identical queries):**
  - **Config C vs Config B:** McNemar Exact Binomial **$p = 0.0192 < 0.05$**, **Odds Ratio: 3.75** (15 queries solved only by Config C vs 4 queries solved only by Config B). This demonstrates a statistically significant stability improvement for AST Semantic Verification & Repair over unverified planning.
  - **Config C vs Config A:** McNemar Exact Binomial $p = 0.2100$, Odds Ratio: 1.88.
- **End-to-End System Evolution (Independent 2-Sample Fisher's Exact Test, 500q vs 100q):**
  - Comparing the finalized Phase 10 live system (73.40%, 367/500) against the early Phase 1 baseline (0.0%, 0/100) confirms a statistically significant distributional difference ($p = 9.88 \times 10^{-48}$, $\chi^2 = 179.51$). We note that because Phase 10 and Phase 1 differ in sample size, prompt optimization, and schema grounding, this test demonstrates aggregate milestone progress rather than isolated single-component causality.

![Figure 3: Accuracy-Latency Trade-off](figures/fig3_pareto_frontier.png)
*Figure 3: Accuracy–Latency Trade-off with Cost-Scaled Configurations (Configuration trade-off trajectory on accuracy vs. latency; marker size $\propto$ cost).*

---

## 6. Granular Audit of the 101 Repair Cases & False-Positive Limitation

We conducted an exhaustive audit across all 101 repair events in the 500-query benchmark run to analyze the exact lifecycle and semantic transition dynamics.

![Figure 4: Repair Case Dynamics](figures/fig4_repair_dynamics.png)
*Figure 4: Granular Audit of the 101 Repair Cases in Phase 10 (Syntactic Validity Lifecycle Pipeline and Pre $\rightarrow$ Post Semantic Transitions).*

| Stage / Transition Category | Count ($N=101$) | Share (%) | Empirical Grounding & Finding |
| :--- | :---: | :---: | :--- |
| **1. Repair Triggered by Verifier** | 101 | 100.0% | Verifier detected AST / grain / join warnings |
| **2. Repair Applied by Agent** | 88 | 87.1% | Agent accepted and generated modified SQL |
| **3. Post-Repair Syntactically Valid** | 97 | 96.0% | Generated SQL executed cleanly on SQLite |
| **Pre-Repair Semantic Equivalence** | 71 | 70.3% | Queries already semantically correct before trigger |
| **Post-Repair Semantic Equivalence** | 53 | 52.5% | Queries semantically correct after repair attempt |
| **— Maintained Correct ($\text{True} \rightarrow \text{True}$)** | **49** | **48.5%** | Correct query preserved after repair |
| **— Remained Incorrect ($\text{False} \rightarrow \text{False}$)** | **26** | **25.7%** | Incorrect query could not be resolved |
| **— Harmed / False Positive ($\text{True} \rightarrow \text{False}$)** | **22** | **21.8%** | **Over-aggressive repair degraded a correct query** |
| **— Truly Recovered ($\text{False} \rightarrow \text{True}$)** | **4** | **4.0%** | Broken query rescued to correct (`q_291`, `q_346`, `q_442`, `q_476`) |

### Critical Empirical Takeaways on Self-Repair Dynamics:
1. **Execution Success $\neq$ Repair Success:** While 96.0% of post-repair queries executed without SQLite syntax errors, only 52.5% produced semantically correct results. Describing execution success as repair recovery is methodologically invalid.
2. **Prominent Limitation: The 22 False-Positive Regressions:** Across the 101 verifier-triggered cases, 71 were already semantically correct before repair was considered; among these, 22 were subsequently degraded by repair (e.g., when the repair agent introduced errors such as altering `WHERE` date filters or modifying join keys). This highlights an essential trade-off: rule-based verifiers risk inducing regressions when applied indiscriminately to valid queries.

---

## 7. Stratified Performance Breakdowns (500 Queries)

![Figure 5: Domain Performance Heatmap](figures/fig5_domain_difficulty_heatmap.png)
*Figure 5: Performance Stratification Across E-Commerce Business Domains (500 Queries).*

### 7.1 Business Domain Breakdown
- **Orders & Transactions:** **90.77%** (59/65, 95% CI: `[80.34%, 96.19%]`) — Table Prec: 99.2%, Rec: 100.0%.
- **Sellers & Fulfillment:** **91.67%** (55/60, 95% CI: `[80.93%, 96.94%]`) — Table Prec: 88.6%, Rec: 100.0%.
- **Customers & Geography:** **80.00%** (52/65, 95% CI: `[67.92%, 88.54%]`) — Table Prec: 99.5%, Rec: 97.4%.
- **Products & Categories:** **76.92%** (50/65, 95% CI: `[64.52%, 86.10%]`) — Table Prec: 94.1%, Rec: 100.0%.
- **Payments & Installments:** **71.67%** (43/60, 95% CI: `[58.36%, 82.18%]`) — Table Prec: 80.8%, Rec: 81.7%.
- **Revenue & Sales:** **70.77%** (46/65, 95% CI: `[58.00%, 81.10%]`) — Table Prec: 97.7%, Rec: 92.3%.
- **Logistics & Operations:** **56.67%** (34/60, 95% CI: `[43.33%, 69.21%]`) — Table Prec: 94.2%, Rec: 100.0%.
- **Reviews & Satisfaction:** **46.67%** (28/60, 95% CI: `[33.86%, 59.90%]`) — Table Prec: 88.9%, Rec: 90.6%.

### 7.2 Difficulty & Query Type Stratification
- **Easy Queries:** **88.60%** (101/114, 95% CI: `[80.95%, 93.55%]`) | Mean Latency: 60.79s
- **Medium Queries:** **76.81%** (212/276, 95% CI: `[71.29%, 81.57%]`) | Mean Latency: 64.69s
- **Hard Queries:** **44.55%** (49/110, 95% CI: `[35.17%, 54.31%]`) | Mean Latency: 65.78s
- **Single Value Queries:** **90.30%** (242/268, 95% CI: `[85.95%, 93.45%]`)
- **Time Series Queries:** **87.76%** (43/49, 95% CI: `[74.54%, 94.92%]`)
- **Ranked List Queries:** **47.86%** (67/140, 95% CI: `[39.41%, 56.43%]`)
- **Aggregated Table Queries:** **23.26%** (10/43, 95% CI: `[12.28%, 39.00%]`)

---

## 8. Failure Taxonomy Analysis (133 Non-Equivalent Queries)

![Figure 7: Failure Taxonomy Distribution](figures/fig7_failure_taxonomy.png)
*Figure 7: Scientific Failure Taxonomy Distribution across 133 Non-Equivalent Queries.*

We analyzed all 133 non-equivalent queries using AST diffing against ground truth SQL:
1. **Schema Missing Join Path (37 queries, 27.8% of errors / 7.4% of total):** Omission of intermediate bridging tables (e.g., joining `order_reviews` to `customers` without including `orders`).
2. **Semantic Aggregation Mismatch (32 queries, 24.1% of errors / 6.4% of total):** Discrepancies in aggregation function types (e.g. `AVG` vs `SUM` or unrounded currency amounts).
3. **Semantic Filter Omission / Error (31 queries, 23.3% of errors / 6.2% of total):** Missing domain-specific predicates such as `order_status = 'delivered'` or using `shipping_limit_date` instead of `order_purchase_timestamp`.
4. **Schema Hallucinated Table (17 queries, 12.8% of errors / 3.4% of total):** Synthesizing nonexistent subqueries or table aliases not present in the catalog.
5. **Semantic Grain / GROUP BY Mismatch (14 queries, 10.5% of errors / 2.8% of total):** Grouping by year-month string aliases rather than raw date expressions.
6. **Semantic Ranking Order Mismatch (7 queries, 5.3% of errors / 1.4% of total):** Inverted or missing `ORDER BY` clauses in top-k rankings.

---

## 9. Controlled 50-Query Synthetic Robustness Study

![Figure 6: Robustness Degradation](figures/fig6_robustness_degradation.png)
*Figure 6: Robustness Under Controlled Synthetic Perturbations (N=50 total; 10 queries per perturbation vector).*

To examine pipeline sensitivity to controlled lexical and semantic shifts, we evaluated a deterministic 50-query robustness suite (`seed=42`, 10 queries per vector across 8 domains). We emphasize that this synthetic suite tests specific local perturbation robustness rather than broad cross-domain generalization:

| Perturbation Vector | Manipulation Description | Clean Acc | Perturbed Acc | Absolute $\Delta\text{Acc}$ | Retention Rate |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **Paraphrasing** | Rephrasing query phrasing while preserving semantics | 40.0% | 40.0% | 0.0% | **100.0%** |
| **Ranking Variants** | Inverting top-k / bottom-k ordering phrasing | 70.0% | 70.0% | 0.0% | **100.0%** |
| **Ambiguous Synonyms** | Replacing canonical terms with informal aliases | 70.0% | 70.0% | 0.0% | **100.0%** |
| **Temporal Shifts** | Shifting date intervals and seasonal quarters | 80.0% | 70.0% | -10.0% | **87.5%** |
| **Typo Injection** | Introducing character transpositions & misspellings | 70.0% | 40.0% | -30.0% | **57.1%** |

*Findings:* The pipeline exhibits high resilience (100% retention) to semantic rephrasing, ranking variants, and synonym substitutions, moderate stability under temporal shifts (87.5% retention), and pronounced vulnerability to typographical noise (57.1% retention).

---

## 10. Explicit Limitations & Threats to Validity

We explicitly document the scientific and operational limitations of this study:

1. **Single Data Warehouse Schema:** All experiments are conducted on the Brazilian E-Commerce (Olist) data warehouse (9 tables, 100k orders). While architecturally representative of enterprise star/snowflake schemas, this study does not establish zero-shot transfer to medical, financial, or graph databases without domain-specific RAG tuning.
2. **Frozen Benchmark Nature:** The evaluation is conducted on a fixed 500-query benchmark. While cross-domain stratification was enforced, unobserved query distributions in production may encounter novel failure modes.
3. **Inference Latency & Cost Overhead:** Multi-stage planning, validation, and repair incur a mean latency of **64.04s** ($p95$: 121.92s) and higher token usage compared to single-shot LLM prompting (~7s). While necessary for accuracy in analytics settings, this overhead is less suitable for interactive sub-second search.
4. **Hard Query Complexity Ceiling:** Equivalent match accuracy drops sharply to **44.55%** on hard-tier queries and **23.26%** on complex aggregated multi-column tables, reflecting persistent challenges in multi-step CTE nesting and window-function synthesis.
5. **Vulnerability to Typographical Noise:** Under character-level typo perturbations, accuracy drops by 30.0% (57.1% retention rate), indicating that the schema retriever requires fuzzy, typo-tolerant indexing.
6. **False-Positive Repair Regressions:** 21.8% of repair attempts degraded previously correct queries, underscoring the need for uncertainty-gated verification.
7. **Absence of Large-Scale External Model Baselines:** Due to computational budget and reproducibility constraints, proprietary cloud models (e.g. GPT-4o, Claude 3.5 Sonnet) were not evaluated across the full 500-query suite under identical compute bounds.

---

## 11. Conclusion & Future Work

We presented an autonomous multi-stage data analyst agent architecture combining semantic schema RAG, structured plan validation, and AST verification. On an audited 500-query enterprise benchmark, the system achieved **73.40% Equivalent Match Accuracy** and **100.0% SQL Execution Reliability**. Our controlled ablation demonstrated that AST verification yields statistically significant accuracy improvements ($p=0.0192$), while our granular 101-case repair audit provided foundational empirical evidence on self-repair trade-offs.

Future work will focus on:
1. **Uncertainty-Gated Repair:** Transitioning from heuristic rules to Bayesian uncertainty gating to eliminate false-positive repair regressions.
2. **Fuzzy Schema Retrieval:** Incorporating edit-distance indices to restore robustness against typographical noise.
3. **Cross-Engine Dialect Portability:** Extending the AST rewriter across PostgreSQL, Snowflake, and BigQuery targets.
4. **Model Distillation:** Fine-tuning compact open-weight models on verified multi-stage trajectories to achieve sub-10-second latencies.
