---
name: gate-evidence
description: Records executable evidence and independent gate verdicts against the current program revision.
---

# Gate evidence

Run evidence through `corp-harness check --run`; do not hand-type success. Record a gate
only when its report and target artifacts are current. If the target digest changes,
rerun the command and review. A failing gate returns to site delivery; exhausted attempts
escalate to the user.
