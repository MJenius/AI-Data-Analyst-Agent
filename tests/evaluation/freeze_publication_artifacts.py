import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
paper_dir = ROOT / "docs" / "research_paper"

def file_sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

files_to_hash = [
    ROOT / "tests" / "evaluation" / "benchmark_dataset_500.json",
    ROOT / "data" / "analytics.db",
    ROOT / "results" / "phase10" / "live_500_benchmark_run" / "summary.json",
    ROOT / "results" / "phase10" / "final_research_validation_report.json",
    paper_dir / "PAPER_DRAFT.md",
    paper_dir / "PAPER_READINESS_AUDIT.md",
    paper_dir / "macros.tex",
]

for fig in (paper_dir / "figures").glob("*.*"):
    files_to_hash.append(fig)
for tab in (paper_dir / "tables").glob("*.tex"):
    files_to_hash.append(tab)

manifest = {
    "title": "Frozen Publication Artifact Manifest",
    "timestamp_utc": "2026-08-19T08:35:00Z",
    "status": "FROZEN_FOR_SUBMISSION",
    "artifacts": {},
}

for p in sorted(files_to_hash):
    rel = str(p.relative_to(ROOT)).replace("\\", "/")
    manifest["artifacts"][rel] = {
        "sha256": file_sha256(p),
        "size_bytes": p.stat().st_size,
    }

manifest_path = paper_dir / "ARTIFACT_MANIFEST.json"
with open(manifest_path, "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2)

print(f"Frozen manifest created with {len(manifest['artifacts'])} artifacts at {manifest_path}")
