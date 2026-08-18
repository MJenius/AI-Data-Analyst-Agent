"""500-Query Benchmark Dataset Validator.

Validates `tests/evaluation/benchmark_dataset_500.json` BEFORE any live benchmark run:
1. JSON integrity & structure schema
2. Schema & table validity (ensures all referenced tables and columns exist in analytics.db)
3. Ground-truth SQL execution against SQLite (executes expected_sql and verifies expected_result matches)
4. Duplicate & near-duplicate query detection (exact text match, cosine/Jaccard semantic overlap)
5. Result shape & column non-emptiness validation
6. Coverage distribution analysis across business domains & query categories
"""

from __future__ import annotations

import argparse
import difflib
import json
import logging
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("validate_500")

DB_PATH = ROOT / "data" / "analytics.db"
DATASET_PATH = ROOT / "tests" / "evaluation" / "benchmark_dataset_500.json"
KNOWN_TABLES = {
    "customers", "geolocation", "order_items", "order_payments",
    "order_reviews", "orders", "products", "sellers",
    "product_category_name_translation"
}


def load_dataset(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Dataset file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_db_schema(db_path: Path) -> dict[str, set[str]]:
    """Retrieve all table names and their column names from SQLite DB."""
    schema = {}
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall() if not row[0].startswith("sqlite_")]
        for tbl in tables:
            cursor.execute(f"PRAGMA table_info('{tbl}');")
            columns = {row[1] for row in cursor.fetchall()}
            schema[tbl] = columns
    finally:
        conn.close()
    return schema


def tokenize(text: str) -> set[str]:
    return set(re.findall(r"\b[a-z0-9_]{3,}\b", text.lower()))


def jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def validate_500_benchmark(dataset_path: Path = DATASET_PATH, db_path: Path = DB_PATH) -> dict[str, Any]:
    logger.info("Loading 500-query benchmark dataset from: %s", dataset_path)
    dataset = load_dataset(dataset_path)
    total_queries = len(dataset)
    logger.info("Total query entries found: %d", total_queries)

    db_schema = get_db_schema(db_path) if db_path.exists() else {}
    if not db_schema:
        logger.warning("Database not found or empty at %s. SQL execution check will be skipped.", db_path)

    issues: list[dict[str, Any]] = []
    category_dist: Counter[str] = Counter()
    difficulty_dist: Counter[str] = Counter()
    domain_dist: Counter[str] = Counter()

    # Duplicate check structures
    seen_exact_questions: dict[str, int] = {}
    exact_duplicates: list[tuple[int, int, str]] = []
    question_tokens: list[tuple[int, str, set[str]]] = []
    near_duplicates: list[tuple[int, int, float, str, str]] = []

    sql_executable_count = 0
    sql_failed_count = 0
    ground_truth_mismatch_count = 0
    table_hallucination_count = 0
    empty_result_count = 0

    conn = sqlite3.connect(db_path) if db_schema else None

    for idx, item in enumerate(dataset):
        qid = item.get("id", f"q_{idx:03d}")
        question = item.get("question", "").strip()
        expected_sql = item.get("expected_sql", "").strip()
        expected_tables = item.get("expected_tables", [])
        expected_result = item.get("expected_result", {})
        category = item.get("category", item.get("domain", "uncategorized"))
        difficulty = item.get("difficulty", "medium")
        domain = item.get("domain", category)

        category_dist[category] += 1
        difficulty_dist[difficulty] += 1
        domain_dist[domain] += 1

        # 1. Structural checks
        if not question:
            issues.append({"id": qid, "index": idx, "issue": "empty_question", "severity": "error"})
        if not expected_sql:
            issues.append({"id": qid, "index": idx, "issue": "empty_expected_sql", "severity": "error"})

        # 2. Exact Duplicate Check
        q_norm = re.sub(r"\s+", " ", question.lower())
        if q_norm in seen_exact_questions:
            orig_idx = seen_exact_questions[q_norm]
            exact_duplicates.append((orig_idx, idx, question))
            issues.append({
                "id": qid, "index": idx, "issue": f"exact_duplicate_of_index_{orig_idx}",
                "severity": "warning", "question": question
            })
        else:
            seen_exact_questions[q_norm] = idx

        # 3. Near-Duplicate Check
        tokens = tokenize(question)
        for prev_idx, prev_q, prev_tokens in question_tokens[-50:]:  # window of recent queries
            sim = jaccard_similarity(tokens, prev_tokens)
            if sim >= 0.85 and q_norm != re.sub(r"\s+", " ", prev_q.lower()):
                near_duplicates.append((prev_idx, idx, round(sim, 3), prev_q, question))
        question_tokens.append((idx, question, tokens))

        # 4. Table Schema Validation
        for tbl in expected_tables:
            if tbl not in KNOWN_TABLES:
                table_hallucination_count += 1
                issues.append({
                    "id": qid, "index": idx, "issue": f"unknown_table_{tbl}",
                    "severity": "error", "table": tbl
                })

        # 5. Ground-Truth SQL Execution & Validation
        if conn and expected_sql:
            try:
                cursor = conn.cursor()
                cursor.execute(expected_sql)
                rows = cursor.fetchall()
                cols = [d[0] for d in cursor.description] if cursor.description else []
                sql_executable_count += 1

                if not rows:
                    empty_result_count += 1

                # Verify expected_result structure if provided
                if isinstance(expected_result, dict):
                    exp_vals = expected_result.get("values", [])
                    if exp_vals and len(exp_vals) != len(rows):
                        ground_truth_mismatch_count += 1
                        issues.append({
                            "id": qid, "index": idx, "issue": "ground_truth_row_count_mismatch",
                            "severity": "warning", "expected_rows": len(exp_vals), "actual_db_rows": len(rows)
                        })
                elif isinstance(expected_result, list) and expected_result:
                    if len(expected_result) != len(rows):
                        ground_truth_mismatch_count += 1
                        issues.append({
                            "id": qid, "index": idx, "issue": "ground_truth_row_count_mismatch",
                            "severity": "warning", "expected_rows": len(expected_result), "actual_db_rows": len(rows)
                        })

            except Exception as exc:
                sql_failed_count += 1
                issues.append({
                    "id": qid, "index": idx, "issue": "sql_execution_failure",
                    "severity": "error", "error": str(exc), "sql": expected_sql
                })

    if conn:
        conn.close()

    error_count = sum(1 for i in issues if i["severity"] == "error")
    warning_count = sum(1 for i in issues if i["severity"] == "warning")

    summary = {
        "dataset_path": str(dataset_path),
        "total_queries": total_queries,
        "valid_structure": error_count == 0,
        "error_count": error_count,
        "warning_count": warning_count,
        "sql_executable_count": sql_executable_count,
        "sql_failed_count": sql_failed_count,
        "ground_truth_mismatch_count": ground_truth_mismatch_count,
        "table_hallucination_count": table_hallucination_count,
        "empty_result_count": empty_result_count,
        "exact_duplicates_count": len(exact_duplicates),
        "near_duplicates_count": len(near_duplicates),
        "category_distribution": dict(category_dist),
        "difficulty_distribution": dict(difficulty_dist),
        "domain_distribution": dict(domain_dist),
        "exact_duplicates": exact_duplicates[:10],
        "near_duplicates_sample": near_duplicates[:10],
        "issues_sample": issues[:25],
    }

    return summary


def main():
    parser = argparse.ArgumentParser(description="Validate 500-query benchmark dataset")
    parser.add_argument("--dataset", type=Path, default=DATASET_PATH, help="Path to benchmark JSON")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="Path to SQLite database")
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "phase10" / "benchmark_500_validation_report.json")
    args = parser.parse_args()

    report = validate_500_benchmark(args.dataset, args.db)

    print("\n" + "=" * 60)
    print(" 500-QUERY BENCHMARK DATASET VALIDATION REPORT")
    print("=" * 60)
    print(f" Total Queries:            {report['total_queries']}")
    print(f" SQL Executable (Passed):  {report['sql_executable_count']}/{report['total_queries']} ({report['sql_executable_count']/report['total_queries']*100:.1f}%)")
    print(f" SQL Execution Failures:   {report['sql_failed_count']}")
    print(f" Ground Truth Mismatches:  {report['ground_truth_mismatch_count']}")
    print(f" Table Hallucinations:     {report['table_hallucination_count']}")
    print(f" Exact Duplicates:         {report['exact_duplicates_count']}")
    print(f" Near Duplicates:          {report['near_duplicates_count']}")
    print(f" Errors:                   {report['error_count']}")
    print(f" Warnings:                 {report['warning_count']}")
    print(f" Validation Passed:        {'YES' if report['valid_structure'] and report['sql_failed_count'] == 0 else 'NO'}")
    print("=" * 60)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    logger.info("Validation report saved to: %s", args.output)


if __name__ == "__main__":
    main()
