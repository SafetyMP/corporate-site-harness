from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tarfile
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from corp_harness.model import ContractError

FORBIDDEN_NAMES = {".env", "secrets", "__pycache__", ".pytest_cache", ".ruff_cache"}
MAX_ARCHIVE_MEMBERS = 10_000
MAX_ARCHIVE_FILE_BYTES = 100 * 1024 * 1024
MAX_ARCHIVE_TOTAL_BYTES = 1024 * 1024 * 1024


def create_archive(
    source_root: Path,
    includes: list[str],
    destination: Path,
    apply: bool,
) -> dict[str, Any]:
    root = source_root.expanduser().resolve()
    selected = [_resolve_include(root, include) for include in includes]
    target = destination.expanduser().resolve()
    if any(
        target == selected_path
        or selected_path in target.parents
        or target in selected_path.parents
        for selected_path in selected
    ):
        raise ContractError("archive destination must not overlap selected source paths")
    files = _inventory(root, selected)
    plan = {
        "schema": "corporate-site-archive/v1",
        "source_root": str(root),
        "destination": str(target),
        "includes": includes,
        "file_count": len(files),
        "files": files,
        "apply": apply,
    }
    if not apply:
        return plan

    target.mkdir(parents=True, exist_ok=False, mode=0o700)
    os.chmod(target, 0o700)
    payload = target / "payload.tar.gz"
    with tarfile.open(payload, "w:gz", format=tarfile.PAX_FORMAT) as archive:
        for path in selected:
            archive.add(
                path,
                arcname=path.relative_to(root).as_posix(),
                recursive=True,
                filter=_tar_filter,
            )
    os.chmod(payload, 0o600)

    manifest = {
        **plan,
        "apply": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "archive": payload.name,
        "archive_sha256": _sha256(payload),
        "restore_verified": False,
    }
    manifest_path = target / "manifest.json"
    _write_private_json(manifest_path, manifest)
    verify_archive(manifest_path)
    manifest["restore_verified"] = True
    _write_private_json(manifest_path, manifest)
    _write_private_json(
        target / "ARCHIVE.OK",
        {
            "manifest_sha256": _sha256(manifest_path),
            "archive_sha256": manifest["archive_sha256"],
            "restore_verified": True,
        },
    )
    return manifest


def verify_archive(
    manifest_path: Path,
    payload_name: str | None = None,
) -> dict[str, Any]:
    raw = _read_manifest_json(manifest_path)
    if "payloads" in raw and payload_name is None:
        payloads = raw["payloads"]
        if not isinstance(payloads, list) or not payloads:
            raise ContractError("aggregate archive manifest requires payloads")
        verified = []
        for item in payloads:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                raise ContractError("aggregate archive payload is invalid")
            manifest = _load_manifest(manifest_path, item["name"])
            verified.append(_verify_manifest(manifest_path, manifest))
        return {
            "archive": str(manifest_path.parent),
            "file_count": sum(item["file_count"] for item in verified),
            "payloads": verified,
            "verified": True,
        }
    manifest = _load_manifest(manifest_path, payload_name)
    return _verify_manifest(manifest_path, manifest)


def _verify_manifest(manifest_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    payload = manifest_path.parent / manifest["archive"]
    if _sha256(payload) != manifest["archive_sha256"]:
        raise ContractError("archive payload digest mismatch")
    with tempfile.TemporaryDirectory(prefix="corp-harness-archive-verify-") as temporary:
        restore_root = Path(temporary)
        expected_paths = {item["path"] for item in manifest["files"]}
        _safe_extract(payload, restore_root, expected_paths)
        _apply_modes(restore_root, manifest["files"])
        actual = _inventory(restore_root, [restore_root])
        actual_map = {item["path"]: item for item in actual}
        expected_map = {item["path"]: item for item in manifest["files"]}
        if set(actual_map) != set(expected_map):
            raise ContractError("archive restore path set does not match manifest")
        for path, expected in expected_map.items():
            actual_item = actual_map[path]
            for field in ("size", "mode", "sha256"):
                if actual_item[field] != expected[field]:
                    raise ContractError(f"archive restore mismatch: {path}:{field}")
    return {
        "archive": str(payload),
        "file_count": len(manifest["files"]),
        "verified": True,
    }


def restore_archive(manifest_path: Path, target: Path, apply: bool) -> dict[str, Any]:
    return restore_archive_payload(manifest_path, target, apply, payload_name=None)


def restore_archive_payload(
    manifest_path: Path,
    target: Path,
    apply: bool,
    payload_name: str | None,
) -> dict[str, Any]:
    verification = verify_archive(manifest_path, payload_name)
    destination = target.expanduser().resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ContractError("restore target must be empty")
    result = {**verification, "target": str(destination), "apply": apply}
    if not apply:
        return result
    manifest = _load_manifest(manifest_path, payload_name)
    staging = destination.parent / f".{destination.name}.restore-{uuid.uuid4().hex}"
    staging.mkdir(parents=True, exist_ok=False)
    try:
        expected_paths = {item["path"] for item in manifest["files"]}
        _safe_extract(manifest_path.parent / manifest["archive"], staging, expected_paths)
        _apply_modes(staging, manifest["files"])
        actual = _inventory(staging, [staging])
        if {item["path"]: item for item in actual} != {
            item["path"]: item for item in manifest["files"]
        }:
            raise ContractError("staged archive restore does not match manifest")
        if destination.exists():
            destination.rmdir()
        os.replace(staging, destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return result


def restore_archive_merge(
    manifest_path: Path,
    target: Path,
    apply: bool,
    payload_name: str | None,
) -> dict[str, Any]:
    verification = verify_archive(manifest_path, payload_name)
    destination = target.expanduser().resolve()
    result = {**verification, "target": str(destination), "apply": apply, "merge": True}
    if not apply:
        return result
    destination.mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest(manifest_path, payload_name)
    staging = destination.parent / f".{destination.name}.merge-{uuid.uuid4().hex}"
    extracted = staging / "extracted"
    backup = staging / "backup"
    extracted.mkdir(parents=True)
    backup.mkdir()
    installed: list[Path] = []
    backed_up: list[tuple[Path, Path]] = []
    try:
        expected_paths = {item["path"] for item in manifest["files"]}
        _safe_extract(manifest_path.parent / manifest["archive"], extracted, expected_paths)
        _apply_modes(extracted, manifest["files"])
        for item in manifest["files"]:
            relative = Path(*PurePosixPath(item["path"]).parts)
            source = extracted / relative
            destination_file = _contained_destination(destination, relative)
            destination_file.parent.mkdir(parents=True, exist_ok=True)
            if destination_file.exists():
                if not destination_file.is_file() or destination_file.is_symlink():
                    raise ContractError(f"merge target is not a regular file: {relative}")
                backup_file = backup / relative
                backup_file.parent.mkdir(parents=True, exist_ok=True)
                os.replace(destination_file, backup_file)
                backed_up.append((backup_file, destination_file))
            temporary = destination_file.parent / (
                f".{destination_file.name}.restore-{uuid.uuid4().hex}"
            )
            shutil.copy2(source, temporary, follow_symlinks=False)
            os.chmod(temporary, int(item["mode"]))
            os.replace(temporary, destination_file)
            installed.append(destination_file)
    except Exception:
        for path in reversed(installed):
            if path.exists():
                path.unlink()
        for backup_file, original in reversed(backed_up):
            original.parent.mkdir(parents=True, exist_ok=True)
            os.replace(backup_file, original)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return result


def _contained_destination(root: Path, relative: Path) -> Path:
    candidate = root / relative
    root_real = root.resolve()
    for parent in (candidate.parent, *candidate.parent.parents):
        if parent == root_real.parent:
            break
        if parent.exists() and parent.is_symlink():
            raise ContractError(f"merge target contains symlink: {relative}")
    resolved_parent = candidate.parent.resolve()
    if resolved_parent != root_real and root_real not in resolved_parent.parents:
        raise ContractError(f"merge target escapes destination: {relative}")
    return candidate


def _resolve_include(root: Path, include: str) -> Path:
    pure = PurePosixPath(include)
    if pure.is_absolute() or ".." in pure.parts:
        raise ContractError(f"include must be a contained relative path: {include}")
    candidate = root
    for part in pure.parts:
        candidate /= part
        if candidate.is_symlink():
            raise ContractError(f"archive include contains symlink: {include}")
    path = candidate.resolve()
    if path != root and root not in path.parents:
        raise ContractError(f"include escapes source root: {include}")
    if not path.exists():
        raise ContractError(f"include does not exist: {include}")
    if any(part in FORBIDDEN_NAMES for part in pure.parts):
        raise ContractError(f"forbidden archive include: {include}")
    return path


def _inventory(root: Path, selected: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for selected_path in selected:
        paths = [selected_path] if selected_path.is_file() else sorted(selected_path.rglob("*"))
        for path in paths:
            rel = path.relative_to(root)
            if any(part in FORBIDDEN_NAMES for part in rel.parts):
                continue
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise ContractError(f"archive source contains symlink: {path}")
            if stat.S_ISDIR(info.st_mode):
                continue
            if not stat.S_ISREG(info.st_mode):
                raise ContractError(f"archive source contains unsupported file: {path}")
            records.append(
                {
                    "path": rel.as_posix(),
                    "size": info.st_size,
                    "mode": stat.S_IMODE(info.st_mode),
                    "sha256": _sha256(path),
                }
            )
    return sorted(records, key=lambda item: item["path"])


def _tar_filter(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    if any(part in FORBIDDEN_NAMES for part in PurePosixPath(info.name).parts):
        return None
    if info.issym() or info.islnk():
        raise ContractError(f"archive source contains link: {info.name}")
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    return info


def _safe_extract(payload: Path, target: Path, expected_paths: set[str]) -> None:
    target_real = target.resolve()
    with tarfile.open(payload, "r:gz") as archive:
        members: list[tarfile.TarInfo] = []
        regular_paths: set[str] = set()
        total_size = 0
        for count, member in enumerate(archive, start=1):
            if count > MAX_ARCHIVE_MEMBERS:
                raise ContractError("archive exceeds member-count limit")
            pure = PurePosixPath(member.name)
            if pure.is_absolute() or ".." in pure.parts or member.issym() or member.islnk():
                raise ContractError(f"unsafe archive member: {member.name}")
            if any(part in FORBIDDEN_NAMES for part in pure.parts):
                raise ContractError(f"forbidden archive member: {member.name}")
            if not (member.isdir() or member.isfile()):
                raise ContractError(f"unsupported archive member: {member.name}")
            if member.size > MAX_ARCHIVE_FILE_BYTES:
                raise ContractError(f"archive member exceeds size limit: {member.name}")
            total_size += member.size
            if total_size > MAX_ARCHIVE_TOTAL_BYTES:
                raise ContractError("archive exceeds aggregate size limit")
            resolved = (target / Path(*pure.parts)).resolve()
            if resolved != target_real and target_real not in resolved.parents:
                raise ContractError(f"archive member escapes target: {member.name}")
            if member.isfile():
                normalized = pure.as_posix()
                if normalized in regular_paths:
                    raise ContractError(f"duplicate archive member: {member.name}")
                regular_paths.add(normalized)
            members.append(member)
        if regular_paths != expected_paths:
            raise ContractError("archive file members do not match manifest")
        if total_size > shutil.disk_usage(target).free:
            raise ContractError("insufficient free space for archive extraction")
        archive.extractall(target, members=members, filter="data")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_manifest_json(path: Path) -> dict[str, Any]:
    try:
        if path.stat().st_size > 10 * 1024 * 1024:
            raise ValueError("archive manifest exceeds size limit")
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise TypeError("manifest root must be an object")
        if manifest.get("schema") != "corporate-site-archive/v1":
            raise ValueError("unsupported archive manifest")
        return manifest
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read archive manifest: {exc}") from exc


def _load_manifest(path: Path, payload_name: str | None = None) -> dict[str, Any]:
    try:
        raw = _read_manifest_json(path)
        if "payloads" in raw:
            if payload_name is None:
                raise ValueError("aggregate restore requires a payload name")
            payloads = raw["payloads"]
            if not isinstance(payloads, list):
                raise TypeError("aggregate payloads must be a list")
            matches = [
                item
                for item in payloads
                if isinstance(item, dict) and item.get("name") == payload_name
            ]
            if len(matches) != 1:
                raise ValueError(f"unknown or duplicate aggregate payload: {payload_name}")
            selected = matches[0]
            manifest = {
                "schema": raw["schema"],
                "source_root": selected.get("source_root"),
                "archive": selected.get("archive"),
                "archive_sha256": selected.get("archive_sha256"),
                "files": selected.get("files"),
            }
        else:
            manifest = raw
        archive_name = manifest.get("archive")
        if (
            not isinstance(archive_name, str)
            or PurePosixPath(archive_name).is_absolute()
            or ".." in PurePosixPath(archive_name).parts
        ):
            raise ValueError("archive filename must be contained")
        if not isinstance(manifest.get("archive_sha256"), str):
            raise TypeError("archive_sha256 must be a string")
        files = manifest.get("files")
        if not isinstance(files, list):
            raise TypeError("files must be a list")
        if len(files) > MAX_ARCHIVE_MEMBERS:
            raise ValueError("archive manifest exceeds file-count limit")
        seen: set[str] = set()
        for item in files:
            if not isinstance(item, dict) or not {
                "path",
                "size",
                "mode",
                "sha256",
            } <= set(item):
                raise TypeError("invalid archive file record")
            normalized = _manifest_file_path(item["path"])
            if normalized in seen:
                raise ValueError(f"duplicate archive file record: {normalized}")
            seen.add(normalized)
            item["path"] = normalized
            if (
                not isinstance(item["size"], int)
                or item["size"] < 0
                or item["size"] > MAX_ARCHIVE_FILE_BYTES
            ):
                raise ValueError(f"invalid archive file size: {normalized}")
            if (
                not isinstance(item["mode"], int)
                or item["mode"] < 0
                or item["mode"] > 0o777
            ):
                raise ValueError(f"invalid archive file mode: {normalized}")
            if (
                not isinstance(item["sha256"], str)
                or len(item["sha256"]) != 64
                or any(char not in "0123456789abcdef" for char in item["sha256"])
            ):
                raise ValueError(f"invalid archive file digest: {normalized}")
        return manifest
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read archive manifest: {exc}") from exc


def _apply_modes(target: Path, files: list[dict[str, Any]]) -> None:
    target_real = target.resolve()
    for item in files:
        normalized = _manifest_file_path(item["path"])
        path = target / Path(*PurePosixPath(normalized).parts)
        resolved = path.resolve()
        if resolved != target_real and target_real not in resolved.parents:
            raise ContractError(f"archive mode path escapes target: {normalized}")
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise ContractError(f"archive mode target is not a regular file: {normalized}")
        os.chmod(path, int(item["mode"]))


def _manifest_file_path(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("archive file path must be a string")
    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or not pure.parts
        or pure.as_posix() in {"", "."}
        or ".." in pure.parts
        or any(part in FORBIDDEN_NAMES for part in pure.parts)
    ):
        raise ValueError(f"archive file path must be contained: {value}")
    return pure.as_posix()


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
