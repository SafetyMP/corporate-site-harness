# ADR-PP-004: Premium model spend controls

## Status

Accepted for factory platform (`portfolio-platform` authorized surfaces).

## Context

OpenCode delivery burned majority Sol spend on recapture, remediation, and abort
restarts. Cursor cannot hard-lock the model picker, so the harness must attest
and gate premium use.

## Decision

1. Add `corporate-site-execution-policy/v1` with task classes, model aliases
   (Sol/Fable → premium; Grok/Composer first for fast/standard), budgets,
   packet limits, and evidence max age.
2. Expose `corp-harness route-model`, `usage record|show` (user actor), and
   `check --attest-packet` / `--evidence-captured-at`.
3. Deny with `PREMIUM_MODEL_POLICY` when premium models attest outside allowlist
   + escalation.
4. Plugin roles/skills/hooks/rules route Task launches and keep reminders lean.

## Consequences

- Operators record invoice Sol/Fable totals via `usage record --actor user`.
- Site packets must carry `model_id` / `model_class` / `task_class`.
- Portfolio status surfaces readonly budget envelopes only.
