# Releasing

The PyPI name is `zalobot-sdk` (the import name stays `zalobot`). PyPI refuses `zalobot` as too similar to an
existing project: it compares names after dropping `-`, `_` and `.` and mapping `l`/`i` to `1` and `o` to `0`.

Releases run from GitHub Actions (`.github/workflows/release.yml`) with PyPI Trusted Publishing: no PyPI password
or token is stored anywhere. A `v*` tag builds once, publishes to TestPyPI, and then publishes to PyPI after you
approve it.

## One-time setup

### 1. GitHub repository

The code lives at https://github.com/nttams/zalobot. Commit and push to `main` there. GitHub credits commits to
you only if their email (`ngothtam.me@gmail.com`) is a verified email on your GitHub account.

### 2. GitHub environments (the approval step)

On the GitHub repository: **Settings** > **Environments** > **New environment**.

- Name `testpypi`, then **Configure environment**. No rules are needed.
- Name `pypi`, then **Configure environment** > **Required reviewers** (add yourself) > **Save protection rules**.

### 3. PyPI and TestPyPI pending publishers

On https://pypi.org/manage/account/publishing/ (log in first), use the **GitHub** form:

| Field | Value |
|---|---|
| PyPI Project Name | `zalobot-sdk` |
| Owner | `nttams` |
| Repository name | `zalobot` |
| Workflow name | `release.yml` |
| Environment name | `pypi` |

Click **Add**. Do the same on https://test.pypi.org/manage/account/publishing/ (a separate account) with
**Environment name** `testpypi`.

A pending publisher does **not** reserve the name: until the first upload, someone else could still take
`zalobot-sdk`. So publish soon after adding it.

### 4. Docs site (optional)

1. On the GitHub repository: **Settings** > **Pages** > under **Build and deployment**, **Source**: **GitHub Actions**.
2. **Settings** > **Secrets and variables** > **Actions** > **Variables** tab > **New repository variable**:
   **Name** `PAGES_ENABLED`, **Value** `true`, then **Add variable**.

From then on, `docs.yml` publishes the MkDocs site on every push to `main`. Without the variable, the workflow
skips instead of failing.

## Each release

1. Update `CHANGELOG.md` (move "Unreleased" under the new version) and bump the version with
   `uv version --bump minor` (or `patch`). Also update `__version__` in `src/zalobot/__init__.py`. A test checks
   that the two match.
2. Run `uv run pytest --cov`, the live tests (see CONTRIBUTING.md), and `sh scripts/check_history.sh --publish`.
3. Commit with the message `release: 0.2.0`, tag it `v0.2.0`, and push both to GitHub
   (`git push origin main --tags`).
4. On GitHub, the **release** workflow builds the package and publishes it to
   TestPyPI. Check https://test.pypi.org/project/zalobot-sdk/, then approve the `pypi` job in the run's page on GitHub.
