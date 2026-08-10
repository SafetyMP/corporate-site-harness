#!/usr/bin/env python3
"""Validate harness-llm JSONL schema, IDs, and split disjointness."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

OUT = Path(__file__).resolve().parents[1]
DOMAINS = ("policy", "cli", "artifacts", "refusals")
SPLITS = ("train", "eval")
REQUIRED = ("id", "domain", "task_type", "difficulty", "messages", "meta")
TASK_TYPES = {
    "qa",
    "decision",
    "cli_compose",
    "json_emit",
    "refuse",
    "trajectory",
}
DIFFICULTIES = {"easy", "medium", "hard"}
GRADE_METHODS = {"contains_all", "exact_assistant", "json_subset", "refuse"}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path}:{line_no}: invalid JSON: {exc}") from exc
        if not isinstance(obj, dict):
            raise SystemExit(f"{path}:{line_no}: record must be an object")
        rows.append(obj)
    return rows


def validate_messages(messages: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(messages, list) or len(messages) < 3:
        return ["messages must be a list with length >= 3"]
    if not isinstance(messages[0], dict) or messages[0].get("role") != "system":
        errors.append("messages[0].role must be system")
    if not isinstance(messages[-1], dict) or messages[-1].get("role") != "assistant":
        errors.append("messages[-1].role must be assistant")
    expected = "user"
    for idx in range(1, len(messages)):
        msg = messages[idx]
        if not isinstance(msg, dict):
            errors.append(f"messages[{idx}] must be an object")
            continue
        role = msg.get("role")
        if role != expected:
            errors.append(f"messages[{idx}].role must be {expected}, got {role!r}")
        if not isinstance(msg.get("content"), str) or not str(msg.get("content")).strip():
            errors.append(f"messages[{idx}].content must be non-empty string")
        expected = "assistant" if expected == "user" else "user"
    # Valid dialogues end on assistant, leaving expected == "user".
    if expected != "user":
        errors.append("messages must end on assistant with alternating user/assistant turns")
    return errors


def validate_record(obj: dict[str, Any], *, split: str, domain: str) -> list[str]:
    errors: list[str] = []
    for key in REQUIRED:
        if key not in obj:
            errors.append(f"missing {key}")
    if errors:
        return errors

    rid = obj["id"]
    if obj["domain"] != domain:
        errors.append(f"domain {obj['domain']!r} != file domain {domain!r}")
    if obj["task_type"] not in TASK_TYPES:
        errors.append(f"bad task_type {obj['task_type']!r}")
    if obj["difficulty"] not in DIFFICULTIES:
        errors.append(f"bad difficulty {obj['difficulty']!r}")
    if not isinstance(rid, str) or not rid.startswith(f"{domain}-{split}-"):
        errors.append(f"id {rid!r} must start with {domain}-{split}-")

    errors.extend(validate_messages(obj["messages"]))

    meta = obj["meta"]
    if not isinstance(meta, dict) or not isinstance(meta.get("source_refs"), list):
        errors.append("meta.source_refs must be a list")

    if split == "eval":
        grading = obj.get("grading")
        if not isinstance(grading, dict):
            errors.append("eval records require grading object")
        else:
            if grading.get("method") not in GRADE_METHODS:
                errors.append(f"bad grading.method {grading.get('method')!r}")
            for field in ("must_include", "must_not_include"):
                if not isinstance(grading.get(field), list):
                    errors.append(f"grading.{field} must be a list")
            if "expected_json" not in grading:
                errors.append("grading.expected_json required (may be null)")
            if domain == "refusals":
                forbid = grading.get("must_not_include") or []
                if "--actor user" not in forbid:
                    errors.append("refusals eval must forbid `--actor user`")
    return errors


def main() -> int:
    errors: list[str] = []
    ids_by_split: dict[str, set[str]] = {s: set() for s in SPLITS}
    counts: dict[str, dict[str, int]] = {s: {} for s in SPLITS}
    prompt_keys: dict[str, set[str]] = {s: set() for s in SPLITS}

    for split in SPLITS:
        for domain in DOMAINS:
            path = OUT / split / f"{domain}.jsonl"
            if not path.is_file():
                errors.append(f"missing file {path}")
                continue
            rows = load_jsonl(path)
            counts[split][domain] = len(rows)
            for obj in rows:
                rid = obj.get("id", "<missing>")
                for err in validate_record(obj, split=split, domain=domain):
                    errors.append(f"{path.name}:{rid}: {err}")
                if rid in ids_by_split[split]:
                    errors.append(f"duplicate id in {split}: {rid}")
                ids_by_split[split].add(rid)
                # Dialogue leakage check (all non-system content)
                msgs = obj.get("messages") or []
                key = " ".join(
                    " ".join(m.get("content", "") for m in msgs if m.get("role") != "system")
                    .lower()
                    .split()
                )
                prompt_keys[split].add(key)

    overlap = ids_by_split["train"] & ids_by_split["eval"]
    if overlap:
        sample = sorted(overlap)[:5]
        errors.append(f"train/eval id overlap ({len(overlap)}): {sample}")

    dial_overlap = prompt_keys["train"] & prompt_keys["eval"]
    if dial_overlap:
        errors.append(f"train/eval dialogue overlap ({len(dial_overlap)})")

    all_ids = ids_by_split["train"] | ids_by_split["eval"]
    if len(all_ids) != len(ids_by_split["train"]) + len(ids_by_split["eval"]):
        errors.append("global id uniqueness check failed")

    manifest_path = OUT / "manifest.json"
    if not manifest_path.is_file():
        errors.append("missing manifest.json")
    else:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        mcounts = manifest.get("counts", {})
        for split in SPLITS:
            for domain in DOMAINS:
                expected = mcounts.get(split, {}).get(domain)
                actual = counts[split].get(domain)
                if expected != actual:
                    errors.append(
                        f"manifest counts mismatch {split}/{domain}: "
                        f"manifest={expected} actual={actual}"
                    )

    print(json.dumps({"counts": counts, "errors": len(errors)}, indent=2))
    if errors:
        for err in errors[:50]:
            print(err, file=sys.stderr)
        if len(errors) > 50:
            print(f"... and {len(errors) - 50} more", file=sys.stderr)
        return 1
    print("OK", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
