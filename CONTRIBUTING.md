# Contributing

Thanks for helping improve the Corporate/Site Harness.

## Development setup

```bash
pip install -e ".[dev]"
python3 -m pytest -q
python3 -m ruff check src tests
```

Optional full factory gate:

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

## Pull requests

1. Keep changes focused; match existing style.
2. Add or update tests for runtime/CLI behavior.
3. Run pytest + ruff before opening a PR.
4. Update [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) or an ADR when phases,
   roles, or gate contracts change.

## License

By contributing, you agree that your contributions are licensed under the
Apache License 2.0.
