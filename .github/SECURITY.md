# Security policy

## Supported versions

| Version | Supported |
|---------|-----------|
| `0.1.x` (default branch) | Yes |
| Older / unreleased forks | Best effort |

This project is pre-1.0. Security fixes land on the default branch first.

## Reporting a Vulnerability

**Do not** open a public issue for exploitable bugs.

Prefer GitHub **Private vulnerability reporting** /
[Security advisories](https://docs.github.com/en/code-security/security-advisories)
on this repository when enabled.

Include:

- Affected component (`corp-harness` CLI, plugin hooks, site scripts, Swift assist, etc.)
- Reproduction steps and impact assessment
- Whether the issue can invent gate `PASS`, bypass digest binding, escalate
  `--actor user` without a human, or expose secrets

You should receive an acknowledgement within 7 days. We aim to publish a fix or
mitigation timeline within 30 days for confirmed high-impact issues.

## Non-goals for reporters

The harness deliberately rejects agent-granted user approval and stale evidence.
Reports that only show agents *asking* for `--actor user` (and being denied) are
working as designed.

## Safe harbor

Good-faith research that follows this policy and avoids privacy violations,
destructive data loss, or service disruption is welcome. Do not access other
users' private repositories or production systems without authorization.
