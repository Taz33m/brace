"""Build a real-data recovery seed and run a deterministic screen or draft agent.

Default: cache/kit only, no model or remote API calls. Outputs stay under ignored
data/recovery; they contain sponsor evidence and must never be committed.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".recovery-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as out:
            json.dump(value, out, indent=2, allow_nan=False)
            out.write("\n")
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    from backend.config import DATA_DIR
    from backend.recovery.domain.service import (EvidenceImages, MODES, fresh_run_id,
                                                make_case_seed, screen_case, valuation_inputs)
    from backend.recovery.domain.sources import load_inventory

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("property_id", type=int)
    parser.add_argument("--incident-name", required=True)
    parser.add_argument("--incident-at", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--mode", choices=MODES, default="scenario_exercise")
    parser.add_argument("--fetch-sources", action="store_true", help="Allow sponsor API requests")
    parser.add_argument("--agent", action="store_true", help="Run the paid model loop; output stays draft")
    parser.add_argument("--financial-inputs", type=Path, help="Local JSON financial_assumptions object")
    parser.add_argument("--snapshot", type=Path, help="Local owner snapshot, including verified reports")
    parser.add_argument("--register-inputs", action="store_true",
                        help="Register immutable case inputs for the authenticated recovery runtime")
    args = parser.parse_args(argv)
    try:
        inventory = load_inventory(args.property_id, incident_at=args.incident_at,
                                   assessment_as_of=args.as_of, mode=args.mode,
                                   allow_network=args.fetch_sources)
        snapshot = make_case_seed(inventory, incident_name=args.incident_name,
                                  incident_at=args.incident_at, assessment_as_of=args.as_of,
                                  mode=args.mode)
        if args.snapshot:
            supplied = json.loads(args.snapshot.read_text())
            for key in ("property_ref", "incident_at", "assessment_as_of", "mode"):
                if supplied["case"][key] != snapshot["case"][key]:
                    raise ValueError(f"Supplied snapshot has a different {key}")
            snapshot = supplied
        finance = json.loads(args.financial_inputs.read_text()) if args.financial_inputs else None
        inputs = valuation_inputs(inventory, snapshot, finance)
        inputs["source_fetch_allowed"] = args.fetch_sources
        screen = screen_case(snapshot, inputs)
        # Every invocation gets its own directory: no overwriting a reviewed seed or prior run.
        run_id = fresh_run_id()
        directory = DATA_DIR / "recovery" / snapshot["case"]["case_id"] / run_id
        atomic_json(directory / "seed.json", snapshot)
        atomic_json(directory / "inputs.json", inputs)
        atomic_json(directory / "inventory.json", inventory)
        atomic_json(directory / "screen.json", screen)
        registered_digest = None
        if args.register_inputs:
            from backend.recovery.registry import CaseInputRegistry

            registered_digest = CaseInputRegistry(DATA_DIR / "recovery" / "registered-inputs").register(
                snapshot, inventory, finance)
        result = None
        if args.agent:
            from backend.recovery.domain.agent import RecoveryAgent

            snapshot["run_id"] = run_id
            images = EvidenceImages(inventory.get("assets", {}), snapshot["evidence"],
                                    allow_network=args.fetch_sources)
            def report_progress(event):
                import sys

                if event["type"] in {"tool.completed", "tool.rejected", "assessment.completed"}:
                    print(f"[{event['type']}] {event.get('tool') or event.get('status') or ''}", file=sys.stderr, flush=True)

            result = RecoveryAgent(snapshot, inputs, inspect_image=images, emit=report_progress).run()
            atomic_json(directory / "assessment.json", result)
        value = screen["valuation"]
        print(json.dumps({"case_id": snapshot["case"]["case_id"], "mode": args.mode,
                          "source_status": inventory.get("source_status", {}),
                          "evidence_count": len(snapshot["evidence"]),
                          "included_comparables": sum(c["included"] for c in value["comparables"]),
                          "valuation_basis": value["basis"],
                          "current_condition": value["current_condition"],
                          "agent_status": result["assessment"]["status"] if result else "not_requested",
                          "registered_input_digest": registered_digest,
                          "output_directory": str(directory)}, indent=2))
        return 1 if result and result["assessment"]["status"] == "failed" else 0
    except (ValueError, KeyError, OSError) as exc:
        # Local CLI shows input errors, never whole records or model/API tracebacks.
        parser.exit(2, f"Recovery input unavailable or invalid ({type(exc).__name__}). Check paths, dates, and source coverage.\n")


if __name__ == "__main__":
    raise SystemExit(main())
