# Changelog

All notable changes to this package are documented here. Each behaviour change
references the SCOPE.md feature ID(s) it implements.

The format follows [Keep a Changelog](https://keepachangelog.com/), and the
project adheres to semantic versioning.

## [Unreleased]

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
