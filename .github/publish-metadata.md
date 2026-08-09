# GitHub publish metadata (SafetyMP)

Apply these settings when creating or updating
`https://github.com/SafetyMP/corporate-site-harness`.

## Repository

| Field | Value |
|-------|-------|
| Name | `corporate-site-harness` |
| Visibility | Public |
| Default branch | `main` |
| License | Apache-2.0 (already in tree) |
| Homepage | `https://github.com/SafetyMP/corporate-site-harness#why-this-exists` |

### Description

```text
Evergreen OSS reference for evidence-gated Cursor corporate/site agent workflows — digest-bound gates, role separation, factory control plane. Not a production enterprise governance product.
```

### Topics

```text
agent-governance
agents
apache2
cursor
evidence
multi-agent
open-source
python
reference-architecture
verification
```

## Security & automation (Settings)

Enable after first push:

- [x] Dependabot alerts / security updates (config: `.github/dependabot.yml`)
- [ ] Secret scanning
- [ ] Push protection for secrets
- [ ] Private vulnerability reporting
- [ ] Branch protection on `main` (require `CI` status checks)

## Workflows included

| Workflow | Purpose |
|----------|---------|
| `.github/workflows/ci.yml` | pytest + ruff + package metadata |
| `.github/workflows/codeql.yml` | CodeQL (Python) |
| `.github/workflows/scorecard.yml` | OpenSSF Scorecard |
