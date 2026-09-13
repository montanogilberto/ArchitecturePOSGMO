"""
Phase 2 spike CLI — self-contained, LLM-backed, NOT wired into the
production factory (agents/agent.py, orchestrator.py are untouched).

Usage:
    python run_debate_spike.py "create a new module for rewards"

Requires GOOGLE_API_KEY or GEMINI_API_KEY in posgmo-factory/.env.
"""
from __future__ import annotations

import asyncio
import sys

from pathlib import Path

from dotenv import load_dotenv

from debate_v2.run import run_debate
from debate_v2.solution_package import render_solution_package
from debate_v2.transcript import render_transcript

load_dotenv()


def main() -> None:
    request = " ".join(sys.argv[1:]) or "create a new module for rewards"
    state = asyncio.run(run_debate(request))
    print(render_transcript(state))

    out_dir = Path(__file__).parent / "debate_v2_output"
    out_dir.mkdir(exist_ok=True)
    package_path = out_dir / "SOLUTION_PACKAGE.md"
    package_path.write_text(render_solution_package(state), encoding="utf-8")
    print(f"\nSolution Package written to {package_path}")


if __name__ == "__main__":
    main()
