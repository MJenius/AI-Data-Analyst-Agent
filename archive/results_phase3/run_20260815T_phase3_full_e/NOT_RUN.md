# NOT RUN — incomplete Phase 3 live experiment

This directory records the attempted full controlled run started on
2026-08-15. It is intentionally incomplete and must not be used for benchmark
claims or configuration comparisons.

- Planned workload: 100 V3 benchmark queries for each of five configurations.
- Completed workload: two queries from `config1_current_system` only.
- Blocking condition: repeated Groq HTTP 429 rate-limit responses, recorded in
  `../run_20260815T_phase3_full_e.stderr.log`.
- Action taken: the process was stopped rather than scoring provider failures as
  SQL/model failures.

Use the immutable runner after the configured model has sufficient API quota:

```powershell
.\.venv\Scripts\python.exe tests/evaluation/phase3/run_experiments.py --run-id run_<utc_timestamp>
```

The runner now stops a controlled configuration after three consecutive provider
failures and emits `run_status.json` with
`not_run_provider_unavailable`; such a run is not a valid comparison.
