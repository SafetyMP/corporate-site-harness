"""ADR-EX-001 execution targets: allowlist, reserved names, isolation is not PASS."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from corp_harness.cli import build_parser
from corp_harness.execution_policy import (
    DENIAL_EXECUTION_TARGET,
    DENIAL_SUBCONTRACTOR_CEILING,
    route_model,
    validate_packet_attestation,
)
from corp_harness.execution_target import (
    DEFAULT_EXECUTION_TARGET,
    FORBIDDEN_CLI_RUNTIME_TOKENS,
    assert_legal_site_path,
    load_and_execute_deny_case,
    parse_execution_target,
    validate_packet_execution_target,
)
from corp_harness.model import ContractError, Program
from corp_harness.site_gate_oracles import inventory_missing_cells


def _sealed(**overrides: object) -> dict:
    packet = {
        "role": "site-specialist",
        "packet_id": "WP-EX-001",
        "root": "/tmp/factory-site",
        "write_set": ["src/corp_harness/execution_target.py"],
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


def test_EX_001_omitted_and_empty_mean_worktree() -> None:
    assert parse_execution_target(None) == (DEFAULT_EXECUTION_TARGET, None)
    assert parse_execution_target("") == (DEFAULT_EXECUTION_TARGET, None)
    assert parse_execution_target("   ") == (DEFAULT_EXECUTION_TARGET, None)
    admitted = validate_packet_execution_target(_sealed())
    assert admitted["ok"] is True
    assert admitted["execution_target"] == "worktree"


def test_EX_001_known_tokens_and_openshell_grammar() -> None:
    for token in ("worktree", "isolated_copy", "cloud_subagent", "openshell:my-app"):
        result = validate_packet_execution_target(_sealed(execution_target=token))
        assert result["ok"] is True
        assert result["execution_target"] == token


def test_EX_DENY_005_unknown_token_fails_closed() -> None:
    result = validate_packet_execution_target(_sealed(execution_target="vercel"))
    assert result["ok"] is False
    assert result["deny_id"] == "EX-DENY-005"
    assert result["denial_code"] == DENIAL_EXECUTION_TARGET
    attested = validate_packet_attestation(_sealed(execution_target="e2b"))
    assert attested["ok"] is False
    assert attested["denial_code"] == DENIAL_EXECUTION_TARGET
    routed = route_model(
        role="site-specialist",
        task_class="packet_implement",
        packet=_sealed(execution_target="daytona"),
    )
    assert routed["ok"] is False
    assert routed["denial_code"] == DENIAL_EXECUTION_TARGET


def test_EX_DENY_006_reserved_openshell_names() -> None:
    for name in ("hermes", "pi", "eval", "HERMES", "openshell:eval"):
        token = name if name.startswith("openshell:") else f"openshell:{name}"
        result = validate_packet_execution_target(_sealed(execution_target=token))
        assert result["ok"] is False
        assert result["deny_id"] == "EX-DENY-006"


def test_EX_DENY_003_reserved_site_path(tmp_path: Path) -> None:
    site = tmp_path / "hermes"
    site.mkdir()
    with pytest.raises(ContractError, match="reserved"):
        Program.create("demo", site, program_root=tmp_path / "corp")
    alias = tmp_path / "innocuous"
    alias.symlink_to(site)
    with pytest.raises(ContractError, match="reserved"):
        assert_legal_site_path(alias)
    packet = _sealed(site_path=str(tmp_path / "eval"))
    (tmp_path / "eval").mkdir()
    denied = validate_packet_execution_target(packet)
    assert denied["ok"] is False
    assert denied["deny_id"] == "EX-DENY-003"


def test_EX_DENY_007_cloud_subagent_cannot_write_corporate_root() -> None:
    result = validate_packet_execution_target(
        _sealed(
            execution_target="cloud_subagent",
            write_set=["program.json", "gates.json"],
            program_root="/tmp/corp",
            root="/tmp/corp",
        )
    )
    assert result["ok"] is False
    assert result["deny_id"] == "EX-DENY-007"


def test_EX_DENY_001_isolation_green_is_not_named_gate_pass() -> None:
    result = validate_packet_execution_target(
        _sealed(pass_claim="sandbox green, gate PASS")
    )
    assert result["ok"] is False
    assert result["deny_id"] == "EX-DENY-001"


def test_EX_DENY_001_dummy_oracle_digest_is_not_hall_pass() -> None:
    prose = validate_packet_execution_target(
        _sealed(
            pass_claim="sandbox green, named-gate PASS",
            oracle_collect_digest="deadbeef",
        )
    )
    assert prose["ok"] is False
    assert prose["deny_id"] == "EX-DENY-001"
    flagged = validate_packet_execution_target(
        _sealed(
            named_gate_pass_from_isolation=True,
            oracle_collect_digest="deadbeef",
        )
    )
    assert flagged["ok"] is False
    assert flagged["deny_id"] == "EX-DENY-001"


def test_EX_DENY_002_packet_actor_user_field() -> None:
    result = validate_packet_execution_target(_sealed(actor="user", autopilot=True))
    assert result["ok"] is False
    assert result["deny_id"] == "EX-DENY-002"


def test_EX_DENY_004_connect_command_editor_cursor() -> None:
    result = validate_packet_execution_target(
        _sealed(
            execution_target="openshell:my-app",
            connect_command="openshell sandbox connect my-app --editor cursor",
        )
    )
    assert result["ok"] is False
    assert result["deny_id"] == "EX-DENY-004"


def test_EX_001_reviewer_independent_review_requires_isolated_copy() -> None:
    missing = validate_packet_execution_target(
        _sealed(role="operations-excellence", task_class="independent_review")
    )
    assert missing["ok"] is False
    ok = validate_packet_execution_target(
        _sealed(
            role="operations-excellence",
            task_class="independent_review",
            execution_target="isolated_copy",
            write_set=["evidence/oracle.txt"],
        )
    )
    assert ok["ok"] is True
    follow = validate_packet_execution_target(
        _sealed(
            role="corporate-adversary",
            task_class="independent_review",
            execution_target="cloud_subagent",
        )
    )
    assert follow["ok"] is False


def test_EX_001_corporate_role_non_worktree_denied() -> None:
    result = validate_packet_execution_target(
        _sealed(role="corporate-ceo", execution_target="cloud_subagent")
    )
    assert result["ok"] is False


def test_EX_004_no_sandbox_runtime_in_cli() -> None:
    names: list[str] = []

    def collect(parser: argparse.ArgumentParser) -> None:
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                names.extend(action.choices)
                for sub in action.choices.values():
                    collect(sub)

    collect(build_parser())
    lowered = {name.casefold() for name in names}
    assert not (lowered & FORBIDDEN_CLI_RUNTIME_TOKENS)


def test_EX_004_sandbox_fallback_stays_oos() -> None:
    report = {
        "cells": [
            {"taxonomy": "sandbox_fallback", "verdict": "OOS"},
        ],
        "missing_cells": [],
    }
    assert "sandbox_fallback" not in inventory_missing_cells(report)


def test_EX_010_ceilings_unchanged_vm_is_depth_one_placement() -> None:
    depth = route_model(
        role="site-specialist",
        task_class="packet_implement",
        packet=_sealed(execution_target="cloud_subagent", depth=2),
    )
    assert depth["ok"] is False
    assert depth["denial_code"] == DENIAL_SUBCONTRACTOR_CEILING


_DENY_DIR = Path(__file__).resolve().parent / "fixtures/site-gate-oracles/deny-cases"
_REQUIRED_EX_DENY = tuple(f"EX-DENY-00{index}" for index in range(1, 8))


def _execute_ex_deny(deny_id: str) -> None:
    result = load_and_execute_deny_case(_DENY_DIR / f"{deny_id}.json")
    assert result["executed"] is True
    assert result["denied"] is True
    assert result["expected"] == "deny"
    assert result["id"] == deny_id


def test_EX_DENY_001_sandbox_prose_as_pass() -> None:
    _execute_ex_deny("EX-DENY-001")


def test_EX_DENY_002_autopilot_as_actor_user() -> None:
    _execute_ex_deny("EX-DENY-002")


def test_EX_DENY_003_reserved_names_as_site_path() -> None:
    _execute_ex_deny("EX-DENY-003")


def test_EX_DENY_004_cursor_remote_into_openshell() -> None:
    _execute_ex_deny("EX-DENY-004")


def test_EX_DENY_005_unknown_execution_target() -> None:
    _execute_ex_deny("EX-DENY-005")


def test_EX_DENY_006_openshell_reserved_names() -> None:
    _execute_ex_deny("EX-DENY-006")


def test_EX_DENY_007_cloud_subagent_corporate_root_write() -> None:
    _execute_ex_deny("EX-DENY-007")


def test_EX_DENY_collect_all_executed() -> None:
    missing = [
        deny_id
        for deny_id in _REQUIRED_EX_DENY
        if not (_DENY_DIR / f"{deny_id}.json").is_file()
    ]
    assert missing == []
    for deny_id in _REQUIRED_EX_DENY:
        _execute_ex_deny(deny_id)
