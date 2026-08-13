"""Three-plane control: ACC-TPC plane/court/magnet/legal (WP-TPC-001/002)."""

from __future__ import annotations

import inspect
import json
import os
from decimal import Decimal
from pathlib import Path

import pytest

from corp_harness import runtime_engine as tre
from corp_harness.cli import main
from corp_harness.contracts import ContractError
from corp_harness.execution_policy import validate_packet_attestation
from corp_harness.model import USER_GATED_ARTIFACTS, Program, digest_path


@pytest.fixture(autouse=True)
def _isolate_program_root_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(tre.PROGRAM_ROOT_ENV, raising=False)
    monkeypatch.delenv(tre.ACTIVE_PACKET_ENV, raising=False)


def _minimal_program(tmp_path: Path) -> tuple[Path, Path, Path]:
    factory = tmp_path / "factory"
    root = tmp_path / "three-plane-control"
    factory.mkdir()
    root.mkdir()
    (factory / "src" / "corp_harness").mkdir(parents=True)
    (factory / "corporate" / "plugin" / "corporate-site-harness").mkdir(parents=True)
    Program.create(
        "three-plane-control",
        factory,
        ["platform", "security"],
        program_root=root,
        program_kind="factory",
    ).save(root / "program.json")
    return factory, root, factory


def test_TPC_PLANE_001_three_plane_allow_with_score_zero(tmp_path: Path) -> None:
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
    decision = tre.evaluate_three_planes(
        capability_ok=True,
        evidence_ok=True,
        spend_ok=True,
        trust_score=Decimal("0.00"),
        execution_layer="heavy",
    )
    assert decision["allowed"] is True
    assert decision["permission"] == "allow"
    assert decision["refused_planes"] == []
    route = tre.route_for_action(root, "record_artifact:other")
    assert route["trust_score"] == 0.0
    assert route["execution_layer"] == "heavy"
    assert route["action_routed_layer"] == "light"
    assert route["always_force_heavy"] is False


def test_TPC_PLANE_001_refuse_when_any_plane_fails() -> None:
    for failed in tre.THREE_PLANE_NAMES:
        kwargs = {
            "capability_ok": failed != "capability",
            "evidence_ok": failed != "evidence",
            "spend_ok": failed != "spend",
            "trust_score": Decimal("1.00"),
            "execution_layer": "light",
        }
        decision = tre.evaluate_three_planes(**kwargs)
        assert decision["allowed"] is False
        assert decision["permission"] == "deny"
        assert decision["refused_planes"] == [failed]


def test_TPC_COURT_001_score_mutation_ignored_for_apply(tmp_path: Path) -> None:
    src = inspect.getsource(tre.action_routed_layer)
    assert "execution_layer_for_score(" not in src

    _, root, _ = _minimal_program(tmp_path)
    digest = digest_path(root / "program.json")
    allow_at_zero = tre.evaluate_three_planes(
        capability_ok=True,
        evidence_ok=True,
        spend_ok=True,
        trust_score=Decimal("0.00"),
    )
    allow_at_one = tre.evaluate_three_planes(
        capability_ok=True,
        evidence_ok=True,
        spend_ok=True,
        trust_score=Decimal("1.00"),
    )
    assert allow_at_zero["allowed"] is True
    assert allow_at_one["allowed"] is True
    assert allow_at_zero["permission"] == allow_at_one["permission"] == "allow"

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
    low = tre.route_for_action(root, "record_artifact:other")
    tre.save_trust_state(
        root,
        tre.TrustState(
            trust_score=Decimal("1.00"),
            execution_layer="light",
            program_digest=digest,
            last_event=None,
            updated_at="2020-01-01T00:00:00Z",
            generation=tre.load_trust_state(root).generation,
        ),
    )
    high = tre.route_for_action(root, "record_artifact:other")
    assert low["action_routed_layer"] == high["action_routed_layer"] == "light"
    assert tre.action_routed_layer(Decimal("0.00"), "check_apply") == "light"
    assert tre.action_routed_layer(Decimal("1.00"), "check_apply") == "light"


def test_TPC_COURT_001_theater_kind_ignored_for_routing(tmp_path: Path) -> None:
    _, root, _ = _minimal_program(tmp_path)
    digest = digest_path(root / "program.json")
    for kind in ("strict_success", "validation_failure", "deceptive_theater"):
        decision = tre.evaluate_three_planes(
            capability_ok=True,
            evidence_ok=True,
            spend_ok=True,
            theater_kind=kind,
            trust_score=Decimal("0.00"),
        )
        assert decision["allowed"] is True
        assert "theater_kind" in decision["ignored_for_decision"]

    tre.emit_and_apply(
        root,
        kind="deceptive_theater",
        program_digest=digest,
        theater_signal_id="unbound_kpi",
        reasons=["theater"],
    )
    assert tre.load_trust_state(root).trust_score == Decimal("0.00")
    assert tre.route_for_action(root, "record_artifact:other")[
        "action_routed_layer"
    ] == "light"
    assert tre.route_for_action(root, "check_apply")["action_routed_layer"] == "light"


def test_TPC_COURT_002_fg001_always_force_independent_of_score(tmp_path: Path) -> None:
    _, root, _ = _minimal_program(tmp_path)
    digest = digest_path(root / "program.json")
    for score, layer in (
        (Decimal("1.00"), "light"),
        (Decimal("0.00"), "heavy"),
    ):
        tre.save_trust_state(
            root,
            tre.TrustState(
                trust_score=score,
                execution_layer=layer,
                program_digest=digest,
                last_event=None,
                updated_at="2020-01-01T00:00:00Z",
                generation=tre.load_trust_state(root).generation
                if (root / "trust-state.json").is_file()
                else 0,
            ),
        )
        for action in tre.ALWAYS_FORCE_HEAVY_ACTIONS:
            routed = tre.route_for_action(root, action)
            assert routed["action_routed_layer"] == "heavy"
            assert routed["always_force_heavy"] is True
            assert tre.action_routed_layer(score, action) == "heavy"
        assert tre.action_routed_layer(score, tre.HEAVY_VALIDATE_ACTION) == "heavy"
        assert (
            tre.action_routed_layer(score, "record_artifact:other") == "light"
        )


def test_TPC_SEC_MAGNET_001_bits_audit_only_not_routing(tmp_path: Path) -> None:
    assert tre.magnet_bits_affect_routing() is False
    _, root, _ = _minimal_program(tmp_path)
    digest = digest_path(root / "program.json")
    tre.save_trust_state(root, tre.synthesize_trust_state(digest))
    before = tre.route_for_action(root, "record_artifact:other")
    score_before = tre.load_trust_state(root).trust_score

    for bit in sorted(tre.MAGNET_CHEAT_BITS):
        entry = tre.append_magnet_cheat_bit(
            root, bit=bit, program_digest=digest, reasons=[bit]
        )
        assert entry["entry_kind"] == "magnet_cheat_bit"
        assert entry["payload"]["audit_only"] is True
        assert entry["payload"]["bit"] == bit

    after = tre.route_for_action(root, "record_artifact:other")
    state = tre.load_trust_state(root)
    assert state.trust_score == score_before
    assert after["action_routed_layer"] == before["action_routed_layer"] == "light"
    decision = tre.evaluate_three_planes(
        capability_ok=True,
        evidence_ok=True,
        spend_ok=True,
        magnet_bits={"hook_write": True, "actor_skip": 1, "self_approval": True},
        trust_score=state.trust_score,
    )
    assert decision["allowed"] is True
    assert "magnet_bits" in decision["ignored_for_decision"]
    kinds = {
        item.get("entry_kind") for item in tre.read_trust_log_entries(root)
    }
    assert "magnet_cheat_bit" in kinds
    with pytest.raises(ContractError, match="unknown magnet cheat bit"):
        tre.append_magnet_cheat_bit(
            root, bit="intern_to_principal", program_digest=digest
        )


def _write(path: Path, value: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return path


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


def _sealed_legal_packet(**overrides: object) -> dict:
    packet = {
        "role": "site-specialist",
        "packet_id": "WP-TPC-002",
        "root": "/tmp/factory",
        "write_set": ["src/corp_harness/evidence.py"],
        "routed_model": "composer-2.5",
        "success_schema": "pytest exit 0",
        "halt_conditions": ["Would pass --actor user"],
        "model_id": "composer-2.5",
        "model_class": "standard",
        "task_class": "packet_implement",
        "max_mode": False,
    }
    packet.update(overrides)
    return packet


def test_TPC_LEGAL_001_apply_autobind_without_mint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Apply auto-binds ACTIVE_PACKET; no separate mint; no manual export."""
    factory, root, _ = _minimal_program(tmp_path)
    program = Program.load(root / "program.json")
    _record_factory_auth(program, root, factory, ["src/corp_harness", "tests"])
    tre.bind_program_root(factory, root)
    monkeypatch.setenv(tre.PROGRAM_ROOT_ENV, str(root))
    monkeypatch.delenv(tre.ACTIVE_PACKET_ENV, raising=False)

    target = factory / "src" / "corp_harness" / "evidence.py"
    target.write_text("# baseline\n", encoding="utf-8")
    tre.update_surface_baseline(root, factory_root=factory)
    target.write_text("# packet-edit\n", encoding="utf-8")

    with pytest.raises(ContractError, match="unsigned or preToolUse"):
        tre.run_deferred_dirty_scan(
            root, factory_root=factory, program=program, force=True
        )

    assert tre.ACTIVE_PACKET_ENV not in os.environ
    assert not (root / "trust-mutation-permit.json").exists()

    packet = _sealed_legal_packet(root=str(factory))
    assert validate_packet_attestation(packet)["ok"] is True
    # Packet file lives outside the corporate root so creating it is not OOB.
    packet_path = tmp_path / "packet-WP-TPC-002.json"
    _write(packet_path, json.dumps(packet) + "\n")

    code = main(["apply", "--root", str(root), "--packet", str(packet_path)])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["ok"] is True
    assert payload["apply"] is True
    assert payload["minted_permit"] is False
    assert payload["active_packet"] == str(packet_path.resolve())
    assert "src/corp_harness/evidence.py" in payload["write_set"]
    assert os.environ.get(tre.ACTIVE_PACKET_ENV) == str(packet_path.resolve())
    assert not (root / "trust-mutation-permit.json").exists()

    # Covered dirt accepted; force scan stays clean afterward.
    clean = tre.run_deferred_dirty_scan(
        root, factory_root=factory, program=Program.load(root / "program.json"), force=True
    )
    assert clean["ok"] is True
    assert [
        item
        for item in clean["reported"]
        if item.get("theater_signal_id") == "out_of_band_mutation"
    ] == []


def test_TPC_LEGAL_001_legal_next_no_gap_then_omits_mint() -> None:
    """WP-TPC-002 transitional: mint AND apply both present (WP-TPC-006 cuts mint)."""
    legal = tre.LEGAL_NEXT_COMMANDS
    assert "corp-harness mint-mutation-permit" in legal
    assert "corp-harness apply" in legal
    assert legal.index("corp-harness mint-mutation-permit") < legal.index(
        "corp-harness apply"
    )
    # No gap: both ceremony paths are named legal next this packet.
    assert {"corp-harness mint-mutation-permit", "corp-harness apply"}.issubset(
        set(legal)
    )


def test_TPC_LEGAL_001_stereotyped_deny_includes_apply_after_autobind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory, root, _ = _minimal_program(tmp_path)
    tre.bind_program_root(factory, root)
    monkeypatch.setenv(tre.PROGRAM_ROOT_ENV, str(root))
    packet = _sealed_legal_packet(root=str(factory))
    packet_path = root / "sealed-packet.json"
    _write(packet_path, json.dumps(packet) + "\n")
    tre.auto_bind_active_packet(root, packet_path)
    assert os.environ.get(tre.ACTIVE_PACKET_ENV)

    decision = tre.evaluate_pretooluse(
        factory,
        root,
        {
            "tool_name": "Write",
            "tool_input": {"path": str(root / "program.json")},
        },
    )
    assert decision["permission"] == "deny"
    legal = decision.get("legal_next") or []
    assert "corp-harness apply" in legal
    assert "corp-harness mint-mutation-permit" in legal
    assert "corp-harness apply" in decision["user_message"]
    assert "corp-harness apply" in decision["agent_message"]
    assert decision["halt_report"]["verdict"] == "halt_report"


def test_TPC_LEGAL_003_clean_status_non_event(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, root, factory = _minimal_program(tmp_path)
    tre.bind_program_root(factory, root)
    tre.update_surface_baseline(root, factory_root=factory)
    digest = digest_path(root / "program.json")
    tre.emit_and_apply(
        root, kind="strict_success", program_digest=digest, event_id="legal3-seed"
    )
    tre.update_surface_baseline(root, factory_root=factory)
    before_log = (root / "trust-event-log.jsonl").read_text(encoding="utf-8")
    before_state = (root / "trust-state.json").read_text(encoding="utf-8")
    assert main(["status", "--root", str(root)]) in {0, 1}
    capsys.readouterr()
    assert (root / "trust-event-log.jsonl").read_text(encoding="utf-8") == before_log
    assert (root / "trust-state.json").read_text(encoding="utf-8") == before_state


def test_TPC_LEGAL_003_actor_user_scoped_fa_approval_recover_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert "factory_authorization" in USER_GATED_ARTIFACTS
    assert "user_approval" in USER_GATED_ARTIFACTS
    _, root, _ = _minimal_program(tmp_path)

    # Invoice/usage-style: --actor user refused.
    code = main(
        [
            "usage",
            "record",
            "--root",
            str(root),
            "--actor",
            "user",
            "--amount-usd",
            "1.0",
            "--source",
            "invoice",
            "--apply",
        ]
    )
    usage_payload = json.loads(capsys.readouterr().out)
    assert code == 3
    assert usage_payload["ok"] is False
    assert "refuses --actor user" in str(usage_payload.get("error") or "")

    # recover-chain still requires --actor user.
    code = main(
        ["trust", "recover-chain", "--root", str(root), "--actor", "ceo", "--apply"]
    )
    recover_payload = json.loads(capsys.readouterr().out)
    assert code == 3
    assert recover_payload["ok"] is False
    assert "requires --actor user" in str(recover_payload.get("error") or "")

    # FA / approval remain user-gated at the model layer.
    with pytest.raises(ContractError, match="must be produced by user"):
        Program.load(root / "program.json").record_artifact(
            "factory_authorization",
            _write(root / "factory-authorization.json", "{}\n"),
            "ceo",
            root,
        )
