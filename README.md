# Autonomous Enterprise Data Analysis via Semantic Schema Grounding, Plan Validation, and Multi-Turn SQL AST Repair

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Benchmark: 500 Queries](https://img.shields.io/badge/Benchmark-500%20Queries-green.svg)](tests/evaluation/benchmark_dataset_500.json)
[![LaTeX Paper](https://img.shields.io/badge/Manuscript-LaTeX%20Ready-red.svg)](docs/research_paper/latex/main.tex)

This repository contains the official implementation, evaluation harnesses, and publication artifacts for the research paper:  
**"Autonomous Enterprise Data Analysis via Semantic Schema Grounding, Plan Validation, and Multi-Turn SQL AST Repair"** (August 2026).

---

## 📌 Executive Summary

Enterprise natural language database querying (Text-to-SQL) routinely fails in production due to four structural obstacles: **schema grounding hallucinations**, **aggregation grain inconsistencies**, **SQL dialect traps**, and **agent hallucinatory drift**.

To resolve these failure modes, we present an autonomous multi-stage data analyst architecture that decomposes query synthesis into deterministic validation stages:
1. **Graph-Guided Semantic Schema RAG**: Precision table and column subgraph retrieval augmented with foreign-key traversal.
2. **DAG Query Planning \& Deterministic Validation**: Structural query plan generation with pre-execution catalog constraint verification.
3. **AST-Level Semantic Verifier \& Closed-Loop Repair**: Abstract Syntax Tree inspection via SQLGlot with targeted feedback for multi-turn grain and join correction.

---

## 📊 Audited Empirical Results (500-Query Benchmark)

Evaluated over the 100,000-order Brazilian E-Commerce data warehouse (Olist relational database, 9 tables) across 8 business domains:

| Metric | Empirical Value | 95% Confidence Interval | Evaluation Method |
| :--- | :---: | :---: | :--- |
| **Equivalent Match Rate** | **73.40%** (367 / 500) | **[69.26%, 77.18%]** | Wilson Score (continuity-corrected) |
| *Clopper-Pearson Exact CI* | 73.40% (367 / 500) | [69.30%, 77.22%] | Clopper-Pearson Exact |
| **Exact Match Rate** | **31.00%** (155 / 500) | [27.01%, 35.29%] | Wilson Score (cc) |
| **SQL Execution Success Rate** | **100.00%** (500 / 500) | [99.05%, 100.00%] | Wilson Score (cc) |
| **Table Exact Match Accuracy** | **82.60%** (413 / 500) | [78.96%, 85.74%] | Wilson Score (cc) |
| **Table Macro Precision** | **93.07%** | — | Macro-averaged table precision |
| **Table Macro Recall** | **95.33%** | — | Macro-averaged table recall |
| **Mean Latency** | **64.04s** | [61.27s, 66.90s] | BCa Bootstrap ($N=2000$) |
| **Provider Dropouts / Timeouts** | **0 / 0 / 0** | — | 100% Request Completion |

---

## 🔬 Key Scientific Insights

1. **Controlled Component Ablation**: Activating AST Semantic Verification yields an execution reliability increase from **34.0% to 65.0%** and an equivalent accuracy improvement from **15.0% to 26.0%** over unverified planners on identical 100-query instances.
2. **The Self-Repair Trade-Off**: An exhaustive audit of 101 repair events demonstrates that execution success ($\neq$ semantic correctness): while repair maintained 96.0% syntactic validity and preserved 49 valid queries, aggressive repair rules caused 22 false-positive regressions.
3. **Controlled Synthetic Robustness**: Evaluated across 5 perturbation vectors ($N=50$), achieving 100% retention under paraphrasing, synonym replacement, and ranking variants, with vulnerability under character-level typographical noise (57.1% retention).

---

## 🏗️ System Architecture

```
User Question
     │
     ▼
[1. Graph-Guided Schema RAG]  ◄───  FAISS Embeddings + Foreign Key Graph Traversal
     │ (Minimal schema subgraph: 93.1% precision, 95.3% recall)
     ▼
[2. Structured DAG Planner]   ───►  Synthesizes metric targets, grain, & join paths
     │
     ▼
[3. Deterministic Plan Validator]  Statically checks catalog & foreign-key paths
     │ (Prunes hallucinations prior to code generation)
     ▼
[4. SQL Generation & AST Verifier] SQLGlot dialect conversion, grain & fan-out checks
     │ ◄─── Closed-Loop Multi-Turn Repair Loop (up to 2 correction rounds)
     ▼
[5. Sandboxed SQLite DB Engine]    PRAGMA query_only = ON (100% execution reliability)
     │
     ▼
[6. Evaluator & Executive Summary] Formulates verified findings & confidence score
```

---

## 📁 Repository Structure

```text
├── docs/research_paper/          # Publication package
│   ├── latex/main.tex            # Full 13-section publication LaTeX manuscript
│   ├── latex/references.bib      # Complete bibliography
│   ├── figures/                  # Figures 1–7 (PDF, SVG, 300 DPI PNG)
│   ├── tables/                   # LaTeX tables
│   ├── macros.tex                # Auto-generated LaTeX macros
│   ├── PAPER_DRAFT.md            # Markdown companion manuscript
│   ├── SEMANTIC_AUDIT.md         # Pre-registered stratified human audit protocol
│   └── ARTIFACT_MANIFEST.json    # Cryptographic SHA-256 artifact manifest
├── src/agent_platform/           # Core library source code
│   ├── analytics/                # Multi-stage Planner, Executor, Evaluator agents
│   ├── experiments/              # Statistics, metrics, compare_results, failure taxonomy
│   ├── llms/                     # Resilient LLM cascade with automatic fallback
│   ├── rag/                      # Schema context builder & FAISS retriever
│   └── tools/                    # SQLTool, SQLSemanticVerifier, PlanValidator
├── tests/
│   ├── unit/                     # Unit test suite (multiset equivalence, linter, etc.)
│   └── evaluation/               # Benchmark dataset (500q), runner, ablation harness
├── data/
│   ├── schema.sql                # Relational DDL schema
│   └── build_database.py         # Deterministic SQLite database constructor
├── REPRODUCIBILITY.md            # Exact step-by-step reproduction instructions
├── CITATION.cff                  # Citation metadata
└── pyproject.toml                # Project specification & dependencies
```

---

## 🚀 Quickstart & Reproducibility

### 1. Installation
```bash
# Clone repository
git clone https://github.com/MJenius/AI-Data-Analyst-Agent.git
cd AI-Data-Analyst-Agent

# Setup virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\Activate.ps1

# Install package with research & dev dependencies
pip install -e ".[research,dev]"
```

### 2. Run Tests
```bash
pytest tests/unit/ -v
```

### 3. Run Benchmark Integrity Checks
```bash
python tests/evaluation/validate_500_dataset.py
```

### 4. Compile Publication Manuscript
```bash
cd docs/research_paper/latex
pdflatex main.tex
bibtex main
pdflatex main.tex
pdflatex main.tex
```

For complete instructions on acquiring the Olist dataset and running live evaluations, see **[REPRODUCIBILITY.md](REPRODUCIBILITY.md)**.

---

## 📜 License & Attribution

- **Code & Artifacts**: Licensed under the [MIT License](LICENSE).
- **Dataset Attribution**: The evaluation database is constructed from the [Brazilian E-Commerce Public Dataset by Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) on Kaggle, licensed under **CC BY-NC-SA 4.0**.

If you build upon this work, please cite:
```bibtex
@article{ai_data_analyst_2026,
  title={Autonomous Enterprise Data Analysis via Semantic Schema Grounding, Plan Validation, and Multi-Turn SQL AST Repair},
  author={Mevin Jose},
  year={2026},
  url={https://github.com/MJenius/AI-Data-Analyst-Agent}
}
```
