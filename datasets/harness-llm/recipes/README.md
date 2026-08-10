# Harness LLM training recipes

Endorsed, user-run recipes for specializing a chat model on
`SafetyMP/corporate-site-harness-training-data`. Companion model:
`SafetyMP/corporate-site-harness-llm`. Packaging CI does **not** run GPU training.

## Recommended base

**Qwen2.5-7B-Instruct** — `Qwen/Qwen2.5-7B-Instruct`

| Knob | Value |
|---|---|
| Method | QLoRA (Unsloth or TRL) |
| LoRA r / alpha | 16 / 16 |
| LR | ≈ 2e-4 |
| Epochs | 1–2 |
| Max seq len | 4096 |
| Loss | train on assistant responses only |

## Quick start

```bash
# Inspect knobs without GPU
python3 datasets/harness-llm/recipes/train_qlora_qwen25_7b.py --dry-run

# Train (requires Unsloth/TRL GPU env)
python3 datasets/harness-llm/recipes/train_qlora_qwen25_7b.py \
  --dataset SafetyMP/corporate-site-harness-training-data \
  --output-dir outputs/qwen25-7b-harness-qlora
```

Local package instead of Hub:

```bash
python3 datasets/harness-llm/recipes/train_qlora_qwen25_7b.py \
  --dataset datasets/harness-llm/huggingface
```

## Evaluation

Do **not** train on `validation`. After generation:

```bash
python3 datasets/harness-llm/scripts/score_eval.py \
  --predictions path/to/gens.jsonl
```

Report by-domain scores. A green score is **not** a harness gate `PASS`.

## DPO (optional)

Preference pairs ship under Hub config `dpo` (`prompt` / `chosen` / `rejected`).
Run DPO only after SFT, and never use `rejected` as SFT targets.
