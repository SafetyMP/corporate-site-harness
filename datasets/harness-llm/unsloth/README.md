# Unsloth export

Ready-to-load JSONL for Unsloth / TRL `SFTTrainer`.

| File | Rows | Columns |
|---|---:|---|
| `train.jsonl` | 3000 | `id`, `domain`, `messages`, `conversations` |
| `eval.jsonl` | 450 | same (held out — do not train) |
| `train_messages.jsonl` | 3000 | `messages` only |
| `eval_messages.jsonl` | 450 | `messages` only |

## Load + format

```python
from datasets import load_dataset
from unsloth.chat_templates import get_chat_template

dataset = load_dataset(
    "json",
    data_files={
        "train": "datasets/harness-llm/unsloth/train_messages.jsonl",
        "eval": "datasets/harness-llm/unsloth/eval_messages.jsonl",
    },
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
    return {"text": texts}

train_dataset = dataset["train"].map(formatting_prompts_func, batched=True)
eval_dataset = dataset["eval"].map(formatting_prompts_func, batched=True)
```

Then pass `train_dataset` to `SFTTrainer` (`dataset_text_field="text"` / TRL defaults).
Keep `eval` held out for `score_eval.py` after inference.

Rebuild export:

```bash
python3 datasets/harness-llm/scripts/export_unsloth.py
```
