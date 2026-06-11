# Scope

This document is the **single source of truth** for what this package does and
why. The README explains *how to use* it; this file defines *what it must do*.
Every feature below has an ID. Every feature ID must be covered by at least one
test (enforced by `tests/test_scope_coverage.py`). Do not add, change, or remove
a feature here without updating the tests — that is how current behaviour is
guaranteed across future changes.

## Purpose

The **WooCommerce-specific** toolkit for WooCommerce reporting routines: an
authenticated, paginated WooCommerce REST client with a retry-with-backoff layer;
tolerant parsing of WooCommerce `meta_data`; shop-currency detection;
ISO-week-aligned reporting windows; a Dropbox refresh-token upload; and Excel
styling helpers. It builds on the vendor-agnostic, dependency-light
`claude-code-commons` core (env lookup, `parse_num`, `currency_symbol`,
`build_remote_path`, `log`) and **re-exports** those helpers, so a consumer gets
the whole toolkit from one `wc_client` import. It contains **no report logic and
no shop-specific knowledge** — only reusable plumbing — so a fix made here lands
in every consumer at once.

## Why it exists

Routines that pull data from a WooCommerce shop and build reports tend to
re-implement the same plumbing. Diverging copies are a maintenance hazard (a bug
fixed in one is missed in the others). Centralising it in one installable
package, versioned and tested in isolation, removes that hazard and keeps each
consumer thin: it imports the client and adds only its own report.

## Features (acceptance criteria)

Each feature is testable. The ID in brackets is referenced by tests via
`@pytest.mark.feature("F-00X")`.

- **[F-003] Tolerant meta_data parsing.** `meta_get(meta_list, *keys)` returns
  the first non-empty value for any of the given keys, skipping non-dict entries
  in the list (some WC plugins write a bare string into `meta_data`) rather than
  raising. Returns `None` when nothing matches.

- **[F-004] Retry-with-backoff on transient failures.** `WooClient.get_with_retry`
  retries on connection errors/timeouts — including a connection that drops
  mid-body (`ChunkedEncodingError`) — HTTP 5xx and HTTP 429 up to
  `max_retries` times with exponential backoff (`retry_backoff_base × 2**attempt`
  seconds); other 4xx (401, 404, …) are raised immediately and never retried.

- **[F-005] Paginated client with a `MAX_PAGES` safety net and truncation flag.**
  `WooClient.paged` yields every item across pages of a WC list endpoint
  (`per_page` each) and stops after at most `max_pages` pages, logging a clear
  warning rather than looping or hanging on an unexpectedly large dataset. When it
  stops at the cap it sets `WooClient.truncated = True` so the caller can tell a
  truncated result from a naturally-exhausted one and flag the report as
  incomplete. The flag starts `False` and is sticky for the client's life.
  Requests carry a stable sort (`orderby=id`, `order=asc`) by default — explicit
  caller params win — so rows created or removed mid-pull cannot shift items
  between page fetches (WC's default newest-first ordering would double-yield or
  skip rows). A dataset that ends exactly at `max_pages` full pages is recognised
  as complete via the `X-WP-TotalPages` response header and does **not** set the
  flag; without that header the cap is conservatively reported as truncation.

- **[F-006] Shop-currency detection.** `detect_shop_currency(client)` reads the
  shop currency (3-letter code) from `/system_status` via the retry layer and
  fails soft to `"EUR"` on any error or a missing value. (The code→symbol mapping
  `currency_symbol` lives in the `claude-code-commons` core and is re-exported —
  see F-011.)

- **[F-007] ISO-week-aligned reporting windows.** `iso_week_windows(weeks, now,
  tz)` returns a current and a prior window: the current covers the last `weeks`
  *completed* ISO weeks (ending at 00:00 on the Monday of the ISO week
  containing `now`, exclusive), and the prior covers the same ISO week numbers in
  the previous ISO year — weekday-aligned (both start on a Monday) and the same
  length. A week-53 start clamps to week 52 when the previous ISO year has no
  week 53, without raising. `tz` (default UTC) is the shop's timezone: "today"
  is determined in `tz` — so a run early on Monday local time never silently
  reports a week-stale window from a still-Sunday UTC date — and the window
  boundaries are `tz`-local midnights (timezone-aware datetimes). Both windows
  expose `after`/`before` (aware, `before` exclusive), a `label`, `iso_start`
  and `days` (calendar days, stable across DST transitions).

- **[F-008] Dropbox upload.** `upload_to_dropbox(...)` uploads a local file via
  the app-key + refresh-token OAuth flow in *overwrite* mode and muted (no
  desktop notification — these are automated runs). It returns the remote path
  on success and raises on failure so the caller chooses the exit behaviour.

- **[F-009] Excel style helpers.** `style_header(ws, n_cols)` applies the shared
  header style (bold white on dark fill, centred, frozen first row);
  `set_widths(ws, widths)` sets column widths; the module exposes the shared
  fills (`HEADER_FILL`, `RED`, `ORANGE`, `GREEN`) and fonts so the reports look
  consistent.

- **[F-011] Re-exports the vendor-agnostic core.** The generic helpers from
  `claude-code-commons` — `env_required`, `env_opt`, `env_get`, `env_int`,
  `env_float`, `parse_num`, `currency_symbol`, `CURRENCY_SYMBOLS`,
  `build_remote_path`, `log` — are importable from `wc_client` unchanged, so a
  consumer gets generic + WooCommerce helpers from one import surface and an
  existing `from wc_client import parse_num, ...` keeps working. The env helpers'
  `shared` flag (defined in the core package) passes through transparently.

- **[F-012] Year-over-year percentage.** `yoy_pct(curr, prev)` returns
  `(curr - prev) / prev * 100`, or `None` when `prev <= 0` (growth is undefined
  for a genuinely new seller rather than an infinite spike; it naturally yields
  `-100` when `curr` is 0 and `prev > 0`). A pure, parameterised helper shared so
  every routine computes YoY identically.

- **[F-013] House-brand revenue share.** `house_brand_share(curr_by_brand,
  prev_by_brand, house_brand)` takes two `{brand: revenue}` maps and a single
  house-brand *label*, and returns house-brand revenue and its share of total
  revenue for both windows (`hb_curr`/`hb_prev`/`total_curr`/`total_prev`/
  `hb_share_curr`/`hb_share_prev`). The brand is matched case-insensitively
  (`.strip().lower()`); **no brand name is hard-coded** — the caller passes the
  configured label, and an empty/`None` label yields zero house-brand revenue.
  Shares are `None` when the total is 0; values are returned unrounded.

- **[F-014] Revenue versus target.** `revenue_goal(total_curr, total_prev, *,
  target_growth_pct, target_absolute)` returns `revenue_yoy`, the resolved
  `revenue_target` (a growth-% target `prev*(1+pct/100)` takes precedence over an
  absolute target *when it can resolve*, i.e. `prev > 0`; with a non-positive
  prior it falls back to the absolute target when given, else `revenue_target`
  **and** `revenue_target_basis` are both `None` — a basis is never returned
  without a target), `revenue_target_basis` (signed: `+20% vs prior year`,
  `-10% vs prior year`, or `absolute`), and `revenue_target_pct` (the share of
  target achieved). Values are unrounded.

- **[F-015] Shop timezone + canonical WC date params.** Two helpers so every
  consumer forms its order-window request identically instead of guessing.
  `shop_timezone(name)` parses an IANA timezone name (the family's shared
  `WC_TIMEZONE` key) to a `tzinfo`: empty/`None` falls back to UTC, an unknown
  name raises a `ValueError` naming the offending value (a config typo fails
  loudly at startup/dry-run, not silently mid-report). `wc_window_params(window)`
  renders a `Window` to WooCommerce REST params:
  `{"after", "before", "dates_are_gmt": "true"}` with both instants converted
  to **naive UTC** strings (`YYYY-MM-DDTHH:MM:SS`). With `dates_are_gmt=true`
  WooCommerce compares against the GMT date column, so the realised boundary is
  identical on legacy (CPT) and HPOS order storage. Because WP's `after` is
  strictly exclusive, the emitted `after` is `window.after − 1s` — the window
  keeps its `[after, before)` semantics on the wire: an order stamped exactly
  on the boundary second lands in the window that starts there, and in no
  other (closes the per-boundary 1-second hole).

## Out of scope

How metrics are *presented* (sheet layout, melding wording) and any
**shop-specific** rules — which brand is the house brand, shop-specific meta
keys, plugin-specific cost logic, brand/category business rules — live in the
consuming routines, not here. The package does provide a few **generic,
parameterised** KPI helpers (F-012–F-014): they hold no brand names or shop
knowledge (the house-brand *label* and targets are passed in by the caller), so
the *definition* of a KPI stays single-sourced while each routine still owns its
data, presentation and which brand counts as "house". Also out: writing back to
WooCommerce (every helper here is read-only against the WC API, except the
Dropbox upload which writes only to Dropbox); currency conversion (only symbol
labelling). The generic, vendor-agnostic plumbing itself lives in
`claude-code-commons` (re-exported via F-011), not here. If any of these are ever
needed, add a new feature ID here first, then a test, then the code.
