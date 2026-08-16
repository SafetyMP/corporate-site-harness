"""Trust-routed runtime: ACC-TR-* / D9 / D10 falsifiable tests."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from test_fail_closed import (
    test_FC_EVIDENCE_001_run_evidence_forwards_program_root_env as _fc_evidence_001,
)
from test_fail_closed import (
    test_FC_EVIDENCE_002_leaked_active_packet_write_set_does_not_bypass_deny as _fc_evidence_002,
)

from corp_harness import runtime_engine as tre
from corp_harness.cli import main
from corp_harness.contracts import ContractError
from corp_harness.execution_policy import route_model
from corp_harness.model import USER_GATED_ARTIFACTS, Program, digest_path
from corp_harness.swift_gov import (
    GOV_ASSIST_UNAVAILABLE,
    GOV_REQUIRED,
    PYTHON_SOLE_WRITER_FILES,
    run_gov_command,
)


@pytest.fixture(autouse=True)
def _isolate_program_root_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(tre.PROGRAM_ROOT_ENV, raising=False)
    monkeypatch.delenv(tre.ACTIVE_PACKET_ENV, raising=False)


def _write(path: Path, value: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return path


def _layout(tmp_path: Path) -> tuple[Path, Path]:
    factory = tmp_path / "factory"
    root = tmp_path / "corporate"
    factory.mkdir()
    root.mkdir()
    (factory / "src" / "corp_harness").mkdir(parents=True)
    (factory / "corporate" / "plugin" / "corporate-site-harness").mkdir(parents=True)
    return factory, root


def _minimal_program(tmp_path: Path) -> tuple[Program, Path, Path]:
    factory, root = _layout(tmp_path)
    program = Program.create(
        "trust-pilot",
        factory,
        ["platform", "quality"],
        program_root=root,
        program_kind="factory",
    )
    program.save(root / "program.json")
    return program, root, factory


# --- D1 / D9 type-algebra (WP-A) ---


def test_TR_D1_001_threshold_boundary() -> None:
    assert tre.execution_layer_for_score(Decimal("0.70")) == "light"
    assert tre.execution_layer_for_score(Decimal("0.69")) == "heavy"


def test_TR_D1_002_success_delta_clamp() -> None:
    assert tre.apply_kind(Decimal("0.98"), "strict_success") == Decimal("1.00")
    assert tre.apply_kind(Decimal("0.70"), "strict_success") == Decimal("0.75")


def test_TR_D1_003_failure_drops_below_threshold() -> None:
    assert tre.apply_kind(Decimal("0.95"), "validation_failure") == Decimal("0.69")
    assert tre.execution_layer_for_score(Decimal("0.69")) == "heavy"


def test_TR_D1_004_theater_zero() -> None:
    assert tre.apply_kind(Decimal("0.80"), "deceptive_theater") == Decimal("0.00")


def test_TR_D1_005_half_up_quantize_boundary() -> None:
    assert tre.quantize_score(Decimal("0.025")) == Decimal("0.03")
    assert tre.quantize_score(Decimal("0.024")) == Decimal("0.02")
    assert tre.execution_layer_for_score(Decimal("0.025")) == "heavy"
    assert tre.quantize_score(Decimal("0.695")) == Decimal("0.70")
    assert tre.execution_layer_for_score(Decimal("0.695")) == "light"


def test_TR_D9_001_closed_kinds_and_score_effects() -> None:
    assert tre.TRUST_EVENT_KINDS == {
        "strict_success",
        "validation_failure",
        "deceptive_theater",
    }
    assert tre.apply_kind(Decimal("0.50"), "strict_success") == Decimal("0.55")
    assert tre.apply_kind(Decimal("0.50"), "validation_failure") == Decimal("0.50")
    assert tre.apply_kind(Decimal("0.90"), "validation_failure") == Decimal("0.69")
    assert tre.apply_kind(Decimal("0.40"), "deceptive_theater") == Decimal("0.00")


def test_TR_D9_002_precondition_fixtures() -> None:
    for signal in sorted(tre.THEATER_SIGNAL_IDS):
        tre.validate_event_preconditions(
            "deceptive_theater", theater_signal_id=signal, reasons=["r"]
        )
    with pytest.raises(ContractError):
        tre.validate_event_preconditions(
            "deceptive_theater", theater_signal_id="nope", reasons=["r"]
        )
    with pytest.raises(ContractError):
        tre.validate_event_preconditions(
            "validation_failure", theater_signal_id=None, reasons=[]
        )


def test_TR_D9_005_theater_signal_and_emitter(tmp_path: Path) -> None:
    _, root, _ = _minimal_program(tmp_path)
    digest = digest_path(root / "program.json")
    with pytest.raises(ContractError):
        tre.build_trust_event(
            kind="deceptive_theater",
            program_digest=digest,
            score_before=Decimal("1"),
            score_after=Decimal("0"),
            theater_signal_id="not_a_signal",
            reasons=["x"],
        )
    event = tre.build_trust_event(
        kind="strict_success",
        program_digest=digest,
        score_before=Decimal("1"),
        score_after=Decimal("1"),
        emitter=tre.SOLE_EMITTER,
    )
    assert event["emitter"] == tre.SOLE_EMITTER
    proposed = {
        "kind": "validation_failure",
        "emitter": tre.SWIFT_PROPOSE_ONLY,
        "reasons": ["bad"],
    }
    state = tre.emit_and_apply(
        root,
        kind="validation_failure",
        program_digest=digest,
        proposed_by_swift=proposed,
        reasons=["bad"],
    )
    assert state.last_event is not None
    assert state.last_event["emitter"] == tre.SOLE_EMITTER


def test_TR_D9_006_digest_rebind_forbidden_as_trust_event_kind() -> None:
    assert "digest_amnesty" not in tre.TRUST_EVENT_KINDS
    assert "amnesty" not in tre.TRUST_EVENT_KINDS
    with pytest.raises(ContractError):
        tre.apply_kind(Decimal("1"), "digest_amnesty")


# --- H3 / D3 / CLI / D7 / D9 ordering (WP-B) ---


def test_TR_H3_001_true_genesis_ungated_ok(tmp_path: Path) -> None:
    _, root, _ = _minimal_program(tmp_path)
    assert not (root / "trust-state.json").exists()
    assert tre.is_true_genesis(root)
    code = main(["status", "--root", str(root)])
    assert code == 0
    # synthesize does not persist until mutating apply
    assert not (root / "trust-state.json").exists()


# Back-compat alias if anything still imports the old node name.
test_TR_H3_001_missing_trust_state_ungated_ok = test_TR_H3_001_true_genesis_ungated_ok


def test_TR_H3_002_score_1_0_ungated_ok(tmp_path: Path) -> None:
    _, root, _ = _minimal_program(tmp_path)
    digest = digest_path(root / "program.json")
    tre.save_trust_state(root, tre.synthesize_trust_state(digest))
    route = tre.route_for_action(root, "record_artifact:other")
    assert route["action_routed_layer"] == "light"
    code = main(["status", "--root", str(root)])
    assert code == 0


def test_TR_D3_001_digest_mismatch_rebind_preserves_score(tmp_path: Path) -> None:
    _, root, _ = _minimal_program(tmp_path)
    tre.save_trust_state(
        root,
        tre.TrustState(
            trust_score=Decimal("0.20"),
            execution_layer="heavy",
            program_digest="0" * 64,
            last_event={"kind": "validation_failure", "event_id": "old"},
            updated_at="2020-01-01T00:00:00Z",
        ),
    )
    state = tre.load_trust_state(root)
    assert state.trust_score == Decimal("0.20")
    assert state.execution_layer == "heavy"
    assert state.last_event == {"kind": "validation_failure", "event_id": "old"}
    assert state.program_digest == digest_path(root / "program.json")
    assert state.pending_rebind_from == "0" * 64
    assert not (root / "trust-event-log.jsonl").exists()


def test_TR_CLI_001_status_emits_trust_fields(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, root, _ = _minimal_program(tmp_path)
    main(["status", "--root", str(root)])
    payload = json.loads(capsys.readouterr().out)
    assert payload["trust_score"] == 1.0
    assert payload["execution_layer"] == "light"
    assert payload["last_event"] is None


def test_TR_ORTHO_001_route_model_unaffected_by_trust_score(tmp_path: Path) -> None:
    _, root, _ = _minimal_program(tmp_path)
    digest = digest_path(root / "program.json")
    tre.emit_and_apply(
        root,
        kind="deceptive_theater",
        program_digest=digest,
        theater_signal_id="vacuous_gate_pass",
        reasons=["theater"],
    )
    before = route_model(role="site-specialist", task_class="packet_implement")
    after_state = tre.load_trust_state(root)
    assert after_state.trust_score == Decimal("0.00")
    after = route_model(role="site-specialist", task_class="packet_implement")
    assert before["model_class"] == after["model_class"]
    assert before["allowed_model_ids"] == after["allowed_model_ids"]


def test_TR_D7_001_trust_state_rejects_lost_update(tmp_path: Path) -> None:
    _, root, _ = _minimal_program(tmp_path)
    digest = digest_path(root / "program.json")
    first = tre.synthesize_trust_state(digest)
    tre.save_trust_state(root, first)
    assert first.generation == 1
    stale = tre.TrustState(
        trust_score=Decimal("0.50"),
        execution_layer="heavy",
        program_digest=digest,
        last_event=None,
        updated_at="2020-01-01T00:00:00Z",
        generation=0,
    )
    with pytest.raises(ContractError, match="trust-state changed concurrently"):
        tre.save_trust_state(root, stale)
    loaded = tre.load_trust_state(root)
    assert loaded.generation == 1
    assert loaded.trust_score == Decimal("1.00")


def test_TR_D7_002_stale_trust_state_rebind_preserves_score_after_program_save(
    tmp_path: Path,
) -> None:
    program, root, _ = _minimal_program(tmp_path)
    digest = digest_path(root / "program.json")
    tre.emit_and_apply(
        root,
        kind="validation_failure",
        program_digest=digest,
        reasons=["x"],
    )
    assert tre.load_trust_state(root).trust_score == Decimal("0.69")
    prior_event = tre.load_trust_state(root).last_event
    master = _write(root / "master-spec.md", "# master\n")
    program.record_artifact("master_spec", master, "ceo", root)
    program.save(root / "program.json")
    state = tre.load_trust_state(root)
    assert state.trust_score == Decimal("0.69")
    assert state.execution_layer == "heavy"
    assert state.last_event == prior_event
    assert state.program_digest == digest_path(root / "program.json")
    assert state.pending_rebind_from == digest


def test_TR_D9_003_ordering_rejected_theater_no_program_write(tmp_path: Path) -> None:
    _, root, _ = _minimal_program(tmp_path)
    before = digest_path(root / "program.json")
    tre.emit_and_apply(
        root,
        kind="deceptive_theater",
        program_digest=before,
        theater_signal_id="seal_bypass_attempt",
        reasons=["bypass"],
    )
    assert digest_path(root / "program.json") == before
    assert tre.load_trust_state(root).trust_score == Decimal("0.00")


def test_TR_D9_003_ordering_accepted_mutating_after_save(tmp_path: Path) -> None:
    program, root, _ = _minimal_program(tmp_path)
    master = _write(root / "master-spec.md", "# m\n")
    program.record_artifact("master_spec", master, "ceo", root)
    program.save(root / "program.json")
    post = digest_path(root / "program.json")
    state = tre.emit_and_apply(root, kind="strict_success", program_digest=post)
    assert state.last_event is not None
    assert state.last_event["program_digest"] == post


def test_TR_D9_003_ordering_validate_only(tmp_path: Path) -> None:
    _, root, _ = _minimal_program(tmp_path)
    before = digest_path(root / "program.json")
    tre.emit_and_apply(
        root,
        kind="strict_success",
        program_digest=before,
    )
    assert digest_path(root / "program.json") == before


def test_TR_D9_003_requires_heavy_intermediate_no_event_final_emits(
    tmp_path: Path,
) -> None:
    """TPC-COURT-001: score/band telemetry must not force action_routed_layer."""
    _, root, _ = _minimal_program(tmp_path)
    digest = digest_path(root / "program.json")
    tre.save_trust_state(
        root,
        tre.TrustState(
            trust_score=Decimal("0.69"),
            execution_layer="heavy",
            program_digest=digest,
            last_event=None,
            updated_at="2020-01-01T00:00:00Z",
        ),
    )
    route = tre.route_for_action(root, "record_artifact:other")
    assert route["execution_layer"] == "heavy"
    assert route["trust_score"] == 0.69
    assert route["action_routed_layer"] == "light"
    # Intermediate route consult emits no TrustEvent
    assert tre.load_trust_state(root).last_event is None
    # Final mutating apply still emits when writer path runs.
    state = tre.emit_and_apply(
        root, kind="strict_success", program_digest=digest, event_id="d9-003-final"
    )
    assert state.last_event is not None
    assert state.last_event["kind"] == "strict_success"


test_TR_D9_003_requires_heavy_no_event = (
    test_TR_D9_003_requires_heavy_intermediate_no_event_final_emits
)


def test_TR_D9_004_non_events_surfaces(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, root, _ = _minimal_program(tmp_path)
    stub = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "governance"
        / "corp-gov-check-stub"
    )
    monkeypatch.setenv("CORP_GOV_CHECK", str(stub))

    main(["status", "--root", str(root)])
    capsys.readouterr()
    main(
        [
            "route-model",
            "--root",
            str(root),
            "--role",
            "site-specialist",
            "--task-class",
            "explore",
        ]
    )
    capsys.readouterr()
    main(["check", "--root", str(root)])
    capsys.readouterr()

    master = _write(root / "master-spec.md", "# Spec\n")
    main(
        [
            "record",
            "--root",
            str(root),
            "--artifact",
            "master_spec",
            "--path",
            str(master),
            "--actor",
            "ceo",
        ]
    )
    dry_payload = json.loads(capsys.readouterr().out)
    assert dry_payload["apply"] is False

    code = main(["gov", "diagnose", "--root", str(root)])
    assist_payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert assist_payload["mutation"] is False
    assert assist_payload["command"] == "diagnose"

    assert not (root / "trust-state.json").exists()


def test_TR_D9_007_last_event_schema_idempotency(tmp_path: Path) -> None:
    _, root, _ = _minimal_program(tmp_path)
    digest = digest_path(root / "program.json")
    eid = "evt-fixed-1"
    s1 = tre.emit_and_apply(
        root, kind="strict_success", program_digest=digest, event_id=eid
    )
    s2 = tre.emit_and_apply(
        root, kind="strict_success", program_digest=digest, event_id=eid
    )
    assert s1.trust_score == s2.trust_score == Decimal("1.00")
    assert s2.last_event is not None
    assert s2.last_event["event_id"] == eid
    assert s2.last_event["schema"] == tre.TRUST_EVENT_SCHEMA


def test_TR_D10_006_status_dry_run_display_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, root, _ = _minimal_program(tmp_path)
    main(["status", "--root", str(root)])
    payload = json.loads(capsys.readouterr().out)
    assert payload["trust_score"] == 1.0
    assert payload["execution_layer"] == "light"
    assert payload["last_event"] is None
    assert not (root / "trust-state.json").exists()

    master = _write(root / "master-spec.md", "# Spec\n")
    main(
        [
            "record",
            "--root",
            str(root),
            "--artifact",
            "master_spec",
            "--path",
            str(master),
            "--actor",
            "ceo",
        ]
    )
    dry_payload = json.loads(capsys.readouterr().out)
    assert dry_payload["apply"] is False
    assert dry_payload["trust_score"] == 1.0
    assert dry_payload["execution_layer"] == "light"
    assert dry_payload["last_event"] is None
    assert not (root / "trust-state.json").exists()

    main(
        [
            "record",
            "--root",
            str(root),
            "--artifact",
            "master_spec",
            "--path",
            str(master),
            "--actor",
            "ceo",
            "--apply",
        ]
    )
    apply_payload = json.loads(capsys.readouterr().out)
    assert apply_payload["apply"] is True
    assert apply_payload["trust_score"] == 1.0
    assert apply_payload["execution_layer"] == "light"
    assert apply_payload["last_event"]["kind"] == "strict_success"
    assert (root / "trust-state.json").is_file()
    persisted = json.loads((root / "trust-state.json").read_text(encoding="utf-8"))
    assert persisted["last_event"]["kind"] == "strict_success"


def test_TR_D10_007_atomic_persist_score_layer_last_event(tmp_path: Path) -> None:
    _, root, _ = _minimal_program(tmp_path)
    digest = digest_path(root / "program.json")
    state = tre.emit_and_apply(
        root,
        kind="validation_failure",
        program_digest=digest,
        reasons=["x"],
    )
    raw = json.loads((root / "trust-state.json").read_text(encoding="utf-8"))
    assert raw["trust_score"] == float(state.trust_score)
    assert raw["execution_layer"] == "heavy"
    assert raw["last_event"]["kind"] == "validation_failure"
    assert raw["program_digest"] == digest
    assert "updated_at" in raw


def test_TR_D10_008_forbidden_trust_set_score_cheat_paths() -> None:
    parser_help = Path(__file__).resolve().parents[1] / "src" / "corp_harness" / "cli.py"
    text = parser_help.read_text(encoding="utf-8")
    assert "trust set-score" not in text
    assert "set-score" not in text
    with pytest.raises(SystemExit):
        main(["trust", "set-score", "--value", "1.0"])


# --- Heavy / FG-001 / D10 consequences (WP-C) ---


def test_TR_D6_001_heavy_missing_gov_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TPC-COURT-001: heavy score band does not route heavy; light soft-fails gov."""
    _, root, _ = _minimal_program(tmp_path)
    digest = digest_path(root / "program.json")
    tre.save_trust_state(
        root,
        tre.TrustState(
            trust_score=Decimal("0.69"),
            execution_layer="heavy",
            program_digest=digest,
            last_event=None,
            updated_at="2020-01-01T00:00:00Z",
        ),
    )
    monkeypatch.setenv("CORP_GOV_CHECK", str(tmp_path / "missing-binary"))
    route = tre.route_for_action(root, "record_artifact:other")
    assert route["execution_layer"] == "heavy"
    assert route["action_routed_layer"] == "light"
    err = tre.require_heavy_available(
        action_routed_layer_value=route["action_routed_layer"],
        swift_available=False,
    )
    assert err is None


def test_TR_D6_002_fg001_missing_gov_required(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, root, _ = _minimal_program(tmp_path)
    route = tre.route_for_action(root, "record_artifact:gates")
    assert route["action_routed_layer"] == "heavy"
    err = tre.require_heavy_available(
        action_routed_layer_value=route["action_routed_layer"],
        swift_available=False,
    )
    assert err == tre.GOV_REQUIRED
    monkeypatch.setenv("CORP_GOV_CHECK", str(tmp_path / "nope"))


def test_TR_D6_003_bound_root_light_missing_gov_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TPC-PIPE-001: bound root does not force heavy_validate / GOV_REQUIRED."""
    from corp_harness.cli import _enforce_trust_route

    _, root, factory = _minimal_program(tmp_path)
    digest = digest_path(root / "program.json")
    tre.save_trust_state(root, tre.synthesize_trust_state(digest))
    tre.bind_program_root(factory, root, seed_baseline=False)
    monkeypatch.setenv(tre.PROGRAM_ROOT_ENV, str(root))
    monkeypatch.setenv("CORP_GOV_CHECK", str(tmp_path / "missing-corp-gov-check"))
    assert tre.program_root_is_bound(factory)
    assert tre.heavy_validate_forced(root, factory_root=factory) is False
    assert tre.route_for_action(root, "record_artifact:other")["action_routed_layer"] == "light"
    # Light apply on bound root: no heavy_validate theater / GOV_REQUIRED.
    _enforce_trust_route(root, "record_artifact:other", factory_root=factory)


def test_TR_D6_004_heavy_empty_stdout_gov_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from corp_harness.swift_gov import run_gov_command

    stub = tmp_path / "empty-stdout-gov"
    stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    stub.chmod(0o700)
    monkeypatch.setenv("CORP_GOV_CHECK", str(stub))
    _, root, _ = _minimal_program(tmp_path)
    payload, code = run_gov_command(
        "validate-action", root, action="heavy_validate"
    )
    assert code == 2
    assert payload["error"] == tre.GOV_REQUIRED
    assert payload["assist"] is False


def test_TR_D6_005_unbound_root_light_sg03_preserved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, root, factory = _minimal_program(tmp_path)
    monkeypatch.delenv(tre.PROGRAM_ROOT_ENV, raising=False)
    marker = factory / tre.PROGRAM_ROOT_MARKER
    if marker.is_file():
        marker.unlink()
    assert not tre.program_root_is_bound(factory)
    monkeypatch.setenv("CORP_GOV_CHECK", str(tmp_path / "missing-corp-gov-check"))
    code = main(["gov", "diagnose", "--root", str(root)])
    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload["error"] == GOV_ASSIST_UNAVAILABLE
    assert payload["assist"] is True
    assert not tre.heavy_validate_forced(root, factory_root=factory)


def test_TR_FG001_001_seal_always_gated_at_score_1_0(tmp_path: Path) -> None:
    _, root, _ = _minimal_program(tmp_path)
    digest = digest_path(root / "program.json")
    tre.save_trust_state(root, tre.synthesize_trust_state(digest))
    for action in tre.ALWAYS_FORCE_HEAVY_ACTIONS:
        assert tre.route_for_action(root, action)["action_routed_layer"] == "heavy"


def test_TR_FG001_002_heavy_validate_skipped_at_score_1_0_unbound_root(
    tmp_path: Path,
) -> None:
    """Unbound score 1.0: heavy_validate gate skipped for light non-seal applies."""
    _, root, factory = _minimal_program(tmp_path)
    digest = digest_path(root / "program.json")
    tre.save_trust_state(root, tre.synthesize_trust_state(digest))
    assert tre.HEAVY_VALIDATE_ACTION not in tre.ALWAYS_FORCE_HEAVY_ACTIONS
    assert not tre.program_root_is_bound(factory)
    assert tre.route_for_action(root, "record_artifact:other")["action_routed_layer"] == "light"
    assert not tre.heavy_validate_forced(root, factory_root=factory)
    # Explicit heavy_validate action remains heavy when invoked.
    assert tre.route_for_action(root, tre.HEAVY_VALIDATE_ACTION)["action_routed_layer"] == "heavy"


def test_TR_FG001_003_heavy_validate_forced_when_root_bound(tmp_path: Path) -> None:
    """TPC-PIPE-001: bound root alone must not force heavy_validate."""
    _, root, factory = _minimal_program(tmp_path)
    digest = digest_path(root / "program.json")
    tre.save_trust_state(root, tre.synthesize_trust_state(digest))
    tre.bind_program_root(factory, root, seed_baseline=False)
    assert tre.program_root_is_bound(factory)
    assert tre.route_for_action(root, "record_artifact:other")["action_routed_layer"] == "light"
    assert tre.heavy_validate_forced(root, factory_root=factory) is False
    # Explicit heavy_validate / FG-001 seals remain heavy when invoked.
    assert tre.route_for_action(root, tre.HEAVY_VALIDATE_ACTION)["action_routed_layer"] == "heavy"
    for action in tre.ALWAYS_FORCE_HEAVY_ACTIONS:
        assert tre.route_for_action(root, action)["action_routed_layer"] == "heavy"


test_TR_FG001_002_heavy_validate_skipped_at_score_1_0 = (
    test_TR_FG001_002_heavy_validate_skipped_at_score_1_0_unbound_root
)


def test_TR_D10_001_validation_failure_forces_heavy_on_next_apply(tmp_path: Path) -> None:
    """TPC-COURT-001: validation_failure updates court telemetry, not route layer."""
    _, root, _ = _minimal_program(tmp_path)
    digest = digest_path(root / "program.json")
    tre.emit_and_apply(
        root, kind="validation_failure", program_digest=digest, reasons=["fail"]
    )
    assert tre.load_trust_state(root).execution_layer == "heavy"
    assert tre.route_for_action(root, "record_artifact:other")["action_routed_layer"] == "light"


def test_TR_D10_002_deceptive_theater_forces_heavy_on_next_apply(tmp_path: Path) -> None:
    """TPC-COURT-001: theater zeros score telemetry but does not force heavy route."""
    _, root, _ = _minimal_program(tmp_path)
    digest = digest_path(root / "program.json")
    tre.emit_and_apply(
        root,
        kind="deceptive_theater",
        program_digest=digest,
        theater_signal_id="unbound_kpi",
        reasons=["kpi"],
    )
    assert tre.load_trust_state(root).trust_score == Decimal("0.00")
    assert tre.route_for_action(root, "check_apply")["action_routed_layer"] == "light"


def test_TR_D10_003_fourteen_strict_success_recovers_light(tmp_path: Path) -> None:
    _, root, _ = _minimal_program(tmp_path)
    digest = digest_path(root / "program.json")
    tre.save_trust_state(
        root,
        tre.TrustState(
            trust_score=Decimal("0.00"),
            execution_layer="heavy",
            program_digest=digest,
            last_event=None,
            updated_at="2020-01-01T00:00:00Z",
        ),
    )
    for _ in range(14):
        digest = digest_path(root / "program.json")
        tre.emit_and_apply(root, kind="strict_success", program_digest=digest)
    state = tre.load_trust_state(root)
    assert state.trust_score == Decimal("0.70")
    assert state.execution_layer == "light"
    assert tre.route_for_action(root, "record_artifact:other")["action_routed_layer"] == "light"


def test_TR_D10_003b_thirteen_strict_success_still_heavy(tmp_path: Path) -> None:
    _, root, _ = _minimal_program(tmp_path)
    digest = digest_path(root / "program.json")
    tre.save_trust_state(
        root,
        tre.TrustState(
            trust_score=Decimal("0.00"),
            execution_layer="heavy",
            program_digest=digest,
            last_event=None,
            updated_at="2020-01-01T00:00:00Z",
        ),
    )
    for _ in range(13):
        tre.emit_and_apply(
            root,
            kind="strict_success",
            program_digest=digest_path(root / "program.json"),
        )
    state = tre.load_trust_state(root)
    assert state.trust_score == Decimal("0.65")
    assert state.execution_layer == "heavy"


def test_TR_D10_004_always_force_heavy_at_score_1_0(tmp_path: Path) -> None:
    test_TR_FG001_001_seal_always_gated_at_score_1_0(tmp_path)


def test_TR_D10_005_missing_swift_at_0_69_gov_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    test_TR_D6_001_heavy_missing_gov_required(tmp_path, monkeypatch)


def test_TR_D10_005b_unbound_light_ungated_assist_sg03(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, root, factory = _minimal_program(tmp_path)
    monkeypatch.delenv(tre.PROGRAM_ROOT_ENV, raising=False)
    monkeypatch.delenv("CORP_GOV_CHECK", raising=False)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("CORP_GOV_CHECK", str(tmp_path / "missing-corp-gov-check"))
    assert not tre.program_root_is_bound(factory)

    before_digest = digest_path(root / "program.json")
    assert not (root / "trust-state.json").exists()

    code = main(["gov", "diagnose", "--root", str(root)])
    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload["error"] == GOV_ASSIST_UNAVAILABLE
    assert payload["assist"] is True
    assert payload["mutation"] is False
    assert payload["command"] == "diagnose"
    assert digest_path(root / "program.json") == before_digest
    assert not (root / "trust-state.json").exists()

    assert main(["status", "--root", str(root)]) in {0, 1}
    status_payload = json.loads(capsys.readouterr().out)
    assert status_payload["trust_score"] == 1.0
    assert status_payload["execution_layer"] == "light"
    assert not (root / "trust-state.json").exists()


test_TR_D10_005b_light_ungated_assist_sg03 = (
    test_TR_D10_005b_unbound_light_ungated_assist_sg03
)


def test_TR_D10_005c_bound_root_light_gov_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    test_TR_D6_003_bound_root_light_missing_gov_required(tmp_path, monkeypatch)


def test_TR_sole_writer_validate_action_non_mutation(tmp_path: Path) -> None:
    from corp_harness.swift_gov import build_validate_action_payload

    _, root, _ = _minimal_program(tmp_path)
    before = digest_path(root / "program.json")
    payload = build_validate_action_payload(root, "heavy_validate")
    assert payload["mutation"] is False
    assert payload["program_digest"] == before
    assert digest_path(root / "program.json") == before
    assert payload["verdict"] == "accept"


# --- Trust event log writer / D3 rebind (WP-TR-LOG-A) ---


def _read_log(root: Path) -> list[dict]:
    path = root / "trust-event-log.jsonl"
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def test_TR_LOG_001_applied_event_appends_trust_event_line(tmp_path: Path) -> None:
    _, root, _ = _minimal_program(tmp_path)
    digest = digest_path(root / "program.json")
    eid = "log-001-event"
    state = tre.emit_and_apply(
        root, kind="strict_success", program_digest=digest, event_id=eid
    )
    lines = _read_log(root)
    assert len(lines) == 1
    entry = lines[0]
    assert entry["schema"] == tre.TRUST_LOG_ENTRY_SCHEMA
    assert entry["entry_kind"] == "trust_event"
    assert entry["prev_hash"] == tre.GENESIS_PREV_HASH
    assert entry["entry_hash"]
    assert entry["seq"] == 1
    assert entry["payload"]["event"]["event_id"] == eid
    assert entry["entry_hash"] == tre.canonical_log_entry_hash(
        {k: v for k, v in entry.items() if k != "entry_hash"}
    )
    anchor = json.loads((root / "trust-log-anchor.json").read_text(encoding="utf-8"))
    assert anchor["schema"] == tre.TRUST_LOG_ANCHOR_SCHEMA
    assert anchor["first_entry_hash"] == entry["entry_hash"]
    assert anchor["program_id"] == "trust-pilot"
    assert state.log_tip_hash == entry["entry_hash"]
    assert state.log_seq == 1
    persisted = json.loads((root / "trust-state.json").read_text(encoding="utf-8"))
    assert persisted["log_tip_hash"] == entry["entry_hash"]
    assert persisted["log_seq"] == 1


def test_TR_LOG_002_duplicate_event_id_no_append(tmp_path: Path) -> None:
    _, root, _ = _minimal_program(tmp_path)
    digest = digest_path(root / "program.json")
    eid = "log-002-dup"
    s1 = tre.emit_and_apply(
        root,
        kind="validation_failure",
        program_digest=digest,
        reasons=["once"],
        event_id=eid,
        protected_path="program.json",
        content_hash="content-a",
    )
    s2 = tre.emit_and_apply(
        root,
        kind="validation_failure",
        program_digest=digest,
        reasons=["once"],
        event_id=eid,
        protected_path="program.json",
        content_hash="content-a",
    )
    assert s1.trust_score == s2.trust_score == Decimal("0.69")
    lines = _read_log(root)
    assert len(lines) == 1
    assert lines[0]["payload"]["event"]["event_id"] == eid


def test_TR_D9_007b_fingerprint_mismatch_requires_new_event_id(tmp_path: Path) -> None:
    _, root, _ = _minimal_program(tmp_path)
    digest = digest_path(root / "program.json")
    eid = "log-007b-same-id"
    tre.emit_and_apply(
        root,
        kind="validation_failure",
        program_digest=digest,
        reasons=["first"],
        event_id=eid,
        protected_path="program.json",
        content_hash="hash-one",
    )
    with pytest.raises(ContractError, match="fingerprint mismatch requires a new event_id"):
        tre.emit_and_apply(
            root,
            kind="validation_failure",
            program_digest=digest,
            reasons=["second"],
            event_id=eid,
            protected_path="program.json",
            content_hash="hash-two",
        )
    assert len(_read_log(root)) == 1
    assert tre.load_trust_state(root).trust_score == Decimal("0.69")


def test_TR_LOG_003_non_events_do_not_append(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ACC-TR-LOG-003 LOG-scoped half: non-events must not append or mutate.

    Dirty deferred anti-harness half (test_TR_AH_007_*) is WP-TR-AH-A/C;
    G-TR-LOG-NON-EVENTS stays partial until that node exists.
    """
    _, root, _ = _minimal_program(tmp_path)
    stub = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "governance"
        / "corp-gov-check-stub"
    )
    monkeypatch.setenv("CORP_GOV_CHECK", str(stub))
    digest = digest_path(root / "program.json")
    tre.emit_and_apply(
        root,
        kind="validation_failure",
        program_digest=digest,
        reasons=["seed"],
        event_id="log-003-seed",
    )
    log_path = root / "trust-event-log.jsonl"
    state_path = root / "trust-state.json"
    anchor_path = root / "trust-log-anchor.json"
    before_log = log_path.read_text(encoding="utf-8")
    before_state = state_path.read_text(encoding="utf-8")
    before_anchor = anchor_path.read_text(encoding="utf-8")
    before_lines = len(_read_log(root))
    assert before_lines == 1

    # Clean status (display-only; dirty deferred scan is AH, not this node).
    assert main(["status", "--root", str(root)]) in {0, 1}
    capsys.readouterr()

    # corp-harness trust log is read-only / non-event when chain ok.
    assert main(["trust", "log", "--root", str(root), "--verify-chain"]) == 0
    log_payload = json.loads(capsys.readouterr().out)
    assert log_payload["ok"] is True
    assert log_payload["chain_ok"] is True

    # Other LOG-scoped non-event surfaces from ADR-TR-002 §8 / ACC-TR-LOG-003.
    assert (
        main(
            [
                "route-model",
                "--root",
                str(root),
                "--role",
                "site-specialist",
                "--task-class",
                "explore",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["check", "--root", str(root)]) in {0, 1}
    capsys.readouterr()

    master = _write(root / "master-spec.md", "# Spec\n")
    dry_code = main(
        [
            "record",
            "--root",
            str(root),
            "--artifact",
            "master_spec",
            "--path",
            str(master),
            "--actor",
            "ceo",
        ]
    )
    dry_payload = json.loads(capsys.readouterr().out)
    assert dry_code == 0
    assert dry_payload["apply"] is False

    assist_code = main(["gov", "diagnose", "--root", str(root)])
    assist_payload = json.loads(capsys.readouterr().out)
    assert assist_code == 0
    assert assist_payload["mutation"] is False

    assert log_path.read_text(encoding="utf-8") == before_log
    assert state_path.read_text(encoding="utf-8") == before_state
    assert anchor_path.read_text(encoding="utf-8") == before_anchor
    assert len(_read_log(root)) == before_lines


def test_TR_LOG_004_digest_rebind_appends_on_writer_not_status(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, root, _ = _minimal_program(tmp_path)
    tre.save_trust_state(
        root,
        tre.TrustState(
            trust_score=Decimal("0.20"),
            execution_layer="heavy",
            program_digest="0" * 64,
            last_event={"kind": "validation_failure", "event_id": "stale"},
            updated_at="2020-01-01T00:00:00Z",
        ),
    )
    assert main(["status", "--root", str(root)]) in {0, 1}
    capsys.readouterr()
    assert not (root / "trust-event-log.jsonl").exists()
    loaded = tre.load_trust_state(root)
    assert loaded.trust_score == Decimal("0.20")
    assert loaded.pending_rebind_from == "0" * 64

    digest = digest_path(root / "program.json")
    state = tre.emit_and_apply(
        root, kind="strict_success", program_digest=digest, event_id="after-rebind"
    )
    lines = _read_log(root)
    assert [line["entry_kind"] for line in lines] == ["digest_rebind", "trust_event"]
    assert lines[0]["prev_hash"] == tre.GENESIS_PREV_HASH
    assert lines[0]["payload"]["stored_digest"] == "0" * 64
    assert lines[0]["payload"]["current_digest"] == digest
    assert lines[0]["payload"]["trust_score"] == 0.2
    assert lines[1]["payload"]["event"]["event_id"] == "after-rebind"
    assert lines[1]["prev_hash"] == lines[0]["entry_hash"]
    # Rebind itself does not change score; strict_success then applies +0.05.
    assert state.trust_score == Decimal("0.25")
    assert state.execution_layer == "heavy"
    assert (root / "trust-log-anchor.json").is_file()


# --- Trust event log reader / chain gate (WP-TR-LOG-B) ---


def _tamper_middle_log_line(root: Path) -> None:
    path = tre.trust_event_log_path(root)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) >= 2
    mid = json.loads(lines[0])
    payload = mid.setdefault("payload", {})
    event = payload.setdefault("event", {})
    event["reasons"] = ["tampered"]
    lines[0] = json.dumps(mid, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_TR_LOG_005_chain_verify_pass_and_tamper_fail(tmp_path: Path) -> None:
    _, root, _ = _minimal_program(tmp_path)
    digest = digest_path(root / "program.json")
    tre.emit_and_apply(
        root, kind="strict_success", program_digest=digest, event_id="c1"
    )
    tre.emit_and_apply(
        root,
        kind="validation_failure",
        program_digest=digest,
        reasons=["x"],
        event_id="c2",
    )
    ok = tre.verify_log_chain(root)
    assert ok["ok"] is True
    assert ok["chain_ok"] is True
    assert ok["tip_seq"] == 2

    _tamper_middle_log_line(root)
    bad = tre.verify_log_chain(root)
    assert bad["ok"] is False
    assert bad["chain_ok"] is False
    assert "entry_hash mismatch" in str(bad["reason"])


def test_TR_LOG_005c_legacy_digest_amnesty_verifies_but_not_writable(
    tmp_path: Path,
) -> None:
    """Historical digest_amnesty lines verify; writers cannot mint new ones."""
    _, root, _ = _minimal_program(tmp_path)
    digest = digest_path(root / "program.json")
    body = {
        "schema": tre.TRUST_LOG_ENTRY_SCHEMA,
        "seq": 1,
        "prev_hash": tre.GENESIS_PREV_HASH,
        "entry_kind": "digest_amnesty",
        "program_digest": digest,
        "recorded_at": "2026-07-26T00:00:00Z",
        "payload": {
            "stored_digest": "a" * 64,
            "current_digest": digest,
            "score_before_reset": 1.0,
            "last_event_kind_before_reset": "strict_success",
        },
    }
    # Historical amnesty lines used legacy prev\\ncanonical hashing.
    entry = {**body, "entry_hash": tre.legacy_log_entry_hash(body)}
    (root / "trust-event-log.jsonl").write_text(
        json.dumps(entry, sort_keys=True) + "\n", encoding="utf-8"
    )
    ok = tre.verify_log_chain(root)
    assert ok["ok"] is True
    assert ok["chain_ok"] is True
    assert ok["tip_seq"] == 1
    with pytest.raises(ContractError, match="amnesty is forbidden"):
        tre.append_trust_log_entry(
            root,
            entry_kind="digest_amnesty",
            program_digest=digest,
            payload={"forbidden": True},
        )


def test_TR_LOG_005b_broken_chain_blocks_mutating_apply(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, root, _ = _minimal_program(tmp_path)
    digest = digest_path(root / "program.json")
    tre.emit_and_apply(
        root, kind="strict_success", program_digest=digest, event_id="blk-1"
    )
    tre.emit_and_apply(
        root, kind="strict_success", program_digest=digest, event_id="blk-2"
    )
    before_log = (root / "trust-event-log.jsonl").read_text(encoding="utf-8")
    before_state = (root / "trust-state.json").read_text(encoding="utf-8")
    before_digest = digest_path(root / "program.json")
    _tamper_middle_log_line(root)

    audit = tre.verify_log_chain(root)
    assert audit["ok"] is False
    assert audit["chain_ok"] is False

    with pytest.raises(ContractError, match=tre.GOV_REQUIRED):
        tre.emit_and_apply(
            root, kind="strict_success", program_digest=digest, event_id="blk-blocked"
        )

    master = _write(root / "master-spec.md", "# Spec\n")
    code = main(
        [
            "record",
            "--root",
            str(root),
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
    assert tre.GOV_REQUIRED in str(payload.get("error") or "")
    assert digest_path(root / "program.json") == before_digest
    assert (root / "trust-event-log.jsonl").read_text(encoding="utf-8") != before_log
    # Tamper remains; mutating apply must not heal or append.
    assert "blk-blocked" not in (root / "trust-event-log.jsonl").read_text(
        encoding="utf-8"
    )
    assert (root / "trust-state.json").read_text(encoding="utf-8") == before_state


def test_TR_LOG_006_history_survives_last_event_overwrite(tmp_path: Path) -> None:
    _, root, _ = _minimal_program(tmp_path)
    digest = digest_path(root / "program.json")
    tre.emit_and_apply(
        root,
        kind="validation_failure",
        program_digest=digest,
        reasons=["bad"],
        event_id="bad-1",
    )
    tre.emit_and_apply(
        root,
        kind="deceptive_theater",
        program_digest=digest,
        theater_signal_id="vacuous_gate_pass",
        reasons=["theater"],
        event_id="theater-1",
    )
    tre.emit_and_apply(
        root, kind="strict_success", program_digest=digest, event_id="ok-1"
    )
    state = tre.load_trust_state(root)
    assert state.last_event is not None
    assert state.last_event["kind"] == "strict_success"
    assert state.trust_score == Decimal("0.05")
    entries = tre.read_trust_log_entries(root)
    kinds = [e["payload"]["event"]["kind"] for e in entries]
    assert kinds == ["validation_failure", "deceptive_theater", "strict_success"]
    assert [e["payload"]["event"]["event_id"] for e in entries] == [
        "bad-1",
        "theater-1",
        "ok-1",
    ]


def test_TR_LOG_006b_trust_log_cli_readonly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, root, _ = _minimal_program(tmp_path)
    digest = digest_path(root / "program.json")
    tre.emit_and_apply(
        root,
        kind="validation_failure",
        program_digest=digest,
        reasons=["x"],
        event_id="cli-1",
    )
    before = (root / "trust-event-log.jsonl").read_text(encoding="utf-8")
    before_state = (root / "trust-state.json").read_text(encoding="utf-8")
    code = main(["trust", "log", "--root", str(root), "--verify-chain", "--limit", "1"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["ok"] is True
    assert payload["chain_ok"] is True
    assert len(payload["entries"]) == 1
    assert payload["entries"][0]["payload"]["event"]["event_id"] == "cli-1"
    assert (root / "trust-event-log.jsonl").read_text(encoding="utf-8") == before
    assert (root / "trust-state.json").read_text(encoding="utf-8") == before_state

    # Tamper then verify fails without rewriting.
    path = tre.trust_event_log_path(root)
    path.write_text(
        before.replace("validation_failure", "strict_success"), encoding="utf-8"
    )
    code = main(["trust", "log", "--root", str(root), "--verify-chain"])
    bad = json.loads(capsys.readouterr().out)
    assert code == 1
    assert bad["ok"] is False
    assert bad["chain_ok"] is False


# --- Anti-harness core (WP-TR-AH-A) ---
# context7: skip (stdlib / local harness APIs only)


_TRUST_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "trust"


def _bind_and_baseline(factory: Path, root: Path) -> None:
    tre.bind_program_root(factory, root, seed_baseline=True)


def test_TR_AH_001_d5_seven_theater_fixtures_and_rejection() -> None:
    expected = {
        "vacuous_gate_pass",
        "unbound_kpi",
        "seal_bypass_attempt",
        "out_of_band_mutation",
        "unauthorized_actor",
        "stale_factory_authorization",
        "wrong_root_operation",
    }
    assert tre.THEATER_SIGNAL_IDS == expected
    assert len(tre.THEATER_SIGNAL_IDS) == 7
    for signal in sorted(expected):
        fixture = _TRUST_FIXTURES / f"{signal}.json"
        assert fixture.is_file(), f"missing fixture for {signal}"
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        assert payload["theater_signal_id"] == signal
        assert payload["kind"] == "deceptive_theater"
        tre.validate_event_preconditions(
            "deceptive_theater",
            theater_signal_id=signal,
            reasons=list(payload["reasons"]),
        )
    with pytest.raises(ContractError, match="theater_signal_id"):
        tre.validate_event_preconditions(
            "deceptive_theater",
            theater_signal_id="not_in_d5",
            reasons=["x"],
        )


def test_TR_AH_002_report_event_anti_harness_zeros_and_appends(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, root, factory = _minimal_program(tmp_path)
    # Bind without seeding baseline so report-event is the sole trust_event line.
    tre.bind_program_root(factory, root, seed_baseline=False)
    code = main(
        [
            "trust",
            "report-event",
            "--root",
            str(root),
            "--signal",
            "out_of_band_mutation",
            "--reason",
            "hook-detected-edit",
            "--path",
            "program.json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["ok"] is True
    assert payload["trust_score"] == 0.0
    assert payload["execution_layer"] == "heavy"
    state = tre.load_trust_state(root)
    assert state.trust_score == Decimal("0.00")
    assert state.execution_layer == "heavy"
    assert state.last_event is not None
    assert state.last_event["kind"] == "deceptive_theater"
    assert state.last_event["theater_signal_id"] == "out_of_band_mutation"
    lines = _read_log(root)
    assert len(lines) == 1
    assert lines[0]["entry_kind"] == "trust_event"
    assert lines[0]["payload"]["event"]["theater_signal_id"] == "out_of_band_mutation"


def test_TR_AH_003_validation_failure_excludes_anti_harness_theater_ids(
    tmp_path: Path,
) -> None:
    _, root, _ = _minimal_program(tmp_path)
    digest = digest_path(root / "program.json")
    for signal in sorted(tre.ANTI_HARNESS_THEATER_IDS | tre.THEATER_SIGNAL_IDS):
        with pytest.raises(ContractError, match="must not use theater_signal_id"):
            tre.validate_event_preconditions(
                "validation_failure",
                theater_signal_id=signal,
                reasons=["honest-fail"],
            )
        with pytest.raises(ContractError, match="must not use theater_signal_id"):
            tre.emit_and_apply(
                root,
                kind="validation_failure",
                program_digest=digest,
                reasons=["honest-fail"],
                theater_signal_id=signal,
            )
    state = tre.emit_and_apply(
        root,
        kind="validation_failure",
        program_digest=digest,
        reasons=["honest-fail"],
    )
    assert state.trust_score == Decimal("0.69")
    assert state.last_event is not None
    assert state.last_event["theater_signal_id"] is None


def test_TR_AH_004_authorized_apply_valid_permit_not_anti_harness(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, root, factory = _minimal_program(tmp_path)
    _bind_and_baseline(factory, root)
    stub = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "governance"
        / "corp-gov-check-stub"
    )
    monkeypatch.setenv("CORP_GOV_CHECK", str(stub))
    master = _write(root / "master-spec.md", "# Spec\n")
    before_score = tre.load_trust_state(root).trust_score
    code = main(
        [
            "record",
            "--root",
            str(root),
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
    assert code == 0
    assert payload["apply"] is True
    assert payload["trust_score"] == 1.0
    assert tre.load_trust_state(root).trust_score >= before_score
    assert not (root / "trust-mutation-permit.json").exists()
    # Valid mint/consume round-trip is not theater.
    permit = tre.mint_mutation_permit(
        root, paths=["program.json"], ttl_seconds=60
    )
    assert permit["schema"] == tre.MUTATION_PERMIT_SCHEMA
    assert permit["single_use"] is True
    assert permit["ttl_seconds"] <= 120
    tre.consume_mutation_permit(root, paths=["program.json"], report_theater=False)
    assert tre.load_trust_state(root).trust_score == Decimal("1.00")


def test_TR_AH_004b_forged_expired_permit_is_theater(tmp_path: Path) -> None:
    _, root, factory = _minimal_program(tmp_path)
    _bind_and_baseline(factory, root)
    digest = digest_path(root / "program.json")
    tre.emit_and_apply(
        root, kind="strict_success", program_digest=digest, event_id="seed-permit"
    )
    # Forged writer.
    forged = {
        "schema": tre.MUTATION_PERMIT_SCHEMA,
        "permit_id": "forged",
        "program_digest": digest,
        "paths": ["program.json"],
        "ttl_seconds": 60,
        "minted_at": "2020-01-01T00:00:00Z",
        "expires_at": "2020-01-01T00:01:00Z",
        "single_use": True,
        "writer": "not_python",
    }
    (root / "trust-mutation-permit.json").write_text(
        json.dumps(forged, indent=2) + "\n", encoding="utf-8"
    )
    with pytest.raises(ContractError, match="out_of_band_mutation"):
        tre.consume_mutation_permit(root, paths=["program.json"])
    assert tre.load_trust_state(root).trust_score == Decimal("0.00")
    assert tre.load_trust_state(root).last_event["theater_signal_id"] == (
        "out_of_band_mutation"
    )

    # Expired permit.
    tre.emit_and_apply(
        root,
        kind="strict_success",
        program_digest=digest_path(root / "program.json"),
        event_id="recover-1",
    )
    # Score still 0.05 after one success from 0; mint then expire via now.
    past = datetime(2020, 1, 1, tzinfo=timezone.utc)
    tre.mint_mutation_permit(root, paths=["program.json"], ttl_seconds=30, now=past)
    with pytest.raises(ContractError, match="out_of_band_mutation"):
        tre.consume_mutation_permit(
            root,
            paths=["program.json"],
            now=datetime.now(timezone.utc),
        )
    assert tre.load_trust_state(root).last_event["theater_signal_id"] == (
        "out_of_band_mutation"
    )


def test_TR_AH_004c_clock_rollback_invalidates_permit(tmp_path: Path) -> None:
    _, root, factory = _minimal_program(tmp_path)
    _bind_and_baseline(factory, root)
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    tre.mint_mutation_permit(
        root, paths=["program.json"], ttl_seconds=60, now=future
    )
    with pytest.raises(ContractError, match="out_of_band_mutation|clock skew"):
        tre.consume_mutation_permit(
            root,
            paths=["program.json"],
            now=datetime.now(timezone.utc),
        )
    assert tre.load_trust_state(root).trust_score == Decimal("0.00")
    assert tre.load_trust_state(root).last_event["theater_signal_id"] == (
        "out_of_band_mutation"
    )


def test_TR_AH_005_oob_d8_sole_writer_zeros_trust_with_program_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, root, factory = _minimal_program(tmp_path)
    _bind_and_baseline(factory, root)
    target = factory / "AGENTS.md"
    target.write_text("# oob edit\n", encoding="utf-8")
    code = main(["status", "--root", str(root)])
    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["trust_score"] == 0.0
    assert payload["execution_layer"] == "heavy"
    assert tre.load_trust_state(root).last_event["theater_signal_id"] == (
        "out_of_band_mutation"
    )
    assert any(
        e["entry_kind"] == "trust_event"
        and e["payload"]["event"]["theater_signal_id"] == "out_of_band_mutation"
        for e in _read_log(root)
    )


def test_TR_AH_005b_oob_enumerated_corporate_artifacts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, root, factory = _minimal_program(tmp_path)
    _bind_and_baseline(factory, root)
    (root / "acceptance.json").write_text('{"oob": true}\n', encoding="utf-8")
    code = main(["status", "--root", str(root)])
    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["trust_score"] == 0.0
    assert tre.load_trust_state(root).last_event["theater_signal_id"] == (
        "out_of_band_mutation"
    )


def test_TR_AH_006_missing_program_root_fail_closed_wrong_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, root, factory = _minimal_program(tmp_path)
    monkeypatch.delenv(tre.PROGRAM_ROOT_ENV, raising=False)
    assert tre.resolve_program_root(factory) is None
    with pytest.raises(ContractError, match="wrong_root_operation"):
        tre.require_program_root_for_protected_touch(
            factory,
            theater_root=root,
            protected_path="src/corp_harness/runtime_engine.py",
        )
    state = tre.load_trust_state(root)
    assert state.trust_score == Decimal("0.00")
    assert state.last_event is not None
    assert state.last_event["theater_signal_id"] == "wrong_root_operation"
    assert any(
        e["payload"]["event"]["theater_signal_id"] == "wrong_root_operation"
        for e in _read_log(root)
        if e.get("entry_kind") == "trust_event"
    )


def test_TR_AH_007_dirty_deferred_scan_consequential_clean_status_non_event(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, root, factory = _minimal_program(tmp_path)
    _bind_and_baseline(factory, root)
    digest = digest_path(root / "program.json")
    tre.emit_and_apply(
        root, kind="strict_success", program_digest=digest, event_id="ah7-seed"
    )
    tre.update_surface_baseline(root, factory_root=factory)
    before_log = (root / "trust-event-log.jsonl").read_text(encoding="utf-8")
    before_state = (root / "trust-state.json").read_text(encoding="utf-8")
    # Clean status is non-event.
    assert main(["status", "--root", str(root)]) in {0, 1}
    capsys.readouterr()
    assert (root / "trust-event-log.jsonl").read_text(encoding="utf-8") == before_log
    assert (root / "trust-state.json").read_text(encoding="utf-8") == before_state
    # Dirty deferred scan is consequential via report-event path.
    (root / "gates.json").write_text('{"dirty": true}\n', encoding="utf-8")
    code = main(["status", "--root", str(root)])
    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["trust_score"] == 0.0
    assert len(_read_log(root)) > before_log.count("\n")
    assert tre.load_trust_state(root).last_event["theater_signal_id"] == (
        "out_of_band_mutation"
    )


def test_TR_AH_008_stale_factory_authorization_theater(tmp_path: Path) -> None:
    program, root, factory = _minimal_program(tmp_path)
    _bind_and_baseline(factory, root)
    master = _write(root / "master-spec.md", "# master\n")
    program.record_artifact("master_spec", master, "ceo", root)
    program.save(root / "program.json")
    tre.update_surface_baseline(root, factory_root=factory)
    # Mutate a D8 surface while factory_authorization is missing/unbound.
    (factory / "AGENTS.md").write_text("# tampered\n", encoding="utf-8")
    with pytest.raises(ContractError, match="cannot finish/advance"):
        tre.run_deferred_dirty_scan(
            root,
            factory_root=factory,
            program=Program.load(root / "program.json"),
            force=True,
        )
    state = tre.load_trust_state(root)
    signals = {state.last_event["theater_signal_id"]} if state.last_event else set()
    assert "stale_factory_authorization" in signals or "out_of_band_mutation" in signals
    # Explicit stale classifier.
    stale = tre.classify_stale_factory_authorization(
        root, program=Program.load(root / "program.json")
    )
    assert stale is not None
    assert stale["theater_signal_id"] == "stale_factory_authorization"
    tre.report_anti_harness_event(
        root,
        theater_signal_id="stale_factory_authorization",
        reasons=[stale["reason"]],
        protected_path=stale["protected_path"],
    )
    assert tre.load_trust_state(root).trust_score == Decimal("0.00")
    assert tre.load_trust_state(root).last_event["theater_signal_id"] == (
        "stale_factory_authorization"
    )


def test_TR_AH_009_wrong_root_operation_theater(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, root, factory = _minimal_program(tmp_path)
    other = tmp_path / "other-corp"
    other.mkdir()
    Program.create(
        "other",
        factory,
        ["platform"],
        program_root=other,
        program_kind="factory",
    ).save(other / "program.json")
    _bind_and_baseline(factory, root)
    # Status against a different corporate root than the binding.
    code = main(["status", "--root", str(other)])
    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["trust_score"] == 0.0
    assert tre.load_trust_state(other).last_event["theater_signal_id"] == (
        "wrong_root_operation"
    )


def test_TR_AH_010_forbidden_set_score_swift_writer_actor_user(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli_text = (
        Path(__file__).resolve().parents[1] / "src" / "corp_harness" / "cli.py"
    ).read_text(encoding="utf-8")
    assert "set-score" not in cli_text
    with pytest.raises(SystemExit):
        main(["trust", "set-score", "--value", "1.0"])

    from corp_harness.swift_gov import build_validate_action_payload

    _, root, factory = _minimal_program(tmp_path)
    _bind_and_baseline(factory, root)
    digest = digest_path(root / "program.json")
    tre.emit_and_apply(
        root, kind="strict_success", program_digest=digest, event_id="ah10-seed"
    )
    before = {
        name: (root / name).read_text(encoding="utf-8")
        if (root / name).is_file()
        else None
        for name in PYTHON_SOLE_WRITER_FILES
    }
    payload = build_validate_action_payload(root, "heavy_validate")
    assert payload["mutation"] is False
    for name, prior in before.items():
        path = root / name
        current = path.read_text(encoding="utf-8") if path.is_file() else None
        assert current == prior
    assert "factory_authorization" in USER_GATED_ARTIFACTS
    # --actor user does not raise trust via a cheat path.
    before_score = tre.load_trust_state(root).trust_score
    code = main(
        [
            "next",
            "--root",
            str(root),
            "--to",
            "CORPORATE_ACCEPTANCE",
            "--actor",
            "user",
            "--apply",
        ]
    )
    out = json.loads(capsys.readouterr().out)
    assert code == 3
    assert out["ok"] is False
    # Wrong --actor user must not raise score or bypass trust algebra.
    assert tre.load_trust_state(root).trust_score <= before_score


def _install_factory_hooks(factory: Path) -> None:
    """Copy canonical factory .cursor hooks into a temp factory checkout."""
    src = Path(__file__).resolve().parents[1] / ".cursor"
    hooks_json = src / "hooks.json"
    script = src / "hooks" / "trust_report.py"
    assert hooks_json.is_file(), "factory .cursor/hooks.json missing (WP-TR-AH-B)"
    assert script.is_file(), "factory .cursor/hooks/trust_report.py missing"
    dest = factory / ".cursor"
    (dest / "hooks").mkdir(parents=True, exist_ok=True)
    (dest / "hooks.json").write_text(hooks_json.read_text(encoding="utf-8"), encoding="utf-8")
    (dest / "hooks" / "trust_report.py").write_text(
        script.read_text(encoding="utf-8"), encoding="utf-8"
    )


def test_TR_AH_013_disabled_hooks_bound_root_seal_bypass(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, root, factory = _minimal_program(tmp_path)
    _install_factory_hooks(factory)
    assert tre.required_hooks_intact(factory)
    _bind_and_baseline(factory, root)
    assert tre.baseline_had_factory_hooks(root)
    # Disabling required hooks while bound → seal_bypass_attempt → 0.0.
    (factory / ".cursor" / "hooks.json").write_text(
        json.dumps({"version": 1, "hooks": {"sessionStart": [{"command": "true"}]}})
        + "\n",
        encoding="utf-8",
    )
    assert not tre.required_hooks_intact(factory)
    code = main(["status", "--root", str(root)])
    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["trust_score"] == 0.0
    assert payload["execution_layer"] == "heavy"
    state = tre.load_trust_state(root)
    assert state.trust_score == Decimal("0.00")
    assert state.last_event is not None
    assert state.last_event["theater_signal_id"] == "seal_bypass_attempt"
    assert any(
        e.get("entry_kind") == "trust_event"
        and e["payload"]["event"]["theater_signal_id"] == "seal_bypass_attempt"
        for e in _read_log(root)
    )
    # Full removal is also seal_bypass.
    digest = digest_path(root / "program.json")
    tre.emit_and_apply(
        root, kind="strict_success", program_digest=digest, event_id="ah13-restore"
    )
    # Score may stay 0 after theater; re-baseline with intact hooks then remove.
    _install_factory_hooks(factory)
    tre.update_surface_baseline(root, factory_root=factory)
    # Force a clean tip score for the removal assertion via direct state is
    # forbidden; classify path alone must still report seal_bypass.
    (factory / ".cursor" / "hooks.json").unlink()
    finding = tre.classify_disabled_hooks_seal_bypass(root, factory_root=factory)
    assert finding is not None
    assert finding["theater_signal_id"] == "seal_bypass_attempt"
    result = tre.run_deferred_dirty_scan(root, factory_root=factory, force=True)
    assert result["dirty"] is True
    assert any(
        item["theater_signal_id"] == "seal_bypass_attempt" for item in result["reported"]
    )
    assert tre.load_trust_state(root).trust_score == Decimal("0.00")


def test_TR_AH_012_post_log_trust_state_deletion_is_theater(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, root, factory = _minimal_program(tmp_path)
    _bind_and_baseline(factory, root)
    digest = digest_path(root / "program.json")
    tre.emit_and_apply(
        root, kind="validation_failure", program_digest=digest, reasons=["seed"]
    )
    tre.update_surface_baseline(root, factory_root=factory)
    assert (root / "trust-event-log.jsonl").is_file()
    (root / "trust-state.json").unlink()
    # load must not synthesize 1.0
    loaded = tre.load_trust_state(root)
    assert loaded.trust_score == Decimal("0.00")
    assert loaded.false_genesis is True
    code = main(["status", "--root", str(root)])
    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["trust_score"] == 0.0
    assert tre.load_trust_state(root).last_event["theater_signal_id"] == (
        "out_of_band_mutation"
    )


def test_TR_AH_014_dual_wipe_or_anchor_delete_is_theater(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, root, factory = _minimal_program(tmp_path)
    _bind_and_baseline(factory, root)
    digest = digest_path(root / "program.json")
    tre.emit_and_apply(
        root, kind="strict_success", program_digest=digest, event_id="ah14"
    )
    tre.update_surface_baseline(root, factory_root=factory)
    assert (root / "trust-log-anchor.json").is_file()
    (root / "trust-state.json").unlink()
    (root / "trust-event-log.jsonl").unlink()
    code = main(["status", "--root", str(root)])
    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["trust_score"] == 0.0
    assert tre.load_trust_state(root).last_event["theater_signal_id"] == (
        "out_of_band_mutation"
    )


def test_TR_AH_014b_anchor_blocks_false_genesis(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, root, factory = _minimal_program(tmp_path)
    _bind_and_baseline(factory, root)
    digest = digest_path(root / "program.json")
    tre.emit_and_apply(
        root, kind="strict_success", program_digest=digest, event_id="ah14b"
    )
    tre.update_surface_baseline(root, factory_root=factory)
    anchor = root / "trust-log-anchor.json"
    assert anchor.is_file()
    (root / "trust-state.json").unlink()
    (root / "trust-event-log.jsonl").write_text("", encoding="utf-8")
    # Anchor remains: must not recreate light/1.0 genesis.
    loaded = tre.load_trust_state(root)
    assert loaded.trust_score == Decimal("0.00")
    assert loaded.execution_layer == "heavy"
    code = main(["status", "--root", str(root)])
    payload = json.loads(capsys.readouterr().out)
    assert payload["trust_score"] == 0.0
    assert payload["execution_layer"] == "heavy"
    assert code == 1
    # Deleting the anchor after it existed is also theater.
    tre.update_surface_baseline(root, factory_root=factory)
    # Re-seed log/state via theater already applied; ensure anchor delete detected.
    if not (root / "trust-state.json").is_file():
        tre.report_anti_harness_event(
            root,
            theater_signal_id="out_of_band_mutation",
            reasons=["re-seed after wipe"],
        )
    tre.update_surface_baseline(root, factory_root=factory)
    anchor.unlink()
    code = main(["status", "--root", str(root)])
    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["trust_score"] == 0.0


def test_TR_AH_011_verify_adversarial_collect_ah_tests() -> None:
    """verify.sh / adversarial.sh collect G-TR-AH-CORE + G-TR-AH-BYPASS nodes."""
    root = Path(__file__).resolve().parents[1]
    verify = (root / "scripts" / "harness" / "verify.sh").read_text(encoding="utf-8")
    adversarial = (root / "scripts" / "harness" / "adversarial.sh").read_text(
        encoding="utf-8"
    )
    required = [
        "test_TR_AH_001_d5_seven_theater_fixtures_and_rejection",
        "test_TR_AH_002_report_event_anti_harness_zeros_and_appends",
        "test_TR_AH_003_validation_failure_excludes_anti_harness_theater_ids",
        "test_TR_AH_004_authorized_apply_valid_permit_not_anti_harness",
        "test_TR_AH_004b_forged_expired_permit_is_theater",
        "test_TR_AH_004c_clock_rollback_invalidates_permit",
        "test_TR_AH_005_oob_d8_sole_writer_zeros_trust_with_program_root",
        "test_TR_AH_005b_oob_enumerated_corporate_artifacts",
        "test_TR_AH_006_missing_program_root_fail_closed_wrong_root",
        "test_TR_AH_007_dirty_deferred_scan_consequential_clean_status_non_event",
        "test_TR_AH_008_stale_factory_authorization_theater",
        "test_TR_AH_009_wrong_root_operation_theater",
        "test_TR_AH_010_forbidden_set_score_swift_writer_actor_user",
        "test_TR_AH_011_verify_adversarial_collect_ah_tests",
        "test_TR_AH_012_post_log_trust_state_deletion_is_theater",
        "test_TR_AH_013_disabled_hooks_bound_root_seal_bypass",
        "test_TR_AH_014_dual_wipe_or_anchor_delete_is_theater",
        "test_TR_AH_014b_anchor_blocks_false_genesis",
        "test_TR_AH_015_unbind_program_root_seal_bypass_no_sg03",
        "test_TR_AH_016_status_and_gated_cli_run_dirty_scan",
        "test_TR_AH_016b_verify_scripts_require_program_root",
        "test_TR_AH_017_trust_gated_cli_surfaces",
    ]
    for name in required:
        assert name in verify, f"verify.sh missing {name}"
        assert name in adversarial, f"adversarial.sh missing {name}"
    env = {**os.environ, "PYTHONPATH": "src"}
    collected = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "tests/test_trust_runtime.py",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert collected.returncode == 0, collected.stderr
    for name in required:
        assert f"::{name}" in collected.stdout, f"not collected: {name}"


def test_TR_AH_015_unbind_program_root_seal_bypass_no_sg03(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, root, factory = _minimal_program(tmp_path)
    _bind_and_baseline(factory, root)
    assert tre.program_root_is_bound(factory)
    assert tre.prior_binding_established(root)
    assert tre.sg03_soft_fail_allowed(factory_root=factory, program_root=root) is False
    marker = factory / tre.PROGRAM_ROOT_MARKER
    assert marker.is_file()
    marker.unlink()
    monkeypatch.delenv(tre.PROGRAM_ROOT_ENV, raising=False)
    assert not tre.program_root_is_bound(factory)
    assert tre.prior_binding_established(root)
    finding = tre.classify_unbind_program_root_seal_bypass(root, factory_root=factory)
    assert finding is not None
    assert finding["theater_signal_id"] == "seal_bypass_attempt"
    assert tre.sg03_soft_fail_allowed(factory_root=factory, program_root=root) is False
    code = main(["status", "--root", str(root)])
    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["trust_score"] == 0.0
    assert tre.load_trust_state(root).last_event["theater_signal_id"] == (
        "seal_bypass_attempt"
    )
    # Unbind must not restore SG-03 soft-fail; light apply stays light (PIPE-001)
    # while FG-001 seals remain GOV_REQUIRED without corp-gov-check.
    from corp_harness.cli import _enforce_trust_route

    monkeypatch.setenv("CORP_GOV_CHECK", str(tmp_path / "missing-corp-gov-check"))
    assert tre.sg03_soft_fail_allowed(factory_root=factory, program_root=root) is False
    master = _write(root / "master-spec.md", "# Spec\n")
    # Re-bind temporarily is forbidden for this assertion; keep unbound.
    code = main(
        [
            "record",
            "--root",
            str(root),
            "--artifact",
            "master_spec",
            "--path",
            str(master),
            "--actor",
            "ceo",
            "--apply",
        ]
    )
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["ok"] is True
    assert tre.route_for_action(root, "record_artifact:other")["action_routed_layer"] == (
        "light"
    )
    with pytest.raises(ContractError, match=tre.GOV_REQUIRED):
        _enforce_trust_route(root, "record_artifact:gates", factory_root=factory)
    assert tre.sg03_soft_fail_allowed(factory_root=factory, program_root=root) is False


def test_TR_AH_016_status_and_gated_cli_run_dirty_scan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, root, factory = _minimal_program(tmp_path)
    _bind_and_baseline(factory, root)
    tre.update_surface_baseline(root, factory_root=factory)
    (root / "gates.json").write_text('{"dirty": true}\n', encoding="utf-8")
    # status
    code = main(["status", "--root", str(root)])
    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["trust_score"] == 0.0
    assert tre.load_trust_state(root).last_event["theater_signal_id"] == (
        "out_of_band_mutation"
    )
    # Reset tip via report path then dirty again for gated record entry.
    digest = digest_path(root / "program.json")
    tre.emit_and_apply(
        root, kind="strict_success", program_digest=digest, event_id="ah16-seed"
    )
    tre.update_surface_baseline(root, factory_root=factory)
    (root / "acceptance.json").write_text('{"dirty": true}\n', encoding="utf-8")
    before = len(_read_log(root))
    master = _write(root / "master-spec.md", "# Spec\n")
    code = main(
        [
            "record",
            "--root",
            str(root),
            "--artifact",
            "master_spec",
            "--path",
            str(master),
            "--actor",
            "ceo",
        ]
    )
    capsys.readouterr()
    assert code == 0
    assert len(_read_log(root)) > before
    assert tre.load_trust_state(root).last_event["theater_signal_id"] == (
        "out_of_band_mutation"
    )


def test_TR_AH_016b_verify_scripts_require_program_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(__file__).resolve().parents[1]
    verify = root / "scripts" / "harness" / "verify.sh"
    adversarial = root / "scripts" / "harness" / "adversarial.sh"
    for script in (verify, adversarial):
        text = script.read_text(encoding="utf-8")
        assert "CORP_HARNESS_PROGRAM_ROOT" in text
        assert ".corp-harness-program-root" in text
        assert "CORP_HARNESS_REQUIRE_BOUND_ROOT" in text
        # Spaced corporate paths (e.g. "Trust Routed Runtime") must survive:
        # marker parse may trim edges, never delete all whitespace classes.
        assert "tr -d " not in text
        assert "sed -e 's/^[[:space:]]*//'" in text
    base_env = {
        k: v
        for k, v in os.environ.items()
        if k not in {tre.PROGRAM_ROOT_ENV, "CORP_HARNESS_REQUIRE_BOUND_ROOT"}
    }
    # Invalid env binding fails closed.
    bad = dict(base_env)
    bad[tre.PROGRAM_ROOT_ENV] = str(tmp_path / "missing-corporate")
    bad["PYTHONPATH"] = "src"
    for script in (verify, adversarial):
        proc = subprocess.run(
            ["bash", str(script)],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            env=bad,
        )
        assert proc.returncode != 0, script.name
        assert "program.json" in (proc.stderr + proc.stdout)
    # Require-bound without env/marker fails closed (no bootstrap escape).
    monkeypatch.chdir(root)
    require = dict(base_env)
    require["CORP_HARNESS_REQUIRE_BOUND_ROOT"] = "1"
    require["PYTHONPATH"] = "src"
    marker = root / tre.PROGRAM_ROOT_MARKER
    marker_backup = None
    if marker.is_file():
        marker_backup = marker.read_text(encoding="utf-8")
        marker.unlink()
    try:
        for script in (verify, adversarial):
            proc = subprocess.run(
                ["bash", str(script)],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
                env=require,
            )
            assert proc.returncode != 0, script.name
            assert "program root binding required" in (proc.stderr + proc.stdout)
    finally:
        if marker_backup is not None:
            marker.write_text(marker_backup, encoding="utf-8")


def test_TR_AH_017_trust_gated_cli_surfaces(tmp_path: Path) -> None:
    expected = {
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
    assert tre.TRUST_GATED_CLI_SURFACES == expected
    cli_text = (
        Path(__file__).resolve().parents[1] / "src" / "corp_harness" / "cli.py"
    ).read_text(encoding="utf-8")
    assert "_maybe_dirty_scan" in cli_text
    assert "_dirty_scan_bound_program_root" in cli_text
    assert 'surface="archive"' in cli_text
    assert 'surface="install"' in cli_text
    assert 'surface="rollback"' in cli_text
    assert 'args.command == "status"' in cli_text
    assert 'usage_command == "record"' in cli_text
    assert "validate-action" in cli_text
    assert "write-receipt" in cli_text
    assert "report-event" in cli_text
    assert "check_apply" in cli_text
    _, corp, fact = _minimal_program(tmp_path)
    _bind_and_baseline(fact, corp)
    digest = digest_path(corp / "program.json")
    tre.save_trust_state(corp, tre.synthesize_trust_state(digest))
    route = tre.route_for_action(corp, tre.HEAVY_VALIDATE_ACTION)
    assert route["action_routed_layer"] == "heavy"
    assert tre.sg03_soft_fail_allowed(factory_root=fact, program_root=corp) is False


# --- TRR residuals (ADR-TR-004 / WP-TR-H) ---

_EXPECTED_D5_THEATER_IDS = frozenset(
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


def test_TRR_001_swift_theater_signal_id_seven() -> None:
    """Swift TheaterSignalId must be full D5 7/7 (closes PLAT-TR-05)."""
    swift_src = (
        Path(__file__).resolve().parents[1]
        / "swift"
        / "Sources"
        / "GovernanceTypes"
        / "TrustRuntime.swift"
    )
    if not swift_src.is_file():
        pytest.skip("Swift TrustRuntime.swift absent")
    text = swift_src.read_text(encoding="utf-8")
    # Extract TheaterSignalId enum body only.
    m = re.search(
        r"public enum TheaterSignalId:[^{]+\{(.*?)\n\}",
        text,
        flags=re.S,
    )
    assert m is not None, "TheaterSignalId enum not found in Swift sources"
    body = m.group(1)
    raw_ids = set(re.findall(r'case\s+\w+\s*=\s*"([^"]+)"', body))
    assert raw_ids == _EXPECTED_D5_THEATER_IDS, (
        f"Swift TheaterSignalId raw values {sorted(raw_ids)} != "
        f"expected D5 set {sorted(_EXPECTED_D5_THEATER_IDS)}"
    )
    assert len(raw_ids) == 7
    # Cross-check Python closed set stays the authority for emit+apply.
    assert tre.THEATER_SIGNAL_IDS == _EXPECTED_D5_THEATER_IDS
    if shutil.which("swift") is None:
        return
    # When toolchain present, GovernanceTypesTests must stay green for the mirror.
    proc = subprocess.run(
        ["swift", "test", "--filter", "TrustRuntimeTests"],
        cwd=str(Path(__file__).resolve().parents[1] / "swift"),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_TRR_002_heavy_oserror_gov_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Direct heavy run_gov_command OSError → GOV_REQUIRED (closes ADV-TR-001)."""
    stub = tmp_path / "corp-gov-check-stub"
    stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    stub.chmod(0o700)
    monkeypatch.setenv("CORP_GOV_CHECK", str(stub))

    def _boom(*_a: object, **_k: object) -> object:
        raise OSError("injected heavy OSError for TRR_002")

    monkeypatch.setattr(subprocess, "run", _boom)
    _, root, _ = _minimal_program(tmp_path)
    for command, kwargs in (
        ("validate-action", {"action": "heavy_validate"}),
        ("write-receipt", {}),
    ):
        payload, code = run_gov_command(command, root, **kwargs)
        assert code == 2
        assert payload["error"] == GOV_REQUIRED
        assert payload["assist"] is False
        assert payload["ok"] is False


def test_TRR_002b_assist_oserror_sg03_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Assist-command OSError remains SG-03 / GOV_ASSIST_UNAVAILABLE."""
    stub = tmp_path / "corp-gov-check-stub"
    stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    stub.chmod(0o700)
    monkeypatch.setenv("CORP_GOV_CHECK", str(stub))

    def _boom(*_a: object, **_k: object) -> object:
        raise OSError("injected assist OSError for TRR_002b")

    monkeypatch.setattr(subprocess, "run", _boom)
    _, root, _ = _minimal_program(tmp_path)
    payload, code = run_gov_command("diagnose", root)
    assert code == 2
    assert payload["error"] == GOV_ASSIST_UNAVAILABLE
    assert payload["assist"] is True
    assert payload["ok"] is False


def _fork_duplicate_seq(root: Path) -> None:
    path = tre.trust_event_log_path(root)
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    last = json.loads(lines[-1])
    fork = json.loads(json.dumps(last))
    fork["recorded_at"] = "2099-01-01T00:00:00Z"
    body = {key: value for key, value in fork.items() if key != "entry_hash"}
    fork["entry_hash"] = tre.canonical_log_entry_hash(body)
    lines.append(json.dumps(fork, sort_keys=True, separators=(",", ":")))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_FC_RECOVER_001_agent_actor_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, root, _ = _minimal_program(tmp_path)
    digest = digest_path(root / "program.json")
    tre.emit_and_apply(
        root, kind="strict_success", program_digest=digest, event_id="fc-rec-seed"
    )
    _fork_duplicate_seq(root)
    code = main(
        [
            "trust",
            "recover-chain",
            "--root",
            str(root),
            "--actor",
            "ceo",
            "--apply",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 3
    assert payload["ok"] is False
    assert "unauthorized_actor" in str(payload.get("error") or "")
    assert not tre.chain_recovery_path(root).is_file()


def test_FC_RECOVER_001_user_apply_allows_record(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "governance"
        / "corp-gov-check-stub"
    )
    monkeypatch.setenv("CORP_GOV_CHECK", str(stub))
    _, root, _ = _minimal_program(tmp_path)
    digest = digest_path(root / "program.json")
    tre.emit_and_apply(
        root, kind="strict_success", program_digest=digest, event_id="fc-rec-ok"
    )
    score_before = tre.load_trust_state(root).trust_score
    log_before = tre.trust_event_log_path(root).read_text(encoding="utf-8")
    _fork_duplicate_seq(root)
    broken = tre.verify_log_chain(root)
    assert broken["ok"] is False
    master = _write(root / "master-spec.md", "# Spec\n")
    blocked = main(
        [
            "record",
            "--root",
            str(root),
            "--artifact",
            "master_spec",
            "--path",
            str(master),
            "--actor",
            "ceo",
            "--apply",
        ]
    )
    capsys.readouterr()
    assert blocked == 3
    dry = main(
        ["trust", "recover-chain", "--root", str(root), "--actor", "user"]
    )
    dry_payload = json.loads(capsys.readouterr().out)
    assert dry == 0
    assert dry_payload["would_recover"] is True
    assert dry_payload["apply"] is False
    assert not tre.chain_recovery_path(root).is_file()
    code = main(
        [
            "trust",
            "recover-chain",
            "--root",
            str(root),
            "--actor",
            "user",
            "--apply",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["recovered"] is True
    assert payload["trust_score"] == float(score_before)
    assert tre.load_trust_state(root).trust_score == score_before
    assert tre.chain_recovery_path(root).is_file()
    recovered = tre.verify_log_chain(root)
    assert recovered["ok"] is True
    assert recovered["chain_ok"] is True
    record_code = main(
        [
            "record",
            "--root",
            str(root),
            "--artifact",
            "master_spec",
            "--path",
            str(master),
            "--actor",
            "ceo",
            "--apply",
        ]
    )
    record_payload = json.loads(capsys.readouterr().out)
    assert record_code == 0, record_payload
    assert record_payload["ok"] is True
    assert tre.trust_event_log_path(root).read_text(encoding="utf-8").startswith(
        log_before.split("2099-01-01", 1)[0]
    ) or log_before in tre.trust_event_log_path(root).read_text(encoding="utf-8")


def test_FC_LOG_001_concurrent_append_unique_seq(tmp_path: Path) -> None:
    _, root, _ = _minimal_program(tmp_path)
    digest = digest_path(root / "program.json")
    tre.emit_and_apply(
        root, kind="strict_success", program_digest=digest, event_id="fc-lock-seed"
    )
    errors: list[BaseException] = []

    def _worker(index: int) -> None:
        try:
            tre.append_trust_log_entry(
                root,
                entry_kind="digest_rebind",
                program_digest=digest,
                payload={"index": index},
            )
        except Exception as exc:  # noqa: BLE001 — collect for assertion
            errors.append(exc)

    threading = __import__("threading")
    workers = [threading.Thread(target=_worker, args=(i,)) for i in range(8)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert errors == []
    seqs = [int(entry["seq"]) for entry in tre.read_trust_log_entries(root)]
    assert len(seqs) == len(set(seqs))
    assert tre.verify_log_chain(root)["ok"] is True


def test_FC_SCAN_001_pyc_build_not_oob_without_fa(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    factory = tmp_path / "factory"
    program_a = tmp_path / "fail-closed-runtime"
    sibling = tmp_path / "trust-runtime-residuals"
    factory.mkdir()
    program_a.mkdir()
    sibling.mkdir()
    (factory / "src" / "corp_harness").mkdir(parents=True)
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
    tre.bind_program_root(factory, sibling)
    marker_before = (factory / tre.PROGRAM_ROOT_MARKER).read_text(encoding="utf-8")
    monkeypatch.setenv(tre.PROGRAM_ROOT_ENV, str(program_a))
    tre.update_surface_baseline(program_a, factory_root=factory)
    pyc = factory / "src" / "corp_harness" / "__pycache__" / "cli.cpython-313.pyc"
    pyc.parent.mkdir(parents=True, exist_ok=True)
    pyc.write_bytes(b"pyc")
    build = (
        factory
        / "swift"
        / ".build"
        / "arm64-apple-macosx"
        / "debug"
        / "index"
        / "store"
        / "CGPath.h"
    )
    build.parent.mkdir(parents=True, exist_ok=True)
    build.write_text("noise\n", encoding="utf-8")
    (factory / "src" / "corp_harness" / "runtime_engine.py").write_text(
        "# live factory working tree\n", encoding="utf-8"
    )
    before = tre.load_trust_state(program_a).trust_score
    code = main(["status", "--root", str(program_a)])
    capsys.readouterr()
    assert code == 0
    assert tre.load_trust_state(program_a).trust_score == before
    assert (factory / tre.PROGRAM_ROOT_MARKER).read_text(encoding="utf-8") == marker_before
    findings = tre.detect_dirty_surfaces(program_a, factory_root=factory)
    assert findings == []
    (program_a / "program.json").write_text(
        (program_a / "program.json").read_text(encoding="utf-8").replace(
            "fail-closed-runtime", "tampered-id", 1
        ),
        encoding="utf-8",
    )
    dirty = tre.detect_dirty_surfaces(program_a, factory_root=factory)
    assert any(
        item.get("theater_signal_id") == "out_of_band_mutation"
        and item.get("protected_path") == "program.json"
        for item in dirty
    )


def test_FC_LOG_001_shared_lock_state_and_append(tmp_path: Path) -> None:
    _, root, _ = _minimal_program(tmp_path)
    digest = digest_path(root / "program.json")
    tre.emit_and_apply(
        root, kind="strict_success", program_digest=digest, event_id="fc-lock-mix"
    )
    errors: list[Exception] = []

    def _worker(index: int) -> None:
        try:
            if index % 2 == 0:
                tre.append_trust_log_entry(
                    root,
                    entry_kind="digest_rebind",
                    program_digest=digest,
                    payload={"index": index},
                )
            else:
                state = tre.load_trust_state(root)
                tre.save_trust_state(root, state)
        except Exception as exc:
            errors.append(exc)

    threading = __import__("threading")
    workers = [threading.Thread(target=_worker, args=(i,)) for i in range(8)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    unexpected = [
        exc
        for exc in errors
        if "trust-state changed concurrently" not in str(exc)
    ]
    assert unexpected == []
    seqs = [int(entry["seq"]) for entry in tre.read_trust_log_entries(root)]
    assert len(seqs) == len(set(seqs))
    assert tre.verify_log_chain(root)["ok"] is True


def test_FC_RECOVER_001_does_not_wipe_or_amnesty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, root, _ = _minimal_program(tmp_path)
    digest = digest_path(root / "program.json")
    tre.emit_and_apply(
        root, kind="strict_success", program_digest=digest, event_id="fc-rec-wipe"
    )
    _fork_duplicate_seq(root)
    log_path = tre.trust_event_log_path(root)
    before = log_path.read_bytes()
    score_before = tre.load_trust_state(root).trust_score
    code = main(
        [
            "trust",
            "recover-chain",
            "--root",
            str(root),
            "--actor",
            "user",
            "--apply",
        ]
    )
    capsys.readouterr()
    assert code == 0
    assert log_path.is_file()
    assert log_path.read_bytes() == before
    assert tre.load_trust_state(root).trust_score == score_before


def test_FC_INCIDENT_001_chain_incident_r1_fixture_and_verify_required_collect() -> None:
    fixture = {
        "duplicate_seq": 6312,
        "duplicate_at_file_lines": [6312, 6313],
        "kind_counts": {
            "out_of_band_mutation": 6310,
            "wrong_root_operation": 4,
        },
        "verify_error": "expected seq 6313, got 6312",
    }
    live = Path(
        "/Users/sagehart/Downloads/Fail Closed Harness/evidence/chain-incident-r1.json"
    )
    if live.is_file():
        raw = json.loads(live.read_text(encoding="utf-8"))
        log = raw.get("log") or {}
        assert log.get("duplicate_seq") == fixture["duplicate_seq"]
        assert log.get("duplicate_at_file_lines") == fixture["duplicate_at_file_lines"]
        assert (log.get("kind_counts") or {}).get("out_of_band_mutation") == 6310
        assert fixture["verify_error"] in str(log.get("verify_error") or "")
    else:
        assert fixture["duplicate_seq"] == 6312
        assert fixture["duplicate_at_file_lines"] == [6312, 6313]
        assert fixture["kind_counts"]["out_of_band_mutation"] == 6310
        assert "expected seq 6313, got 6312" in fixture["verify_error"]
    verify_sh = (
        Path(__file__).resolve().parents[1] / "scripts" / "harness" / "verify.sh"
    ).read_text(encoding="utf-8")
    required = (
        "test_FC_LOG_001_concurrent_append_unique_seq",
        "test_FC_RECOVER_001_agent_actor_refused",
        "test_FC_RECOVER_001_user_apply_allows_record",
        "test_FC_INCIDENT_001_chain_incident_r1_fixture_and_verify_required_collect",
    )
    for name in required:
        assert name in verify_sh


def test_FC_EVIDENCE_001_run_evidence_forwards_program_root_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G-TPC-002 node id; body retained from WP-FC-007 (ACC-TPC-LEGAL-002)."""
    _fc_evidence_001(tmp_path, monkeypatch)


def test_FC_EVIDENCE_002_leaked_active_packet_write_set_does_not_bypass_deny(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G-TPC-002 node id; body retained from WP-FC-008 (ACC-TPC-LEGAL-002)."""
    _fc_evidence_002(tmp_path, monkeypatch)
