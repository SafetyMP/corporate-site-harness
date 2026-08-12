"""Shared v2 handoff fixtures for factory tests."""

from __future__ import annotations

import json
from pathlib import Path

from corp_harness.model import digest_path
from corp_harness.site_gate_oracles import POINTER_KINDS, v2_handoff_body


def write(path: Path, value: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return path


def _blob(kind: str, extra: dict) -> dict:
    payload = {
        "schema": kind,
        "result": "PASS",
        "captured_at": "2026-08-12T00:00:00Z",
        "producer": "test",
    }
    payload.update(extra)
    return payload


def live_oracle_pointers(site: Path) -> dict[str, dict]:
    inventory = _blob(
        "surface_inventory/v1",
        {
            "taxonomy_version": "CR-8",
            "missing_cells": [],
            "cells": [
                {
                    "id": name,
                    "taxonomy": name,
                    "verdict": "OOS",
                    "owner": "test-dri",
                    "residual_risk": "fixture",
                    "probe_ref": None,
                }
                for name in (
                    "listen_bind",
                    "cors",
                    "metrics_authn",
                    "host_eval_fallback",
                    "sandbox_fallback",
                    "daemon_bind",
                )
            ],
        },
    )
    blobs = {
        "enforcement_path_parity": _blob(
            "enforcement_path_parity/v1",
            {
                "fixture": {
                    "principal": "User::\"a\"",
                    "action": "Action::\"x\"",
                    "resource": "Resource::\"y\"",
                },
                "paths": [
                    {
                        "id": "http",
                        "surface": "http_authorize",
                        "evaluator_identity": "official",
                        "decision": "deny",
                        "reachable": True,
                    }
                ],
                "shared_evaluator": True,
                "drift": {
                    "decision": False,
                    "evaluator_identity": False,
                    "undeclared_live_path": False,
                    "gate_side_door": False,
                },
            },
        ),
        "call_site_wiring": _blob(
            "call_site_wiring/v1",
            {
                "symbol": "authorize",
                "production_module": "src/app.py",
                "production_refs": [{"file": "src/app.py", "line": 1, "kind": "call"}],
                "test_only_refs": [],
            },
        ),
        "surface_inventory": inventory,
        "adversarial_corpus": _blob(
            "adversarial_corpus/v1",
            {
                "deny_case_extension": {
                    "mode": "append_only_findings",
                    "corpus_dir": "evidence/site-gate-oracles/deny-cases",
                    "hook_present": True,
                },
                "executed_cells": [
                    {
                        "deny_id": "fixture_denied",
                        "executed": True,
                        "denied": True,
                        "enforcement_path": "http_authorize",
                        "report_entry_id": "1",
                    }
                ],
                "uncovered_cells": [],
            },
        ),
    }
    pointers: dict[str, dict] = {}
    for field, payload in blobs.items():
        rel = f"evidence/site-gate-oracles/{field.replace('_', '-')}.json"
        path = write(site / rel, json.dumps(payload) + "\n")
        pointers[field] = {
            "path": rel,
            "sha256": digest_path(path),
            "kind": POINTER_KINDS[field],
        }
    deny_dir = site / "evidence/site-gate-oracles/deny-cases"
    deny_dir.mkdir(parents=True, exist_ok=True)
    write(deny_dir / "fixture_denied.json", json.dumps({"id": "fixture_denied"}) + "\n")
    return pointers


def write_v2_handoff(
    root: Path,
    site: Path,
    program,
    *,
    pending: bool = False,
    filename: str = "corporate-handoff.json",
) -> Path:
    master = program.artifacts["master_spec"].sha256
    acceptance = program.artifacts["acceptance"].sha256
    if pending:
        body = v2_handoff_body(
            program_id=program.program_id,
            site_path=str(site),
            master_sha256=master,
            acceptance_sha256=acceptance,
            pending=True,
        )
    else:
        pointers = live_oracle_pointers(site)
        body = v2_handoff_body(
            program_id=program.program_id,
            site_path=str(site),
            master_sha256=master,
            acceptance_sha256=acceptance,
            pending=False,
            pointers=pointers,
        )
    return write(root / filename, json.dumps(body) + "\n")
