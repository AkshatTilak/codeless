# Contributing to Codeless

Codeless is an open-source autonomous agent execution harness engineered for the Agent Buildable Base (ABB) governance paradigm.

## Ways to contribute

- Fix bugs or tighten edge-case handling in the harness runtime.
- Improve docs, onboarding, examples, and architecture notes.
- Add tests for tools, permissions, plugins, MCP, or multi-agent flows.
- Contribute new skills, plugins, or provider compatibility improvements.
- Share real usage patterns that can be added to [`docs/SHOWCASE.md`](docs/SHOWCASE.md).

## Development setup

```bash
git clone https://github.com/AkshatTilak/codeless.git
cd codeless
uv sync --extra dev
cd frontend/terminal && npm install && cd ../..
```

## Local checks

Run the same core checks that CI runs before opening a PR:

```bash
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run pytest -q
```

Frontend sanity check:

```bash
cd frontend/terminal
npx tsc --noEmit
```

## Pull request expectations

- Keep PRs scoped. Small, reviewable changes merge faster than broad rewrites.
- Include the problem, the change, and how you verified it.
- Add or update tests when behavior changes.
- Update docs when CLI flags, workflows, or compatibility claims change.
- Add a short entry under `Unreleased` in [`CHANGELOG.md`](CHANGELOG.md) for user-visible changes.
- If you are improving type coverage, feel free to run `uv run mypy src`, but it is not yet a required green check for the whole repo.

## Documentation and community contributions

Issue [#7](https://github.com/HKUDS/OpenHarness/issues/7) surfaced several high-value docs needs. Useful contributions in that area include:

- README accuracy improvements and compatibility notes.
- Short, reproducible examples for common workflows.
- Showcase entries based on real usage rather than generic marketing claims.
- Contribution and maintenance docs that make the repo easier to navigate.

## Reporting bugs and proposing features

- Use the GitHub issue templates when possible.
- Include environment details, exact commands, and error output for bugs.
- For features, explain the concrete workflow gap and expected behavior.
- If the request is mostly documentation or maintenance related, say that explicitly so it can be scoped as a docs PR.
