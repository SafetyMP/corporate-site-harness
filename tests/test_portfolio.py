from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest

from corp_harness.cli import main
from corp_harness.model import ContractError
from corp_harness.portfolio import (
    load_portfolio_contract,
    portfolio_check,
    portfolio_route,
    portfolio_status,
)


def _write_site(root: Path, *, executable: bool = True) -> None:
    corp = root / ".corp-harness"
    corp.mkdir(parents=True)
    (corp / "site.json").write_text(
        json.dumps(
            {
                "schema": "corporate-site-site/v1",
                "site_id": root.name,
                "corporate_program": None,
                "corporate_handoff_sha256": None,
                "verify_argv": ["./scripts/harness/verify.sh"],
                "adversarial_argv": ["./scripts/harness/adversarial.sh"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    harness = root / "scripts" / "harness"
    harness.mkdir(parents=True)
    for name in ("verify.sh", "adversarial.sh"):
        path = harness / name
        path.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        if executable:
            path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _contract(tmp_path: Path, entries: list[dict], **extra) -> Path:
    payload = {
        "schema": "corporate-site-portfolio/v1",
        "entries": entries,
        **extra,
    }
    path = tmp_path / "portfolio.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def test_loader_rejects_harness_profile_and_retired_tokens(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps(
            {
                "schema": "corporate-site-portfolio/v1",
                "entries": [
                    {
                        "site_id": "a",
                        "repo_path": str(tmp_path / "a"),
                        "harness": "site",
                        "harness_profile": "solo",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ContractError, match="harness_profile"):
        load_portfolio_contract(path)

    path.write_text(
        json.dumps(
            {
                "schema": "corporate-site-portfolio/v1",
                "entries": [
                    {
                        "site_id": "a",
                        "repo_path": str(tmp_path / "a"),
                        "harness": "site",
                        "note": "portfolio-ops mission",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ContractError, match="retired identifier"):
        load_portfolio_contract(path)


def test_inventory_and_readiness_and_route(tmp_path: Path) -> None:
    meta = tmp_path / "meta"
    app = tmp_path / "app"
    _write_site(meta)
    _write_site(app)
    (meta / "AGENTS.md").write_text("baseline\n", encoding="utf-8")
    (app / "AGENTS.md").write_text("baseline\n", encoding="utf-8")
    contract = _contract(
        tmp_path,
        [
            {
                "site_id": "meta",
                "repo_path": str(meta),
                "harness": "corporate",
            },
            {
                "site_id": "app",
                "repo_path": str(app),
                "harness": "site",
            },
        ],
        sensors=["parity"],
        parity_baseline_site_id="meta",
    )
    result = portfolio_check(contract)
    assert result["ok"] is True
    statuses = {item["name"]: item["status"] for item in result["sensors"]}
    assert statuses["inventory"] == "PASS"
    assert statuses["readiness"] == "PASS"
    assert statuses["parity"] == "PASS"

    program_root = tmp_path / "app-corporate-program"
    routed = portfolio_route(contract, target=app, program_root=program_root)
    assert routed["wrote"] is False
    assert routed["apply"] is False
    assert "--apply" not in routed["proposed_command"]
    assert not program_root.exists()


def test_route_rejects_nested_program_root(tmp_path: Path) -> None:
    app = tmp_path / "app"
    _write_site(app)
    contract = _contract(
        tmp_path,
        [{"site_id": "app", "repo_path": str(app), "harness": "site"}],
    )
    with pytest.raises(ContractError, match="must not be nested"):
        portfolio_route(contract, target=app, program_root=app / "programs" / "x")


def test_route_defaults_to_sibling_corporate_folder(tmp_path: Path) -> None:
    app = tmp_path / "app"
    _write_site(app)
    contract = _contract(
        tmp_path,
        [{"site_id": "app", "repo_path": str(app), "harness": "site"}],
    )
    routed = portfolio_route(contract, target=app)
    assert routed["program_root"] == str((tmp_path / "app-corporate-program").resolve())
    assert routed["proposed_command"][routed["proposed_command"].index("--site") + 1] == str(
        app.resolve()
    )


def test_live_harness_fails_without_chex_exception(tmp_path: Path) -> None:
    meta = tmp_path / "meta"
    _write_site(meta)
    (meta / ".harness").mkdir()
    contract = _contract(
        tmp_path,
        [{"site_id": "meta", "repo_path": str(meta), "harness": "corporate"}],
    )
    result = portfolio_check(contract)
    assert result["ok"] is False
    readiness = next(item for item in result["sensors"] if item["name"] == "readiness")
    assert readiness["status"] == "FAIL"


def test_classification_exception_allowlist(tmp_path: Path) -> None:
    orphan = tmp_path / "asclepius"
    orphan.mkdir()
    contract = _contract(
        tmp_path,
        [
            {
                "site_id": "asclepius",
                "repo_path": str(orphan),
                "harness": "site",
                "classification_exception": {"id": "asclepius"},
            }
        ],
    )
    assert portfolio_check(contract)["ok"] is True
    bad = _contract(
        tmp_path,
        [
            {
                "site_id": "other",
                "repo_path": str(orphan),
                "harness": "site",
                "classification_exception": {"id": "legacy-profile"},
            }
        ],
    )
    # rewrite unique path
    bad.write_text(
        json.dumps(
            {
                "schema": "corporate-site-portfolio/v1",
                "entries": [
                    {
                        "site_id": "other",
                        "repo_path": str(orphan),
                        "harness": "site",
                        "classification_exception": {"id": "legacy-profile"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ContractError, match="allow-listed"):
        load_portfolio_contract(bad)


def test_cli_portfolio_help_lists_subcommands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["portfolio", "--help"])
    assert excinfo.value.code == 0
    help_text = capsys.readouterr().out
    assert "status" in help_text
    assert "check" in help_text
    assert "route" in help_text


def test_cli_portfolio_check_and_write_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = tmp_path / "app"
    _write_site(app)
    contract = _contract(
        tmp_path,
        [{"site_id": "app", "repo_path": str(app), "harness": "site"}],
    )
    writes: list[Path] = []
    original = Path.write_text

    def tracked(self: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
        writes.append(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", tracked)
    output = tmp_path / "out.json"
    code = main(["portfolio", "check", "--contract", str(contract), "--output", str(output)])
    assert code == 0
    assert output in writes
    assert all(path == output or not str(path).startswith(str(app)) for path in writes)
    # ensure site tree untouched
    assert not (app / "program.json").exists()


def _write_program_root(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "program.json").write_text(
        json.dumps({"schema": "corporate-site-program/v1", "program_id": "p", "phase": "DESIGN"})
        + "\n",
        encoding="utf-8",
    )
    return root


def _status_payload(*, ok: bool, phase: str = "DESIGN") -> dict[str, Any]:
    return {
        "ok": ok,
        "program": {"phase": phase, "program_id": "p"},
        "issues": [] if ok else ["program unhealthy"],
        "trust_score": 0.85 if ok else 0.2,
        "execution_layer": "light" if ok else "heavy",
        "last_event": {"kind": "heartbeat"} if ok else {"kind": "issue"},
        "execution_policy": {
            "schema": "corporate-site-execution-policy/v1",
            "budget": {"max_premium_calls": 0},
            "premium_allowlist": [],
            "evidence_max_age_seconds": 3600,
        },
    }


def _mock_status_run(
    monkeypatch: pytest.MonkeyPatch, *, returncode: int, payload: dict[str, Any]
) -> None:
    def fake_run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["corp_harness", "status"],
            returncode=returncode,
            stdout=json.dumps(payload) + "\n",
            stderr="",
        )

    monkeypatch.setattr("corp_harness.portfolio.subprocess.run", fake_run)


def test_status_unknown_when_root_missing(tmp_path: Path) -> None:
    app = tmp_path / "app"
    _write_site(app)
    contract = _contract(
        tmp_path,
        [
            {
                "site_id": "app",
                "repo_path": str(app),
                "harness": "site",
                "active_program_root": str(tmp_path / "missing-program"),
            }
        ],
    )
    result = portfolio_status(contract)
    assert result["ok"] is False
    assert result["entries"][0]["state"] == "UNKNOWN"
    code = main(["portfolio", "status", "--contract", str(contract)])
    assert code == 1


def test_status_bound_when_status_exits_nonzero_with_valid_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = tmp_path / "app"
    program = tmp_path / "program"
    _write_site(app)
    _write_program_root(program)
    contract = _contract(
        tmp_path,
        [
            {
                "site_id": "app",
                "repo_path": str(app),
                "harness": "site",
                "active_program_root": str(program),
            }
        ],
    )
    payload = _status_payload(ok=False)
    _mock_status_run(monkeypatch, returncode=1, payload=payload)
    result = portfolio_status(contract)
    entry = result["entries"][0]
    assert result["ok"] is True
    assert entry["state"] == "BOUND"
    assert entry["ok"] is False
    assert entry["trust_score"] == payload["trust_score"]
    assert entry["execution_layer"] == payload["execution_layer"]
    assert entry["last_event"] == payload["last_event"]
    assert entry["phase"] == "DESIGN"
    assert entry["issues"] == ["program unhealthy"]
    assert entry["execution_policy"]["schema"] == "corporate-site-execution-policy/v1"


def test_status_bound_healthy_with_trust_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = tmp_path / "app"
    program = tmp_path / "program"
    _write_site(app)
    _write_program_root(program)
    contract = _contract(
        tmp_path,
        [
            {
                "site_id": "app",
                "repo_path": str(app),
                "harness": "site",
                "active_program_root": str(program),
            }
        ],
    )
    payload = _status_payload(ok=True, phase="APPROVED")
    _mock_status_run(monkeypatch, returncode=0, payload=payload)
    result = portfolio_status(contract)
    entry = result["entries"][0]
    assert result["ok"] is True
    assert entry["state"] == "BOUND"
    assert entry["ok"] is True
    assert entry["trust_score"] == payload["trust_score"]
    assert entry["execution_layer"] == payload["execution_layer"]
    assert entry["last_event"] == payload["last_event"]
    assert entry["phase"] == "APPROVED"
    assert entry["issues"] == []
    assert "premium_allowlist" in entry["execution_policy"]
