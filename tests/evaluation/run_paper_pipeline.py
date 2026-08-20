"""Paper Artifact Compilation Script & Conference PDF Builder.

Executes paper_generator.py to produce figures, LaTeX tables, macros,
and builds a compact two-column conference research paper PDF.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import fitz  # PyMuPDF for visual inspection
from agent_platform.experiments.paper_generator import PaperArtifactCompiler
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    FrameBreak,
    HRFlowable,
    Image,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


PAPER_DRAFT_TEXT = """# Engineering Reliable LLM-Based Data Analysis: An Empirical Study of Schema Grounding, Planning, Verification, and SQL Repair

**Mevin Jose**  
*Independent Researcher* (`mevin.research@gmail.com`)

---

## Abstract

While Large Language Models (LLMs) demonstrate notable code-generation capabilities, translating natural language questions into reliable analytical SQL over relational databases (Text-to-SQL) remains brittle in practice. In this paper, we investigate the empirical mechanisms governing Text-to-SQL reliability: **structural verification improves query reliability, whereas aggressive automated repair can introduce substantial semantic regressions**. We evaluate a multi-stage reliability pipeline on a frozen 500-query benchmark across 8 business domains over a public relational e-commerce data warehouse (the Olist dataset, 9 tables, 100,000+ orders). Our system achieves a **73.40% Result Equivalence Rate under the study comparator** (367/500 queries, 95% Wilson Score CI: `[69.26%, 77.18%]`, Clopper-Pearson Exact CI: `[69.30%, 77.22%]`), **31.00% Exact Result Match**, and **100.00% SQL Execution Success** with a mean latency of 64.04s ($p50$: 56.47s, $p95$: 121.92s). In a controlled 4-way 100-query ablation, activating deterministic Abstract Syntax Tree (AST) structural verification significantly improves result equivalence over unverified planning (Config C 26.0% vs. Config B 15.0%, McNemar exact $p=0.0192$, $\\text{Odds Ratio}=3.75$). However, an exhaustive audit of all 101 repair events reveals that automated self-repair is a double-edged mechanism: while 97 of 101 post-repair queries (96.0%) were syntactically valid and preserved 49 already-correct queries, repair yielded only 4 genuine recoveries while inducing **22 harmful false-positive regressions** (21.8% of repair events) where previously correct queries were degraded. Furthermore, a cross-schema transfer probe across 20 external databases from the Spider benchmark demonstrates that while execution stability is preserved (100.0%), result equivalence drops to **18.0%** (9/50), highlighting the gap between in-domain grounding and zero-shot schema transfer. We conclude that conservative, uncertainty-aware structural verification is preferable to unconstrained automated repair loops.

**Keywords:** Text-to-SQL, LLM Reliability, Structural Verification, Automated Query Repair, Abstract Syntax Trees, Empirical Software Engineering.

---

## 1. Introduction

Natural language interfaces to relational databases (Text-to-SQL) promise to democratize data analytics for non-technical stakeholders. However, evaluating LLM-generated SQL against complex, multi-table schemas reveals a foundational insight:

> **Executable SQL is not necessarily reliable analytical SQL.**

A query may compile cleanly and execute without database runtime exceptions, yet return subtly corrupted figures due to systemic structural failure modes: schema hallucinations, join-path omissions, aggregation grain mismatches, and filter inconsistencies.

### Central Thesis
Rather than presenting Text-to-SQL as an unconstrained agentic pipeline, this empirical study establishes that:
> **Deterministic structural verification improves Text-to-SQL reliability, while aggressive automated repair can introduce semantic regressions.**

Our evidence directly supports this thesis:
1. **Verification Benefit:** In a controlled ablation, activating AST-based structural verification improves result equivalence from **15.0% to 26.0%** over unverified planning (McNemar exact $p=0.0192$, $\\text{OR}=3.75$).
2. **Repair Hazard:** An audit of all 101 repair events reveals that compiler execution validity masks semantic degradation, producing **22 harmful false-positive regressions** against only **4 genuine recoveries**.
3. **Transfer Boundary:** On a zero-shot cross-schema transfer probe across 20 unseen SQLite databases from the Spider benchmark, execution reliability remains 100.0%, while result equivalence drops to 18.0%, exposing the boundary between deep schema grounding and zero-shot generalization.

### Research Questions
- **RQ1 (Overall Reliability):** Does the multi-stage pipeline achieve high result equivalence on a complex relational warehouse? ($\\rightarrow$ **73.40% Result Equivalence**, **100.00% Execution Success**).
- **RQ2 (Verification Impact):** What is the marginal effect of deterministic AST structural verification? ($\\rightarrow$ Execution rises from 34.0% to 65.0%, result equivalence rises from 15.0% to 26.0%; paired McNemar exact $p=0.0192$, $\\text{OR}=3.75$).
- **RQ3 (Repair Dynamics):** Does automated self-repair reliably fix broken queries without harming valid ones? ($\\rightarrow$ No; **4 genuine recoveries** vs. **22 false-positive regressions**).
- **RQ4 (Failure Taxonomy):** What structural failure modes dominate remaining non-equivalent queries? ($\\rightarrow$ Missing join paths [27.8%], filter omissions [24.8%], and aggregation mismatches [24.1%]).
- **RQ5 (Cross-Schema Transfer):** Does warehouse-grounded reliability transfer to unseen external schemas? ($\\rightarrow$ **100.0% execution success**, but **18.0% result equivalence** on 20 unseen databases).

### Summary of Contributions
1. **Controlled Empirical Decomposition:** We evaluate the marginal effect of deterministic AST verification over unverified planning, demonstrating a statistically significant reliability gain for result equivalence ($p=0.0192$).
2. **Repair-Risk Characterization:** We present an exhaustive 4-way semantic audit of 101 repair events, showing that execution-valid repair can induce substantial false-positive regressions.
3. **Systematic Failure Taxonomy:** We categorize all 133 non-equivalent queries using AST diffing across six core structural failure classes.
4. **Cross-Schema Transfer Probe:** We report zero-shot transfer evaluation across 20 unseen SQLite databases from the Spider benchmark, demonstrating execution robustness alongside a marked semantic generalization drop.
5. **Audited Open Science Package:** We release all source code, frozen benchmark definitions, evaluation scripts, and a cryptographic SHA-256 artifact manifest.

---

## 2. Related Work and Positioning

- **Text-to-SQL Decomposition & Benchmarks:** Benchmarks such as Spider (Yu et al., 2018) and BIRD (Li et al., 2023) evaluate LLMs on multi-table joins and nested subqueries. Decomposition frameworks such as DIN-SQL (Pourreza & Rafiei, 2023), MAC-SQL (Wang et al., 2024), and CHESS (Talaei et al., 2024) show that dividing SQL generation into sub-problems improves performance over monolithic prompting. Our work builds upon this modular paradigm by introducing deterministic, AST-level structural verification gates that inspect query structure prior to execution.
- **Schema Linking & Retrieval-Augmented Generation (RAG):** Retrieval-Augmented Generation (Lewis et al., 2020; Asai et al., 2023) grounds LLMs in external knowledge. In relational querying, schema linking requires retrieving relevant tables, columns, and foreign-key join paths. We augment hybrid dense-sparse retrieval with explicit foreign-key graph traversal to preserve schema connectivity.
- **Structural Verification vs. Execution-Guided Self-Repair:** Iterative reasoning architectures such as ReAct (Yao et al., 2022) and Reflexion (Shinn et al., 2023) leverage feedback loops for self-correction. In Text-to-SQL, execution-guided self-correction feeds compiler errors back to the model (Gao et al., 2023). However, program analysis and constrained decoding literature emphasize that execution validity does not guarantee semantic correctness. Our work directly positions itself at this critical juncture: we provide an empirical comparison between pre-execution AST structural verification and automated self-repair, demonstrating that while syntactic verification significantly aids query reliability, unconstrained repair loops frequently induce false-positive regressions.

---

## 3. Reliability-Oriented System Architecture

Our architecture decomposes analytical SQL synthesis into a 5-stage pipeline:

![Figure 1: Pipeline Architecture](figures/fig1_pipeline_architecture.png)
*Figure 1: Reliability-Oriented Multi-Stage Architecture with Structural Verification & Repair.*

### 3.1 Graph-Guided Semantic Schema RAG
Rather than passing an entire database schema into the LLM context, our retriever combines BM25 keyword matching, dense embedding retrieval via SentenceTransformers, and foreign-key graph traversal. Given a user query, the retriever extracts the minimal required schema subgraph, achieving **93.07% Table Precision** and **95.33% Table Recall** (Table Exact Match: 82.60%) across the 500-query benchmark.

### 3.2 Structured DAG Query Planning & Deterministic Plan Validation
Before emitting SQL code, the planner synthesizes a structural JSON DAG declaring target metrics, grain dimensions, required tables, and explicit join paths. A deterministic `PlanValidator` statically inspects this DAG against the live database catalog, pruning hallucinated column references or invalid foreign-key joins prior to SQL generation.

### 3.3 AST-Based SQL Structural Verification & Closed-Loop Repair
Generated SQL statements are parsed into Abstract Syntax Trees (AST) using SQLGlot. The `SQLSemanticVerifier` statically enforces:
- **Dialect Compliance:** Translating dialect-specific functions (`DATEDIFF`, `DATE_TRUNC`) into canonical SQLite expressions (`strftime`, `julianday`).
- **Join Fan-Out & Grain Integrity:** Verifying that non-aggregated projection columns appear in `GROUP BY` clauses and detecting cartesian products.
- **Canonical Metric Source Mapping:** Enforcing standardized column mappings (e.g., mapping revenue to `order_items.price`).

When violations are identified, the verifier triggers targeted closed-loop repair prompts detailing the specific AST constraint violation.

---

## 4. Experimental Setup and Methodology

### 4.1 Data Warehouse & Benchmark Corpus
We evaluate our system on a multi-table relational e-commerce schema constructed from the Brazilian E-Commerce Public Dataset (Olist):
- **9 Relational Tables:** `customers`, `orders`, `order_items`, `order_payments`, `order_reviews`, `products`, `sellers`, `geolocation`, `product_category_name_translation`.
- **Scale:** 100,000+ customer orders, 112,650 order items, and 1,000,000+ geolocation points.
- **Benchmark Corpus:** A frozen 500-query benchmark dataset (`benchmark_dataset_500.json`) stratified across 8 business domains and 3 difficulty tiers (Easy: 114, Medium: 276, Hard: 110).

### 4.2 Evaluation Metrics & Methodological Definitions
- **Result Equivalence Rate under the Study Comparator (95% Wilson CI):** Evaluates whether executed SQL results match ground-truth result sets under row-order invariance (comparing row multisets via item Counters) with numerical tolerance ($\\epsilon=0.01$) and string whitespace normalization. Positional column semantics are preserved. *Result equivalence is an empirical evaluation criterion under the study comparator, not a formal mathematical proof of semantic correctness.*
- **Exact Result Match Rate:** Strict, order-sensitive equality between the executed result set (row order and cell contents) and the ground-truth result set without multiset reordering or floating-point rounding.
- **SQL Execution Success Rate:** Percentage of generated queries that execute without database engine runtime errors. Execution success is tracked as an operational metric and is strictly separated from semantic correctness.
- **Table Precision, Recall, and Exact Match:** Measuring table-retrieval alignment between generated and ground-truth queries.

---

## 5. Main Benchmark Results & Ablation

### 5.1 Headline Performance
Table 1 summarizes the headline results audited directly from raw per-query benchmark records.

| Metric | Phase 10 Live Run ($N=500$) | 95% Confidence Interval | Methodological Verification |
| :--- | :---: | :---: | :--- |
| **Result Equivalence Rate under Study Comparator** | **73.40%** (367 / 500) | **[69.26%, 77.18%]** | Wilson Score (continuity-corrected) |
| *Clopper-Pearson Exact CI* | 73.40% (367 / 500) | [69.30%, 77.22%] | Clopper-Pearson Exact Binomial |
| **Exact Result Match Rate** | **31.00%** (155 / 500) | [27.01%, 35.29%] | Strict Row/Header Order Equality |
| **SQL Execution Success Rate** | **100.00%** (500 / 500) | [99.05%, 100.00%] | Zero Database Runtime Exceptions |
| **Table Exact Match Accuracy** | **82.60%** (413 / 500) | [78.96%, 85.74%] | Wilson Score (continuity-corrected) |
| **Table Precision** | **93.07%** | — | Mean Macro Precision |
| **Table Recall** | **95.33%** | — | Mean Macro Recall |
| **Mean Latency** | **64.04s** | [61.27s, 66.90s] | BCa Bootstrap ($N=2000$) |
| **Median Latency ($p50$)** | **56.47s** | — | Empirical Percentile |
| **95th Percentile Latency ($p95$)** | **121.92s** | — | Empirical Percentile |

![Figure 2: Progression](figures/fig2_phase_accuracy_progression.png)
*Figure 2: Empirical Progression Across Development Milestones and Component Ablations.*

![Figure 3: Accuracy-Latency Trade-off](figures/fig3_pareto_frontier.png)
*Figure 3: Accuracy–Latency Trade-off with Cost-Scaled Configurations (marker size $\\propto$ cost).*

### 5.2 Domain and Difficulty Stratification

![Figure 5: Domain Performance Heatmap](figures/fig5_domain_difficulty_heatmap.png)
*Figure 5: Performance Stratification Across E-Commerce Business Domains and Difficulty Tiers (500 Queries).*

### 5.3 Controlled Component Ablation

| Configuration | Description | Execution Success | Result Equivalence | Table Exact Match | Mean Latency |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **Config A** | Baseline Schema RAG (No DAG Planner, No Verifier) | 99.0% | 19.0% | 76.0% | 14.2s |
| **Config B** | RAG + Structured DAG Planner (Verifier Disabled) | 34.0% | 15.0% | 81.0% | 38.6s |
| **Config C** | RAG + Planner + AST Structural Verifier & Repair | 65.0% | 26.0% | 83.0% | 61.2s |
| **Config D** | Full Pipeline (Planner + Verifier + Evaluator Agent) | **100.0%** | **73.4%** | **82.6%** | 64.0s |

*Statistical Findings:* In a matched paired McNemar test on 100 identical benchmark queries, Config C demonstrates a statistically significant improvement over Config B for result equivalence (exact binomial $p=0.0192 < 0.05$, $\\text{Odds Ratio}=3.75$, with 15 queries solved only by Config C vs. 4 solved only by Config B), establishing that AST-based structural verification significantly improves result equivalence over unverified planning.

---

## 6. Empirical Audit of Automated SQL Repair

![Figure 4: Repair Case Dynamics](figures/fig4_repair_dynamics.png)
*Figure 4: Granular Audit of the 101 Repair Cases (Panel A: Syntactic validity; Panel B: 4-Way Semantic Transitions).*

| Metric / Transition Category | Count | Percentage |
| :--- | :---: | :---: |
| **Total Repair Events Triggered** | 101 | 100.0% |
| **Repairs Successfully Applied** | 88 | 87.1% |
| **Post-Repair Syntax / Execution Valid** | 97 | 96.0% |
| **Post-Repair Semantically Equivalent** | 53 | 52.5% |
| **Maintained Correct (Valid Before & After)** | 49 | 48.5% |
| **Remained Incorrect (Failed Before & After)** | 26 | 25.7% |
| **Harmed / False-Positive Regressions** | **22** | **21.8%** |
| **Truly Recovered (Failed $\\rightarrow$ Correct)** | **4** | **4.0%** |

*Core Finding:* **Execution Success Is Not Semantic Recovery.** While 96.0% of post-repair queries execute cleanly, repair degraded 22 previously correct queries into incorrect ones while genuinely rescuing only 4.

---

## 7. AST-Level Failure Taxonomy

![Figure 7: Failure Taxonomy Distribution](figures/fig7_failure_taxonomy.png)
*Figure 7: Scientific Failure Taxonomy Distribution across 133 Non-Equivalent Queries.*

We analyzed all 133 non-equivalent queries using AST diffing against ground-truth SQL:
1. **Schema Missing Join Path (37 queries, 27.8% of errors / 7.4% of total):** Omission of intermediate bridging tables (e.g., joining `order_reviews` to `customers` without including `orders`).
2. **Semantic Filter Omission or Error (33 queries, 24.8% of errors / 6.6% of total):** Missing domain-specific predicates (e.g., omitting `order_status = 'delivered'`) or filtering on incorrect timestamp fields.
3. **Semantic Aggregation Mismatch (32 queries, 24.1% of errors / 6.4% of total):** Discrepancies in aggregation function types (e.g., `AVG` vs `SUM` or unrounded currency amounts).
4. **Schema Hallucinated Table (15 queries, 11.3% of errors / 3.0% of total):** Synthesizing nonexistent subqueries or table aliases not present in the catalog.
5. **Grain / GROUP BY Mismatch (14 queries, 10.5% of errors / 2.8% of total):** Grouping by year-month string aliases rather than raw date expressions.
6. **Semantic Ranking Order Mismatch (2 queries, 1.5% of errors / 0.4% of total):** Inverted or missing `ORDER BY` clauses in top-k rankings.

---

## 8. Robustness and Cross-Schema Transfer

### 8.1 Controlled Synthetic Perturbation Robustness

![Figure 6: Robustness Degradation](figures/fig6_robustness_degradation.png)
*Figure 6: Robustness Under Controlled Synthetic Perturbations ($N=50$ total; 10 queries per perturbation vector).*

| Perturbation Vector | Manipulation Description | Clean Acc | Perturbed Acc | Absolute $\\Delta\\text{Acc}$ | Retention Rate |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **Paraphrasing** | Rephrasing query phrasing while preserving semantics | 50.0% | 40.0% | -10.0% | **80.0%** |
| **Ranking Variants** | Inverting top-k / bottom-k ordering phrasing | 70.0% | 70.0% | 0.0% | **100.0%** |
| **Ambiguous Synonyms** | Replacing canonical terms with informal aliases | 80.0% | 80.0% | 0.0% | **100.0%** |
| **Temporal Shifts** | Shifting date intervals and seasonal quarters | 70.0% | 60.0% | -10.0% | **85.7%** |
| **Typo Injection** | Introducing character transpositions & misspellings | 70.0% | 40.0% | -30.0% | **57.1%** |

*Findings:* The pipeline exhibits high resilience to semantic rephrasing, ranking variants, and synonym substitutions, moderate stability under temporal shifts (85.7% retention), and pronounced vulnerability to typographical noise (57.1% retention, 30.0% absolute drop).

### 8.2 Cross-Schema Transfer Evaluation (Spider Probe)

| Evaluation Setting | Unique Databases | Sample Size ($N$) | Result Equivalence | Execution Success | Mean Latency |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **In-Domain Warehouse (Olist)** | 1 | 500 | **73.4%** | **100.0%** | 64.04s |
| **Spider Transfer Probe** | **20** | **50** | **18.0%** | **100.0%** | 72.66s |

*Key Findings:*
1. **Execution Robustness:** The pipeline maintains 100.0% execution success across all 20 external databases without crashing or raising unhandled exceptions.
2. **Transfer Bottlenecks:** Result equivalence drops to 18.0% (9/50 matches). Inspection of generated SQL traces indicates that schema-linking assumptions tuned to the domain-specific foreign-key graph were a major source of transfer failures alongside unannotated cross-table joins.
3. **Architectural Stop-Condition:** Strong performance in a controlled, explicitly modeled relational warehouse does not automatically transfer to heterogeneous unseen schemas without database-specific catalog introspection.

---

## 9. Discussion and Limitations

1. **Single Primary Relational Data Warehouse:** The primary 500-query benchmark is conducted on a multi-table relational e-commerce schema (Olist dataset, 9 tables, 100,000+ orders) with SQLite execution. Schema grounding assumptions tuned for this warehouse schema do not automatically translate to arbitrary domains.
2. **Cross-Schema Transfer Gap (18.0% Spider Result):** On the 20-database, 50-query Spider transfer probe, result equivalence dropped to 18.0%, demonstrating a pronounced semantic-generalization gap on heterogeneous external schemas.
3. **Sample Size of Transfer Probe:** The Spider transfer evaluation is a targeted 50-query stratified probe across 20 databases, not a full benchmark run.
4. **Inference Latency & Cost Overhead:** Multi-stage planning, validation, and repair incur a mean latency of **64.04s** ($p95$: 121.92s) and higher token usage compared to single-shot prompting (~7s).
5. **Hard Query Complexity Ceiling:** Result equivalence drops to **44.55%** on hard-tier queries and **32.56%** on complex aggregated multi-column tables, reflecting persistent challenges in multi-step CTE nesting and window-function synthesis.
6. **Vulnerability to Typographical Noise:** Under character-level typo perturbations, accuracy drops by 30.0% (57.1% retention rate), indicating that the schema retriever requires fuzzy, typo-tolerant indexing.
7. **False-Positive Repair Regressions:** 21.8% of repair attempts degraded previously correct queries in this setting, confirming that syntactic repair success is not equivalent to semantic recovery.
8. **Empirical Comparator Limits:** The row-multiset comparator is an empirical evaluation metric under the study comparator, not a formal proof of semantic correctness.
9. **Sub-study Sample Sizes:** Component ablations ($N=100$) and synthetic perturbation tests ($N=50$) use smaller samples than the main 500-query benchmark.

---

## 10. Open Science and Reproducibility

All code, benchmark definitions, evaluation scripts, and manuscript sources are open-source for full reproducibility:
- Complete reproduction instructions in `REPRODUCIBILITY.md`.
- Deterministic database constructor in `data/build_database.py`.
- Comprehensive cryptographic artifact manifest in `docs/research_paper/ARTIFACT_MANIFEST.json`.
- Verified MIT code license and Olist CC BY-NC-SA 4.0 data attribution in `LICENSE`.

---

## 11. Conclusion

In this study, we investigated the architectural mechanisms governing the reliability of LLM-generated analytical SQL over a public relational e-commerce data warehouse. On an audited 500-query benchmark, our multi-stage pipeline achieved a **73.40% Result Equivalence Rate under the study comparator** and **100.00% SQL Execution Success**. Our controlled component ablation demonstrated that adding AST-based structural verification provides a statistically significant improvement over unverified planning (Config C 26.0% vs. Config B 15.0%, exact $p=0.0192$, $\\text{OR}=3.75$). However, an exhaustive audit of 101 repair cases revealed that automated self-repair is a double-edged mechanism, producing **22 harmful false-positive regressions** against only **4 genuine recoveries**. Furthermore, the Spider transfer probe shows that these reliability gains are not automatically preserved under unseen schemas, with result equivalence falling to 18.0% despite maintaining 100.0% execution success. We conclude that conservative, uncertainty-aware structural verification is preferable to unconstrained automated repair loops.
"""


def build_conference_pdf(doc_path: Path) -> Path:
    """Build a professional, compact two-column conference research paper PDF."""
    md_file = doc_path / "PAPER_DRAFT.md"
    pdf_file = doc_path / "paper.pdf"
    
def build_conference_pdf(md_text: str, output_pdf: Path) -> Path:
    """Compile paper markdown into an official IEEEtran conference-style two-column PDF."""
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import BaseDocTemplate, PageTemplate, Frame, FrameBreak, NextPageTemplate, Paragraph, Spacer, Table, TableStyle, Image, KeepTogether
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT

    doc_path = output_pdf.parent
    figures_dir = doc_path / "figures"
    pdf_file = output_pdf

    # Page Geometry (US Letter: 612 x 792 pt, standard IEEE margins)
    PAGE_W, PAGE_H = letter
    MARGIN_LEFT = 40
    MARGIN_RIGHT = 40
    MARGIN_TOP = 50
    MARGIN_BOTTOM = 50
    
    PRINT_W = PAGE_W - MARGIN_LEFT - MARGIN_RIGHT  # 532 pt
    COL_GAP = 18
    COL_W = (PRINT_W - COL_GAP) / 2               # 257 pt
    PRINT_H = PAGE_H - MARGIN_TOP - MARGIN_BOTTOM  # 692 pt
    
    TITLE_FRAME_H = 105
    COL_PAGE1_H = PRINT_H - TITLE_FRAME_H - 12    # 575 pt

    # Frames for Page 1
    f_top = Frame(MARGIN_LEFT, PAGE_H - MARGIN_TOP - TITLE_FRAME_H, PRINT_W, TITLE_FRAME_H, id="TitleFrame",
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    f_c1_p1 = Frame(MARGIN_LEFT, MARGIN_BOTTOM, COL_W, COL_PAGE1_H, id="Col1_P1",
                    leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    f_c2_p1 = Frame(MARGIN_LEFT + COL_W + COL_GAP, MARGIN_BOTTOM, COL_W, COL_PAGE1_H, id="Col2_P1",
                    leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)

    # Frames for Page 2+
    f_c1_later = Frame(MARGIN_LEFT, MARGIN_BOTTOM, COL_W, PRINT_H, id="Col1_Later",
                       leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    f_c2_later = Frame(MARGIN_LEFT + COL_W + COL_GAP, MARGIN_BOTTOM, COL_W, PRINT_H, id="Col2_Later",
                       leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)

    # Header and Footer (Clean IEEE conference style)
    def add_page_decorations(canvas, doc):
        canvas.saveState()
        canvas.setFont("Times-Roman", 8)
        canvas.setFillColor(colors.HexColor("#475569"))
        if doc.page > 1:
            canvas.drawString(MARGIN_LEFT, PAGE_H - 30, "M. Jose: Engineering Reliable LLM-Based Data Analysis")
            canvas.drawRightString(PAGE_W - MARGIN_RIGHT, PAGE_H - 30, f"{doc.page}")
        canvas.restoreState()

    template_page1 = PageTemplate(id="FirstPage", frames=[f_top, f_c1_p1, f_c2_p1], onPage=add_page_decorations)
    template_later = PageTemplate(id="TwoCol", frames=[f_c1_later, f_c2_later], onPage=add_page_decorations)

    doc = BaseDocTemplate(
        str(pdf_file),
        pagesize=letter,
        leftMargin=MARGIN_LEFT,
        rightMargin=MARGIN_RIGHT,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
        pageTemplates=[template_page1, template_later]
    )

    # Typography Styles
    title_style = ParagraphStyle(
        "IEEETitle",
        fontName="Times-Bold",
        fontSize=15,
        leading=18,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#000000"),
    )
    author_style = ParagraphStyle(
        "IEEEAuthor",
        fontName="Times-Roman",
        fontSize=9.5,
        leading=12,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#000000"),
    )
    abstract_style = ParagraphStyle(
        "IEEEAbstract",
        fontName="Times-Roman",
        fontSize=8.5,
        leading=10.8,
        alignment=TA_JUSTIFY,
        spaceAfter=4,
        textColor=colors.HexColor("#000000"),
    )
    keywords_style = ParagraphStyle(
        "IEEEKeywords",
        fontName="Times-Roman",
        fontSize=8.5,
        leading=10.8,
        alignment=TA_JUSTIFY,
        spaceAfter=6,
        textColor=colors.HexColor("#000000"),
    )
    h1_style = ParagraphStyle(
        "IEEEH1",
        fontName="Times-Bold",
        fontSize=9.0,
        leading=11.5,
        alignment=TA_CENTER,
        spaceBefore=7,
        spaceAfter=2.5,
        textColor=colors.HexColor("#000000"),
        keepWithNext=True,
    )
    h2_style = ParagraphStyle(
        "IEEEH2",
        fontName="Times-Italic",
        fontSize=8.5,
        leading=11.0,
        alignment=TA_LEFT,
        spaceBefore=5,
        spaceAfter=1.5,
        textColor=colors.HexColor("#000000"),
        keepWithNext=True,
    )
    body_style = ParagraphStyle(
        "IEEEBody",
        fontName="Times-Roman",
        fontSize=8.5,
        leading=10.8,
        alignment=TA_JUSTIFY,
        spaceAfter=3,
        textColor=colors.HexColor("#000000"),
    )
    bullet_style = ParagraphStyle(
        "IEEEBullet",
        fontName="Times-Roman",
        fontSize=8.5,
        leading=10.8,
        leftIndent=8,
        firstLineIndent=-5,
        spaceAfter=1.5,
        textColor=colors.HexColor("#000000"),
    )
    quote_style = ParagraphStyle(
        "IEEEQuote",
        fontName="Times-Italic",
        fontSize=8.5,
        leading=10.8,
        alignment=TA_CENTER,
        leftIndent=6,
        rightIndent=6,
        spaceBefore=2,
        spaceAfter=3,
        textColor=colors.HexColor("#000000"),
    )
    caption_style = ParagraphStyle(
        "IEEECaption",
        fontName="Times-Italic",
        fontSize=7.5,
        leading=9.2,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#1e293b"),
        spaceBefore=1.5,
        spaceAfter=3.5,
        keepWithNext=True,
    )
    table_num_style = ParagraphStyle(
        "IEEETableNum",
        fontName="Times-Bold",
        fontSize=7.5,
        leading=9.0,
        alignment=TA_CENTER,
        spaceBefore=2,
        spaceAfter=0.5,
        keepWithNext=True,
    )
    table_title_style = ParagraphStyle(
        "IEEETableTitle",
        fontName="Times-Roman",
        fontSize=7.0,
        leading=8.5,
        alignment=TA_CENTER,
        spaceBefore=0.5,
        spaceAfter=2,
        keepWithNext=True,
    )
    table_cell = ParagraphStyle(
        "IEEETC",
        fontName="Times-Roman",
        fontSize=6.8,
        leading=8.2,
        textColor=colors.HexColor("#000000"),
    )
    table_hdr = ParagraphStyle(
        "IEEETH",
        fontName="Times-Bold",
        fontSize=6.8,
        leading=8.2,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#000000"),
    )

    def inline_fmt(txt: str) -> str:
        # Normalize escaped dollar signs
        txt = txt.replace(r"\$", "$")
        txt = txt.replace(r"\rightarrow", " &rarr; ")
        txt = txt.replace(r"$\rightarrow$", " &rarr; ")
        txt = txt.replace(r"\Delta\text{Acc}", "&Delta;Acc")
        txt = txt.replace(r"$\Delta\text{Acc}$", "&Delta;Acc")
        txt = txt.replace(r"\text{OR}", "OR")
        txt = txt.replace(r"$\text{OR}=3.75$", "OR = 3.75")
        txt = txt.replace(r"\text{Odds Ratio}", "Odds Ratio")
        txt = txt.replace(r"$\text{Odds Ratio}=3.75$", "Odds Ratio = 3.75")
        txt = txt.replace(r"\epsilon", "&epsilon;")
        txt = txt.replace(r"$\epsilon=0.01$", "&epsilon; = 0.01")
        txt = txt.replace(r"\propto", "&prop;")
        txt = txt.replace(r"$\propto$", "&prop;")
        txt = txt.replace(r"$p=0.0192$", "<i>p</i> = 0.0192")
        txt = txt.replace(r"$p_{50}$", "<i>p</i><sub>50</sub>")
        txt = txt.replace(r"($p_{50}$", "(<i>p</i><sub>50</sub>")
        txt = txt.replace(r"$p_{95}$", "<i>p</i><sub>95</sub>")
        txt = txt.replace(r"($p_{95}$", "(<i>p</i><sub>95</sub>")
        txt = txt.replace(r"$p50$", "<i>p</i><sub>50</sub>")
        txt = txt.replace(r"($p50$", "(<i>p</i><sub>50</sub>")
        txt = txt.replace(r"$p95$", "<i>p</i><sub>95</sub>")
        txt = txt.replace(r"($p95$", "(<i>p</i><sub>95</sub>")
        txt = txt.replace(r"$N=500$", "<i>N</i> = 500")
        txt = txt.replace(r"($N=500$)", "(<i>N</i> = 500)")
        txt = txt.replace(r"$N=100$", "<i>N</i> = 100")
        txt = txt.replace(r"($N=100$)", "(<i>N</i> = 100)")
        txt = txt.replace(r"$N=50$", "<i>N</i> = 50")
        txt = txt.replace(r"($N=50$)", "(<i>N</i> = 50)")
        txt = txt.replace(r"$N=2000$", "<i>N</i> = 2000")
        txt = txt.replace(r"($N=2000$)", "(<i>N</i> = 2000)")
        txt = txt.replace(r"(\$N=500\$)", "(<i>N</i> = 500)")
        txt = txt.replace(r"(\$N=100\$)", "(<i>N</i> = 100)")
        txt = txt.replace(r"(\$N=50\$)", "(<i>N</i> = 50)")
        txt = txt.replace(r"(\$N=2000\$)", "(<i>N</i> = 2000)")
        txt = txt.replace(r"(\$p50\$:", "(<i>p</i><sub>50</sub>:")
        txt = txt.replace(r"\$p50\$", "<i>p</i><sub>50</sub>")
        txt = txt.replace(r"\$p95\$", "<i>p</i><sub>95</sub>")
        txt = txt.replace(r"\$N=500\$", "<i>N</i> = 500")
        txt = txt.replace(r"\$N=100\$", "<i>N</i> = 100")
        txt = txt.replace(r"\$N=50\$", "<i>N</i> = 50")
        txt = txt.replace(r"\$p=0.0192\$", "<i>p</i> = 0.0192")
        txt = txt.replace(r"\$p=0.0192 < 0.05\$", "<i>p</i> = 0.0192 &lt; 0.05")
        txt = txt.replace(r"$p=0.0192 < 0.05$", "<i>p</i> = 0.0192 &lt; 0.05")
        txt = txt.replace(r"\Delta\text{Acc}", "&Delta;Acc")
        txt = txt.replace(r"\$\Delta\text{Acc}\$", "&Delta;Acc")
        txt = txt.replace(r"\text{OR}=3.75", "OR = 3.75")
        txt = txt.replace(r"\text{Odds Ratio}=3.75", "Odds Ratio = 3.75")
        txt = txt.replace(r"\epsilon=0.01", "&epsilon; = 0.01")
        txt = txt.replace(r"\$\epsilon=0.01\$", "&epsilon; = 0.01")
        txt = txt.replace(r"\rightarrow", " &rarr; ")
        txt = txt.replace(r"\$rightarrow\$", " &rarr; ")
        txt = txt.replace(r"\$propto\$", "&prop;")
        
        # HTML tag formatting
        txt = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", txt)
        txt = re.sub(r"\*(.*?)\*", r"<i>\1</i>", txt)
        txt = re.sub(r"`(.*?)`", r'<font face="Courier" size="7.0">\1</font>', txt)
        txt = txt.replace("$", "")
        return txt

    story = []

    # Title & Author Block (Spanning top frame)
    story.append(Paragraph("Engineering Reliable LLM-Based Data Analysis: An Empirical Study of Schema Grounding, Planning, Verification, and SQL Repair", title_style))
    story.append(Spacer(1, 4))
    story.append(Paragraph("<b>Mevin Jose</b><br/><i>Independent Researcher</i><br/><font face=\"Courier\" size=\"7.5\">mevin.research@gmail.com</font>", author_style))
    story.append(NextPageTemplate("TwoCol"))
    story.append(FrameBreak())

    # Abstract & Index Terms in Left Column of Page 1
    abs_text = (
        "While Large Language Models (LLMs) demonstrate notable code-generation capabilities, "
        "translating natural language questions into reliable analytical SQL over relational databases (Text-to-SQL) "
        "remains brittle in practice. In this paper, we investigate the empirical mechanisms governing Text-to-SQL reliability: "
        "<b>structural verification improves query reliability, whereas aggressive automated repair can introduce substantial semantic regressions</b>. "
        "We evaluate a multi-stage reliability pipeline on a frozen 500-query benchmark across 8 business domains over a public relational "
        "e-commerce data warehouse (the Olist dataset, 9 tables, 100,000+ orders). Our system achieves a <b>73.40% Result Equivalence Rate "
        "under the study comparator</b> (367/500 queries, 95% Wilson Score CI: [69.26%, 77.18%], Clopper-Pearson Exact CI: [69.30%, 77.22%]), "
        "<b>31.00% Exact Result Match</b>, and <b>100.00% SQL Execution Success</b> with a mean latency of 64.04s (<i>p</i><sub>50</sub>: 56.47s, <i>p</i><sub>95</sub>: 121.92s). "
        "In a controlled 4-way 100-query ablation, activating deterministic Abstract Syntax Tree (AST) structural verification significantly "
        "improves result equivalence over unverified planning (Config C 26.0% vs. Config B 15.0%, McNemar exact <i>p</i> = 0.0192, Odds Ratio = 3.75). "
        "However, an exhaustive audit of all 101 repair events reveals that automated self-repair is a double-edged mechanism: while 97 of 101 "
        "post-repair queries (96.0%) were syntactically valid and preserved 49 already-correct queries, repair yielded only 4 genuine recoveries "
        "while inducing <b>22 harmful false-positive regressions</b> (21.8% of repair events) where previously correct queries were degraded. "
        "Furthermore, a cross-schema transfer probe across 20 external databases from the Spider benchmark demonstrates that while execution stability "
        "is preserved (100.0%), result equivalence drops to <b>18.0%</b> (9/50), highlighting the gap between in-domain grounding and zero-shot schema transfer. "
        "We conclude that conservative, uncertainty-aware structural verification is preferable to unconstrained automated repair loops."
    )
    story.append(Paragraph(f"<b><i>Abstract</i>&mdash;</b>{abs_text}", abstract_style))
    story.append(Paragraph("<b><i>Index Terms</i>&mdash;Text-to-SQL, LLM Reliability, Structural Verification, Automated Query Repair, AST, Empirical Software Engineering.</b>", keywords_style))

    # Parse remaining body lines from PAPER_DRAFT.md
    lines = md_text.splitlines()
    in_table = False
    table_rows = []
    
    body_lines = []
    skip = True
    for l in lines:
        if l.strip().startswith("## I. Introduction"):
            skip = False
        if not skip:
            body_lines.append(l)

    idx = 0
    while idx < len(body_lines):
        line = body_lines[idx]
        s = line.strip()
        
        if in_table:
            if s.startswith("|") and "|" in s[1:]:
                cells = [c.strip() for c in s.split("|")[1:-1]]
                if not all(set(c).issubset({"-", ":", " "}) for c in cells):
                    table_rows.append(cells)
                idx += 1
                continue
            else:
                in_table = False
                if table_rows:
                    hdr = [Paragraph(inline_fmt(c), table_hdr) for c in table_rows[0]]
                    body = [[Paragraph(inline_fmt(c), table_cell) for c in r] for r in table_rows[1:]]
                    num_cols = len(table_rows[0])
                    
                    if num_cols == 4:
                        # Table 1: [Metric, Score, 95% CI, Methodological Verification]
                        col_w = [70, 48, 62, 77]
                    elif num_cols == 6 and "Config" in table_rows[0][0]:
                        # Table 2: [Config, Description, Exec, Equiv, Table EM, Latency]
                        col_w = [39, 63, 40, 40, 40, 35]
                    elif num_cols == 3:
                        # Table 3: [Metric / Category, Count, Percentage]
                        col_w = [147, 45, 65]
                    elif num_cols == 6 and "Perturbation" in table_rows[0][0]:
                        # Table 4: [Vector, Description, Clean, Perturb, Delta, Retention]
                        col_w = [48, 67, 34, 36, 36, 36]
                    elif num_cols == 6 and "Evaluation" in table_rows[0][0]:
                        # Table 5: [Setting, DBs, N, Equiv, Exec, Latency]
                        col_w = [62, 35, 38, 42, 42, 38]
                    else:
                        col_w = [COL_W / num_cols] * num_cols

                    t = Table([hdr] + body, colWidths=col_w)
                    t.setStyle(TableStyle([
                        ("LINEABOVE", (0,0), (-1,0), 1.0, colors.HexColor("#000000")),
                        ("LINEBELOW", (0,0), (-1,0), 0.5, colors.HexColor("#000000")),
                        ("LINEBELOW", (0,-1), (-1,-1), 1.0, colors.HexColor("#000000")),
                        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
                        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.HexColor("#ffffff"), colors.HexColor("#f8fafc")]),
                        ("TOPPADDING", (0,0), (-1,-1), 1.2),
                        ("BOTTOMPADDING", (0,0), (-1,-1), 1.2),
                        ("LEFTPADDING", (0,0), (-1,-1), 2.0),
                        ("RIGHTPADDING", (0,0), (-1,-1), 2.0),
                    ]))
                    story.append(Spacer(1, 1))
                    story.append(t)
                    story.append(Spacer(1, 2.5))
                table_rows = []

        if not s:
            idx += 1
            continue
        
        if s.lower().startswith("## references"):
            # Break to dedicated IEEE references renderer
            break
        
        if s.startswith("## "):
            story.append(Spacer(1, 4))
            heading_p = Paragraph(inline_fmt(s[3:].upper()), h1_style)
            story.append(KeepTogether([heading_p]))
            idx += 1
        elif s.startswith("### "):
            story.append(Paragraph(f"<i>{inline_fmt(s[4:])}</i>", h2_style))
            idx += 1
        elif s.startswith("**TABLE ") and s.endswith("**"):
            # Table Title in IEEE style
            t_num = s[2:-2]
            t_title = ""
            if idx + 1 < len(body_lines) and body_lines[idx+1].strip().startswith("*") and body_lines[idx+1].strip().endswith("*"):
                t_title = body_lines[idx+1].strip()[1:-1]
                idx += 1
            story.append(Paragraph(t_num, table_num_style))
            if t_title:
                story.append(Paragraph(inline_fmt(t_title).upper(), table_title_style))
            idx += 1
        elif s.startswith("![") and "](" in s:
            img_rel = s.split("(")[1].split(")")[0]
            img_p = doc_path / img_rel
            
            # Check if next line is caption
            caption_p = None
            if idx + 1 < len(body_lines) and (body_lines[idx+1].strip().startswith("*Fig.") or body_lines[idx+1].strip().startswith("*Figure")):
                caption_txt = body_lines[idx+1].strip()[1:-1]
                caption_p = Paragraph(inline_fmt(caption_txt), caption_style)
                idx += 1  # consume caption line
            
            if img_p.exists():
                # Single-column figure width: 250 pt, proportional height
                img_flowable = Image(str(img_p), width=COL_W, height=108)
                if caption_p:
                    story.append(KeepTogether([Spacer(1, 1.5), img_flowable, caption_p, Spacer(1, 2)]))
                else:
                    story.append(KeepTogether([Spacer(1, 1.5), img_flowable, Spacer(1, 2)]))
            idx += 1
        elif (s.startswith("*Fig.") or s.startswith("*Figure")) and s.endswith("*"):
            story.append(Paragraph(inline_fmt(s[1:-1]), caption_style))
            idx += 1
        elif s.startswith("|") and "|" in s[1:]:
            in_table = True
            table_rows.append([c.strip() for c in s.split("|")[1:-1]])
            idx += 1
        elif s.startswith("- ") or s.startswith("* "):
            story.append(Paragraph(f"&bull; {inline_fmt(s[2:])}", bullet_style))
            idx += 1
        elif re.match(r"^\d+\.\s+", s):
            m = re.match(r"^(\d+\.)\s+(.*)", s)
            story.append(Paragraph(f"<b>{m.group(1)}</b> {inline_fmt(m.group(2))}", bullet_style))
            idx += 1
        elif s.startswith("> "):
            story.append(Paragraph(f"<i>{inline_fmt(s[2:])}</i>", quote_style))
            idx += 1
        elif s == "---":
            idx += 1
        else:
            story.append(Paragraph(inline_fmt(s), body_style))
            idx += 1

    # Add References Section
    story.append(Spacer(1, 4))
    ref_head = Paragraph("REFERENCES", h1_style)
    story.append(KeepTogether([ref_head]))
    
    ref_style = ParagraphStyle(
        "IEEERef",
        fontName="Times-Roman",
        fontSize=7.5,
        leading=9.5,
        leftIndent=8,
        firstLineIndent=-8,
        spaceAfter=2,
        textColor=colors.HexColor("#000000"),
    )
    refs = [
        "[1] T. Yu, R. Zhang, K. Yang, M. Yasunaga, D. Wang, Z. Li, et al., \"Spider: A large-scale human-labeled dataset for complex and cross-domain semantic parsing and text-to-sql,\" in <i>Proc. EMNLP</i>, 2018.",
        "[2] J. Li, B. Hui, G. Qu, J. Yang, B. Li, B. Wang, et al., \"Can llm already serve as a database interface? a bird's eye view of text-to-sql benchmarks,\" in <i>Proc. NeurIPS</i>, 2023.",
        "[3] M. Pourreza and D. Rafiei, \"DIN-SQL: Decomposed in-context learning of text-to-sql with self-correction,\" in <i>Proc. NeurIPS</i>, 2023.",
        "[4] B. Wang, C. Zhang, Z. Yang, M. Zhang, B. Qin, and T. Liu, \"MAC-SQL: A multi-agent collaborative framework for text-to-sql,\" <i>arXiv preprint arXiv:2403.11181</i>, 2024.",
        "[5] S. Talaei, M. Pourreza, Y. Chang, A. Mirhoseini, and D. Rafiei, \"CHESS: Contextual harnessing for efficient sql synthesis,\" <i>arXiv preprint arXiv:2405.16755</i>, 2024.",
        "[6] D. Gao, H. Wang, Y. Li, X. Xi, Y. Chen, H. Shen, et al., \"Text-to-sql empowered by large language models: A benchmark evaluation,\" <i>PVLDB</i>, vol. 17, no. 5, pp. 1132-1145, 2023.",
        "[7] P. Lewis, E. Perez, A. Piktus, F. Petroni, V. Karpukhin, N. Goyal, et al., \"Retrieval-augmented generation for knowledge-intensive nlp tasks,\" in <i>Proc. NeurIPS</i>, 2020.",
        "[8] S. Yao, J. Zhao, D. Yu, N. Du, I. Shafran, K. Narasimhan, and Y. Cao, \"ReAct: Synergizing reasoning and acting in language models,\" in <i>Proc. ICLR</i>, 2023.",
        "[9] N. Shinn, F. Cassano, E. Berman, A. Gopinath, K. Narasimhan, and S. Yao, \"Reflexion: Language agents with verbal reinforcement learning,\" in <i>Proc. NeurIPS</i>, 2023.",
        "[10] Q. McNemar, \"Note on the sampling error of the difference between correlated proportions or percentages,\" <i>Psychometrika</i>, vol. 12, no. 2, pp. 153-157, 1947.",
    ]
    for r in refs:
        story.append(Paragraph(r, ref_style))

    doc.build(story)
    print(f"Successfully compiled IEEE conference paper PDF: {pdf_file} ({pdf_file.stat().st_size} bytes)")
    return pdf_file


def render_pdf_pages_to_images(pdf_path: Path, output_dir: Path) -> list[Path]:
    """Render each page of the PDF into high-resolution PNG images for visual inspection."""
    doc = fitz.open(str(pdf_path))
    image_paths = []
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Rendering {len(doc)} pages of {pdf_path.name} to PNG for visual inspection...")
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        # Render at 200 DPI for crisp visual inspection
        pix = page.get_pixmap(dpi=200)
        img_file = output_dir / f"page_{page_num + 1}.png"
        pix.save(str(img_file))
        image_paths.append(img_file)
        print(f"  Page {page_num + 1} saved: {img_file.name} ({img_file.stat().st_size} bytes)")
    
    return image_paths


def main():
    output_dir = ROOT / "docs" / "research_paper"
    
    # 0. Sync clean conference markdown manuscript from PAPER_DRAFT.md
    md_file = output_dir / "PAPER_DRAFT.md"
    md_text = md_file.read_text(encoding="utf-8")
    
    # 1. Compile figures, tables, and macros from empirical records
    compiler = PaperArtifactCompiler(output_dir=output_dir)
    res = compiler.compile_all(workspace_root=ROOT)
    print("Paper compilation result:", res)
    
    # 2. Build conference paper PDF
    pdf_path = output_dir / "paper.pdf"
    build_conference_pdf(md_text, pdf_path)

    
    # 3. Render all pages to images for inspection
    inspect_dir = output_dir / "rendered_pages"
    rendered_images = render_pdf_pages_to_images(pdf_path, inspect_dir)
    print(f"All {len(rendered_images)} pages rendered to {inspect_dir}")


if __name__ == "__main__":
    main()


