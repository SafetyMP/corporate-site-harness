import hashlib
import json
import os
from pathlib import Path

import pytest

from corp_harness.model import ContractError, Program, digest_path


def write(path: Path, value: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return path


def build_program(tmp_path: Path) -> tuple[Program, Path, Path]:
    root = tmp_path / "corporate"
    site = tmp_path / "site"
    root.mkdir()
    site.mkdir()
    return (
        Program.create("pilot", site, ["quality", "security"], program_root=root),
        root,
        site,
    )


def gate_report(
    program: Program,
    root: Path,
    name: str,
    reviewer_role: str,
    status: str = "PASS",
    *,
    review_only: bool = False,
) -> Path:
    target_sha256 = program.gate_target_digest(name)
    evidence_refs = []
    if name == "corporate_acceptance" and not review_only:
        stdout = "passed\n" if status == "PASS" else ""
        stderr = "" if status == "PASS" else "failed\n"
        argv = ["./scripts/harness/corporate-acceptance.sh"]
        script = root / argv[0]
        if not script.is_file():
            write(script, "#!/bin/sh\nexit 0\n")
            os.chmod(script, 0o755)
        executable = write(
            root / "evidence" / f"{name}-executable.json",
            json.dumps(
                {
                    "schema": "corporate-site-evidence/v1",
                    "name": "corporate_acceptance",
                    "argv": argv,
                    "cwd": str(root.resolve()),
                    "executable_path": str(script.resolve()),
                    "executable_sha256": digest_path(script),
                    "revision": program.revision,
                    "target_sha256": target_sha256,
                    "passed": status == "PASS",
                    "exit_code": 0 if status == "PASS" else 1,
                    "timed_out": False,
                    "truncated": False,
                    "stdout": stdout,
                    "stderr": stderr,
                    "stdout_sha256": hashlib.sha256(stdout.encode()).hexdigest(),
                    "stderr_sha256": hashlib.sha256(stderr.encode()).hexdigest(),
                }
            )
            + "\n",
        )
        evidence_refs.append({"path": str(executable), "sha256": digest_path(executable)})
    if name in {"site_verify", "operations", "corporate_review", "adversary"}:
        stdout = "passed\n" if status == "PASS" else ""
        stderr = "" if status == "PASS" else "failed\n"
        evidence_name = "adversarial" if name == "adversary" else name
        argv = (
            ["./scripts/harness/adversarial.sh"]
            if name == "adversary"
            else ["./scripts/harness/verify.sh"]
        )
        executable_path = Path(program.site_path) / argv[0]
        executable = write(
            root / "evidence" / f"{name}-executable.json",
            json.dumps(
                {
                    "schema": "corporate-site-evidence/v1",
                    "name": evidence_name,
                    "argv": argv,
                    "cwd": program.site_path,
                    "executable_path": str(executable_path.resolve()),
                    "executable_sha256": digest_path(executable_path),
                    "revision": program.revision,
                    "target_sha256": target_sha256,
                    "passed": status == "PASS",
                    "exit_code": 0 if status == "PASS" else 1,
                    "timed_out": False,
                    "truncated": False,
                    "stdout": stdout,
                    "stderr": stderr,
                    "stdout_sha256": hashlib.sha256(stdout.encode()).hexdigest(),
                    "stderr_sha256": hashlib.sha256(stderr.encode()).hexdigest(),
                }
            )
            + "\n",
        )
        evidence_refs.append({"path": str(executable), "sha256": digest_path(executable)})
    if name in {"corporate_acceptance", "corporate_review", "adversary"}:
        review = write(
            root / "evidence" / f"{name}-review.json",
            json.dumps(
                {
                    "schema": "corporate-site-review-evidence/v1",
                    "reviewer": reviewer_role,
                    "revision": program.revision,
                    "verdict": status,
                    "target_sha256": target_sha256,
                }
            )
            + "\n",
        )
        evidence_refs.append({"path": str(review), "sha256": digest_path(review)})
    report = {
        "schema": "corporate-site-gate/v1",
        "gate": name,
        "reviewer_role": reviewer_role,
        "status": status,
        "revision": program.revision,
        "target_sha256": target_sha256,
        "evidence_refs": evidence_refs,
    }
    return write(root / f"{name}-gate.json", json.dumps(report) + "\n")


def advance_to_adversary(tmp_path: Path) -> tuple[Program, Path, Path]:
    program, root, site = build_program(tmp_path)
    master = write(root / "master-spec.md", "# Spec\n")
    acceptance = write(root / "acceptance.json", "{}\n")
    program.record_artifact("master_spec", master, "ceo", root)
    program.record_artifact("acceptance", acceptance, "ceo", root)
    program.advance("CORPORATE_ACCEPTANCE", "ceo")

    corporate_report = gate_report(program, root, "corporate_acceptance", "coo")
    program.record_gate(
        "corporate_acceptance",
        "PASS",
        corporate_report,
        "coo",
        root,
    )
    handoff = write(root / "corporate-handoff.json", "{}\n")
    program.record_artifact("corporate_handoff", handoff, "coo", root)
    program.advance("SITE_DELIVERY", "coo")

    adr = write(site / "docs/adr/ADR-001.md", "# Decision\n")
    implementation = write(site / "src/app.py", "VALUE = 1\n")
    verification = write(site / "tests/test_app.py", "def test_app():\n    assert True\n")
    harness = site / "scripts" / "harness"
    verification_script = write(harness / "verify.sh", "#!/bin/sh\nexit 0\n")
    adversarial_script = write(harness / "adversarial.sh", "#!/bin/sh\nexit 0\n")
    os.chmod(verification_script, 0o755)
    os.chmod(adversarial_script, 0o755)
    runtime_manifest = write(site / "pyproject.toml", "[project]\nname = 'app'\n")
    program.record_artifact("adr:ADR-001", adr, "site-specialist", root)
    program.record_artifact("implementation", implementation, "site-specialist", root)
    program.record_artifact("verification", verification, "site-specialist", root)
    program.record_artifact(
        "verification_scripts",
        harness,
        "site-specialist",
        root,
    )
    program.record_artifact(
        "runtime_manifest",
        runtime_manifest,
        "site-specialist",
        root,
    )
    program.advance("SITE_VERIFICATION", "site-manager")

    verify_report = gate_report(program, root, "site_verify", "operations-excellence")
    operations_report = gate_report(program, root, "operations", "operations-excellence")
    program.record_gate("site_verify", "PASS", verify_report, "operations-excellence", root)
    program.record_gate("operations", "PASS", operations_report, "operations-excellence", root)
    program.advance("CORPORATE_REVIEW", "operations-excellence")

    corporate_review = gate_report(
        program,
        root,
        "corporate_review",
        "corporate-specialist",
    )
    program.record_gate(
        "corporate_review",
        "PASS",
        corporate_review,
        "corporate-specialist",
        root,
    )
    program.advance("ADVERSARY", "corporate-specialist")
    return program, root, site


def test_complete_lifecycle_records_explicit_user_approval(tmp_path: Path) -> None:
    program, root, _site = advance_to_adversary(tmp_path)
    adversary_report = gate_report(
        program,
        root,
        "adversary",
        "corporate-adversary",
    )
    dossier = write(root / "final-dossier.md", "# Evidence\n")
    program.record_gate(
        "adversary",
        "PASS",
        adversary_report,
        "corporate-adversary",
        root,
    )
    program.record_artifact("final_dossier", dossier, "ceo", root)
    program.advance("AWAITING_USER_APPROVAL", "ceo")

    assert program.phase == "AWAITING_USER_APPROVAL"
    assert program.current_issues() == []

    approval = write(
        root / "user-approval.json",
        json.dumps(
            {
                "schema": "corporate-site-user-approval/v1",
                "program_id": program.program_id,
                "revision": program.revision,
                "approved": True,
                "granted_by": "user",
                "granted_at": "2026-07-17T02:45:00+00:00",
                "final_dossier_sha256": program.artifacts["final_dossier"].sha256,
                "gate_report_sha256": {
                    name: gate.report_sha256 for name, gate in sorted(program.gates.items())
                },
            }
        )
        + "\n",
    )
    program.record_artifact("user_approval", approval, "user", root)
    program.advance("APPROVED", "user")

    assert program.phase == "APPROVED"
    assert program.current_issues() == []


def test_user_approval_must_match_current_dossier(tmp_path: Path) -> None:
    program, root, _site = advance_to_adversary(tmp_path)
    adversary_report = gate_report(
        program,
        root,
        "adversary",
        "corporate-adversary",
    )
    dossier = write(root / "final-dossier.md", "# Evidence\n")
    program.record_gate(
        "adversary",
        "PASS",
        adversary_report,
        "corporate-adversary",
        root,
    )
    program.record_artifact("final_dossier", dossier, "ceo", root)
    program.advance("AWAITING_USER_APPROVAL", "ceo")
    approval = write(
        root / "bad-approval.json",
        json.dumps(
            {
                "schema": "corporate-site-user-approval/v1",
                "program_id": program.program_id,
                "revision": program.revision,
                "approved": True,
                "granted_by": "user",
                "granted_at": "2026-07-17T02:45:00+00:00",
                "final_dossier_sha256": "0" * 64,
                "gate_report_sha256": {
                    name: gate.report_sha256 for name, gate in sorted(program.gates.items())
                },
            }
        )
        + "\n",
    )

    with pytest.raises(ContractError, match="current final dossier"):
        program.record_artifact("user_approval", approval, "user", root)


def test_skipping_phase_is_rejected(tmp_path: Path) -> None:
    program, _root, _site = build_program(tmp_path)

    with pytest.raises(ContractError, match="transition not allowed"):
        program.advance("SITE_DELIVERY", "ceo")


def test_artifact_change_stales_gate(tmp_path: Path) -> None:
    program, root, _site = advance_to_adversary(tmp_path)
    Path(program.artifacts["implementation"].path).write_text("VALUE = 2\n", encoding="utf-8")

    assert "artifact implementation is stale" in program.current_issues()
    assert "gate corporate_review is stale" in program.current_issues()


def test_artifact_role_cannot_be_impersonated(tmp_path: Path) -> None:
    program, root, _site = build_program(tmp_path)
    implementation = write(root / "implementation.py", "pass\n")

    with pytest.raises(ContractError, match="must be produced by site-specialist"):
        program.record_artifact(
            "implementation",
            implementation,
            "operations-excellence",
            root,
        )


def test_rework_is_bounded(tmp_path: Path) -> None:
    program, _root, _site = advance_to_adversary(tmp_path)

    program.gates["adversary"] = program.gates["corporate_review"]
    for attempt in range(program.max_attempts):
        program.phase = "ADVERSARY"
        program.rework("corporate-adversary")
        if attempt == 0:
            assert set(program.gates) <= {"corporate_acceptance"}

    program.phase = "ADVERSARY"
    with pytest.raises(ContractError, match="attempt budget exhausted"):
        program.rework("corporate-adversary")


def test_user_reopen_from_approved_bypasses_attempt_budget(tmp_path: Path) -> None:
    program, root, _site = advance_to_adversary(tmp_path)
    adversary_report = gate_report(program, root, "adversary", "corporate-adversary")
    program.record_gate(
        "adversary",
        "PASS",
        adversary_report,
        "corporate-adversary",
        root,
    )
    dossier = write(root / "final-dossier.md", "# Done\n")
    program.record_artifact("final_dossier", dossier, "ceo", root)
    program.advance("AWAITING_USER_APPROVAL", "ceo")
    approval = write(
        root / "user-approval.json",
        json.dumps(
            {
                "schema": "corporate-site-user-approval/v1",
                "approved": True,
                "granted_by": "user",
                "program_id": program.program_id,
                "revision": program.revision,
                "final_dossier_sha256": program.artifacts["final_dossier"].sha256,
                "gate_report_sha256": {
                    name: gate.report_sha256 for name, gate in sorted(program.gates.items())
                },
                "granted_at": "2026-07-20T00:00:00Z",
            }
        )
        + "\n",
    )
    program.record_artifact("user_approval", approval, "user", root)
    program.advance("APPROVED", "user")
    program.attempts = program.max_attempts
    prior_revision = program.revision

    with pytest.raises(ContractError, match="requires role user"):
        program.rework("ceo")
    program.rework("user")

    assert program.phase == "SITE_DELIVERY"
    assert program.revision == prior_revision + 1
    assert program.attempts == program.max_attempts
    assert "user_approval" not in program.artifacts
    assert "final_dossier" not in program.artifacts
    assert set(program.gates) == {"corporate_acceptance"}


def test_gate_status_must_match_report(tmp_path: Path) -> None:
    program, root, _site = build_program(tmp_path)
    master = write(root / "master.md", "# Spec\n")
    acceptance = write(root / "acceptance.json", "{}\n")
    program.record_artifact("master_spec", master, "ceo", root)
    program.record_artifact("acceptance", acceptance, "ceo", root)
    program.advance("CORPORATE_ACCEPTANCE", "ceo")
    report = gate_report(program, root, "corporate_acceptance", "coo", status="FAIL")

    with pytest.raises(ContractError, match="does not match"):
        program.record_gate("corporate_acceptance", "PASS", report, "coo", root)


def test_gate_cannot_be_recorded_out_of_phase(tmp_path: Path) -> None:
    program, root, _site = build_program(tmp_path)
    master = write(root / "master.md", "# Spec\n")
    acceptance = write(root / "acceptance.json", "{}\n")
    program.record_artifact("master_spec", master, "ceo", root)
    program.record_artifact("acceptance", acceptance, "ceo", root)
    report = gate_report(program, root, "corporate_acceptance", "coo")

    with pytest.raises(ContractError, match="may only be recorded"):
        program.record_gate("corporate_acceptance", "PASS", report, "coo", root)


def test_executable_mode_change_stales_artifact(tmp_path: Path) -> None:
    script = write(tmp_path / "verify.sh", "#!/bin/sh\nexit 0\n")
    os.chmod(script, 0o755)
    initial = digest_path(script)
    os.chmod(script, 0o644)

    assert digest_path(script) != initial


def test_program_save_rejects_lost_update(tmp_path: Path) -> None:
    program, root, _site = build_program(tmp_path)
    path = root / "program.json"
    program.save(path)
    first = Program.load(path)
    stale = Program.load(path)
    first.selected_domains.append("platform")
    first.save(path)
    stale.selected_domains.append("experience")

    with pytest.raises(ContractError, match="changed concurrently"):
        stale.save(path)


def test_pass_gate_rejects_failed_executable_evidence(tmp_path: Path) -> None:
    program, root, site = build_program(tmp_path)
    master = write(root / "master.md", "# Spec\n")
    acceptance = write(root / "acceptance.json", "{}\n")
    program.record_artifact("master_spec", master, "ceo", root)
    program.record_artifact("acceptance", acceptance, "ceo", root)
    program.advance("CORPORATE_ACCEPTANCE", "ceo")
    corporate = gate_report(program, root, "corporate_acceptance", "coo")
    program.record_gate("corporate_acceptance", "PASS", corporate, "coo", root)
    handoff = write(root / "handoff.json", "{}\n")
    program.record_artifact("corporate_handoff", handoff, "coo", root)
    program.advance("SITE_DELIVERY", "coo")
    harness = site / "scripts" / "harness"
    verify = write(harness / "verify.sh", "#!/bin/sh\nexit 0\n")
    adversarial = write(harness / "adversarial.sh", "#!/bin/sh\nexit 0\n")
    os.chmod(verify, 0o755)
    os.chmod(adversarial, 0o755)
    for name, path in {
        "adr:ADR-001": write(site / "ADR.md", "# ADR\n"),
        "implementation": write(site / "app.py", "pass\n"),
        "verification": write(site / "test_app.py", "assert True\n"),
        "verification_scripts": harness,
        "runtime_manifest": write(site / "pyproject.toml", "[project]\nname='x'\n"),
    }.items():
        program.record_artifact(name, path, "site-specialist", root)
    program.advance("SITE_VERIFICATION", "site-manager")
    report_path = gate_report(program, root, "site_verify", "operations-excellence")
    report = json.loads(report_path.read_text())
    evidence_path = Path(report["evidence_refs"][0]["path"])
    evidence = json.loads(evidence_path.read_text())
    evidence.update({"passed": False, "exit_code": 1})
    evidence_path.write_text(json.dumps(evidence) + "\n")
    report["evidence_refs"][0]["sha256"] = digest_path(evidence_path)
    report_path.write_text(json.dumps(report) + "\n")

    with pytest.raises(ContractError, match="failed executable evidence"):
        program.record_gate(
            "site_verify",
            "PASS",
            report_path,
            "operations-excellence",
            root,
        )


def test_program_load_rejects_forged_gate_role(tmp_path: Path) -> None:
    program, root, _site = build_program(tmp_path)
    master = write(root / "master.md", "# Spec\n")
    acceptance = write(root / "acceptance.json", "{}\n")
    program.record_artifact("master_spec", master, "ceo", root)
    program.record_artifact("acceptance", acceptance, "ceo", root)
    program.advance("CORPORATE_ACCEPTANCE", "ceo")
    report = gate_report(program, root, "corporate_acceptance", "coo")
    program.record_gate("corporate_acceptance", "PASS", report, "coo", root)
    path = root / "program.json"
    program.save(path)
    raw = json.loads(path.read_text())
    raw["gates"]["corporate_acceptance"]["reviewer_role"] = "ceo"
    path.write_text(json.dumps(raw) + "\n")

    with pytest.raises(ContractError, match="must be reviewed by coo"):
        Program.load(path)


def test_awaiting_approval_requires_all_predecessor_gates(tmp_path: Path) -> None:
    program, root, _site = advance_to_adversary(tmp_path)
    adversary = gate_report(program, root, "adversary", "corporate-adversary")
    dossier = write(root / "dossier.md", "# Dossier\n")
    program.record_gate("adversary", "PASS", adversary, "corporate-adversary", root)
    program.record_artifact("final_dossier", dossier, "ceo", root)
    program.advance("AWAITING_USER_APPROVAL", "ceo")
    program.gates.pop("operations")

    assert "missing gate operations" in program.current_issues()


def test_executable_evidence_cannot_be_replayed_across_gates(tmp_path: Path) -> None:
    program, root, _site = advance_to_adversary(tmp_path)
    adversary = gate_report(program, root, "adversary", "corporate-adversary")
    report = json.loads(adversary.read_text())
    operations_evidence = root / "evidence/operations-executable.json"
    report["evidence_refs"][0] = {
        "path": str(operations_evidence),
        "sha256": digest_path(operations_evidence),
    }
    adversary.write_text(json.dumps(report) + "\n")

    with pytest.raises(ContractError, match="command does not match"):
        program.record_gate(
            "adversary",
            "PASS",
            adversary,
            "corporate-adversary",
            root,
        )


def test_create_rejects_nested_program_and_site(tmp_path: Path) -> None:
    root = tmp_path / "corporate"
    site = root / "nested-site"
    root.mkdir()
    site.mkdir()

    with pytest.raises(ContractError, match="must not be the same or nested"):
        Program.create("pilot", site, program_root=root)


def test_create_rejects_site_that_is_corporate_root(tmp_path: Path) -> None:
    root = tmp_path / "corporate"
    site = tmp_path / "site"
    root.mkdir()
    site.mkdir()
    write(site / "program.json", "{}\n")

    with pytest.raises(ContractError, match="contains program.json"):
        Program.create("pilot", site, program_root=root)


def test_create_accepts_site_json_with_distinct_site_id(tmp_path: Path) -> None:
    root = tmp_path / "corporate"
    site = tmp_path / "site"
    root.mkdir()
    site.mkdir()
    write(
        site / ".corp-harness" / "site.json",
        json.dumps(
            {
                "schema": "corporate-site-site/v1",
                "site_id": "hr-erp",
                "verify_argv": ["./scripts/harness/verify.sh"],
                "adversarial_argv": ["./scripts/harness/adversarial.sh"],
            }
        )
        + "\n",
    )

    program = Program.create("core-hr", site, ["product"], program_root=root)

    assert program.program_id == "core-hr"
    assert program.site_path == str(site.resolve())


def test_create_rejects_invalid_site_json(tmp_path: Path) -> None:
    root = tmp_path / "corporate"
    site = tmp_path / "site"
    root.mkdir()
    site.mkdir()
    write(
        site / ".corp-harness" / "site.json",
        json.dumps({"schema": "wrong", "site_id": "x"}) + "\n",
    )

    with pytest.raises(ContractError, match="site.json schema"):
        Program.create("pilot", site, program_root=root)


def _factory_layout(tmp_path: Path) -> tuple[Path, Path]:
    factory = tmp_path / "Cursor Harness"
    (factory / "src" / "corp_harness").mkdir(parents=True)
    (factory / "corporate" / "plugin" / "corporate-site-harness").mkdir(parents=True)
    write(factory / "src" / "corp_harness" / "__init__.py", "")
    root = tmp_path / "factory-feature-corporate"
    root.mkdir(parents=True)
    return factory, root


def test_create_factory_requires_factory_root(tmp_path: Path) -> None:
    root = tmp_path / "corporate"
    site = tmp_path / "site"
    root.mkdir()
    site.mkdir()

    with pytest.raises(ContractError, match="factory root"):
        Program.create("feat", site, program_root=root, program_kind="factory")


def test_create_factory_accepts_sibling_corporate_root(tmp_path: Path) -> None:
    factory, root = _factory_layout(tmp_path)

    program = Program.create(
        "factory-feature",
        factory,
        ["platform"],
        program_root=root,
        program_kind="factory",
    )

    assert program.program_kind == "factory"
    assert program.site_path == str(factory.resolve())


def test_create_factory_rejects_programs_nesting(tmp_path: Path) -> None:
    factory = tmp_path / "Cursor Harness"
    (factory / "src" / "corp_harness").mkdir(parents=True)
    (factory / "corporate" / "plugin" / "corporate-site-harness").mkdir(parents=True)
    write(factory / "src" / "corp_harness" / "__init__.py", "")
    root = factory / "programs" / "factory-feature"
    root.mkdir(parents=True)

    with pytest.raises(ContractError, match="must not be the same or nested"):
        Program.create(
            "factory-feature",
            factory,
            ["platform"],
            program_root=root,
            program_kind="factory",
        )


def test_create_product_rejects_programs_nesting(tmp_path: Path) -> None:
    factory = tmp_path / "Cursor Harness"
    factory.mkdir()
    root = factory / "programs" / "feat"
    root.mkdir(parents=True)

    with pytest.raises(ContractError, match="must not be the same or nested"):
        Program.create("feat", factory, program_root=root, program_kind="product")


def test_current_issues_flags_nested_program_root(tmp_path: Path) -> None:
    factory, root = _factory_layout(tmp_path)
    program = Program.create(
        "factory-feature",
        factory,
        ["platform"],
        program_root=root,
        program_kind="factory",
    )
    nested = factory / "programs" / "legacy"
    nested.mkdir(parents=True)
    program.save(nested / "program.json")

    loaded = Program.load(nested / "program.json")
    issues = loaded.current_issues(program_root=nested)

    assert any("must not be the same or nested" in issue for issue in issues)


def test_factory_cannot_enter_corporate_acceptance_without_authorization(
    tmp_path: Path,
) -> None:
    factory, root = _factory_layout(tmp_path)
    program = Program.create(
        "factory-feature",
        factory,
        program_root=root,
        program_kind="factory",
    )
    master = write(root / "master-spec.md", "# Factory feature\n")
    acceptance = write(root / "acceptance.json", "{}\n")
    program.record_artifact("master_spec", master, "ceo", root)
    program.record_artifact("acceptance", acceptance, "ceo", root)

    with pytest.raises(ContractError, match="missing artifact factory_authorization"):
        program.advance("CORPORATE_ACCEPTANCE", "ceo")


def test_factory_authorization_binds_master_spec(tmp_path: Path) -> None:
    factory, root = _factory_layout(tmp_path)
    program = Program.create(
        "factory-feature",
        factory,
        program_root=root,
        program_kind="factory",
    )
    master = write(root / "master-spec.md", "# Factory feature\n")
    acceptance = write(root / "acceptance.json", "{}\n")
    program.record_artifact("master_spec", master, "ceo", root)
    program.record_artifact("acceptance", acceptance, "ceo", root)
    auth = write(
        root / "factory-authorization.json",
        json.dumps(
            {
                "schema": "corporate-site-factory-authorization/v1",
                "authorized": True,
                "granted_by": "user",
                "granted_at": "2026-07-19T12:00:00Z",
                "program_id": "factory-feature",
                "revision": 1,
                "master_spec_sha256": program.artifacts["master_spec"].sha256,
                "factory_root": str(factory.resolve()),
                "authorized_surfaces": ["src/corp_harness/portfolio.py"],
            }
        )
        + "\n",
    )
    program.record_artifact("factory_authorization", auth, "user", root)
    program.advance("CORPORATE_ACCEPTANCE", "ceo")

    assert program.phase == "CORPORATE_ACCEPTANCE"


def test_factory_authorization_rejects_stale_master_digest(tmp_path: Path) -> None:
    factory, root = _factory_layout(tmp_path)
    program = Program.create(
        "factory-feature",
        factory,
        program_root=root,
        program_kind="factory",
    )
    master = write(root / "master-spec.md", "# Factory feature\n")
    program.record_artifact("master_spec", master, "ceo", root)
    auth = write(
        root / "factory-authorization.json",
        json.dumps(
            {
                "schema": "corporate-site-factory-authorization/v1",
                "authorized": True,
                "granted_by": "user",
                "granted_at": "2026-07-19T12:00:00Z",
                "program_id": "factory-feature",
                "revision": 1,
                "master_spec_sha256": "0" * 64,
                "factory_root": str(factory.resolve()),
                "authorized_surfaces": ["src/corp_harness/cli.py"],
            }
        )
        + "\n",
    )

    with pytest.raises(ContractError, match="not bound to the current master spec"):
        program.record_artifact("factory_authorization", auth, "user", root)


def test_factory_authorization_rejects_non_user_actor(tmp_path: Path) -> None:
    factory, root = _factory_layout(tmp_path)
    program = Program.create(
        "factory-feature",
        factory,
        program_root=root,
        program_kind="factory",
    )
    master = write(root / "master-spec.md", "# Factory feature\n")
    program.record_artifact("master_spec", master, "ceo", root)
    auth = write(
        root / "factory-authorization.json",
        json.dumps(
            {
                "schema": "corporate-site-factory-authorization/v1",
                "authorized": True,
                "granted_by": "user",
                "granted_at": "2026-07-19T12:00:00Z",
                "program_id": "factory-feature",
                "revision": 1,
                "master_spec_sha256": program.artifacts["master_spec"].sha256,
                "factory_root": str(factory.resolve()),
                "authorized_surfaces": ["src/corp_harness/cli.py"],
            }
        )
        + "\n",
    )

    with pytest.raises(ContractError, match="must be produced by user"):
        program.record_artifact("factory_authorization", auth, "ceo", root)


def test_product_rejects_factory_authorization(tmp_path: Path) -> None:
    program, root, site = build_program(tmp_path)
    master = write(root / "master-spec.md", "# Spec\n")
    program.record_artifact("master_spec", master, "ceo", root)
    auth = write(
        root / "factory-authorization.json",
        json.dumps(
            {
                "schema": "corporate-site-factory-authorization/v1",
                "authorized": True,
                "granted_by": "user",
                "granted_at": "2026-07-19T12:00:00Z",
                "program_id": "pilot",
                "revision": 1,
                "master_spec_sha256": program.artifacts["master_spec"].sha256,
                "factory_root": str(site.resolve()),
                "authorized_surfaces": ["src/app.py"],
            }
        )
        + "\n",
    )

    with pytest.raises(ContractError, match="only valid for factory programs"):
        program.record_artifact("factory_authorization", auth, "user", root)


def test_factory_status_surfaces_missing_authorization(tmp_path: Path) -> None:
    factory, root = _factory_layout(tmp_path)
    program = Program.create(
        "factory-feature",
        factory,
        program_root=root,
        program_kind="factory",
    )
    master = write(root / "master-spec.md", "# Factory feature\n")
    program.record_artifact("master_spec", master, "ceo", root)

    assert "missing artifact factory_authorization" in program.current_issues()


def _harness_scripts(site: Path) -> Path:
    harness = site / "scripts" / "harness"
    verify = write(harness / "verify.sh", "#!/bin/sh\nexit 0\n")
    adversarial = write(harness / "adversarial.sh", "#!/bin/sh\nexit 0\n")
    os.chmod(verify, 0o755)
    os.chmod(adversarial, 0o755)
    return harness


def test_verification_scripts_rejects_whole_scripts_tree(tmp_path: Path) -> None:
    program, root, site = build_program(tmp_path)
    scripts = site / "scripts"
    write(scripts / "verify.sh", "#!/bin/sh\nexit 0\n")
    write(scripts / "adversarial.sh", "#!/bin/sh\nexit 0\n")
    write(scripts / "extra.sh", "#!/bin/sh\nexit 0\n")

    with pytest.raises(ContractError, match="scripts/harness"):
        program.record_artifact("verification_scripts", scripts, "site-specialist", root)


def test_verification_scripts_rejects_extra_harness_file(tmp_path: Path) -> None:
    program, root, site = build_program(tmp_path)
    harness = _harness_scripts(site)
    write(harness / "extra.sh", "#!/bin/sh\nexit 0\n")

    with pytest.raises(
        ContractError,
        match="may only contain verify.sh, adversarial.sh, and optional corporate-acceptance.sh",
    ):
        program.record_artifact("verification_scripts", harness, "site-specialist", root)


def test_verification_scripts_rejects_subdirectory(tmp_path: Path) -> None:
    program, root, site = build_program(tmp_path)
    harness = _harness_scripts(site)
    (harness / "lib").mkdir()

    with pytest.raises(ContractError, match="must not contain subdirectories"):
        program.record_artifact("verification_scripts", harness, "site-specialist", root)


def test_verification_scripts_accepts_canonical_harness(tmp_path: Path) -> None:
    program, root, site = build_program(tmp_path)
    harness = _harness_scripts(site)
    write(site / "scripts" / "noise.sh", "#!/bin/sh\nexit 0\n")

    artifact = program.record_artifact(
        "verification_scripts",
        harness,
        "site-specialist",
        root,
    )
    baseline = artifact.sha256
    write(site / "scripts" / "capture-screenshots.mjs", "console.log(1)\n")
    assert digest_path(harness) == baseline
    os.chmod(harness / "verify.sh", 0o644)
    assert digest_path(harness) != baseline


def test_verification_scripts_status_flags_invalid_binding(tmp_path: Path) -> None:
    program, root, site = build_program(tmp_path)
    harness = _harness_scripts(site)
    program.record_artifact("verification_scripts", harness, "site-specialist", root)
    program.artifacts["verification_scripts"] = type(program.artifacts["verification_scripts"])(
        path=str(site / "scripts"),
        sha256=digest_path(harness),
        revision=program.revision,
        producer_role="site-specialist",
    )
    write(site / "scripts" / "verify.sh", "#!/bin/sh\nexit 0\n")
    write(site / "scripts" / "adversarial.sh", "#!/bin/sh\nexit 0\n")

    issues = program.current_issues()
    assert any("verification_scripts" in item for item in issues)
