# Contributing

Thanks for helping improve the Corporate/Site Harness.

Please read the [Code of Conduct](CODE_OF_CONDUCT.md) before participating.

## Development setup

```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python3 -m pytest -q
python3 -m ruff check src tests
```

Optional full factory gate (binds an active program root when present):

```bash
./scripts/harness/verify.sh
```

## Scope rules

- **Factory code** lives in `src/corp_harness/**`, `corporate/plugin/**`, and
  related tests/docs. Product programs must not land factory edits.
- Prefer enforceable behavior in code and tests over long agent prose.
- Do not weaken gates, invent PASS evidence, or add paths that grant user
  approval to agents.
- Keep corporate roots and sites as separate workspaces in docs and examples.
- Local runtime dirs (`programs/`, `evidence/`, `archives/`,
  `.corp-harness-program-root`) must stay gitignored.

## Issues

- Bugs and features: use the GitHub issue templates.
- Security: follow [SECURITY.md](SECURITY.md) (private advisory).
- Questions / how-to: see [SUPPORT.md](SUPPORT.md).

## Pull requests

1. Keep changes focused; match existing style (see `.editorconfig`).
2. Add or update tests for runtime/CLI behavior.
3. Run pytest + ruff before opening a PR.
4. Update [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) or an ADR when phases,
   roles, or gate contracts change.
5. Fill out the pull request template checklist.

### Developer Certificate of Origin (DCO)

This project requires a DCO sign-off on every commit:

```bash
git commit -s -m "Your message"
```

That appends:

```text
Signed-off-by: Your Name <your.email@example.com>
```

By signing off, you certify the contribution under the
[Developer Certificate of Origin](https://developercertificate.org/) (v1.1).

## License

By contributing, you agree that your contributions are licensed under the
Apache License 2.0 (see [LICENSE](LICENSE) and [NOTICE](NOTICE)).
