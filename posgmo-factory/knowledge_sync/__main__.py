"""python -m knowledge_sync [--check]"""
from __future__ import annotations

import argparse
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from knowledge_sync.sync import REPORT, sync_knowledge  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh Factory knowledge from the GMO repos + live DB.")
    parser.add_argument("--check", action="store_true", help="report drift only, write nothing")
    args = parser.parse_args()
    report = sync_knowledge(check_only=args.check)
    if not args.check:
        print(f"[knowledge_sync] report: {REPORT}")
    raise SystemExit(1 if report["errors"] and not report["files"] else 0)


if __name__ == "__main__":
    main()
