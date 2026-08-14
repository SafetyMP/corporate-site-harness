"""P0/P1/P2 gov assist: ACC-SG-001..004, ACC-P0/P1/P2-001."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sgo_testutil import write_v2_handoff

from corp_harness.cli import build_parser, main
from corp_harness.model import Gate, Program, digest_path
from corp_harness.runtime_engine import ALWAYS_FORCE_HEAVY_ACTIONS, route_for_action
from corp_harness.swift_gov import (
    GOV_ASSIST_UNAVAILABLE,
    GOV_REQUIRED,
    build_assist_payload,
    build_write_receipt_payload,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "governance"
STUB = FIXTURES / "corp-gov-check-stub"
MANIFEST = FIXTURES / "manifest.json"


def _write(path: Path, value: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return path


@pytest.fixture
def gov_stub_env(monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("CORP_GOV_CHECK", str(STUB))
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[1] / "src"))
    return STUB


def _factory_layout(tmp_path: Path) -> tuple[Path, Path]:
    factory = tmp_path / "factory"
    root = tmp_path / "corporate"
    factory.mkdir()
    root.mkdir()
    (factory / "src" / "corp_harness").mkdir(parents=True)
    (factory / "corporate" / "plugin" / "corporate-site-harness").mkdir(parents=True)
    return factory, root


def _review_only_ca_report(program: Program, root: Path) -> Path:
    target_sha256 = program.gate_target_digest("corporate_acceptance")
    review = _write(
        root / "evidence" / "corporate_acceptance-review.json",
        json.dumps(
            {
                "schema": "corporate-site-review-evidence/v1",
                "reviewer": "coo",
                "revision": program.revision,
                "verdict": "PASS",
                "target_sha256": target_sha256,
            }
        )
        + "\n",
    )
    report = {
        "schema": "corporate-site-gate/v1",
        "gate": "corporate_acceptance",
        "reviewer_role": "coo",
        "status": "PASS",
        "revision": program.revision,
        "target_sha256": target_sha256,
        "evidence_refs": [{"path": str(review), "sha256": digest_path(review)}],
    }
    return _write(root / "corporate_acceptance-gate.json", json.dumps(report) + "\n")


def _review_only_ca_program(tmp_path: Path) -> tuple[Program, Path, Path]:
    """Hand-craft Stage-2 review-only CA PASS (loadable, not current)."""
    factory, root = _factory_layout(tmp_path)
    program = Program.create(
        "gov-assist-pilot",
        factory,
        ["platform"],
        program_root=root,
        program_kind="factory",
    )
    master = _write(root / "master-spec.md", "# Spec\n")
    acceptance = _write(root / "acceptance.json", "{}\n")
    program.record_artifact("master_spec", master, "ceo", root)
    program.record_artifact("acceptance", acceptance, "ceo", root)
    auth = _write(
        root / "factory-authorization.json",
        json.dumps(
            {
                "schema": "corporate-site-factory-authorization/v1",
                "authorized": True,
                "granted_by": "user",
                "granted_at": "2026-07-19T12:00:00Z",
                "program_id": "gov-assist-pilot",
                "revision": 1,
                "master_spec_sha256": program.artifacts["master_spec"].sha256,
                "factory_root": str(factory.resolve()),
                "authorized_surfaces": ["swift", "src/corp_harness/swift_gov.py"],
            }
        )
        + "\n",
    )
    program.record_artifact("factory_authorization", auth, "user", root)
    program.advance("CORPORATE_ACCEPTANCE", "ceo")

    report = _review_only_ca_report(program, root)
    # Bypass record_gate Stage-2 dual-evidence enforcement; persist review-only PASS.
    program.gates["corporate_acceptance"] = Gate(
        status="PASS",
        report_path=str(report.resolve()),
        report_sha256=digest_path(report),
        target_sha256=program.gate_target_digest("corporate_acceptance"),
        revision=program.revision,
        reviewer_role="coo",
    )
    handoff = write_v2_handoff(root, factory, program, pending=True)
    program.record_artifact("corporate_handoff", handoff, "coo", root)
    # Advance without requiring current CA (phase write only for the fixture).
    path = root / "program.json"
    program.phase = "SITE_DELIVERY"
    program.save(path)
    loaded = Program.load(path)
    assert loaded.phase == "SITE_DELIVERY"
    assert loaded.gates["corporate_acceptance"].status == "PASS"
    assert loaded.gate_is_current("corporate_acceptance") is False
    return loaded, root, factory


def test_ACC_P0_001_fixture_digests_pinned() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["schema"] == "corporate-site-gov-fixture-manifest/v1"
    for name, expected in manifest["fixtures"].items():
        path = FIXTURES / name
        assert path.is_file(), name
        assert digest_path(path) == expected, name


def test_GOV_ASSIST_UNAVAILABLE_soft_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    factory, root = _factory_layout(tmp_path)
    assert (
        main(
            [
                "init",
                "--root",
                str(root),
                "--id",
                "softfail",
                "--site",
                str(factory),
                "--kind",
                "factory",
                "--apply",
            ]
        )
        == 0
    )
    capsys.readouterr()
    monkeypatch.delenv("CORP_GOV_CHECK", raising=False)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    # Ensure no accidental discovery under factory checkout during test.
    monkeypatch.setenv("CORP_GOV_CHECK", str(tmp_path / "missing-corp-gov-check"))

    before = digest_path(root / "program.json")
    code = main(["gov", "diagnose", "--root", str(root)])
    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload["error"] == GOV_ASSIST_UNAVAILABLE
    assert payload["mutation"] is False
    assert digest_path(root / "program.json") == before

    # Core paths still succeed without Swift assist.
    assert main(["status", "--root", str(root)]) in {0, 1}
    status_payload = json.loads(capsys.readouterr().out)
    assert "program" in status_payload
    assert digest_path(root / "program.json") == before


def _heavy_gov_stub(tmp_path: Path) -> Path:
    """Minimal corp-gov-check stub for heavy proof commands (validate-action / write-receipt)."""
    script = tmp_path / "corp-gov-check-heavy-stub"
    script.write_text(
        """#!/usr/bin/env python3
import json
import sys
from pathlib import Path

from corp_harness.swift_gov import build_validate_action_payload, build_write_receipt_payload

def main(argv):
    if not argv:
        return 2
    command = argv[0]
    root = None
    action = None
    idx = 1
    while idx < len(argv):
        if argv[idx] == "--root" and idx + 1 < len(argv):
            root = Path(argv[idx + 1])
            idx += 2
            continue
        if argv[idx] == "--action" and idx + 1 < len(argv):
            action = argv[idx + 1]
            idx += 2
            continue
        idx += 1
    if root is None:
        return 2
    if command == "validate-action":
        payload = build_validate_action_payload(root, action or "heavy_validate")
    elif command == "write-receipt":
        payload = build_write_receipt_payload(root)
    else:
        print(json.dumps({"ok": False, "error": f"unsupported: {command}"}))
        return 2
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload.get("ok") else 1

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
""",
        encoding="utf-8",
    )
    script.chmod(0o700)
    return script


def test_gov_help_shows_write_receipt() -> None:
    parser = build_parser()
    help_text = parser.format_help()
    assert "write-receipt" in help_text


def test_write_receipt_seal_non_mutation(tmp_path: Path) -> None:
    factory, root = _factory_layout(tmp_path)
    program = Program.create(
        "write-receipt-pilot",
        factory,
        ["platform"],
        program_root=root,
        program_kind="factory",
    )
    program.save(root / "program.json")
    before = digest_path(root / "program.json")
    payload = build_write_receipt_payload(root)
    assert payload["mutation"] is False
    assert payload["assist"] is False
    assert payload["command"] == "write-receipt"
    assert payload["kind"] == "gov_seal"
    assert payload["action"] == "mint_gov_receipt"
    assert payload["layer"] == "heavy"
    assert payload["verdict"] == "accept"
    assert payload["program_digest"] == before
    assert payload["program_digest_after"] == before
    assert digest_path(root / "program.json") == before


def test_mint_gov_receipt_always_force_at_score_1_0(tmp_path: Path) -> None:
    factory, root = _factory_layout(tmp_path)
    program = Program.create(
        "mint-gov-pilot",
        factory,
        ["platform"],
        program_root=root,
        program_kind="factory",
    )
    program.save(root / "program.json")
    assert "mint_gov_receipt" in ALWAYS_FORCE_HEAVY_ACTIONS
    route = route_for_action(root, "mint_gov_receipt")
    assert route["action_routed_layer"] == "heavy"
    payload = build_write_receipt_payload(root)
    assert payload["layer"] == "heavy"
    assert payload["trust_score"] == 1.0


def test_write_receipt_gov_required_without_swift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    factory, root = _factory_layout(tmp_path)
    program = Program.create(
        "write-receipt-softfail",
        factory,
        ["platform"],
        program_root=root,
        program_kind="factory",
    )
    program.save(root / "program.json")
    before = digest_path(root / "program.json")
    monkeypatch.setenv("CORP_GOV_CHECK", str(tmp_path / "missing-corp-gov-check"))
    code = main(["gov", "write-receipt", "--root", str(root)])
    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload["error"] == GOV_REQUIRED
    assert payload["command"] == "write-receipt"
    assert payload["mutation"] is False
    assert digest_path(root / "program.json") == before


def test_write_receipt_cli_via_heavy_stub(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    factory, root = _factory_layout(tmp_path)
    program = Program.create(
        "write-receipt-cli",
        factory,
        ["platform"],
        program_root=root,
        program_kind="factory",
    )
    program.save(root / "program.json")
    stub = _heavy_gov_stub(tmp_path)
    monkeypatch.setenv("CORP_GOV_CHECK", str(stub))
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[1] / "src"))
    before = digest_path(root / "program.json")
    code = main(["gov", "write-receipt", "--root", str(root)])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0, payload
    assert payload["ok"] is True
    assert payload["command"] == "write-receipt"
    assert payload["action"] == "mint_gov_receipt"
    assert payload["kind"] == "gov_seal"
    assert payload["layer"] == "heavy"
    assert payload["mutation"] is False
    assert payload["program_digest"] == before
    assert digest_path(root / "program.json") == before


def test_write_receipt_assist_unavailable_not_used_for_heavy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    """Heavy write-receipt must fail GOV_REQUIRED, not GOV_ASSIST_UNAVAILABLE."""
    factory, root = _factory_layout(tmp_path)
    program = Program.create(
        "write-receipt-heavy-fail",
        factory,
        ["platform"],
        program_root=root,
        program_kind="factory",
    )
    program.save(root / "program.json")
    monkeypatch.setenv("CORP_GOV_CHECK", str(tmp_path / "missing-corp-gov-check"))
    code = main(["gov", "write-receipt", "--root", str(root)])
    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload["error"] == GOV_REQUIRED
    assert payload["error"] != GOV_ASSIST_UNAVAILABLE


def test_write_receipt_empty_stdout_gov_required(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    """Heavy write-receipt with empty corp-gov-check stdout is GOV_REQUIRED."""
    factory, root = _factory_layout(tmp_path)
    program = Program.create(
        "write-receipt-empty-stdout",
        factory,
        ["platform"],
        program_root=root,
        program_kind="factory",
    )
    program.save(root / "program.json")
    stub = tmp_path / "empty-stdout-write-receipt"
    stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    stub.chmod(0o700)
    monkeypatch.setenv("CORP_GOV_CHECK", str(stub))
    code = main(["gov", "write-receipt", "--root", str(root)])
    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload["error"] == GOV_REQUIRED
    assert payload.get("assist") is False


def test_ACC_SG_001_assist_non_mutation(gov_stub_env: Path, tmp_path: Path, capsys) -> None:
    program, root, _factory = _review_only_ca_program(tmp_path)
    path = root / "program.json"
    before = digest_path(path)
    before_phase = program.phase

    for command in (
        ["gov", "diagnose", "--root", str(root)],
        ["gov", "scaffold-approval", "--root", str(root)],
        ["gov", "scaffold-factory-auth", "--root", str(root)],
        ["gov", "explain-transition", "--root", str(root), "--to", "SITE_VERIFICATION"],
    ):
        code = main(command)
        payload = json.loads(capsys.readouterr().out)
        assert code == 0, payload
        assert payload["ok"] is True
        assert payload["assist"] is True
        assert payload["mutation"] is False
        assert payload["phase_unchanged"] is True
        assert payload["program_digest"] == before
        assert payload["program_digest_after"] == before
        assert digest_path(path) == before
        assert Program.load(path).phase == before_phase


def test_ACC_SG_002_review_only_ca_not_current(
    gov_stub_env: Path,
    tmp_path: Path,
    capsys,
) -> None:
    _program, root, _factory = _review_only_ca_program(tmp_path)
    signals = json.loads((FIXTURES / "stage2_review_only_ca_signals.json").read_text())

    assert main(["gov", "diagnose", "--root", str(root)]) == 0
    diagnose = json.loads(capsys.readouterr().out)
    ca = diagnose["diagnosis"]["corporate_acceptance"]
    assert ca["status"] == "PASS"
    assert ca["current"] is False
    assert ca["currentness_mode"] == signals["currentness_mode"]
    assert ca["review_only_pass_not_current"] is True
    assert any("review-only" in reason for reason in ca["reasons"])

    explain_cmd = [
        "gov",
        "explain-transition",
        "--root",
        str(root),
        "--to",
        "SITE_VERIFICATION",
    ]
    assert main(explain_cmd) == 0
    explain = json.loads(capsys.readouterr().out)
    assert explain["transition"]["corporate_acceptance"]["current"] is False
    assert explain["transition"]["implies_current_corporate_acceptance_pass"] is False

    assert main(["gov", "scaffold-approval", "--root", str(root)]) == 0
    approval = json.loads(capsys.readouterr().out)
    draft = approval["scaffold"]
    assert draft["approved"] is False
    assert draft["implies_current_corporate_acceptance_pass"] is False
    assert draft["corporate_acceptance_current"] is False
    assert approval["grants_authorization"] is False

    assert main(["gov", "scaffold-factory-auth", "--root", str(root)]) == 0
    factory_auth = json.loads(capsys.readouterr().out)
    fdraft = factory_auth["scaffold"]
    assert fdraft["authorized"] is False
    assert fdraft["implies_current_corporate_acceptance_pass"] is False
    assert fdraft["corporate_acceptance_current"] is False
    assert factory_auth["grants_authorization"] is False


def test_ACC_P0_001_scaffold_and_explain_commands(
    gov_stub_env: Path,
    tmp_path: Path,
    capsys,
) -> None:
    _program, root, _factory = _review_only_ca_program(tmp_path)
    approval_fixture = json.loads((FIXTURES / "scaffold_approval_draft.json").read_text())
    factory_fixture = json.loads((FIXTURES / "scaffold_factory_auth_draft.json").read_text())

    assert main(["gov", "scaffold-approval", "--root", str(root)]) == 0
    approval = json.loads(capsys.readouterr().out)["scaffold"]
    for key, value in approval_fixture.items():
        assert approval[key] == value

    assert main(["gov", "scaffold-factory-auth", "--root", str(root)]) == 0
    factory_payload = json.loads(capsys.readouterr().out)
    factory_auth = factory_payload["scaffold"]
    for key, value in factory_fixture.items():
        assert factory_auth[key] == value
    assert factory_payload["grants_authorization"] is False

    explain_cmd = [
        "gov",
        "explain-transition",
        "--root",
        str(root),
        "--to",
        "SITE_VERIFICATION",
    ]
    assert main(explain_cmd) == 0
    explain = json.loads(capsys.readouterr().out)
    assert explain["command"] == "explain-transition"
    assert explain["transition"]["from_phase"] == "SITE_DELIVERY"
    assert explain["transition"]["to_phase"] == "SITE_VERIFICATION"
    assert explain["transition"]["required_actor"] == "site-manager"


def test_gov_assist_direct_payload_matches_cli(gov_stub_env: Path, tmp_path: Path, capsys) -> None:
    _program, root, _factory = _review_only_ca_program(tmp_path)
    direct = build_assist_payload("diagnose", root)
    assert main(["gov", "diagnose", "--root", str(root)]) == 0
    via_cli = json.loads(capsys.readouterr().out)
    assert via_cli["diagnosis"]["corporate_acceptance"]["current"] is False
    assert direct["diagnosis"]["corporate_acceptance"]["current"] is False
    assert via_cli["program_digest"] == direct["program_digest"]


def test_ACC_P1_001_explain_stale_and_check_handoff(
    gov_stub_env: Path,
    tmp_path: Path,
    capsys,
) -> None:
    program, root, _factory = _review_only_ca_program(tmp_path)
    path = root / "program.json"
    before = digest_path(path)
    before_phase = program.phase
    stale_signals = json.loads((FIXTURES / "explain_stale_signals.json").read_text())
    handoff_signals = json.loads((FIXTURES / "check_handoff_signals.json").read_text())

    assert main(["gov", "explain-stale", "--root", str(root)]) == 0
    stale = json.loads(capsys.readouterr().out)
    assert stale["command"] == stale_signals["command"]
    assert stale["mutation"] is False
    assert stale["phase_unchanged"] is True
    assert stale["program_digest"] == before
    assert stale["program_digest_after"] == before
    assert digest_path(path) == before
    assert Program.load(path).phase == before_phase
    report = stale["staleness"]
    assert report["has_stale"] is stale_signals["has_stale"]
    assert report["implies_current_corporate_acceptance_pass"] is False
    assert report["corporate_acceptance"]["current"] is False
    assert report["corporate_acceptance"]["review_only_pass_not_current"] is True
    assert any(
        item["kind"] == "gate" and item["name"] == stale_signals["expects_gate_item"]
        for item in report["items"]
    )
    assert any("Stage-2" in note for note in report["cascade"])

    assert main(["gov", "check-handoff", "--root", str(root)]) == 0
    handoff = json.loads(capsys.readouterr().out)
    assert handoff["command"] == handoff_signals["command"]
    assert handoff["mutation"] is False
    assert handoff["phase_unchanged"] is True
    assert handoff["program_digest"] == before
    assert handoff["program_digest_after"] == before
    assert digest_path(path) == before
    assert Program.load(path).phase == before_phase
    check = handoff["handoff"]
    assert check["present"] is handoff_signals["present"]
    assert check["file_current"] is handoff_signals["file_current_for_empty_handoff_body"]
    assert check["implies_current_corporate_acceptance_pass"] is False
    assert check["corporate_acceptance"]["current"] is False
    assert check["corporate_acceptance"]["review_only_pass_not_current"] is True
    assert check["stage2_notes"]
    assert any("Stage-2" in note for note in check["stage2_notes"])


def test_explain_stale_detects_mutated_artifact(
    gov_stub_env: Path,
    tmp_path: Path,
    capsys,
) -> None:
    _program, root, _factory = _review_only_ca_program(tmp_path)
    path = root / "program.json"
    before = digest_path(path)
    (root / "master-spec.md").write_text("# Spec\nmutated\n", encoding="utf-8")

    assert main(["gov", "explain-stale", "--root", str(root)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert digest_path(path) == before
    items = payload["staleness"]["items"]
    assert any(item["kind"] == "artifact" and item["name"] == "master_spec" for item in items)


def test_check_handoff_detects_digest_mismatch(
    gov_stub_env: Path,
    tmp_path: Path,
    capsys,
) -> None:
    program, root, _factory = _review_only_ca_program(tmp_path)
    path = root / "program.json"
    before = digest_path(path)
    master_sha = program.artifacts["master_spec"].sha256
    handoff_path = Path(program.artifacts["corporate_handoff"].path)
    handoff_path.write_text(
        json.dumps(
            {
                "schema": "corporate-site-handoff/v1",
                "program_id": program.program_id,
                "revision": program.revision,
                "artifact_digests": {
                    "master_spec": "0" * 64,
                    "acceptance": program.artifacts["acceptance"].sha256,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    # Keep program.json pointing at the old handoff digest so assist sees file stale.
    assert digest_path(handoff_path) != program.artifacts["corporate_handoff"].sha256

    assert main(["gov", "check-handoff", "--root", str(root)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert digest_path(path) == before
    check = payload["handoff"]
    assert check["file_current"] is False
    assert check["integrity_ok"] is False
    assert check["implies_current_corporate_acceptance_pass"] is False
    # master_spec pin is wrong vs program even when comparing recorded digests
    checks = check["artifact_digest_checks"]
    assert any(c["name"] == "master_spec" and c["match"] is False for c in checks)
    assert master_sha != ("0" * 64)


def test_SGO_012_check_handoff_reports_schema_and_oracle_pin_currency(
    gov_stub_env: Path,
    tmp_path: Path,
    capsys,
) -> None:
    _program, root, _factory = _review_only_ca_program(tmp_path)
    assert main(["gov", "check-handoff", "--root", str(root)]) == 0
    payload = json.loads(capsys.readouterr().out)
    check = payload["handoff"]
    assert check["schema"] == "corporate-site-handoff/v2"
    assert "oracle_pins" in check
    assert check["implies_current_corporate_acceptance_pass"] is False


def test_SGO_012_handoff_currentness_does_not_imply_ca_pass(
    gov_stub_env: Path,
    tmp_path: Path,
    capsys,
) -> None:
    _program, root, _factory = _review_only_ca_program(tmp_path)
    assert main(["gov", "check-handoff", "--root", str(root)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["handoff"]["implies_current_corporate_acceptance_pass"] is False


def test_ACC_P1_001_soft_fail_without_binary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    factory, root = _factory_layout(tmp_path)
    assert (
        main(
            [
                "init",
                "--root",
                str(root),
                "--id",
                "p1-softfail",
                "--site",
                str(factory),
                "--kind",
                "factory",
                "--apply",
            ]
        )
        == 0
    )
    capsys.readouterr()
    monkeypatch.setenv("CORP_GOV_CHECK", str(tmp_path / "missing-corp-gov-check"))
    before = digest_path(root / "program.json")
    for command in ("explain-stale", "check-handoff"):
        code = main(["gov", command, "--root", str(root)])
        payload = json.loads(capsys.readouterr().out)
        assert code == 2
        assert payload["error"] == GOV_ASSIST_UNAVAILABLE
        assert payload["mutation"] is False
        assert digest_path(root / "program.json") == before


AUTHORIZED_SURFACES = [
    "swift",
    "src/corp_harness/swift_gov.py",
    "src/corp_harness/cli.py",
    "tests",
    "tests/fixtures/governance",
    "scripts/harness",
    "corporate/plugin/corporate-site-harness",
    "docs/adr",
]


def _materialize_authorized_surfaces(factory: Path) -> None:
    (factory / "swift").mkdir(parents=True, exist_ok=True)
    (factory / "src" / "corp_harness").mkdir(parents=True, exist_ok=True)
    (factory / "src" / "corp_harness" / "swift_gov.py").write_text("# assist\n", encoding="utf-8")
    (factory / "src" / "corp_harness" / "cli.py").write_text("# cli\n", encoding="utf-8")
    (factory / "src" / "corp_harness" / "model.py").write_text("# substrate\n", encoding="utf-8")
    (factory / "tests" / "fixtures" / "governance").mkdir(parents=True, exist_ok=True)
    (factory / "scripts" / "harness").mkdir(parents=True, exist_ok=True)
    (factory / "corporate" / "plugin" / "corporate-site-harness").mkdir(
        parents=True, exist_ok=True
    )
    (factory / "docs" / "adr").mkdir(parents=True, exist_ok=True)


def _surfaces_program(tmp_path: Path) -> tuple[Program, Path, Path]:
    program, root, factory = _review_only_ca_program(tmp_path)
    _materialize_authorized_surfaces(factory)
    auth_path = Path(program.artifacts["factory_authorization"].path)
    auth = json.loads(auth_path.read_text(encoding="utf-8"))
    auth["authorized_surfaces"] = list(AUTHORIZED_SURFACES)
    auth_path.write_text(json.dumps(auth) + "\n", encoding="utf-8")
    # Keep program.json pointing at the prior auth digest; assist reads the file
    # for surfaces and must not mutate digests when checking.
    return Program.load(root / "program.json"), root, factory


def test_ACC_P2_001_check_authorized_surfaces_allow_deny(
    gov_stub_env: Path,
    tmp_path: Path,
    capsys,
) -> None:
    program, root, factory = _surfaces_program(tmp_path)
    path = root / "program.json"
    before = digest_path(path)
    before_phase = program.phase
    signals = json.loads(
        (FIXTURES / "check_authorized_surfaces_signals.json").read_text(encoding="utf-8")
    )
    factory_marker = factory / "src" / "corp_harness" / "swift_gov.py"
    factory_before = factory_marker.read_text(encoding="utf-8")

    allow_cmd = [
        "gov",
        "check-authorized-surfaces",
        "--root",
        str(root),
        "--path",
        signals["allow_path"],
    ]
    assert main(allow_cmd) == 0
    allow_payload = json.loads(capsys.readouterr().out)
    assert allow_payload["command"] == signals["command"]
    assert allow_payload["ok"] is True
    assert allow_payload["mutation"] is signals["mutation"]
    assert allow_payload["phase_unchanged"] is True
    assert allow_payload["program_digest"] == before
    assert allow_payload["program_digest_after"] == before
    assert digest_path(path) == before
    assert Program.load(path).phase == before_phase
    assert factory_marker.read_text(encoding="utf-8") == factory_before
    surfaces = allow_payload["surfaces"]
    assert surfaces["existence_ok"] is True
    assert surfaces["check_ok"] is True
    assert surfaces["tree_unchanged"] is signals["tree_unchanged"]
    assert surfaces["grants_authorization"] is signals["grants_authorization"]
    assert surfaces["implies_current_corporate_acceptance_pass"] is False
    assert signals["allow_path"] in surfaces["allowed"]
    assert surfaces["denied"] == []
    assert all(item["exists"] for item in surfaces["existence"])

    deny_cmd = [
        "gov",
        "check-authorized-surfaces",
        "--root",
        str(root),
        "--path",
        signals["deny_path"],
    ]
    assert main(deny_cmd) == 1
    deny_payload = json.loads(capsys.readouterr().out)
    assert deny_payload["ok"] is False
    assert deny_payload["mutation"] is False
    assert deny_payload["program_digest"] == before
    assert deny_payload["program_digest_after"] == before
    assert digest_path(path) == before
    assert factory_marker.read_text(encoding="utf-8") == factory_before
    deny_surfaces = deny_payload["surfaces"]
    assert deny_surfaces["existence_ok"] is True
    assert deny_surfaces["check_ok"] is False
    assert signals["deny_path"] in deny_surfaces["denied"]
    assert deny_surfaces["grants_authorization"] is False


def test_check_authorized_surfaces_missing_surface_before_allow(
    gov_stub_env: Path,
    tmp_path: Path,
    capsys,
) -> None:
    program, root, factory = _surfaces_program(tmp_path)
    path = root / "program.json"
    before = digest_path(path)
    # Remove an authorized surface after auth lists it — existence must fail first.
    (factory / "swift").rmdir()

    code = main(
        [
            "gov",
            "check-authorized-surfaces",
            "--root",
            str(root),
            "--path",
            "src/corp_harness/swift_gov.py",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["ok"] is False
    assert digest_path(path) == before
    assert Program.load(path).phase == program.phase
    surfaces = payload["surfaces"]
    assert surfaces["existence_ok"] is False
    assert surfaces["check_ok"] is False
    assert any("AUTHORIZED_SURFACE_MISSING: swift" in issue for issue in surfaces["issues"])


def test_ACC_SG_004_surface_boundary_and_no_actor_user(
    gov_stub_env: Path,
    tmp_path: Path,
    capsys,
) -> None:
    _program, root, _factory = _surfaces_program(tmp_path)
    path = root / "program.json"
    before = digest_path(path)
    signals = json.loads(
        (FIXTURES / "check_authorized_surfaces_signals.json").read_text(encoding="utf-8")
    )

    code = main(
        [
            "gov",
            "check-authorized-surfaces",
            "--root",
            str(root),
            "--path",
            signals["allow_path"],
            "--path",
            "tests/test_gov_assist.py",
            "--path",
            signals["deny_path"],
            "--path",
            "src/corp_harness/contracts.py",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["mutation"] is False
    assert payload["assist"] is True
    assert digest_path(path) == before
    surfaces = payload["surfaces"]
    assert surfaces["existence_ok"] is True
    assert signals["allow_path"] in surfaces["allowed"]
    assert "tests/test_gov_assist.py" in surfaces["allowed"]
    assert signals["deny_path"] in surfaces["denied"]
    assert "src/corp_harness/contracts.py" in surfaces["denied"]
    assert surfaces["grants_authorization"] is False
    # Assist path never records with --actor user; digest/phase prove non-mutation.
    assert "actor" not in payload
    assert payload["phase_unchanged"] is True


def test_ACC_P2_001_soft_fail_without_binary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    factory, root = _factory_layout(tmp_path)
    assert (
        main(
            [
                "init",
                "--root",
                str(root),
                "--id",
                "p2-softfail",
                "--site",
                str(factory),
                "--kind",
                "factory",
                "--apply",
            ]
        )
        == 0
    )
    capsys.readouterr()
    monkeypatch.setenv("CORP_GOV_CHECK", str(tmp_path / "missing-corp-gov-check"))
    before = digest_path(root / "program.json")
    code = main(
        [
            "gov",
            "check-authorized-surfaces",
            "--root",
            str(root),
            "--path",
            "swift",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload["error"] == GOV_ASSIST_UNAVAILABLE
    assert payload["mutation"] is False
    assert digest_path(root / "program.json") == before
