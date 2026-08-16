"""Tests for premium model spend controls."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from corp_harness.cli import dispatch
from corp_harness.execution_policy import (
    DENIAL_PREMIUM_MODEL_POLICY,
    ESCALATION_SCHEMA,
    attest_model_use,
    check_evidence_age,
    default_execution_policy,
    route_model,
    validate_execution_policy,
    validate_packet_attestation,
)
from corp_harness.model import ContractError, Program


def _ns(**kwargs):
    from argparse import Namespace

    return Namespace(**kwargs)


def escalation(task_class: str = "hard_implement") -> dict:
    return {
        "schema": ESCALATION_SCHEMA,
        "authorized": True,
        "task_class": task_class,
        "reason": "complexity warrants premium",
        "id": "esc-1",
    }


def _sealed(packet: dict, **overrides: object) -> dict:
    sealed = {
        "role": "site-specialist",
        "packet_id": "WP-TEST",
        "root": "/tmp/site",
        "write_set": ["src/corp_harness/cli.py"],
        "routed_model": str(packet.get("model_id") or "composer-2.5"),
        "success_schema": "pytest exit 0",
        "halt_conditions": ["Would treat Sol as ceiling bypass"],
        **packet,
        **overrides,
    }
    return sealed


def test_default_policy_validates() -> None:
    policy = validate_execution_policy(default_execution_policy())
    assert policy["schema"].endswith("/v1")
    assert "hard_implement" in policy["premium_allowlist"]


def test_unknown_policy_field_rejected() -> None:
    raw = default_execution_policy()
    raw["unexpected"] = True
    with pytest.raises(ContractError, match="unknown fields"):
        validate_execution_policy(raw)


def test_route_recapture_is_fast() -> None:
    result = route_model(role="operations-excellence", task_class="evidence_recapture")
    assert result["model_class"] == "fast"
    assert result["requires_escalation"] is False
    assert result["allowed_model_ids"][0].startswith("cursor-grok") or "grok" in result[
        "allowed_model_ids"
    ][0]


def test_route_defaults_prioritize_grok_and_composer() -> None:
    fast = route_model(role="site-manager", task_class="design_review")
    assert fast["model_class"] == "fast"
    assert "grok" in fast["allowed_model_ids"][0]
    standard = route_model(role="site-specialist", task_class="packet_implement")
    assert standard["model_class"] == "standard"
    assert standard["allowed_model_ids"][0].startswith("composer")


def test_route_hard_implement_requires_escalation() -> None:
    result = route_model(role="site-specialist", task_class="hard_implement")
    assert result["model_class"] == "premium"
    assert result["requires_escalation"] is True


def test_route_remediate_stays_standard_until_failures() -> None:
    first = route_model(role="site-specialist", task_class="remediate")
    assert first["model_class"] == "standard"
    promoted = route_model(
        role="site-specialist",
        task_class="remediate",
        failed_standard_attempts=2,
        escalation=escalation("remediate"),
    )
    assert promoted["model_class"] == "premium"


def test_attest_premium_recapture_fails() -> None:
    result = attest_model_use(
        model_id="gpt-5.6-sol-max",
        model_class="premium",
        task_class="evidence_recapture",
    )
    assert result["ok"] is False
    assert result["denial_code"] == DENIAL_PREMIUM_MODEL_POLICY


def test_attest_premium_hard_implement_with_escalation_passes() -> None:
    result = attest_model_use(
        model_id="gpt-5.6-sol-max",
        model_class="premium",
        task_class="hard_implement",
        escalation=escalation(),
    )
    assert result["ok"] is True
    assert result["denial_code"] is None


def test_attest_fable_alias_is_premium() -> None:
    result = attest_model_use(
        model_id="claude-4.6-fable",
        model_class="premium",
        task_class="hard_implement",
        escalation=escalation(),
    )
    assert result["ok"] is True


def test_packet_attestation_fixture_paths() -> None:
    bad = _sealed(
        {
            "model_id": "gpt-5.6-sol-max",
            "model_class": "premium",
            "task_class": "evidence_recapture",
            "max_mode": True,
        }
    )
    good = _sealed(
        {
            "model_id": "gpt-5.6-sol-max",
            "model_class": "premium",
            "task_class": "hard_implement",
            "max_mode": True,
            "escalation": escalation(),
        }
    )
    assert validate_packet_attestation(bad)["ok"] is False
    assert validate_packet_attestation(good)["ok"] is True


def test_evidence_max_age() -> None:
    # TPC-CUT-004: wall-clock age alone never hard-denies evidence.
    now = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
    fresh = (now - timedelta(seconds=10)).isoformat().replace("+00:00", "Z")
    stale = (now - timedelta(seconds=301)).isoformat().replace("+00:00", "Z")
    assert check_evidence_age(fresh, now=now)["ok"] is True
    stale_result = check_evidence_age(stale, now=now)
    assert stale_result["ok"] is True
    assert stale_result["denial_code"] is None
    assert stale_result["aged"] is True
    assert stale_result["age_seconds"] > stale_result["max_age_seconds"]


def test_program_persists_execution_policy(tmp_path: Path) -> None:
    root = tmp_path / "corp"
    site = tmp_path / "site"
    root.mkdir()
    site.mkdir()
    program = Program.create("policy-pilot", site, ["quality"], program_root=root)
    program.execution_policy = default_execution_policy()
    path = root / "program.json"
    program.save(path)
    loaded = Program.load(path)
    assert loaded.execution_policy is not None
    assert loaded.execution_policy["evidence_max_age_seconds"] == 300
    # USD budget hard-stop fields are not harness control defaults.
    budget = loaded.execution_policy.get("budget") or {}
    assert "premium_usd_hard" not in budget
    assert "recorded_premium_usd" not in budget


def test_cli_route_model_and_attest(tmp_path: Path) -> None:
    root = tmp_path / "corp"
    site = tmp_path / "site"
    root.mkdir()
    site.mkdir()
    program = Program.create("cli-policy", site, program_root=root)
    program.save(root / "program.json")

    routed, code = dispatch(
        _ns(
            command="route-model",
            root=root,
            role="site-specialist",
            task_class="evidence_recapture",
            packet=None,
            escalation=None,
            failed_standard_attempts=0,
            max_mode=False,
        )
    )
    assert code == 0
    assert routed["model_class"] == "fast"

    packet_path = root / "bad-packet.json"
    packet_path.write_text(
        json.dumps(
            _sealed(
                {
                    "model_id": "gpt-5.6-sol-max",
                    "model_class": "premium",
                    "task_class": "evidence_recapture",
                }
            )
        )
        + "\n",
        encoding="utf-8",
    )
    checked, check_code = dispatch(
        _ns(
            command="check",
            root=root,
            run=None,
            cwd=None,
            timeout=120,
            output=None,
            apply=False,
            attest_packet=packet_path,
            evidence_captured_at=None,
            argv=[],
        )
    )
    assert check_code == 1
    assert checked["denial_code"] == DENIAL_PREMIUM_MODEL_POLICY

    good = root / "good-packet.json"
    good.write_text(
        json.dumps(
            _sealed(
                {
                    "model_id": "gpt-5.6-sol-max",
                    "model_class": "premium",
                    "task_class": "hard_implement",
                    "escalation": escalation(),
                }
            )
        )
        + "\n",
        encoding="utf-8",
    )
    ok_checked, ok_code = dispatch(
        _ns(
            command="check",
            root=root,
            run=None,
            cwd=None,
            timeout=120,
            output=None,
            apply=False,
            attest_packet=good,
            evidence_captured_at=None,
            argv=[],
        )
    )
    assert ok_code == 0
    assert ok_checked["attestation"]["ok"] is True


def test_cli_usage_record_requires_user(tmp_path: Path) -> None:
    # ACC-TPC-LEGAL-003 / TPC-CUT-002: invoice/usage is refused as a control
    # surface. --actor user cannot unlock invoice writes (reserved for FA /
    # user_approval / recover-chain). Non-user actors also cannot record.
    root = tmp_path / "corp"
    site = tmp_path / "site"
    root.mkdir()
    site.mkdir()
    Program.create("usage-pilot", site, program_root=root).save(root / "program.json")
    with pytest.raises(ContractError, match="refuses --actor user"):
        dispatch(
            _ns(
                command="usage",
                usage_command="record",
                root=root,
                actor="user",
                amount_usd=10.0,
                source="invoice",
                note="",
                apply=True,
            )
        )
    with pytest.raises(ContractError, match="removed from harness control surface"):
        dispatch(
            _ns(
                command="usage",
                usage_command="record",
                root=root,
                actor="coo",
                amount_usd=1500.0,
                source="cursor-invoice",
                note="sol",
                apply=True,
            )
        )
    status, status_code = dispatch(_ns(command="status", root=root))
    assert status_code == 0
    summary = status["execution_policy"]
    assert "recorded_premium_usd" not in (summary.get("budget") or {})
    assert (summary.get("budget") or {}).get("state") != "hard"
