from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from corp_harness.contracts import (
    CORPORATE_ACCEPTANCE_REQUIRE_EXECUTABLE_CURRENTNESS,
    CORPORATE_ROOT_EVIDENCE_RUNS,
    ContractError,
    assert_migration_currentness_invariant,
)

ATTEST_EVIDENCE_SOURCE = "corp-harness check --attest-packet"


def admit_attest_evidence(
    payload: dict[str, Any] | Path,
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    """Admit attest evidence only when produced by ``check --attest-packet``.

    Hand-written ``attest-*.json`` files (or equivalent payloads lacking the
    CLI provenance stamp) are rejected as non-evidence (TPC-HALT-002).
    """
    source_path = path
    data: dict[str, Any]
    if isinstance(payload, Path):
        source_path = payload
        try:
            loaded = json.loads(payload.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {
                "admitted": False,
                "ok": False,
                "gate_evidence": False,
                "error": f"unreadable attest evidence: {exc}",
            }
        if not isinstance(loaded, dict):
            return {
                "admitted": False,
                "ok": False,
                "gate_evidence": False,
                "error": "attest evidence must be a JSON object",
            }
        data = loaded
    elif isinstance(payload, dict):
        data = payload
    else:
        return {
            "admitted": False,
            "ok": False,
            "gate_evidence": False,
            "error": "attest evidence must be an object",
        }

    source = data.get("evidence_source") or data.get("attestation_evidence_source")
    if source != ATTEST_EVIDENCE_SOURCE:
        name = source_path.name if isinstance(source_path, Path) else ""
        handwritten = bool(name) and (
            name.startswith("attest-")
            or name.startswith("attest_")
            or name.startswith("attest.")
        )
        return {
            "admitted": False,
            "ok": False,
            "gate_evidence": False,
            "error": (
                "hand-written attest-*.json is not gate evidence; "
                "use check --attest-packet"
                if handwritten
                else (
                    "attest evidence requires "
                    f"{ATTEST_EVIDENCE_SOURCE} provenance"
                )
            ),
        }

    attestation = data.get("attestation")
    if not isinstance(attestation, dict) or not attestation.get("ok"):
        return {
            "admitted": False,
            "ok": False,
            "gate_evidence": False,
            "error": "attestation not ok",
        }
    return {
        "admitted": True,
        "ok": True,
        "gate_evidence": True,
        "attestation": attestation,
        "evidence_source": ATTEST_EVIDENCE_SOURCE,
    }


def executable_evidence_root(
    gate_name: str,
    program_root: Path,
    site_root: Path,
) -> Path:
    """Return the filesystem root that must own executable evidence for a gate."""
    if gate_name == "corporate_acceptance":
        return program_root.expanduser().resolve()
    return site_root.expanduser().resolve()


def resolve_check_evidence_roots(
    run_name: str,
    *,
    program_root: Path,
    site_path: str | Path,
    cwd: Path | None,
) -> tuple[Path, Path]:
    """Resolve (cwd, allowed_root) for ``check --run``.

    ``corporate_acceptance`` is bound to the corporate program root and does not
    require reading or writing ``site_path``. Site-gated runs remain site-root
    bound and reject a corporate-root cwd.
    """
    resolved_program = program_root.expanduser().resolve()

    if run_name in CORPORATE_ROOT_EVIDENCE_RUNS:
        allowed_root = resolved_program
        resolved_cwd = (cwd or allowed_root).expanduser().resolve()
        if resolved_cwd != allowed_root:
            raise ContractError(
                "corporate_acceptance evidence must run from the corporate program root"
            )
        return resolved_cwd, allowed_root

    site_root = Path(site_path).expanduser().resolve()
    allowed_root = site_root
    resolved_cwd = (cwd or allowed_root).expanduser().resolve()
    if resolved_cwd != allowed_root:
        raise ContractError("gate evidence must run from the registered site root")
    return resolved_cwd, allowed_root


def enforce_pass_evidence_classes(
    gate_name: str,
    gate_status: str,
    *,
    saw_executable: bool,
    saw_review: bool,
    saw_failure: bool,
    saw_executable_ref: bool,
) -> None:
    """Apply gate-level evidence class rules, including CA currentness mode.

    Stage 2 (``CORPORATE_ACCEPTANCE_REQUIRE_EXECUTABLE_CURRENTNESS`` is True):
    corporate_acceptance PASS requires successful executable evidence in addition
    to independent review.

    When the flag is False (migration window): matching-revision review-only
    corporate_acceptance PASS may remain valid; if any executable ref is claimed,
    it must also be successful (dual-record).
    """
    assert_migration_currentness_invariant()

    if gate_name in {"site_verify", "operations", "corporate_review", "adversary"}:
        if gate_status == "PASS" and not saw_executable:
            raise ContractError(f"{gate_name} PASS requires successful executable evidence")
    if gate_name in {"corporate_acceptance", "corporate_review", "adversary"}:
        if gate_status == "PASS" and not saw_review:
            raise ContractError(f"{gate_name} PASS requires independent review evidence")
    if gate_name == "corporate_acceptance" and gate_status == "PASS":
        if CORPORATE_ACCEPTANCE_REQUIRE_EXECUTABLE_CURRENTNESS:
            if not saw_executable:
                raise ContractError(
                    "corporate_acceptance PASS requires successful executable evidence"
                )
        elif saw_executable_ref and not saw_executable:
            raise ContractError(
                "corporate_acceptance PASS with executable refs requires "
                "successful executable evidence"
            )
    if gate_status == "FAIL" and not saw_failure:
        raise ContractError("FAIL gate requires failed evidence")
