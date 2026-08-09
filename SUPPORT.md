# Support

## How to get help

1. Read [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) for lifecycle and roles.
2. Check [docs/adr/](docs/adr/README.md) for enforceable design decisions.
3. Search existing GitHub Issues before opening a new one.

## Bug reports and features

Use the issue templates under **New issue**. Include:

- `corp-harness` version (`python -c "import corp_harness; print(corp_harness.__version__)"`)
- Python version and OS
- Minimal reproduction (commands + relevant `program.json` fields, redacted)
- Whether the problem invents gate PASS, digests, or `--actor user`
  (security-sensitive — see [SECURITY.md](SECURITY.md))

## What this project does not provide

- Guaranteed SLA or paid support
- Agent “self-approval” of gates or user approval
- Debugging of private product sites that are not reproducible with a minimal fixture

## Security issues

Do not file public issues for vulnerabilities. Follow [SECURITY.md](SECURITY.md).
