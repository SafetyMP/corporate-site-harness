import json
import os
import shutil
from pathlib import Path

import pytest

import corp_harness.install as install_module
from corp_harness.model import ContractError


def make_plugin(root: Path, version: str) -> Path:
    (root / ".cursor-plugin").mkdir(parents=True)
    (root / "agents").mkdir()
    (root / ".cursor-plugin/plugin.json").write_text(
        json.dumps(
            {
                "name": "corporate-site-harness",
                "version": version,
                "agents": "agents",
            }
        )
        + "\n"
    )
    (root / "agents/ceo.md").write_text(
        "---\n"
        "name: corporate-ceo\n"
        "description: Route projects\n"
        "readonly: true\n"
        "---\n\n"
        "Return a packet.\n"
    )
    return root


def test_plugin_install_and_rollback(tmp_path: Path) -> None:
    source = make_plugin(tmp_path / "source", "1.0.0")
    runtime = tmp_path / "runtime"
    target = tmp_path / "plugins/corporate-site-harness"

    first = install_module.install_plugin(source, runtime, target, apply=True)
    (source / "agents/ceo.md").write_text(
        "---\n"
        "name: corporate-ceo\n"
        "description: Route projects\n"
        "readonly: true\n"
        "---\n\n"
        "Version two.\n"
    )
    second = install_module.install_plugin(source, runtime, target, apply=True)
    install_module.rollback_plugin(runtime, target, first["release_id"], apply=True)

    assert first["release_id"] != second["release_id"]
    assert "Return a packet." in (target / "agents/ceo.md").read_text()
    assert (
        json.loads((runtime / "current.json").read_text())["active_release"] == first["release_id"]
    )


def test_plugin_validation_rejects_path_escape(tmp_path: Path) -> None:
    plugin = tmp_path / "plugin"
    (plugin / ".cursor-plugin").mkdir(parents=True)
    (plugin / ".cursor-plugin/plugin.json").write_text('{"name":"bad","agents":"../agents"}\n')

    with pytest.raises(ContractError, match="escapes root"):
        install_module.validate_plugin(plugin)


def test_plugin_validation_rejects_symlink(tmp_path: Path) -> None:
    plugin = make_plugin(tmp_path / "plugin", "1.0.0")
    os.symlink(plugin / "agents/ceo.md", plugin / "agents/link.md")

    with pytest.raises(ContractError, match="symlink"):
        install_module.validate_plugin(plugin)


def test_rollback_rejects_release_path_escape(tmp_path: Path) -> None:
    with pytest.raises(ContractError, match="64 lowercase hexadecimal"):
        install_module.rollback_plugin(
            tmp_path / "runtime",
            tmp_path / "plugin",
            "../outside",
            apply=False,
        )


def test_rollback_rejects_corrupted_release(tmp_path: Path) -> None:
    source = make_plugin(tmp_path / "source", "1.0.0")
    runtime = tmp_path / "runtime"
    target = tmp_path / "corporate-site-harness"
    installed = install_module.install_plugin(source, runtime, target, apply=True)
    stored = runtime / "releases" / installed["release_id"] / "plugin" / "agents/ceo.md"
    stored.write_text("corrupted\n")

    with pytest.raises(ContractError, match="missing YAML|digest does not match"):
        install_module.rollback_plugin(runtime, target, installed["release_id"], apply=False)


def test_failed_first_activation_removes_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = make_plugin(tmp_path / "source", "1.0.0")
    runtime = tmp_path / "runtime"
    target = tmp_path / "corporate-site-harness"
    original = install_module._write_json

    def fail_current(path: Path, payload: dict) -> None:
        if path.name == "current.json":
            raise OSError("injected metadata failure")
        original(path, payload)

    monkeypatch.setattr(install_module, "_write_json", fail_current)

    with pytest.raises(OSError, match="injected metadata failure"):
        install_module.install_plugin(source, runtime, target, apply=True)
    assert not target.exists()


def test_install_rejects_runtime_target_overlap(tmp_path: Path) -> None:
    source = make_plugin(tmp_path / "source", "1.0.0")
    runtime = tmp_path / "corporate-site-harness"

    with pytest.raises(ContractError, match="must not overlap"):
        install_module.install_plugin(source, runtime, runtime, apply=False)


def test_install_rejects_unmanaged_existing_target(tmp_path: Path) -> None:
    source = make_plugin(tmp_path / "source", "1.0.0")
    runtime = tmp_path / "runtime"
    target = tmp_path / "corporate-site-harness"
    target.mkdir()
    (target / "unrelated.txt").write_text("keep\n")

    with pytest.raises(ContractError, match="unmanaged"):
        install_module.install_plugin(source, runtime, target, apply=True)
    assert (target / "unrelated.txt").read_text() == "keep\n"


def test_first_install_can_rollback_to_absent(tmp_path: Path) -> None:
    source = make_plugin(tmp_path / "source", "1.0.0")
    runtime = tmp_path / "runtime"
    target = tmp_path / "corporate-site-harness"

    install_module.install_plugin(source, runtime, target, apply=True)
    install_module.rollback_plugin(runtime, target, "absent", apply=True)

    assert not target.exists()
    assert json.loads((runtime / "current.json").read_text())["active_release"] is None


def test_absent_rollback_restores_target_when_metadata_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = make_plugin(tmp_path / "source", "1.0.0")
    runtime = tmp_path / "runtime"
    target = tmp_path / "corporate-site-harness"
    install_module.install_plugin(source, runtime, target, apply=True)
    original = install_module._write_json

    def fail_current(path: Path, payload: dict) -> None:
        if path.name == "current.json" and payload.get("active_release") is None:
            raise OSError("injected rollback metadata failure")
        original(path, payload)

    monkeypatch.setattr(install_module, "_write_json", fail_current)

    with pytest.raises(OSError, match="injected rollback metadata failure"):
        install_module.rollback_plugin(runtime, target, "absent", apply=True)
    assert target.is_dir()
    assert install_module.validate_plugin(target)["name"] == "corporate-site-harness"


def test_absent_rollback_rejects_identical_unmanaged_clone(tmp_path: Path) -> None:
    source = make_plugin(tmp_path / "source", "1.0.0")
    runtime = tmp_path / "runtime"
    managed = tmp_path / "managed/corporate-site-harness"
    clone = tmp_path / "clone/corporate-site-harness"
    install_module.install_plugin(source, runtime, managed, apply=True)
    clone.parent.mkdir()
    shutil.copytree(managed, clone)

    with pytest.raises(ContractError, match="managed target"):
        install_module.rollback_plugin(runtime, clone, "absent", apply=True)
    assert clone.is_dir()
    assert managed.is_dir()
