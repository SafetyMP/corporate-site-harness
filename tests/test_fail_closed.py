"""Fail-closed runtime: ACC-FC bind, deny, sealed orders, telemetry, mandates."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from corp_harness import runtime_engine as tre
from corp_harness.cli import main
from corp_harness.contracts import (
    GATE_EXECUTION,
    VERIFICATION_SCRIPTS_OPTIONAL,
    VERIFICATION_SCRIPTS_REQUIRED,
)
from corp_harness.evidence import SAFE_ENV_KEYS, run_evidence
from corp_harness.execution_policy import (
    DENIAL_CHILD_PROSE_EVIDENCE,
    DENIAL_PREMIUM_MODEL_POLICY,
    DENIAL_SAME_SESSION_REVIEWER,
    DENIAL_SEALED_WORK_ORDER,
    DENIAL_SUBCONTRACTOR_CEILING,
    DENIAL_VOIDED_ACTOR,
    attest_model_use,
    collect_admissible_gate_packets,
    default_execution_policy,
    route_model,
    validate_packet_attestation,
    validate_reviewer_evidence,
    validate_reviewer_launch,
    validate_reviewer_prompt,
)
from corp_harness.model import USER_GATED_ARTIFACTS, ContractError, Program, digest_path


@pytest.fixture(autouse=True)
def _isolate_program_root_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(tre.PROGRAM_ROOT_ENV, raising=False)
    monkeypatch.delenv(tre.ACTIVE_PACKET_ENV, raising=False)


def _write(path: Path, value: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return path


def _two_factory_programs(tmp_path: Path) -> tuple[Path, Path, Path]:
    factory = tmp_path / "factory"
    program_a = tmp_path / "fail-closed-runtime"
    sibling = tmp_path / "trust-runtime-residuals"
    factory.mkdir()
    program_a.mkdir()
    sibling.mkdir()
    (factory / "src" / "corp_harness").mkdir(parents=True)
    (factory / "tests").mkdir(parents=True)
    (factory / "corporate" / "plugin" / "corporate-site-harness").mkdir(parents=True)
    Program.create(
        "fail-closed-runtime",
        factory,
        ["platform", "security"],
        program_root=program_a,
        program_kind="factory",
    ).save(program_a / "program.json")
    Program.create(
        "trust-runtime-residuals",
        factory,
        ["platform"],
        program_root=sibling,
        program_kind="factory",
    ).save(sibling / "program.json")
    return factory, program_a, sibling


def _record_factory_auth(
    program: Program, root: Path, factory: Path, surfaces: list[str]
) -> None:
    master = _write(root / "master-spec.md", "# master\n")
    program.record_artifact("master_spec", master, "ceo", root)
    auth = _write(
        root / "factory-authorization.json",
        json.dumps(
            {
                "schema": "corporate-site-factory-authorization/v1",
                "authorized": True,
                "granted_by": "user",
                "granted_at": "2026-08-12T00:00:00Z",
                "program_id": program.program_id,
                "revision": 1,
                "master_spec_sha256": program.artifacts["master_spec"].sha256,
                "factory_root": str(factory.resolve()),
                "authorized_surfaces": surfaces,
            }
        )
        + "\n",
    )
    program.record_artifact("factory_authorization", auth, "user", root)
    program.save(root / "program.json")


def test_FC_006_env_overrides_marker_without_rewrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory, program_a, sibling = _two_factory_programs(tmp_path)
    tre.bind_program_root(factory, sibling)
    marker = factory / tre.PROGRAM_ROOT_MARKER
    marker_before = marker.read_text(encoding="utf-8")
    monkeypatch.setenv(tre.PROGRAM_ROOT_ENV, str(program_a))
    resolved = tre.resolve_program_root(factory)
    assert resolved == program_a.resolve()
    assert marker.read_text(encoding="utf-8") == marker_before
    assert sibling.resolve().as_posix() in marker_before

    monkeypatch.delenv(tre.PROGRAM_ROOT_ENV, raising=False)
    marker.unlink()
    assert tre.prior_binding_established(sibling)
    finding = tre.classify_unbind_program_root_seal_bypass(
        sibling, factory_root=factory
    )
    assert finding is not None
    assert finding["theater_signal_id"] == "seal_bypass_attempt"


def test_FC_007_dirty_scan_scopes_to_active_program(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory, program_a, sibling = _two_factory_programs(tmp_path)
    program = Program.load(program_a / "program.json")
    _record_factory_auth(
        program, program_a, factory, ["src/corp_harness", "AGENTS.md"]
    )
    tre.bind_program_root(factory, sibling)
    monkeypatch.setenv(tre.PROGRAM_ROOT_ENV, str(program_a))
    tre.update_surface_baseline(program_a, factory_root=factory)
    score_before = tre.load_trust_state(program_a).trust_score

    (sibling / "gates.json").write_text('{"sibling": true}\n', encoding="utf-8")
    (factory / "tests" / "sibling_only.py").write_text("# not A's surface\n", encoding="utf-8")
    findings = tre.detect_dirty_surfaces(program_a, factory_root=factory)
    assert findings == []
    assert tre.load_trust_state(program_a).trust_score == score_before

    (factory / "src" / "corp_harness" / "cli.py").write_text("# oob\n", encoding="utf-8")
    factory_oob = tre.detect_dirty_surfaces(program_a, factory_root=factory)
    assert any(
        item.get("theater_signal_id") == "out_of_band_mutation"
        and str(item.get("protected_path") or "").endswith("cli.py")
        for item in factory_oob
    )

    tre.update_surface_baseline(program_a, factory_root=factory)
    (program_a / "program.json").write_text(
        (program_a / "program.json").read_text(encoding="utf-8").replace(
            "fail-closed-runtime", "tampered-id", 1
        ),
        encoding="utf-8",
    )
    corporate_oob = tre.detect_dirty_surfaces(program_a, factory_root=factory)
    assert any(
        item.get("theater_signal_id") == "out_of_band_mutation"
        and item.get("protected_path") == "program.json"
        for item in corporate_oob
    )


def test_FC_008_wrong_root_on_mutating_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    factory, program_a, sibling = _two_factory_programs(tmp_path)
    tre.bind_program_root(factory, sibling)
    marker_before = (factory / tre.PROGRAM_ROOT_MARKER).read_text(encoding="utf-8")
    monkeypatch.setenv(tre.PROGRAM_ROOT_ENV, str(program_a))
    tre.update_surface_baseline(program_a, factory_root=factory)

    status_code = main(["status", "--root", str(program_a)])
    capsys.readouterr()
    assert status_code == 0
    assert (factory / tre.PROGRAM_ROOT_MARKER).read_text(encoding="utf-8") == marker_before

    master = _write(sibling / "master-spec.md", "# other\n")
    apply_code = main(
        [
            "record",
            "--root",
            str(sibling),
            "--artifact",
            "master_spec",
            "--path",
            str(master),
            "--actor",
            "ceo",
            "--apply",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert apply_code == 3
    assert payload["ok"] is False
    assert "wrong_root_operation" in str(payload.get("error") or "")
    assert tre.load_trust_state(sibling).last_event["theater_signal_id"] == (
        "wrong_root_operation"
    )
    assert (factory / tre.PROGRAM_ROOT_MARKER).read_text(encoding="utf-8") == marker_before


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _run_pretooluse_hook(
    factory: Path, payload: dict, program_root: Path
) -> tuple[int, dict]:
    script = _repo_root() / ".cursor" / "hooks" / "trust_report.py"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_repo_root() / "src")
    env[tre.PROGRAM_ROOT_ENV] = str(program_root)
    proc = subprocess.run(
        [sys.executable, str(script), "--event", "preToolUse"],
        input=json.dumps(payload),
        cwd=str(factory),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    body = {}
    if proc.stdout.strip():
        body = json.loads(proc.stdout)
    return proc.returncode, body


def test_FC_001_pretooluse_deny_protected_surfaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live_hooks = json.loads(
        (_repo_root() / ".cursor" / "hooks.json").read_text(encoding="utf-8")
    )
    assert tre.hooks_config_has_pretooluse(live_hooks)
    assert "preToolUse" in tre.REQUIRED_CURSOR_HOOK_EVENTS
    after_only = {
        "version": 1,
        "hooks": {
            "afterFileEdit": [
                {
                    "command": (
                        "python3 .cursor/hooks/trust_report.py --event afterFileEdit"
                    )
                }
            ]
        },
    }
    assert tre.afterfileedit_only_hooks(after_only)
    assert not tre.hooks_config_has_pretooluse(after_only)

    factory, program_a, _sibling = _two_factory_programs(tmp_path)
    (factory / "scripts" / "harness").mkdir(parents=True)
    (factory / "src" / "corp_harness" / "cli.py").write_text("# cli\n", encoding="utf-8")
    (factory / "scripts" / "harness" / "verify.sh").write_text(
        "#!/bin/sh\n", encoding="utf-8"
    )
    (program_a / "gates.json").write_text("{}\n", encoding="utf-8")
    (program_a / "evidence").mkdir()
    (program_a / "evidence" / "digest.json").write_text("{}\n", encoding="utf-8")
    tre.bind_program_root(factory, program_a)
    monkeypatch.setenv(tre.PROGRAM_ROOT_ENV, str(program_a))

    protected = [
        program_a / "program.json",
        program_a / "gates.json",
        program_a / "evidence" / "digest.json",
        factory / "src" / "corp_harness" / "cli.py",
        factory / "scripts" / "harness" / "verify.sh",
        factory / tre.PROGRAM_ROOT_MARKER,
    ]
    for path in protected:
        decision = tre.evaluate_pretooluse(
            factory,
            program_a,
            {"tool_name": "Write", "tool_input": {"path": str(path)}},
        )
        assert decision["permission"] == "deny", path
        assert decision["halt_report"]["verdict"] == "halt_report"

    tre.mint_mutation_permit(program_a, paths=["program.json"], ttl_seconds=60)
    allowed = tre.evaluate_pretooluse(
        factory,
        program_a,
        {"tool_name": "Write", "tool_input": {"path": str(program_a / "program.json")}},
    )
    assert allowed["permission"] == "allow"
    (program_a / "trust-mutation-permit.json").unlink()

    (program_a / tre.ACTIVE_WRITE_SET_FILE).write_text(
        json.dumps({"write_set": ["src/corp_harness/cli.py"]}) + "\n",
        encoding="utf-8",
    )
    covered = tre.evaluate_pretooluse(
        factory,
        program_a,
        {
            "tool_name": "StrReplace",
            "tool_input": {"path": str(factory / "src" / "corp_harness" / "cli.py")},
        },
    )
    assert covered["permission"] == "allow"

    code, body = _run_pretooluse_hook(
        factory,
        {"tool_name": "Write", "tool_input": {"path": str(program_a / "gates.json")}},
        program_a,
    )
    assert code == 2
    assert body.get("permission") == "deny"


def test_FC_002_deny_names_legal_next_or_halt_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory, program_a, _sibling = _two_factory_programs(tmp_path)
    tre.bind_program_root(factory, program_a)
    monkeypatch.setenv(tre.PROGRAM_ROOT_ENV, str(program_a))
    before = (program_a / "program.json").read_bytes()
    decision = tre.evaluate_pretooluse(
        factory,
        program_a,
        {"tool_name": "Write", "tool_input": {"path": str(program_a / "program.json")}},
    )
    assert decision["permission"] == "deny"
    legal = decision.get("legal_next") or []
    for command in tre.LEGAL_NEXT_COMMANDS:
        assert command in legal
        assert command in decision["user_message"]
        assert command in decision["agent_message"]
    halt = decision["halt_report"]
    assert halt["schema"] == tre.HALT_REPORT_SCHEMA
    assert halt["verdict"] == "halt_report"
    assert halt["ok"] is True
    assert halt["digests_unchanged"] is True
    assert (program_a / "program.json").read_bytes() == before


def test_FC_DENY_002_afterfileedit_only_insufficient(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    after_only = {
        "version": 1,
        "hooks": {
            "afterFileEdit": [
                {
                    "command": (
                        "python3 .cursor/hooks/trust_report.py --event afterFileEdit"
                    )
                }
            ],
            "beforeShellExecution": [
                {
                    "command": (
                        "python3 .cursor/hooks/trust_report.py "
                        "--event beforeShellExecution"
                    )
                }
            ],
        },
    }
    assert tre.afterfileedit_only_hooks(after_only)
    factory, program_a, _sibling = _two_factory_programs(tmp_path)
    (factory / ".cursor" / "hooks").mkdir(parents=True)
    (factory / ".cursor" / "hooks.json").write_text(
        json.dumps(after_only) + "\n", encoding="utf-8"
    )
    (factory / ".cursor" / "hooks" / "trust_report.py").write_text(
        "# stub\n", encoding="utf-8"
    )
    assert not tre.required_hooks_intact(factory)
    tre.bind_program_root(factory, program_a)
    monkeypatch.setenv(tre.PROGRAM_ROOT_ENV, str(program_a))
    stub = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "governance"
        / "corp-gov-check-stub"
    )
    monkeypatch.setenv("CORP_GOV_CHECK", str(stub))
    tre.update_surface_baseline(program_a, factory_root=factory)
    (program_a / "program.json").write_text(
        (program_a / "program.json").read_text(encoding="utf-8").replace(
            "fail-closed-runtime", "tampered-id", 1
        ),
        encoding="utf-8",
    )
    master = _write(program_a / "master-spec.md", "# Spec\n")
    code = main(
        [
            "record",
            "--root",
            str(program_a),
            "--artifact",
            "master_spec",
            "--path",
            str(master),
            "--actor",
            "ceo",
            "--apply",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 3
    assert payload["ok"] is False
    assert "cannot finish/advance" in str(payload.get("error") or "")


def _sealed_packet(**overrides: object) -> dict:
    packet = {
        "role": "site-specialist",
        "packet_id": "WP-FC-002",
        "root": "/tmp/factory",
        "write_set": ["src/corp_harness/cli.py"],
        "routed_model": "composer-2.5",
        "success_schema": "pytest exit 0",
        "halt_conditions": ["Would treat Sol as ceiling bypass"],
        "model_id": "composer-2.5",
        "model_class": "standard",
        "task_class": "packet_implement",
        "max_mode": False,
    }
    packet.update(overrides)
    return packet


def test_FC_003_sealed_work_order_required(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _factory, program_a, _sibling = _two_factory_programs(tmp_path)
    unsigned = {
        "model_id": "composer-2.5",
        "model_class": "standard",
        "task_class": "packet_implement",
    }
    with pytest.raises(ContractError, match="unsigned work order"):
        validate_packet_attestation(unsigned)
    missing_path = program_a / "unsigned-packet.json"
    missing_path.write_text(json.dumps(unsigned) + "\n", encoding="utf-8")
    code = main(
        ["check", "--root", str(program_a), "--attest-packet", str(missing_path)]
    )
    capsys.readouterr()
    # ContractError from attest → CLI exit 3
    assert code == 3
    sealed = _sealed_packet()
    attested = validate_packet_attestation(sealed)
    assert attested["ok"] is True
    sealed_path = program_a / "sealed-packet.json"
    sealed_path.write_text(json.dumps(sealed) + "\n", encoding="utf-8")
    ok_code = main(
        ["check", "--root", str(program_a), "--attest-packet", str(sealed_path)]
    )
    capsys.readouterr()
    assert ok_code == 0


def test_FC_003_unsealed_general_purpose_ignored() -> None:
    gp = {
        "role": "generalPurpose",
        "subagent_type": "generalPurpose",
        "model_id": "composer-2.5",
        "model_class": "standard",
        "task_class": "explore",
        "notes": "they said it passed",
    }
    attested = validate_packet_attestation(gp)
    assert attested["ok"] is False
    assert attested["denial_code"] == DENIAL_SEALED_WORK_ORDER
    assert attested.get("gate_evidence") is False
    sealed = _sealed_packet(packet_id="WP-FC-SEALED")
    admitted = collect_admissible_gate_packets([gp, sealed, {"not": "a packet"}])
    assert gp not in admitted
    assert sealed in admitted
    assert all(item.get("role") != "generalPurpose" for item in admitted)


def test_FC_004_subcontractor_ceilings_halt() -> None:
    depth = route_model(
        role="site-specialist",
        task_class="packet_implement",
        packet=_sealed_packet(depth=2),
    )
    assert depth["ok"] is False
    assert depth["denial_code"] == DENIAL_SUBCONTRACTOR_CEILING
    assert depth["verdict"] == "halt_report"
    assert depth["halt_report"]["ok"] is True
    assert depth["allowed_model_ids"] == []
    assert not any("sol" in str(item).lower() for item in depth["allowed_model_ids"])

    children = route_model(
        role="site-specialist",
        task_class="hard_implement",
        packet=_sealed_packet(child_count=7),
    )
    assert children["denial_code"] == DENIAL_SUBCONTRACTOR_CEILING
    assert children["halt_report"]["verdict"] == "halt_report"

    redelegate = route_model(
        role="site-specialist",
        task_class="packet_implement",
        packet=_sealed_packet(worker_redelegate=True),
    )
    assert redelegate["denial_code"] == DENIAL_SUBCONTRACTOR_CEILING
    assert "redelegation" in " ".join(redelegate["reasons"])


def test_FC_004_premium_not_ceiling_bypass() -> None:
    # Remediate without escalation stays standard; Sol is not a ceiling bypass.
    failed = route_model(
        role="site-specialist",
        task_class="remediate",
        failed_standard_attempts=9,
    )
    assert failed["model_class"] == "standard"
    assert not any("sol" in item.lower() for item in failed["allowed_model_ids"])

    refused = attest_model_use(
        model_id="gpt-5.6-sol-max",
        model_class="premium",
        task_class="remediate",
        failed_standard_attempts=9,
    )
    assert refused["ok"] is False
    assert refused["denial_code"] == DENIAL_PREMIUM_MODEL_POLICY

    # USD hard-stop removed: hard_implement still routes premium+escalation
    # required; denial is never PREMIUM_BUDGET_HARD.
    hard = route_model(
        role="site-specialist",
        task_class="hard_implement",
        policy=default_execution_policy(),
        packet=_sealed_packet(),
    )
    assert hard["model_class"] == "premium"
    assert hard["requires_escalation"] is True
    assert hard.get("denial_code") is None
    assert hard.get("denial_code") != "PREMIUM_BUDGET_HARD"


def test_FC_005_light_band_no_gate_skip(tmp_path: Path) -> None:
    _factory, program_a, _sibling = _two_factory_programs(tmp_path)
    digest = digest_path(program_a / "program.json")
    tre.save_trust_state(program_a, tre.synthesize_trust_state(digest))
    state = tre.load_trust_state(program_a)
    assert state.trust_score == Decimal("1.00")
    assert state.execution_layer == "light"
    for control in tre.NAMED_CONTROLS_NOT_SKIPPABLE_BY_TRUST:
        assert tre.light_band_skips_named_control(control) is False
    for action in tre.ALWAYS_FORCE_HEAVY_ACTIONS:
        routed = tre.route_for_action(program_a, action)
        assert routed["action_routed_layer"] == "heavy"
        assert routed["always_force_heavy"] is True
    assert "record_artifact:user_approval" in tre.ALWAYS_FORCE_HEAVY_ACTIONS
    with pytest.raises(ContractError, match="must not skip"):
        tre.refuse_named_control_skip(
            "adversary", skip=True, trust_score=Decimal("1.00")
        )
    with pytest.raises(ContractError, match="must not skip"):
        tre.refuse_named_control_skip(
            "user_approval", skip=True, trust_score=Decimal("1.00")
        )
    with pytest.raises(SystemExit):
        main(["trust", "set-score", "--value", "1.0"])

    program = Program.load(program_a / "program.json")
    program.phase = "AWAITING_USER_APPROVAL"
    issues = program.phase_requirements("AWAITING_USER_APPROVAL")
    assert any("adversary" in item for item in issues)
    with pytest.raises(ContractError):
        program.advance("APPROVED", "user")

    loaded = tre.load_trust_state(program_a)
    tre.save_trust_state(
        program_a,
        tre.TrustState(
            trust_score=Decimal("0.20"),
            execution_layer="heavy",
            program_digest=digest,
            last_event=None,
            updated_at="2020-01-01T00:00:00Z",
            generation=loaded.generation,
        ),
    )
    raw = json.loads((program_a / "program.json").read_text(encoding="utf-8"))
    raw["revision"] = int(raw.get("revision") or 1) + 1
    (program_a / "program.json").write_text(
        json.dumps(raw, indent=2) + "\n", encoding="utf-8"
    )
    rebound = tre.load_trust_state(program_a)
    assert rebound.trust_score == Decimal("0.20")
    assert rebound.pending_rebind_from == digest
    assert rebound.trust_score != Decimal("1.00")


def test_FC_010_locked_mandates_preserved(tmp_path: Path) -> None:
    adr = (_repo_root() / "docs" / "adr" / "ADR-FC-001-fail-closed-runtime.md").read_text(
        encoding="utf-8"
    )
    assert "TR-12" in adr
    assert "premium" in adr.lower()
    cli_text = (_repo_root() / "src" / "corp_harness" / "cli.py").read_text(
        encoding="utf-8"
    )
    assert "set-score" not in cli_text
    for argv in (
        ["trust", "set-score", "--value", "1.0"],
        ["trust", "wipe"],
        ["trust", "amnesty"],
        ["trust", "rebind"],
    ):
        with pytest.raises(SystemExit):
            main(argv)

    factory, program_a, _sibling = _two_factory_programs(tmp_path)
    digest = digest_path(program_a / "program.json")
    with pytest.raises(ContractError, match="amnesty is forbidden"):
        tre.append_trust_log_entry(
            program_a,
            entry_kind="digest_amnesty",
            program_digest=digest,
            payload={"trust_score": 1.0},
        )

    product_root = tmp_path / "product-corp"
    product_root.mkdir()
    Program.create(
        "widget-app",
        factory,
        ["platform"],
        program_root=product_root,
        program_kind="product",
    ).save(product_root / "program.json")
    (factory / "src" / "corp_harness" / "cli.py").write_text("# cli\n", encoding="utf-8")
    (product_root / tre.ACTIVE_WRITE_SET_FILE).write_text(
        json.dumps({"write_set": ["src/corp_harness", "src/corp_harness/cli.py"]})
        + "\n",
        encoding="utf-8",
    )
    tre.mint_mutation_permit(
        product_root, paths=["src/corp_harness/cli.py"], ttl_seconds=60
    )
    denied = tre.evaluate_pretooluse(
        factory,
        product_root,
        {
            "tool_name": "Write",
            "tool_input": {"path": str(factory / "src" / "corp_harness" / "cli.py")},
        },
    )
    assert denied["permission"] == "deny"
    assert denied["verdict"] == "halt_report"

    low = route_model(role="site-specialist", task_class="packet_implement")
    assert low["model_class"] != "premium"
    assert "premium_not_trust_reward" in tre.LOCKED_MANDATES

    harness = _repo_root() / "scripts" / "harness"
    names = {item.name for item in harness.iterdir() if item.is_file()}
    assert VERIFICATION_SCRIPTS_REQUIRED.issubset(names)
    assert names.issubset(VERIFICATION_SCRIPTS_REQUIRED | VERIFICATION_SCRIPTS_OPTIONAL)
    assert "verify.sh" in names
    assert "adversarial.sh" in names


def test_FC_TRUST_002_process_error_label_no_cheat(tmp_path: Path) -> None:
    with pytest.raises(ContractError, match="process-error skip path is not enabled"):
        tre.refuse_process_error_skip(label="process_error", would_skip="adversary")
    with pytest.raises(ContractError, match="process-error skip path is not enabled"):
        tre.apply_kind(Decimal("1.00"), "process_error")
    with pytest.raises(ContractError, match="process-error skip path is not enabled"):
        tre.validate_event_preconditions(
            "process-error", theater_signal_id=None, reasons=["skip seal"]
        )
    with pytest.raises(ContractError, match="process-error skip path is not enabled"):
        tre.refuse_named_control_skip("adversary", process_error=True)

    _factory, program_a, _sibling = _two_factory_programs(tmp_path)
    program = Program.load(program_a / "program.json")
    program.phase = "AWAITING_USER_APPROVAL"
    issues = program.phase_requirements("AWAITING_USER_APPROVAL")
    assert any("missing gate adversary" in item for item in issues)
    with pytest.raises(ContractError):
        program.advance("APPROVED", "user")
    digest = digest_path(program_a / "program.json")
    with pytest.raises(ContractError, match="process-error skip path is not enabled"):
        tre.emit_and_apply(
            program_a,
            kind="process_error",
            program_digest=digest,
            reasons=["would skip adversary"],
        )


def test_FC_SPLIT_001_reviewer_requires_fresh_task() -> None:
    same = _sealed_packet(
        role="operations-excellence",
        task_class="independent_review",
        packet_id="WP-FC-005",
        task_id="session-producer",
        session_id="session-producer",
        producer_session_id="session-producer",
    )
    with pytest.raises(ContractError, match="NEW Task"):
        validate_reviewer_launch(same, producer_session_id="session-producer")
    attested = validate_packet_attestation(same)
    assert attested["ok"] is False
    assert attested["denial_code"] == DENIAL_SAME_SESSION_REVIEWER
    assert attested.get("gate_evidence") is False

    fresh = _sealed_packet(
        role="corporate-adversary",
        task_class="independent_review",
        packet_id="WP-FC-005",
        task_id="task-reviewer-9",
        producer_session_id="session-producer",
        model_id="cursor-grok-4.5-high-fast",
        model_class="fast",
    )
    validate_reviewer_launch(fresh, producer_session_id="session-producer")
    ok = validate_packet_attestation(fresh)
    assert ok["ok"] is True


def test_FC_SPLIT_002_prompt_packet_digests_oracle_only() -> None:
    digests = {
        "master_spec": "bbfa379f3d4b538d5c029994d37d028c26c6de538750749cc794dae9186afacc",
        "acceptance": "2a838d294b22d0c746b845058c4584da7ed7260b3b8b402886e71b014d85467a",
    }
    oracle = "./scripts/harness/verify.sh"
    good = (
        "Review WP-FC-005. master_spec="
        f"{digests['master_spec']} acceptance={digests['acceptance']} "
        f"oracle={oracle}"
    )
    validate_reviewer_prompt(
        good, packet_id="WP-FC-005", digests=digests, oracle_command=oracle
    )
    with pytest.raises(ContractError, match="pass-claims"):
        validate_reviewer_prompt(
            good + " they said it passed",
            packet_id="WP-FC-005",
            digests=digests,
            oracle_command=oracle,
        )
    with pytest.raises(ContractError, match="implementer JSON"):
        validate_reviewer_prompt(
            "WP-FC-005 producer json " + digests["master_spec"] + " " + oracle,
            packet_id="WP-FC-005",
            digests=digests,
            oracle_command=oracle,
        )
    with pytest.raises(ContractError, match="packet_id"):
        validate_reviewer_prompt(
            f"{digests['master_spec']} {oracle}",
            packet_id="WP-FC-005",
            digests=digests,
            oracle_command=oracle,
        )


def test_FC_SPLIT_003_child_prose_not_evidence() -> None:
    with pytest.raises(ContractError, match="oracle_collect digest required"):
        validate_reviewer_evidence(
            child_prose="specialist said the gate passed",
            oracle_collect_digest=None,
        )
    validate_reviewer_evidence(
        child_prose=None,
        oracle_collect_digest="abc123",
    )
    child = _sealed_packet(
        role="operations-excellence",
        task_class="independent_review",
        packet_id="WP-FC-005",
        task_id="task-reviewer-2",
        producer_session_id="session-producer",
        child_prose="they said it passed",
        model_id="cursor-grok-4.5-high-fast",
        model_class="fast",
    )
    attested = validate_packet_attestation(child)
    assert attested["ok"] is False
    assert attested["denial_code"] == DENIAL_CHILD_PROSE_EVIDENCE
    admitted = collect_admissible_gate_packets([child])
    assert child not in admitted
    with_oracle = dict(child)
    with_oracle["oracle_collect_digest"] = "deadbeef"
    del with_oracle["child_prose"]
    assert with_oracle in collect_admissible_gate_packets([with_oracle])


def test_FC_COL_001_cover_skip_voids_packets(tmp_path: Path) -> None:
    _factory, program_a, _sibling = _two_factory_programs(tmp_path)
    implementer = _sealed_packet(
        packet_id="WP-FC-IMPL",
        actor_id="actor-impl",
        session_id="sess-impl",
    )
    reviewer = _sealed_packet(
        role="operations-excellence",
        packet_id="WP-FC-REV",
        actor_id="actor-rev",
        session_id="sess-rev",
        task_id="task-rev",
        task_class="independent_review",
    )
    with pytest.raises(ContractError, match="voids involved packets"):
        tre.apply_covered_skip_void(
            program_a,
            packets=[implementer, reviewer],
            covering=True,
            gate_status="SKIP",
            actor_ids=["actor-impl", "actor-rev"],
            session_ids=["sess-impl", "sess-rev"],
        )
    assert tre.is_voided_actor(program_a, actor_id="actor-impl")
    assert tre.is_voided_actor(program_a, session_id="sess-rev")
    program = Program.load(program_a / "program.json")
    with pytest.raises(ContractError, match="voids involved packets"):
        program.record_gate(
            "corporate_acceptance",
            "SKIP",
            program_a / "missing.json",
            "coo",
            program_a,
        )
    assert "corporate_acceptance" not in program.gates


def test_FC_COL_002_producer_cannot_record_own_gate(tmp_path: Path) -> None:
    _factory, program_a, _sibling = _two_factory_programs(tmp_path)
    program = Program.load(program_a / "program.json")
    auth = _write(program_a / "factory-authorization.json", "{}\n")
    with pytest.raises(ContractError, match="must be produced by user"):
        program.record_artifact(
            "factory_authorization", auth, "site-specialist", program_a
        )
    with pytest.raises(ContractError, match="must be produced by user"):
        program.record_artifact("user_approval", auth, "ceo", program_a)
    assert "factory_authorization" in USER_GATED_ARTIFACTS
    assert "user_approval" in USER_GATED_ARTIFACTS
    program.phase = "CORPORATE_ACCEPTANCE"
    with pytest.raises(ContractError, match="must be reviewed by"):
        program.record_gate(
            "corporate_acceptance",
            "PASS",
            program_a / "report.json",
            "site-specialist",
            program_a,
        )
    model_text = (
        _repo_root() / "src" / "corp_harness" / "model.py"
    ).read_text(encoding="utf-8")
    assert "an artifact producer cannot approve its own work" in model_text
    code = main(
        [
            "record",
            "--root",
            str(program_a),
            "--artifact",
            "factory_authorization",
            "--actor",
            "ceo",
            "--path",
            str(auth),
        ]
    )
    assert code == 3


def test_FC_COL_003_voided_actor_no_rehire_until_user(tmp_path: Path) -> None:
    """TPC-CUT-006: career ledger ignored for route-model; session/self-record still deny."""
    _factory, program_a, _sibling = _two_factory_programs(tmp_path)
    tre.void_involved_packets(
        program_a,
        packets=[
            {
                "packet_id": "WP-VOID",
                "actor_id": "banned-actor",
                "session_id": "banned-session",
            }
        ],
        actor_ids=["banned-actor"],
        session_ids=["banned-session"],
    )
    assert tre.is_voided_actor(program_a, actor_id="banned-actor")
    allowed = route_model(
        role="site-specialist",
        task_class="packet_implement",
        packet=_sealed_packet(
            actor_id="banned-actor",
            session_id="banned-session",
            corporate_root=str(program_a),
        ),
    )
    assert allowed["ok"] is True
    assert allowed.get("denial_code") != DENIAL_VOIDED_ACTOR

    # Reinstate remains user-gated audit API (not a route control).
    with pytest.raises(ContractError, match="unauthorized_actor"):
        tre.reinstate_voided_actor(
            program_a, actor="site-specialist", actor_id="banned-actor"
        )
    tre.reinstate_voided_actor(program_a, actor="user", actor_id="banned-actor")
    assert not tre.is_voided_actor(program_a, actor_id="banned-actor")

    same = _sealed_packet(
        role="operations-excellence",
        task_class="independent_review",
        packet_id="WP-FC-VOID-REV",
        task_id="session-producer",
        session_id="session-producer",
        producer_session_id="session-producer",
        model_id="cursor-grok-4.5-high-fast",
        model_class="fast",
    )
    with pytest.raises(ContractError, match="NEW Task"):
        validate_reviewer_launch(same, producer_session_id="session-producer")
    attested = validate_packet_attestation(same)
    assert attested["ok"] is False
    assert attested["denial_code"] == DENIAL_SAME_SESSION_REVIEWER

    program = Program.load(program_a / "program.json")
    auth = _write(program_a / "factory-authorization.json", "{}\n")
    with pytest.raises(ContractError, match="must be produced by user"):
        program.record_artifact(
            "factory_authorization", auth, "site-specialist", program_a
        )
    with pytest.raises(ContractError, match="must be produced by user"):
        program.record_artifact("user_approval", auth, "ceo", program_a)


def test_FC_SEC_HALT_001_unbind_sibling_or_weaken_approval_halt_report(
    tmp_path: Path,
) -> None:
    factory, program_a, sibling = _two_factory_programs(tmp_path)
    tre.bind_program_root(factory, sibling)
    marker_before = (factory / tre.PROGRAM_ROOT_MARKER).read_text(encoding="utf-8")
    digest_before = digest_path(program_a / "program.json")
    halt = tre.halt_unbind_or_weaken_approval(
        {"unbind_sibling": True, "packet_id": "WP-FC-005"}
    )
    assert halt is not None
    assert halt["verdict"] == "halt_report"
    assert halt["ok"] is True
    assert halt["digests_unchanged"] is True
    routed = route_model(
        role="site-specialist",
        task_class="packet_implement",
        packet=_sealed_packet(weaken_adversary=True),
    )
    assert routed["verdict"] == "halt_report"
    assert routed["halt_report"]["ok"] is True
    assert routed["ok"] is False
    assert (factory / tre.PROGRAM_ROOT_MARKER).read_text(encoding="utf-8") == marker_before
    assert digest_path(program_a / "program.json") == digest_before
    assert "corporate_acceptance" not in Program.load(program_a / "program.json").gates
    assert GATE_EXECUTION["adversary"][1] == ["./scripts/harness/adversarial.sh"]
    assert GATE_EXECUTION["site_verify"][1] == ["./scripts/harness/verify.sh"]


def test_FC_EVIDENCE_001_run_evidence_forwards_program_root_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert tre.PROGRAM_ROOT_ENV in SAFE_ENV_KEYS
    factory, program_a, sibling = _two_factory_programs(tmp_path)
    tre.bind_program_root(factory, sibling)
    marker_before = (factory / tre.PROGRAM_ROOT_MARKER).read_text(encoding="utf-8")
    monkeypatch.setenv(tre.PROGRAM_ROOT_ENV, str(program_a))
    script = factory / "echo-root.sh"
    script.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$CORP_HARNESS_PROGRAM_ROOT\"\n",
        encoding="utf-8",
    )
    os.chmod(script, 0o700)
    result = run_evidence("verify", ["./echo-root.sh"], factory, factory, 10)
    assert result.passed
    assert result.stdout.strip() == str(program_a)
    assert (factory / tre.PROGRAM_ROOT_MARKER).read_text(encoding="utf-8") == marker_before


def test_FC_EVIDENCE_002_leaked_active_packet_write_set_does_not_bypass_deny(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Leaked ops packet write_set must not survive oracle pytest isolation."""
    assert tre.ACTIVE_PACKET_ENV not in SAFE_ENV_KEYS
    factory, program_a, _sibling = _two_factory_programs(tmp_path)
    tre.bind_program_root(factory, program_a)
    monkeypatch.setenv(tre.PROGRAM_ROOT_ENV, str(program_a))
    digest = program_a / "evidence" / "digest.json"
    digest.parent.mkdir(parents=True, exist_ok=True)
    digest.write_text("{}\n", encoding="utf-8")
    packet = tmp_path / "leaked-ops-packet.json"
    packet.write_text(json.dumps({"write_set": ["evidence"]}) + "\n", encoding="utf-8")
    monkeypatch.setenv(tre.ACTIVE_PACKET_ENV, str(packet))
    leaked = tre.evaluate_pretooluse(
        factory,
        program_a,
        {"tool_name": "Write", "tool_input": {"path": str(digest)}},
    )
    assert leaked["permission"] == "allow"
    monkeypatch.delenv(tre.ACTIVE_PACKET_ENV, raising=False)
    isolated = tre.evaluate_pretooluse(
        factory,
        program_a,
        {"tool_name": "Write", "tool_input": {"path": str(digest)}},
    )
    assert isolated["permission"] == "deny"
    assert isolated["halt_report"]["verdict"] == "halt_report"
    root = _repo_root()
    verify = (root / "scripts" / "harness" / "verify.sh").read_text(encoding="utf-8")
    adversarial = (root / "scripts" / "harness" / "adversarial.sh").read_text(
        encoding="utf-8"
    )
    assert "unset CORP_HARNESS_ACTIVE_PACKET" in verify
    assert "unset CORP_HARNESS_ACTIVE_PACKET" in adversarial


def test_FC_SCAN_002_write_set_covers_force_apply_factory_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory, program_a, _sibling = _two_factory_programs(tmp_path)
    program = Program.load(program_a / "program.json")
    _record_factory_auth(
        program, program_a, factory, ["src/corp_harness", "tests"]
    )
    tre.bind_program_root(factory, program_a)
    monkeypatch.setenv(tre.PROGRAM_ROOT_ENV, str(program_a))
    target = factory / "src" / "corp_harness" / "evidence.py"
    target.write_text("# baseline\n", encoding="utf-8")
    tre.update_surface_baseline(program_a, factory_root=factory)
    target.write_text("# packet\n", encoding="utf-8")
    with pytest.raises(ContractError, match="unsigned or preToolUse"):
        tre.run_deferred_dirty_scan(
            program_a, factory_root=factory, program=program, force=True
        )

    covered_root = tmp_path / "covered"
    covered_root.mkdir()
    factory_b, program_b_root, _sib = _two_factory_programs(covered_root)
    program_b = Program.load(program_b_root / "program.json")
    _record_factory_auth(
        program_b, program_b_root, factory_b, ["src/corp_harness", "tests"]
    )
    tre.bind_program_root(factory_b, program_b_root)
    monkeypatch.setenv(tre.PROGRAM_ROOT_ENV, str(program_b_root))
    covered = factory_b / "src" / "corp_harness" / "evidence.py"
    covered.write_text("# baseline\n", encoding="utf-8")
    tre.update_surface_baseline(program_b_root, factory_root=factory_b)
    covered.write_text("# packet\n", encoding="utf-8")
    (program_b_root / tre.ACTIVE_WRITE_SET_FILE).write_text(
        json.dumps({"write_set": ["src/corp_harness/evidence.py"]}) + "\n",
        encoding="utf-8",
    )
    result = tre.run_deferred_dirty_scan(
        program_b_root, factory_root=factory_b, program=program_b, force=True
    )
    assert result["skipped"] is False
    oob = [
        item
        for item in result["reported"]
        if item.get("theater_signal_id") == "out_of_band_mutation"
    ]
    assert oob == []


