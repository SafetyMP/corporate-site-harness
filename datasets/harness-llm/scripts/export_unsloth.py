#!/usr/bin/env python3
"""Export harness-llm JSONL into Unsloth-ready train/eval files.

Unsloth SFT typically wants a `messages` column (chat roles) that you map with
`tokenizer.apply_chat_template` into a `text` column. This exporter also writes
a ShareGPT-style `conversations` column for `standardize_sharegpt`.
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1]
DOMAINS = ("policy", "cli", "artifacts", "refusals")


def load_split(split: str) -> list[dict]:
    rows: list[dict] = []
    for domain in DOMAINS:
        path = OUT / split / f"{domain}.jsonl"
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    rows.sort(key=lambda r: r["id"])
    return rows


def to_unsloth(row: dict) -> dict:
    messages = row["messages"]
    conversations = [
        {
            "from": {"system": "system", "user": "human", "assistant": "gpt"}[m["role"]],
            "value": m["content"],
        }
        for m in messages
    ]
    return {
        "id": row["id"],
        "domain": row["domain"],
        "messages": messages,
        "conversations": conversations,
    }


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def main() -> None:
    dest = OUT / "unsloth"
    train = [to_unsloth(r) for r in load_split("train")]
    eval_rows = [to_unsloth(r) for r in load_split("eval")]
    write_jsonl(dest / "train.jsonl", train)
    write_jsonl(dest / "eval.jsonl", eval_rows)
    # messages-only slim files (common Unsloth loaders)
    write_jsonl(
        dest / "train_messages.jsonl",
        [{"messages": r["messages"]} for r in train],
    )
    write_jsonl(
        dest / "eval_messages.jsonl",
        [{"messages": r["messages"]} for r in eval_rows],
    )
    meta = {
        "schema": "harness-llm-unsloth-export/v1",
        "train_rows": len(train),
        "eval_rows": len(eval_rows),
        "files": [
            "train.jsonl",
            "eval.jsonl",
            "train_messages.jsonl",
            "eval_messages.jsonl",
        ],
        "load": {
            "huggingface_datasets": (
                'load_dataset("json", data_files={'
                '"train": "datasets/harness-llm/unsloth/train_messages.jsonl", '
                '"eval": "datasets/harness-llm/unsloth/eval_messages.jsonl"})'
            )
        },
    }
    (dest / "README.md").write_text(
        f"""# Unsloth export

Ready-to-load JSONL for Unsloth / TRL `SFTTrainer`.

| File | Rows | Columns |
|---|---:|---|
| `train.jsonl` | {len(train)} | `id`, `domain`, `messages`, `conversations` |
| `eval.jsonl` | {len(eval_rows)} | same (held out — do not train) |
| `train_messages.jsonl` | {len(train)} | `messages` only |
| `eval_messages.jsonl` | {len(eval_rows)} | `messages` only |

## Load + format

```python
from datasets import load_dataset
from unsloth.chat_templates import get_chat_template

dataset = load_dataset(
    "json",
    data_files={{
        "train": "datasets/harness-llm/unsloth/train_messages.jsonl",
        "eval": "datasets/harness-llm/unsloth/eval_messages.jsonl",
    }},
)

# After FastLanguageModel.from_pretrained(...):
tokenizer = get_chat_template(tokenizer, chat_template="chatml")  # or model-specific

def formatting_prompts_func(examples):
    texts = [
        tokenizer.apply_chat_template(
            convo, tokenize=False, add_generation_prompt=False
        )
        for convo in examples["messages"]
    ]
    return {{"text": texts}}

train_dataset = dataset["train"].map(formatting_prompts_func, batched=True)
eval_dataset = dataset["eval"].map(formatting_prompts_func, batched=True)
```

Then pass `train_dataset` to `SFTTrainer` (`dataset_text_field="text"` / TRL defaults).
Keep `eval` held out for `score_eval.py` after inference.

Rebuild export:

```bash
python3 datasets/harness-llm/scripts/export_unsloth.py
```
""",
        encoding="utf-8",
    )
    (dest / "export_meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"train": len(train), "eval": len(eval_rows), "out": str(dest)}))


if __name__ == "__main__":
    main()
