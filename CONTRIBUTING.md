# Contributing — branching & releases (trunk-on-main)

`ClaudeWooCommerceCommons` is a shared library for the Claude routine family. It uses **trunk-based
development**: `main` is always releasable, and every release is an annotated `vX.Y.Z`
tag on `main` — no `develop` / `release` / `hotfix` branches. The plain `git` commands
below are the whole workflow.

The family deliberately picks its branching model by **deploy model**: pip-installed
libraries and scheduled routines use trunk-on-main (this guide); gated multi-environment
apps use Git Flow. The *release gate* — version = changelog = tag — is the same either
way; only the branching differs.

## Branch model

| Branch | Purpose |
| --- | --- |
| `main` | The line. Always releasable, always green. Every release is a tag here. Default branch. |
| `feature/*` (optional) | A short-lived branch for one unit of work, merged back with `git merge --no-ff`. For small changes, committing straight to `main` is fine. |

Tags are always `vX.Y.Z` (a `v` prefix on the version).

## Daily work

Follow the **SCOPE → test → code → changelog** loop in `CLAUDE.md` (if present), or at
minimum: add/adjust the test, change the code, keep `pytest` green, and add a line under
`[Unreleased]` in `CHANGELOG.md`. Every public symbol downstream routines import is part
of this library's contract — change it deliberately and note breaking changes.

## Quality gates (run before every commit)

```bash
ruff check .
ruff format --check .
pytest          # tests + line coverage >= 80% (use pytest --no-cov for subsets)
```

CI runs exactly these on every push and PR. `ruff format` owns formatting; the linter is
a small, stable rule set (`E`, `F`, `I`).

## Cutting a release (the release gate lives here)

The version in `pyproject.toml`, the topmost `CHANGELOG.md` heading, and the annotated
tag must be the same `X.Y.Z`:

```bash
# on a clean, green main:
# 1) bump "version" in pyproject.toml
# 2) move CHANGELOG.md [Unreleased] entries under a new "## [X.Y.Z] - YYYY-MM-DD" heading
# 3) ruff check . && ruff format --check . && pytest
git commit -am "Added vX.Y.Z — <summary>"
git tag -a vX.Y.Z -m "vX.Y.Z"
git push origin main --tags
```

Downstream routines pin this library by tag (`...@vX.Y.Z`), so a release is only "done"
once the tag is pushed. Pushing the tag triggers `release.yml`, which creates the GitHub
Release from the changelog. Release this package before the routines that need the new
version, and don't break the public API without a major-version bump.
