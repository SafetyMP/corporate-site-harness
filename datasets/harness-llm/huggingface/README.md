---
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

**Revision:** `v0.3-lora-standard`

- **Factory git commit:** `e4f4f2f1a992c16dc2bf9068e8324174d55560c2`

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
| `messages` | list of `{role, content}` | OpenAI-style chat turns |
| `conversations` | list of `{from, value}` | ShareGPT-style turns |
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
| train | 3000 | 400 |
| validation | 450 | 60 |

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
   `{"id", "messages"}` (or reuse gold structure with model `assistant` text).
3. From the factory checkout, run:

```bash
python3 datasets/harness-llm/scripts/score_eval.py \
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
@misc{safetymp_corporate_site_harness_llm,
  title        = {Corporate Site Harness Training Data},
  author       = {SafetyMP},
  year         = {2026},
  howpublished = {\url{https://huggingface.co/datasets/SafetyMP/corporate-site-harness-training-data}},
  note         = {Revision v0.3-lora-standard; derived from https://github.com/SafetyMP/corporate-site-harness}
}
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
python3 datasets/harness-llm/scripts/upload_huggingface.py \
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
    return {"text": texts}

train_dataset = ds["train"].map(formatting_prompts_func, batched=True)
```

Pass `train_dataset` to your `SFTTrainer`. Keep `validation` for evaluation only.
