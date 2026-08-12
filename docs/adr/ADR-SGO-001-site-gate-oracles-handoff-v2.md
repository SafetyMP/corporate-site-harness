# ADR-SGO-001: Site-gate oracles on corporate-site-handoff/v2

## Status

Accepted (`site-gate-oracle` factory program)

## Context

FidusGate SAST/pen-test showed the factory process could go green on named
probes and a TypeScript Cedar mock while missing official-engine fail-closed
behavior, evaluator split, unwired helpers, and unmodeled listen/fallback
surfaces. `verification_scripts` only enforced `scripts/harness` membership.

## Decision

1. Newly recorded `corporate_handoff` artifacts MUST use
   `corporate-site-handoff/v2` with required `site_gate_oracles`. Recording
   `corporate-site-handoff/v1` fails. A v1 handoff is non-current for
   `site_verify`, `operations`, `corporate_review`, and `adversary`.
2. `verification_scripts` exact-set binding is unchanged. Oracle evidence
   lives outside `scripts/harness`.
3. `policy_engine` is `none` | `cedar` | `equivalent`. Cedar requires official
   `cedar-policy` / `cedar-python` schema-validate + `is_authorized`.
4. Pointers (`enforcement_path_parity`, `call_site_wiring`, `surface_inventory`,
   `adversarial_corpus`) are site-relative. `sha256` may be null only with
   `pin_status=pending_site_delivery`. Those gates require live pins.
5. Deny-case extension is append-only findings; YAML-only frozen replay is
   insufficient.

## Consequences

Product and factory handoffs cannot skip official-engine, parity, wiring,
inventory, or adversarial-extension evidence. Existing trust/AH/TRR
collections remain required.
