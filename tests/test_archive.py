import hashlib
import json
import os
import shutil
import tarfile
from pathlib import Path

import pytest

from corp_harness.archive import (
    create_archive,
    restore_archive,
    restore_archive_merge,
    restore_archive_payload,
    verify_archive,
)
from corp_harness.model import ContractError


def test_archive_round_trip(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "config").mkdir()
    (source / "config/settings.json").write_text('{"enabled":true}\n')
    os.chmod(source / "config/settings.json", 0o400)
    destination = tmp_path / "archive"

    manifest = create_archive(source, ["config"], destination, apply=True)
    verification = verify_archive(destination / "manifest.json")
    restored = tmp_path / "restored"
    restore_archive(destination / "manifest.json", restored, apply=True)

    assert manifest["restore_verified"] is True
    assert verification["verified"] is True
    assert (restored / "config/settings.json").read_text() == '{"enabled":true}\n'
    assert oct((restored / "config/settings.json").stat().st_mode & 0o777) == "0o400"
    assert oct(destination.stat().st_mode & 0o777) == "0o700"
    assert json.loads((destination / "ARCHIVE.OK").read_text())["restore_verified"] is True


def test_archive_is_dry_run_by_default(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "value.txt").write_text("value\n")
    destination = tmp_path / "archive"

    result = create_archive(source, ["value.txt"], destination, apply=False)

    assert result["file_count"] == 1
    assert not destination.exists()


def test_archive_rejects_forbidden_files(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / ".env").write_text("TOKEN=secret\n")

    with pytest.raises(ContractError, match="forbidden archive include"):
        create_archive(source, [".env"], tmp_path / "archive", apply=False)


def test_archive_rejects_symlinks(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "real.txt").write_text("value\n")
    os.symlink(source / "real.txt", source / "link.txt")

    with pytest.raises(ContractError, match="symlink"):
        create_archive(source, ["link.txt"], tmp_path / "archive", apply=False)


def test_archive_rejects_destination_inside_source(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "value.txt").write_text("value\n")

    with pytest.raises(ContractError, match="must not overlap"):
        create_archive(source, ["."], source / "archive", apply=True)


def test_archive_manifest_rejects_path_escape_before_chmod(tmp_path: Path) -> None:
    victim = tmp_path / "victim"
    victim.write_text("safe\n")
    os.chmod(victim, 0o600)
    archive = tmp_path / "archive"
    archive.mkdir()
    payload = archive / "payload.tar.gz"
    with tarfile.open(payload, "w:gz"):
        pass
    manifest = {
        "schema": "corporate-site-archive/v1",
        "archive": payload.name,
        "archive_sha256": hashlib.sha256(payload.read_bytes()).hexdigest(),
        "files": [
            {
                "path": "../victim",
                "size": 5,
                "mode": 0o777,
                "sha256": hashlib.sha256(b"safe\n").hexdigest(),
            }
        ],
    }
    manifest_path = archive / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(ContractError, match="contained"):
        verify_archive(manifest_path)
    assert victim.stat().st_mode & 0o777 == 0o600


def test_archive_rejects_forbidden_unmanifested_member(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    archive.mkdir()
    secret = tmp_path / ".env"
    secret.write_text("TOKEN=value\n")
    payload = archive / "payload.tar.gz"
    with tarfile.open(payload, "w:gz") as bundle:
        bundle.add(secret, arcname=".env")
    manifest = {
        "schema": "corporate-site-archive/v1",
        "archive": payload.name,
        "archive_sha256": hashlib.sha256(payload.read_bytes()).hexdigest(),
        "files": [],
    }
    manifest_path = archive / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(ContractError, match="forbidden archive member"):
        verify_archive(manifest_path)


def test_aggregate_archive_can_verify_and_restore_named_payload(tmp_path: Path) -> None:
    aggregate = tmp_path / "aggregate"
    aggregate.mkdir()
    payloads = []
    for name in ("global-v4", "test-site-prepilot"):
        source = tmp_path / name
        source.mkdir()
        (source / "value.txt").write_text(name + "\n")
        built = tmp_path / f"{name}-built"
        manifest = create_archive(source, ["value.txt"], built, apply=True)
        archive_name = f"{name}.tar.gz"
        shutil.copy2(built / "payload.tar.gz", aggregate / archive_name)
        payloads.append(
            {
                "name": name,
                "source_root": str(source),
                "archive": archive_name,
                "archive_sha256": manifest["archive_sha256"],
                "files": manifest["files"],
            }
        )
    manifest_path = aggregate / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema": "corporate-site-archive/v1",
                "payloads": payloads,
            }
        )
    )

    assert verify_archive(manifest_path)["verified"] is True
    restored = tmp_path / "restored"
    restore_archive_payload(
        manifest_path,
        restored,
        apply=True,
        payload_name="global-v4",
    )
    assert (restored / "value.txt").read_text() == "global-v4\n"


def test_merge_restore_preserves_unarchived_state(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "rules").mkdir()
    (source / "rules/policy.mdc").write_text("legacy\n")
    archive = tmp_path / "archive"
    create_archive(source, ["rules"], archive, apply=True)
    live = tmp_path / "live"
    (live / "rules").mkdir(parents=True)
    (live / "rules/policy.mdc").write_text("replacement\n")
    (live / "projects").mkdir()
    (live / "projects/keep.txt").write_text("unmanaged\n")

    restore_archive_merge(
        archive / "manifest.json",
        live,
        apply=True,
        payload_name=None,
    )

    assert (live / "rules/policy.mdc").read_text() == "legacy\n"
    assert (live / "projects/keep.txt").read_text() == "unmanaged\n"
