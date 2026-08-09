# Security policy

## Supported versions

This project is pre-1.0. Security fixes land on the default branch.

## Reporting a vulnerability

Please open a **private** GitHub security advisory on this repository when
available, or contact the maintainer listed in `pyproject.toml` if advisories
are not enabled yet.

Include:

- Affected component (`corp-harness` CLI, plugin hooks, site scripts, etc.)
- Reproduction steps and impact
- Whether the issue can invent gate PASS, bypass digest binding, or escalate
  `--actor user` without a human

Do **not** file public issues for exploitable gate-bypass or secret-exposure bugs
until a fix is available.

## Non-goals for reporters

The harness deliberately rejects agent-granted user approval and stale evidence.
Reports that only show agents *asking* for `--actor user` (and being denied) are
working as designed.
