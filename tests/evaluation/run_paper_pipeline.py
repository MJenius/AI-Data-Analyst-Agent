"""Paper Artifact Compilation Script.

Executes paper_generator.py to produce figures, LaTeX tables, and macros.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_platform.experiments.paper_generator import PaperArtifactCompiler

def main():
    output_dir = ROOT / "docs" / "research_paper"
    compiler = PaperArtifactCompiler(output_dir=output_dir)
    res = compiler.compile_all(workspace_root=ROOT)
    print("Paper compilation result:", res)

if __name__ == "__main__":
    main()
