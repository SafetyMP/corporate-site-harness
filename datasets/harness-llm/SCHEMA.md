# Harness LLM dataset schema

Each JSONL line is one training or eval record.

## Required fields

| Field | Type | Notes |
|---|---|---|
| `id` | string | Unique across all splits; pattern `{domain}-{split}-{nnnn}` |
| `domain` | string | `policy` \| `cli` \| `artifacts` \| `refusals` |
| `task_type` | string | `qa` \| `decision` \| `cli_compose` \| `json_emit` \| `refuse` \| `trajectory` |
| `difficulty` | string | `easy` \| `medium` \| `hard` |
| `messages` | array | Chat turns: starts with `system`, ends with `assistant`; after system, roles alternate `user`/`assistant` |
| `meta` | object | `source_refs` (string[]), optional `tags` (string[]) |

Single-turn rows are still `[system, user, assistant]`. Multi-turn **trajectories** add further user/assistant pairs (simulated tool/CLI context in user turns is allowed).

## Optional / eval fields

| Field | Type | Notes |
|---|---|---|
| `grading` | object | Required for every eval record; optional on train |

### `grading`

| Field | Type | Notes |
|---|---|---|
| `method` | string | `contains_all` \| `exact_assistant` \| `json_subset` \| `refuse` |
| `must_include` | string[] | Case-sensitive substrings that must appear in the **final** assistant turn |
| `must_not_include` | string[] | Substrings that must not appear (see refuse waiver) |
| `expected_json` | object \| null | For `json_subset` |

### Grading methods

- **`contains_all`**: final assistant text must include every `must_include` entry and none of `must_not_include`.
- **`exact_assistant`**: final assistant text equals the gold final assistant message (after strip).
- **`json_subset`**: parse a JSON object from the final assistant reply; every key in `expected_json` must match.
- **`refuse`**: final turn must refuse/correct; `must_not_include` is waived when the reply clearly refuses. Refusals eval still lists `--actor user` under `must_not_include`.

## System prompt

All records share the same short system prompt (see `SYSTEM_PROMPT` in `scripts/build_dataset.py` and README). It encodes digest authority, no `--actor user`, root isolation, and no invented PASS.
