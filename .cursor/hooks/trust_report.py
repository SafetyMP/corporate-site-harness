#!/usr/bin/env python3
"""Factory Cursor hooks → corp-harness trust report-event (sole anti-harness path).

Non-secret payloads only. Never passes --actor user. Never writes sole-writer
trust files except through `trust report-event`.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

PROGRAM_ROOT_ENV = "CORP_HARNESS_PROGRAM_ROOT"
PROGRAM_ROOT_MARKER = ".corp-harness-program-root"

FACTORY_PREFIXES = (
    "src/corp_harness/",
    "swift/",
    "tests/",
    "docs/adr/",
    "scripts/harness/",
    "corporate/plugin/corporate-site-harness/",
    ".cursor/",
)
FACTORY_FILES = frozenset(
    {"pyproject.toml", "AGENTS.md", ".corp-harness-program-root", ".cursor"}
)
CORPORATE_FILES = frozenset(
    {
        "program.json",
        "trust-state.json",
        "trust-event-log.jsonl",
        "trust-mutation-permit.json",
        "trust-log-anchor.json",
        "trust-chain-recovery.json",
        "trust-surface-baseline.json",
        "master-spec.md",
        "acceptance.json",
        "gates.json",
        "kpis.json",
        "corporate-handoff.json",
        "factory-authorization.json",
        "user-approval.json",
        "final-dossier.md",
    }
)


def _factory_root() -> Path:
    return Path.cwd().resolve()


def _resolve_program_root(factory: Path) -> Path | None:
    env = os.environ.get(PROGRAM_ROOT_ENV, "").strip()
    if env:
        candidate = Path(env).expanduser().resolve()
        if candidate.is_dir() and (candidate / "program.json").is_file():
            return candidate
        return None
    marker = factory / PROGRAM_ROOT_MARKER
    if not marker.is_file():
        return None
    raw = marker.read_text(encoding="utf-8").strip()
    if not raw:
        return None
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = (factory / candidate).resolve()
    else:
        candidate = candidate.resolve()
    if candidate.is_dir() and (candidate / "program.json").is_file():
        return candidate
    return None


def _rel_to(path: Path, root: Path) -> str | None:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


def _is_protected_factory(rel: str) -> bool:
    normalized = rel.lstrip("./")
    if normalized in FACTORY_FILES or normalized == ".cursor":
        return True
    if normalized.startswith(".cursor/"):
        return True
    return any(
        normalized == p.rstrip("/") or normalized.startswith(p) for p in FACTORY_PREFIXES
    )


def _is_protected_corporate(rel: str) -> bool:
    normalized = rel.lstrip("./")
    if normalized in CORPORATE_FILES:
        return True
    return normalized.startswith("evidence/")


def _permit_covers(program_root: Path, rel: str) -> bool:
    permit_path = program_root / "trust-mutation-permit.json"
    if not permit_path.is_file():
        return False
    try:
        permit = json.loads(permit_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    paths = permit.get("paths")
    if not isinstance(paths, list):
        return False
    return any(str(p) == rel or rel.startswith(str(p).rstrip("/") + "/") for p in paths)


def _marker_establishes_valid_bind(factory: Path, path: Path) -> bool:
    """True when editing the bind marker to a resolvable corporate program root."""
    try:
        if path.resolve() != (factory / PROGRAM_ROOT_MARKER).resolve():
            return False
    except OSError:
        return False
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    if not raw:
        return False
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = (factory / candidate).resolve()
    else:
        candidate = candidate.resolve()
    return candidate.is_dir() and (candidate / "program.json").is_file()


def _classify_edit(
    factory: Path, program_root: Path, file_path: str
) -> tuple[str, str] | None:
    """Return (signal, protected_path) when edit is anti-harness."""
    path = Path(file_path).expanduser()
    if not path.is_absolute():
        path = (factory / path).resolve()
    else:
        path = path.resolve()
    # Establishing / refreshing a valid program-root bind is not OOB theater.
    if _marker_establishes_valid_bind(factory, path):
        return None
    factory_rel = _rel_to(path, factory)
    if factory_rel and _is_protected_factory(factory_rel):
        if _permit_covers(program_root, factory_rel):
            return None
        return "out_of_band_mutation", factory_rel
    corp_rel = _rel_to(path, program_root)
    if corp_rel and _is_protected_corporate(corp_rel):
        if _permit_covers(program_root, corp_rel):
            return None
        return "out_of_band_mutation", corp_rel
    return None


def _is_authorized_harness_command(command: str) -> bool:
    """Allow harness control-plane / oracle / test runners under a bound root.

    These mutate only through Python sole-writer paths (emit_and_apply, record
    with permits). Misclassifying them as OOB blocks legitimate SITE_DELIVERY.
    """
    lowered = f" {command.lower()} "
    needles = (
        " -m corp_harness",
        " -m corp_harness.cli",
        " corp-harness ",
        " -m pytest",
        " pytest ",
        "scripts/harness/verify.sh",
        "scripts/harness/adversarial.sh",
        " ruff check ",
        " python3 -m ruff ",
        "python3 .cursor/hooks/trust_report.py",
    )
    return any(needle in lowered for needle in needles)


def _classify_shell(
    factory: Path, program_root: Path, command: str
) -> tuple[str, str] | None:
    """Heuristic: shell touching protected relative paths → anti-harness."""
    if _is_authorized_harness_command(command):
        return None
    tokens = command.replace("\t", " ").split()
    candidates: list[str] = []
    for token in tokens:
        cleaned = token.strip("'\"")
        if not cleaned or cleaned.startswith("-"):
            continue
        if any(
            cleaned == name
            or cleaned.endswith("/" + name)
            or cleaned.startswith(name + "/")
            or f"/{name}" in cleaned
            for name in (
                *CORPORATE_FILES,
                *FACTORY_FILES,
                "src/corp_harness",
                ".cursor",
                "trust-state.json",
            )
        ):
            candidates.append(cleaned)
    for raw in candidates:
        path = Path(raw)
        for root, checker in (
            (factory, _is_protected_factory),
            (program_root, _is_protected_corporate),
        ):
            candidate = path if path.is_absolute() else (root / path)
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            rel = _rel_to(resolved, root)
            if rel and checker(rel):
                if _permit_covers(program_root, rel):
                    continue
                return "out_of_band_mutation", rel
    # Destructive patterns without going through harness CLI fail closed.
    lowered = command.lower()
    if any(
        needle in lowered
        for needle in (
            "rm -",
            " git checkout ",
            "git restore ",
            "truncate ",
        )
    ) and any(
        name in command
        for name in (
            "program.json",
            "trust-state",
            "trust-event-log",
            ".cursor",
            "hooks.json",
            "corp_harness",
        )
    ):
        return "out_of_band_mutation", ".cursor/hooks.json"
    return None


def _report_event(
    factory: Path,
    program_root: Path,
    *,
    signal: str,
    reason: str,
    protected_path: str,
) -> int:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(factory / "src") + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    cmd = [
        sys.executable,
        "-m",
        "corp_harness.cli",
        "trust",
        "report-event",
        "--root",
        str(program_root),
        "--signal",
        signal,
        "--reason",
        reason,
        "--path",
        protected_path,
    ]
    # Never --actor user. stdout/stderr discarded beyond exit status for hooks.
    completed = subprocess.run(
        cmd,
        cwd=str(factory),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode


def _emit_shell_permission(permission: str) -> None:
    json.dump({"permission": permission}, sys.stdout)
    sys.stdout.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Anti-harness Cursor project hook")
    parser.add_argument(
        "--event",
        required=True,
        choices=("afterFileEdit", "beforeShellExecution"),
    )
    args = parser.parse_args(argv)
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    factory = _factory_root()
    program_root = _resolve_program_root(factory)
    if program_root is None:
        # Ordinary / unbound coding: soft-allow (no trust mutation).
        if args.event == "beforeShellExecution":
            _emit_shell_permission("allow")
        return 0

    if args.event == "afterFileEdit":
        file_path = str(payload.get("file_path") or "")
        # Non-secret: path only (never edits/contents).
        finding = _classify_edit(factory, program_root, file_path) if file_path else None
        if finding is None:
            return 0
        signal, protected = finding
        code = _report_event(
            factory,
            program_root,
            signal=signal,
            reason=f"cursor-hook:afterFileEdit path={protected}",
            protected_path=protected,
        )
        return 0 if code == 0 else 2

    command = str(payload.get("command") or "")
    finding = _classify_shell(factory, program_root, command) if command else None
    if finding is None:
        _emit_shell_permission("allow")
        return 0
    signal, protected = finding
    code = _report_event(
        factory,
        program_root,
        signal=signal,
        reason=f"cursor-hook:beforeShellExecution path={protected}",
        protected_path=protected,
    )
    # Fail closed for emit when bound + anti-harness.
    if code == 0:
        _emit_shell_permission("deny")
        return 2
    _emit_shell_permission("deny")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
