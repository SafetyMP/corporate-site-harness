from __future__ import annotations

import hashlib
import json
import os
import re
import resource
import signal
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

from corp_harness.model import ContractError, digest_path

MAX_CAPTURE_BYTES = 1_000_000
SAFE_ENV_KEYS = {
    "HOME",
    "LANG",
    "LC_ALL",
    "PATH",
    "PYTHONPATH",
    "TMPDIR",
    "VIRTUAL_ENV",
    # Session-active corporate root. Must reach verify.sh / dirty-scan children
    # so check --run binds the env-selected program, not a sibling marker.
    "CORP_HARNESS_PROGRAM_ROOT",
    # Site oracles (verify/adversarial) may need a provisioned app DSN + JWT for
    # nested Postgres proof. Values are redacted from captured stdout/stderr.
    "DATABASE_URL",
    "HR_ERP_VERIFY_DATABASE_URL",
    "JWT_SECRET",
    "NODE_ENV",
    "CI",
}
SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)\S+"),
    re.compile(r"(?i)((?:api[_-]?key|token|password|secret)\s*[=:]\s*)\S+"),
    re.compile(r"\b(?:sk|ghp|github_pat)_[A-Za-z0-9_\-]{12,}\b"),
    re.compile(r'(?i)("(?:api[_-]?key|token|password|secret)"\s*:\s*")[^"]*(")'),
)
SENSITIVE_FLAGS = {
    "--api-key",
    "--password",
    "--secret",
    "--token",
    "-p",
}


@dataclass(frozen=True)
class EvidenceResult:
    schema: str
    name: str
    revision: int | None
    target_sha256: str | None
    argv: list[str]
    cwd: str
    executable_path: str
    executable_sha256: str
    started_at: str
    finished_at: str
    duration_seconds: float
    exit_code: int
    passed: bool
    timed_out: bool
    stdout: str
    stderr: str
    stdout_sha256: str
    stderr_sha256: str
    truncated: bool


def run_evidence(
    name: str,
    argv: list[str],
    cwd: Path,
    allowed_root: Path,
    timeout_seconds: int,
    revision: int | None = None,
    target_sha256: str | None = None,
) -> EvidenceResult:
    if not name or not argv or any(not isinstance(item, str) or not item for item in argv):
        raise ContractError("evidence name and non-empty argv strings are required")
    if timeout_seconds < 1 or timeout_seconds > 3600:
        raise ContractError("timeout must be between 1 and 3600 seconds")

    resolved_root = allowed_root.expanduser().resolve()
    resolved_cwd = cwd.expanduser().resolve()
    if resolved_cwd != resolved_root and resolved_root not in resolved_cwd.parents:
        raise ContractError(f"evidence cwd is outside allowed root: {resolved_cwd}")
    if not resolved_cwd.is_dir():
        raise ContractError(f"evidence cwd is not a directory: {resolved_cwd}")
    resolved_executable = _validate_executable(argv[0], resolved_cwd, resolved_root)

    environment = {key: value for key, value in os.environ.items() if key in SAFE_ENV_KEYS}
    started_at = datetime.now(timezone.utc)
    started_clock = monotonic()
    deadline = started_clock + timeout_seconds
    timed_out = False
    exit_code = -1
    with tempfile.TemporaryDirectory(prefix="corp-harness-evidence-") as temporary_home:
        environment["HOME"] = temporary_home
        environment["TMPDIR"] = temporary_home
        environment["CORP_HARNESS_ALLOWED_HOST"] = "127.0.0.1"
        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            process = subprocess.Popen(
                argv,
                cwd=resolved_cwd,
                env=environment,
                stdout=stdout_file,
                stderr=stderr_file,
                shell=False,
                start_new_session=True,
                preexec_fn=_limit_child_files,
            )
            try:
                exit_code = process.wait(timeout=max(0.0, deadline - monotonic()))
            except subprocess.TimeoutExpired:
                timed_out = True
                _signal_process_group(process.pid, signal.SIGKILL)
                process.wait()
            else:
                _signal_process_group(process.pid, signal.SIGTERM)
            stdout_file.seek(0)
            stderr_file.seek(0)
            stdout_bytes = stdout_file.read(MAX_CAPTURE_BYTES + 1)
            stderr_bytes = stderr_file.read(MAX_CAPTURE_BYTES + 1)

    finished_at = datetime.now(timezone.utc)
    stdout, stdout_truncated = _decode_and_redact(stdout_bytes)
    stderr, stderr_truncated = _decode_and_redact(stderr_bytes)
    truncated = stdout_truncated or stderr_truncated
    return EvidenceResult(
        schema="corporate-site-evidence/v1",
        name=name,
        revision=revision,
        target_sha256=target_sha256,
        argv=_redact_argv(argv),
        cwd=str(resolved_cwd),
        executable_path=str(resolved_executable),
        executable_sha256=digest_path(resolved_executable),
        started_at=started_at.isoformat(),
        finished_at=finished_at.isoformat(),
        duration_seconds=round(monotonic() - started_clock, 6),
        exit_code=exit_code,
        passed=exit_code == 0 and not timed_out and not truncated,
        timed_out=timed_out,
        stdout=stdout,
        stderr=stderr,
        stdout_sha256=hashlib.sha256(stdout.encode("utf-8")).hexdigest(),
        stderr_sha256=hashlib.sha256(stderr.encode("utf-8")).hexdigest(),
        truncated=truncated,
    )


def write_evidence(result: EvidenceResult, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            json.dump(asdict(result), temporary, indent=2, sort_keys=True)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.chmod(temporary_name, 0o600)
        try:
            os.link(temporary_name, output_path)
        except FileExistsError as exc:
            raise ContractError(
                f"evidence is immutable and already exists: {output_path}"
            ) from exc
    finally:
        if temporary_name and Path(temporary_name).exists():
            Path(temporary_name).unlink()


def _validate_executable(executable: str, cwd: Path, allowed_root: Path) -> Path:
    if "/" not in executable:
        raise ContractError("evidence executable must be a contained path")
    candidate = Path(executable)
    resolved = (cwd / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    if resolved != allowed_root and allowed_root not in resolved.parents:
        raise ContractError(f"executable is outside allowed root: {resolved}")
    if not resolved.is_file():
        raise ContractError(f"executable does not exist: {resolved}")
    return resolved


def _limit_child_files() -> None:
    # Cap runaway single-file writes without blocking Next/Prisma builds.
    # stdout/stderr capture is still truncated to MAX_CAPTURE_BYTES separately.
    soft_hard = 2 * 1024 * 1024 * 1024  # 2 GiB
    resource.setrlimit(resource.RLIMIT_FSIZE, (soft_hard, soft_hard))


def _signal_process_group(pid: int, signal_number: int) -> None:
    try:
        os.killpg(pid, signal_number)
    except ProcessLookupError:
        return


def _decode_and_redact(value: bytes) -> tuple[str, bool]:
    truncated = len(value) > MAX_CAPTURE_BYTES
    text = value[:MAX_CAPTURE_BYTES].decode("utf-8", errors="replace")
    return _redact_text(text), truncated


def _redact_text(text: str) -> str:
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(_secret_replacement, text)
    return text


def _secret_replacement(match: re.Match[str]) -> str:
    if len(match.groups()) == 2:
        return f"{match.group(1)}[REDACTED]{match.group(2)}"
    if match.groups():
        return f"{match.group(1)}[REDACTED]"
    return "[REDACTED]"


def _redact_argv(argv: list[str]) -> list[str]:
    redacted: list[str] = []
    hide_next = False
    for item in argv:
        if hide_next:
            redacted.append("[REDACTED]")
            hide_next = False
            continue
        lowered = item.lower()
        if lowered in SENSITIVE_FLAGS:
            redacted.append(item)
            hide_next = True
            continue
        if any(lowered.startswith(f"{flag}=") for flag in SENSITIVE_FLAGS):
            redacted.append(item.split("=", 1)[0] + "=[REDACTED]")
            continue
        redacted.append(_redact_text(item))
    return redacted
