"""CLI Runner for Compiling All Scientific Paper Figures, Tables, and Artifacts."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_platform.experiments.paper_generator import PaperArtifactCompiler

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("run_paper_pipeline")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile Research Paper Figures, Tables, and Macros")
    parser.add_argument("--output-dir", type=str, default=None, help="Output directory for research artifacts")
    args = parser.parse_args()

    out_dir = Path(args.output_dir) if args.output_dir else ROOT / "docs" / "research_paper"
    compiler = PaperArtifactCompiler(output_dir=out_dir)
    res = compiler.compile_all(workspace_root=ROOT)

    print("\n" + "=" * 80)
    print("RESEARCH PAPER ARTIFACTS COMPILATION COMPLETE")
    print("=" * 80)
    print(f"Output Directory:    {res['output_dir']}")
    print(f"Phases Processed:    {res['records_compiled']}")
    print(f"Figures Generated:   {res['figures_generated']} (PDF, SVG, 300 DPI PNG)")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
