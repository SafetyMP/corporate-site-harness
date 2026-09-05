---
name: site-delivery
description: Delivers an approved corporate handoff through ADR-scoped implementation and independent site verification.
---

# Site delivery

1. Verify the handoff digest.
2. Have the readonly site manager return bounded ADR packets.
3. The root orchestrator launches site specialists in isolated roots.
   Default `execution_target` is `worktree` (`.worktrees/<packet-id>`). Opt-in
   `isolated_copy`, `openshell:<name>`, or `cloud_subagent` is placement only
   (depth-1 worker). Reserved OpenShell names `hermes`, `pi`, `eval` are illegal
   as `openshell:<name>` and as `site_path`. Connect with
   `openshell sandbox connect <name>` from a Mac terminal; never `--editor cursor`.
   Reviewers require `isolated_copy` and do not follow into OpenShell or
   `cloud_subagent`. Ceilings: `max_depth=1`, `max_children=6`,
   `no_redelegation=true`. A green isolated run is not a named-gate PASS. Agents
   never `--actor user`.
4. Integrate and run `scripts/harness/verify.sh`.
5. Record `verification_scripts` as site-relative `scripts/harness` (only
   `verify.sh` and `adversarial.sh`). Do not bind the whole `scripts/` tree.
6. Ask operations excellence to review fresh evidence.
7. Return failures to the owning ADR; never bypass retries or self-approve.
