# Phase 4 experiment artifacts

Each child directory is one immutable experiment run on the audited 100-query
benchmark (`tests/evaluation/benchmark_dataset_v2.json`). It contains the exact
configuration snapshot, raw per-query outputs, summaries, and a generated report.

## Configurations

| Config ID | Description |
| :--- | :--- |
| `phase4_full_schema` | Full schema context (Phase 3 config2 control) |
| `phase4_current_top5` | Unchanged top-5 vector RAG (Phase 3 config3 control) |
| `phase4_improved_rag` | Hybrid table/column/business-term retrieval + join-path expansion |
| `phase4_plan_improved_rag` | Structured QueryPlan + improved RAG (diagnostic ablation) |

## Run the experiment

```powershell
$env:EXPERIMENT_LLM_PROVIDER = "nvidia"
$env:NVIDIA_MODEL = "nvidia/nemotron-3-super-120b-a12b"
$env:NVIDIA_API_KEY = "<your-key>"

.\.venv\Scripts\python.exe tests/evaluation/phase4/run_experiments.py --run-id run_YYYYMMDDTHHMMSSZ

# Options:
#   --limit 5                    # smoke test
#   --configs phase4_improved_rag  # single config
#   --resume                     # resume interrupted run
```

Outputs land in `results/phase4/<run-id>/` with `phase4_report.md`, `all_summaries.json`,
and per-config `raw_results.json` / `summary.json`.

## Authoritative runs

| Run | Notes |
| :--- | :--- |
| `run_20260816T_phase4_nvidia_nemotron_120b` | Initial Phase 4 completion |
| `run_20260816T_phase4_nvidia_nemotron_120b_v2` | Column-aware retrieval refinements + regression tests |
