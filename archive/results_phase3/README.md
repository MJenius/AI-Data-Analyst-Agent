# Phase 3 experiment artifacts

Each child directory is one immutable experiment run on the audited 100-query
benchmark (`tests/evaluation/benchmark_dataset_v2.json`, referred to as V3 by
the evaluation workflow). It contains the exact configuration snapshot, raw
per-query outputs, summaries, and a generated report.

The legacy files directly in this directory are a three-query smoke run. They
are retained for traceability and must not be cited as 100-query evidence.

Run the full diagnostic experiment with:

```powershell
.\.venv\Scripts\python.exe tests/evaluation/phase3/run_experiments.py --run-id run_YYYYMMDDTHHMMSSZ
```
