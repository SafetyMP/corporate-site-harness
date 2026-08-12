"""Site-gate oracle contract: handoff v2 shape and fail-closed collectors."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from corp_harness.contracts import ContractError

HANDOFF_SCHEMA_V1 = "corporate-site-handoff/v1"
HANDOFF_SCHEMA_V2 = "corporate-site-handoff/v2"
POLICY_ENGINES = frozenset({"none", "cedar", "equivalent"})
POINTER_FIELDS = (
    "enforcement_path_parity",
    "call_site_wiring",
    "surface_inventory",
    "adversarial_corpus",
)
POINTER_KINDS = {
    "official_engine_evidence": "official_engine_evidence/v1",
    "enforcement_path_parity": "enforcement_path_parity/v1",
    "call_site_wiring": "call_site_wiring/v1",
    "surface_inventory": "surface_inventory/v1",
    "adversarial_corpus": "adversarial_corpus/v1",
}
REQUIRED_TAXONOMY = (
    "listen_bind",
    "cors",
    "metrics_authn",
    "host_eval_fallback",
    "sandbox_fallback",
    "daemon_bind",
)
MOCK_ENGINE_MARKERS = (
    "typescript",
    "wasm",
    "simulator",
    "evaluateSimulator",
    "mock",
    "ts-cedar",
)
OFFICIAL_CEDAR_PACKAGES = ("cedar-policy", "cedar-python")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_HANDOFF_FIELDS = (
    "schema",
    "program_id",
    "verification_scripts",
    "site_gate_oracles",
)
ORACLE_GATES = frozenset(
    {"site_verify", "operations", "corporate_review", "adversary"}
)


def load_handoff_object(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"corporate_handoff unreadable: {exc}") from exc
    if not isinstance(raw, dict):
        raise ContractError("corporate_handoff root must be an object")
    return raw


def validate_handoff_schema_v2(body: dict[str, Any]) -> None:
    schema = body.get("schema")
    if schema == HANDOFF_SCHEMA_V1:
        raise ContractError(
            "corporate-site-handoff/v1 is rejected; record corporate-site-handoff/v2"
        )
    if schema != HANDOFF_SCHEMA_V2:
        raise ContractError(
            f"corporate_handoff must use {HANDOFF_SCHEMA_V2}, not {schema!r}"
        )
    missing = [name for name in REQUIRED_HANDOFF_FIELDS if name not in body]
    if missing:
        raise ContractError(
            "corporate_handoff missing required fields: " + ", ".join(missing)
        )
    scripts = body.get("verification_scripts")
    if not isinstance(scripts, dict):
        raise ContractError("verification_scripts must be an object")
    if scripts.get("binding") != "scripts/harness":
        raise ContractError("verification_scripts.binding must be scripts/harness")
    if scripts.get("verify_argv") != ["./scripts/harness/verify.sh"]:
        raise ContractError("verification_scripts.verify_argv mismatch")
    if scripts.get("adversarial_argv") != ["./scripts/harness/adversarial.sh"]:
        raise ContractError("verification_scripts.adversarial_argv mismatch")
    _validate_site_gate_oracles(body.get("site_gate_oracles"))


def _validate_site_gate_oracles(oracles: Any) -> None:
    if not isinstance(oracles, dict):
        raise ContractError("site_gate_oracles must be an object")
    engine = oracles.get("policy_engine")
    if engine not in POLICY_ENGINES:
        raise ContractError(
            "site_gate_oracles.policy_engine must be none, cedar, or equivalent"
        )
    official = oracles.get("official_engine_evidence")
    if engine == "none":
        if official is not None:
            raise ContractError(
                "official_engine_evidence must be null when policy_engine is none"
            )
    else:
        _validate_pointer("official_engine_evidence", official)
    for field in POINTER_FIELDS:
        _validate_pointer(field, oracles.get(field))
    corpus = oracles.get("adversarial_corpus")
    if isinstance(corpus, dict):
        extension = corpus.get("deny_case_extension")
        if not isinstance(extension, dict):
            raise ContractError("adversarial_corpus.deny_case_extension is required")
        if extension.get("mode") != "append_only_findings":
            raise ContractError(
                "deny_case_extension.mode must be append_only_findings"
            )
        corpus_dir = extension.get("corpus_dir")
        if not isinstance(corpus_dir, str) or not corpus_dir.strip():
            raise ContractError("deny_case_extension.corpus_dir is required")
        _assert_site_relative_oracle_path(corpus_dir)


def _validate_pointer(field: str, pointer: Any) -> None:
    if not isinstance(pointer, dict):
        raise ContractError(f"site_gate_oracles.{field} must be a pointer object")
    path = pointer.get("path")
    kind = pointer.get("kind")
    sha = pointer.get("sha256")
    pin_status = pointer.get("pin_status")
    expected_kind = POINTER_KINDS[field]
    if kind != expected_kind:
        raise ContractError(
            f"site_gate_oracles.{field}.kind must be {expected_kind}"
        )
    if not isinstance(path, str):
        raise ContractError(f"site_gate_oracles.{field}.path must be a string")
    _assert_site_relative_oracle_path(path)
    if sha is None:
        if pin_status != "pending_site_delivery":
            raise ContractError(
                f"site_gate_oracles.{field}.sha256 may be null only with "
                "pin_status=pending_site_delivery"
            )
        return
    if not isinstance(sha, str) or not SHA256_RE.fullmatch(sha):
        raise ContractError(f"site_gate_oracles.{field}.sha256 must be 64-hex or null")


def _assert_site_relative_oracle_path(path: str) -> None:
    text = path.strip().replace("\\", "/")
    if not text or text.startswith("/") or text.startswith("~"):
        raise ContractError(f"oracle path must be site-relative: {path}")
    parts = Path(text).parts
    if ".." in parts:
        raise ContractError(f"oracle path must not contain ..: {path}")
    if text == "scripts/harness" or text.startswith("scripts/harness/"):
        raise ContractError(
            "oracle evidence must not live under scripts/harness: " + path
        )


def iter_live_pointers(body: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    oracles = body.get("site_gate_oracles")
    if not isinstance(oracles, dict):
        return []
    items: list[tuple[str, dict[str, Any]]] = []
    official = oracles.get("official_engine_evidence")
    if isinstance(official, dict):
        items.append(("official_engine_evidence", official))
    for field in POINTER_FIELDS:
        pointer = oracles.get(field)
        if isinstance(pointer, dict):
            items.append((field, pointer))
    return items


def pending_oracle_pins(body: dict[str, Any]) -> list[str]:
    pending: list[str] = []
    for field, pointer in iter_live_pointers(body):
        if pointer.get("sha256") is None or pointer.get("pin_status") == (
            "pending_site_delivery"
        ):
            pending.append(field)
    return pending


def mock_engine_report_is_invalid(report: dict[str, Any]) -> bool:
    package = str(report.get("official_package") or "").lower()
    fingerprint = str(report.get("import_path_fingerprint") or "").lower()
    blob = package + " " + fingerprint
    return any(marker.lower() in blob for marker in MOCK_ENGINE_MARKERS)


def official_cedar_identity_ok(report: dict[str, Any]) -> bool:
    if report.get("policy_engine") != "cedar":
        return report.get("policy_engine") == "equivalent"
    package = str(report.get("official_package") or "")
    fingerprint = str(report.get("import_path_fingerprint") or "")
    version = str(report.get("version_constraint") or "")
    if not version.strip():
        return False
    if mock_engine_report_is_invalid(report):
        return False
    return any(name in package or name in fingerprint for name in OFFICIAL_CEDAR_PACKAGES)


def inventory_missing_cells(report: dict[str, Any]) -> list[str]:
    cells = report.get("cells")
    if not isinstance(cells, list):
        return list(REQUIRED_TAXONOMY)
    present = {
        str(cell.get("taxonomy"))
        for cell in cells
        if isinstance(cell, dict) and cell.get("taxonomy")
    }
    missing = [name for name in REQUIRED_TAXONOMY if name not in present]
    declared_missing = report.get("missing_cells")
    if isinstance(declared_missing, list):
        missing = sorted(set(missing) | {str(item) for item in declared_missing})
    return missing


def inventory_oos_without_owner(report: dict[str, Any]) -> list[str]:
    bad: list[str] = []
    cells = report.get("cells")
    if not isinstance(cells, list):
        return ["cells"]
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        if cell.get("verdict") != "OOS":
            continue
        owner = cell.get("owner")
        residual = cell.get("residual_risk")
        if not isinstance(owner, str) or not owner.strip() or not residual:
            bad.append(str(cell.get("id") or cell.get("taxonomy") or "unknown"))
    return bad


def wiring_is_test_only(report: dict[str, Any]) -> bool:
    production_refs = report.get("production_refs")
    test_only_refs = report.get("test_only_refs")
    if not isinstance(production_refs, list) or not production_refs:
        return True
    if not isinstance(test_only_refs, list):
        return True
    return False


def deny_extension_hook_present(report: dict[str, Any]) -> bool:
    extension = report.get("deny_case_extension")
    if not isinstance(extension, dict):
        return False
    if extension.get("mode") != "append_only_findings":
        return False
    return extension.get("hook_present") is True


def executed_deny_cells(report: dict[str, Any]) -> list[dict[str, Any]]:
    cells = report.get("executed_cells")
    if not isinstance(cells, list):
        return []
    return [cell for cell in cells if isinstance(cell, dict)]


def name_presence_only(report: dict[str, Any]) -> bool:
    cells = executed_deny_cells(report)
    if not cells:
        return True
    return any(cell.get("executed") is not True for cell in cells)


def v2_handoff_body(
    *,
    program_id: str,
    site_path: str,
    master_sha256: str,
    acceptance_sha256: str,
    pending: bool = True,
    policy_engine: str = "none",
    pointers: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Minimal valid v2 handoff for tests and pending factory pins."""
    def _pointer(field: str, relpath: str) -> dict[str, Any]:
        if pointers and field in pointers:
            return pointers[field]
        payload: dict[str, Any] = {
            "path": relpath,
            "kind": POINTER_KINDS[field],
        }
        if pending:
            payload["sha256"] = None
            payload["pin_status"] = "pending_site_delivery"
        else:
            raise ContractError("live pointers must be supplied when pending is false")
        return payload

    official: Any = None
    if policy_engine != "none":
        official = _pointer(
            "official_engine_evidence",
            "evidence/site-gate-oracles/official-engine-evidence.json",
        )
    return {
        "schema": HANDOFF_SCHEMA_V2,
        "program_id": program_id,
        "program_kind": "product",
        "revision": 1,
        "site_id": "test-site",
        "site_path": site_path,
        "artifact_digests": {
            "master_spec": master_sha256,
            "acceptance": acceptance_sha256,
        },
        "authorized_surfaces": ["src"],
        "verification_scripts": {
            "binding": "scripts/harness",
            "verify_argv": ["./scripts/harness/verify.sh"],
            "adversarial_argv": ["./scripts/harness/adversarial.sh"],
        },
        "site_gate_oracles": {
            "policy_engine": policy_engine,
            "official_engine_evidence": official,
            "enforcement_path_parity": _pointer(
                "enforcement_path_parity",
                "evidence/site-gate-oracles/enforcement-path-parity.json",
            ),
            "call_site_wiring": _pointer(
                "call_site_wiring",
                "evidence/site-gate-oracles/call-site-wiring.json",
            ),
            "surface_inventory": _pointer(
                "surface_inventory",
                "evidence/site-gate-oracles/surface-inventory.json",
            ),
            "adversarial_corpus": {
                **_pointer(
                    "adversarial_corpus",
                    "evidence/site-gate-oracles/adversarial-corpus.json",
                ),
                "deny_case_extension": {
                    "mode": "append_only_findings",
                    "corpus_dir": "evidence/site-gate-oracles/deny-cases",
                    "storage_constraint": "site_relative_outside_scripts_harness",
                },
            },
        },
        "site_constraints": {
            "require_site_gate_oracles": True,
            "handoff_schema_min": HANDOFF_SCHEMA_V2,
            "agents_never_actor_user": True,
            "verification_scripts_only": ["verify.sh", "adversarial.sh"],
        },
    }
