from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from corp_harness.archive import (
    create_archive,
    restore_archive_merge,
    restore_archive_payload,
    verify_archive,
)
from corp_harness.contracts import CORPORATE_ACCEPTANCE_ARGV
from corp_harness.evidence import run_evidence, write_evidence
from corp_harness.evidence_validation import resolve_check_evidence_roots
from corp_harness.execution_policy import (
    TASK_CLASSES,
    check_evidence_age,
    load_policy_for_program,
    load_recorded_premium_usd,
    policy_status_summary,
    record_premium_usage,
    route_model,
    validate_packet_attestation,
)
from corp_harness.install import install_plugin, rollback_plugin, validate_plugin
from corp_harness.model import PHASES, ContractError, Program, digest_path
from corp_harness.portfolio import dispatch_portfolio
from corp_harness.runtime_engine import (
    GOV_REQUIRED,
    THEATER_SIGNAL_IDS,
    TRUST_GATED_CLI_SURFACES,
    attach_trust_status,
    consume_mutation_permit,
    emit_and_apply,
    mint_mutation_permit,
    mutation_permit_path,
    read_trust_log,
    report_anti_harness_event,
    require_heavy_available,
    require_verifiable_trust_log,
    resolve_program_root,
    route_for_action,
    run_deferred_dirty_scan,
    sg03_soft_fail_allowed,
    update_surface_baseline,
)
from corp_harness.swift_gov import ASSIST_COMMANDS, find_corp_gov_check, run_gov_command

DEFAULT_RUNTIME = Path("~/.cursor/corporate-harness")
DEFAULT_PLUGIN_TARGET = Path("~/.cursor/plugins/local/corporate-site-harness")
EVIDENCE_COMMANDS = {
    "smoke": ["./scripts/harness/verify.sh"],
    "site_verify": ["./scripts/harness/verify.sh"],
    "operations": ["./scripts/harness/verify.sh"],
    "corporate_review": ["./scripts/harness/verify.sh"],
    "adversarial": ["./scripts/harness/adversarial.sh"],
    "corporate_acceptance": list(CORPORATE_ACCEPTANCE_ARGV),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="corp-harness")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="create a program contract")
    _root_argument(init_parser)
    init_parser.add_argument("--id", required=True)
    init_parser.add_argument("--site", type=Path, required=True)
    init_parser.add_argument(
        "--kind",
        choices=("product", "factory"),
        default="product",
        help="product (default) or factory platform program",
    )
    init_parser.add_argument("--domain", action="append", default=[])
    init_parser.add_argument("--apply", action="store_true")

    next_parser = subparsers.add_parser("next", help="advance or rework a program")
    _root_argument(next_parser)
    action = next_parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--to", choices=PHASES)
    action.add_argument("--rework", action="store_true")
    next_parser.add_argument("--actor", required=True)
    next_parser.add_argument("--apply", action="store_true")

    record_parser = subparsers.add_parser("record", help="record an artifact or gate")
    _root_argument(record_parser)
    record_type = record_parser.add_mutually_exclusive_group(required=True)
    record_type.add_argument("--artifact")
    record_type.add_argument("--gate")
    record_parser.add_argument("--path", type=Path, required=True)
    record_parser.add_argument("--actor", required=True)
    record_parser.add_argument("--status", choices=("PASS", "FAIL"))
    record_parser.add_argument("--apply", action="store_true")

    check_parser = subparsers.add_parser("check", help="validate state or run evidence")
    _root_argument(check_parser)
    check_parser.add_argument("--run")
    check_parser.add_argument("--cwd", type=Path)
    check_parser.add_argument("--timeout", type=int, default=120)
    check_parser.add_argument("--output", type=Path)
    check_parser.add_argument("--apply", action="store_true")
    check_parser.add_argument(
        "--attest-packet",
        type=Path,
        help="validate a work-packet model attestation against execution_policy",
    )
    check_parser.add_argument(
        "--evidence-captured-at",
        help="ISO-8601 timestamp to check against evidence_max_age_seconds",
    )
    check_parser.add_argument("argv", nargs=argparse.REMAINDER)

    status_parser = subparsers.add_parser("status", help="show current state")
    _root_argument(status_parser)

    route_model_parser = subparsers.add_parser(
        "route-model",
        help="resolve model_class for a role/task under execution_policy",
    )
    _root_argument(route_model_parser)
    route_model_parser.add_argument("--role", required=True)
    route_model_parser.add_argument("--task-class", required=True, choices=sorted(TASK_CLASSES))
    route_model_parser.add_argument("--packet", type=Path)
    route_model_parser.add_argument("--escalation", type=Path)
    route_model_parser.add_argument("--failed-standard-attempts", type=int, default=0)
    route_model_parser.add_argument("--max-mode", action="store_true")

    usage_parser = subparsers.add_parser(
        "usage",
        help="record or show premium model invoice usage (user actor for record)",
    )
    usage_sub = usage_parser.add_subparsers(dest="usage_command", required=True)
    usage_record = usage_sub.add_parser("record", help="record invoice premium spend")
    _root_argument(usage_record)
    usage_record.add_argument("--actor", required=True)
    usage_record.add_argument("--amount-usd", type=float, required=True)
    usage_record.add_argument("--source", required=True)
    usage_record.add_argument("--note", default="")
    usage_record.add_argument("--apply", action="store_true")
    usage_show = usage_sub.add_parser("show", help="show recorded premium spend")
    _root_argument(usage_show)

    archive_parser = subparsers.add_parser("archive", help="create or verify an archive")
    archive_action = archive_parser.add_mutually_exclusive_group(required=True)
    archive_action.add_argument("--create", action="store_true")
    archive_action.add_argument("--verify", type=Path)
    archive_action.add_argument("--restore", type=Path)
    archive_parser.add_argument("--source-root", type=Path)
    archive_parser.add_argument("--include", action="append", default=[])
    archive_parser.add_argument("--destination", type=Path)
    archive_parser.add_argument("--target", type=Path)
    archive_parser.add_argument("--payload")
    archive_parser.add_argument("--merge", action="store_true")
    archive_parser.add_argument("--apply", action="store_true")

    install_parser = subparsers.add_parser("install", help="validate or install the plugin")
    install_parser.add_argument("--source", type=Path, required=True)
    install_parser.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME)
    install_parser.add_argument("--plugin-target", type=Path, default=DEFAULT_PLUGIN_TARGET)
    install_parser.add_argument("--validate-only", action="store_true")
    install_parser.add_argument("--apply", action="store_true")

    rollback_parser = subparsers.add_parser("rollback", help="activate an older release")
    rollback_parser.add_argument("--release", required=True)
    rollback_parser.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME)
    rollback_parser.add_argument("--plugin-target", type=Path, default=DEFAULT_PLUGIN_TARGET)
    rollback_parser.add_argument("--apply", action="store_true")

    portfolio_parser = subparsers.add_parser(
        "portfolio",
        help="readonly portfolio orchestrator (status, check, route)",
    )
    portfolio_sub = portfolio_parser.add_subparsers(dest="portfolio_command", required=True)
    check_p = portfolio_sub.add_parser("check", help="run portfolio sensors")
    check_p.add_argument("--contract", type=Path, required=True)
    check_p.add_argument("--output", type=Path)
    status_p = portfolio_sub.add_parser("status", help="aggregate corp-harness status")
    status_p.add_argument("--contract", type=Path, required=True)
    status_p.add_argument("--timeout", type=int, default=60)
    status_p.add_argument("--output", type=Path)
    route_p = portfolio_sub.add_parser("route", help="print unexecuted corp-harness init")
    route_p.add_argument("--contract", type=Path, required=True)
    route_p.add_argument("--target", type=Path, required=True)
    route_p.add_argument("--program-root", type=Path)
    route_p.add_argument("--program-id")
    route_p.add_argument("--output", type=Path)

    gov_parser = subparsers.add_parser(
        "gov",
        help="Swift governance assist splash + heavy validate-action + write-receipt seal",
    )
    gov_sub = gov_parser.add_subparsers(dest="gov_command", required=True)
    for name in sorted(ASSIST_COMMANDS):
        gov_cmd = gov_sub.add_parser(name, help=f"assist-only {name}")
        _root_argument(gov_cmd)
        if name == "explain-transition":
            gov_cmd.add_argument(
                "--to",
                required=True,
                choices=PHASES,
                help="target phase to explain",
            )
        if name == "check-authorized-surfaces":
            gov_cmd.add_argument(
                "--path",
                action="append",
                default=[],
                help="relative factory path to allow/deny (repeatable)",
            )
    validate_cmd = gov_sub.add_parser(
        "validate-action",
        help="heavy-path validate-action (not always-force; never mutates program.json)",
    )
    _root_argument(validate_cmd)
    validate_cmd.add_argument("--action", required=True, help="harness action id")
    write_receipt_cmd = gov_sub.add_parser(
        "write-receipt",
        help="heavy-path FG-001 seal mint_gov_receipt (always-force; never mutates program.json)",
    )
    _root_argument(write_receipt_cmd)

    trust_parser = subparsers.add_parser(
        "trust",
        help="trust-state helpers (log read-only; report-event sole anti-harness path)",
    )
    trust_sub = trust_parser.add_subparsers(dest="trust_command", required=True)
    trust_log = trust_sub.add_parser(
        "log",
        help="read append-only trust-event-log.jsonl (non-event; never mutates)",
    )
    _root_argument(trust_log)
    trust_log.add_argument(
        "--limit",
        type=int,
        default=None,
        help="return only the last N entries (omit for all)",
    )
    trust_log.add_argument(
        "--verify-chain",
        action="store_true",
        help="recompute hash chain; ok=false on tamper (audit-only)",
    )
    trust_report = trust_sub.add_parser(
        "report-event",
        help="sole anti-harness report path → emit_and_apply deceptive_theater",
    )
    _root_argument(trust_report)
    trust_report.add_argument(
        "--signal",
        required=True,
        choices=sorted(THEATER_SIGNAL_IDS),
        help="D5 theater_signal_id",
    )
    trust_report.add_argument(
        "--reason",
        action="append",
        default=[],
        help="reason string (repeatable; at least one required)",
    )
    trust_report.add_argument(
        "--path",
        dest="protected_path",
        help="optional protected path relative to program or factory root",
    )
    trust_report.add_argument("--event-id", help="optional TrustEvent event_id")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result, exit_code = dispatch(args)
    except ContractError as exc:
        _emit({"ok": False, "error": str(exc)})
        return 3
    except OSError as exc:
        _emit({"ok": False, "error": f"filesystem error: {exc}"})
        return 4
    _emit(result)
    return exit_code


def dispatch(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    if args.command == "init":
        program = Program.create(
            args.id,
            args.site,
            args.domain,
            program_root=args.root,
            program_kind=args.kind,
        )
        path = _program_path(args.root)
        if path.exists():
            raise ContractError(f"program already exists: {path}")
        if args.apply:
            program.save(path)
        return {"ok": True, "apply": args.apply, "path": str(path), "program": program.to_dict()}, 0

    if args.command == "status":
        program = _load_program(args.root)
        program_root = args.root.expanduser().resolve()
        factory_root = Path(program.site_path).expanduser().resolve()
        dirty = _maybe_dirty_scan(program_root, factory_root=factory_root, program=program)
        issues = program.current_issues(program_root=program_root)
        policy = load_policy_for_program(program_root, program)
        recorded = load_recorded_premium_usd(program_root)
        # Reflect invoice ledger into the in-memory policy budget for status only.
        policy = dict(policy)
        budget = dict(policy.get("budget") or {})
        budget["recorded_premium_usd"] = recorded
        policy["budget"] = budget
        result = {
            "ok": not issues and dirty.get("ok", True),
            "program": program.to_dict(),
            "issues": issues,
            "execution_policy": policy_status_summary(policy, recorded),
        }
        if dirty.get("dirty"):
            result["anti_harness"] = dirty
        return attach_trust_status(result, program_root), 0 if result["ok"] else 1

    if args.command == "trust":
        return _trust(args)

    if args.command == "route-model":
        return _route_model(args)

    if args.command == "usage":
        return _usage(args)

    if args.command == "next":
        program = _load_program(args.root)
        program_root = args.root.expanduser().resolve()
        factory_root = Path(program.site_path).expanduser().resolve()
        # Dry-run entries scan immediately; --apply scans after permit mint.
        if not args.apply:
            _maybe_dirty_scan(program_root, factory_root=factory_root, program=program)
        if args.rework:
            program.rework(args.actor)
            action = "next_advance"
        else:
            program.advance(args.to, args.actor)
            action = "next_advance"
        if args.apply:
            _authorized_mutating_apply(
                program_root,
                factory_root=factory_root,
                program=program,
                action=action,
                covered_paths=["program.json"],
                apply_fn=lambda: (
                    program.save(_program_path(args.root)),
                    emit_and_apply(
                        program_root,
                        kind="strict_success",
                        program_digest=digest_path(_program_path(args.root)),
                    ),
                ),
            )
        result = {"ok": True, "apply": args.apply, "program": program.to_dict()}
        return attach_trust_status(result, program_root), 0

    if args.command == "record":
        program = _load_program(args.root)
        program_root = args.root.expanduser().resolve()
        factory_root = Path(program.site_path).expanduser().resolve()
        # Dry-run entries scan immediately; --apply scans after permit mint.
        if not args.apply:
            _maybe_dirty_scan(program_root, factory_root=factory_root, program=program)
        if args.artifact:
            action = f"record_artifact:{args.artifact}"
            recorded = program.record_artifact(
                args.artifact,
                args.path,
                args.actor,
                program_root,
            )
        else:
            if args.status is None:
                raise ContractError("--status is required when recording a gate")
            action = f"record_gate:{args.gate}"
            recorded = program.record_gate(
                args.gate,
                args.status,
                args.path,
                args.actor,
                program_root,
            )
        if args.apply:
            covered = ["program.json"]
            artifact_path = args.path.expanduser().resolve()
            try:
                covered.append(str(artifact_path.relative_to(program_root)))
            except ValueError:
                # Evidence may live outside the program root; keep program.json only.
                pass
            _authorized_mutating_apply(
                program_root,
                factory_root=factory_root,
                program=program,
                action=action,
                covered_paths=covered,
                apply_fn=lambda: (
                    program.save(_program_path(args.root)),
                    emit_and_apply(
                        program_root,
                        kind="strict_success",
                        program_digest=digest_path(_program_path(args.root)),
                    ),
                ),
            )
        result = {
            "ok": True,
            "apply": args.apply,
            "recorded": recorded.__dict__,
            "program": program.to_dict(),
        }
        return attach_trust_status(result, program_root), 0

    if args.command == "check":
        return _check(args)

    if args.command == "archive":
        _dirty_scan_bound_program_root(surface="archive")
        if args.verify is not None:
            return {
                "ok": True,
                **verify_archive(args.verify.expanduser().resolve(), args.payload),
            }, 0
        if args.restore is not None:
            if args.target is None:
                raise ContractError("--target is required with --restore")
            restore = restore_archive_merge if args.merge else restore_archive_payload
            result = restore(args.restore, args.target, args.apply, args.payload)
            return {"ok": True, **result}, 0
        if args.source_root is None or args.destination is None or not args.include:
            raise ContractError("--source-root, --destination, and --include are required")
        result = create_archive(
            args.source_root,
            args.include,
            args.destination,
            args.apply,
        )
        return {"ok": True, **result}, 0

    if args.command == "install":
        _dirty_scan_bound_program_root(surface="install")
        if args.validate_only:
            return {"ok": True, "plugin": validate_plugin(args.source)}, 0
        result = install_plugin(
            args.source,
            args.runtime_root,
            args.plugin_target,
            args.apply,
        )
        return {"ok": True, **result}, 0

    if args.command == "rollback":
        _dirty_scan_bound_program_root(surface="rollback")
        result = rollback_plugin(
            args.runtime_root,
            args.plugin_target,
            args.release,
            args.apply,
        )
        return {"ok": True, **result}, 0

    if args.command == "portfolio":
        return dispatch_portfolio(args)

    if args.command == "gov":
        to_phase = getattr(args, "to", None)
        paths = getattr(args, "path", None)
        action = getattr(args, "action", None)
        if args.gov_command in {"validate-action", "write-receipt"}:
            program = _load_program(args.root)
            program_root = args.root.expanduser().resolve()
            factory_root = Path(program.site_path).expanduser().resolve()
            _maybe_dirty_scan(
                program_root, factory_root=factory_root, program=program, force=True
            )
        return run_gov_command(
            args.gov_command,
            args.root,
            to_phase=to_phase,
            paths=paths or None,
            action=action,
        )

    raise ContractError(f"unknown command: {args.command}")


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ContractError(f"{label} not found: {resolved}")
    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read {label}: {exc}") from exc
    if not isinstance(data, dict):
        raise ContractError(f"{label} root must be an object")
    return data


def _route_model(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    program = _load_program(args.root)
    program_root = args.root.expanduser().resolve()
    policy = load_policy_for_program(program_root, program)
    recorded = load_recorded_premium_usd(program_root)
    budget = dict(policy.get("budget") or {})
    budget["recorded_premium_usd"] = recorded
    policy = {**policy, "budget": budget}
    packet = _load_json_object(args.packet, label="packet") if args.packet else None
    escalation = (
        _load_json_object(args.escalation, label="escalation") if args.escalation else None
    )
    result = route_model(
        role=args.role,
        task_class=args.task_class,
        policy=policy,
        packet=packet,
        escalation=escalation,
        failed_standard_attempts=args.failed_standard_attempts,
        max_mode=bool(args.max_mode),
    )
    exit_code = 0
    if result.get("denial_code"):
        exit_code = 1
        result["ok"] = False
    return result, exit_code


def _usage(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    program_root = args.root.expanduser().resolve()
    _load_program(args.root)  # ensure program exists
    if args.usage_command == "show":
        recorded = load_recorded_premium_usd(program_root)
        path = program_root / "premium-usage.json"
        ledger = None
        if path.is_file():
            ledger = _load_json_object(path, label="premium-usage")
        return {
            "ok": True,
            "recorded_premium_usd": recorded,
            "ledger": ledger,
        }, 0
    if args.usage_command == "record":
        if args.actor != "user":
            raise ContractError("usage record requires --actor user")
        preview = {
            "ok": True,
            "apply": False,
            "amount_usd": float(args.amount_usd),
            "source": args.source,
            "note": args.note,
            "recorded_premium_usd": load_recorded_premium_usd(program_root)
            + float(args.amount_usd),
        }
        if not args.apply:
            return preview, 0
        program = _load_program(args.root)
        factory_root = Path(program.site_path).expanduser().resolve()
        _maybe_dirty_scan(
            program_root, factory_root=factory_root, program=program, force=True
        )
        ledger = record_premium_usage(
            program_root,
            amount_usd=float(args.amount_usd),
            source=args.source,
            note=args.note,
        )
        return {"ok": True, "apply": True, "ledger": ledger}, 0
    raise ContractError(f"unknown usage command: {args.usage_command}")


def _check(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    program = _load_program(args.root)
    program_root = args.root.expanduser().resolve()
    issues = program.current_issues(program_root=program_root)
    result: dict[str, Any] = {"ok": not issues, "issues": issues}
    policy = load_policy_for_program(program_root, program)
    recorded = load_recorded_premium_usd(program_root)
    budget = dict(policy.get("budget") or {})
    budget["recorded_premium_usd"] = recorded
    policy = {**policy, "budget": budget}

    if args.attest_packet is not None:
        packet = _load_json_object(args.attest_packet, label="attest-packet")
        attestation = validate_packet_attestation(packet, policy=policy)
        result["attestation"] = attestation
        if not attestation.get("ok"):
            result["ok"] = False
            result["denial_code"] = attestation.get("denial_code")
            issues = list(issues)
            issues.append(
                attestation.get("error")
                or attestation.get("denial_code")
                or "packet attestation failed"
            )
            result["issues"] = issues

    if args.evidence_captured_at:
        age = check_evidence_age(args.evidence_captured_at, policy=policy)
        result["evidence_age"] = age
        if not age.get("ok"):
            result["ok"] = False
            result["denial_code"] = age.get("denial_code")
            issues = list(result.get("issues") or [])
            issues.append(
                f"evidence age {age.get('age_seconds')}s exceeds "
                f"{age.get('max_age_seconds')}s"
            )
            result["issues"] = issues

    if args.run:
        command = list(args.argv)
        if command and command[0] == "--":
            command = command[1:]
        if not command:
            raise ContractError("an evidence command is required after --")
        expected_command = EVIDENCE_COMMANDS.get(args.run)
        if expected_command is None or command != expected_command:
            raise ContractError(
                f"{args.run} evidence must run exactly: "
                + " ".join(expected_command or ["<unsupported>"])
            )
        cwd, allowed_root = resolve_check_evidence_roots(
            args.run,
            program_root=program_root,
            site_path=program.site_path,
            cwd=args.cwd,
        )
        gate_name = "adversary" if args.run == "adversarial" else args.run
        target_sha256 = None
        if gate_name in {
            "corporate_acceptance",
            "site_verify",
            "operations",
            "corporate_review",
            "adversary",
        }:
            target_sha256 = program.gate_target_digest(gate_name)
        # Capture emits corporate-site-evidence/v1 only (run_evidence schema).
        # Reviewer identity / review evidence are never produced by check.
        evidence = run_evidence(
            args.run,
            command,
            cwd,
            allowed_root,
            args.timeout,
            revision=program.revision,
            target_sha256=target_sha256,
        )
        output = args.output or (program_root / "evidence" / f"{args.run}-r{program.revision}.json")
        output = output.expanduser().resolve()
        evidence_root = (program_root / "evidence").resolve()
        if output == evidence_root or evidence_root not in output.parents:
            raise ContractError(
                "evidence output must be a file under the program evidence directory"
            )
        if args.apply:
            factory_root = Path(program.site_path).expanduser().resolve()
            covered = ["program.json"]
            try:
                covered.append(str(output.relative_to(program_root)))
            except ValueError:
                covered.append(str(output))

            def _apply() -> None:
                write_evidence(evidence, output)
                emit_and_apply(
                    program_root,
                    kind="strict_success" if evidence.passed else "validation_failure",
                    program_digest=digest_path(_program_path(args.root)),
                    reasons=[] if evidence.passed else [f"evidence failed: {args.run}"],
                )

            _authorized_mutating_apply(
                program_root,
                factory_root=factory_root,
                program=program,
                action="check_apply",
                covered_paths=covered,
                apply_fn=_apply,
            )
            issues = program.current_issues(program_root=program_root)
            result["issues"] = issues
            result["ok"] = not issues
        result.update(
            {
                "evidence": evidence.__dict__,
                "evidence_path": str(output),
                "apply": args.apply,
            }
        )
        if not evidence.passed:
            result["ok"] = False
    return attach_trust_status(result, program_root), 0 if result["ok"] else 1


def _trust(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    program_root = args.root.expanduser().resolve()
    program = _load_program(args.root)
    factory_root = Path(program.site_path).expanduser().resolve()
    if args.trust_command == "log":
        # Ensure program exists; trust log itself is a non-event and never mutates.
        payload = read_trust_log(
            program_root,
            limit=args.limit,
            verify_chain=bool(args.verify_chain),
        )
        return payload, 0 if payload.get("ok") else 1
    if args.trust_command == "report-event":
        reasons = list(args.reason or [])
        if not reasons:
            raise ContractError("trust report-event requires at least one --reason")
        # Sole report path: do not pre-scan (avoids double theater). Hooks/deferred
        # scan invoke this command as the consequential sink.
        state = report_anti_harness_event(
            program_root,
            theater_signal_id=str(args.signal),
            reasons=reasons,
            protected_path=args.protected_path,
            event_id=args.event_id,
        )
        update_surface_baseline(program_root, factory_root=factory_root)
        return attach_trust_status(
            {
                "ok": True,
                "reported": True,
                "theater_signal_id": args.signal,
                "trust_score": float(state.trust_score),
                "execution_layer": state.execution_layer,
            },
            program_root,
        ), 0
    raise ContractError(f"unsupported trust command: {args.trust_command!r}")


def _maybe_dirty_scan(
    program_root: Path,
    *,
    factory_root: Path | None = None,
    program: Program | None = None,
    force: bool = False,
) -> dict[str, Any]:
    return run_deferred_dirty_scan(
        program_root,
        factory_root=factory_root,
        program=program,
        force=force,
    )


def _dirty_scan_bound_program_root(*, surface: str) -> dict[str, Any] | None:
    """Run deferred dirty scan for trust-gated surfaces that lack --root."""
    del surface  # documented participation via TRUST_GATED_CLI_SURFACES
    assert "archive" in TRUST_GATED_CLI_SURFACES
    bound = resolve_program_root()
    if bound is None:
        return None
    program = Program.load(bound / "program.json")
    factory_root = Path(program.site_path).expanduser().resolve()
    return _maybe_dirty_scan(
        bound, factory_root=factory_root, program=program, force=True
    )


def _authorized_mutating_apply(
    program_root: Path,
    *,
    factory_root: Path | None,
    program: Program | None,
    action: str,
    covered_paths: list[str],
    apply_fn: Any,
) -> None:
    """Mint permit before dirty scan, then apply, consume, and refresh baseline."""
    covered = sorted(
        {
            *covered_paths,
            "program.json",
            "trust-state.json",
            "trust-event-log.jsonl",
            "trust-log-anchor.json",
            "trust-mutation-permit.json",
        }
    )
    mint_mutation_permit(program_root, paths=covered)
    try:
        _maybe_dirty_scan(
            program_root, factory_root=factory_root, program=program, force=True
        )
        _enforce_trust_route(program_root, action, factory_root=factory_root)
        apply_fn()
        consume_mutation_permit(program_root, paths=None, report_theater=True)
        update_surface_baseline(program_root, factory_root=factory_root)
    except Exception:
        permit = mutation_permit_path(program_root)
        if permit.is_file():
            permit.unlink()
        raise


def _enforce_trust_route(
    program_root: Path,
    action: str,
    *,
    factory_root: Path | None = None,
) -> None:
    """Fail closed on broken trust log or missing corp-gov-check when required.

    Bound program roots always force heavy_validate (handoff
    heavy_validate_always_force_when_root_bound). Unbound light routes skip
    validate-action at score 1.0. Prior-bound unbound roots still deny SG-03.
    """
    require_verifiable_trust_log(program_root)
    route = route_for_action(program_root, action)
    swift_path = find_corp_gov_check()
    bound = resolve_program_root(factory_root) is not None
    # Bound root always forces heavy_validate even at score 1.0 / light band.
    force_heavy_validate = bound or route["action_routed_layer"] == "heavy"
    bound_blocks_sg03 = not sg03_soft_fail_allowed(
        factory_root=factory_root, program_root=program_root
    )
    if not force_heavy_validate:
        if bound_blocks_sg03 and swift_path is None:
            raise ContractError(
                f"{GOV_REQUIRED}: action {action!r} requires corp-gov-check "
                "(bound/prior-bound program root; SG-03 not restored)"
            )
        return
    err = require_heavy_available(
        action_routed_layer_value="heavy",
        swift_available=swift_path is not None,
    )
    if err == GOV_REQUIRED:
        raise ContractError(
            f"{GOV_REQUIRED}: action {action!r} requires corp-gov-check "
            + (
                "(bound program root forces heavy_validate)"
                if bound and route["action_routed_layer"] != "heavy"
                else "(routed heavy but corp-gov-check missing)"
            )
        )
    payload, code = run_gov_command(
        "validate-action",
        program_root,
        action=action if action != "check_apply" else "heavy_validate",
    )
    if not payload.get("ok") or code != 0:
        raise ContractError(
            f"{GOV_REQUIRED}: heavy validate-action failed for {action!r}: "
            f"{payload.get('error') or payload.get('detail') or code}"
        )


def _root_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", type=Path, required=True)


def _program_path(root: Path) -> Path:
    return root.expanduser().resolve() / "program.json"


def _load_program(root: Path) -> Program:
    path = _program_path(root)
    if not path.is_file():
        raise ContractError(f"program does not exist: {path}")
    return Program.load(path)


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    sys.exit(main())
