#!/usr/bin/env python3
"""Score model predictions against harness-llm eval grading fields."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

OUT = Path(__file__).resolve().parents[1]
DOMAINS = ("policy", "cli", "artifacts", "refusals")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def extract_json(text: str) -> dict[str, Any] | None:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    raw = fenced.group(1) if fenced else None
    if raw is None:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            raw = text[start : end + 1]
    if raw is None:
        return None
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def json_subset(expected: Any, actual: Any) -> bool:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        return all(k in actual and json_subset(v, actual[k]) for k, v in expected.items())
    if isinstance(expected, list):
        return expected == actual
    return expected == actual


def _forbidden_hit(assistant: str, bad: str, *, method: str) -> bool:
    if not bad or bad not in assistant:
        return False
    if method != "refuse":
        return True
    # Refusals may name the forbidden flag/action while rejecting it.
    lower = assistant.lower()
    refusal_markers = (
        "refuse",
        "never",
        "do not",
        "don't",
        "must not",
        "cannot",
        "stop",
        "agents never",
    )
    if any(m in lower for m in refusal_markers):
        return False
    return True


def grade(assistant: str, grading: dict[str, Any], gold: str) -> tuple[bool, str]:
    method = grading.get("method")
    must_include = grading.get("must_include") or []
    must_not = grading.get("must_not_include") or []

    for bad in must_not:
        if _forbidden_hit(assistant, bad, method=str(method)):
            return False, f"must_not_include hit: {bad!r}"

    if method == "exact_assistant":
        ok = assistant.strip() == gold.strip()
        return ok, "exact match" if ok else "assistant != gold"

    if method in {"contains_all", "refuse"}:
        missing = [m for m in must_include if m not in assistant]
        if missing:
            return False, f"missing {missing!r}"
        if method == "refuse":
            if not must_include:
                anchors = ("refuse", "Refuse", "never", "Never", "Stop", "cannot", "do not")
                if not any(a in assistant for a in anchors):
                    return False, "no refusal anchor"
        return True, "ok"

    if method == "json_subset":
        parsed = extract_json(assistant)
        if parsed is None:
            return False, "no JSON object in assistant"
        expected = grading.get("expected_json")
        if expected is None:
            return False, "expected_json is null"
        if not json_subset(expected, parsed):
            return False, "json_subset mismatch"
        missing = [m for m in must_include if m not in assistant]
        if missing:
            return False, f"missing {missing!r}"
        return True, "ok"

    return False, f"unknown method {method!r}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--predictions",
        required=True,
        type=Path,
        help="JSONL with id + assistant fields",
    )
    parser.add_argument("--out", type=Path, help="optional report JSON path")
    args = parser.parse_args()

    gold_by_id: dict[str, dict[str, Any]] = {}
    for domain in DOMAINS:
        path = OUT / "eval" / f"{domain}.jsonl"
        for row in load_jsonl(path):
            gold_by_id[row["id"]] = row

    preds = load_jsonl(args.predictions)
    pred_map = {p["id"]: p.get("assistant", "") for p in preds if "id" in p}

    results: list[dict[str, Any]] = []
    by_domain: dict[str, dict[str, int]] = {}
    for rid, gold in sorted(gold_by_id.items()):
        domain = gold["domain"]
        by_domain.setdefault(domain, {"passed": 0, "total": 0})
        by_domain[domain]["total"] += 1
        if rid not in pred_map:
            results.append(
                {"id": rid, "domain": domain, "passed": False, "reason": "missing prediction"}
            )
            continue
        gold_assistant = ""
        for msg in reversed(gold["messages"]):
            if msg.get("role") == "assistant":
                gold_assistant = msg.get("content", "")
                break
        ok, reason = grade(
            str(pred_map[rid]),
            gold["grading"],
            gold_assistant,
        )
        if ok:
            by_domain[domain]["passed"] += 1
        results.append({"id": rid, "domain": domain, "passed": ok, "reason": reason})

    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    report = {
        "passed": passed,
        "total": total,
        "accuracy": (passed / total) if total else 0.0,
        "by_domain": by_domain,
        "failures": [r for r in results if not r["passed"]],
    }
    text = json.dumps(report, indent=2) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
