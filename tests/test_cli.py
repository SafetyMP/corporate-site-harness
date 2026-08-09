import json
import os
from pathlib import Path

from corp_harness.cli import main


def add_verify_script(site: Path) -> None:
    harness = site / "scripts/harness"
    harness.mkdir(parents=True)
    for name in ("verify.sh", "adversarial.sh"):
        script = harness / name
        script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        os.chmod(script, 0o755)


def test_init_is_dry_run_without_apply(tmp_path: Path, capsys) -> None:
    root = tmp_path / "program"
    site = tmp_path / "site"
    site.mkdir()
    add_verify_script(site)

    exit_code = main(["init", "--root", str(root), "--id", "pilot", "--site", str(site)])

    assert exit_code == 0
    assert not (root / "program.json").exists()
    assert json.loads(capsys.readouterr().out)["apply"] is False


def test_init_and_status(tmp_path: Path, capsys) -> None:
    root = tmp_path / "program"
    site = tmp_path / "site"
    site.mkdir()

    assert (
        main(
            [
                "init",
                "--root",
                str(root),
                "--id",
                "pilot",
                "--site",
                str(site),
                "--apply",
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert main(["status", "--root", str(root)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["program"]["phase"] == "DESIGN"


def test_check_records_evidence_only_with_apply(tmp_path: Path, capsys) -> None:
    root = tmp_path / "program"
    site = tmp_path / "site"
    site.mkdir()
    add_verify_script(site)
    main(
        [
            "init",
            "--root",
            str(root),
            "--id",
            "pilot",
            "--site",
            str(site),
            "--apply",
        ]
    )
    capsys.readouterr()

    command = [
        "check",
        "--root",
        str(root),
        "--run",
        "smoke",
        "--apply",
        "--",
        "./scripts/harness/verify.sh",
    ]
    assert main(command) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["evidence"]["passed"] is True
    assert Path(payload["evidence_path"]).is_file()


def test_check_cannot_overwrite_program_state(tmp_path: Path, capsys) -> None:
    root = tmp_path / "program"
    site = tmp_path / "site"
    site.mkdir()
    add_verify_script(site)
    main(
        [
            "init",
            "--root",
            str(root),
            "--id",
            "pilot",
            "--site",
            str(site),
            "--apply",
        ]
    )
    capsys.readouterr()

    exit_code = main(
        [
            "check",
            "--root",
            str(root),
            "--run",
            "smoke",
            "--output",
            str(root / "program.json"),
            "--apply",
            "--",
            "./scripts/harness/verify.sh",
        ]
    )

    assert exit_code == 3
    assert json.loads(capsys.readouterr().out)["ok"] is False
    assert json.loads((root / "program.json").read_text())["program_id"] == "pilot"


def test_check_rejects_subdirectory_cwd(tmp_path: Path, capsys) -> None:
    root = tmp_path / "program"
    site = tmp_path / "site"
    site.mkdir()
    add_verify_script(site)
    (site / "subdir").mkdir()
    main(
        [
            "init",
            "--root",
            str(root),
            "--id",
            "pilot",
            "--site",
            str(site),
            "--apply",
        ]
    )
    capsys.readouterr()

    exit_code = main(
        [
            "check",
            "--root",
            str(root),
            "--run",
            "smoke",
            "--cwd",
            str(site / "subdir"),
            "--",
            "./scripts/harness/verify.sh",
        ]
    )

    assert exit_code == 3
    assert "registered site root" in json.loads(capsys.readouterr().out)["error"]


def test_init_rejects_nested_roots(tmp_path: Path, capsys) -> None:
    root = tmp_path / "program"
    site = root / "site"
    site.mkdir(parents=True)

    exit_code = main(
        ["init", "--root", str(root), "--id", "pilot", "--site", str(site), "--apply"]
    )

    assert exit_code == 3
    assert "must not be the same or nested" in json.loads(capsys.readouterr().out)["error"]


def test_init_rejects_site_with_program_json(tmp_path: Path, capsys) -> None:
    root = tmp_path / "program"
    site = tmp_path / "site"
    site.mkdir()
    (site / "program.json").write_text("{}\n", encoding="utf-8")

    exit_code = main(
        ["init", "--root", str(root), "--id", "pilot", "--site", str(site), "--apply"]
    )

    assert exit_code == 3
    assert "contains program.json" in json.loads(capsys.readouterr().out)["error"]


def test_init_accepts_distinct_program_and_site_ids(tmp_path: Path, capsys) -> None:
    root = tmp_path / "program"
    site = tmp_path / "site"
    site.mkdir()
    manifest = site / ".corp-harness" / "site.json"
    manifest.parent.mkdir()
    manifest.write_text(
        json.dumps(
            {
                "schema": "corporate-site-site/v1",
                "site_id": "hr-erp",
                "verify_argv": ["./scripts/harness/verify.sh"],
                "adversarial_argv": ["./scripts/harness/adversarial.sh"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "init",
            "--root",
            str(root),
            "--id",
            "core-hr",
            "--site",
            str(site),
            "--apply",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["program"]["program_id"] == "core-hr"
    assert payload["program"]["site_path"] == str(site.resolve())
    assert payload["program"].get("program_kind", "product") == "product"


def test_init_factory_kind_requires_factory_site(tmp_path: Path, capsys) -> None:
    root = tmp_path / "program"
    site = tmp_path / "site"
    site.mkdir()

    exit_code = main(
        [
            "init",
            "--root",
            str(root),
            "--id",
            "feat",
            "--site",
            str(site),
            "--kind",
            "factory",
            "--apply",
        ]
    )

    assert exit_code == 3
    assert "factory root" in json.loads(capsys.readouterr().out)["error"]


def test_init_factory_kind_rejects_programs_nesting(tmp_path: Path, capsys) -> None:
    factory = tmp_path / "Cursor Harness"
    (factory / "src" / "corp_harness").mkdir(parents=True)
    (factory / "corporate" / "plugin" / "corporate-site-harness").mkdir(parents=True)
    root = factory / "programs" / "factory-feature"
    root.mkdir(parents=True)

    exit_code = main(
        [
            "init",
            "--root",
            str(root),
            "--id",
            "factory-feature",
            "--site",
            str(factory),
            "--kind",
            "factory",
            "--apply",
        ]
    )

    assert exit_code == 3
    assert "must not be the same or nested" in json.loads(capsys.readouterr().out)["error"]


def test_init_factory_kind_accepts_sibling_corporate_root(tmp_path: Path, capsys) -> None:
    factory = tmp_path / "Cursor Harness"
    (factory / "src" / "corp_harness").mkdir(parents=True)
    (factory / "corporate" / "plugin" / "corporate-site-harness").mkdir(parents=True)
    root = tmp_path / "factory-feature-corporate"
    root.mkdir(parents=True)

    exit_code = main(
        [
            "init",
            "--root",
            str(root),
            "--id",
            "factory-feature",
            "--site",
            str(factory),
            "--kind",
            "factory",
            "--apply",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["program"]["program_kind"] == "factory"
    assert payload["program"]["site_path"] == str(factory.resolve())
    assert (root / "program.json").is_file()
