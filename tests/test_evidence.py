import json
import os
import threading
from pathlib import Path
from time import monotonic

import pytest

from corp_harness.evidence import run_evidence, write_evidence
from corp_harness.model import ContractError


def script(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text("#!/bin/sh\nset -eu\n" + body, encoding="utf-8")
    os.chmod(path, 0o700)
    return path


def test_evidence_runs_without_shell_and_redacts_output(tmp_path: Path) -> None:
    script(tmp_path, "emit.sh", "echo 'token=super-secret-value'\n")
    result = run_evidence(
        "verify",
        ["./emit.sh"],
        tmp_path,
        tmp_path,
        10,
    )

    assert result.passed
    assert "super-secret-value" not in result.stdout
    assert all("super-secret-value" not in item for item in result.argv)
    assert "[REDACTED]" in result.stdout


def test_evidence_redacts_structured_arguments_and_json(tmp_path: Path) -> None:
    script(tmp_path, "emit.sh", """echo '{"token":"visible-secret"}'\n""")
    result = run_evidence(
        "verify",
        [
            "./emit.sh",
            "--token",
            "argument-secret",
        ],
        tmp_path,
        tmp_path,
        10,
    )

    assert "visible-secret" not in result.stdout
    assert "argument-secret" not in json.dumps(result.argv)


def test_evidence_rejects_cwd_outside_root(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    script(outside, "version.sh", "echo version\n")

    with pytest.raises(ContractError, match="outside allowed root"):
        run_evidence("verify", ["./version.sh"], outside, allowed, 10)


def test_evidence_timeout_is_a_failure(tmp_path: Path) -> None:
    script(tmp_path, "sleep.sh", "sleep 2\n")
    result = run_evidence(
        "timeout",
        ["./sleep.sh"],
        tmp_path,
        tmp_path,
        1,
    )

    assert result.timed_out
    assert not result.passed


def test_evidence_report_is_json(tmp_path: Path) -> None:
    script(tmp_path, "ok.sh", "echo ok\n")
    result = run_evidence(
        "verify",
        ["./ok.sh"],
        tmp_path,
        tmp_path,
        10,
    )
    output = tmp_path / "evidence.json"

    write_evidence(result, output)

    assert json.loads(output.read_text())["passed"] is True

    with pytest.raises(ContractError, match="immutable"):
        write_evidence(result, output)


def test_evidence_publication_is_atomic(tmp_path: Path) -> None:
    script(tmp_path, "ok.sh", "echo ok\n")
    result = run_evidence("verify", ["./ok.sh"], tmp_path, tmp_path, 10)
    output = tmp_path / "evidence.json"
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def publish() -> None:
        barrier.wait()
        try:
            write_evidence(result, output)
            outcomes.append("created")
        except ContractError:
            outcomes.append("rejected")

    threads = [threading.Thread(target=publish) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(outcomes) == ["created", "rejected"]
    assert json.loads(output.read_text())["passed"] is True


def test_evidence_output_limit_fails_closed(tmp_path: Path) -> None:
    script(tmp_path, "large.sh", "yes x | head -c 1500000\n")

    result = run_evidence("large", ["./large.sh"], tmp_path, tmp_path, 10)

    assert not result.passed
    assert len(result.stdout.encode()) <= 1_000_000


def test_background_descendant_cannot_hold_capture_open(tmp_path: Path) -> None:
    script(
        tmp_path,
        "background.sh",
        "python3 -c 'import subprocess; "
        'subprocess.Popen(["sleep", "30"], start_new_session=True)\'\n'
        "echo done\n",
    )
    started = monotonic()

    result = run_evidence("background", ["./background.sh"], tmp_path, tmp_path, 10)

    assert result.passed
    assert "done" in result.stdout
    assert monotonic() - started < 5
