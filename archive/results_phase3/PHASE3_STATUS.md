# Phase 3 status — complete

The controlled five-configuration, 100-query experiment completed with
`nvidia/nemotron-3-super-120b-a12b`.

- Run: `run_20260815T_phase3_nvidia_nemotron_120b_controlled/`
- Concise report: `run_20260815T_phase3_nvidia_nemotron_120b_controlled/PHASE3_CONCISE_REPORT.md`
- Raw results: one `raw_results.json` per configuration, 100 rows each
- Benchmark SHA-256: `3B55106604BB4CE7E3580A4A838AC29F8EBCF6A2F1B49442644437698B79F209`

Nemotron 120B is ready and completed the full experiment. Nemotron 49B is not
ready because its corrected 5-query preflight still recorded a bounded timeout.
All partial and superseded attempts are preserved with `NOT_RUN.md` markers.

The main bottleneck is column- and join-key-grounded SQL generation, especially
with top-5 RAG context. Full-schema generation achieved 14% correctness and 69%
execution; RAG-only achieved 1% correctness and 4% execution. Planning and
execution feedback did not recover that loss.
