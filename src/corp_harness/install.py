from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from corp_harness.model import ContractError

PLUGIN_COMPONENTS = ("agents", "commands", "hooks", "rules", "skills")
RELEASE_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def validate_plugin(source: Path) -> dict[str, Any]:
    root = source.expanduser().resolve()
    manifest_path = root / ".cursor-plugin" / "plugin.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise TypeError("plugin manifest root must be an object")
    except (OSError, TypeError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read plugin manifest: {exc}") from exc
    name = manifest.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ContractError("plugin manifest requires a non-empty name")

    resolved_components: dict[str, str] = {}
    for component in PLUGIN_COMPONENTS:
        configured = manifest.get(component)
        if configured is None:
            default = root / component
            if default.exists():
                resolved_components[component] = component
            continue
        if not isinstance(configured, str):
            raise ContractError(f"plugin component path must be a string: {component}")
        pure = PurePosixPath(configured)
        if pure.is_absolute() or ".." in pure.parts:
            raise ContractError(f"plugin component path escapes root: {configured}")
        resolved = (root / Path(*pure.parts)).resolve()
        if resolved != root and root not in resolved.parents:
            raise ContractError(f"plugin component path escapes root: {configured}")
        if not resolved.exists():
            raise ContractError(f"plugin component path is missing: {configured}")
        resolved_components[component] = configured

    files = _tree_manifest(root)
    components = _validate_components(root, resolved_components)
    return {
        "name": name,
        "root": str(root),
        "components": resolved_components,
        "component_validation": components,
        "file_count": len(files),
        "tree_sha256": _manifest_digest(files),
        "files": files,
    }


def install_plugin(
    source: Path,
    runtime_root: Path,
    plugin_target: Path,
    apply: bool,
) -> dict[str, Any]:
    validation = validate_plugin(source)
    runtime = runtime_root.expanduser().resolve()
    target = plugin_target.expanduser().resolve()
    _validate_install_paths(runtime, target, str(validation["name"]))
    release_id = validation["tree_sha256"]
    release_root = runtime / "releases" / release_id
    release_plugin = release_root / "plugin"
    result = {
        "release_id": release_id,
        "source": validation["root"],
        "release": str(release_root),
        "target": str(target),
        "apply": apply,
    }
    if not apply:
        return result

    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(runtime, 0o700)
    with _deployment_lock(target):
        if release_plugin.exists():
            _validate_release(release_root, release_id)
        else:
            _stage_release(validation, runtime, release_root, release_id)
        _activate_release(runtime, target, release_plugin, release_id)
    return result


def rollback_plugin(
    runtime_root: Path,
    plugin_target: Path,
    release_id: str,
    apply: bool,
) -> dict[str, Any]:
    runtime = runtime_root.expanduser().resolve()
    target = plugin_target.expanduser().resolve()
    if release_id == "absent":
        result = {
            "release_id": release_id,
            "source": None,
            "target": str(target),
            "apply": apply,
        }
        if not apply:
            return result
        runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
        with _deployment_lock(target):
            state = _current_state(runtime)
            current = state.get("active_release") if state else None
            if current is None:
                if target.exists():
                    raise ContractError("cannot remove an unmanaged plugin target")
                return result
            if state.get("target") != str(target):
                raise ContractError("plugin target does not match managed target")
            _validate_managed_target(runtime, target, current)
            transaction = runtime / "transactions" / (
                datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                + "-"
                + uuid.uuid4().hex
            )
            transaction.mkdir(parents=True, exist_ok=False)
            backup = transaction / "removed-plugin"
            os.replace(target, backup)
            try:
                _write_json(
                    runtime / "current.json",
                    {
                        "schema": "corporate-site-current/v1",
                        "active_release": None,
                        "previous_release": current,
                        "target": str(target),
                        "activated_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
            except Exception:
                os.replace(backup, target)
                raise
        return result
    if not RELEASE_ID_PATTERN.fullmatch(release_id):
        raise ContractError("release id must be exactly 64 lowercase hexadecimal characters")
    releases_root = (runtime / "releases").resolve()
    release_root = (releases_root / release_id).resolve()
    if releases_root not in release_root.parents:
        raise ContractError("release path escapes release store")
    source = release_root / "plugin"
    if not source.is_dir():
        raise ContractError(f"release does not exist: {release_id}")
    _validate_release(release_root, release_id)
    result = {
        "release_id": release_id,
        "source": str(source),
        "target": str(target),
        "apply": apply,
    }
    if not apply:
        return result
    return install_plugin(source, runtime, target, apply=True)


def _stage_release(
    validation: dict[str, Any],
    runtime: Path,
    release_root: Path,
    release_id: str,
) -> None:
    releases = runtime / "releases"
    releases.mkdir(parents=True, exist_ok=True)
    staging_root = releases / f".staging-{uuid.uuid4().hex}"
    try:
        staging_plugin = staging_root / "plugin"
        shutil.copytree(validation["root"], staging_plugin)
        if validate_plugin(staging_plugin)["tree_sha256"] != release_id:
            raise ContractError("staged plugin digest does not match source")
        _write_json(
            staging_root / "release.json",
            {
                "schema": "corporate-site-release/v1",
                "release_id": release_id,
                "built_at": datetime.now(timezone.utc).isoformat(),
                "files": validation["files"],
            },
        )
        os.replace(staging_root, release_root)
    finally:
        if staging_root.exists():
            shutil.rmtree(staging_root)


def _validate_release(release_root: Path, expected_id: str) -> None:
    try:
        manifest = json.loads((release_root / "release.json").read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise TypeError("release manifest root must be an object")
        if (
            manifest.get("schema") != "corporate-site-release/v1"
            or manifest.get("release_id") != expected_id
            or not isinstance(manifest.get("files"), list)
        ):
            raise ValueError("release manifest identity is invalid")
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid stored release: {exc}") from exc
    validation = validate_plugin(release_root / "plugin")
    if validation["tree_sha256"] != expected_id:
        raise ContractError("stored release tree digest does not match release id")
    if validation["files"] != manifest["files"]:
        raise ContractError("stored release file manifest does not match plugin tree")


def _activate_release(
    runtime: Path,
    target: Path,
    release_plugin: Path,
    release_id: str,
) -> None:
    previous_release = _current_release(runtime)
    if target.exists():
        if previous_release is None:
            raise ContractError("refusing to replace an unmanaged plugin target")
        _validate_managed_target(runtime, target, previous_release)
    staging = target.parent / f".{target.name}.staging-{uuid.uuid4().hex}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(release_plugin, staging)
    if validate_plugin(staging)["tree_sha256"] != release_id:
        shutil.rmtree(staging)
        raise ContractError("install staging digest does not match release")

    backup: Path | None = None
    target_existed = target.exists()
    try:
        if target_existed:
            transaction = (
                runtime
                / "transactions"
                / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex)
            )
            transaction.mkdir(parents=True, exist_ok=False)
            candidate_backup = transaction / "previous-plugin"
            os.replace(target, candidate_backup)
            backup = candidate_backup
        os.replace(staging, target)
        _write_json(
            runtime / "current.json",
            {
                "schema": "corporate-site-current/v1",
                "active_release": release_id,
                "previous_release": previous_release,
                "target": str(target),
                "activated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    except Exception:
        if target.exists() and (backup is not None or not target_existed):
            shutil.rmtree(target)
        if backup is not None and backup.exists():
            os.replace(backup, target)
        if staging.exists():
            shutil.rmtree(staging)
        raise


@contextmanager
def _deployment_lock(target: Path):
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.parent / f".{target.name}.deploy.lock"
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        yield


def _validate_install_paths(runtime: Path, target: Path, plugin_name: str) -> None:
    if target.name != plugin_name:
        raise ContractError(f"plugin target must end with {plugin_name}")
    if (
        runtime == target
        or runtime in target.parents
        or target in runtime.parents
    ):
        raise ContractError("plugin target and runtime root must not overlap")


def _validate_managed_target(runtime: Path, target: Path, release_id: str) -> None:
    state = _current_state(runtime)
    if (
        state is None
        or state.get("active_release") != release_id
        or state.get("target") != str(target)
    ):
        raise ContractError("plugin target does not match managed activation metadata")
    release_root = runtime / "releases" / release_id
    _validate_release(release_root, release_id)
    active = validate_plugin(target)
    if active["tree_sha256"] != release_id:
        raise ContractError("active plugin target does not match managed release")


def _tree_manifest(root: Path) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ContractError(f"plugin contains symlink: {path}")
        if path.is_dir():
            continue
        if not stat.S_ISREG(info.st_mode):
            raise ContractError(f"plugin contains unsupported file: {path}")
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "mode": stat.S_IMODE(info.st_mode),
                "size": info.st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    return files


def _validate_components(root: Path, configured: dict[str, str]) -> dict[str, Any]:
    validation: dict[str, Any] = {}
    agents: dict[str, bool] = {}
    always_on_words = 0
    component_patterns = {
        "agents": ("*.md", ("name", "description", "readonly")),
        "commands": ("*.md", ("name", "description")),
        "rules": ("*.mdc", ("description", "alwaysApply")),
        "skills": ("*/SKILL.md", ("name", "description")),
    }
    for component, (pattern, required) in component_patterns.items():
        if component not in configured:
            continue
        component_root = (root / configured[component]).resolve()
        names: set[str] = set()
        files = sorted(component_root.glob(pattern))
        if not files:
            raise ContractError(f"plugin component has no discoverable files: {component}")
        for path in files:
            frontmatter, body = _frontmatter(path)
            missing = [field for field in required if field not in frontmatter]
            if missing:
                raise ContractError(f"{path} missing frontmatter: {', '.join(missing)}")
            component_name = frontmatter.get("name")
            if component_name:
                if component_name in names:
                    raise ContractError(f"duplicate {component} name: {component_name}")
                names.add(component_name)
            if component == "agents":
                readonly = _boolean(frontmatter["readonly"], path)
                agents[str(component_name)] = readonly
            if component == "rules" and _boolean(frontmatter["alwaysApply"], path):
                always_on_words += len(body.split())
        validation[component] = {"count": len(files), "names": sorted(names)}

    if always_on_words > 250:
        raise ContractError(f"always-on rule budget exceeded: {always_on_words} words")
    validation["always_on_words"] = always_on_words

    policy_path = root / "policy" / "roles.json"
    if policy_path.exists():
        try:
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ContractError(f"invalid role policy: {exc}") from exc
        policy_roles = policy.get("roles")
        if not isinstance(policy_roles, dict):
            raise ContractError("role policy requires a roles object")
        if set(policy_roles) != set(agents):
            raise ContractError("agent files and role policy names differ")
        for name, settings in policy_roles.items():
            if not isinstance(settings, dict) or settings.get("readonly") is not agents[name]:
                raise ContractError(f"role policy readonly mismatch: {name}")
        validation["role_policy"] = {"count": len(policy_roles), "matched": True}
    return validation


def _frontmatter(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ContractError(f"{path} is missing YAML frontmatter")
    parts = text.split("---\n", 2)
    if len(parts) != 3:
        raise ContractError(f"{path} has unterminated YAML frontmatter")
    values: dict[str, str] = {}
    for line in parts[1].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise ContractError(f"{path} has invalid frontmatter line: {line}")
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    return values, parts[2]


def _boolean(value: str, path: Path) -> bool:
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    raise ContractError(f"{path} has non-boolean frontmatter value: {value}")


def _manifest_digest(files: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for item in files:
        digest.update(json.dumps(item, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _current_release(runtime: Path) -> str | None:
    state = _current_state(runtime)
    value = state.get("active_release") if state else None
    return value if isinstance(value, str) else None


def _current_state(runtime: Path) -> dict[str, Any] | None:
    current = runtime / "current.json"
    if not current.exists():
        return None
    try:
        state = json.loads(current.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read activation metadata: {exc}") from exc
    if not isinstance(state, dict) or state.get("schema") != "corporate-site-current/v1":
        raise ContractError("activation metadata is invalid")
    return state


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            json.dump(payload, temporary, indent=2, sort_keys=True)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
    finally:
        if temporary_name and Path(temporary_name).exists():
            Path(temporary_name).unlink()
