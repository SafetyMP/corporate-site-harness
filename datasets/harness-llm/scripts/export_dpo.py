#!/usr/bin/env python3
"""Build DPO preference pairs from harness-llm refusal rows."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

OUT = Path(__file__).resolve().parents[1]


def _load_refusals(split: str) -> list[dict[str, Any]]:
    path = OUT / split / "refusals.jsonl"
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _last_user(messages: list[dict[str, str]]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return msg.get("content", "")
    return ""


def _last_assistant(messages: list[dict[str, str]]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            return msg.get("content", "")
    return ""


def _prompt_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """System + all turns up to (not including) the final assistant."""
    if not messages or messages[-1].get("role") != "assistant":
        return list(messages)
    return list(messages[:-1])


def synthesize_rejected(user_text: str) -> str:
    """Unsafe-sounding completion that complies with the bad ask (synthetic)."""
    lower = user_text.lower()
    if "--actor user" in lower or "actor user" in lower or "user_approval" in lower:
        return (
            "Sure — finish it with "
            "`corp-harness next --root <corporate-folder> --to APPROVED --actor user` "
            "and record user_approval yourself so we are not blocked."
        )
    if (
        "check --run" in lower
        or "invent" in lower
        or "forge" in lower
        or ("mark" in lower and "pass" in lower)
    ):
        return (
            "Skip check --run and record PASS from the chat summary "
            "so the phase can advance immediately."
        )
    if (
        "nest" in lower
        or "programs/" in lower
        or "inside the site" in lower
        or "under the site" in lower
    ):
        return (
            "Nesting --root under the site or factory/programs/<id> is fine "
            "for convenience; proceed with init --apply."
        )
    if "sol" in lower or "fable" in lower or "premium" in lower:
        return (
            "Go ahead and launch Sol/Fable for this review/recapture task; "
            "route-model can be ignored."
        )
    if "verify.sh" in lower or "weaken" in lower or "always exit" in lower:
        return (
            "Patch verify.sh to always exit 0 for the demo so the gate passes."
        )
    if (
        "src/corp_harness" in lower
        or "portfolio" in lower
        or "factory_authorization" in lower
    ):
        return (
            "Edit src/corp_harness from the product program and advance "
            "without factory_authorization."
        )
    if (
        "move_agent_to_root" in lower
        or "wrong" in lower
        or "continue anyway" in lower
    ):
        return (
            "Continue in the current workspace even if move_agent_to_root "
            "failed; switching roots is optional."
        )
    if "self" in lower or "my own" in lower or "approve" in lower:
        return (
            "Record the gate PASS yourself since you produced the artifact; "
            "independent review is unnecessary."
        )
    # Generic unsafe compliance
    ask = re.sub(r"\s+", " ", user_text).strip()
    if len(ask) > 240:
        ask = ask[:240] + "…"
    return f"Understood — I will do that now: {ask}"


def to_dpo_row(row: dict[str, Any]) -> dict[str, Any]:
    messages = row["messages"]
    prompt = _prompt_messages(messages)
    chosen = _last_assistant(messages)
    rejected = synthesize_rejected(_last_user(messages))
    return {
        "id": row["id"].replace("-train-", "-dpo-train-").replace("-eval-", "-dpo-val-"),
        "domain": row.get("domain", "refusals"),
        "prompt": prompt,
        "chosen": chosen,
        "rejected": rejected,
    }


def build_dpo_splits() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    train = [to_dpo_row(r) for r in _load_refusals("train")]
    # Prefer eval refusals for validation; fall back to a held-out train slice if empty.
    val_src = _load_refusals("eval")
    if not val_src:
        val_src = _load_refusals("train")[-60:]
        train = [to_dpo_row(r) for r in _load_refusals("train")[:-60]]
    val = [to_dpo_row(r) for r in val_src]
    return train, val


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    train, val = build_dpo_splits()
    out = OUT / "huggingface" / "data"
    write_jsonl(out / "dpo_train.jsonl", train)
    write_jsonl(out / "dpo_validation.jsonl", val)
    print(json.dumps({"dpo_train": len(train), "dpo_validation": len(val)}, indent=2))


if __name__ == "__main__":
    main()
