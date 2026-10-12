# Documentation map

Start at the root [README](../README.md). The lifecycle is [HOW_IT_WORKS.md](./HOW_IT_WORKS.md).

Community files live at the repository root: [CONTRIBUTING.md](../CONTRIBUTING.md), [CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md), and [SECURITY.md](../SECURITY.md).

## Repository layout

| Path | What it is |
| --- | --- |
| `src/` | `corp-harness` Python package |
| `corporate/` | Cursor plugin |
| `scripts/` | Factory verify scripts |
| `tests/` | Pytest |
| `docs/` | This map, the lifecycle, and ADRs |
| `site-template/`, `templates/` | Site scaffolding |
| `datasets/` | Harness-LLM training dumps used by the dataset workflow |
| `evals/` | Eval fixtures |
| `swift/` | Swift package beside the Python CLI |

Corporate root stays a sibling checkout. This repository does not hold a product site's `program.json`.


## Canonical community files

`CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, and `SECURITY.md` are at the repository root. This repository does not keep a second copy under `.github/`, because GitHub would show that copy instead of the root file.
