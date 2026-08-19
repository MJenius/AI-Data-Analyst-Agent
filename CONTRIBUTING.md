# Contributing Guidelines

Thank you for your interest in contributing to the AI Data Analyst Agent research project and codebase.

## Scientific and Code Standards

1. **Empirical Integrity**:
   - Never report fabricated metrics, simulated benchmarks, or unverified claims.
   - All evaluation claims must be grounded in raw execution logs and reproducible evaluation runs.
   - When modifying metrics or evaluation code (e.g., `compare_results`), always run regression tests and document semantic definitions clearly.

2. **Code Structure**:
   - Core agent logic resides in `src/agent_platform/`.
   - Experimental evaluation harnesses and benchmark datasets reside in `tests/evaluation/`.
   - Unit tests reside in `tests/unit/`.

3. **Development Workflow**:
   ```bash
   # 1. Create a virtual environment and install in editable mode with research dependencies
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\Activate.ps1
   pip install -e ".[research,dev]"

   # 2. Run unit tests
   pytest tests/unit/ -v

   # 3. Format and lint checks
   # Ensure clean imports, no unused variables, and PEP 8 compliance
   ```

4. **Submitting Changes**:
   - Open a pull request with a descriptive summary of scientific motivation or bug fixes.
   - Include test coverage for new functionality or bug fixes.
   - If experimental results are modified, document changes to affected figures and tables.
