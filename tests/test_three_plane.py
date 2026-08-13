"""Three-plane control: ACC-TPC plane/court/magnet (WP-TPC-001)."""

from __future__ import annotations

import inspect
from decimal import Decimal
from pathlib import Path

import pytest

from corp_harness import runtime_engine as tre
from corp_harness.contracts import ContractError
from corp_harness.model import Program, digest_path


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
