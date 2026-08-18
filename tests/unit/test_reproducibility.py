"""Unit Tests for Reproducibility Manifests and Hashing."""

import json
from pathlib import Path
import pytest

from agent_platform.experiments.reproducibility import (
    DatabaseMetadata,
    DatasetMetadata,
    EnvironmentSnapshot,
    ExperimentManifest,
    ModelConfigManifest,
    compute_file_sha256,
    compute_string_sha256,
    verify_manifest_integrity,
)


def test_hashing_and_environment_capture(tmp_path: Path):
    test_file = tmp_path / "test.txt"
    test_file.write_text("reproducibility test content", encoding="utf-8")

    sha = compute_file_sha256(test_file)
    assert len(sha) == 64
    assert sha == compute_string_sha256("reproducibility test content")

    env_snap = EnvironmentSnapshot.capture()
    assert env_snap.os_name
    assert env_snap.python_version


def test_manifest_creation_and_verification(tmp_path: Path):
    # Setup dummy dataset and sqlite DB
    ds_file = tmp_path / "dataset.json"
    ds_file.write_text(json.dumps([{"id": "q1", "question": "test?"}]), encoding="utf-8")

    import sqlite3
    db_file = tmp_path / "test.db"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE orders (id INTEGER, total REAL);")
    conn.execute("INSERT INTO orders VALUES (1, 100.0);")
    conn.commit()
    conn.close()

    ds_meta = DatasetMetadata.from_file(ds_file)
    db_meta = DatabaseMetadata.from_file(db_file)
    env_snap = EnvironmentSnapshot.capture()
    model_cfg = ModelConfigManifest(model_name="test-model", provider="test")

    manifest = ExperimentManifest(
        experiment_id="test_exp",
        timestamp_utc="2026-08-19T00:00:00Z",
        title="Test Experiment",
        description="Unit test experiment",
        dataset=ds_meta,
        database=db_meta,
        model_config=model_cfg,
        environment=env_snap,
    )

    manifest_file = tmp_path / "manifest.json"
    manifest.save(manifest_file)
    assert manifest_file.exists()

    # Verification should pass
    res_pass = verify_manifest_integrity(manifest_file, expected_dataset_path=ds_file, expected_db_path=db_file)
    assert res_pass.is_valid
    assert res_pass.dataset_match
    assert res_pass.database_match

    # Corrupt dataset and test verification failure
    ds_file.write_text(json.dumps([{"id": "q1_modified"}]), encoding="utf-8")
    res_fail = verify_manifest_integrity(manifest_file, expected_dataset_path=ds_file, expected_db_path=db_file)
    assert not res_fail.is_valid
    assert not res_fail.dataset_match
    assert len(res_fail.discrepancies) > 0
