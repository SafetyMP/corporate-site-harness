# Governance

This project is in early public alpha and uses a **benevolent maintainer** model.

## Roles

| Role | Authority |
|------|-----------|
| **Maintainer** | Merge PRs, cut releases, interpret ADRs, enforce the Code of Conduct |
| **Contributor** | Propose changes via pull requests; no commit access required |
| **User** (runtime) | Sole authority for `factory_authorization` and `user_approval` inside the harness — unrelated to git maintainership |

## Decisions

- Day-to-day code review: maintainer judgment against tests and ADRs.
- Contract changes (phases, gates, roles, digest rules): require tests plus an
  ADR or an update to [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md).
- Security-sensitive changes: follow [SECURITY.md](SECURITY.md); prefer fail-closed behavior.

## Releases

- Versioning follows SemVer (`pyproject.toml` / plugin version).
- Notable changes are recorded in [CHANGELOG.md](CHANGELOG.md).

## Changes to governance

Amendments land via pull request like any other documentation change.
