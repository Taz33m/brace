"""Import a fresh local source run into the operator's recovery database.

No network, invitations, model calls, or publication. Existing cases are checked
and reused without resetting their reports, reviews, or revisions.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main(argv=None):
    from backend.config import DATA_DIR
    from backend.recovery.local import LocalRecoveryLock, import_fresh_case
    from backend.recovery.platform.auth import Actor, LOCAL_OWNER_ID
    from backend.recovery.platform.errors import PlatformError
    from backend.recovery.platform.store import CaseStore
    from backend.recovery.registry import CaseInputRegistry

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directory", type=Path)
    parser.add_argument("--root", type=Path,
                        default=Path(os.environ.get("BRACE_RECOVERY_DATA_DIR") or DATA_DIR / "recovery"))
    parser.add_argument("--household-label", help="Explicit owner-supplied household label; no verified unit/scan binding is created")
    args = parser.parse_args(argv)
    try:
        seed = json.loads((args.run_directory / "seed.json").read_text())
        inventory = json.loads((args.run_directory / "inventory.json").read_text())
        inputs = json.loads((args.run_directory / "inputs.json").read_text())
        private = args.root / "platform"
        with LocalRecoveryLock(private):
            store = CaseStore(private / "platform.sqlite3", private / "media")
            registry = CaseInputRegistry(args.root / "registered-inputs")
            snapshot = import_fresh_case(store, registry, seed, inventory, inputs.get("financial_assumptions"))
            if args.household_label is not None:
                label = args.household_label.strip()
                if not label or len(label) > 200:
                    raise ValueError("Use a nonempty household label up to 200 characters")
                matches = [row for row in snapshot["household_labels"] if row["unit_label"] == label]
                if len(matches) > 1:
                    raise ValueError("This label matches multiple households; review it in the owner workspace")
                if not matches:
                    store.add_household(Actor("owner", LOCAL_OWNER_ID), snapshot["case"]["case_id"], label)
                    snapshot = store.owner_snapshot(Actor("owner", LOCAL_OWNER_ID), snapshot["case"]["case_id"]).model_dump(mode="json")
        print(json.dumps({"case_id": snapshot["case"]["case_id"], "mode": snapshot["case"]["mode"],
                          "case_revision": snapshot["case"]["case_revision"],
                          "evidence_count": len(snapshot["evidence"]),
                          "household_count": len(snapshot["household_labels"]), "status": "ready"}))
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, PlatformError) as exc:
        parser.exit(2, f"Case import could not complete ({type(exc).__name__}). Check the source run and private storage paths.\n")


if __name__ == "__main__":
    raise SystemExit(main())
