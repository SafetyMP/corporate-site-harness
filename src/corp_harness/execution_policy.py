"""Premium model spend controls: route, attest, and deny outside allowlists."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from corp_harness.model import ContractError
from corp_harness.runtime_engine import (
    build_halt_report,
    halt_unbind_or_weaken_approval,
)

POLICY_SCHEMA = "corporate-site-execution-policy/v1"
USAGE_SCHEMA = "corporate-site-premium-usage/v1"
ESCALATION_SCHEMA = "corporate-site-premium-escalation/v1"
PACKET_ATTEST_SCHEMA = "corporate-site-packet-model-attestation/v1"

DENIAL_PREMIUM_MODEL_POLICY = "PREMIUM_MODEL_POLICY"
DENIAL_EVIDENCE_STALE = "EVIDENCE_MAX_AGE_EXCEEDED"
DENIAL_SEALED_WORK_ORDER = "SEALED_WORK_ORDER_REQUIRED"
DENIAL_SUBCONTRACTOR_CEILING = "SUBCONTRACTOR_CEILING"
DENIAL_SAME_SESSION_REVIEWER = "REVIEWER_SAME_SESSION"
DENIAL_VOIDED_ACTOR = "VOIDED_ACTOR_NO_REHIRE"
DENIAL_REVIEWER_PROMPT = "REVIEWER_PROMPT_INVALID"
DENIAL_CHILD_PROSE_EVIDENCE = "CHILD_PROSE_NOT_EVIDENCE"

SEALED_WORK_ORDER_FIELDS = (
    "role",
    "packet_id",
    "root",
    "write_set",
    "routed_model",
    "success_schema",
    "halt_conditions",
)
GENERAL_PURPOSE_ROLES = frozenset({"generalPurpose", "general-purpose", "general_purpose"})
REVIEWER_ROLES = frozenset(
    {
        "operations-excellence",
        "corporate-adversary",
        "corporate-specialist",
        "ops-excellence",
        "adversary",
        "conformance",
    }
)
REVIEWER_TASK_CLASSES = frozenset({"independent_review", "design_review"})
PASS_CLAIM_MARKERS = (
    "they said it passed",
    "implementer json",
    "producer json",
    "child said pass",
    "child prose",
)

MODEL_CLASSES = frozenset({"premium", "standard", "fast"})
TASK_CLASSES = frozenset(
    {
        "design_review",
        "explore",
        "evidence_recapture",
        "dispatch_attest",
        "independent_review",
        "packet_implement",
        "hard_implement",
        "remediate",
    }
)

ROLE_DEFAULT_MODEL_CLASS = {
    "corporate-ceo": "standard",
    "corporate-coo": "standard",
    "corporate-specialist": "standard",
    "corporate-adversary": "standard",
    "operations-excellence": "fast",
    "site-manager": "fast",
    "site-specialist": "standard",
    "ceo": "standard",
    "coo": "standard",
}

# Prefer Grok for speed paths and Composer for standard/implement paths.
DEFAULT_TASK_CLASS_DEFAULTS = {
    "design_review": "fast",
    "explore": "fast",
    "evidence_recapture": "fast",
    "dispatch_attest": "fast",
    "independent_review": "fast",
    "packet_implement": "standard",
    "hard_implement": "premium",
    "remediate": "standard",
}

DEFAULT_PREMIUM_ALLOWLIST = frozenset({"hard_implement"})

DEFAULT_MODEL_ALIASES = {
    "sol": ["gpt-5.6-sol", "gpt-5.6-sol-max", "gpt-5.6-sol-max-fast"],
    "fable": [
        "claude-fable",
        "claude-4.6-fable",
        "claude-4.6-fable-medium",
        "claude-4.5-fable",
    ],
    "premium": [
        "gpt-5.6-sol",
        "gpt-5.6-sol-max",
        "gpt-5.6-sol-max-fast",
        "claude-fable",
        "claude-4.6-fable",
        "claude-4.6-fable-medium",
        "claude-4.5-fable",
    ],
    # First ID is the launch default (allowed_model_ids[0]).
    # Grok 4.6 is fast/standard only — never premium (Sol/Fable alone).
    "standard": [
        "composer-2.5",
        "composer-2",
        "cursor-grok-4.6-high-fast",
        "grok-4.6",
        "grok-4.5",
        "cursor-grok-4.5-high-fast",
        "gpt-5.6-luna-medium",
        "gpt-5.6-terra-medium",
    ],
    "fast": [
        "cursor-grok-4.6-high-fast",
        "grok-4.6",
        "cursor-grok-4.5-high-fast",
        "grok-4.5",
        "composer-2.5-fast",
        "composer-2.5",
    ],
}

DEFAULT_PACKET_LIMITS = {
    "max_changed_paths": 40,
    "max_acceptance_ids": 12,
    "max_adrs": 1,
    "complexity_path_threshold": 25,
    "complexity_acceptance_threshold": 8,
}

DEFAULT_SUBCONTRACTOR_CEILINGS = {
    "max_depth": 1,
    "max_children": 6,
    "no_redelegation": True,
}

KNOWN_POLICY_KEYS = frozenset(
    {
        "schema",
        "model_aliases",
        "task_class_defaults",
        "premium_allowlist",
        "budget",
        "evidence_max_age_seconds",
        "packet_limits",
        "subcontractor_ceilings",
        "role_defaults",
        "remediate_premium_after_failed_standard_attempts",
    }
)

# Escalation artifacts must not carry USD/invoice control fields (TPC-MODEL-001).
ESCALATION_FORBIDDEN_DOLLAR_KEYS = frozenset(
    {
        "premium_usd",
        "amount_usd",
        "invoice",
        "recorded_premium_usd",
        "premium_usd_soft",
        "premium_usd_hard",
        "total_premium_usd",
        "budget",
    }
)


def default_execution_policy() -> dict[str, Any]:
    return {
        "schema": POLICY_SCHEMA,
        "model_aliases": {key: list(value) for key, value in DEFAULT_MODEL_ALIASES.items()},
        "task_class_defaults": dict(DEFAULT_TASK_CLASS_DEFAULTS),
        "premium_allowlist": sorted(DEFAULT_PREMIUM_ALLOWLIST),
        # Budget USD hard-stops removed from control surface (TPC-CUT-002).
        "budget": {},
        "evidence_max_age_seconds": 300,
        "packet_limits": dict(DEFAULT_PACKET_LIMITS),
        "subcontractor_ceilings": dict(DEFAULT_SUBCONTRACTOR_CEILINGS),
        "role_defaults": dict(ROLE_DEFAULT_MODEL_CLASS),
        "remediate_premium_after_failed_standard_attempts": 2,
    }


def validate_execution_policy(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ContractError("execution_policy must be an object")
    unknown = sorted(set(raw) - KNOWN_POLICY_KEYS)
    if unknown:
        raise ContractError(f"execution_policy has unknown fields: {', '.join(unknown)}")
    schema = raw.get("schema", POLICY_SCHEMA)
    if schema != POLICY_SCHEMA:
        raise ContractError(f"unsupported execution_policy schema: {schema!r}")

    policy = default_execution_policy()
    if "model_aliases" in raw:
        aliases = raw["model_aliases"]
        if not isinstance(aliases, dict) or not aliases:
            raise ContractError("model_aliases must be a nonempty object")
        cleaned: dict[str, list[str]] = {}
        for key, values in aliases.items():
            if not isinstance(key, str) or not key.strip():
                raise ContractError("model_aliases keys must be nonempty strings")
            if not isinstance(values, list) or not values:
                raise ContractError(f"model_aliases[{key!r}] must be a nonempty list")
            ids: list[str] = []
            for item in values:
                if not isinstance(item, str) or not item.strip():
                    raise ContractError(f"model_aliases[{key!r}] entries must be nonempty strings")
                ids.append(item.strip())
            cleaned[key.strip()] = ids
        policy["model_aliases"] = cleaned

    if "task_class_defaults" in raw:
        defaults = raw["task_class_defaults"]
        if not isinstance(defaults, dict):
            raise ContractError("task_class_defaults must be an object")
        for task_class, model_class in defaults.items():
            if task_class not in TASK_CLASSES:
                raise ContractError(f"unknown task_class in defaults: {task_class!r}")
            if model_class not in MODEL_CLASSES:
                raise ContractError(f"unknown model_class in defaults: {model_class!r}")
            policy["task_class_defaults"][task_class] = model_class

    if "premium_allowlist" in raw:
        allow = raw["premium_allowlist"]
        if not isinstance(allow, list) or not allow:
            raise ContractError("premium_allowlist must be a nonempty list")
        cleaned_allow: list[str] = []
        for item in allow:
            if item not in TASK_CLASSES:
                raise ContractError(f"premium_allowlist contains unknown task_class: {item!r}")
            cleaned_allow.append(str(item))
        policy["premium_allowlist"] = sorted(set(cleaned_allow))

    if "budget" in raw:
        budget = raw["budget"]
        if not isinstance(budget, dict):
            raise ContractError("budget must be an object")
        # Accept legacy budget objects as non-gating telemetry only; USD hard/soft
        # keys are ignored for route/attest/check deny decisions.
        policy["budget"] = dict(budget)

    if "evidence_max_age_seconds" in raw:
        age = raw["evidence_max_age_seconds"]
        if not isinstance(age, int) or isinstance(age, bool) or age < 1:
            raise ContractError("evidence_max_age_seconds must be a positive integer")
        policy["evidence_max_age_seconds"] = age

    if "packet_limits" in raw:
        limits = raw["packet_limits"]
        if not isinstance(limits, dict):
            raise ContractError("packet_limits must be an object")
        for key, value in limits.items():
            if key not in DEFAULT_PACKET_LIMITS:
                raise ContractError(f"unknown packet_limits field: {key!r}")
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ContractError(f"packet_limits.{key} must be a positive integer")
            policy["packet_limits"][key] = value

    if "subcontractor_ceilings" in raw:
        ceilings = raw["subcontractor_ceilings"]
        if not isinstance(ceilings, dict):
            raise ContractError("subcontractor_ceilings must be an object")
        for key in ("max_depth", "max_children"):
            if key in ceilings:
                value = ceilings[key]
                if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                    raise ContractError(
                        f"subcontractor_ceilings.{key} must be a positive integer"
                    )
                policy["subcontractor_ceilings"][key] = value
        if "no_redelegation" in ceilings:
            flag = ceilings["no_redelegation"]
            if not isinstance(flag, bool):
                raise ContractError("subcontractor_ceilings.no_redelegation must be a boolean")
            policy["subcontractor_ceilings"]["no_redelegation"] = flag

    if "role_defaults" in raw:
        roles = raw["role_defaults"]
        if not isinstance(roles, dict):
            raise ContractError("role_defaults must be an object")
        for role, model_class in roles.items():
            if not isinstance(role, str) or not role.strip():
                raise ContractError("role_defaults keys must be nonempty strings")
            if model_class not in MODEL_CLASSES:
                raise ContractError(f"role_defaults[{role!r}] has unknown model_class")
            policy["role_defaults"][role.strip()] = model_class

    if "remediate_premium_after_failed_standard_attempts" in raw:
        attempts = raw["remediate_premium_after_failed_standard_attempts"]
        if not isinstance(attempts, int) or isinstance(attempts, bool) or attempts < 1:
            raise ContractError(
                "remediate_premium_after_failed_standard_attempts must be a positive integer"
            )
        policy["remediate_premium_after_failed_standard_attempts"] = attempts

    return policy


def classify_model_id(model_id: str, policy: dict[str, Any] | None = None) -> str:
    if not isinstance(model_id, str) or not model_id.strip():
        raise ContractError("model_id must be a nonempty string")
    resolved = (policy or default_execution_policy())["model_aliases"]
    needle = model_id.strip().lower()
    for model_class in ("premium", "fast", "standard"):
        for alias in resolved.get(model_class, []):
            if alias.lower() == needle:
                return model_class
    for family, ids in resolved.items():
        if family in MODEL_CLASSES:
            continue
        for alias in ids:
            if alias.lower() == needle:
                if family in {"sol", "fable"}:
                    return "premium"
                return "standard"
    if "sol" in needle or "fable" in needle:
        return "premium"
    if "grok" in needle or needle.endswith("-fast") or "composer-2.5-fast" in needle:
        return "fast"
    if "composer" in needle:
        return "standard"
    if "fast" in needle:
        return "fast"
    return "standard"


def _packet_complexity(packet: dict[str, Any] | None, policy: dict[str, Any]) -> bool:
    if not packet:
        return False
    limits = policy["packet_limits"]
    paths = packet.get("changed_paths") or packet.get("allowed_paths") or []
    acceptance = packet.get("acceptance_ids") or packet.get("case_ids") or []
    if isinstance(paths, list) and len(paths) >= limits["complexity_path_threshold"]:
        return True
    if isinstance(acceptance, list) and len(acceptance) >= limits[
        "complexity_acceptance_threshold"
    ]:
        return True
    return bool(packet.get("hard_implement") or packet.get("requires_premium"))


def _escalation_has_dollar_fields(escalation: dict[str, Any]) -> bool:
    for key in escalation:
        if key in ESCALATION_FORBIDDEN_DOLLAR_KEYS:
            return True
        if key == "currency" and str(escalation.get(key) or "").strip().upper() == "USD":
            return True
    return False


def _escalation_valid(escalation: dict[str, Any] | None, task_class: str) -> bool:
    if not escalation:
        return False
    if escalation.get("schema") != ESCALATION_SCHEMA:
        return False
    if escalation.get("authorized") is not True:
        return False
    if escalation.get("task_class") not in {task_class, "hard_implement"}:
        return False
    reason = escalation.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        return False
    esc_id = escalation.get("id")
    if not isinstance(esc_id, str) or not esc_id.strip():
        return False
    if _escalation_has_dollar_fields(escalation):
        return False
    return True


def sealed_work_order_issues(packet: dict[str, Any]) -> list[str]:
    """Return issues when a packet is missing unsigned/invalid work-order fields."""
    issues: list[str] = []
    if not isinstance(packet, dict):
        return ["packet must be an object"]
    for field in SEALED_WORK_ORDER_FIELDS:
        if field not in packet:
            issues.append(f"missing sealed work-order field {field}")
            continue
        value = packet[field]
        if field in {"write_set", "halt_conditions"}:
            if (
                not isinstance(value, list)
                or not value
                or not all(isinstance(item, str) and item.strip() for item in value)
            ):
                issues.append(
                    f"sealed work-order field {field} must be a nonempty list of strings"
                )
        elif not isinstance(value, str) or not value.strip():
            issues.append(f"sealed work-order field {field} must be a nonempty string")
    return issues


def is_general_purpose_packet(packet: dict[str, Any]) -> bool:
    role = str(packet.get("role") or packet.get("subagent_type") or "").strip()
    return role in GENERAL_PURPOSE_ROLES


def is_unsealed_general_purpose(packet: dict[str, Any]) -> bool:
    return is_general_purpose_packet(packet) and bool(sealed_work_order_issues(packet))


def collect_admissible_gate_packets(packets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Oracle/gate collectors skip unsealed generalPurpose, voided, and child prose."""
    admitted: list[dict[str, Any]] = []
    for packet in packets:
        if not isinstance(packet, dict):
            continue
        if is_unsealed_general_purpose(packet):
            continue
        if packet.get("void"):
            continue
        if packet.get("child_prose") and not packet.get("oracle_collect_digest"):
            continue
        admitted.append(packet)
    return admitted


def is_reviewer_packet(packet: dict[str, Any]) -> bool:
    role = str(packet.get("role") or packet.get("subagent_type") or "").strip()
    task_class = str(packet.get("task_class") or "").strip()
    return role in REVIEWER_ROLES or task_class in REVIEWER_TASK_CLASSES


def validate_reviewer_launch(
    packet: dict[str, Any],
    *,
    producer_session_id: str | None = None,
    producer_task_id: str | None = None,
) -> None:
    """Reviewers must launch as a NEW Task, not the implementer session."""
    if not is_reviewer_packet(packet):
        return
    task_id = packet.get("task_id") or packet.get("session_id")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ContractError("reviewer launch requires a fresh Task id")
    producer = (
        producer_session_id
        or producer_task_id
        or packet.get("producer_session_id")
        or packet.get("producer_task_id")
    )
    if producer and str(task_id) == str(producer):
        raise ContractError(
            "reviewer must launch as NEW Task; parent must not reuse implementer session"
        )


def validate_reviewer_prompt(
    prompt: str,
    *,
    packet_id: str,
    digests: dict[str, str],
    oracle_command: str,
) -> None:
    text = prompt.lower()
    for marker in PASS_CLAIM_MARKERS:
        if marker in text:
            raise ContractError(
                "reviewer prompt must not include implementer JSON or pass-claims"
            )
    if packet_id not in prompt:
        raise ContractError("reviewer prompt must include packet_id")
    for name, digest in digests.items():
        if digest not in prompt:
            raise ContractError(f"reviewer prompt must include {name} digest")
    if oracle_command not in prompt:
        raise ContractError("reviewer prompt must include oracle command")


def validate_reviewer_evidence(
    *,
    child_prose: str | None = None,
    oracle_collect_digest: str | None = None,
) -> None:
    if child_prose and not oracle_collect_digest:
        raise ContractError(
            "child prose is not gate evidence; oracle_collect digest required"
        )
    if not oracle_collect_digest:
        raise ContractError("reviewer packet invalid without oracle_collect digest")


def _subcontractor_ceiling_reasons(
    packet: dict[str, Any] | None, policy: dict[str, Any]
) -> list[str]:
    if not packet:
        return []
    ceilings = policy["subcontractor_ceilings"]
    reasons: list[str] = []
    depth = packet.get("depth", packet.get("subcontractor_depth"))
    children = packet.get("children", packet.get("child_count"))
    redelegating = bool(
        packet.get("redelegating") or packet.get("worker_redelegate")
    )
    if isinstance(depth, int) and not isinstance(depth, bool) and depth > ceilings["max_depth"]:
        reasons.append(f"depth {depth} exceeds max_depth {ceilings['max_depth']}")
    if (
        isinstance(children, int)
        and not isinstance(children, bool)
        and children > ceilings["max_children"]
    ):
        reasons.append(
            f"children {children} exceeds max_children {ceilings['max_children']}"
        )
    if ceilings["no_redelegation"] and redelegating:
        reasons.append("worker redelegation forbidden")
    return reasons


def route_model(
    *,
    role: str,
    task_class: str,
    policy: dict[str, Any] | None = None,
    packet: dict[str, Any] | None = None,
    escalation: dict[str, Any] | None = None,
    failed_standard_attempts: int = 0,
    max_mode: bool = False,
) -> dict[str, Any]:
    resolved = validate_execution_policy(policy or default_execution_policy())
    if task_class not in TASK_CLASSES:
        raise ContractError(f"unknown task_class: {task_class!r}")
    if not isinstance(role, str) or not role.strip():
        raise ContractError("role must be a nonempty string")
    if not isinstance(failed_standard_attempts, int) or failed_standard_attempts < 0:
        raise ContractError("failed_standard_attempts must be a non-negative integer")

    halt = halt_unbind_or_weaken_approval(packet or {})
    if halt is not None:
        return {
            "ok": False,
            "role": role.strip(),
            "task_class": task_class,
            "model_class": "standard",
            "allowed_model_ids": [],
            "requires_escalation": False,
            "max_mode_allowed": False,
            "verdict": "halt_report",
            "halt_report": halt,
            "reasons": [halt["reason"]],
            "denial_code": None,
        }

    # Voided-actor / no-rehire ledger is audit-only (TPC-CUT-006); not a route control.
    ceiling_reasons = _subcontractor_ceiling_reasons(packet, resolved)
    if ceiling_reasons:
        halt = build_halt_report(
            reason="; ".join(ceiling_reasons),
            protected_path="execution_policy",
        )
        return {
            "ok": False,
            "role": role.strip(),
            "task_class": task_class,
            "model_class": "standard",
            "allowed_model_ids": [],
            "requires_escalation": False,
            "max_mode_allowed": False,
            "verdict": "halt_report",
            "halt_report": halt,
            "reasons": ceiling_reasons,
            "denial_code": DENIAL_SUBCONTRACTOR_CEILING,
        }

    role_key = role.strip()
    role_default = resolved["role_defaults"].get(role_key, "standard")
    task_default = resolved["task_class_defaults"][task_class]
    model_class = task_default
    requires_escalation = False
    reasons: list[str] = []

    # Packet complexity must never auto-select Sol/Fable (TPC-MODEL-001).
    # Size/depth breaches may still hit subcontractor ceilings above.
    if task_class == "packet_implement" and _packet_complexity(packet, resolved):
        reasons.append("packet_complexity_noted_non_premium")

    if task_class == "hard_implement":
        model_class = "premium"
        requires_escalation = True
        reasons.append("hard_implement")

    if task_class == "remediate":
        threshold = resolved["remediate_premium_after_failed_standard_attempts"]
        if failed_standard_attempts >= threshold and _escalation_valid(escalation, task_class):
            model_class = "premium"
            requires_escalation = True
            reasons.append("remediate_after_failed_standard")
        else:
            model_class = "standard"
            reasons.append("remediate_standard_first")

    if model_class == "premium" and task_class not in set(resolved["premium_allowlist"]):
        if not (
            task_class == "remediate"
            and failed_standard_attempts
            >= resolved["remediate_premium_after_failed_standard_attempts"]
            and _escalation_valid(escalation, task_class)
        ):
            model_class = task_default if task_default != "premium" else "standard"
            requires_escalation = False
            reasons.append("premium_not_allowlisted")

    if model_class == "premium" and requires_escalation and not _escalation_valid(
        escalation, task_class
    ):
        if task_class == "hard_implement":
            # Still recommend premium, but mark escalation required before launch.
            reasons.append("escalation_required")

    if max_mode and model_class == "premium" and not _escalation_valid(escalation, task_class):
        requires_escalation = True
        reasons.append("max_mode_requires_escalation")

    # Readonly roles never default to premium unless explicitly hard_implement + escalation.
    if role_default != "premium" and role_key != "site-specialist" and model_class == "premium":
        if task_class != "hard_implement" or not _escalation_valid(escalation, task_class):
            model_class = role_default
            requires_escalation = False
            reasons.append("role_forbids_premium_default")

    allowed_ids = list(resolved["model_aliases"].get(model_class, []))
    return {
        "ok": True,
        "role": role_key,
        "task_class": task_class,
        "model_class": model_class,
        "allowed_model_ids": allowed_ids,
        "requires_escalation": requires_escalation,
        "max_mode_allowed": model_class == "premium" and _escalation_valid(escalation, task_class),
        "reasons": reasons,
        "denial_code": None,
    }


def attest_model_use(
    *,
    model_id: str,
    model_class: str,
    task_class: str,
    max_mode: bool = False,
    escalation: dict[str, Any] | None = None,
    failed_standard_attempts: int = 0,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved = validate_execution_policy(policy or default_execution_policy())
    if task_class not in TASK_CLASSES:
        raise ContractError(f"unknown task_class: {task_class!r}")
    if model_class not in MODEL_CLASSES:
        raise ContractError(f"unknown model_class: {model_class!r}")

    inferred = classify_model_id(model_id, resolved)
    if inferred != model_class and not (
        model_class == "premium" and inferred == "premium"
    ):
        # Allow declaring a stricter (cheaper) class than inferred only when not premium.
        if model_class == "premium" and inferred != "premium":
            return {
                "ok": False,
                "denial_code": DENIAL_PREMIUM_MODEL_POLICY,
                "error": (
                    f"model_id {model_id!r} is class {inferred!r}, "
                    f"cannot attest as premium"
                ),
            }
        if inferred == "premium" and model_class != "premium":
            return {
                "ok": False,
                "denial_code": DENIAL_PREMIUM_MODEL_POLICY,
                "error": (
                    f"model_id {model_id!r} is premium but attestation claims {model_class!r}"
                ),
            }

    effective_class = inferred if inferred == "premium" else model_class
    if effective_class != "premium":
        return {
            "ok": True,
            "denial_code": None,
            "model_id": model_id,
            "model_class": effective_class,
            "task_class": task_class,
            "max_mode": bool(max_mode),
        }

    allowlist = set(resolved["premium_allowlist"])
    remediate_ok = (
        task_class == "remediate"
        and failed_standard_attempts
        >= resolved["remediate_premium_after_failed_standard_attempts"]
        and _escalation_valid(escalation, task_class)
    )
    hard_ok = task_class == "hard_implement" and _escalation_valid(escalation, task_class)
    allowlisted_ok = task_class in allowlist and _escalation_valid(escalation, task_class)
    if not (hard_ok or remediate_ok or allowlisted_ok):
        return {
            "ok": False,
            "denial_code": DENIAL_PREMIUM_MODEL_POLICY,
            "error": (
                f"premium model {model_id!r} forbidden for task_class {task_class!r} "
                "without allowlist+escalation"
            ),
        }

    if max_mode and not _escalation_valid(escalation, task_class):
        return {
            "ok": False,
            "denial_code": DENIAL_PREMIUM_MODEL_POLICY,
            "error": "max_mode with premium requires a valid escalation artifact",
        }

    return {
        "ok": True,
        "denial_code": None,
        "model_id": model_id,
        "model_class": "premium",
        "task_class": task_class,
        "max_mode": bool(max_mode),
        "escalation_ref": escalation.get("id") if escalation else None,
    }


def check_evidence_age(
    captured_at: str,
    *,
    policy: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Report wall-clock age; never hard-deny on age alone (TPC-CUT-004).

    Currency is digest of the current artifact elsewhere; aged timestamps remain
    admissible when the caller is checking age alone.
    """
    resolved = validate_execution_policy(policy or default_execution_policy())
    try:
        stamp = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ContractError(f"invalid captured_at timestamp: {captured_at!r}") from exc
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    age = (current - stamp).total_seconds()
    max_age = resolved["evidence_max_age_seconds"]
    return {
        "ok": True,
        "denial_code": None,
        "age_seconds": age,
        "max_age_seconds": max_age,
        "aged": age > max_age,
    }


def extract_policy_from_handoff(handoff: dict[str, Any] | None) -> dict[str, Any] | None:
    if not handoff:
        return None
    if "execution_policy" in handoff:
        return validate_execution_policy(handoff["execution_policy"])
    ref = handoff.get("execution_policy_ref")
    if isinstance(ref, dict) and isinstance(ref.get("path"), str):
        path = Path(ref["path"]).expanduser()
        if path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8"))
            return validate_execution_policy(raw)
    return None


def load_policy_for_program(program_root: Path, program: Any) -> dict[str, Any]:
    """Load execution_policy from program field, handoff artifact, or defaults."""
    direct = getattr(program, "execution_policy", None)
    if isinstance(direct, dict) and direct:
        return validate_execution_policy(direct)
    artifacts = getattr(program, "artifacts", {}) or {}
    handoff = artifacts.get("corporate_handoff")
    if handoff is not None:
        path = Path(handoff.path)
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = None
            extracted = extract_policy_from_handoff(data if isinstance(data, dict) else None)
            if extracted is not None:
                return extracted
    policy_path = program_root.expanduser().resolve() / "execution-policy.json"
    if policy_path.is_file():
        return validate_execution_policy(json.loads(policy_path.read_text(encoding="utf-8")))
    return default_execution_policy()


def record_premium_usage(
    program_root: Path,
    *,
    amount_usd: float,
    source: str,
    note: str = "",
) -> dict[str, Any]:
    """Invoice ledger removed from harness control surface (TPC-CUT-002)."""
    del program_root, amount_usd, source, note
    raise ContractError(
        "premium usage invoice ledger removed from harness control surface "
        "(no USD budget hard-stop / premium-usage.json gate)"
    )


def load_recorded_premium_usd(program_root: Path) -> float:
    """Invoice ledger is non-control; always report zero for callers."""
    del program_root
    return 0.0


def _halt_report_payload(outcome: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(outcome, dict):
        return None
    if outcome.get("verdict") == "halt_report":
        return outcome
    nested = outcome.get("halt_report")
    if isinstance(nested, dict) and (
        nested.get("verdict") == "halt_report" or nested.get("halted") is True
    ):
        return nested
    return None


def validate_role_success_schema(
    success_schema: str | None,
    outcome: dict[str, Any],
) -> dict[str, Any]:
    """Accept ``halt_report`` as role success (TPC-HALT-003).

    ``success_schema`` may name other exits (pytest, etc.); a schema-valid
    halt_report is always a successful role outcome.
    """
    del success_schema  # halt_report is always accepted regardless of schema text
    halt = _halt_report_payload(outcome)
    if halt is not None and halt.get("ok", True) is not False:
        return {
            "ok": True,
            "accepted": True,
            "success": True,
            "terminal": True,
            "reason": "halt_report",
        }
    return {
        "ok": False,
        "accepted": False,
        "success": False,
        "terminal": False,
        "reason": "outcome is not an accepted halt_report success",
    }


def site_manager_after_packet_outcome(outcome: dict[str, Any]) -> dict[str, Any]:
    """Site-manager scheduling after a specialist/reviewer outcome (TPC-HALT-003).

    ``halt_report.halted=true`` is terminal: do not schedule a pass-forcing
    re-dispatch.
    """
    halt = _halt_report_payload(outcome)
    if halt is not None and halt.get("halted") is True:
        return {
            "terminal": True,
            "schedule_redispatch": False,
            "pass_forcing": False,
            "reason": "halt_report.halted",
        }
    return {
        "terminal": False,
        "schedule_redispatch": True,
        "pass_forcing": False,
        "reason": "non_halt_outcome",
    }


def validate_packet_attestation(
    packet: dict[str, Any],
    *,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(packet, dict):
        raise ContractError("packet attestation must be an object")
    if is_unsealed_general_purpose(packet):
        return {
            "ok": False,
            "denial_code": DENIAL_SEALED_WORK_ORDER,
            "error": "unsealed generalPurpose Task output is not gate evidence",
            "gate_evidence": False,
        }
    work_order_issues = sealed_work_order_issues(packet)
    if work_order_issues:
        raise ContractError("unsigned work order: " + "; ".join(work_order_issues))
    if is_reviewer_packet(packet):
        try:
            validate_reviewer_launch(packet)
        except ContractError as exc:
            return {
                "ok": False,
                "denial_code": DENIAL_SAME_SESSION_REVIEWER,
                "error": str(exc),
                "gate_evidence": False,
            }
        if packet.get("child_prose") and not packet.get("oracle_collect_digest"):
            return {
                "ok": False,
                "denial_code": DENIAL_CHILD_PROSE_EVIDENCE,
                "error": "child prose is not gate evidence; oracle_collect digest required",
                "gate_evidence": False,
            }
    model_id = packet.get("model_id")
    model_class = packet.get("model_class")
    task_class = packet.get("task_class")
    if not isinstance(model_id, str) or not isinstance(model_class, str) or not isinstance(
        task_class, str
    ):
        raise ContractError("packet requires model_id, model_class, and task_class")
    escalation = packet.get("escalation") or None
    if packet.get("escalation_ref") and escalation is None:
        escalation = {
            "schema": ESCALATION_SCHEMA,
            "authorized": True,
            "task_class": task_class,
            "reason": "escalation_ref_present",
            "id": packet.get("escalation_ref"),
        }
    return attest_model_use(
        model_id=model_id,
        model_class=model_class,
        task_class=task_class,
        max_mode=bool(packet.get("max_mode")),
        escalation=escalation if isinstance(escalation, dict) else None,
        failed_standard_attempts=int(packet.get("failed_standard_attempts") or 0),
        policy=policy,
    )


def policy_status_summary(
    policy: dict[str, Any], recorded_premium_usd: float = 0.0
) -> dict[str, Any]:
    """Status summary without USD hard/soft gate states (TPC-CUT-002)."""
    del recorded_premium_usd  # invoice spend is not a control plane input
    resolved = validate_execution_policy(policy)
    return {
        "schema": resolved["schema"],
        "premium_allowlist": resolved["premium_allowlist"],
        "evidence_max_age_seconds": resolved["evidence_max_age_seconds"],
        "task_class_defaults": resolved["task_class_defaults"],
    }
