# Reproducibility Guide

This guide provides exact, deterministic instructions to reproduce all empirical evaluations, statistical analyses, figures, tables, and the manuscript package from a clean checkout.

---

## 1. Environment Setup

### System Requirements
- Python 3.11 or higher
- SQLite 3.35+
- (Optional for PDF generation) TeX Live / pdflatex

### Installation
```bash
# Clone the repository
git clone https://github.com/MJenius/AI-Data-Analyst-Agent.git
cd AI-Data-Analyst-Agent

# Create and activate virtual environment
python -m venv .venv
# On Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# On macOS/Linux:
source .venv/bin/activate

# Install package with research & evaluation dependencies
pip install -e ".[research,dev]"
```

---

## 2. Dataset Acquisition & Database Construction

The evaluation relies on the Brazilian E-Commerce Public Dataset by Olist (available on Kaggle under CC BY-NC-SA 4.0).

### Method A: Build from Source CSVs
1. Download the 9 CSV files from Kaggle:
   `https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce`
2. Place the unzipped CSV files into `data/olist/`.
3. Run the deterministic SQLite build script:
   ```bash
   python data/build_database.py
   ```
4. Verify database checksum:
   - Expected path: `data/analytics.db`
   - Expected SHA-256: `8550c4cc6d670aa0441bc898e47a57a40001858fc3f13dc5cb16fb90ca11c130`

---

## 3. Running Unit and Regression Tests

Run the full automated test suite:
```bash
pytest tests/ -v
```
All unit tests, including result-equivalence multiset checks, schema grounding tests, and error taxonomy classifications should pass with zero failures.

---

## 4. Benchmark Validation & Integrity Checks

Validate benchmark dataset consistency, foreign-key relationships, and SQL syntax:
```bash
python tests/evaluation/validate_500_dataset.py
```
- Expected benchmark path: `tests/evaluation/benchmark_dataset_500.json`
- Expected SHA-256: `0c9807d5867ff9cb6a9252437dab31660b62b2e6c9d09c5e54b1dfc7edc43e04`

---

## 5. Running Evaluations

### A. Live Benchmark Evaluation (Requires LLM API Key)
Set your API key in `.env`:
```env
GROQ_API_KEY=your_key_here
GEMINI_API_KEY=your_key_here
LLM_PROVIDER=auto
```

Run the 500-query benchmark with configurable concurrency:
```bash
python tests/evaluation/run_benchmark_phase10.py --dataset tests/evaluation/benchmark_dataset_500.json --workers 4
```

### B. 4-Way Controlled Component Ablation Study (100 Queries)
Run all 4 configurations with strictly controlled verifier toggles:
```bash
python tests/evaluation/run_ablation_study.py --configs rag_only rag_planner rag_planner_verifier full_system --workers 4
```

### C. Offline Re-Scoring (Deterministic, No API Calls Needed)
To re-score raw stored executions with the exact multiset equivalence metric:
```bash
python tests/evaluation/rescore_500_benchmark.py
```

---

## 6. Regenerating Figures, Tables, and LaTeX Macros

Regenerate all publication artifacts from the latest evaluation summary:
```bash
python src/agent_platform/experiments/paper_generator.py --run-all
```
Outputs:
- Figures 1–7 in `docs/research_paper/figures/` (PDF, SVG, 300 DPI PNG)
- Tables in `docs/research_paper/tables/`
- LaTeX macros in `docs/research_paper/macros.tex`

---

## 7. Compiling the LaTeX Manuscript

```bash
cd docs/research_paper/latex
pdflatex main.tex
bibtex main
pdflatex main.tex
pdflatex main.tex
```
The compiled output `main.pdf` contains the full 13-section publication manuscript.
