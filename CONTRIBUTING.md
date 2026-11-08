# Contributing

Thanks for helping. Bug reports, fixes and docs improvements are all welcome.

## Set up

The project uses [uv](https://docs.astral.sh/uv/):

```bash
uv sync --all-groups
```

## Before you open a pull request

```bash
uv run ruff check src tests examples
uv run ruff format src tests examples
uv run mypy src
uv run pytest --cov
```

- Every bug fix comes with a test that fails without the fix.
- Coverage stays at 90% or more (the suite fails below that).
- Behaviour follows the official docs at https://bot.zaloplatforms.com/docs/. If the docs and the real API disagree,
  say so in the pull request with what you observed.
- The public API is typed. `mypy --strict` must pass.
- Add a line under "Unreleased" in `CHANGELOG.md`.

## Live tests

`tests/test_live.py` calls the real API. Use a bot made only for testing, because the tests set and delete a
webhook. Send that bot a text message and a sticker from your Zalo account, then run:

```bash
ZALOBOT_TEST_TOKEN=... uv run pytest -m live -v
```

## Docs

```bash
uv run --group docs mkdocs serve
```
