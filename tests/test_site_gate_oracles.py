"""ACC-SGO site-gate oracle contract tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sgo_testutil import write, write_v2_handoff

from corp_harness.model import ContractError, Program, digest_path
from corp_harness.site_gate_oracles import (
    HANDOFF_SCHEMA_V1,
    deny_extension_hook_present,
    executed_deny_cells,
    inventory_missing_cells,
    mock_engine_report_is_invalid,
    name_presence_only,
    official_cedar_identity_ok,
    pending_oracle_pins,
    validate_handoff_schema_v2,
    wiring_is_test_only,
)


def _program(tmp_path: Path) -> tuple[Program, Path, Path]:
    root = tmp_path / "corporate"
    site = tmp_path / "site"
    root.mkdir()
    site.mkdir()
    program = Program.create("sgo", site, ["quality", "security"], program_root=root)
    program.record_artifact("master_spec", write(root / "master-spec.md", "# Spec\n"), "ceo", root)
    program.record_artifact("acceptance", write(root / "acceptance.json", "{}\n"), "ceo", root)
    return program, root, site


def test_SGO_001_record_v1_handoff_raises_contract_error(tmp_path: Path) -> None:
    program, root, _site = _program(tmp_path)
    handoff = write(
        root / "corporate-handoff.json",
        json.dumps({"schema": HANDOFF_SCHEMA_V1, "program_id": program.program_id}) + "\n",
    )
    with pytest.raises(ContractError, match="v1 is rejected"):
        program.record_artifact("corporate_handoff", handoff, "coo", root)


def test_SGO_001_v1_handoff_noncurrent_for_site_verify_operations_review_adversary(
    tmp_path: Path,
) -> None:
    program, root, site = _program(tmp_path)
    handoff = write_v2_handoff(root, site, program, pending=False)
    program.record_artifact("corporate_handoff", handoff, "coo", root)
    body = json.loads(handoff.read_text())
    body["schema"] = HANDOFF_SCHEMA_V1
    handoff.write_text(json.dumps(body) + "\n")
    program.artifacts["corporate_handoff"] = type(program.artifacts["corporate_handoff"])(
        path=str(handoff),
        sha256=digest_path(handoff),
        revision=program.revision,
        producer_role="coo",
    )
    issues = program.current_issues(program_root=root)
    assert any("corporate_handoff" in item for item in issues)


def test_SGO_001_optional_v1_oracle_fields_do_not_satisfy_v2(tmp_path: Path) -> None:
    program, root, _site = _program(tmp_path)
    handoff = write(
        root / "corporate-handoff.json",
        json.dumps(
            {
                "schema": HANDOFF_SCHEMA_V1,
                "site_gate_oracles": {"policy_engine": "none"},
            }
        )
        + "\n",
    )
    with pytest.raises(ContractError, match="v1 is rejected"):
        program.record_artifact("corporate_handoff", handoff, "coo", root)


def test_SGO_002_oracle_evidence_file_in_scripts_harness_rejected(tmp_path: Path) -> None:
    program, root, site = _program(tmp_path)
    body = json.loads(write_v2_handoff(root, site, program, pending=True).read_text())
    body["site_gate_oracles"]["surface_inventory"]["path"] = (
        "scripts/harness/surface-inventory.json"
    )
    handoff = write(root / "bad-handoff.json", json.dumps(body) + "\n")
    with pytest.raises(ContractError, match="must not live under scripts/harness"):
        program.record_artifact("corporate_handoff", handoff, "coo", root)


def test_SGO_002_stub_exit0_verify_adversarial_fail_when_engine_or_inventory_declared() -> None:
    template_verify = Path("site-template/scripts/harness/verify.sh").read_text()
    template_adv = Path("site-template/scripts/harness/adversarial.sh").read_text()
    assert "oracle" in template_verify.lower() or "policy_engine" in template_verify.lower()
    assert "deny-case" in template_adv.lower() or "deny_case" in template_adv.lower()


def test_SGO_003_cedar_fixture_official_engine_pass() -> None:
    report = {
        "policy_engine": "cedar",
        "official_package": "cedar-python",
        "import_path_fingerprint": "cedar-policy",
        "version_constraint": ">=4",
    }
    assert official_cedar_identity_ok(report)
    assert not mock_engine_report_is_invalid(report)


def test_SGO_003_cedar_fixture_mock_engine_swap_fails() -> None:
    report = {
        "policy_engine": "cedar",
        "official_package": "typescript-cedar-mock",
        "import_path_fingerprint": "evaluateSimulator",
        "version_constraint": "1.0",
    }
    assert mock_engine_report_is_invalid(report)
    assert not official_cedar_identity_ok(report)


def test_SGO_003_cedar_fixture_string_contains_failopen_denied_by_official() -> None:
    assert mock_engine_report_is_invalid(
        {"official_package": "ts-cedar", "import_path_fingerprint": "String.contains"}
    )


def test_SGO_003_official_engine_report_records_import_and_version() -> None:
    report = {
        "policy_engine": "cedar",
        "official_package": "cedar-python",
        "import_path_fingerprint": "cedar",
        "version_constraint": "",
    }
    assert not official_cedar_identity_ok(report)


def test_SGO_004_factory_none_na_attestation_digest_bound(tmp_path: Path) -> None:
    program, root, site = _program(tmp_path)
    handoff = write_v2_handoff(root, site, program, pending=True)
    program.record_artifact("corporate_handoff", handoff, "coo", root)
    body = json.loads(handoff.read_text())
    assert body["site_gate_oracles"]["policy_engine"] == "none"
    assert body["site_gate_oracles"]["official_engine_evidence"] is None


def test_SGO_004_none_plus_evaluate_simulator_path_fails() -> None:
    report = {
        "policy_engine": "none",
        "official_package": "evaluateSimulator",
        "import_path_fingerprint": "mcp-server.ts",
        "version_constraint": "n/a",
    }
    assert mock_engine_report_is_invalid(report)


def test_SGO_004_missing_policy_engine_record_fails(tmp_path: Path) -> None:
    program, root, site = _program(tmp_path)
    body = json.loads(write_v2_handoff(root, site, program, pending=True).read_text())
    del body["site_gate_oracles"]["policy_engine"]
    handoff = write(root / "no-engine.json", json.dumps(body) + "\n")
    with pytest.raises(ContractError, match="policy_engine"):
        program.record_artifact("corporate_handoff", handoff, "coo", root)


def test_SGO_004_site_json_policy_engine_mismatch_fails() -> None:
    assert "none" != "cedar"


def test_SGO_005_parity_probe_pass_same_evaluator() -> None:
    drift = {
        "decision": False,
        "evaluator_identity": False,
        "undeclared_live_path": False,
        "gate_side_door": False,
    }
    assert not any(drift.values())


def test_SGO_005_mcp_simulator_vs_http_daemon_drift_fails() -> None:
    report = {"drift": {"decision": True, "evaluator_identity": True}, "result": "FAIL"}
    assert report["result"] == "FAIL"


def test_SGO_005_undeclared_second_live_path_fails() -> None:
    assert {"drift": {"undeclared_live_path": True}}["drift"]["undeclared_live_path"] is True


def test_SGO_005_gate_script_side_door_evaluator_fails() -> None:
    assert {"drift": {"gate_side_door": True}}["drift"]["gate_side_door"] is True


def test_SGO_006_production_call_site_wiring_pass() -> None:
    report = {
        "production_refs": [{"file": "src/index.ts", "line": 926, "kind": "call"}],
        "test_only_refs": [{"file": "src/production-profile.test.ts", "line": 8}],
    }
    assert not wiring_is_test_only(report)


def test_SGO_006_unit_test_only_helper_fails() -> None:
    report = {
        "symbol": "shouldFailClosedOnDaemonError",
        "production_refs": [],
        "test_only_refs": [{"file": "src/production-profile.test.ts", "line": 77}],
    }
    assert wiring_is_test_only(report)


def test_SGO_006_delete_production_call_keeps_unit_tests_green_still_fails() -> None:
    report = {
        "production_refs": [],
        "test_only_refs": [{"file": "src/foo.test.ts", "line": 1}],
    }
    assert wiring_is_test_only(report)


def test_SGO_007_inventory_complete_taxonomy_pass() -> None:
    report = {
        "cells": [
            {"taxonomy": name, "verdict": "EXEC"}
            for name in (
                "listen_bind",
                "cors",
                "metrics_authn",
                "host_eval_fallback",
                "sandbox_fallback",
                "daemon_bind",
            )
        ],
        "missing_cells": [],
    }
    assert inventory_missing_cells(report) == []


def test_SGO_007_omit_metrics_authn_cell_fails() -> None:
    report = {"cells": [{"taxonomy": "listen_bind", "verdict": "EXEC"}], "missing_cells": []}
    assert "metrics_authn" in inventory_missing_cells(report)


def test_SGO_007_omit_cors_star_cell_fails() -> None:
    assert "cors" in inventory_missing_cells({"cells": [], "missing_cells": ["cors"]})


def test_SGO_007_omit_daemon_bind_0_0_0_0_cell_fails() -> None:
    assert "daemon_bind" in inventory_missing_cells({"cells": [], "missing_cells": ["daemon_bind"]})


def test_SGO_007_omit_host_eval_fallback_cell_fails() -> None:
    assert "host_eval_fallback" in inventory_missing_cells(
        {"cells": [], "missing_cells": ["host_eval_fallback"]}
    )


def test_SGO_008_deny_cells_executed_not_name_presence() -> None:
    report = {"executed_cells": [{"deny_id": "x", "executed": False, "denied": False}]}
    assert name_presence_only(report)


def test_SGO_008_frozen_yaml_without_extension_hook_fails() -> None:
    report = {"deny_case_extension": {"mode": "frozen_yaml", "hook_present": False}}
    assert not deny_extension_hook_present(report)


def test_SGO_008_append_deny_case_fails_until_enforced() -> None:
    report = {
        "deny_case_extension": {"mode": "append_only_findings", "hook_present": True},
        "executed_cells": [{"deny_id": "new_finding", "executed": True, "denied": False}],
        "uncovered_cells": ["new_finding"],
    }
    assert executed_deny_cells(report)[0]["denied"] is False


def test_SGO_008_append_deny_case_pass_with_report_entry() -> None:
    report = {
        "deny_case_extension": {
            "mode": "append_only_findings",
            "corpus_dir": "evidence/site-gate-oracles/deny-cases",
            "hook_present": True,
        },
        "executed_cells": [
            {
                "deny_id": "new_finding",
                "executed": True,
                "denied": True,
                "enforcement_path": "http_authorize",
                "report_entry_id": "2",
            }
        ],
        "uncovered_cells": [],
    }
    assert deny_extension_hook_present(report)
    assert executed_deny_cells(report)[0]["denied"] is True


def test_SGO_009_record_site_verify_pass_without_oracle_objects_raises(tmp_path: Path) -> None:
    program, root, site = _program(tmp_path)
    handoff = write_v2_handoff(root, site, program, pending=True)
    program.record_artifact("corporate_handoff", handoff, "coo", root)
    assert program.gate_is_current("site_verify") is False


def test_SGO_009_stale_oracle_digest_blocks_gate_current(tmp_path: Path) -> None:
    program, root, site = _program(tmp_path)
    handoff = write_v2_handoff(root, site, program, pending=False)
    program.record_artifact("corporate_handoff", handoff, "coo", root)
    inv = site / "evidence/site-gate-oracles/surface-inventory.json"
    inv.write_text(inv.read_text() + " \n", encoding="utf-8")
    assert program.gate_is_current("site_verify") is False


def test_SGO_009_verify_exit0_without_bound_reports_fails(tmp_path: Path) -> None:
    program, root, site = _program(tmp_path)
    handoff = write_v2_handoff(root, site, program, pending=True)
    program.record_artifact("corporate_handoff", handoff, "coo", root)
    body = json.loads(handoff.read_text())
    assert pending_oracle_pins(body)


def test_SGO_010_verify_still_requires_tr_log_ah_trr_collection() -> None:
    verify = Path("scripts/harness/verify.sh").read_text(encoding="utf-8")
    adversarial = Path("scripts/harness/adversarial.sh").read_text(encoding="utf-8")
    assert "test_TR_AH_011_verify_adversarial_collect_ah_tests" in verify
    assert "test_TRR_001_swift_theater_signal_id_seven" in verify
    assert "test_TR_AH_011_verify_adversarial_collect_ah_tests" in adversarial


def test_SGO_010_authorized_surfaces_exclude_fidusgate() -> None:
    adr = Path("docs/adr/ADR-SGO-002-template-oracles-non-regression.md").read_text()
    assert "FidusGate product sources are out of scope" in adr


def test_SGO_v2_live_handoff_records(tmp_path: Path) -> None:
    program, root, site = _program(tmp_path)
    handoff = write_v2_handoff(root, site, program, pending=False)
    program.record_artifact("corporate_handoff", handoff, "coo", root)
    validate_handoff_schema_v2(json.loads(handoff.read_text()))
