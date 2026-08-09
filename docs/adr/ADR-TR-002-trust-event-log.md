# ADR-TR-002: Append-only hash-chained trust event log

## Status

Partially implemented (trust-routed-runtime, SITE_DELIVERY revision 3)

- `WP-TR-LOG-A`: Python sole append writer, D3 rebind-preserve, anchor mint,
  dedup fingerprint idempotency.
- `WP-TR-LOG-B`: `corp-harness trust log` reader/`--verify-chain`; broken chain
  fails closed on mutating `--apply` / `emit_and_apply` (`GOV_REQUIRED`).
- `WP-TR-LOG-C`: falsifiable G-TR-LOG-* pytest nodes + `verify.sh` collection
  binding. `test_TR_LOG_003_non_events_do_not_append` covers LOG-scoped
  non-events (`trust log`, clean `status`, dry-run, `route-model`, `check`,
  gov assist). Dirty deferred anti-harness half of ACC-TR-LOG-003 /
  G-TR-LOG-NON-EVENTS (`test_TR_AH_007_*`) remains under `WP-TR-AH-A` /
  `WP-TR-AH-C` — do not claim that gate fully green until AH-007 exists.

## Context

ADR-TR-001 shipped dual-layer trust routing with `trust-state.json` as the
routing head (`last_event`). That head alone cannot audit history, detect
tamper, or block false-genesis after wipe. Revision 3 requires an append-only
hash-chained JSONL trust event log and a non-genesis anchor so score restore
via state/log/anchor deletion is impossible.

Related handoff packets: `WP-TR-LOG-A`, `WP-TR-LOG-B`, `WP-TR-LOG-C`.

## Decision

1. **Log file:** `<corporate_root>/trust-event-log.jsonl` with schema
   `corporate-site-trust-log-entry/v1` per line. Python `runtime_engine` is the
   sole append writer (via `emit_and_apply` and digest-rebind writer paths).
   No automatic rotation.

2. **Hash chain:** each entry carries `prev_hash` and `entry_hash`. Genesis
   `prev_hash` is the literal string `genesis`. `entry_kind` ∈
   {`trust_event`, `digest_rebind`}. Applied TrustEvents append
   `entry_kind=trust_event` with matching `event_id`. D3 digest rebind appends
   `entry_kind=digest_rebind` (audit only; not a TrustEvent wire kind; **not** a
   score reset). `entry_hash` is `sha256` of the canonical JSON body with
   `sort_keys=True` and separators `(",", ":")`, excluding `entry_hash` itself.

3. **D3 rebind (supersedes ADR-TR-001 amnesty restore):** on
   `program_digest` mismatch, rebind digest and preserve `trust_score`,
   `execution_layer`, and `last_event`. Append `digest_rebind` on the writer
   path (emit_and_apply / mutating apply), never on clean status alone. Score
   reset to `1.0`/light/`last_event=null` via digest mismatch is forbidden.

4. **Anchor:** mint `<corporate_root>/trust-log-anchor.json`
   (`corporate-site-trust-log-anchor/v1`) on first log append with
   `program_id`, `initialized_at`, `first_entry_hash`. Sole writer
   `python_runtime_engine`. Anchor proves non-genesis even if log/state wiped
   (false-genesis / dual-wipe handled under ADR-TR-003).

5. **True genesis only** when all three are absent: `trust-state.json`,
   non-empty `trust-event-log.jsonl`, and `trust-log-anchor.json`.

6. **Idempotency:** duplicate `event_id` with matching dedup fingerprint
   (`theater_signal_id` + protected path + content hash + coarse time bucket)
   appends nothing and does not re-apply score delta. Fingerprint mismatch
   requires a new `event_id`.

7. **Read CLI:** `corp-harness trust log --root PATH [--limit N] [--verify-chain]`
   is read-only / non-event when the chain is ok. Broken/unverifiable chain:
   `--verify-chain` fails; mutating `--apply` and dirty apply-entry MUST fail
   closed (`GOV_REQUIRED` or equivalent). Tip fields `log_tip_hash` / `log_seq`
   on trust-state are advisory; JSONL is authoritative.

8. **Non-events (must not append):** dry-run without `--apply`, `route-model`,
   `check` without `--apply`, gov assist without write-receipt, `trust log`
   (read-only), and **clean** `status`. Evidence: `test_TR_LOG_003_non_events_do_not_append`
   (LOG-C). Dirty deferred anti-harness scan is consequential per ADR-TR-003 /
   TR-09 carve-out (not a LOG non-event); evidence deferred to
   `test_TR_AH_007_dirty_deferred_scan_consequential_clean_status_non_event`.

9. **Forbidden:** `corp-harness trust set-score`; score mutation outside D9
   emit+apply; false genesis via truncate/delete of log and/or state and/or
   anchor.

## Consequences

- Work packets: `WP-TR-LOG-A` (writer + rebind + anchor mint), `WP-TR-LOG-B`
  (CLI reader/verify + broken-chain blocks apply), `WP-TR-LOG-C` (falsifiable
  tests + gate bindings for G-TR-LOG-*).
- Existing ADR-TR-001 digest-amnesty load reset must be replaced before LOG
  acceptance can pass.
- `./scripts/harness/verify.sh` and `adversarial.sh` remain the verification
  binding; LOG tests must be collected under pytest.
