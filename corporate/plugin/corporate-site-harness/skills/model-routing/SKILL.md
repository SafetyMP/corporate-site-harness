---
name: model-routing
description: Routes Task/subagent launches through corp-harness route-model so premium models (Sol, Claude Fable) are used only for allowlisted hard implementation with escalation—not for review, recapture, or first-pass remediation.
---

# Model routing

## Before every Task or subagent launch

1. Classify the work into exactly one `task_class`:
   - `design_review`, `explore`, `evidence_recapture`, `dispatch_attest`,
     `independent_review`, `packet_implement`, `hard_implement`, `remediate`
2. Run:

```sh
corp-harness route-model --root <corporate-folder> \
  --role <role> --task-class <task_class> \
  [--packet <packet.json>] [--escalation <escalation.json>] \
  [--failed-standard-attempts N] [--max-mode]
```

3. Pass the returned `allowed_model_ids[0]` as the Task `model=` argument.
   Defaults prioritize Grok (`fast`) and Composer (`standard`). Do not launch
   premium/Max unless `model_class` is `premium` and `requires_escalation` is
   satisfied by a valid escalation artifact.
4. Refuse Sol/Fable for `evidence_recapture`, `dispatch_attest`,
   `independent_review`, `design_review`, and first-pass `remediate`.

## Escalation artifact

Schema `corporate-site-premium-escalation/v1` with `authorized: true`,
`task_class`, nonempty `reason`, and stable `id`. Required for
`hard_implement`, Max Mode premium, complexity-elevated `packet_implement`,
and `remediate` after two failed standard attempts.

## Abort / resume

On user abort, API limit, or PING timeout:

1. Write a resume checkpoint JSON under the site
   `evidence/resume/<work_packet_id>.json` with ADR, digests, workspace root,
   commands/results so far, and remaining risks.
2. Resume on `standard` or `fast` with a short handoff. Do not cold-start a new
   Max Mode premium agent.

## Attestation

Site packets must record `model_id`, `model_class`, `task_class`, `max_mode`,
and optional `escalation_ref`. Validate with:

```sh
corp-harness check --root <corporate-folder> --attest-packet <packet.json>
```

`PREMIUM_MODEL_POLICY` is a hard failure for ops/site gates.
