# AI Data Analyst Agent ⚡

An agentic AI system that performs autonomous data analysis using planning, schema-aware SQL generation, and multi-step evaluation.

## 🚀 One-Line Pitch
"An autonomous agent that reasons over structured databases to answer complex business questions with full traceability and SQL verification."

## 📺 Demo
![Demo UI Screenshot](docs/screenshots/ui_demo.png)

### Example Input:
> "Why did revenue drop in March?"

### Agent Output:
- **Executive Summary**: Analysis of revenue trends across product categories.
- **Key Findings**: Identification of specific products with the largest month-over-month declines.
- **SQL Evidence**: Validated SQL queries executed against the live database.
- **Reasoning Trace**: A step-by-step look into the agent's thought process.

## 🏗️ Architecture
The system follows a **Plan-Execute-Evaluate** loop:

1. **Planner Agent**: Analyzes the user question and database schema to create a logical sequence of analytical steps.
2. **Schema Retriever (RAG)**: Uses FAISS and embeddings to retrieve the most relevant table schemas and business definitions for the current step.
3. **Executor Agent**: Generates optimized SQL using Groq LLM, validates it for safety/syntax, and executes it against SQLite.
4. **Evaluator Agent**: Inspects the results, assigns a confidence score, and provides a final verdict on the accuracy of the analysis.

## ✨ Key Features
- **Semantic RAG**: Schema-aware retrieval ensures the LLM only sees relevant table context, reducing token costs and hallucinations.
- **SQL Validation & Retry**: Automatic detection of hallucinated columns/tables with self-correction logic.
- **Multi-Step Orchestration**: Handles complex questions that require multiple queries and data joins.
- **High Observability**: Every run is traced with timing and reasoning metadata, viewable in a polished UI.
- **Performance Optimized**: Cached embeddings and reused vector indices for sub-second planning.

## 🛠️ Tech Stack
- **Backend**: Python, FastAPI
- **LLM Reasoning**: Groq (Llama 3 70B)
- **Vector DB**: FAISS
- **Database**: SQLite
- **Observability**: Custom JSONL Tracing
- **Frontend**: Vanilla JS, Modern CSS (Premium Aesthetics)

## 🏃 How to Run

### 1. Setup Environment
```bash
# Clone the repository
git clone https://github.com/your-repo/ai-data-analyst.git
cd ai-data-analyst

# Install dependencies
pip install -e .
```

### 2. Configure API Keys
Create a `.env` file with your Groq API key:
```env
GROQ_API_KEY=your_key_here
ANALYTICS_DB_PATH=runtime/analytics.db
```

### 3. Run the Backend
```bash
python -m uvicorn apps.api.main:app --reload
```

### 4. Run the CLI Demo
```bash
python run_analysis.py "Show me the top 5 products by sales"
```

### 5. Open the UI
Simply open `apps/ui/index.html` in your browser.

## 📊 Example Demo Queries
- "Why did revenue drop in March?"
- "Which products drove the most revenue growth?"
- "Which region has the highest customer churn?"
- "Show top 5 products by sales"

---
*Built for Enterprise Data Teams*
