#!/usr/bin/env python3
"""Endorsed QLoRA SFT recipe for SafetyMP/corporate-site-harness-training-data.

Base model: Qwen/Qwen2.5-7B-Instruct

This script is the documented training entrypoint. Maintainers do **not** run GPU
training in the packaging pass — users run it on their own hardware.

Requires (typical Unsloth env):
  pip install "unsloth" "trl" "datasets" "transformers" "accelerate" "peft"

Optional eval after training (factory checkout):
  python3 datasets/harness-llm/scripts/score_eval.py --predictions gens.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from trl import SFTConfig, SFTTrainer
    from unsloth import FastLanguageModel
    from unsloth.chat_templates import train_on_responses_only
except ImportError:  # optional until a real GPU training run
    SFTConfig = None  # type: ignore[misc, assignment]
    SFTTrainer = None  # type: ignore[misc, assignment]
    FastLanguageModel = None  # type: ignore[misc, assignment]
    train_on_responses_only = None  # type: ignore[misc, assignment]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--dataset",
        default="SafetyMP/corporate-site-harness-training-data",
        help="Hub dataset id or local path to huggingface/ export folder",
    )
    p.add_argument(
        "--config",
        default="default",
        choices=("default", "messages_only"),
        help="Dataset config name",
    )
    p.add_argument(
        "--model",
        default="Qwen/Qwen2.5-7B-Instruct",
        help="Base instruct model",
    )
    p.add_argument("--output-dir", default="outputs/qwen25-7b-harness-qlora")
    p.add_argument("--max-seq-length", type=int, default=4096)
    p.add_argument("--lora-r", type=int, default=16)
    p.add_argument("--lora-alpha", type=int, default=16)
    p.add_argument("--learning-rate", type=float, default=2e-4)
    p.add_argument("--epochs", type=float, default=1.0)
    p.add_argument("--batch-size", type=int, default=2)
    p.add_argument("--grad-accum", type=int, default=8)
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print resolved knobs and exit (no GPU / no install required)",
    )
    return p.parse_args()


def load_sft_split(dataset: str, config: str):
    from datasets import load_dataset

    path = Path(dataset)
    if path.is_dir():
        # Local export folder
        data_files = {
            "train": str(path / "data" / "train.jsonl"),
            "validation": str(path / "data" / "validation.jsonl"),
        }
        if config == "messages_only":
            data_files = {
                "train": str(path / "data" / "messages_only_train.jsonl"),
                "validation": str(path / "data" / "messages_only_validation.jsonl"),
            }
        return load_dataset("json", data_files=data_files)
    return load_dataset(dataset, config)


def main() -> None:
    args = parse_args()
    knobs = {
        "dataset": args.dataset,
        "config": args.config,
        "model": args.model,
        "max_seq_length": args.max_seq_length,
        "lora_r": args.lora_r,
        "lora_alpha": args.lora_alpha,
        "learning_rate": args.learning_rate,
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "grad_accum": args.grad_accum,
        "output_dir": args.output_dir,
        "train_on_responses_only": True,
        "note": "User-run recipe; packaging CI does not execute GPU training",
    }
    print(json.dumps(knobs, indent=2))
    if args.dry_run:
        return

    if (
        FastLanguageModel is None
        or SFTTrainer is None
        or SFTConfig is None
        or train_on_responses_only is None
    ):
        raise SystemExit(
            "Training requires unsloth + trl. Install them, or pass --dry-run."
        )

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.model,
        max_seq_length=args.max_seq_length,
        load_in_4bit=True,
    )
    model = FastLanguageModel.get_peft_model(
        model,
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=0.0,
        target_modules=[
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ],
        use_gradient_checkpointing="unsloth",
    )

    ds = load_sft_split(args.dataset, args.config)
    # Never train on validation.
    train_ds = ds["train"]

    def formatting_prompts_func(examples):
        texts = [
            tokenizer.apply_chat_template(
                convo, tokenize=False, add_generation_prompt=False
            )
            for convo in examples["messages"]
        ]
        return {"text": texts}

    train_ds = train_ds.map(formatting_prompts_func, batched=True)

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=train_ds,
        args=SFTConfig(
            output_dir=args.output_dir,
            per_device_train_batch_size=args.batch_size,
            gradient_accumulation_steps=args.grad_accum,
            learning_rate=args.learning_rate,
            num_train_epochs=args.epochs,
            logging_steps=10,
            save_strategy="epoch",
            max_seq_length=args.max_seq_length,
            dataset_text_field="text",
        ),
    )
    trainer = train_on_responses_only(trainer)
    trainer.train()
    model.save_pretrained(args.output_dir)
    tokenizer.save_pretrained(args.output_dir)
    print(f"Saved adapter to {args.output_dir}")
    print(
        "Eval tip: generate on validation prompts, then "
        "python3 datasets/harness-llm/scripts/score_eval.py --predictions gens.jsonl"
    )


if __name__ == "__main__":
    main()
