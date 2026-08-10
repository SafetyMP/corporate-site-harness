#!/usr/bin/env python3
"""Build a Hugging Face Hub-ready dataset folder for harness-llm SFT / DPO data."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_dpo import (  # noqa: E402,I001
    build_dpo_splits,
    write_jsonl as write_dpo_jsonl,
)

OUT = Path(__file__).resolve().parents[1]
HF = OUT / "huggingface"
DOMAINS = ("policy", "cli", "artifacts", "refusals")
SCHEMA = "v0.3-lora-standard"
# Hub naming (factory GitHub repo stays SafetyMP/corporate-site-harness):
DATASET_REPO = "SafetyMP/corporate-site-harness-training-data"
MODEL_REPO = "SafetyMP/corporate-site-harness-llm"
GITHUB_REPO = "https://github.com/SafetyMP/corporate-site-harness"


def load_split(split: str) -> list[dict]:
    rows: list[dict] = []
    for domain in DOMAINS:
        path = OUT / split / f"{domain}.jsonl"
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    rows.sort(key=lambda r: r["id"])
    return rows


def to_hf_row(row: dict, *, include_grading: bool) -> dict:
    messages = row["messages"]
    conversations = [
        {
            "from": {"system": "system", "user": "human", "assistant": "gpt"}[m["role"]],
            "value": m["content"],
        }
        for m in messages
    ]
    out = {
        "id": row["id"],
        "domain": row["domain"],
        "task_type": row["task_type"],
        "difficulty": row["difficulty"],
        "messages": messages,
        "conversations": conversations,
        "source_refs": row.get("meta", {}).get("source_refs", []),
        "tags": row.get("meta", {}).get("tags", []),
    }
    # Hub Dataset Viewer fails on train/validation feature mismatch and on
    # nested grading.expected_json (object|null). Keep grading as a JSON
    # string on validation only for a flat, viewer-safe schema.
    if include_grading and isinstance(row.get("grading"), dict):
        out["grading_json"] = json.dumps(
            row["grading"], ensure_ascii=False, separators=(",", ":")
        )
    else:
        out["grading_json"] = ""
    return out


def to_messages_only(row: dict) -> dict:
    return {"messages": row["messages"]}


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _flatten_for_parquet(rows: list[dict]) -> list[dict]:
    """Serialize nested columns to JSON strings for portable Parquet."""
    flat: list[dict] = []
    for row in rows:
        item: dict[str, Any] = {}
        for key, value in row.items():
            if isinstance(value, (list, dict)):
                item[key] = json.dumps(value, ensure_ascii=False)
            else:
                item[key] = value
        flat.append(item)
    return flat


def write_parquet(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flat = _flatten_for_parquet(rows)
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - exercised in CI with pyarrow
        raise SystemExit(
            "pyarrow is required for Parquet export. Install with: pip install pyarrow"
        ) from exc
    table = pa.Table.from_pylist(flat)
    pq.write_table(table, path)


def git_commit() -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=OUT.parents[1],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return out or None
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None


def dataset_card(
    train_n: int,
    val_n: int,
    dpo_train_n: int,
    dpo_val_n: int,
    commit: str | None,
) -> str:
    commit_line = (
        f"- **Factory git commit:** `{commit}`"
        if commit
        else "- **Factory git commit:** (local / unavailable)"
    )
    return f"""---
language:
  - en
license: apache-2.0
pretty_name: Corporate Site Harness Training Data
size_categories:
  - 1K<n<10K
task_categories:
  - text-generation
  - question-answering
annotations_creators:
  - expert-generated
language_creators:
  - expert-generated
multilinguality:
  - monolingual
source_datasets:
  - original
tags:
  - agents
  - agent-governance
  - corp-harness
  - corporate-site-harness
  - chat
  - sft
  - instruction-tuning
  - unsloth
  - trl
  - refusals
  - synthetic
  - qwen
  - qwen2.5
  - lora
  - qlora
  - dpo
configs:
  - config_name: default
    data_files:
      - split: train
        path: data/train.jsonl
      - split: validation
        path: data/validation.jsonl
    default: true
  - config_name: messages_only
    data_files:
      - split: train
        path: data/messages_only_train.jsonl
      - split: validation
        path: data/messages_only_validation.jsonl
  - config_name: dpo
    data_files:
      - split: train
        path: data/dpo_train.jsonl
      - split: validation
        path: data/dpo_validation.jsonl
---

# Dataset Card for Corporate Site Harness Training Data

**Revision:** `{SCHEMA}`

{commit_line}

## Table of Contents

- [Dataset Description](#dataset-description)
- [Intended Use](#intended-use)
- [Dataset Structure](#dataset-structure)
- [Training Recipe (Qwen2.5-7B QLoRA)](#training-recipe-qwen25-7b-qlora)
- [Evaluation Protocol](#evaluation-protocol)
- [Dataset Creation](#dataset-creation)
- [Considerations for Using the Data](#considerations-for-using-the-data)
- [Additional Information](#additional-information)
- [Reproduction](#reproduction)

## Dataset Description

- **Homepage:** https://github.com/SafetyMP/corporate-site-harness
- **Repository:** https://github.com/SafetyMP/corporate-site-harness
- **Dataset:** https://huggingface.co/datasets/SafetyMP/corporate-site-harness-training-data
- **Companion model:** https://huggingface.co/SafetyMP/corporate-site-harness-llm
- **Point of Contact:** [SafetyMP](https://huggingface.co/SafetyMP)
- **License:** Apache License 2.0
- **Recommended base model:** [`Qwen/Qwen2.5-7B-Instruct`](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct)

### Dataset Summary

English chat-style supervised fine-tuning (SFT), preference (DPO), and held-out
evaluation data for teaching a local LLM the **corporate/site harness** used by
[corporate-site-harness](https://github.com/SafetyMP/corporate-site-harness):

- **policy** — phases, roles, workspace isolation, premium-model routing, factory vs product
- **cli** — `corp-harness` argv, tool-grounded status/route JSON, multi-turn trajectories
- **artifacts** — gate reports, evidence, handoff digests, bad-report repair
- **refusals** — stratified hard negatives (actor-user, invent-PASS, nested roots, …)

Rows are chat `messages` (single-turn or multi-turn `trajectory`) suitable for
Unsloth, TRL `SFTTrainer`, and other ChatML / messages loaders.

This dataset is a **training/eval resource only**. It is **not** a harness gate
and does **not** grant program approval. A green fine-tuned model does **not**
mean a harness `PASS`.

## Intended Use

### In scope

- Specialize a chat model (recommended: Qwen2.5-7B-Instruct via QLoRA) toward
  harness-safe explanations, CLI composition, artifact shapes, and refusals.
- Offline evaluation with `score_eval.py` on the validation split.
- Optional DPO on the `dpo` config (refusal-derived preference pairs).

### Out of scope

- Replacing `corp-harness` executable gates, digests, or user approval.
- Claiming production “governance” compliance solely from model generations.
- Training on the `validation` split.
- Using rejected DPO completions as positive SFT targets.

## Dataset Structure

### Configurations

| Config | Files | Purpose |
|---|---|---|
| `default` | `data/train.jsonl`, `data/validation.jsonl` (+ Parquet twins) | Full SFT rows |
| `messages_only` | `data/messages_only_*.jsonl` (+ Parquet) | Slim `messages` only |
| `dpo` | `data/dpo_train.jsonl`, `data/dpo_validation.jsonl` (+ Parquet) | Preference pairs |

Parquet twins use the same logical columns with nested fields JSON-serialized
for Hub viewer portability (`messages`, `conversations`, `prompt`, etc.).

### Data Instances

```python
from datasets import load_dataset

ds = load_dataset("SafetyMP/corporate-site-harness-training-data")
example = ds["train"][0]
print(example["id"], example["domain"])
print(example["messages"])

dpo = load_dataset("SafetyMP/corporate-site-harness-training-data", "dpo")
print(dpo["train"][0]["chosen"][:120])
```

### Data Fields (default)

| Field | Type | Description |
|---|---|---|
| `id` | string | Stable unique id |
| `domain` | string | `policy`, `cli`, `artifacts`, or `refusals` |
| `task_type` | string | `qa`, `decision`, `cli_compose`, `json_emit`, or `refuse` |
| `difficulty` | string | `easy`, `medium`, or `hard` |
| `messages` | list of `{{role, content}}` | OpenAI-style chat turns |
| `conversations` | list of `{{from, value}}` | ShareGPT-style turns |
| `source_refs` | list[string] | Doc / policy references |
| `tags` | list[string] | Topic tags |
| `grading_json` | string | Eval rubric JSON (validation); empty on train |

### Data Fields (dpo)

| Field | Type | Description |
|---|---|---|
| `id` | string | Preference pair id |
| `domain` | string | Usually `refusals` |
| `prompt` | list of messages | Context up to the final assistant turn |
| `chosen` | string | Gold refusal / safe completion |
| `rejected` | string | Synthetic unsafe compliance (no real secrets) |

### Data Splits

| Split | default rows | dpo rows |
|---|---:|---:|
| train | {train_n} | {dpo_train_n} |
| validation | {val_n} | {dpo_val_n} |

Train and validation dialogues are disjoint (enforced by
`validate_dataset.py`).

## Training Recipe (Qwen2.5-7B QLoRA)

**Endorsed recipe (user-run; not executed by maintainers in the packaging pass):**
[`datasets/harness-llm/recipes/train_qlora_qwen25_7b.py`](https://github.com/SafetyMP/corporate-site-harness/blob/main/datasets/harness-llm/recipes/train_qlora_qwen25_7b.py)

| Knob | Value |
|---|---|
| Base | `Qwen/Qwen2.5-7B-Instruct` |
| Method | QLoRA (Unsloth or TRL `SFTTrainer`) |
| Rank / alpha | `r=16`, `lora_alpha=16` |
| Learning rate | ≈ `2e-4` |
| Epochs | 1–2 |
| Max sequence length | 4096 |
| Loss masking | `train_on_responses_only` (assistant turns) |
| Data | Hub `default` or local `datasets/harness-llm/huggingface/` |

Do **not** train on `validation`. Optional preference tuning: load config `dpo`
after SFT.

## Evaluation Protocol

1. Keep `validation` held out (never in the SFT trainer train split).
2. Generate assistant replies for validation prompts; write a JSONL of
   `{{"id", "messages"}}` (or reuse gold structure with model `assistant` text).
3. From the factory checkout, run:

```bash
python3 datasets/harness-llm/scripts/score_eval.py \\
  --predictions path/to/model_generations.jsonl
```

4. Report overall and **by-domain** scores (`policy`, `cli`, `artifacts`, `refusals`).
5. Interpret results as **model specialization metrics only**. A high score is
   **not** a harness gate `PASS` and does not grant user approval.

Gold self-score on the packaged eval set must be 100% via the same scorer
(CI / local verification).

## Dataset Creation

### Curation Rationale

Agents frequently invent harness shortcuts (`--actor user`, forged PASS,
nested roots). This corpus teaches correct CLI/policy language and hard
refusals without replacing executable gates.

### Source Data

Synthetic, expert-authored templates expanded in
`datasets/harness-llm/scripts/` against corporate-site-harness docs and CLI
contracts. Paths are workspace-neutral (`/work/...`); no personal data.

### Annotations

Authoritative assistant targets and eval `grading` rubrics are curated with the
dataset scripts. DPO `rejected` strings are synthetic unsafe paraphrases, not
logged user traffic.

### Personal and Sensitive Information

No PII, credentials, or live secrets. Placeholder digests only.

## Considerations for Using the Data

### Social Impact of Dataset

Intended to reduce unsafe harness shortcut suggestions in specialized assistants.
Misuse: treating generations as governance authority.

### Discussion of Biases

Harness-specific, English-only, refusal-heavy relative to open-ended coding.

### Other Known Limitations

- Mid-small scale (`1K<n<10K`).
- Heuristic grading, not a full semantic judge.
- Green model ≠ harness PASS.

## Additional Information

### Dataset Curators

[SafetyMP](https://huggingface.co/SafetyMP) — corporate-site-harness maintainers.

### Licensing Information

Apache License 2.0.

### Citation Information

```bibtex
@misc{{safetymp_corporate_site_harness_llm,
  title        = {{Corporate Site Harness Training Data}},
  author       = {{SafetyMP}},
  year         = {{2026}},
  howpublished = {{\\url{{https://huggingface.co/datasets/SafetyMP/corporate-site-harness-training-data}}}},
  note         = {{Revision {SCHEMA}; derived from https://github.com/SafetyMP/corporate-site-harness}}
}}
```

### Contributions

Scripts: `datasets/harness-llm/`. Issues:
[GitHub](https://github.com/SafetyMP/corporate-site-harness).

## Reproduction

```bash
python3 datasets/harness-llm/scripts/build_dataset.py
python3 datasets/harness-llm/scripts/validate_dataset.py
python3 datasets/harness-llm/scripts/export_huggingface.py
# optional upload (requires HF token):
python3 datasets/harness-llm/scripts/upload_huggingface.py \\
  --repo-id SafetyMP/corporate-site-harness-training-data
```

### How to Use (SFT)

```python
from datasets import load_dataset

ds = load_dataset("SafetyMP/corporate-site-harness-training-data")
# or messages_only:
# ds = load_dataset("SafetyMP/corporate-site-harness-training-data", "messages_only")

def formatting_prompts_func(examples):
    texts = [
        tokenizer.apply_chat_template(
            convo, tokenize=False, add_generation_prompt=False
        )
        for convo in examples["messages"]
    ]
    return {{"text": texts}}

train_dataset = ds["train"].map(formatting_prompts_func, batched=True)
```

Pass `train_dataset` to your `SFTTrainer`. Keep `validation` for evaluation only.
"""


def main() -> None:
    if HF.exists():
        shutil.rmtree(HF)
    data_dir = HF / "data"

    train_src = load_split("train")
    val_src = load_split("eval")
    train_rows = [to_hf_row(r, include_grading=False) for r in train_src]
    val_rows = [to_hf_row(r, include_grading=True) for r in val_src]
    train_msg = [to_messages_only(r) for r in train_src]
    val_msg = [to_messages_only(r) for r in val_src]
    dpo_train, dpo_val = build_dpo_splits()

    write_jsonl(data_dir / "train.jsonl", train_rows)
    write_jsonl(data_dir / "validation.jsonl", val_rows)
    write_jsonl(data_dir / "messages_only_train.jsonl", train_msg)
    write_jsonl(data_dir / "messages_only_validation.jsonl", val_msg)
    write_dpo_jsonl(data_dir / "dpo_train.jsonl", dpo_train)
    write_dpo_jsonl(data_dir / "dpo_validation.jsonl", dpo_val)

    write_parquet(data_dir / "train.parquet", train_rows)
    write_parquet(data_dir / "validation.parquet", val_rows)
    write_parquet(data_dir / "messages_only_train.parquet", train_msg)
    write_parquet(data_dir / "messages_only_validation.parquet", val_msg)
    write_parquet(data_dir / "dpo_train.parquet", dpo_train)
    write_parquet(data_dir / "dpo_validation.parquet", dpo_val)

    commit = git_commit()
    (HF / "README.md").write_text(
        dataset_card(
            len(train_rows),
            len(val_rows),
            len(dpo_train),
            len(dpo_val),
            commit,
        ),
        encoding="utf-8",
    )

    data_files = [
        "data/train.jsonl",
        "data/validation.jsonl",
        "data/train.parquet",
        "data/validation.parquet",
        "data/messages_only_train.jsonl",
        "data/messages_only_validation.jsonl",
        "data/messages_only_train.parquet",
        "data/messages_only_validation.parquet",
        "data/dpo_train.jsonl",
        "data/dpo_validation.jsonl",
        "data/dpo_train.parquet",
        "data/dpo_validation.parquet",
    ]
    meta = {
        "schema": SCHEMA,
        "train_rows": len(train_rows),
        "validation_rows": len(val_rows),
        "dpo_train_rows": len(dpo_train),
        "dpo_validation_rows": len(dpo_val),
        "data_files": data_files,
        "suggested_repo_name": DATASET_REPO,
        "companion_model_repo": MODEL_REPO,
        "factory_github": GITHUB_REPO,
        "naming": {
            "github_factory": "SafetyMP/corporate-site-harness",
            "hf_dataset": DATASET_REPO,
            "hf_model": MODEL_REPO,
        },
        "recommended_base_model": "Qwen/Qwen2.5-7B-Instruct",
        "factory_git_commit": commit,
        "privacy": "synthetic paths only; no personal identifying information",
    }
    (HF / "export_meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )

    # Keep package manifest in sync when present.
    manifest_path = OUT / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["schema"] = SCHEMA
        manifest["huggingface_export"] = {
            "schema": SCHEMA,
            "train_rows": len(train_rows),
            "validation_rows": len(val_rows),
            "dpo_train_rows": len(dpo_train),
            "dpo_validation_rows": len(dpo_val),
            "recommended_base_model": "Qwen/Qwen2.5-7B-Instruct",
            "suggested_repo_name": DATASET_REPO,
            "companion_model_repo": MODEL_REPO,
            "factory_github": GITHUB_REPO,
        }
        if commit:
            manifest["factory_git_commit"] = commit
        manifest_path.write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )

    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
