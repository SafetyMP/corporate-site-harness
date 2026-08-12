# Architecture Decision Records

ADRs record enforceable harness decisions. Prefer them over chat history when
behavior is ambiguous. For the end-to-end flow, start with
[../HOW_IT_WORKS.md](../HOW_IT_WORKS.md).

## Prefix legend

| Prefix | Theme |
|--------|-------|
| **CAFR** | Corporate-acceptance evidence, cwd isolation, Stage-1→2 currentness |
| **PP** | Portfolio CLI / factory platform ownership and sensors |
| **VS** | Verification scripts binding (`scripts/harness`) |
| **SGA** | Swift governance assist (read-only; never mutates `program.json`) |
| **TR** | Trust-routed runtime, event log, anti-harness signals |
| **SGO** | Site-gate oracles (`corporate-site-handoff/v2`) |

## Index

### Corporate acceptance

- [ADR-CAFR-001](ADR-CAFR-001-stage1-capture-registration.md) — Stage-1 capture registration
- [ADR-CAFR-002](ADR-CAFR-002-corporate-root-cwd-isolation.md) — Corporate-root cwd isolation
- [ADR-CAFR-003](ADR-CAFR-003-stage1-grandfather-migration-window.md) — Stage-1 grandfather window
- [ADR-CAFR-004](ADR-CAFR-004-def-ca-03-restore.md) — FAIL → redesign rework
- [ADR-CAFR-005](ADR-CAFR-005-stage2-dual-evidence-currentness.md) — Stage-2 dual evidence
- [ADR-CAFR-006](ADR-CAFR-006-stage2-migration-redesign.md) — User-only migration redesign

### Portfolio and verification scripts

- [ADR-PP-001](ADR-PP-001-portfolio-cli-factory-ownership.md) — Portfolio CLI is factory-owned
- [ADR-PP-002](ADR-PP-002-portfolio-readonly-sensors.md) — Readonly sensors; no invented PASS
- [ADR-PP-003](ADR-PP-003-verification-scripts-harness.md) — Verification scripts harness binding
- [ADR-PP-004](ADR-PP-004-premium-model-spend-controls.md) — Premium model spend controls
- [ADR-VS-001](ADR-VS-001-verification-scripts-harness.md) — Site-relative `scripts/harness` (pairs with PP-003)

### Gov assist

- [ADR-SGA-001](ADR-SGA-001-assist-splash-architecture.md) — Read-only assist splash
- [ADR-SGA-002](ADR-SGA-002-p1-explain-handoff.md) — Explain handoff / staleness
- [ADR-SGA-003](ADR-SGA-003-p2-authorized-surfaces.md) — Authorized-surfaces check

### Trust runtime

- [ADR-TR-001](ADR-TR-001-trust-routed-runtime.md) — Trust-routed runtime
- [ADR-TR-002](ADR-TR-002-trust-event-log.md) — Trust event log
- [ADR-TR-003](ADR-TR-003-anti-harness-trust-events.md) — Anti-harness events
- [ADR-TR-004](ADR-TR-004-trust-runtime-residuals.md) — Residuals closure

### Site-gate oracles

- [ADR-SGO-001](ADR-SGO-001-site-gate-oracles-handoff-v2.md) — Handoff v2 + `site_gate_oracles`
- [ADR-SGO-002](ADR-SGO-002-template-oracles-non-regression.md) — Template fail-closed oracles
