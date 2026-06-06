# Claude WooCommerce Commons

Shared, vendor-agnostic plumbing for WooCommerce reporting routines. One
installable package, versioned and tested in isolation, so a fix lands in every
consumer at once instead of being copy-pasted.

It contains **no report logic** — only the parts such routines have in common.

## What's inside

| Area | API |
|------|-----|
| REST client | `WooClient(url, key, secret, *, per_page, max_pages, timeout_seconds, max_retries, retry_backoff_base)` with `.get_with_retry()` and `.paged()` |
| Parsing | `parse_num()`, `meta_get()` — tolerant of WooCommerce's loose JSON |
| Env | `env_required()`, `env_opt()` |
| Currency | `currency_symbol()`, `detect_shop_currency()` |
| Reporting windows | `iso_week_windows(weeks, now)` → `(current, prior)` weekday-aligned |
| Dropbox | `upload_to_dropbox(...)` (refresh-token OAuth, overwrite, muted) |
| Excel | `style_header()`, `set_widths()`, shared fills/fonts |

All of it is read-only against the WooCommerce REST API (the Dropbox upload
writes only to Dropbox). See `SCOPE.md` for the full feature contract.

## Install

```bash
pip install -e ".[test]"        # local dev (editable) + pytest
```

The package exposes a single top-level module:

```python
from wc_client import WooClient, parse_num, iso_week_windows, upload_to_dropbox

client = WooClient(url, key, secret, max_pages=200)
for product in client.paged("/products", {"status": "publish"}):
    ...
current, prior = iso_week_windows(weeks=10)
```

## Tests

```bash
pytest
```

The suite mocks all network — it never touches a real shop or Dropbox. A
coverage test (`tests/test_scope_coverage.py`) fails if any `SCOPE.md` feature
lacks a test or a test references a feature not in `SCOPE.md`.

## Contributing

Branching is **trunk-on-main**, and releases go through a strict
version = changelog = tag gate. See [CONTRIBUTING.md](./CONTRIBUTING.md) for the full
procedure and the `ruff` + `pytest` quality gates.
