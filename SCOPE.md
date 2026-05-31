# Scope

This document is the **single source of truth** for what this package does and
why. The README explains *how to use* it; this file defines *what it must do*.
Every feature below has an ID. Every feature ID must be covered by at least one
test (enforced by `tests/test_scope_coverage.py`). Do not add, change, or remove
a feature here without updating the tests — that is how current behaviour is
guaranteed across future changes.

## Purpose

A small, vendor-agnostic toolkit for WooCommerce reporting routines. It owns the
parts such routines have in common: an authenticated, paginated WooCommerce REST
client with a retry-with-backoff layer; tolerant parsing of the loosely-typed
JSON WooCommerce returns; shop-currency detection; ISO-week-aligned reporting
windows; a Dropbox refresh-token upload; and Excel styling helpers. It contains
**no report logic and no shop-specific knowledge** — only reusable plumbing — so
a fix made here lands in every consumer at once instead of being copy-pasted.

## Why it exists

Routines that pull data from a WooCommerce shop and build reports tend to
re-implement the same plumbing. Diverging copies are a maintenance hazard (a bug
fixed in one is missed in the others). Centralising the plumbing in one
installable package, versioned and tested in isolation, removes that hazard and
keeps each consumer thin: it imports the client and adds only its own report.

## Features (acceptance criteria)

Each feature is testable. The ID in brackets is referenced by tests via
`@pytest.mark.feature("F-00X")`.

- **[F-001] Environment helpers.** `env_required(key)` returns the stripped
  value of an env var and aborts the run with a clear `SystemExit` naming the
  variable when it is missing or empty — it never returns a placeholder.
  `env_opt(key, default)` returns the stripped value or `default` when
  unset/empty.

- **[F-002] Tolerant number parsing.** `parse_num()` accepts comma thousands
  separators (`"1,234"` → `1234.0`), plain numbers and numeric strings, and
  returns `0.0` for `None`, `""` or unparseable input — it never raises.

- **[F-003] Tolerant meta_data parsing.** `meta_get(meta_list, *keys)` returns
  the first non-empty value for any of the given keys, skipping non-dict entries
  in the list (some WC plugins write a bare string into `meta_data`) rather than
  raising. Returns `None` when nothing matches.

- **[F-004] Retry-with-backoff on transient failures.** `WooClient.get_with_retry`
  retries on connection errors/timeouts, HTTP 5xx and HTTP 429 up to
  `max_retries` times with exponential backoff (`retry_backoff_base × 2**attempt`
  seconds); other 4xx (401, 404, …) are raised immediately and never retried.

- **[F-005] Paginated client with a `MAX_PAGES` safety net.** `WooClient.paged`
  yields every item across pages of a WC list endpoint (`per_page` each) and
  stops after at most `max_pages` pages, logging a clear warning rather than
  looping or hanging on an unexpectedly large dataset.

- **[F-006] Currency awareness.** `currency_symbol(code)` maps a 3-letter code
  to a display symbol, falling back to the code itself for unmapped currencies.
  `detect_shop_currency(client)` reads the shop currency from `/system_status`
  via the retry layer and fails soft to `"EUR"` on any error or a missing value.

- **[F-007] ISO-week-aligned reporting windows.** `iso_week_windows(weeks, now)`
  returns a current and a prior window: the current covers the last `weeks`
  *completed* ISO weeks (ending at 00:00 UTC on the Monday of the ISO week
  containing `now`, exclusive), and the prior covers the same ISO week numbers in
  the previous ISO year — weekday-aligned (both start on a Monday) and the same
  length. A week-53 start clamps to week 52 when the previous ISO year has no
  week 53, without raising. Both windows expose `after`/`before` (UTC, `before`
  exclusive), a `label` and `iso_start`.

- **[F-008] Dropbox upload.** `upload_to_dropbox(...)` uploads a local file via
  the app-key + refresh-token OAuth flow in *overwrite* mode and muted (no
  desktop notification — these are automated runs). It returns the remote path
  on success and raises on failure so the caller chooses the exit behaviour.

- **[F-009] Excel style helpers.** `style_header(ws, n_cols)` applies the shared
  header style (bold white on dark fill, centred, frozen first row);
  `set_widths(ws, widths)` sets column widths; the module exposes the shared
  fills (`HEADER_FILL`, `RED`, `ORANGE`, `GREEN`) and fonts so the reports look
  consistent.

## Out of scope

Any report logic (the metrics themselves and how they are presented) — that
lives in the consuming routines; shop-specific meta keys, brand/category rules or
plugin-specific cost logic; writing back to WooCommerce (every helper here is
read-only against the WC API, except the Dropbox upload which writes only to
Dropbox); currency conversion (only symbol labelling). If any of these are ever
needed, add a new feature ID here first, then a test, then the code.
