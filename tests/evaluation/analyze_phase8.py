"""Phase 8 analysis — compare Phase 8 live results against Phase 7 / Phase 4 baselines.

Usage:
    python tests/evaluation/analyze_phase8.py [--phase8 DIR] [--out DIR]

Reads:
  - results/phase8/live_<ts>/raw_results.json, summary.json
  - results/phase7/live_<ts>/raw_results.json (configurable)
Writes:
  - a comparative markdown report + JSON comparison at the output path.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

PHASE7_DIR = ROOT / "results" / "phase7" / "live_20260817T145542"


def load(path: Path, name: str) -> dict[str, Any]:
    return json.load(open(path / name, encoding="utf-8"))


def correctness_by_id(results: list[dict[str, Any]]) -> dict[str, bool]:
    return {r["query_id"]: r["result_correct"] for r in results}


def failure_breakdown(results: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in results:
        if not r["result_correct"]:
            cause = r.get("failure_cause") or "unknown"
            counts[cause] = counts.get(cause, 0) + 1
    return counts


def analyze(p8_dir: Path, p7_dir: Path, out_dir: Path) -> None:
    p8 = load(p8_dir, "raw_results.json")
    p8_sum = load(p8_dir, "summary.json")
    p7 = load(p7_dir, "raw_results.json")
    p7_sum = load(p7_dir, "summary.json")

    p8_correct = correctness_by_id(p8)
    p7_correct = correctness_by_id(p7)

    ids = sorted(p8_correct.keys())
    improved = [i for i in ids if p8_correct.get(i) and not p7_correct.get(i)]
    regressed = [i for i in ids if not p8_correct.get(i) and p7_correct.get(i)]
    both_correct = [i for i in ids if p8_correct.get(i) and p7_correct.get(i)]
    both_wrong = [i for i in ids if not p8_correct.get(i) and not p7_correct.get(i)]

    # why did Phase 8 fix them?
    improved_details = []
    for r in p8:
        if r["query_id"] in improved:
            improved_details.append({
                "query_id": r["query_id"],
                "question": r["question"],
                "failure_cause_phase7": "n/a",
                "repair_applied": r["repair_applied"],
                "repair_methods": r["repair_methods"],
                "repair_categories": r["repair_categories"],
                "detected_plan_mismatch": r["detected_plan_mismatch"],
                "pre_repair_correct": r["pre_repair_correct"],
            })

    # why are remaining failures still wrong?
    remaining = [r for r in p8 if not r["result_correct"]]
    remaining_breakdown = failure_breakdown(p8)

    comparison = {
        "phase8_dir": str(p8_dir),
        "phase7_dir": str(p7_dir),
        "total": len(ids),
        "phase8_correct": len([i for i in ids if p8_correct[i]]),
        "phase7_correct": len([i for i in ids if p7_correct[i]]),
        "phase8_rate": p8_sum["result_correctness"],
        "phase7_rate": p7_sum["result_correctness"],
        "improved": improved,
        "regressed": regressed,
        "both_correct": both_correct,
        "both_wrong": both_wrong,
        "improved_details": improved_details,
        "remaining_failure_breakdown": remaining_breakdown,
        "remaining_count": len(remaining),
        "phase8_summary": p8_sum,
        "phase7_summary": p7_sum,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "comparison.json", "w", encoding="utf-8") as f:
        json.dump(comparison, f, indent=2, default=str)

    lines = [
        "# Phase 8 vs Phase 7 — Comparative Analysis",
        "",
        f"**Generated:** {datetime.datetime.now().isoformat()}",
        f"**Phase 8 run:** `{p8_dir.name}`",
        f"**Phase 7 run:** `{p7_dir.name}`",
        "",
        "## 1. Headline",
        "",
        "| Metric | Phase 7 | Phase 8 | Delta |",
        "| :--- | :---: | :---: | :---: |",
        f"| Result correctness | {p7_sum['result_correctness']*100:.1f}% | **{p8_sum['result_correctness']*100:.1f}%** | {100*(p8_sum['result_correctness']-p7_sum['result_correctness']):+.1f}pp |",
        f"| Exact match | {p7_sum.get('exact_match_rate',0)*100:.1f}% | {p8_sum.get('exact_match_rate',0)*100:.1f}% | {100*(p8_sum.get('exact_match_rate',0)-p7_sum.get('exact_match_rate',0)):+.1f}pp |",
        f"| SQL execution success | {p7_sum['sql_execution_success_rate']*100:.1f}% | {p8_sum['sql_execution_success_rate']*100:.1f}% | {100*(p8_sum['sql_execution_success_rate']-p7_sum['sql_execution_success_rate']):+.1f}pp |",
        f"| Mean latency | {p7_sum['mean_latency_seconds']:.1f}s | {p8_sum['mean_latency_seconds']:.1f}s | {p8_sum['mean_latency_seconds']-p7_sum['mean_latency_seconds']:+.1f}s |",
        "",
        "## 2. Phase 8 Detection & Repair",
        "",
        "| Metric | Value |",
        "| :--- | :---: |",
        f"| Semantic detection rate (of incorrect, executable) | {p8_sum['semantic_detection_rate']*100:.1f}% |",
        f"| Detection precision | {p8_sum['detection_precision']*100:.1f}% |",
        f"| Flagged queries | {p8_sum['flagged_count']} |",
        f"| Correct-but-flagged (flag FP) | {p8_sum['correct_but_flagged_count']} ({p8_sum['false_positive_flag_rate']*100:.1f}%) |",
        f"| Repair attempted | {p8_sum['repair_attempted_count']} ({p8_sum['repair_attempted_rate']*100:.1f}%) |",
        f"| Repair applied | {p8_sum['repair_applied_count']} ({p8_sum['repair_applied_rate']*100:.1f}%) |",
        f"| Repair success rate (applied & previously wrong) | {p8_sum['repair_success_rate']*100:.1f}% |",
        f"| Repaired-to-correct | {p8_sum['repaired_to_correct_count']} |",
        f"| False-positive repairs | {p8_sum['false_positive_repair_count']} ({p8_sum['false_positive_repair_rate']*100:.1f}%) |",
        f"| Programmatic / LLM repairs | {p8_sum['programmatic_repair_count']} / {p8_sum['llm_repair_count']} |",
        "",
        "### Repair categories",
        "",
        "| Category | Count |",
        "| :--- | :---: |",
    ]
    for cat, count in p8_sum.get("repair_category_counts", {}).items():
        lines.append(f"| {cat} | {count} |")

    lines += [
        "",
        "## 3. Per-Query Flip Analysis",
        "",
        f"- Improved (wrong in P7 → correct in P8): **{len(improved)}**",
        f"- Regressed (correct in P7 → wrong in P8): **{len(regressed)}**",
        f"- Correct in both: **{len(both_correct)}**",
        f"- Wrong in both: **{len(both_wrong)}**",
        "",
        "### Improved queries",
        "",
        "| # | Question | P8 repair | Method | Categories | Pre-correct |",
        "| :--- | :--- | :---: | :--- | :--- | :---: |",
    ]
    for d in improved_details:
        qid = d["query_id"]
        q = next(r for r in p8 if r["query_id"] == qid)
        lines.append(
            f"| {qid} | {q['question'][:60]} | {'Y' if d['repair_applied'] else 'N'} | "
            f"{','.join(d['repair_methods']) or '-'} | {','.join(d['repair_categories']) or '-'} | "
            f"{'Y' if d['pre_repair_correct'] else 'N' if d['pre_repair_correct'] is False else '-'} |"
        )

    lines += [
        "",
        "### Regressed queries",
        "",
        "| # | Question | P7 correct reason (likely) |",
        "| :--- | :--- | :--- |",
    ]
    for qid in regressed:
        q = next(r for r in p8 if r["query_id"] == qid)
        lines.append(f"| {qid} | {q['question'][:60]} | see raw results |")

    lines += [
        "",
        "## 4. Remaining Failures (Phase 8)",
        "",
        "| Failure Cause | Count | Rate of total |",
        "| :--- | :---: | :---: |",
    ]
    for cause, count in sorted(remaining_breakdown.items(), key=lambda x: -x[1]):
        lines.append(f"| {cause} | {count} | {count/len(p8)*100:.1f}% |")

    lines += [
        "",
        "## 5. Notes & Caveats",
        "",
        "- Correctness is measured by the frozen harness (exact/equivalence match incl. output column names).",
        "- Output-alias naming differences (e.g. `month` vs `peak_month`) are counted as incorrect by the harness even when the SQL is semantically correct.",
        "",
        "*Generated by analyze_phase8.py*",
    ]

    (out_dir / "phase8_comparison_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {out_dir / 'comparison.json'}")
    print(f"Wrote {out_dir / 'phase8_comparison_report.md'}")
    print(f"Phase8: {len([i for i in ids if p8_correct[i]])}/{len(ids)} | Phase7: {len([i for i in ids if p7_correct[i]])}/{len(ids)}")
    print(f"Improved: {len(improved)} | Regressed: {len(regressed)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase8", default=None, help="Phase 8 results dir (default: newest results/phase8/live_*)")
    parser.add_argument("--phase7", default=str(PHASE7_DIR), help="Phase 7 results dir")
    parser.add_argument("--out", default=str(ROOT / "results" / "phase8" / "comparison"), help="Output dir")
    args = parser.parse_args()

    if args.phase8:
        p8_dir = Path(args.phase8)
    else:
        candidates = sorted((ROOT / "results" / "phase8").glob("live_*"), reverse=True)
        p8_dir = candidates[0]
    analyze(p8_dir, Path(args.phase7), Path(args.out))


if __name__ == "__main__":
    main()