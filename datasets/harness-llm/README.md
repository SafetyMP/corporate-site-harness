# Harness LLM SFT + Eval Dataset

Chat-style JSONL for fine-tuning and evaluating a **local LLM** on the
corporate/site harness: role/policy rules, `corp-harness` CLI usage, and
role-correct artifact / agent packets — plus hard refusals.

This is a **workspace dataset only**. It is not a harness gate and does not
grant program approval. A green fine-tuned model is **not** a harness `PASS`.

**Packaging revision:** `v0.3-lora-standard`  
**Recommended base:** `Qwen/Qwen2.5-7B-Instruct` (QLoRA)

| Surface | ID |
|---|---|
| GitHub (factory) | [`SafetyMP/corporate-site-harness`](https://github.com/SafetyMP/corporate-site-harness) |
| HF training data | [`SafetyMP/corporate-site-harness-training-data`](https://huggingface.co/datasets/SafetyMP/corporate-site-harness-training-data) |
| HF model | [`SafetyMP/corporate-site-harness-llm`](https://huggingface.co/SafetyMP/corporate-site-harness-llm) |

## v0.3 LoRA-standard checklist

- [x] SFT JSONL + Parquet (`default`)
- [x] Slim `messages_only` config
- [x] DPO preference config from refusals
- [x] Dataset card: intended use, Qwen2.5 QLoRA recipe, eval protocol
- [x] User-run recipe: [`recipes/train_qlora_qwen25_7b.py`](recipes/train_qlora_qwen25_7b.py)
- [x] CI: `.github/workflows/harness-llm-dataset.yml`
- [ ] Adapter weights published (out of scope for 1A)

## Layout

```text
train/          SFT gold examples (~3000)
eval/           Held-out graded examples (~450)
scripts/        validate, score, build, HF/DPO export
recipes/        Qwen2.5-7B QLoRA train entrypoint
huggingface/    Hub-ready package (card + data/)
SCHEMA.md       Record + grading contract
manifest.json   Counts and source file digests
```

## Shared system prompt

Every record uses:

> You are a corporate/site harness assistant. Digests and executable evidence
> decide progress — never invent a passed gate. Agents never pass `--actor user`
> or grant user approval. Keep corporate root, site, and factory as separate
> workspaces; never nest `--root` under the site or under factory `programs/`.
> Prefer `corp-harness status` / `check --run` over narrative claims.

## Domains

| Domain | Focus |
|---|---|
| `policy` | Phases, roles, workspaces, premium routing, factory vs product |
| `cli` | CLI argv, tool-grounded status/route JSON, multi-turn trajectories |
| `artifacts` | Gate reports, evidence, handoff digests, bad-report repair |
| `refusals` | Stratified hard negatives (actor-user, invent-PASS, nested roots, …) |

Robustness: multi-turn `trajectory` rows, diverse assistant paraphrases, simulated
CLI JSON, stratified eval buckets, disjoint train/eval dialogues.

## Validate

```bash
python3 datasets/harness-llm/scripts/validate_dataset.py
```

## Score model predictions

Predictions JSONL: one object per line with `id` and `assistant` (model output).

```bash
python3 datasets/harness-llm/scripts/score_eval.py \
  --predictions /path/to/preds.jsonl \
  --out /path/to/report.json
```

## Training recipe (no GPU in packaging)

See [`recipes/README.md`](recipes/README.md).

```bash
python3 datasets/harness-llm/recipes/train_qlora_qwen25_7b.py --dry-run
```

## Hugging Face upload package

Hub-ready folder (dataset card + splits):

| Path | Contents |
|---|---|
| [`huggingface/README.md`](huggingface/README.md) | Dataset card (YAML + LoRA recipe / eval) |
| [`huggingface/data/train.jsonl`](huggingface/data/train.jsonl) | ~3000 train rows (+ `.parquet`) |
| [`huggingface/data/validation.jsonl`](huggingface/data/validation.jsonl) | ~450 held-out rows (+ `grading_json`) |
| `data/messages_only_*.jsonl` | Slim messages-only config |
| `data/dpo_*.jsonl` | Preference pairs from refusals |

```bash
# Rebuild package (requires: pip install pyarrow)
python3 datasets/harness-llm/scripts/export_huggingface.py

# Upload (requires huggingface_hub + HF_TOKEN or `huggingface-cli login`)
python3 datasets/harness-llm/scripts/upload_huggingface.py \
  --repo-id SafetyMP/corporate-site-harness-training-data
```

## Unsloth training files

Prebuilt export (regenerate with `scripts/export_unsloth.py`):

| File | Use |
|---|---|
| [`unsloth/train_messages.jsonl`](unsloth/train_messages.jsonl) | **SFT train** — `{messages:[system,user,assistant]}` |
| [`unsloth/eval_messages.jsonl`](unsloth/eval_messages.jsonl) | Held-out eval (do not train) |
| [`unsloth/train.jsonl`](unsloth/train.jsonl) | Same + `id`/`domain`/`conversations` (ShareGPT-style) |
| [`unsloth/eval.jsonl`](unsloth/eval.jsonl) | Held-out with metadata |

See [`unsloth/README.md`](unsloth/README.md) for the load/`apply_chat_template` snippet.

## Fine-tune (other trainers)

Domain-split sources remain under `train/` and `eval/`. Keep `eval/` held out.
Do not train on eval IDs.

## Rebuild

```bash
python3 datasets/harness-llm/scripts/build_dataset.py
python3 datasets/harness-llm/scripts/validate_dataset.py
python3 datasets/harness-llm/scripts/export_huggingface.py
```

## License

Same as the repository (Apache-2.0). Seeded from in-repo docs, CLI, and plugin
role text; see `manifest.json` for source paths and digests.
