"""Download and cache everything backend.hazards needs, so the demo runs offline.

    .venv/bin/python scripts/fetch_hazards.py            # fetch what is missing
    .venv/bin/python scripts/fetch_hazards.py --rebuild  # also re-derive the replay files
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import hazards  # noqa: E402


def main() -> int:
    report = hazards.refresh(log=print, rebuild="--rebuild" in sys.argv[1:])
    print()
    for entry in hazards.scenarios():
        print(f"{entry['id']}  ({entry['kind']}, {entry['city']}, {'live' if entry['live'] else 'replay'})")
        for step in entry["steps"]:
            print(f"    {step['id']:<16} {step['issued']}  {step['label']}")
    if report["problems"]:
        print("\nProblems:")
        for problem in report["problems"]:
            print(f"  - {problem}")
    return 1 if report["problems"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
