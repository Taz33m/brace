"""Immutable local inputs for recovery runs; no network or Platform dependency.

Store under git-ignored private data. The registry holds sponsor records and local
asset references, never uploads or credentials. New reports are read from the
current authorized snapshot; registered source facts cannot silently change.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any

from .domain.temporal import MODES, normalize_date


class CaseInputRegistryError(ValueError):
    pass


class UnknownCaseInputs(CaseInputRegistryError):
    pass


_DATE_FIELDS = {"captured_at", "effective_at", "available_at", "model_created_at", "incident_at",
                "assessment_as_of", "transaction_date", "rate_effective_at", "observed_at", "updated_at"}
_BOOKKEEPING = {"received_at", "retrieved_at"}


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CaseInputRegistryError("Case inputs must contain finite JSON-compatible values.") from exc


def _semantic(value: Any, *, evidence: bool = False) -> Any:
    if isinstance(value, list):
        return [_semantic(item, evidence=evidence) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key in _BOOKKEEPING or (evidence and key == "media"):
            continue
        if key in _DATE_FIELDS and item is not None:
            normalized = normalize_date(item)
            if normalized is None:
                raise CaseInputRegistryError(f"Invalid source date in {key}.")
            result[key] = normalized
        else:
            result[key] = _semantic(item, evidence=(key == "evidence"))
    return result


def evidence_identity(row: dict) -> dict:
    """Stable source metadata: preserve date precision, exclude URLs/receipt time."""
    if not isinstance(row, dict) or not isinstance(row.get("evidence_id"), str) or not row["evidence_id"]:
        raise CaseInputRegistryError("Source evidence requires a nonempty identifier.")
    return _semantic(row, evidence=True)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _case_context(snapshot: dict) -> dict:
    case = snapshot.get("case") if isinstance(snapshot, dict) else None
    if not isinstance(case, dict) or not isinstance(case.get("case_id"), str) or not case["case_id"]:
        raise CaseInputRegistryError("A case snapshot with a nonempty case ID is required.")
    ref = case.get("property_ref")
    if not isinstance(ref, dict) or ref.get("dataset") != "commercial_property" or not isinstance(ref.get("id"), str) or not ref["id"]:
        raise CaseInputRegistryError("Registered inputs require a commercial property reference.")
    if case.get("mode") not in MODES:
        raise CaseInputRegistryError("A valid case mode is required.")
    dates = {}
    for key in ("incident_at", "assessment_as_of"):
        dates[key] = normalize_date(case.get(key))
        if dates[key] is None:
            raise CaseInputRegistryError(f"A valid {key} is required.")
    return {"case_id": case["case_id"], "property_ref": {"dataset": ref["dataset"], "id": ref["id"]},
            **dates, "mode": case["mode"]}


def _validate_property(inventory: dict, context: dict) -> None:
    subject = inventory.get("subject") if isinstance(inventory, dict) else None
    if not isinstance(subject, dict) or isinstance(subject.get("id"), bool) or subject.get("id") is None or str(subject["id"]) != context["property_ref"]["id"]:
        raise CaseInputRegistryError("Source inventory belongs to a different property.")
    for ref in (inventory.get("property_ref"), subject.get("property_ref")):
        if ref is not None and ref != context["property_ref"]:
            raise CaseInputRegistryError("Source inventory property reference does not match this case.")
    if subject.get("dataset", "commercial_property") != "commercial_property":
        raise CaseInputRegistryError("Only commercial source inventories are supported.")


def _validate_evidence(snapshot: dict, inventory: dict) -> None:
    def index(rows: Any) -> dict:
        if not isinstance(rows, list):
            raise CaseInputRegistryError("Source evidence must be a list.")
        result = {}
        for row in rows:
            identity = evidence_identity(row)
            eid = identity["evidence_id"]
            if eid in result:
                raise CaseInputRegistryError("Duplicate source evidence identifiers are ambiguous.")
            result[eid] = identity
        return result

    registered = index(inventory.get("evidence", []))
    current = index(snapshot.get("evidence", []))
    for eid, row in registered.items():
        if eid not in current or _canonical(current[eid]) != _canonical(row):
            raise CaseInputRegistryError("Registered source evidence was removed or changed; a reviewed input version is required.")


class CaseInputRegistry:
    """Content-addressed, create-once inputs pinned to one case context.

    Semantically identical re-registration tolerates source receipt timestamps,
    protected media URLs, and equivalent timezone spellings. It returns the old
    digest without rewriting. A separate integrity hash covers every stored byte
    of payload metadata, including bookkeeping omitted from semantic identity.
    """

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _path(self, case_id: str) -> Path:
        return self.root / (hashlib.sha256(case_id.encode("utf-8")).hexdigest() + ".json")

    def _read(self, context: dict) -> dict:
        path = self._path(context["case_id"])
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except FileNotFoundError:
            raise UnknownCaseInputs("This case has no registered source inputs.") from None
        except OSError:
            raise CaseInputRegistryError("Registered inputs could not be read safely.") from None
        try:
            with os.fdopen(fd, "r", encoding="utf-8") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise CaseInputRegistryError("Registered inputs are not a regular file.")
                manifest = json.load(stream)
            if not isinstance(manifest, dict) or set(manifest) != {"version", "content_digest", "integrity_digest", "payload"} or type(manifest["version"]) is not int or manifest["version"] != 1:
                raise CaseInputRegistryError("Unsupported case input manifest.")
            payload = manifest["payload"]
            if not isinstance(payload, dict) or set(payload) != {"case_context", "inventory", "financial_assumptions"}:
                raise CaseInputRegistryError("Invalid case input payload.")
            if _digest(payload) != manifest["integrity_digest"] or _digest(_semantic(payload)) != manifest["content_digest"]:
                raise CaseInputRegistryError("Registered input integrity verification failed.")
            if payload["case_context"] != context:
                raise CaseInputRegistryError("Registered case context changed; a reviewed input version is required.")
            _validate_property(payload["inventory"], context)
            return manifest
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, KeyError) as exc:
            raise CaseInputRegistryError("Registered input manifest is invalid.") from exc

    def register(self, snapshot: dict, inventory: dict, financial_assumptions: dict | None = None) -> str:
        context = _case_context(snapshot)
        _validate_property(inventory, context)
        _validate_evidence(snapshot, inventory)
        if financial_assumptions is not None and not isinstance(financial_assumptions, dict):
            raise CaseInputRegistryError("Financial assumptions must be an object.")
        inventory = deepcopy(inventory)
        existing_context = inventory.pop("_case_context", None)
        if existing_context is not None and _semantic(existing_context) != context:
            raise CaseInputRegistryError("Source inventory is pinned to another case context.")
        payload = {"case_context": context, "inventory": inventory,
                   "financial_assumptions": deepcopy(financial_assumptions or {})}
        digest = _digest(_semantic(payload))
        manifest = {"version": 1, "content_digest": digest, "integrity_digest": _digest(payload), "payload": payload}
        encoded = _canonical(manifest)
        path = self._path(context["case_id"])
        # A complete private temporary file is linked exclusively into place.
        # Unlike rename(), link() cannot overwrite a concurrent registration.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.root, prefix=".register-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                previous = self._read(context)
                if previous["content_digest"] != digest:
                    raise CaseInputRegistryError("This case already has different source or financial inputs; a reviewed input version is required.")
            return digest
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def load_inventory(self, snapshot: dict) -> dict:
        context = _case_context(snapshot)
        payload = self._read(context)["payload"]
        _validate_evidence(snapshot, payload["inventory"])
        return {**deepcopy(payload["inventory"]), "_case_context": deepcopy(context)}

    def input_provider(self, snapshot: dict) -> tuple[dict, Any]:
        from .domain.service import EvidenceImages, valuation_inputs

        context = _case_context(snapshot)
        payload = self._read(context)["payload"]
        inventory = payload["inventory"]
        _validate_evidence(snapshot, inventory)
        inputs = valuation_inputs(inventory, snapshot, payload["financial_assumptions"])
        return inputs, EvidenceImages(inventory.get("assets", {}), snapshot["evidence"], allow_network=False)
