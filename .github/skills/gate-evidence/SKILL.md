---
name: gate-evidence
description: "Record digest-bound gate evidence with corp-harness check --run. Use when a Cursor agent claims a factory gate passed; never type success by hand; never self-approve."
---

# Gate evidence

Run evidence through `corp-harness check --run`; do not hand-type success. Record a gate
only when its report and target artifacts are current. If the target digest changes,
rerun the command and review. A failing gate returns to site delivery; exhausted attempts
escalate to the user.
