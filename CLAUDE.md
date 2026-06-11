# CLAUDE.md

Context for Claude Code in this repo. Keep this short — it loads on every session.

## What this is

`claude-woocommerce-commons` is a **library**, not a routine. It holds the
plumbing shared by WooCommerce reporting routines: the paginated, retrying
`WooClient`; tolerant parsing (`parse_num`,
`meta_get`); shop-currency detection; ISO-week reporting windows
(`iso_week_windows`); the Dropbox upload; and Excel style helpers. It has **no
report logic and no shop-specific knowledge**.

There is no scheduled-task/operator section here — this package does not run on
its own. It is consumed by the routine repos, which own their own runtime
contracts.

## Read first

Read `SCOPE.md` before changing anything. Every feature has an ID (`F-001`…) and
must stay covered by a test (`tests/test_scope_coverage.py` enforces it).

## Working rules

- Any behaviour change starts in `SCOPE.md`: add/edit a feature ID, then write
  or update its test, then change the code. Never the other way around.
- Every test is tagged `@pytest.mark.feature("F-00X")`.
- Run `pytest` after any change. Network (WC REST API, Dropbox) is always mocked;
  the suite never hits a real shop or Dropbox.
- After a behaviour change, add a line under `[Unreleased]` in `CHANGELOG.md`.
- Before committing, review: adversarially re-read the full uncommitted diff for
  real defects — edge cases, wrong assumptions, criteria the tests miss (in
  Claude Code, `/code-review`). Style is not a finding (ruff owns style); a
  session habit, not a CI gate.
- **This is a dependency of the consuming reporting routines.** A breaking
  change to a public name (`WooClient`, `parse_num`, `iso_week_windows`, …) must
  bump the version and be rolled out to each consumer by bumping its pinned
  version. Prefer additive changes.

## Commands

- Install (editable, with tests): `pip install -e ".[test]"`
- Run tests: `pytest`
- The package exposes a single top-level module: `from wc_client import WooClient, parse_num, iso_week_windows, upload_to_dropbox, ...`

## Consumed by

WooCommerce reporting routines depend on this package and pin it to a tag. Roll a
fix out by tagging a release here and bumping the pin in each consumer.

## Conventions

- Standard library + `requests` + `openpyxl` only. No shop-specific meta keys.
- Number parsing goes through `parse_num()`; env access through
  `env_required` / `env_opt`.
- Everything is read-only against the WC API (the Dropbox upload writes only to
  Dropbox).
