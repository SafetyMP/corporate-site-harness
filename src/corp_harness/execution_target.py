"""ADR-EX-001: legal execution targets for site compute (placement, not a plane)."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from corp_harness.contracts import ContractError

DENIAL_EXECUTION_TARGET = "EXECUTION_TARGET_DENIED"

DEFAULT_EXECUTION_TARGET = "worktree"
LITERAL_TARGETS = frozenset({"worktree", "isolated_copy", "cloud_subagent"})
OPENSHELL_PREFIX = "openshell:"
RESERVED_OPENSHELL_NAMES = frozenset({"hermes", "pi", "eval"})
OPENSHELL_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")

_LOGGER = logging.getLogger(__name__)

CORPORATE_CONTROL_ROLES = frozenset(
    {
        "corporate-ceo",
        "ceo",
        "corporate-coo",
        "coo",
        "corporate-specialist",
        "specialist",
        "site-manager",
    }
)
SITE_REVIEWER_ROLES = frozenset(
    {
        "operations-excellence",
        "ops-excellence",
        "corporate-adversary",
        "adversary",
        "conformance",
    }
)
CORPORATE_ARTIFACT_NAMES = frozenset(
    {
        "program.json",
        "master-spec.md",
        "acceptance.json",
        "gates.json",
        "kpis.json",
        "factory-authorization.json",
        "user_approval.json",
        "user-approval.json",
        "corporate-handoff.json",
    }
)
FORBIDDEN_CLI_RUNTIME_TOKENS = frozenset(
    {
        "sandbox",
        "vm",
        "openshell",
        "e2b",
        "daytona",
        "vercel-sandbox",
        "cloudflare",
        "attach-sandbox",
        "start-vm",
    }
)

_ISOLATION_PASS_MARKERS = (
    "sandbox passed",
    "sandbox green",
    "vm green",
    "vm passed",
    "openshell passed",
    "openshell green",
    "isolated_copy passed",
    "cloud agent passed",
    "isolation green",
    "sandbox-prose-as-pass",
    "named-gate pass",
    "named gate pass",
)


def _casefold_name(value: str) -> str:
    return Path(value).name.casefold()


def is_reserved_openshell_name(name: str) -> bool:
    raw = str(name or "").strip()
    if not raw:
        return False
    if _casefold_name(raw) in RESERVED_OPENSHELL_NAMES:
        return True
    try:
        resolved = Path(raw).expanduser().resolve()
    except OSError:
        return False
    return resolved.name.casefold() in RESERVED_OPENSHELL_NAMES


def site_path_hits_reserved(path: str | Path) -> bool:
    candidate = Path(path).expanduser()
    names = [_casefold_name(candidate.name)]
    try:
        names.append(candidate.resolve().name.casefold())
    except OSError:
        _LOGGER.debug(
            "Failed to resolve site_path candidate for reserved-name check: %s",
            candidate,
        )
    if candidate.is_symlink():
        try:
            names.append(candidate.resolve(strict=False).name.casefold())
        except OSError:
            _LOGGER.debug(
                "Failed to resolve symlink candidate for reserved-name check: %s",
                candidate,
            )
    return any(name in RESERVED_OPENSHELL_NAMES for name in names)


def assert_legal_site_path(path: str | Path) -> None:
    if site_path_hits_reserved(path):
        raise ContractError(
            f"reserved OpenShell name is illegal as site_path: {path}"
        )


def normalize_execution_target(raw: Any) -> str:
    """Omitted, null, or empty means worktree. Unknown tokens are not coerced."""
    if raw is None:
        return DEFAULT_EXECUTION_TARGET
    if not isinstance(raw, str):
        raise ContractError("execution_target must be a string when present")
    token = raw.strip()
    if not token:
        return DEFAULT_EXECUTION_TARGET
    return token


def parse_execution_target(raw: Any) -> tuple[str, str | None]:
    """Return (normalized_token, deny_id_if_illegal)."""
    try:
        token = normalize_execution_target(raw)
    except ContractError:
        return ("", "EX-DENY-005")
    if token in LITERAL_TARGETS:
        return (token, None)
    if token.startswith(OPENSHELL_PREFIX):
        name = token[len(OPENSHELL_PREFIX) :]
        if is_reserved_openshell_name(name):
            return (token, "EX-DENY-006")
        if not OPENSHELL_NAME_RE.fullmatch(name):
            return (token, "EX-DENY-005")
        return (f"{OPENSHELL_PREFIX}{name}", None)
    return (token, "EX-DENY-005")


def isolation_green_claims_named_gate_pass(packet: dict[str, Any]) -> bool:
    if packet.get("named_gate_pass_from_isolation") is True:
        return True
    blob = " ".join(
        str(packet.get(key) or "")
        for key in ("pass_claim", "notes", "evidence")
    ).casefold()
    return any(marker in blob for marker in _ISOLATION_PASS_MARKERS)


def claims_actor_user(packet: dict[str, Any]) -> bool:
    if str(packet.get("actor") or "").strip().casefold() == "user":
        return True
    if packet.get("autopilot") is True:
        return True
    if packet.get("pr_subscription_records_user_approval") is True:
        return True
    command = str(packet.get("connect_command") or packet.get("shell") or "")
    return "--actor user" in command


def claims_cursor_remote_into_openshell(packet: dict[str, Any]) -> bool:
    command = " ".join(
        str(packet.get(key) or "")
        for key in ("connect_command", "editor", "shell")
    ).casefold()
    if "--editor cursor" in command or "cursor remote" in command:
        return True
    target, _deny = parse_execution_target(packet.get("execution_target"))
    return bool(packet.get("cursor_remote")) and target.startswith(OPENSHELL_PREFIX)


def write_set_hits_corporate_root(
    packet: dict[str, Any], *, program_root: Path | None = None
) -> bool:
    write_set = packet.get("write_set")
    items = write_set if isinstance(write_set, list) else []
    for item in items:
        if not isinstance(item, str):
            continue
        if Path(item).name.casefold() in CORPORATE_ARTIFACT_NAMES:
            return True
    root_raw = str(packet.get("root") or "").strip()
    corp = program_root
    if corp is None and packet.get("program_root"):
        corp = Path(str(packet["program_root"]))
    if corp is None or not root_raw:
        return False
    try:
        return Path(root_raw).expanduser().resolve() == corp.expanduser().resolve()
    except OSError:
        return False


def _role(packet: dict[str, Any]) -> str:
    return str(packet.get("role") or packet.get("subagent_type") or "").strip()


def _task_class(packet: dict[str, Any]) -> str:
    return str(packet.get("task_class") or "").strip()


def validate_packet_execution_target(
    packet: dict[str, Any],
    *,
    program_root: Path | None = None,
) -> dict[str, Any]:
    """Fail closed on illegal placement. Does not join the seven sealed fields."""
    if not isinstance(packet, dict):
        return _deny("packet must be an object", "EX-DENY-005")
    if claims_actor_user(packet):
        return _deny(
            "agents never pass --actor user; "
            "autopilot/PR-subscription cannot record user-gated artifacts",
            "EX-DENY-002",
        )
    if claims_cursor_remote_into_openshell(packet):
        return _deny(
            "Cursor Remote and openshell sandbox connect --editor cursor are denied",
            "EX-DENY-004",
        )
    if isolation_green_claims_named_gate_pass(packet):
        return _deny(
            "isolation/VM/OpenShell green is not a named-gate PASS",
            "EX-DENY-001",
        )
    site_path = packet.get("site_path")
    if isinstance(site_path, str) and site_path_hits_reserved(site_path):
        return _deny("reserved OpenShell name is illegal as site_path", "EX-DENY-003")

    token, deny_id = parse_execution_target(packet.get("execution_target"))
    if deny_id == "EX-DENY-006":
        return _deny("reserved OpenShell name is illegal as openshell:<name>", deny_id)
    if deny_id == "EX-DENY-005":
        return _deny(
            "unknown execution_target fails closed and is not coerced to worktree",
            deny_id,
        )

    role = _role(packet)
    task_class = _task_class(packet)
    if role in CORPORATE_CONTROL_ROLES and token != DEFAULT_EXECUTION_TARGET:
        return _deny(
            "corporate/control roles must not carry a non-worktree execution_target",
            "EX-DENY-005",
        )
    if role in SITE_REVIEWER_ROLES:
        if token.startswith(OPENSHELL_PREFIX) or token == "cloud_subagent":
            return _deny(
                "reviewers do not follow the implementer into OpenShell or cloud_subagent",
                "EX-DENY-005",
            )
        if task_class == "independent_review" and token != "isolated_copy":
            return _deny(
                "independent_review requires execution_target isolated_copy",
                "EX-DENY-005",
            )
        if task_class == "design_review" and token != DEFAULT_EXECUTION_TARGET:
            return _deny(
                "design_review stays on the local corporate root (worktree)",
                "EX-DENY-005",
            )

    if token != DEFAULT_EXECUTION_TARGET and write_set_hits_corporate_root(
        packet, program_root=program_root
    ):
        return _deny(
            "non-worktree targets cannot write the corporate root",
            "EX-DENY-007",
        )
    return {
        "ok": True,
        "execution_target": token,
        "denial_code": None,
        "deny_id": None,
        "error": None,
    }


def execute_deny_probe(probe: dict[str, Any]) -> dict[str, Any]:
    """Run one deny-case probe. Name-presence without this hook is theater."""
    if not isinstance(probe, dict):
        return {"executed": True, "denied": True, "deny_id": None}
    kind = str(probe.get("kind") or "")
    deny_id = probe.get("deny_id")
    if kind == "site_path":
        path = probe.get("path")
        denied = False
        if path:
            try:
                assert_legal_site_path(str(path))
            except ContractError:
                denied = True
        return {"executed": True, "denied": denied, "deny_id": deny_id}
    packet = probe.get("packet")
    if not isinstance(packet, dict):
        packet = {}
    program_root = probe.get("program_root")
    result = validate_packet_execution_target(
        packet,
        program_root=Path(program_root) if program_root else None,
    )
    return {
        "executed": True,
        "denied": not result["ok"],
        "deny_id": result.get("deny_id") or deny_id,
        "error": result.get("error"),
    }


def load_and_execute_deny_case(path: Path) -> dict[str, Any]:
    body = json.loads(path.read_text(encoding="utf-8"))
    deny_id = str(body.get("id") or path.stem)
    expected = str(body.get("expected") or "deny")
    probe = dict(body.get("probe") or {})
    probe.setdefault("deny_id", deny_id)
    result = execute_deny_probe(probe)
    result["id"] = deny_id
    result["expected"] = expected
    result["finding"] = body.get("finding")
    return result


def _deny(error: str, deny_id: str) -> dict[str, Any]:
    return {
        "ok": False,
        "execution_target": None,
        "denial_code": DENIAL_EXECUTION_TARGET,
        "deny_id": deny_id,
        "error": error,
        "gate_evidence": False,
    }
