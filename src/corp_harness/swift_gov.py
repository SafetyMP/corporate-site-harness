"""Assist-only bridge from corp-harness gov to optional corp-gov-check.

Python remains the sole writer for program.json. This module never records
artifacts, advances phases, or grants user/factory authorization.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from corp_harness.contracts import (
    CA_CURRENTNESS_MODE,
    CORPORATE_ACCEPTANCE_REQUIRE_EXECUTABLE_CURRENTNESS,
    ContractError,
)
from corp_harness.model import (
    FORWARD_TRANSITIONS,
    PHASES,
    REQUIRED_GATES,
    Program,
    digest_path,
)
from corp_harness.runtime_engine import action_routed_layer, load_trust_state
from corp_harness.site_gate_oracles import pending_oracle_pins, validate_handoff_schema_v2

GOV_ASSIST_UNAVAILABLE = "GOV_ASSIST_UNAVAILABLE"
GOV_REQUIRED = "GOV_REQUIRED"
# Swift/corp-gov-check must never write these sole-writer files (ACC-TR-AH-010).
PYTHON_SOLE_WRITER_FILES = frozenset(
    {
        "program.json",
        "trust-state.json",
        "trust-event-log.jsonl",
        "trust-log-anchor.json",
        "trust-mutation-permit.json",
    }
)
P0_COMMANDS = frozenset(
    {
        "diagnose",
        "scaffold-approval",
        "scaffold-factory-auth",
        "explain-transition",
    }
)
P1_COMMANDS = frozenset(
    {
        "explain-stale",
        "check-handoff",
    }
)
P2_COMMANDS = frozenset(
    {
        "check-authorized-surfaces",
    }
)
ASSIST_COMMANDS = P0_COMMANDS | P1_COMMANDS | P2_COMMANDS
HEAVY_COMMANDS = frozenset({"validate-action", "write-receipt"})
ASSIST_SCHEMA = "corporate-site-gov-assist/v1"
PROOF_SCHEMA = "corporate-site-proof-envelope/v1"


def factory_checkout_root() -> Path:
    """Return the factory checkout that owns this package (…/src/corp_harness)."""
    return Path(__file__).resolve().parents[2]


def find_corp_gov_check(search_root: Path | None = None) -> Path | None:
    """Locate corp-gov-check, or None when Swift assist is unavailable."""
    override = os.environ.get("CORP_GOV_CHECK", "").strip()
    if override:
        candidate = Path(override).expanduser()
        return candidate if candidate.is_file() and os.access(candidate, os.X_OK) else None

    which = shutil.which("corp-gov-check")
    if which:
        path = Path(which)
        if path.is_file() and os.access(path, os.X_OK):
            return path

    root = (search_root or factory_checkout_root()).expanduser().resolve()
    for relative in (
        Path("swift/.build/debug/corp-gov-check"),
        Path("swift/.build/release/corp-gov-check"),
        Path("swift/.build/arm64-apple-macosx/debug/corp-gov-check"),
        Path("swift/.build/arm64-apple-macosx/release/corp-gov-check"),
        Path("swift/.build/x86_64-apple-macosx/debug/corp-gov-check"),
        Path("swift/.build/x86_64-apple-macosx/release/corp-gov-check"),
    ):
        candidate = root / relative
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def run_gov_command(
    command: str,
    root: Path,
    *,
    to_phase: str | None = None,
    paths: list[str] | None = None,
    action: str | None = None,
    search_root: Path | None = None,
) -> tuple[dict[str, Any], int]:
    """Invoke corp-gov-check for assist or heavy validate-action / write-receipt."""
    if command not in ASSIST_COMMANDS | HEAVY_COMMANDS:
        raise ContractError(f"unsupported gov command: {command}")

    binary = find_corp_gov_check(search_root)
    if binary is None:
        if command in HEAVY_COMMANDS:
            return (
                {
                    "ok": False,
                    "assist": False,
                    "mutation": False,
                    "error": GOV_REQUIRED,
                    "detail": (
                        f"corp-gov-check required for heavy {command} but not found"
                    ),
                    "command": command,
                },
                2,
            )
        return (
            {
                "ok": False,
                "assist": True,
                "mutation": False,
                "error": GOV_ASSIST_UNAVAILABLE,
                "detail": (
                    "corp-gov-check not found; install/build the optional swift/ "
                    "package or set CORP_GOV_CHECK. Core init/record/next/check "
                    "continue to work without Swift assist."
                ),
                "command": command,
            },
            2,
        )

    argv = [str(binary), command, "--root", str(root.expanduser().resolve())]
    if command == "explain-transition":
        if not to_phase:
            raise ContractError("explain-transition requires --to")
        argv.extend(["--to", to_phase])
    if command == "check-authorized-surfaces" and paths:
        for path in paths:
            argv.extend(["--path", path])
    if command == "validate-action":
        if not action:
            raise ContractError("validate-action requires --action")
        argv.extend(["--action", action])

    env = os.environ.copy()
    src = str(factory_checkout_root() / "src")
    prior = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = src if not prior else f"{src}{os.pathsep}{prior}"
    env["CORP_HARNESS_ASSIST_IMPL"] = "1"

    try:
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
    except OSError as exc:
        # Heavy proof commands fail closed; assist commands soft-fail (SG-03).
        if command in HEAVY_COMMANDS:
            return (
                {
                    "ok": False,
                    "assist": False,
                    "mutation": False,
                    "error": GOV_REQUIRED,
                    "detail": f"failed to execute corp-gov-check: {exc}",
                    "command": command,
                },
                2,
            )
        return (
            {
                "ok": False,
                "assist": True,
                "mutation": False,
                "error": GOV_ASSIST_UNAVAILABLE,
                "detail": f"failed to execute corp-gov-check: {exc}",
                "command": command,
            },
            2,
        )

    stdout = completed.stdout.strip()
    if not stdout:
        # Heavy proof commands fail closed; assist commands soft-fail (SG-03).
        if command in HEAVY_COMMANDS:
            return (
                {
                    "ok": False,
                    "assist": False,
                    "mutation": False,
                    "error": GOV_REQUIRED,
                    "detail": (
                        "corp-gov-check produced empty stdout on heavy command; "
                        f"stderr={completed.stderr.strip()!r} "
                        f"exit={completed.returncode}"
                    ),
                    "command": command,
                },
                2,
            )
        return (
            {
                "ok": False,
                "assist": True,
                "mutation": False,
                "error": GOV_ASSIST_UNAVAILABLE,
                "detail": (
                    "corp-gov-check produced empty stdout; "
                    f"stderr={completed.stderr.strip()!r} exit={completed.returncode}"
                ),
                "command": command,
            },
            2,
        )
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ContractError(f"corp-gov-check returned non-JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ContractError("corp-gov-check JSON root must be an object")
    payload.setdefault("assist", True)
    payload.setdefault("mutation", False)
    exit_code = 0 if payload.get("ok") else (completed.returncode or 1)
    return payload, exit_code


def build_assist_payload(
    command: str,
    root: Path,
    *,
    to_phase: str | None = None,
    paths: list[str] | None = None,
) -> dict[str, Any]:
    """Build assist JSON without mutating program state (read-only)."""
    if command not in ASSIST_COMMANDS:
        raise ContractError(f"unsupported gov command: {command}")

    program_path = root.expanduser().resolve() / "program.json"
    if not program_path.is_file():
        raise ContractError(f"program does not exist: {program_path}")
    program = Program.load(program_path)
    program_digest = digest_path(program_path)
    phase = program.phase

    if command == "diagnose":
        payload = _diagnose(program, program_digest)
    elif command == "scaffold-approval":
        payload = _scaffold_approval(program, program_digest)
    elif command == "scaffold-factory-auth":
        payload = _scaffold_factory_auth(program, program_digest)
    elif command == "explain-transition":
        payload = _explain_transition(program, program_digest, to_phase)
    elif command == "explain-stale":
        payload = _explain_stale(program, program_digest)
    elif command == "check-handoff":
        payload = _check_handoff(program, program_digest)
    else:
        payload = _check_authorized_surfaces(program, program_digest, paths=paths)

    # Re-read digest/phase to prove assist did not mutate (same process).
    after_digest = digest_path(program_path)
    after_phase = Program.load(program_path).phase
    if after_digest != program_digest or after_phase != phase:
        raise ContractError("assist path mutated program.json (forbidden)")

    check_ok = True
    if command == "check-authorized-surfaces":
        surfaces = payload.get("surfaces")
        if isinstance(surfaces, dict):
            check_ok = bool(surfaces.get("check_ok"))

    payload.update(
        {
            "schema": ASSIST_SCHEMA,
            "ok": check_ok,
            "assist": True,
            "mutation": False,
            "command": command,
            "program_id": program.program_id,
            "phase": phase,
            "revision": program.revision,
            "program_digest": program_digest,
            "program_digest_after": after_digest,
            "phase_unchanged": after_phase == phase,
        }
    )
    return payload


def _ca_currentness(program: Program) -> dict[str, Any]:
    gate = program.gates.get("corporate_acceptance")
    if gate is None:
        return {
            "present": False,
            "status": None,
            "current": False,
            "currentness_mode": CA_CURRENTNESS_MODE,
            "review_only_pass_not_current": True,
            "reasons": ["corporate_acceptance gate is missing"],
        }

    current = program.gate_is_current("corporate_acceptance")
    reasons: list[str] = []
    if gate.status == "PASS" and not current:
        if CORPORATE_ACCEPTANCE_REQUIRE_EXECUTABLE_CURRENTNESS:
            reasons.append(
                "Stage-2 dual-evidence currentness: review-only corporate_acceptance "
                "PASS is not current without successful executable evidence"
            )
        else:
            reasons.append("corporate_acceptance gate is not current")
        # Inspect evidence classes for a clearer assist signal.
        try:
            report = json.loads(Path(gate.report_path).read_text(encoding="utf-8"))
            refs = report.get("evidence_refs") or []
            saw_exec = False
            saw_review = False
            for item in refs:
                if not isinstance(item, dict):
                    continue
                path = Path(str(item.get("path", "")))
                if not path.is_file():
                    continue
                body = json.loads(path.read_text(encoding="utf-8"))
                schema = body.get("schema")
                if schema == "corporate-site-evidence/v1":
                    saw_exec = True
                elif schema == "corporate-site-review-evidence/v1":
                    saw_review = True
            if saw_review and not saw_exec:
                reasons.append(
                    "evidence is review-only; scaffolds must not imply current CA PASS"
                )
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            reasons.append("unable to inspect corporate_acceptance evidence refs")
    elif not current:
        reasons.append("corporate_acceptance gate is not current")

    return {
        "present": True,
        "status": gate.status,
        "current": current,
        "currentness_mode": CA_CURRENTNESS_MODE,
        "review_only_pass_not_current": True,
        "reasons": reasons,
    }


def _diagnose(program: Program, program_digest: str) -> dict[str, Any]:
    ca = _ca_currentness(program)
    issues = program.current_issues()
    return {
        "diagnosis": {
            "program_digest": program_digest,
            "phase": program.phase,
            "program_kind": program.program_kind,
            "issues": issues,
            "corporate_acceptance": ca,
            "gates": {
                name: {
                    "status": gate.status,
                    "current": program.gate_is_current(name),
                    "revision": gate.revision,
                }
                for name, gate in sorted(program.gates.items())
            },
        }
    }


def _scaffold_approval(program: Program, program_digest: str) -> dict[str, Any]:
    ca = _ca_currentness(program)
    dossier = program.artifacts.get("final_dossier")
    gate_digests = {
        name: gate.report_sha256 for name, gate in sorted(program.gates.items())
    }
    draft = {
        "schema": "corporate-site-user-approval/v1",
        "draft": True,
        "approved": False,
        "granted_by": "pending-user",
        "granted_at": "",
        "program_id": program.program_id,
        "revision": program.revision,
        "final_dossier_sha256": dossier.sha256 if dossier is not None else "",
        "gate_report_sha256": gate_digests,
        "assist_notes": [
            "Non-granting scaffold only; user must set approved=true, granted_by=user, "
            "and granted_at before recording.",
            "Does not record artifacts or advance phase.",
        ],
        "bound_program_digest": program_digest,
        "corporate_acceptance_current": ca["current"],
        "implies_current_corporate_acceptance_pass": False,
    }
    if ca["present"] and ca["status"] == "PASS" and not ca["current"]:
        draft["assist_notes"].append(
            "corporate_acceptance status is PASS but not current under Stage-2; "
            "this scaffold does not imply a current CA PASS."
        )
    return {
        "scaffold": draft,
        "corporate_acceptance": ca,
        "grants_authorization": False,
    }


def _scaffold_factory_auth(program: Program, program_digest: str) -> dict[str, Any]:
    ca = _ca_currentness(program)
    master = program.artifacts.get("master_spec")
    factory_root = str(Path(program.site_path).expanduser().resolve())
    draft = {
        "schema": "corporate-site-factory-authorization/v1",
        "draft": True,
        "authorized": False,
        "granted_by": "pending-user",
        "granted_at": "",
        "program_id": program.program_id,
        "revision": program.revision,
        "master_spec_sha256": master.sha256 if master is not None else "",
        "factory_root": factory_root,
        "authorized_surfaces": [],
        "assist_notes": [
            "Non-granting scaffold only; user must set authorized=true, granted_by=user, "
            "granted_at, and authorized_surfaces before recording.",
            "Does not record artifacts or advance phase.",
        ],
        "bound_program_digest": program_digest,
        "corporate_acceptance_current": ca["current"],
        "implies_current_corporate_acceptance_pass": False,
    }
    if program.program_kind != "factory":
        draft["assist_notes"].append(
            "program_kind is not factory; factory_authorization is invalid for product programs."
        )
    if ca["present"] and ca["status"] == "PASS" and not ca["current"]:
        draft["assist_notes"].append(
            "corporate_acceptance status is PASS but not current under Stage-2; "
            "this scaffold does not imply a current CA PASS."
        )
    return {
        "scaffold": draft,
        "corporate_acceptance": ca,
        "grants_authorization": False,
    }


def _explain_transition(
    program: Program,
    program_digest: str,
    to_phase: str | None,
) -> dict[str, Any]:
    if not to_phase:
        raise ContractError("explain-transition requires --to")
    if to_phase not in PHASES:
        raise ContractError(f"unknown phase: {to_phase}")

    ca = _ca_currentness(program)
    required_actor = FORWARD_TRANSITIONS.get((program.phase, to_phase))
    blockers: list[str] = []
    if required_actor is None:
        blockers.append(f"transition not allowed: {program.phase} -> {to_phase}")
    else:
        blockers.extend(program.phase_requirements(to_phase))
    if (
        ca["present"]
        and not ca["current"]
        and "corporate_acceptance" in REQUIRED_GATES.get(to_phase, ())
    ):
        note = (
            "corporate_acceptance is not current under Stage-2 dual-evidence rules"
        )
        if note not in blockers:
            blockers.append(note)

    return {
        "transition": {
            "from_phase": program.phase,
            "to_phase": to_phase,
            "required_actor": required_actor,
            "allowed": required_actor is not None and not blockers,
            "blockers": blockers,
            "program_digest": program_digest,
            "corporate_acceptance": ca,
            "implies_current_corporate_acceptance_pass": False,
        }
    }


def _explain_stale(program: Program, program_digest: str) -> dict[str, Any]:
    """Explain artifact/gate staleness with Stage-2 CA currentness awareness."""
    ca = _ca_currentness(program)
    items: list[dict[str, Any]] = []
    cascade: list[str] = []

    for name, artifact in sorted(program.artifacts.items()):
        reasons: list[str] = []
        current_sha: str | None = None
        try:
            current_sha = digest_path(Path(artifact.path))
            if current_sha != artifact.sha256:
                reasons.append(
                    f"file digest {current_sha} != recorded {artifact.sha256}"
                )
        except ContractError as exc:
            reasons.append(str(exc))
        if reasons:
            items.append(
                {
                    "kind": "artifact",
                    "name": name,
                    "stale": True,
                    "reasons": reasons,
                    "recorded_sha256": artifact.sha256,
                    "current_sha256": current_sha,
                }
            )
            cascade.append(f"stale artifact {name} may stale dependent gates")

    for name, gate in sorted(program.gates.items()):
        current = program.gate_is_current(name)
        reasons: list[str] = []
        if not current:
            if name == "corporate_acceptance":
                reasons.extend(ca["reasons"] or ["corporate_acceptance is not current"])
            else:
                reasons.append(f"gate {name} is not current")
            items.append(
                {
                    "kind": "gate",
                    "name": name,
                    "stale": True,
                    "status": gate.status,
                    "current": False,
                    "reasons": reasons,
                    "report_sha256": gate.report_sha256,
                    "target_sha256": gate.target_sha256,
                }
            )
            if name == "corporate_acceptance" and gate.status == "PASS" and not current:
                cascade.append(
                    "Stage-2: review-only corporate_acceptance PASS is not current; "
                    "do not treat as a current CA PASS when recording gates"
                )

    stale_issues = [
        issue
        for issue in program.current_issues()
        if "stale" in issue or "not current" in issue
    ]
    return {
        "staleness": {
            "program_digest": program_digest,
            "phase": program.phase,
            "items": items,
            "cascade": cascade,
            "stale_issues": stale_issues,
            "has_stale": bool(items),
            "corporate_acceptance": ca,
            "implies_current_corporate_acceptance_pass": False,
        }
    }


def _check_handoff(program: Program, program_digest: str) -> dict[str, Any]:
    """Check corporate_handoff file + pinned artifact digests (read-only)."""
    ca = _ca_currentness(program)
    handoff_art = program.artifacts.get("corporate_handoff")
    if handoff_art is None:
        return {
            "handoff": {
                "present": False,
                "current": False,
                "file_current": False,
                "issues": ["missing artifact corporate_handoff"],
                "artifact_digest_checks": [],
                "program_digest": program_digest,
                "corporate_acceptance": ca,
                "implies_current_corporate_acceptance_pass": False,
            }
        }

    issues: list[str] = []
    path = Path(handoff_art.path)
    current_sha: str | None = None
    file_current = False
    try:
        current_sha = digest_path(path)
        file_current = current_sha == handoff_art.sha256
        if not file_current:
            issues.append(
                f"corporate_handoff file digest mismatch: "
                f"{current_sha} != recorded {handoff_art.sha256}"
            )
    except ContractError as exc:
        issues.append(f"corporate_handoff unreadable: {exc}")

    body: dict[str, Any] = {}
    schema: str | None = None
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                body = loaded
                schema = str(body.get("schema") or "") or None
            else:
                issues.append("corporate_handoff root must be an object")
        except (OSError, json.JSONDecodeError) as exc:
            issues.append(f"corporate_handoff JSON error: {exc}")

    digest_checks: list[dict[str, Any]] = []
    pinned = body.get("artifact_digests") if isinstance(body.get("artifact_digests"), dict) else {}
    for name, expected in sorted(pinned.items()):
        expected_sha = str(expected)
        art = program.artifacts.get(name)
        entry: dict[str, Any] = {
            "name": name,
            "handoff_sha256": expected_sha,
            "program_sha256": art.sha256 if art is not None else None,
            "match": False,
            "file_current": False,
        }
        if art is None:
            issues.append(f"handoff pins missing program artifact {name}")
            digest_checks.append(entry)
            continue
        entry["match"] = art.sha256 == expected_sha
        if not entry["match"]:
            issues.append(
                f"handoff artifact_digests[{name}] mismatch vs program "
                f"({expected_sha} != {art.sha256})"
            )
        try:
            live = digest_path(Path(art.path))
            entry["file_current"] = live == art.sha256
            entry["file_sha256"] = live
            if not entry["file_current"]:
                issues.append(f"handoff-pinned artifact {name} file is stale")
        except ContractError as exc:
            issues.append(f"handoff-pinned artifact {name}: {exc}")
        digest_checks.append(entry)

    # Stage-2 awareness: handoff integrity must not imply CA currentness.
    stage2_notes: list[str] = []
    if ca["present"] and ca["status"] == "PASS" and not ca["current"]:
        stage2_notes.append(
            "corporate_acceptance PASS is not current under Stage-2; "
            "handoff check does not imply current CA PASS"
        )

    if digest_checks:
        integrity_ok = file_current and all(
            bool(c.get("match")) and bool(c.get("file_current")) for c in digest_checks
        )
    else:
        integrity_ok = file_current

    oracle_pins: dict[str, Any] = {
        "schema": schema,
        "pending": [],
        "issues": [],
    }
    if schema == "corporate-site-handoff/v1":
        oracle_pins["issues"].append("handoff schema is v1; v2 required for site-gate oracles")
    elif schema == "corporate-site-handoff/v2":
        try:
            validate_handoff_schema_v2(body)
            oracle_pins["pending"] = pending_oracle_pins(body)
        except ContractError as exc:
            oracle_pins["issues"].append(str(exc))
            issues.append(f"site_gate_oracles: {exc}")

    return {
        "handoff": {
            "present": True,
            "path": str(path),
            "schema": schema,
            "recorded_sha256": handoff_art.sha256,
            "current_sha256": current_sha,
            "file_current": file_current,
            "artifact_digest_checks": digest_checks,
            "oracle_pins": oracle_pins,
            "current": integrity_ok,
            "integrity_ok": integrity_ok,
            "issues": issues,
            "stage2_notes": stage2_notes,
            "program_digest": program_digest,
            "corporate_acceptance": ca,
            "implies_current_corporate_acceptance_pass": False,
        }
    }


def _normalize_relative_surface(value: str) -> str:
    text = value.strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text.rstrip("/")


def _surface_covers_path(surface: str, candidate: str) -> bool:
    surface_norm = _normalize_relative_surface(surface)
    candidate_norm = _normalize_relative_surface(candidate)
    if not surface_norm or not candidate_norm:
        return False
    return candidate_norm == surface_norm or candidate_norm.startswith(
        surface_norm + "/"
    )


def _check_authorized_surfaces(
    program: Program,
    program_digest: str,
    *,
    paths: list[str] | None = None,
) -> dict[str, Any]:
    """Allow/deny candidate paths after authorized_surfaces existence checks."""
    ca = _ca_currentness(program)
    factory_root = Path(program.site_path).expanduser().resolve()
    auth_art = program.artifacts.get("factory_authorization")
    issues: list[str] = []
    existence: list[dict[str, Any]] = []
    evaluations: list[dict[str, Any]] = []
    authorized_surfaces: list[str] = []

    if auth_art is None:
        issues.append("missing artifact factory_authorization")
        return {
            "surfaces": {
                "present": False,
                "factory_root": str(factory_root),
                "authorized_surfaces": [],
                "existence": [],
                "existence_ok": False,
                "evaluations": [],
                "allowed": [],
                "denied": [],
                "check_ok": False,
                "issues": issues,
                "program_digest": program_digest,
                "tree_unchanged": True,
                "corporate_acceptance": ca,
                "implies_current_corporate_acceptance_pass": False,
                "grants_authorization": False,
            }
        }

    auth_path = Path(auth_art.path)
    body: dict[str, Any] = {}
    try:
        loaded = json.loads(auth_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            body = loaded
        else:
            issues.append("factory_authorization root must be an object")
    except (OSError, json.JSONDecodeError) as exc:
        issues.append(f"factory_authorization JSON error: {exc}")

    raw_surfaces = body.get("authorized_surfaces")
    if not isinstance(raw_surfaces, list) or not raw_surfaces:
        issues.append("factory_authorization.authorized_surfaces missing or empty")
    else:
        for item in raw_surfaces:
            if not isinstance(item, str) or not item.strip():
                issues.append("authorized_surfaces entries must be non-empty strings")
                continue
            surface = _normalize_relative_surface(item)
            if surface.startswith("/") or ".." in Path(surface).parts:
                issues.append(f"authorized surface must be a relative path: {item}")
                continue
            authorized_surfaces.append(surface)

    # Python existence checks run before allow/deny evaluation.
    for surface in authorized_surfaces:
        resolved = (factory_root / surface).resolve()
        try:
            resolved.relative_to(factory_root)
            escapes = False
        except ValueError:
            escapes = True
        exists = (not escapes) and resolved.exists()
        entry = {
            "surface": surface,
            "exists": exists,
            "escapes_factory_root": escapes,
            "resolved": str(resolved),
        }
        existence.append(entry)
        if escapes:
            issues.append(f"authorized surface escapes factory root: {surface}")
        elif not exists:
            issues.append(f"AUTHORIZED_SURFACE_MISSING: {surface}")

    existence_ok = bool(authorized_surfaces) and all(
        item["exists"] and not item["escapes_factory_root"] for item in existence
    )

    candidates = [_normalize_relative_surface(p) for p in (paths or []) if p.strip()]
    for candidate in candidates:
        if not candidate or candidate.startswith("/") or ".." in Path(candidate).parts:
            evaluations.append(
                {
                    "path": candidate,
                    "decision": "deny",
                    "reason": "path must be relative without ..",
                    "matched_surface": None,
                }
            )
            continue
        matched = next(
            (
                surface
                for surface in authorized_surfaces
                if _surface_covers_path(surface, candidate)
            ),
            None,
        )
        if matched is None:
            evaluations.append(
                {
                    "path": candidate,
                    "decision": "deny",
                    "reason": "outside authorized_surfaces",
                    "matched_surface": None,
                }
            )
        else:
            evaluations.append(
                {
                    "path": candidate,
                    "decision": "allow",
                    "reason": "within authorized_surfaces",
                    "matched_surface": matched,
                }
            )

    allowed = [e["path"] for e in evaluations if e["decision"] == "allow"]
    denied = [e["path"] for e in evaluations if e["decision"] == "deny"]
    # Existence must pass before allow/deny can pass the check.
    path_ok = not denied if candidates else True
    check_ok = existence_ok and path_ok and not issues

    return {
        "surfaces": {
            "present": True,
            "path": str(auth_path),
            "factory_root": str(factory_root),
            "authorized_surfaces": authorized_surfaces,
            "existence": existence,
            "existence_ok": existence_ok,
            "evaluations": evaluations,
            "allowed": allowed,
            "denied": denied,
            "check_ok": check_ok,
            "issues": issues,
            "program_digest": program_digest,
            "tree_unchanged": True,
            "corporate_acceptance": ca,
            "implies_current_corporate_acceptance_pass": False,
            "grants_authorization": False,
        }
    }


def _snapshot_sole_writer_digests(root: Path) -> dict[str, str | None]:
    base = root.expanduser().resolve()
    out: dict[str, str | None] = {}
    for name in PYTHON_SOLE_WRITER_FILES:
        path = base / name
        out[name] = digest_path(path) if path.is_file() else None
    return out


def _assert_sole_writer_untouched(root: Path, before: dict[str, str | None]) -> None:
    after = _snapshot_sole_writer_digests(root)
    for name in PYTHON_SOLE_WRITER_FILES:
        if after.get(name) != before.get(name):
            raise ContractError(
                f"Swift/gov path mutated sole-writer file {name} (forbidden)"
            )


def build_write_receipt_payload(root: Path) -> dict[str, Any]:
    """Heavy write-receipt (mint_gov_receipt seal): ProofEnvelope; no program write."""
    program_path = root.expanduser().resolve() / "program.json"
    if not program_path.is_file():
        raise ContractError(f"program does not exist: {program_path}")
    before_sole = _snapshot_sole_writer_digests(root)
    before = digest_path(program_path)
    state = load_trust_state(root)
    action = "mint_gov_receipt"
    layer = action_routed_layer(state.trust_score, action)
    payload = {
        "schema": PROOF_SCHEMA,
        "ok": True,
        "assist": False,
        "mutation": False,
        "command": "write-receipt",
        "kind": "gov_seal",
        "program_digest": before,
        "program_digest_after": before,
        "action": action,
        "layer": layer,
        "verdict": "accept",
        "trust_score": float(state.trust_score),
        "execution_layer": state.execution_layer,
        "phase_unchanged": True,
    }
    after = digest_path(program_path)
    if after != before:
        raise ContractError("write-receipt mutated program.json (forbidden)")
    _assert_sole_writer_untouched(root, before_sole)
    payload["program_digest_after"] = after
    return payload


def build_validate_action_payload(root: Path, action: str) -> dict[str, Any]:
    """Heavy validate-action: ProofEnvelope only; never mutates program.json."""
    program_path = root.expanduser().resolve() / "program.json"
    if not program_path.is_file():
        raise ContractError(f"program does not exist: {program_path}")
    before_sole = _snapshot_sole_writer_digests(root)
    before = digest_path(program_path)
    state = load_trust_state(root)
    layer = action_routed_layer(state.trust_score, action)
    verdict = "accept" if layer in {"light", "heavy"} else "reject"
    payload = {
        "schema": PROOF_SCHEMA,
        "ok": True,
        "assist": False,
        "mutation": False,
        "command": "validate-action",
        "kind": "validation_verdict",
        "program_digest": before,
        "program_digest_after": before,
        "action": action,
        "layer": layer,
        "verdict": verdict,
        "trust_score": float(state.trust_score),
        "execution_layer": state.execution_layer,
        "phase_unchanged": True,
    }
    after = digest_path(program_path)
    if after != before:
        raise ContractError("validate-action mutated program.json (forbidden)")
    _assert_sole_writer_untouched(root, before_sole)
    payload["program_digest_after"] = after
    return payload


def main(argv: list[str] | None = None) -> int:
    """Internal CLI used by corp-gov-check (and test stubs)."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        print(
            "usage: python -m corp_harness.swift_gov "
            "(--assist <cmd>|--validate-action|--write-receipt) --root PATH "
            "[--to PHASE] [--path REL ...] [--action ACTION]",
            file=sys.stderr,
        )
        return 2
    mode = args[0]
    if mode not in {"--assist", "--validate-action", "--write-receipt"}:
        print(
            "expected --assist <command>, --validate-action, or --write-receipt",
            file=sys.stderr,
        )
        return 2
    root: Path | None = None
    to_phase: str | None = None
    paths: list[str] = []
    action: str | None = None
    command: str | None = None
    idx = 1
    if mode == "--assist":
        if len(args) < 2:
            print("missing assist command", file=sys.stderr)
            return 2
        command = args[1]
        idx = 2
    while idx < len(args):
        if args[idx] == "--root" and idx + 1 < len(args):
            root = Path(args[idx + 1])
            idx += 2
            continue
        if args[idx] == "--to" and idx + 1 < len(args):
            to_phase = args[idx + 1]
            idx += 2
            continue
        if args[idx] == "--path" and idx + 1 < len(args):
            paths.append(args[idx + 1])
            idx += 2
            continue
        if args[idx] == "--action" and idx + 1 < len(args):
            action = args[idx + 1]
            idx += 2
            continue
        print(f"unknown argument: {args[idx]}", file=sys.stderr)
        return 2
    if root is None:
        print("--root is required", file=sys.stderr)
        return 2
    try:
        if mode == "--validate-action":
            if not action:
                raise ContractError("--action is required for validate-action")
            payload = build_validate_action_payload(root, action)
        elif mode == "--write-receipt":
            payload = build_write_receipt_payload(root)
        else:
            assert command is not None
            payload = build_assist_payload(
                command,
                root,
                to_phase=to_phase,
                paths=paths or None,
            )
    except ContractError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": str(exc),
                    "assist": mode == "--assist",
                    "mutation": False,
                }
            )
        )
        return 3
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
