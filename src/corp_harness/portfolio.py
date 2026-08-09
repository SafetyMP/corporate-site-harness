"""Readonly portfolio orchestrator facilitated by corporate/site harness."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from corp_harness.model import SITE_SCHEMA, ContractError

SCHEMA = "corporate-site-portfolio/v1"
HARNESS_VALUES = frozenset({"corporate", "site"})
EXCEPTION_ALLOWLIST = frozenset({"asclepius", "opencode"})
BUILTIN_SENSORS = ("inventory", "readiness")
DECLARABLE_SENSORS = frozenset({"inventory", "readiness", "parity", "security-alerts"})
RETIRED_TOKENS = ("portfolio-ops", "harnessctl", "harness_profile")


@dataclass(frozen=True)
class SensorResult:
    name: str
    status: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "message": self.message}


def _reject_retired(payload: Any, *, context: str) -> None:
    text = json.dumps(payload, sort_keys=True) if not isinstance(payload, str) else payload
    for token in RETIRED_TOKENS:
        if token in text:
            raise ContractError(f"retired identifier {token!r} is forbidden in {context}")


def _load_yaml_or_json(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    _reject_retired(raw, context=str(path))
    if path.suffix in {".yaml", ".yml"}:
        return _parse_minimal_yaml(raw)
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ContractError("portfolio contract root must be an object")
    return data


def _parse_minimal_yaml(text: str) -> dict[str, Any]:
    """Parse the restricted portfolio YAML subset used by SafetyMP metas."""
    try:
        import yaml  # type: ignore
    except ImportError:
        yaml = None
    if yaml is not None:
        data = yaml.safe_load(text)
        if not isinstance(data, dict):
            raise ContractError("portfolio contract root must be an object")
        return data
    # Fallback: accept JSON with a .yaml extension for hermetic tests.
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ContractError(
            "PyYAML is unavailable; provide JSON portfolio contracts or install PyYAML"
        ) from exc
    if not isinstance(data, dict):
        raise ContractError("portfolio contract root must be an object")
    return data


def load_portfolio_contract(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ContractError(f"portfolio contract not found: {resolved}")
    data = _load_yaml_or_json(resolved)
    _reject_retired(data, context="portfolio contract")
    if data.get("schema") != SCHEMA:
        raise ContractError(f"unsupported portfolio schema: {data.get('schema')!r}")
    if "harness_profile" in data:
        raise ContractError("harness_profile is retired and forbidden")
    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ContractError("portfolio contract requires a non-empty entries list")
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ContractError(f"entries[{index}] must be an object")
        if "harness_profile" in entry:
            raise ContractError("harness_profile is retired and forbidden")
        _reject_retired(entry, context=f"entries[{index}]")
        site_id = entry.get("site_id")
        repo_path = entry.get("repo_path")
        harness = entry.get("harness")
        if not isinstance(site_id, str) or not site_id.strip():
            raise ContractError(f"entries[{index}].site_id must be a non-empty string")
        if site_id in seen:
            raise ContractError(f"duplicate site_id: {site_id}")
        seen.add(site_id)
        if not isinstance(repo_path, str) or not repo_path.strip():
            raise ContractError(f"entries[{index}].repo_path must be a non-empty string")
        if harness not in HARNESS_VALUES:
            raise ContractError(f"entries[{index}].harness must be corporate or site")
        exception = entry.get("classification_exception")
        if exception is not None:
            if not isinstance(exception, dict) or not isinstance(exception.get("id"), str):
                raise ContractError(
                    f"entries[{index}].classification_exception must be an object with id"
                )
            if exception["id"] not in EXCEPTION_ALLOWLIST:
                raise ContractError(
                    f"entries[{index}].classification_exception.id is not allow-listed"
                )
        chex = entry.get("chex_multi_repo_exception")
        exception_ref = entry.get("exception_ref")
        if chex is True and (not isinstance(exception_ref, str) or not exception_ref.strip()):
            raise ContractError(
                f"entries[{index}] requires non-empty exception_ref with chex_multi_repo_exception"
            )
        if chex not in (None, True, False):
            raise ContractError(f"entries[{index}].chex_multi_repo_exception must be boolean")
        active = entry.get("active_program_root")
        if active is not None and (not isinstance(active, str) or not active.strip()):
            raise ContractError(f"entries[{index}].active_program_root must be a non-empty string")
        normalized.append(entry)
    sensors = data.get("sensors")
    if sensors is None:
        sensors = []
    if not isinstance(sensors, list) or any(not isinstance(item, str) for item in sensors):
        raise ContractError("sensors must be a list of strings when present")
    unknown = sorted(set(sensors) - DECLARABLE_SENSORS)
    if unknown:
        raise ContractError(f"unknown sensors: {', '.join(unknown)}")
    baseline = data.get("parity_baseline_site_id")
    if "parity" in sensors:
        if not isinstance(baseline, str) or not baseline.strip():
            raise ContractError(
                "parity_baseline_site_id is required when parity sensor is declared"
            )
        if baseline not in seen:
            raise ContractError("parity_baseline_site_id must match an entry site_id")
    security_snapshot = data.get("security_alerts_snapshot")
    if "security-alerts" in sensors and (
        not isinstance(security_snapshot, str) or not security_snapshot.strip()
    ):
        raise ContractError(
            "security_alerts_snapshot is required when security-alerts sensor is declared"
        )
    return {
        "schema": SCHEMA,
        "entries": normalized,
        "sensors": list(sensors),
        "parity_baseline_site_id": baseline,
        "security_alerts_snapshot": security_snapshot,
        "source_path": str(resolved),
    }


def _digest_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_inventory(contract: dict[str, Any]) -> SensorResult:
    classes = {entry["site_id"]: entry["harness"] for entry in contract["entries"]}
    return SensorResult(
        "inventory",
        "PASS",
        "classified "
        + ", ".join(
            f"{site_id}={harness}" for site_id, harness in sorted(classes.items())
        ),
    )


def _site_json_ok(repo: Path) -> str | None:
    site_json = repo / ".corp-harness" / "site.json"
    if not site_json.is_file():
        return f"missing {site_json}"
    try:
        data = json.loads(site_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"invalid site.json: {exc}"
    if data.get("schema") != SITE_SCHEMA:
        return f"site.json schema is {data.get('schema')!r}, expected {SITE_SCHEMA}"
    for key in ("verify_argv", "adversarial_argv"):
        argv = data.get(key)
        if not isinstance(argv, list) or not argv or not isinstance(argv[0], str):
            return f"site.json {key}[0] missing"
        script = repo / argv[0]
        if not script.is_file():
            return f"missing {argv[0]}"
        if not os.access(script, os.X_OK):
            return f"not executable: {argv[0]}"
    return None


def run_readiness(contract: dict[str, Any]) -> SensorResult:
    failures: list[str] = []
    for entry in contract["entries"]:
        site_id = entry["site_id"]
        if entry.get("classification_exception"):
            continue
        repo = Path(entry["repo_path"]).expanduser().resolve()
        live_harness = repo / ".harness"
        chex_ok = (
            entry.get("chex_multi_repo_exception") is True
            and isinstance(entry.get("exception_ref"), str)
            and bool(str(entry.get("exception_ref")).strip())
        )
        if live_harness.is_dir() and not chex_ok:
            failures.append(f"{site_id}: live .harness/ present without chex exception pairing")
        issue = _site_json_ok(repo)
        if issue:
            failures.append(f"{site_id}: {issue}")
    if failures:
        return SensorResult("readiness", "FAIL", "; ".join(failures))
    return SensorResult("readiness", "PASS", "all entries meet overlay readiness")


def run_parity(contract: dict[str, Any]) -> SensorResult:
    baseline_id = contract["parity_baseline_site_id"]
    baseline_entry = next(item for item in contract["entries"] if item["site_id"] == baseline_id)
    baseline_root = Path(baseline_entry["repo_path"]).expanduser().resolve()
    diffs: list[str] = []
    relative_paths = ["AGENTS.md"]
    rules_dir = baseline_root / ".cursor" / "rules"
    if rules_dir.is_dir():
        relative_paths.extend(
            sorted(
                str(path.relative_to(baseline_root))
                for path in rules_dir.glob("*.mdc")
                if path.is_file()
            )
        )
    baseline_digests = {}
    for relative in relative_paths:
        path = baseline_root / relative
        if path.is_file():
            baseline_digests[relative] = _digest_file(path)
    for entry in contract["entries"]:
        if entry["harness"] != "corporate" or entry["site_id"] == baseline_id:
            continue
        root = Path(entry["repo_path"]).expanduser().resolve()
        for relative, expected in baseline_digests.items():
            path = root / relative
            if not path.is_file():
                diffs.append(f"{entry['site_id']}:{relative}:missing")
                continue
            actual = _digest_file(path)
            if actual != expected:
                diffs.append(f"{entry['site_id']}:{relative}:digest-mismatch")
    if diffs:
        return SensorResult("parity", "FAIL", "; ".join(diffs))
    return SensorResult("parity", "PASS", f"aligned to baseline {baseline_id}")


def run_security_alerts(contract: dict[str, Any]) -> SensorResult:
    snapshot = Path(str(contract["security_alerts_snapshot"])).expanduser().resolve()
    if not snapshot.is_file():
        return SensorResult("security-alerts", "FAIL", f"snapshot missing: {snapshot}")
    try:
        data = json.loads(snapshot.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return SensorResult("security-alerts", "FAIL", f"invalid snapshot: {exc}")
    open_count = int(data.get("open_alert_count", 0))
    if open_count > 0:
        return SensorResult("security-alerts", "FAIL", f"open_alert_count={open_count}")
    return SensorResult("security-alerts", "PASS", "open_alert_count=0")


SENSOR_RUNNERS = {
    "inventory": run_inventory,
    "readiness": run_readiness,
    "parity": run_parity,
    "security-alerts": run_security_alerts,
}


def portfolio_check(contract_path: Path) -> dict[str, Any]:
    contract = load_portfolio_contract(contract_path)
    names = list(dict.fromkeys([*BUILTIN_SENSORS, *contract["sensors"]]))
    results = [SENSOR_RUNNERS[name](contract) for name in names]
    ok = all(item.status != "FAIL" for item in results)
    return {
        "ok": ok,
        "command": "portfolio check",
        "contract": contract["source_path"],
        "sensors": [item.to_dict() for item in results],
    }


def portfolio_status(contract_path: Path, *, timeout: int = 60) -> dict[str, Any]:
    contract = load_portfolio_contract(contract_path)
    entries_out: list[dict[str, Any]] = []
    for entry in contract["entries"]:
        active = entry.get("active_program_root")
        item: dict[str, Any] = {
            "site_id": entry["site_id"],
            "harness": entry["harness"],
            "active_program_root": active,
        }
        if not active:
            item["state"] = "UNBOUND"
            entries_out.append(item)
            continue
        root = Path(str(active)).expanduser().resolve()
        if not (root / "program.json").is_file():
            item["state"] = "UNKNOWN"
            item["issues"] = [f"missing program.json under {root}"]
            entries_out.append(item)
            continue
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "corp_harness", "status", "--root", str(root)],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            item["state"] = "UNKNOWN"
            item["issues"] = [str(exc)]
            entries_out.append(item)
            continue
        # Valid JSON with a program object is BOUND even when status exits nonzero
        # (ok: false). UNKNOWN only for non-JSON or missing program.
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            item["state"] = "UNKNOWN"
            item["issues"] = ["corp-harness status did not return JSON"]
            entries_out.append(item)
            continue
        program = payload.get("program") if isinstance(payload, dict) else None
        if not isinstance(program, dict):
            item["state"] = "UNKNOWN"
            item["issues"] = ["corp-harness status missing program object"]
            entries_out.append(item)
            continue
        item["ok"] = bool(payload.get("ok"))
        item["phase"] = program.get("phase")
        item["issues"] = payload.get("issues") if isinstance(payload.get("issues"), list) else []
        item["trust_score"] = payload.get("trust_score")
        item["execution_layer"] = payload.get("execution_layer")
        item["last_event"] = payload.get("last_event")
        item["state"] = "BOUND"
        policy = payload.get("execution_policy")
        if isinstance(policy, dict):
            # Readonly envelope for operators; portfolio never routes models.
            item["execution_policy"] = {
                "schema": policy.get("schema"),
                "budget": policy.get("budget"),
                "premium_allowlist": policy.get("premium_allowlist"),
                "evidence_max_age_seconds": policy.get("evidence_max_age_seconds"),
            }
        entries_out.append(item)
    return {
        "ok": all(item.get("state") != "UNKNOWN" for item in entries_out),
        "command": "portfolio status",
        "contract": contract["source_path"],
        "entries": entries_out,
    }


def _paths_nested(left: Path, right: Path) -> bool:
    left_r = left.resolve()
    right_r = right.resolve()
    return left_r == right_r or left_r in right_r.parents or right_r in left_r.parents


def portfolio_route(
    contract_path: Path,
    *,
    target: Path,
    program_root: Path | None = None,
    program_id: str | None = None,
) -> dict[str, Any]:
    contract = load_portfolio_contract(contract_path)
    target_resolved = target.expanduser().resolve()
    entry = next(
        (
            item
            for item in contract["entries"]
            if Path(item["repo_path"]).expanduser().resolve() == target_resolved
        ),
        None,
    )
    if entry is None:
        raise ContractError(f"target is not a portfolio entry repo_path: {target_resolved}")
    if entry.get("active_program_root"):
        raise ContractError(
            f"active_program_root already bound for {entry['site_id']}: "
            f"{entry['active_program_root']}"
        )
    site_id = entry["site_id"]
    computed_id = program_id or site_id
    computed_root = (
        program_root.expanduser().resolve()
        if program_root is not None
        else (target_resolved.parent / f"{site_id}-corporate-program").resolve()
    )
    if _paths_nested(computed_root, target_resolved):
        raise ContractError(
            "program_root and repo_path must not be nested; refuse to place program.json in site"
        )
    command = [
        "corp-harness",
        "init",
        "--root",
        str(computed_root),
        "--id",
        computed_id,
        "--site",
        str(target_resolved),
    ]
    return {
        "ok": True,
        "command": "portfolio route",
        "wrote": False,
        "site_id": site_id,
        "program_root": str(computed_root),
        "proposed_command": command,
        "proposed_command_line": " ".join(command),
        "apply": False,
    }


def dispatch_portfolio(args: Any) -> tuple[dict[str, Any], int]:
    action = args.portfolio_command
    contract = Path(args.contract)
    if action == "check":
        result = portfolio_check(contract)
        if args.output:
            _write_output(Path(args.output), result)
        return result, 0 if result["ok"] else 1
    if action == "status":
        result = portfolio_status(contract, timeout=int(args.timeout))
        if args.output:
            _write_output(Path(args.output), result)
        return result, 0 if result["ok"] else 1
    if action == "route":
        result = portfolio_route(
            contract,
            target=Path(args.target),
            program_root=Path(args.program_root) if args.program_root else None,
            program_id=args.program_id,
        )
        if args.output:
            _write_output(Path(args.output), result)
        return result, 0
    raise ContractError(f"unknown portfolio command: {action}")


def _write_output(path: Path, payload: dict[str, Any]) -> None:
    resolved = path.expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
