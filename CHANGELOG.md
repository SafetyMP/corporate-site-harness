# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Public Apache-2.0 packaging (`LICENSE`, `NOTICE`, SPDX metadata)
- Community health: Code of Conduct, Contributing (DCO), Security, Support,
  Governance, Changelog, issue/PR templates, Dependabot, EditorConfig
- CI workflow (pytest + ruff + package metadata check on Python 3.11–3.13)
- CodeQL and OpenSSF Scorecard workflows (SafetyMP portfolio parity)
- SafetyMP evergreen README disclaimer, badges, and `project.urls`
- [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) lifecycle and stakeholder guide
- Runnable `site-template/` scaffold with harness verify/adversarial scripts
- `templates/factory-authorization.TEMPLATE.json` for factory programs

### Changed

- Local `programs/`, `evidence/`, `archives/`, and `.corp-harness-program-root`
  are gitignored (runtime state, not source)
- CI pins `ruff==0.16.6` and `build==1.6.0`; ADRs and the chain-incident
  fixture no longer cite personal home paths
- CI and harness-LLM export installs use `--require-hashes` with
  PyPI-resolved hash pins (`requirements-ci.txt`,
  `datasets/harness-llm/requirements-export.txt`). The CI lockfile is
  compiled for Python 3.11 so marker extras (`backports.tarfile`, Linux
  `SecretStorage`) stay pinned on 3.12/3.13.

## [0.1.0] - 2026-08-09

### Added

- Initial public release of `corp-harness` and the Cursor plugin
  `corporate-site-harness`
- Evidence-gated phase machine, digest-bound gates, and role policy
- Factory vs product program kinds with user-only approvals
