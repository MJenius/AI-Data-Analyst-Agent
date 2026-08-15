from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tests.evaluation.phase3 import common
from tests.evaluation.phase3 import configs
from tests.evaluation.phase3 import run_experiments


class _UnavailableConfig:
    id = "unavailable"

    async def run(self, question, benchmark):
        return {
            "generated_sql": None,
            "latency_seconds": 0.0,
            "provider_error": True,
            "error": "provider unavailable",
        }


class Phase3RunnerTests(unittest.TestCase):
    def test_shared_harness_does_not_retry_a_provider_failure(self):
        class ProviderFailure(RuntimeError):
            is_provider_failure = True

        class Client:
            calls = 0

            def complete_json(self, *_):
                self.calls += 1
                raise ProviderFailure("timeout")

        client = Client()
        with self.assertRaises(configs.ProviderUnavailableError):
            configs._llm_json(client, "system", "user")
        self.assertEqual(client.calls, 1)

    def test_provider_failures_are_marked_not_run_not_scored_as_a_full_benchmark(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "test.db"
            connection = sqlite3.connect(db_path)
            connection.execute("CREATE TABLE sample (value INTEGER)")
            connection.execute("INSERT INTO sample VALUES (1)")
            connection.commit()
            connection.close()

            previous_results_dir = run_experiments.RESULTS_DIR
            previous_db_path = common.DB_PATH
            try:
                run_experiments.RESULTS_DIR = root / "artifacts"
                common.DB_PATH = str(db_path)
                benchmark = {
                    "question": "How many rows are there?",
                    "expected_sql": "SELECT COUNT(*) AS total FROM sample",
                    "expected_tables": [],
                    "expected_result": {"values": [{"total": 1}]},
                    "query_type": "single_value",
                    "difficulty": "easy",
                }
                rows, status = asyncio.run(
                    run_experiments.run_config(
                        _UnavailableConfig(), [benchmark] * 10, None, max_consecutive_provider_errors=3
                    )
                )
            finally:
                run_experiments.RESULTS_DIR = previous_results_dir
                common.DB_PATH = previous_db_path

            self.assertEqual(len(rows), 3)
            self.assertEqual(status["status"], "not_run_provider_unavailable")
            self.assertEqual(status["planned_queries"], 10)
            self.assertEqual(status["provider_error_count"], 3)
            saved_status = json.loads((root / "artifacts" / "unavailable" / "run_status.json").read_text())
            self.assertEqual(saved_status["status"], "not_run_provider_unavailable")


if __name__ == "__main__":
    unittest.main()
