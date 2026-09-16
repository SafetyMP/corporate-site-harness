---
name: code-review
description: "Review factory CLI PRs for digest-bound gates, no --actor user, and no self-approval. Use on pull requests that touch src/corp_harness, scripts/harness, or plugin skills. Flag invented PASS, nested corporate roots, and program.json written into a site."
---

# Copilot code review — corporate-site-harness

Use this skill when reviewing a pull request in this repository.

This repository **is** the factory.

- Reject `--actor user` in agent-facing commands or docs that tell agents to pass it.
- Reject typed/hand-waved gate success. Evidence is `corp-harness check --run`.
- Reject product-site edits to `src/corp_harness/**`.
- Verify with `./scripts/harness/verify.sh`.


## Always flag

- Secrets, `.env` values, private keys, or real personal data in the diff
- Weakened or skipped verify / lint / typecheck / adversarial gates
- Invented success (prose claiming a gate passed with no command output)
- Fail-open authorization, skipped human approval, or agents recording `--actor user`

## Never request

- Drive-by major upgrades, formatter churn, or unrelated refactors
- Softening honesty disclaimers or certification claims
