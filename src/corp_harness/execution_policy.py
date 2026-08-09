"""Premium model spend controls: route, attest, and deny outside allowlists."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from corp_harness.model import ContractError

POLICY_SCHEMA = "corporate-site-execution-policy/v1"
USAGE_SCHEMA = "corporate-site-premium-usage/v1"
ESCALATION_SCHEMA = "corporate-site-premium-escalation/v1"
PACKET_ATTEST_SCHEMA = "corporate-site-packet-model-attestation/v1"

DENIAL_PREMIUM_MODEL_POLICY = "PREMIUM_MODEL_POLICY"
DENIAL_EVIDENCE_STALE = "EVIDENCE_MAX_AGE_EXCEEDED"
DENIAL_BUDGET_HARD = "PREMIUM_BUDGET_HARD"

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
    "standard": [
        "composer-2.5",
        "composer-2",
        "grok-4.5",
        "cursor-grok-4.5-high-fast",
        "gpt-5.6-luna-medium",
        "gpt-5.6-terra-medium",
    ],
    "fast": [
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

KNOWN_POLICY_KEYS = frozenset(
    {
        "schema",
        "model_aliases",
        "task_class_defaults",
        "premium_allowlist",
        "budget",
        "evidence_max_age_seconds",
        "packet_limits",
        "role_defaults",
        "remediate_premium_after_failed_standard_attempts",
    }
)


def default_execution_policy() -> dict[str, Any]:
    return {
        "schema": POLICY_SCHEMA,
        "model_aliases": {key: list(value) for key, value in DEFAULT_MODEL_ALIASES.items()},
        "task_class_defaults": dict(DEFAULT_TASK_CLASS_DEFAULTS),
        "premium_allowlist": sorted(DEFAULT_PREMIUM_ALLOWLIST),
        "budget": {
            "premium_usd_soft": 500.0,
            "premium_usd_hard": 1500.0,
            "currency": "USD",
            "recorded_premium_usd": 0.0,
        },
        "evidence_max_age_seconds": 300,
        "packet_limits": dict(DEFAULT_PACKET_LIMITS),
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
        for key in ("premium_usd_soft", "premium_usd_hard", "recorded_premium_usd"):
            if key in budget:
                value = budget[key]
                if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                    raise ContractError(f"budget.{key} must be a non-negative number")
                policy["budget"][key] = float(value)
        if policy["budget"]["premium_usd_soft"] > policy["budget"]["premium_usd_hard"]:
            raise ContractError("budget.premium_usd_soft must be <= premium_usd_hard")
        currency = budget.get("currency", policy["budget"]["currency"])
        if not isinstance(currency, str) or not currency.strip():
            raise ContractError("budget.currency must be a nonempty string")
        policy["budget"]["currency"] = currency.strip()

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


def _escalation_valid(escalation: dict[str, Any] | None, task_class: str) -> bool:
    if not escalation:
        return False
    if escalation.get("schema") != ESCALATION_SCHEMA:
        return False
    if escalation.get("authorized") is not True:
        return False
    if escalation.get("task_class") not in {task_class, "hard_implement"}:
        return False
    if not escalation.get("reason"):
        return False
    return True


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

    role_key = role.strip()
    role_default = resolved["role_defaults"].get(role_key, "standard")
    task_default = resolved["task_class_defaults"][task_class]
    model_class = task_default
    requires_escalation = False
    reasons: list[str] = []

    if task_class == "packet_implement" and _packet_complexity(packet, resolved):
        model_class = "premium"
        requires_escalation = True
        reasons.append("packet_complexity_threshold")

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
        elif task_class == "packet_implement":
            model_class = "standard"
            requires_escalation = False
            reasons.append("complexity_without_escalation_downgraded")

    if max_mode and model_class == "premium" and not _escalation_valid(escalation, task_class):
        requires_escalation = True
        reasons.append("max_mode_requires_escalation")

    # Readonly roles never default to premium unless explicitly hard_implement + escalation.
    if role_default != "premium" and role_key != "site-specialist" and model_class == "premium":
        if task_class != "hard_implement" or not _escalation_valid(escalation, task_class):
            model_class = role_default
            requires_escalation = False
            reasons.append("role_forbids_premium_default")

    budget = resolved["budget"]
    budget_state = "ok"
    if budget["recorded_premium_usd"] >= budget["premium_usd_hard"]:
        budget_state = "hard"
        if model_class == "premium":
            model_class = "standard"
            requires_escalation = False
            reasons.append("budget_hard_downgrade")
    elif budget["recorded_premium_usd"] >= budget["premium_usd_soft"]:
        budget_state = "soft"
        reasons.append("budget_soft_warning")

    allowed_ids = list(resolved["model_aliases"].get(model_class, []))
    return {
        "ok": True,
        "role": role_key,
        "task_class": task_class,
        "model_class": model_class,
        "allowed_model_ids": allowed_ids,
        "requires_escalation": requires_escalation,
        "max_mode_allowed": model_class == "premium" and _escalation_valid(escalation, task_class),
        "budget": {
            "state": budget_state,
            "recorded_premium_usd": budget["recorded_premium_usd"],
            "premium_usd_soft": budget["premium_usd_soft"],
            "premium_usd_hard": budget["premium_usd_hard"],
            "currency": budget["currency"],
        },
        "reasons": reasons,
        "denial_code": None
        if budget_state != "hard" or task_class not in {"hard_implement"}
        else DENIAL_BUDGET_HARD,
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
    packet_ok = task_class == "packet_implement" and _escalation_valid(
        escalation, task_class
    )
    allowlisted_ok = task_class in allowlist and _escalation_valid(escalation, task_class)
    if not (hard_ok or remediate_ok or packet_ok or allowlisted_ok):
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

    if resolved["budget"]["recorded_premium_usd"] >= resolved["budget"]["premium_usd_hard"]:
        return {
            "ok": False,
            "denial_code": DENIAL_BUDGET_HARD,
            "error": "premium budget hard limit reached",
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
    if age > max_age:
        return {
            "ok": False,
            "denial_code": DENIAL_EVIDENCE_STALE,
            "age_seconds": age,
            "max_age_seconds": max_age,
        }
    return {
        "ok": True,
        "denial_code": None,
        "age_seconds": age,
        "max_age_seconds": max_age,
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
    if not isinstance(amount_usd, (int, float)) or isinstance(amount_usd, bool) or amount_usd < 0:
        raise ContractError("amount_usd must be a non-negative number")
    if not isinstance(source, str) or not source.strip():
        raise ContractError("source must be a nonempty string")
    root = program_root.expanduser().resolve()
    path = root / "premium-usage.json"
    if path.is_file():
        try:
            ledger = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContractError(f"cannot read premium-usage.json: {exc}") from exc
        if not isinstance(ledger, dict) or ledger.get("schema") != USAGE_SCHEMA:
            raise ContractError("unsupported premium-usage schema")
    else:
        ledger = {
            "schema": USAGE_SCHEMA,
            "currency": "USD",
            "total_premium_usd": 0.0,
            "entries": [],
        }
    entry = {
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "amount_usd": float(amount_usd),
        "source": source.strip(),
        "note": note,
        "actor": "user",
    }
    entries = list(ledger.get("entries") or [])
    entries.append(entry)
    total = float(ledger.get("total_premium_usd") or 0.0) + float(amount_usd)
    ledger = {
        "schema": USAGE_SCHEMA,
        "currency": "USD",
        "total_premium_usd": total,
        "entries": entries,
    }
    path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return ledger


def load_recorded_premium_usd(program_root: Path) -> float:
    path = program_root.expanduser().resolve() / "premium-usage.json"
    if not path.is_file():
        return 0.0
    try:
        ledger = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0.0
    if not isinstance(ledger, dict) or ledger.get("schema") != USAGE_SCHEMA:
        return 0.0
    total = ledger.get("total_premium_usd", 0.0)
    if isinstance(total, (int, float)) and not isinstance(total, bool):
        return float(total)
    return 0.0


def validate_packet_attestation(
    packet: dict[str, Any],
    *,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(packet, dict):
        raise ContractError("packet attestation must be an object")
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


def policy_status_summary(policy: dict[str, Any], recorded_premium_usd: float) -> dict[str, Any]:
    resolved = validate_execution_policy(policy)
    budget = dict(resolved["budget"])
    budget["recorded_premium_usd"] = recorded_premium_usd
    state = "ok"
    if recorded_premium_usd >= budget["premium_usd_hard"]:
        state = "hard"
    elif recorded_premium_usd >= budget["premium_usd_soft"]:
        state = "soft"
    return {
        "schema": resolved["schema"],
        "premium_allowlist": resolved["premium_allowlist"],
        "evidence_max_age_seconds": resolved["evidence_max_age_seconds"],
        "budget": {**budget, "state": state},
        "task_class_defaults": resolved["task_class_defaults"],
    }
