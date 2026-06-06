# Changelog

All notable changes to this package are documented here. Each behaviour change
references the SCOPE.md feature ID(s) it implements.

The format follows [Keep a Changelog](https://keepachangelog.com/), and the
project adheres to semantic versioning.

## [Unreleased]

## [1.0.0] - 2026-06-06

First stable release — the public surface is considered stable; this is the v1.0
milestone for the Claude routine family.

### Added
- Self-contained trunk-on-main `CONTRIBUTING.md`, `LICENSE` (MIT) + `license`
  field, `.github/workflows/release.yml` (tag -> GitHub Release) and
  `.github/dependabot.yml` (weekly pip + actions PRs).
- Code-coverage gate: `pytest-cov`, **fail_under = 80** in `[tool.coverage]`.
- Ruff lint + format gate (`[tool.ruff]`), run in CI before the tests.

### Changed
- CI: `ruff check` + `ruff format --check` before `pytest`; `actions/checkout` -> v5.
- Code reformatted by `ruff format` (no behaviour change); `.gitignore` ignores
  coverage artefacts.
- Pinned code_commons to v1.0.0 (was v0.3.0).

## [0.6.0] - 2026-06-05

### Added
- **[F-012] / [F-013] / [F-014]** Generic, parameterised goal/KPI arithmetic in
  `wc_client` — `yoy_pct`, `house_brand_share`, `revenue_goal` — so the sales and
  marketing routines compute year-over-year %, house-brand revenue share and
  revenue-vs-target from one shared definition. The helpers hold no shop-specific
  brand names or meta keys (the house-brand label and targets are passed in by the
  caller). Additive; existing imports are unaffected.

## [0.5.0] - 2026-06-01

### Changed
- Bumped the `claude-code-commons` pin to `v0.3.0`, which makes the env helpers
  **prefix-required by default** for routine-own keys: with a prefix set, the
  unprefixed fallback now applies only when `shared=True`. Consuming routines mark
  their family-shared creds (`WC_*`, `DROPBOX_*`) `shared=True`. The `shared` flag
  passes through the re-exported helpers transparently.

### Added
- **[F-011]** `env_int` and `env_float` are now re-exported from `wc_client`
  alongside the other core helpers, so routines can drop their local `_int`/`_float`
  helpers and use the shared, tested implementation.

## [0.4.0] - 2026-05-31

Split out the vendor-agnostic core (review thread T-1 / option C) and harden the
client. The generic helpers now live in `claude-code-commons` and are re-exported
here, so consumers' `from wc_client import ...` is unchanged.

### Changed
- **Depends on `claude-code-commons` (@v0.1.0).** `env_required` / `env_opt` /
  `env_get`, `parse_num`, `currency_symbol` / `CURRENCY_SYMBOLS`,
  `build_remote_path` and `log` moved to that dependency-light, standard-library-
  only core and are re-exported from `wc_client` (F-011) — no name changes, no
  behaviour changes. This lets non-WooCommerce routines (e.g. the asset repos)
  share the same helpers without installing `requests`/`openpyxl`.
- **F-005** `WooClient.paged` now sets `WooClient.truncated = True` when it stops
  at `max_pages`, so a caller can detect a truncated (under-counted) result
  instead of only seeing a log warning (review finding CM-1).
- CI now runs a `3.9` / `3.11` / `3.12` matrix (was a single `3.12`), so the
  advertised `>=3.9` floor and the Python 3.11 sandbox are actually tested
  (review finding CM-3).

### Removed
- The generic helpers' source (now imported from `claude-code-commons`); their
  SCOPE features F-001 (env), F-002 (`parse_num`), F-010 (`build_remote_path`) and
  the `currency_symbol` half of F-006 moved to the core. The private
  `ClaudeCodeStructure` reference in the env docstring/SCOPE went with them,
  closing a public-repo name leak (review finding CM-6).

## [0.3.0] - 2026-05-31

### Added

- **F-010** `build_remote_path(base, folder, filename)` joins an optional base
  directory, an optional sub-folder and a filename into one Dropbox path
  (slashes normalised). Lets a family of routines share one `DROPBOX_PATH` base
  while each writes into its own `<PREFIX>_DROPBOX_FOLDER` sub-folder. An unset
  folder reproduces the previous single-directory behaviour, so the change is
  backward compatible. Additive — no existing name changes.

## [0.2.0] - 2026-05-31

### Changed

- **F-001** `env_required` / `env_opt` gain an optional `prefix` keyword and now
  resolve a variable by trying `<prefix>_<key>` first, then the unprefixed
  `<key>` (plain `<key>` with no prefix — backward compatible). Enables a family
  of routines to share one environment: shared values set once unprefixed,
  per-routine values set prefixed. See ClaudeCodeStructure v0.6.0.

## [0.1.1] - 2026-05-31

### Changed

- Lower `requires-python` from `>=3.12` to `>=3.9` so the package installs in
  older runtimes (a scheduled-task sandbox runs Python 3.11). No code change —
  the suite already passed on 3.9 and 3.12.

## [0.1.0] - 2026-05-31

Initial release: the shared WooCommerce client and reporting helpers, packaged
for reuse across WooCommerce reporting routines.

### Added

- **F-001** `env_required` / `env_opt` environment helpers.
- **F-002** Tolerant `parse_num()`.
- **F-003** Tolerant `meta_get()` (skips non-dict meta entries).
- **F-004** `WooClient.get_with_retry` retry-with-backoff (5xx/429/connection
  retried; other 4xx not).
- **F-005** `WooClient.paged` pagination with a `MAX_PAGES` safety net.
- **F-006** `currency_symbol` + `detect_shop_currency` (fail-soft to EUR).
- **F-007** `iso_week_windows` ISO-week-aligned current/prior windows with a
  week-53 clamp.
- **F-008** `upload_to_dropbox` (refresh-token OAuth, overwrite, muted).
- **F-009** Excel style helpers (`style_header`, `set_widths`, shared fills/fonts).
