"""Trust-routed runtime: sole emit+apply of TrustEvents and trust-state writer.

Python remains the sole writer of program.json, trust-state.json,
trust-event-log.jsonl, and trust-log-anchor.json.
Swift may propose TrustEvents but never apply them.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from corp_harness.contracts import ContractError
from corp_harness.model import Program, digest_path

TRUST_STATE_SCHEMA = "corporate-site-trust-state/v1"
TRUST_EVENT_SCHEMA = "corporate-site-trust-event/v1"
TRUST_CONSEQUENCE_SCHEMA = "corporate-site-trust-consequence/v1"
TRUST_LOG_ENTRY_SCHEMA = "corporate-site-trust-log-entry/v1"
TRUST_LOG_ANCHOR_SCHEMA = "corporate-site-trust-log-anchor/v1"
MUTATION_PERMIT_SCHEMA = "corporate-site-trust-mutation-permit/v1"
SURFACE_BASELINE_SCHEMA = "corporate-site-trust-surface-baseline/v1"
SOLE_EMITTER = "python_runtime_engine"
SWIFT_PROPOSE_ONLY = "swift_propose_only"

LIGHT_THRESHOLD = Decimal("0.70")
JUST_BELOW_LIGHT = Decimal("0.69")
SUCCESS_DELTA = Decimal("0.05")
QUANTIZE = Decimal("0.01")
GENESIS_PREV_HASH = "genesis"
COARSE_TIME_BUCKET_SECONDS = 300
MAX_PERMIT_TTL_SECONDS = 120
PROGRAM_ROOT_ENV = "CORP_HARNESS_PROGRAM_ROOT"
PROGRAM_ROOT_MARKER = ".corp-harness-program-root"
REQUIRED_CURSOR_HOOK_EVENTS = frozenset({"afterFileEdit", "beforeShellExecution"})
REQUIRED_HOOK_SCRIPT = ".cursor/hooks/trust_report.py"
FACTORY_HOOKS_JSON = ".cursor/hooks.json"

TRUST_EVENT_KINDS = frozenset(
    {"strict_success", "validation_failure", "deceptive_theater"}
)
LOG_ENTRY_KINDS = frozenset({"trust_event", "digest_rebind"})
# Pre-r3 writer emitted digest_amnesty during ADR-TR-001 score-reset amnesty.
# Verify-only grandfather: historical lines may remain in the chain; append
# writers must never mint new digest_amnesty (superseded by digest_rebind).
LEGACY_LOG_ENTRY_KINDS = frozenset({"digest_amnesty"})
VERIFY_LOG_ENTRY_KINDS = LOG_ENTRY_KINDS | LEGACY_LOG_ENTRY_KINDS
THEATER_SIGNAL_IDS = frozenset(
    {
        "vacuous_gate_pass",
        "unbound_kpi",
        "seal_bypass_attempt",
        "out_of_band_mutation",
        "unauthorized_actor",
        "stale_factory_authorization",
        "wrong_root_operation",
    }
)
# Anti-harness subset always maps to deceptive_theater → 0.0 (ADR-TR-003).
ANTI_HARNESS_THEATER_IDS = frozenset(
    {
        "out_of_band_mutation",
        "unauthorized_actor",
        "stale_factory_authorization",
        "wrong_root_operation",
        "seal_bypass_attempt",
    }
)
CORPORATE_PROTECTED_FILES = frozenset(
    {
        "program.json",
        "trust-state.json",
        "trust-event-log.jsonl",
        "trust-mutation-permit.json",
        "trust-log-anchor.json",
        "trust-surface-baseline.json",
        "master-spec.md",
        "acceptance.json",
        "gates.json",
        "kpis.json",
        "corporate-handoff.json",
        "factory-authorization.json",
        "user-approval.json",
        "final-dossier.md",
    }
)
FACTORY_D8_PREFIXES = (
    "src/corp_harness/",
    "swift/",
    "tests/",
    "docs/adr/",
    "scripts/harness/",
    "corporate/plugin/corporate-site-harness/",
)
FACTORY_D8_FILES = frozenset(
    {"pyproject.toml", "AGENTS.md", ".corp-harness-program-root"}
)

ALWAYS_FORCE_HEAVY_ACTIONS = frozenset(
    {
        "record_artifact:gates",
        "record_artifact:kpis",
        "record_artifact:corporate_handoff",
        "record_artifact:factory_authorization",
        "record_artifact:user_approval",
        "mint_gov_receipt",
    }
)
HEAVY_VALIDATE_ACTION = "heavy_validate"
FG001_SEAL_ALIAS = "fg001_seal"

# Trust-gated CLI always-on set (ADR-TR-003 / ACC-TR-AH-017).
TRUST_GATED_CLI_SURFACES = frozenset(
    {
        "record",
        "next",
        "check_apply",
        "gov_validate_action",
        "gov_write_receipt",
        "trust_report_event",
        "archive",
        "install",
        "rollback",
        "usage_record",
        "status",
    }
)

GOV_REQUIRED = "GOV_REQUIRED"


def quantize_score(raw: Decimal | float | str) -> Decimal:
    value = Decimal(str(raw))
    if value < 0:
        value = Decimal("0")
    if value > 1:
        value = Decimal("1")
    return value.quantize(QUANTIZE, rounding=ROUND_HALF_UP)


def execution_layer_for_score(score: Decimal) -> str:
    return "light" if quantize_score(score) >= LIGHT_THRESHOLD else "heavy"


def apply_kind(score: Decimal, kind: str) -> Decimal:
    current = quantize_score(score)
    if kind == "strict_success":
        return quantize_score(min(Decimal("1.0"), current + SUCCESS_DELTA))
    if kind == "validation_failure":
        return quantize_score(min(current, JUST_BELOW_LIGHT))
    if kind == "deceptive_theater":
        return Decimal("0.00")
    raise ContractError(f"unknown TrustEvent kind: {kind!r}")


def expand_action(action: str) -> str:
    if action == FG001_SEAL_ALIAS:
        raise ContractError("fg001_seal is an alias set, not a single action")
    return action


def action_routed_layer(score: Decimal, action: str) -> str:
    action = expand_action(action) if action != FG001_SEAL_ALIAS else action
    if action in ALWAYS_FORCE_HEAVY_ACTIONS or action == HEAVY_VALIDATE_ACTION:
        return "heavy"
    if execution_layer_for_score(score) == "heavy":
        return "heavy"
    return "light"


def is_always_force_heavy(action: str) -> bool:
    return action in ALWAYS_FORCE_HEAVY_ACTIONS


@dataclass
class TrustState:
    trust_score: Decimal
    execution_layer: str
    program_digest: str
    last_event: dict[str, Any] | None
    updated_at: str
    log_tip_hash: str | None = None
    log_seq: int = 0
    generation: int = 0
    pending_rebind_from: str | None = field(default=None, repr=False, compare=False)
    false_genesis: bool = field(default=False, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": TRUST_STATE_SCHEMA,
            "trust_score": float(self.trust_score),
            "execution_layer": self.execution_layer,
            "program_digest": self.program_digest,
            "last_event": self.last_event,
            "updated_at": self.updated_at,
            "generation": self.generation,
        }
        if self.log_tip_hash is not None:
            payload["log_tip_hash"] = self.log_tip_hash
        if self.log_seq:
            payload["log_seq"] = self.log_seq
        return payload

    def status_fields(self) -> dict[str, Any]:
        kind = None
        if isinstance(self.last_event, dict):
            kind = self.last_event.get("kind")
        return {
            "trust_score": float(self.trust_score),
            "execution_layer": self.execution_layer,
            "last_event": {"kind": kind} if kind else None,
        }


def trust_state_path(program_root: Path) -> Path:
    return program_root.expanduser().resolve() / "trust-state.json"


def trust_event_log_path(program_root: Path) -> Path:
    return program_root.expanduser().resolve() / "trust-event-log.jsonl"


def trust_log_anchor_path(program_root: Path) -> Path:
    return program_root.expanduser().resolve() / "trust-log-anchor.json"


def mutation_permit_path(program_root: Path) -> Path:
    return program_root.expanduser().resolve() / "trust-mutation-permit.json"


def surface_baseline_path(program_root: Path) -> Path:
    return program_root.expanduser().resolve() / "trust-surface-baseline.json"


def synthesize_trust_state(program_digest: str) -> TrustState:
    return TrustState(
        trust_score=Decimal("1.00"),
        execution_layer="light",
        program_digest=program_digest,
        last_event=None,
        updated_at=_now(),
    )


def _log_is_nonempty(program_root: Path) -> bool:
    path = trust_event_log_path(program_root)
    if not path.is_file():
        return False
    return any(line.strip() for line in path.read_text(encoding="utf-8").splitlines())


def _anchor_exists(program_root: Path) -> bool:
    return trust_log_anchor_path(program_root).is_file()


def is_true_genesis(program_root: Path) -> bool:
    """True genesis only when state, non-empty log, and anchor are all absent."""
    root = program_root.expanduser().resolve()
    return (
        not trust_state_path(root).is_file()
        and not _log_is_nonempty(root)
        and not _anchor_exists(root)
    )


def load_trust_state(program_root: Path, *, program_json: Path | None = None) -> TrustState:
    """Load trust-state; D3 digest mismatch rebinds digest and preserves score.

    Rebind is load-visible for routing but does not append the audit log or
    persist until a writer path (`emit_and_apply`) runs. Clean status alone
    must not append `digest_rebind`.

    Post-log / post-anchor state deletion must not synthesize 1.0/light
    (false genesis → fail-closed 0.0 heavy until report-event applies).
    """
    root = program_root.expanduser().resolve()
    program_path = (program_json or (root / "program.json")).expanduser().resolve()
    current_digest = digest_path(program_path)
    path = trust_state_path(root)
    if not path.is_file():
        if _anchor_exists(root) or _log_is_nonempty(root):
            return TrustState(
                trust_score=Decimal("0.00"),
                execution_layer="heavy",
                program_digest=current_digest,
                last_event=None,
                updated_at=_now(),
                false_genesis=True,
            )
        return synthesize_trust_state(current_digest)

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ContractError("trust-state.json must be an object")
    stored_digest = str(raw.get("program_digest") or "")
    score = quantize_score(raw.get("trust_score", 1.0))
    stored_layer = raw.get("execution_layer")
    if stored_layer in {"light", "heavy"}:
        layer = str(stored_layer)
    else:
        layer = execution_layer_for_score(score)
    last_event = raw.get("last_event")
    if last_event is not None and not isinstance(last_event, dict):
        raise ContractError("trust-state.last_event must be object or null")
    tip = raw.get("log_tip_hash")
    seq_raw = raw.get("log_seq", 0)
    try:
        log_seq = int(seq_raw or 0)
    except (TypeError, ValueError) as exc:
        raise ContractError("trust-state.log_seq must be an integer") from exc
    try:
        generation = int(raw.get("generation", 0) or 0)
    except (TypeError, ValueError) as exc:
        raise ContractError("trust-state.generation must be an integer") from exc
    if generation < 0:
        raise ContractError("trust-state.generation is invalid")
    pending: str | None = None
    digest = current_digest
    if stored_digest and stored_digest != current_digest:
        # D3 rebind-preserve (supersedes digest amnesty score-reset).
        pending = stored_digest
        digest = current_digest
    return TrustState(
        trust_score=score,
        execution_layer=layer,
        program_digest=digest,
        last_event=last_event,
        updated_at=str(raw.get("updated_at") or _now()),
        log_tip_hash=str(tip) if tip else None,
        log_seq=log_seq,
        generation=generation,
        pending_rebind_from=pending,
    )


def save_trust_state(program_root: Path, state: TrustState) -> None:
    """Sole writer for trust-state.json with flock + generation lost-update reject."""
    root = program_root.expanduser().resolve()
    path = trust_state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        current_generation = 0
        if path.exists():
            try:
                current = json.loads(path.read_text(encoding="utf-8"))
                current_generation = int(current.get("generation", 0) or 0)
            except (
                AttributeError,
                OSError,
                TypeError,
                ValueError,
                json.JSONDecodeError,
            ) as exc:
                raise ContractError(
                    f"cannot compare trust-state generation: {exc}"
                ) from exc
        if current_generation != state.generation:
            raise ContractError(
                "trust-state changed concurrently; reload before recording new state"
            )
        next_generation = state.generation + 1
        payload = state.to_dict()
        payload["generation"] = next_generation
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                delete=False,
            ) as temporary:
                temporary_name = temporary.name
                json.dump(payload, temporary, indent=2, sort_keys=True)
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, path)
            state.generation = next_generation
        finally:
            if temporary_name and Path(temporary_name).exists():
                Path(temporary_name).unlink()


def validate_event_preconditions(
    kind: str,
    *,
    theater_signal_id: str | None,
    reasons: list[str],
) -> None:
    if kind not in TRUST_EVENT_KINDS:
        raise ContractError(f"unknown TrustEvent kind: {kind!r}")
    if kind == "deceptive_theater":
        if theater_signal_id not in THEATER_SIGNAL_IDS:
            raise ContractError(
                "deceptive_theater requires theater_signal_id in "
                f"{sorted(THEATER_SIGNAL_IDS)}"
            )
        if not reasons:
            raise ContractError("deceptive_theater requires reasons")
    if kind == "validation_failure":
        if not reasons:
            raise ContractError("validation_failure requires reasons")
        if theater_signal_id in THEATER_SIGNAL_IDS:
            raise ContractError(
                "validation_failure must not use theater_signal_id "
                f"(reserved for deceptive_theater): {theater_signal_id!r}"
            )


def build_trust_event(
    *,
    kind: str,
    program_digest: str,
    score_before: Decimal,
    score_after: Decimal,
    reasons: list[str] | None = None,
    theater_signal_id: str | None = None,
    event_id: str | None = None,
    emitter: str = SOLE_EMITTER,
) -> dict[str, Any]:
    reasons = list(reasons or [])
    validate_event_preconditions(
        kind, theater_signal_id=theater_signal_id, reasons=reasons
    )
    if emitter not in {SOLE_EMITTER, SWIFT_PROPOSE_ONLY}:
        raise ContractError(f"unsupported TrustEvent emitter: {emitter!r}")
    return {
        "schema": TRUST_EVENT_SCHEMA,
        "event_id": event_id or str(uuid.uuid4()),
        "kind": kind,
        "program_digest": program_digest,
        "emitter": emitter,
        "theater_signal_id": theater_signal_id,
        "reasons": reasons,
        "score_before": float(quantize_score(score_before)),
        "score_after": float(quantize_score(score_after)),
    }


def compute_dedup_fingerprint(
    *,
    theater_signal_id: str | None,
    protected_path: str | None,
    content_hash: str | None,
    at: datetime | None = None,
) -> str:
    """Dedup fingerprint: theater_signal_id + protected path + content hash + time bucket."""
    moment = at or datetime.now(timezone.utc)
    bucket = int(moment.timestamp()) // COARSE_TIME_BUCKET_SECONDS
    material = "\0".join(
        [
            theater_signal_id or "",
            protected_path or "",
            content_hash or "",
            str(bucket),
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def content_hash_for_event(
    *,
    kind: str,
    reasons: list[str] | None,
    theater_signal_id: str | None,
) -> str:
    body = {
        "kind": kind,
        "reasons": list(reasons or []),
        "theater_signal_id": theater_signal_id,
    }
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def canonical_log_entry_hash(entry_without_hash: dict[str, Any]) -> str:
    """Hash chain body: sha256 of canonical JSON excluding entry_hash itself."""
    return hashlib.sha256(
        json.dumps(entry_without_hash, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def legacy_log_entry_hash(entry_without_hash: dict[str, Any]) -> str:
    """Pre-r3 hash: sha256(prev_hash + newline + canonical JSON body).

    Historical corporate logs (digest_amnesty era) used this formula. Verify
    accepts either algorithm; new appends use canonical_log_entry_hash only.
    """
    prev = str(entry_without_hash.get("prev_hash") or GENESIS_PREV_HASH)
    canonical = json.dumps(
        entry_without_hash, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(f"{prev}\n{canonical}".encode("utf-8")).hexdigest()


def entry_hash_matches(entry: dict[str, Any]) -> bool:
    """True if entry_hash matches current or legacy compute."""
    body = {key: value for key, value in entry.items() if key != "entry_hash"}
    stored = entry.get("entry_hash")
    return stored in {
        canonical_log_entry_hash(body),
        legacy_log_entry_hash(body),
    }


def read_trust_log_entries(program_root: Path) -> list[dict[str, Any]]:
    path = trust_event_log_path(program_root)
    if not path.is_file():
        return []
    entries: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ContractError(
                f"trust-event-log.jsonl line {line_no} is not valid JSON"
            ) from exc
        if not isinstance(raw, dict):
            raise ContractError(f"trust-event-log.jsonl line {line_no} must be an object")
        entries.append(raw)
    return entries


def find_trust_event_log_entry(
    program_root: Path, event_id: str
) -> dict[str, Any] | None:
    for entry in read_trust_log_entries(program_root):
        if entry.get("entry_kind") != "trust_event":
            continue
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            continue
        event = payload.get("event")
        if isinstance(event, dict) and event.get("event_id") == event_id:
            return entry
    return None


def verify_log_chain(program_root: Path) -> dict[str, Any]:
    """Recompute hash chain. Empty/missing log is an honest genesis tip."""
    try:
        entries = read_trust_log_entries(program_root)
    except ContractError as exc:
        return {
            "ok": False,
            "chain_ok": False,
            "reason": str(exc),
            "entries": [],
            "tip_hash": None,
            "tip_seq": 0,
        }
    expected_prev = GENESIS_PREV_HASH
    for index, entry in enumerate(entries, start=1):
        if entry.get("schema") != TRUST_LOG_ENTRY_SCHEMA:
            return {
                "ok": False,
                "chain_ok": False,
                "reason": f"seq={entry.get('seq')}: bad schema",
                "entries": entries,
                "tip_hash": None,
                "tip_seq": 0,
            }
        if entry.get("entry_kind") not in VERIFY_LOG_ENTRY_KINDS:
            return {
                "ok": False,
                "chain_ok": False,
                "reason": f"seq={entry.get('seq')}: bad entry_kind",
                "entries": entries,
                "tip_hash": None,
                "tip_seq": 0,
            }
        if int(entry.get("seq") or 0) != index:
            return {
                "ok": False,
                "chain_ok": False,
                "reason": f"expected seq {index}, got {entry.get('seq')}",
                "entries": entries,
                "tip_hash": None,
                "tip_seq": 0,
            }
        if entry.get("prev_hash") != expected_prev:
            return {
                "ok": False,
                "chain_ok": False,
                "reason": f"seq={entry.get('seq')}: prev_hash mismatch",
                "entries": entries,
                "tip_hash": None,
                "tip_seq": 0,
            }
        if not entry_hash_matches(entry):
            return {
                "ok": False,
                "chain_ok": False,
                "reason": f"seq={entry.get('seq')}: entry_hash mismatch",
                "entries": entries,
                "tip_hash": None,
                "tip_seq": 0,
            }
        expected_prev = str(entry["entry_hash"])
    return {
        "ok": True,
        "chain_ok": True,
        "reason": None,
        "entries": entries,
        "tip_hash": expected_prev if entries else GENESIS_PREV_HASH,
        "tip_seq": len(entries),
    }


def read_trust_log(
    program_root: Path,
    *,
    limit: int | None = None,
    verify_chain: bool = False,
) -> dict[str, Any]:
    """Read-only trust log view. Never appends or mutates trust-state."""
    path = trust_event_log_path(program_root)
    if verify_chain:
        result = verify_log_chain(program_root)
    else:
        try:
            entries = read_trust_log_entries(program_root)
        except ContractError as exc:
            return {
                "ok": False,
                "path": str(path),
                "entries": [],
                "chain_ok": None,
                "reason": str(exc),
            }
        result = {
            "ok": True,
            "chain_ok": None,
            "reason": None,
            "entries": entries,
        }
    entries = list(result["entries"])
    if limit is not None:
        if limit < 0:
            raise ContractError("--limit must be >= 0")
        entries = entries[-limit:] if limit else []
    return {
        "ok": bool(result["ok"]),
        "path": str(path),
        "entries": entries,
        "chain_ok": result.get("chain_ok"),
        "reason": result.get("reason"),
    }


def require_verifiable_trust_log(program_root: Path) -> None:
    """Fail closed when the JSONL chain is broken or unverifiable."""
    result = verify_log_chain(program_root)
    if result.get("ok") and result.get("chain_ok"):
        return
    reason = result.get("reason") or "unverifiable trust-event-log chain"
    raise ContractError(f"{GOV_REQUIRED}: broken trust log chain: {reason}")


def append_trust_log_entry(
    program_root: Path,
    *,
    entry_kind: str,
    program_digest: str,
    payload: dict[str, Any],
    program_id: str | None = None,
) -> dict[str, Any]:
    """Sole append writer for trust-event-log.jsonl. Mints anchor on first append."""
    if entry_kind not in LOG_ENTRY_KINDS:
        raise ContractError(f"unknown trust log entry_kind: {entry_kind!r}")
    root = program_root.expanduser().resolve()
    existing = read_trust_log_entries(root)
    if existing:
        prev_hash = str(existing[-1].get("entry_hash") or "")
        if not prev_hash:
            raise ContractError("trust-event-log tip missing entry_hash")
        seq = int(existing[-1].get("seq") or len(existing)) + 1
    else:
        prev_hash = GENESIS_PREV_HASH
        seq = 1
    recorded_at = _now()
    body: dict[str, Any] = {
        "schema": TRUST_LOG_ENTRY_SCHEMA,
        "seq": seq,
        "entry_kind": entry_kind,
        "prev_hash": prev_hash,
        "program_digest": program_digest,
        "recorded_at": recorded_at,
        "payload": payload,
    }
    entry_hash = canonical_log_entry_hash(body)
    entry = {**body, "entry_hash": entry_hash}
    log_path = trust_event_log_path(root)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n")
    if seq == 1:
        _mint_trust_log_anchor(
            root,
            program_id=program_id or _program_id(root),
            first_entry_hash=entry_hash,
            initialized_at=recorded_at,
        )
    return entry


def _mint_trust_log_anchor(
    program_root: Path,
    *,
    program_id: str,
    first_entry_hash: str,
    initialized_at: str,
) -> None:
    path = trust_log_anchor_path(program_root)
    if path.is_file():
        return
    anchor = {
        "schema": TRUST_LOG_ANCHOR_SCHEMA,
        "program_id": program_id,
        "initialized_at": initialized_at,
        "first_entry_hash": first_entry_hash,
        "writer": SOLE_EMITTER,
    }
    path.write_text(json.dumps(anchor, indent=2) + "\n", encoding="utf-8")


def _program_id(program_root: Path) -> str:
    path = program_root.expanduser().resolve() / "program.json"
    if not path.is_file():
        return "unknown"
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and raw.get("program_id"):
        return str(raw["program_id"])
    return "unknown"


def emit_and_apply(
    program_root: Path,
    *,
    kind: str,
    program_digest: str,
    reasons: list[str] | None = None,
    theater_signal_id: str | None = None,
    event_id: str | None = None,
    proposed_by_swift: dict[str, Any] | None = None,
    protected_path: str | None = None,
    content_hash: str | None = None,
) -> TrustState:
    """Sole emit+apply path. Swift proposals are accepted only as input drafts.

    Appends digest_rebind (when D3 pending) then exactly one trust_event line for
    each newly applied event. Duplicate event_id with matching dedup fingerprint
    is a no-op; fingerprint mismatch requires a new event_id.

    Broken/unverifiable hash chains fail closed before any append or score mutate.
    """
    root = program_root.expanduser().resolve()
    require_verifiable_trust_log(root)
    state = load_trust_state(root)
    if proposed_by_swift is not None:
        if proposed_by_swift.get("emitter") not in {None, SWIFT_PROPOSE_ONLY}:
            raise ContractError("Swift may only propose with emitter swift_propose_only")
        kind = str(proposed_by_swift.get("kind") or kind)
        theater_signal_id = proposed_by_swift.get("theater_signal_id", theater_signal_id)
        reasons = list(proposed_by_swift.get("reasons") or reasons or [])
        event_id = proposed_by_swift.get("event_id") or event_id
        if proposed_by_swift.get("protected_path") is not None:
            protected_path = str(proposed_by_swift.get("protected_path"))
        if proposed_by_swift.get("content_hash") is not None:
            content_hash = str(proposed_by_swift.get("content_hash"))

    resolved_content_hash = content_hash or content_hash_for_event(
        kind=kind, reasons=reasons, theater_signal_id=theater_signal_id
    )
    fingerprint = compute_dedup_fingerprint(
        theater_signal_id=theater_signal_id,
        protected_path=protected_path,
        content_hash=resolved_content_hash,
    )

    if event_id:
        prior = find_trust_event_log_entry(root, event_id)
        if prior is not None:
            prior_payload = (
                prior.get("payload") if isinstance(prior.get("payload"), dict) else {}
            )
            prior_fp = None
            if isinstance(prior_payload, dict):
                prior_fp = prior_payload.get("dedup_fingerprint")
            if prior_fp is None and isinstance(state.last_event, dict):
                prior_fp = state.last_event.get("dedup_fingerprint")
            if prior_fp == fingerprint:
                return state
            raise ContractError(
                "fingerprint mismatch requires a new event_id "
                f"(event_id={event_id!r})"
            )
        if (
            isinstance(state.last_event, dict)
            and state.last_event.get("event_id") == event_id
        ):
            prior_fp = state.last_event.get("dedup_fingerprint")
            if prior_fp == fingerprint or prior_fp is None:
                # Matching (or legacy last_event without fingerprint) → no-op.
                return state
            raise ContractError(
                "fingerprint mismatch requires a new event_id "
                f"(event_id={event_id!r})"
            )

    before = state.trust_score
    after = apply_kind(before, kind)
    event = build_trust_event(
        kind=kind,
        program_digest=program_digest,
        score_before=before,
        score_after=after,
        reasons=reasons,
        theater_signal_id=theater_signal_id,
        event_id=event_id,
        emitter=SOLE_EMITTER,
    )
    event["dedup_fingerprint"] = fingerprint

    tip_hash = state.log_tip_hash
    tip_seq = state.log_seq
    if state.pending_rebind_from:
        rebind_entry = append_trust_log_entry(
            root,
            entry_kind="digest_rebind",
            program_digest=program_digest,
            payload={
                "stored_digest": state.pending_rebind_from,
                "current_digest": program_digest,
                "trust_score": float(before),
                "execution_layer": state.execution_layer,
                "last_event_kind": (
                    state.last_event.get("kind")
                    if isinstance(state.last_event, dict)
                    else None
                ),
            },
        )
        tip_hash = str(rebind_entry["entry_hash"])
        tip_seq = int(rebind_entry["seq"])

    log_entry = append_trust_log_entry(
        root,
        entry_kind="trust_event",
        program_digest=program_digest,
        payload={
            "event": event,
            "execution_layer": execution_layer_for_score(after),
            "trust_score": float(after),
            "dedup_fingerprint": fingerprint,
            "protected_path": protected_path,
            "content_hash": resolved_content_hash,
        },
    )
    tip_hash = str(log_entry["entry_hash"])
    tip_seq = int(log_entry["seq"])

    new_state = TrustState(
        trust_score=after,
        execution_layer=execution_layer_for_score(after),
        program_digest=program_digest,
        last_event=event,
        updated_at=_now(),
        log_tip_hash=tip_hash,
        log_seq=tip_seq,
        generation=state.generation,
    )
    save_trust_state(root, new_state)
    _sync_baseline_after_trust_write(root)
    return new_state


def attach_trust_status(
    result: dict[str, Any],
    program_root: Path,
    *,
    mutate: bool = False,
) -> dict[str, Any]:
    """Attach trust fields for status/apply responses. Never mutates when mutate=False."""
    del mutate  # explicit: load-only for display
    state = load_trust_state(program_root)
    result = dict(result)
    result.update(state.status_fields())
    return result


def route_for_action(program_root: Path, action: str) -> dict[str, Any]:
    state = load_trust_state(program_root)
    layer = action_routed_layer(state.trust_score, action)
    return {
        "schema": TRUST_CONSEQUENCE_SCHEMA,
        "trust_score": float(state.trust_score),
        "execution_layer": state.execution_layer,
        "action": action,
        "action_routed_layer": layer,
        "always_force_heavy": is_always_force_heavy(action),
    }


def require_heavy_available(
    *,
    action_routed_layer_value: str,
    swift_available: bool,
) -> str | None:
    """Return error code when heavy path cannot run; None when ok or light soft-fail."""
    if action_routed_layer_value == "heavy" and not swift_available:
        return GOV_REQUIRED
    return None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _format_utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def factory_checkout_root() -> Path:
    """Return the factory checkout that owns this package (…/src/corp_harness)."""
    return Path(__file__).resolve().parents[2]


def bind_program_root(
    factory_root: Path,
    program_root: Path,
    *,
    seed_baseline: bool = True,
) -> Path:
    """Write factory→corporate program-root binding marker."""
    factory = factory_root.expanduser().resolve()
    corporate = program_root.expanduser().resolve()
    if not (corporate / "program.json").is_file():
        raise ContractError(f"program does not exist: {corporate / 'program.json'}")
    marker = factory / PROGRAM_ROOT_MARKER
    marker.write_text(str(corporate) + "\n", encoding="utf-8")
    if seed_baseline:
        update_surface_baseline(corporate, factory_root=factory)
    return marker


def resolve_program_root(factory_root: Path | None = None) -> Path | None:
    """Resolve bound corporate root via env or `.corp-harness-program-root`."""
    env = os.environ.get(PROGRAM_ROOT_ENV, "").strip()
    if env:
        candidate = Path(env).expanduser().resolve()
        if candidate.is_dir() and (candidate / "program.json").is_file():
            return candidate
        return None
    factory = (factory_root or factory_checkout_root()).expanduser().resolve()
    marker = factory / PROGRAM_ROOT_MARKER
    if not marker.is_file():
        return None
    raw = marker.read_text(encoding="utf-8").strip()
    if not raw:
        return None
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = (factory / candidate).resolve()
    else:
        candidate = candidate.resolve()
    if candidate.is_dir() and (candidate / "program.json").is_file():
        return candidate
    return None


def program_root_is_bound(factory_root: Path | None = None) -> bool:
    return resolve_program_root(factory_root) is not None


def heavy_validate_forced(
    program_root: Path,
    *,
    factory_root: Path | None = None,
) -> bool:
    """Whether mutating apply must run heavy validate-action.

    Bound roots always force (handoff heavy_validate_always_force_when_root_bound).
    Unbound roots force only when the trust band / action already routes heavy
    (score < 0.70 or always-force seals); score 1.0 unbound skips the gate.
    """
    if program_root_is_bound(factory_root):
        return True
    state = load_trust_state(program_root)
    return execution_layer_for_score(state.trust_score) == "heavy"


def prior_binding_established(program_root: Path) -> bool:
    """True when a prior bind left durable baseline evidence (survives unbind)."""
    baseline = load_surface_baseline(program_root)
    if baseline is None:
        return False
    if baseline.get("factory_root"):
        return True
    factory_base = baseline.get("factory")
    if not isinstance(factory_base, dict):
        return False
    return PROGRAM_ROOT_MARKER in factory_base


def classify_unbind_program_root_seal_bypass(
    program_root: Path,
    *,
    factory_root: Path | None = None,
) -> dict[str, str] | None:
    """Unbind after bind → seal_bypass_attempt (does not restore SG-03)."""
    factory = (
        factory_root.expanduser().resolve()
        if factory_root is not None
        else factory_checkout_root()
    )
    if not prior_binding_established(program_root):
        return None
    if program_root_is_bound(factory):
        return None
    return {
        "theater_signal_id": "seal_bypass_attempt",
        "reason": (
            "program root unbound after prior bind "
            f"(cleared {PROGRAM_ROOT_ENV} / {PROGRAM_ROOT_MARKER}); "
            "SG-03 soft-fail rights are not restored"
        ),
        "protected_path": PROGRAM_ROOT_MARKER,
    }


def sg03_soft_fail_allowed(
    *,
    factory_root: Path | None = None,
    program_root: Path | None = None,
) -> bool:
    """SG-03 soft-fail only when never bound; bound or unbind-after-bind deny it."""
    if program_root_is_bound(factory_root):
        return False
    if program_root is not None and prior_binding_established(program_root):
        return False
    return True


def factory_hooks_installed(factory_root: Path | None = None) -> bool:
    factory = (factory_root or factory_checkout_root()).expanduser().resolve()
    hooks = factory / ".cursor" / "hooks.json"
    return hooks.is_file()


def load_factory_hooks_config(factory_root: Path | None = None) -> dict[str, Any] | None:
    factory = (factory_root or factory_checkout_root()).expanduser().resolve()
    path = factory / ".cursor" / "hooks.json"
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def required_hooks_intact(factory_root: Path | None = None) -> bool:
    """True when required afterFileEdit + beforeShellExecution hooks are present."""
    factory = (factory_root or factory_checkout_root()).expanduser().resolve()
    cfg = load_factory_hooks_config(factory)
    if cfg is None:
        return False
    hooks = cfg.get("hooks")
    if not isinstance(hooks, dict):
        return False
    for event in sorted(REQUIRED_CURSOR_HOOK_EVENTS):
        entries = hooks.get(event)
        if not isinstance(entries, list) or not entries:
            return False
        has_command = any(
            isinstance(entry, dict) and str(entry.get("command") or "").strip()
            for entry in entries
        )
        if not has_command:
            return False
    script = factory / REQUIRED_HOOK_SCRIPT
    return script.is_file()


def baseline_had_factory_hooks(program_root: Path) -> bool:
    baseline = load_surface_baseline(program_root)
    if baseline is None:
        return False
    factory_base = baseline.get("factory")
    if not isinstance(factory_base, dict):
        return False
    return any(
        key == FACTORY_HOOKS_JSON or key.startswith(".cursor/")
        for key in factory_base
    )


def classify_disabled_hooks_seal_bypass(
    program_root: Path,
    *,
    factory_root: Path | None = None,
) -> dict[str, str] | None:
    """Disabling/removing required hooks while bound (after install) → seal_bypass."""
    factory = (
        factory_root.expanduser().resolve()
        if factory_root is not None
        else factory_checkout_root()
    )
    if not program_root_is_bound(factory):
        return None
    if not baseline_had_factory_hooks(program_root) and not factory_hooks_installed(
        factory
    ):
        return None
    if required_hooks_intact(factory):
        return None
    return {
        "theater_signal_id": "seal_bypass_attempt",
        "reason": (
            "required .cursor hooks disabled or removed while program root bound "
            f"(need {sorted(REQUIRED_CURSOR_HOOK_EVENTS)} + {REQUIRED_HOOK_SCRIPT})"
        ),
        "protected_path": FACTORY_HOOKS_JSON,
    }


def should_run_deferred_dirty_scan(
    factory_root: Path | None = None,
    *,
    program_root: Path | None = None,
) -> bool:
    if program_root_is_bound(factory_root) or factory_hooks_installed(factory_root):
        return True
    if program_root is not None and prior_binding_established(program_root):
        return True
    return False


def require_program_root_for_protected_touch(
    factory_root: Path | None = None,
    *,
    theater_root: Path | None = None,
    protected_path: str | None = None,
) -> Path:
    """Fail closed when program root is missing/unresolvable on protected touch."""
    resolved = resolve_program_root(factory_root)
    if resolved is not None:
        return resolved
    target = theater_root.expanduser().resolve() if theater_root is not None else None
    if target is not None and (target / "program.json").is_file():
        report_anti_harness_event(
            target,
            theater_signal_id="wrong_root_operation",
            reasons=[
                "protected surface touch without resolvable program root binding",
                *( [f"path={protected_path}"] if protected_path else [] ),
            ],
            protected_path=protected_path,
        )
    raise ContractError(
        "wrong_root_operation: program root missing or unresolvable for protected touch"
    )


def report_anti_harness_event(
    program_root: Path,
    *,
    theater_signal_id: str,
    reasons: list[str],
    protected_path: str | None = None,
    event_id: str | None = None,
    content_hash: str | None = None,
) -> TrustState:
    """Sole anti-harness report path helper → emit_and_apply deceptive_theater."""
    if theater_signal_id not in THEATER_SIGNAL_IDS:
        raise ContractError(
            f"unknown theater_signal_id: {theater_signal_id!r}; "
            f"expected one of {sorted(THEATER_SIGNAL_IDS)}"
        )
    root = program_root.expanduser().resolve()
    program_path = root / "program.json"
    if not program_path.is_file():
        raise ContractError(f"program does not exist: {program_path}")
    return emit_and_apply(
        root,
        kind="deceptive_theater",
        program_digest=digest_path(program_path),
        theater_signal_id=theater_signal_id,
        reasons=list(reasons) or [theater_signal_id],
        protected_path=protected_path,
        content_hash=content_hash,
        event_id=event_id,
    )


def mint_mutation_permit(
    program_root: Path,
    *,
    paths: list[str],
    ttl_seconds: int = MAX_PERMIT_TTL_SECONDS,
    now: datetime | None = None,
    permit_id: str | None = None,
) -> dict[str, Any]:
    """Mint short-lived single-use permit for authorized harness --apply."""
    if ttl_seconds < 1 or ttl_seconds > MAX_PERMIT_TTL_SECONDS:
        raise ContractError(
            f"ttl_seconds must be in 1..{MAX_PERMIT_TTL_SECONDS}, got {ttl_seconds}"
        )
    if not paths:
        raise ContractError("mutation permit requires non-empty paths")
    root = program_root.expanduser().resolve()
    program_path = root / "program.json"
    if not program_path.is_file():
        raise ContractError(f"program does not exist: {program_path}")
    moment = now or datetime.now(timezone.utc)
    minted_at = _format_utc(moment)
    expires_at = _format_utc(moment + timedelta(seconds=ttl_seconds))
    permit = {
        "schema": MUTATION_PERMIT_SCHEMA,
        "permit_id": permit_id or str(uuid.uuid4()),
        "program_digest": digest_path(program_path),
        "paths": sorted({str(p) for p in paths}),
        "ttl_seconds": int(ttl_seconds),
        "minted_at": minted_at,
        "expires_at": expires_at,
        "single_use": True,
        "writer": SOLE_EMITTER,
    }
    path = mutation_permit_path(root)
    path.write_text(json.dumps(permit, indent=2) + "\n", encoding="utf-8")
    return permit


def _permit_ttl_matches(permit: dict[str, Any]) -> bool:
    try:
        minted = _parse_utc(str(permit["minted_at"]))
        expires = _parse_utc(str(permit["expires_at"]))
        ttl = int(permit["ttl_seconds"])
    except (KeyError, TypeError, ValueError):
        return False
    expected = int((expires - minted).total_seconds())
    return expected == ttl


def validate_mutation_permit(
    permit: dict[str, Any],
    *,
    program_digest: str,
    paths: list[str] | None = None,
    now: datetime | None = None,
    allow_program_digest_advance: bool = False,
) -> None:
    """Raise ContractError when permit is forged/expired/mismatched/skewed.

    When ``allow_program_digest_advance`` is set and ``program.json`` is in the
    permit paths, a post-save digest may differ from the mint-time digest.
    """
    if not isinstance(permit, dict):
        raise ContractError("mutation permit must be an object")
    if permit.get("schema") != MUTATION_PERMIT_SCHEMA:
        raise ContractError("mutation permit schema mismatch")
    if permit.get("writer") != SOLE_EMITTER:
        raise ContractError("mutation permit writer must be python_runtime_engine")
    if permit.get("single_use") is not True:
        raise ContractError("mutation permit single_use must be true")
    if not permit.get("permit_id"):
        raise ContractError("mutation permit missing permit_id")
    try:
        ttl = int(permit.get("ttl_seconds"))
    except (TypeError, ValueError) as exc:
        raise ContractError("mutation permit ttl_seconds invalid") from exc
    if ttl < 1 or ttl > MAX_PERMIT_TTL_SECONDS:
        raise ContractError(f"mutation permit ttl_seconds out of range: {ttl}")
    if not _permit_ttl_matches(permit):
        raise ContractError("mutation permit ttl_seconds mismatches expires_at-minted_at")
    permit_paths = permit.get("paths")
    if not isinstance(permit_paths, list) or not permit_paths:
        raise ContractError("mutation permit paths must be a non-empty list")
    allowed = {str(p) for p in permit_paths}
    permit_digest = str(permit.get("program_digest") or "")
    if permit_digest != program_digest:
        if not (allow_program_digest_advance and "program.json" in allowed):
            raise ContractError("mutation permit program_digest mismatch")
    if paths is not None:
        needed = {str(p) for p in paths}
        if not needed.issubset(allowed):
            raise ContractError("mutation permit paths mismatch")
    try:
        minted = _parse_utc(str(permit["minted_at"]))
        expires = _parse_utc(str(permit["expires_at"]))
    except (KeyError, ValueError) as exc:
        raise ContractError("mutation permit timestamps invalid") from exc
    moment = now or datetime.now(timezone.utc)
    if moment < minted:
        raise ContractError("mutation permit clock skew: now < minted_at")
    if moment > expires:
        raise ContractError("mutation permit expired")


def load_mutation_permit(program_root: Path) -> dict[str, Any] | None:
    path = mutation_permit_path(program_root)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def consume_mutation_permit(
    program_root: Path,
    *,
    paths: list[str] | None = None,
    now: datetime | None = None,
    report_theater: bool = True,
) -> dict[str, Any]:
    """Validate and single-use consume permit; theater on invalid/reused."""
    root = program_root.expanduser().resolve()
    program_path = root / "program.json"
    digest = digest_path(program_path) if program_path.is_file() else ""
    path = mutation_permit_path(root)
    permit = load_mutation_permit(root)
    if permit is None:
        if report_theater and program_path.is_file():
            report_anti_harness_event(
                root,
                theater_signal_id="out_of_band_mutation",
                reasons=["missing or forged trust-mutation-permit.json"],
                protected_path="trust-mutation-permit.json",
            )
        raise ContractError("out_of_band_mutation: mutation permit missing or forged")
    try:
        validate_mutation_permit(
            permit,
            program_digest=digest,
            paths=paths,
            now=now,
            # Authorized --apply saves program.json then consumes; digest advances.
            allow_program_digest_advance=True,
        )
    except ContractError as exc:
        if path.is_file():
            path.unlink()
        if report_theater and program_path.is_file():
            report_anti_harness_event(
                root,
                theater_signal_id="out_of_band_mutation",
                reasons=[f"invalid mutation permit: {exc}"],
                protected_path="trust-mutation-permit.json",
            )
        raise ContractError(f"out_of_band_mutation: {exc}") from exc
    # Single-use: delete before returning so reuse fails.
    if path.is_file():
        path.unlink()
    return permit


def authorize_paths_with_permit(
    program_root: Path,
    *,
    paths: list[str],
    now: datetime | None = None,
) -> bool:
    """Return True when a valid (unconsumed) permit covers paths."""
    root = program_root.expanduser().resolve()
    program_path = root / "program.json"
    if not program_path.is_file():
        return False
    permit = load_mutation_permit(root)
    if permit is None:
        return False
    try:
        validate_mutation_permit(
            permit,
            program_digest=digest_path(program_path),
            paths=paths,
            now=now,
        )
    except ContractError:
        return False
    return True


def _file_digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    return digest_path(path)


def _relative_posix(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def is_factory_d8_path(rel: str) -> bool:
    normalized = rel.lstrip("./")
    if normalized in FACTORY_D8_FILES or normalized == ".cursor":
        return True
    if normalized.startswith(".cursor/"):
        return True
    return any(normalized == p.rstrip("/") or normalized.startswith(p) for p in FACTORY_D8_PREFIXES)


def is_corporate_protected_path(rel: str) -> bool:
    normalized = rel.lstrip("./")
    if normalized in CORPORATE_PROTECTED_FILES:
        return True
    return normalized.startswith("evidence/")


def collect_corporate_protected_digests(program_root: Path) -> dict[str, str]:
    root = program_root.expanduser().resolve()
    digests: dict[str, str] = {}
    for name in sorted(CORPORATE_PROTECTED_FILES):
        digest = _file_digest(root / name)
        if digest is not None:
            digests[name] = digest
    evidence = root / "evidence"
    if evidence.is_dir():
        for path in sorted(evidence.rglob("*.json")):
            if path.is_file():
                digests[_relative_posix(path, root)] = digest_path(path)
    return digests


def collect_factory_d8_digests(factory_root: Path) -> dict[str, str]:
    factory = factory_root.expanduser().resolve()
    digests: dict[str, str] = {}
    for name in sorted(FACTORY_D8_FILES):
        path = factory / name
        if path.is_file():
            digests[name] = digest_path(path)
    for prefix in FACTORY_D8_PREFIXES:
        base = factory / prefix.rstrip("/")
        if not base.exists():
            continue
        if base.is_file():
            digests[prefix.rstrip("/")] = digest_path(base)
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file():
                digests[_relative_posix(path, factory)] = digest_path(path)
    cursor = factory / ".cursor"
    if cursor.is_dir():
        for path in sorted(cursor.rglob("*")):
            if path.is_file():
                digests[_relative_posix(path, factory)] = digest_path(path)
    return digests


def load_surface_baseline(program_root: Path) -> dict[str, Any] | None:
    path = surface_baseline_path(program_root)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def update_surface_baseline(
    program_root: Path,
    *,
    factory_root: Path | None = None,
) -> dict[str, Any]:
    """Snapshot protected surface digests after authorized harness apply."""
    root = program_root.expanduser().resolve()
    corporate = collect_corporate_protected_digests(root)
    factory_digests: dict[str, str] = {}
    resolved_factory = None
    if factory_root is not None:
        resolved_factory = factory_root.expanduser().resolve()
        factory_digests = collect_factory_d8_digests(resolved_factory)
    payload = {
        "schema": SURFACE_BASELINE_SCHEMA,
        "program_digest": digest_path(root / "program.json"),
        "updated_at": _now(),
        "writer": SOLE_EMITTER,
        "corporate": corporate,
        "factory": factory_digests,
        "factory_root": str(resolved_factory) if resolved_factory else None,
    }
    surface_baseline_path(root).write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def seed_surface_baseline_if_missing(
    program_root: Path,
    *,
    factory_root: Path | None = None,
) -> dict[str, Any]:
    existing = load_surface_baseline(program_root)
    if existing is not None:
        return existing
    return update_surface_baseline(program_root, factory_root=factory_root)


def detect_false_genesis_signals(program_root: Path) -> list[dict[str, str]]:
    """Detect dual-wipe / post-log deletion / anchor delete false-genesis."""
    root = program_root.expanduser().resolve()
    findings: list[dict[str, str]] = []
    state_missing = not trust_state_path(root).is_file()
    log_nonempty = _log_is_nonempty(root)
    anchor = _anchor_exists(root)
    log_path = trust_event_log_path(root)
    log_exists = log_path.is_file()
    if state_missing and (log_nonempty or anchor):
        findings.append(
            {
                "theater_signal_id": "out_of_band_mutation",
                "reason": "trust-state.json missing after non-empty log or anchor",
                "protected_path": "trust-state.json",
            }
        )
    if anchor and (not log_exists or not log_nonempty):
        findings.append(
            {
                "theater_signal_id": "out_of_band_mutation",
                "reason": "trust-event-log wiped/truncated while trust-log-anchor exists",
                "protected_path": "trust-event-log.jsonl",
            }
        )
    baseline = load_surface_baseline(root)
    if baseline is not None:
        prior_anchor = (baseline.get("corporate") or {}).get("trust-log-anchor.json")
        if prior_anchor and not anchor:
            findings.append(
                {
                    "theater_signal_id": "out_of_band_mutation",
                    "reason": "trust-log-anchor.json deleted after baseline",
                    "protected_path": "trust-log-anchor.json",
                }
            )
        prior_log = (baseline.get("corporate") or {}).get("trust-event-log.jsonl")
        if prior_log and not log_nonempty:
            findings.append(
                {
                    "theater_signal_id": "out_of_band_mutation",
                    "reason": "trust-event-log.jsonl deleted/emptied after baseline",
                    "protected_path": "trust-event-log.jsonl",
                }
            )
    state = load_trust_state(root)
    if state.false_genesis:
        findings.append(
            {
                "theater_signal_id": "out_of_band_mutation",
                "reason": "false genesis: refuse synthesize 1.0 after log/anchor evidence",
                "protected_path": "trust-state.json",
            }
        )
    return findings


def detect_dirty_surfaces(
    program_root: Path,
    *,
    factory_root: Path | None = None,
    now: datetime | None = None,
) -> list[dict[str, str]]:
    """Compare protected digests to baseline; honor valid mutation permits."""
    root = program_root.expanduser().resolve()
    findings = detect_false_genesis_signals(root)
    baseline = load_surface_baseline(root)
    if baseline is None:
        return findings
    raw_corporate = baseline.get("corporate")
    corporate_base = raw_corporate if isinstance(raw_corporate, dict) else {}
    current_corporate = collect_corporate_protected_digests(root)
    for rel, prior in corporate_base.items():
        if rel == "trust-surface-baseline.json":
            continue
        current = current_corporate.get(rel)
        if current == prior:
            continue
        if authorize_paths_with_permit(root, paths=[rel], now=now):
            continue
        findings.append(
            {
                "theater_signal_id": "out_of_band_mutation",
                "reason": f"corporate protected surface mutated out-of-band: {rel}",
                "protected_path": rel,
            }
        )
    for rel, current in current_corporate.items():
        if rel in corporate_base:
            continue
        # Baseline file is writer-owned bookkeeping, not an OOB signal.
        if rel == "trust-surface-baseline.json":
            continue
        if authorize_paths_with_permit(root, paths=[rel], now=now):
            continue
        findings.append(
            {
                "theater_signal_id": "out_of_band_mutation",
                "reason": f"corporate protected surface created out-of-band: {rel}",
                "protected_path": rel,
            }
        )
    if factory_root is None:
        return findings
    factory = factory_root.expanduser().resolve()
    factory_base = baseline.get("factory") if isinstance(baseline.get("factory"), dict) else {}
    current_factory = collect_factory_d8_digests(factory)
    for rel, prior in factory_base.items():
        current = current_factory.get(rel)
        if current == prior:
            continue
        if authorize_paths_with_permit(root, paths=[rel], now=now):
            continue
        findings.append(
            {
                "theater_signal_id": "out_of_band_mutation",
                "reason": f"factory D8 surface mutated out-of-band: {rel}",
                "protected_path": rel,
            }
        )
    for rel, current in current_factory.items():
        if rel in factory_base:
            continue
        if authorize_paths_with_permit(root, paths=[rel], now=now):
            continue
        if not is_factory_d8_path(rel):
            continue
        findings.append(
            {
                "theater_signal_id": "out_of_band_mutation",
                "reason": f"factory D8 surface created out-of-band: {rel}",
                "protected_path": rel,
            }
        )
    return findings


def classify_stale_factory_authorization(
    program_root: Path,
    *,
    program: Program | None = None,
) -> dict[str, str] | None:
    """Return theater finding when factory_authorization is missing/unbound."""
    root = program_root.expanduser().resolve()
    loaded = program
    if loaded is None:
        program_path = root / "program.json"
        if not program_path.is_file():
            return None
        loaded = Program.load(program_path)
    if loaded.program_kind != "factory":
        return None
    auth = loaded.artifacts.get("factory_authorization")
    master = loaded.artifacts.get("master_spec")
    if auth is None:
        if master is not None:
            return {
                "theater_signal_id": "stale_factory_authorization",
                "reason": "factory_authorization missing while master_spec recorded",
                "protected_path": "factory-authorization.json",
            }
        return None
    issues = [
        issue
        for issue in loaded.current_issues(program_root=root)
        if "factory_authorization" in issue
    ]
    if issues:
        return {
            "theater_signal_id": "stale_factory_authorization",
            "reason": issues[0],
            "protected_path": "factory-authorization.json",
        }
    # Digest drift on the auth file itself vs recorded artifact sha.
    try:
        if digest_path(Path(auth.path)) != auth.sha256:
            return {
                "theater_signal_id": "stale_factory_authorization",
                "reason": "factory_authorization artifact digest drifted",
                "protected_path": "factory-authorization.json",
            }
        body = json.loads(Path(auth.path).read_text(encoding="utf-8"))
        if master is not None:
            master_digest = digest_path(Path(master.path))
            if str(body.get("master_spec_sha256") or "") != master_digest:
                return {
                    "theater_signal_id": "stale_factory_authorization",
                    "reason": "factory_authorization master_spec_sha256 unbound",
                    "protected_path": "factory-authorization.json",
                }
    except (OSError, json.JSONDecodeError, ContractError) as exc:
        return {
            "theater_signal_id": "stale_factory_authorization",
            "reason": f"factory_authorization unreadable or invalid: {exc}",
            "protected_path": "factory-authorization.json",
        }
    return None


def _sync_baseline_after_trust_write(
    program_root: Path,
    *,
    factory_root: Path | None = None,
) -> None:
    """Keep sole-writer digests current so emit_and_apply is not self-theater."""
    root = program_root.expanduser().resolve()
    existing = load_surface_baseline(root)
    if existing is None:
        # Do not create baseline on every event; only sync when one exists
        # (established by bind or authorized apply). Still refresh if false
        # genesis protections need log/state tip tracking after first event:
        if _anchor_exists(root) or _log_is_nonempty(root):
            update_surface_baseline(root, factory_root=factory_root)
        return
    update_surface_baseline(
        root,
        factory_root=(
            factory_root
            if factory_root is not None
            else (
                Path(str(existing["factory_root"]))
                if existing.get("factory_root")
                else None
            )
        ),
    )


def run_deferred_dirty_scan(
    program_root: Path,
    *,
    factory_root: Path | None = None,
    program: Program | None = None,
    now: datetime | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Deferred dirty-surface scan; reports via report_anti_harness_event.

    When program root is unbound and hooks are absent, returns clean no-op
    unless force=True (protected-touch fail-closed paths). Clean status must
    not write baseline or other sole-writer files.
    """
    root = program_root.expanduser().resolve()
    factory = (
        factory_root.expanduser().resolve()
        if factory_root is not None
        else None
    )
    if not force and not should_run_deferred_dirty_scan(factory, program_root=root):
        return {"ok": True, "dirty": False, "reported": [], "skipped": True}

    # Binding present but resolves elsewhere than CLI --root → wrong_root.
    bound = resolve_program_root(factory) if factory is not None else resolve_program_root()
    reported: list[dict[str, Any]] = []
    if bound is not None and bound != root:
        state = report_anti_harness_event(
            root,
            theater_signal_id="wrong_root_operation",
            reasons=[
                f"CLI root {root} != bound program root {bound}",
            ],
            protected_path="program.json",
        )
        reported.append(
            {
                "theater_signal_id": "wrong_root_operation",
                "trust_score": float(state.trust_score),
            }
        )
        return {"ok": False, "dirty": True, "reported": reported, "skipped": False}

    findings = detect_dirty_surfaces(root, factory_root=factory, now=now)
    unbind_bypass = (
        classify_unbind_program_root_seal_bypass(root, factory_root=factory)
        if factory is not None
        else classify_unbind_program_root_seal_bypass(root)
    )
    if unbind_bypass is not None:
        # Prefer seal_bypass over generic OOB for marker deletion after bind.
        findings = [
            f
            for f in findings
            if not (
                str(f.get("protected_path") or "") == PROGRAM_ROOT_MARKER
                and f.get("theater_signal_id") == "out_of_band_mutation"
            )
        ]
        findings.append(unbind_bypass)
    hook_bypass = (
        classify_disabled_hooks_seal_bypass(root, factory_root=factory)
        if factory is not None
        else None
    )
    if hook_bypass is not None:
        # Prefer seal_bypass_attempt over generic OOB for required-hook disable.
        findings = [
            f
            for f in findings
            if not (
                str(f.get("protected_path") or "").startswith(".cursor")
                and f.get("theater_signal_id") == "out_of_band_mutation"
            )
        ]
        findings.append(hook_bypass)
    stale = classify_stale_factory_authorization(root, program=program)
    # Stale auth elevates only alongside dirty protected/D8 findings (not alone on
    # every forced apply entry during DESIGN before factory_authorization exists).
    if stale is not None and findings:
        findings.append(stale)

    # Deduplicate by protected_path+signal.
    seen: set[tuple[str, str]] = set()
    for finding in findings:
        key = (finding["theater_signal_id"], finding.get("protected_path") or "")
        if key in seen:
            continue
        seen.add(key)
        state = report_anti_harness_event(
            root,
            theater_signal_id=finding["theater_signal_id"],
            reasons=[finding["reason"]],
            protected_path=finding.get("protected_path"),
        )
        reported.append(
            {
                "theater_signal_id": finding["theater_signal_id"],
                "protected_path": finding.get("protected_path"),
                "trust_score": float(state.trust_score),
            }
        )
    return {
        "ok": not reported,
        "dirty": bool(reported),
        "reported": reported,
        "skipped": False,
    }


def authorized_apply_with_permit(
    program_root: Path,
    *,
    paths: list[str],
    apply_fn: Any,
    factory_root: Path | None = None,
    ttl_seconds: int = MAX_PERMIT_TTL_SECONDS,
    now: datetime | None = None,
) -> Any:
    """Mint permit, run apply_fn, consume permit, refresh baseline."""
    root = program_root.expanduser().resolve()
    covered = sorted({*paths, "program.json", "trust-state.json", "trust-event-log.jsonl"})
    mint_mutation_permit(root, paths=covered, ttl_seconds=ttl_seconds, now=now)
    try:
        result = apply_fn()
        consume_mutation_permit(root, paths=None, now=now, report_theater=True)
        update_surface_baseline(root, factory_root=factory_root)
        return result
    except Exception:
        # Best-effort consume cleanup without double theater if already reported.
        path = mutation_permit_path(root)
        if path.is_file():
            path.unlink()
        raise
