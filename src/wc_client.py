#!/usr/bin/env python3
"""
Shared WooCommerce REST helpers.

This module is a self-contained, vendor-agnostic toolkit for WooCommerce
reporting routines. It is deliberately a standalone
file with no dependency on any one report's Config; it now lives in the shared
`ClaudeWooCommerceCommons` package (distribution `claude-woocommerce-commons`).

What lives here:
  - parse_num / meta_get  — tolerant parsing of the mixed types WC returns
  - WooClient             — authenticated, paginated REST client with a
                            retry-with-backoff layer for transient failures
  - currency detection    — read the shop currency from /system_status
  - Dropbox upload        — refresh-token OAuth upload (overwrite, muted)
  - Excel style helpers   — shared header styling / column widths

Nothing here is store-specific. Reports build on top of it.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterator

import requests
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


# ---------------------------------------------------------------------------
# Env helpers
# ---------------------------------------------------------------------------


def _env_lookup(key: str, prefix: str) -> str | None:
    """Project-prefix-with-fallback lookup: try `<prefix>_<key>` first, then the
    unprefixed `<key>`. Returns the first set & non-empty (stripped) value, or
    None. With no prefix this is a plain `<key>` lookup (backward compatible).

    This lets a family of routines share one environment: shared values
    (credentials, tokens, common knobs) are set once unprefixed and reached via
    the fallback, while per-routine values are set prefixed so they never
    collide. See ClaudeCodeStructure → CLAUDE.md "Environment variables".
    """
    names = (f"{prefix}_{key}", key) if prefix else (key,)
    for name in names:
        v = os.environ.get(name, "").strip()
        if v:
            return v
    return None


def env_required(key: str, *, prefix: str = "") -> str:
    """Return a required env var, stripped, using the project-prefix-with-fallback
    lookup. Aborts the run with a clear SystemExit naming the variable when
    neither the prefixed nor the unprefixed form is set. Reports never fall back
    to a placeholder value for a credential or shop URL."""
    v = _env_lookup(key, prefix)
    if not v:
        suffix = f" (or {prefix}_{key})" if prefix else ""
        raise SystemExit(f"Missing required env var: {key}{suffix}")
    return v


def env_opt(key: str, default: str | None = None, *, prefix: str = "") -> str | None:
    """Return an optional env var, stripped, using the project-prefix-with-
    fallback lookup, or `default` when neither form is set/non-empty."""
    v = _env_lookup(key, prefix)
    return v if v is not None else default


# ---------------------------------------------------------------------------
# Tolerant parsing
# ---------------------------------------------------------------------------


def parse_num(v: Any) -> float:
    """Parse the mixed numeric types WooCommerce returns in JSON.

    Accepts plain numbers, numeric strings, and strings with comma thousands
    separators ("1,234" -> 1234.0). Returns 0.0 for None, "", or anything
    unparseable — it never raises, which is what lets the rest of the code
    treat WC's loose typing uniformly.
    """
    if v is None or v == "":
        return 0.0
    try:
        return float(str(v).replace(",", ""))
    except (ValueError, TypeError):
        return 0.0


def meta_get(meta_list: list | None, *keys: str) -> Any:
    """Return the first non-empty value for any of the given meta keys.

    Tolerates non-dict entries: some WC plugins write a bare string or other
    shape into `meta_data` alongside the normal `{"key", "value"}` dicts. A
    single malformed entry must not crash a run, so non-dicts are skipped.
    """
    if not meta_list:
        return None
    for key in keys:
        for m in meta_list:
            if not isinstance(m, dict):
                continue
            if m.get("key") == key:
                val = m.get("value")
                if val not in (None, "", []):
                    return val
    return None


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Currency helpers
# ---------------------------------------------------------------------------

# Known currency code -> display symbol. Codes not in the table fall back to
# the 3-letter code itself, which is always valid in Excel number formats.
CURRENCY_SYMBOLS = {
    "EUR": "€", "USD": "$", "GBP": "£", "CHF": "CHF",
    "DKK": "kr", "SEK": "kr", "NOK": "kr", "ISK": "kr",
    "JPY": "¥", "CNY": "¥",
    "CAD": "$", "AUD": "$", "NZD": "$", "HKD": "$",
    "PLN": "zł", "CZK": "Kč", "HUF": "Ft",
}


def currency_symbol(code: str) -> str:
    """Return a display symbol for a 3-letter currency code, falling back to
    the code itself for currencies we have not mapped."""
    return CURRENCY_SYMBOLS.get((code or "").upper(), (code or "").upper())


def detect_shop_currency(client: "WooClient") -> str:
    """Read the shop currency (3-letter code) from WooCommerce /system_status.

    Falls back to 'EUR' on any error — auto-detect failure must never block a
    run. Goes through the retry layer so a transient hiccup at startup does
    not regress to the fallback.
    """
    try:
        r = client.get_with_retry(f"{client.base}/system_status")
        currency = (r.json().get("settings", {}).get("currency") or "").upper()
        if not currency:
            log("WARNING: shop currency not in /system_status response; using EUR.")
            return "EUR"
        return currency
    except Exception as exc:  # noqa: BLE001 — fail-soft, never block the run
        log(f"WARNING: shop currency auto-detect failed ({exc}); using EUR.")
        return "EUR"


# ---------------------------------------------------------------------------
# WooCommerce client
# ---------------------------------------------------------------------------


class WooClient:
    """Authenticated, paginated WooCommerce REST v3 client.

    Parameter-based (not coupled to any report's Config) so it can be reused
    across routines and later extracted into a shared package unchanged.
    """

    def __init__(
        self,
        wc_url: str,
        consumer_key: str,
        consumer_secret: str,
        *,
        per_page: int = 100,
        max_pages: int = 50,
        timeout_seconds: int = 30,
        max_retries: int = 3,
        retry_backoff_base: float = 1.0,
    ):
        self.session = requests.Session()
        self.session.auth = (consumer_key, consumer_secret)
        self.base = f"{wc_url.rstrip('/')}/wp-json/wc/v3"
        self.per_page = per_page
        self.max_pages = max_pages
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_backoff_base = retry_backoff_base

    def get_with_retry(self, url: str, params: dict | None = None):
        """GET with retry-with-backoff for transient errors.

        Retries on connection errors/timeouts, HTTP 5xx, and HTTP 429
        (rate-limited). Does NOT retry other 4xx — those are configuration
        errors (401 invalid key, 404 wrong endpoint) that retrying cannot fix.
        Backs off exponentially: retry_backoff_base * 2**attempt seconds.
        """
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                r = self.session.get(url, params=params, timeout=self.timeout_seconds)
                if r.status_code == 429 or 500 <= r.status_code < 600:
                    r.raise_for_status()  # raise so the retry path triggers
                r.raise_for_status()  # other 4xx falls through to caller, NOT retried
                return r
            except requests.HTTPError as exc:
                last_exc = exc
                code = exc.response.status_code if exc.response is not None else None
                if code is not None and code != 429 and not (500 <= code < 600):
                    raise  # non-retryable 4xx — bubble immediately
                if attempt >= self.max_retries:
                    raise
                wait = self.retry_backoff_base * (2 ** attempt)
                log(f"WARNING: WC {code} on {url} — retry {attempt + 1}/"
                    f"{self.max_retries} after {wait}s")
                time.sleep(wait)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                if attempt >= self.max_retries:
                    raise
                wait = self.retry_backoff_base * (2 ** attempt)
                log(f"WARNING: WC connection error ({type(exc).__name__}) on "
                    f"{url} — retry {attempt + 1}/{self.max_retries} after {wait}s")
                time.sleep(wait)
        raise last_exc  # type: ignore[misc]  # unreachable: loop returns or raises

    def paged(self, path: str, params: dict | None = None) -> Iterator[dict]:
        """Yield every item across pages of a WC list endpoint, stopping after
        `max_pages` with a clear warning so a runaway loop or a much larger
        dataset is visible rather than a silent hang."""
        params = dict(params or {})
        params["per_page"] = self.per_page
        page = 1
        while True:
            if page > self.max_pages:
                log(f"WARNING: reached MAX_PAGES={self.max_pages} on {path}. "
                    "Increase MAX_PAGES if your dataset is larger.")
                return
            params["page"] = page
            r = self.get_with_retry(f"{self.base}{path}", params=params)
            batch = r.json()
            if not batch:
                return
            for item in batch:
                yield item
            if len(batch) < self.per_page:
                return
            page += 1


# ---------------------------------------------------------------------------
# Dropbox upload
# ---------------------------------------------------------------------------


def upload_to_dropbox(
    *,
    app_key: str,
    app_secret: str,
    refresh_token: str,
    local_path: str,
    remote_path: str,
    timeout_seconds: int = 30,
) -> str:
    """Upload a local file to Dropbox via the app-key + refresh-token OAuth
    flow, in overwrite mode and muted (no desktop notification — these are
    automated daily runs). Returns the remote path on success; raises on
    failure so the caller can decide the exit code."""
    r = requests.post(
        "https://api.dropbox.com/oauth2/token",
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        auth=(app_key, app_secret),
        timeout=timeout_seconds,
    )
    r.raise_for_status()
    access_token = r.json()["access_token"]

    with open(local_path, "rb") as f:
        data = f.read()
    args = {
        "path": remote_path,
        "mode": "overwrite",
        "autorename": False,
        "mute": True,
        "strict_conflict": False,
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Dropbox-API-Arg": json.dumps(args),
        "Content-Type": "application/octet-stream",
    }
    r = requests.post(
        "https://content.dropboxapi.com/2/files/upload",
        headers=headers,
        data=data,
        timeout=timeout_seconds * 2,
    )
    r.raise_for_status()
    return r.json().get("path_display", remote_path)


# ---------------------------------------------------------------------------
# ISO-week reporting windows
# ---------------------------------------------------------------------------
# Shared so reporting routines align "this period vs the same period
# last year" identically. ISO weeks always start on Monday, so aligning last
# year's window by ISO week number lines the two up by weekday automatically.


@dataclass
class Window:
    """A resolved reporting window. `before` is exclusive. `iso_start` is the
    ISO (year, week) of the window's first day."""
    after: datetime
    before: datetime
    label: str
    iso_start: tuple

    @property
    def days(self) -> int:
        return (self.before - self.after).days


def _utc_midnight(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def _monday_of_iso_week(d: date) -> date:
    """Return the Monday (ISO weekday 1) of the ISO week containing `d`."""
    iso_year, iso_week, _ = d.isocalendar()
    return date.fromisocalendar(iso_year, iso_week, 1)


def _safe_iso_monday(iso_year: int, iso_week: int) -> date:
    """Monday of (iso_year, iso_week), clamping week 53 to 52 when the target
    ISO year has no week 53 (no crash on the boundary)."""
    try:
        return date.fromisocalendar(iso_year, iso_week, 1)
    except ValueError:
        return date.fromisocalendar(iso_year, 52, 1)


def _window_label(start: date, end: date, iso_year: int, iso_week: int, weeks: int) -> str:
    last_day = end - timedelta(days=1)
    return (f"{iso_year}-W{iso_week:02d} +{weeks}wk "
            f"({start.isoformat()}–{last_day.isoformat()})")


def iso_week_windows(weeks: int, now: "datetime | None" = None) -> tuple[Window, Window]:
    """Resolve a current and a prior (one-ISO-year-earlier) window of `weeks`
    completed ISO weeks.

    Current: ends at 00:00 UTC on the Monday of the ISO week containing `now`
    (exclusive — the in-progress week is never half-counted) and starts `weeks`
    weeks earlier (also a Monday). Prior: the same ISO week number in the
    previous ISO year, weekday-aligned (both start on a Monday) and the same
    length. Week 53 clamps to 52 when last year has no week 53. `now` is
    injectable for tests.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    current_end_date = _monday_of_iso_week(now.date())     # start of the in-progress week
    current_start_date = current_end_date - timedelta(weeks=weeks)
    cy, cw, _ = current_start_date.isocalendar()
    current = Window(
        after=_utc_midnight(current_start_date),
        before=_utc_midnight(current_end_date),
        label=_window_label(current_start_date, current_end_date, cy, cw, weeks),
        iso_start=(cy, cw),
    )

    prior_start_date = _safe_iso_monday(cy - 1, cw)
    prior_end_date = prior_start_date + timedelta(weeks=weeks)
    py, pw, _ = prior_start_date.isocalendar()
    prior = Window(
        after=_utc_midnight(prior_start_date),
        before=_utc_midnight(prior_end_date),
        label=_window_label(prior_start_date, prior_end_date, py, pw, weeks),
        iso_start=(py, pw),
    )
    return current, prior


# ---------------------------------------------------------------------------
# Excel style helpers
# ---------------------------------------------------------------------------

HEADER_FONT = Font(bold=True, color="FFFFFF")
HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
THIN = Side(style="thin", color="CCCCCC")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
CENTER = Alignment(horizontal="center", vertical="center")
RED = PatternFill("solid", fgColor="F8CBAD")
ORANGE = PatternFill("solid", fgColor="FFE699")
GREEN = PatternFill("solid", fgColor="C6E0B4")


def style_header(ws, n_cols: int) -> None:
    for col_idx in range(1, n_cols + 1):
        c = ws.cell(row=1, column=col_idx)
        c.font = HEADER_FONT
        c.fill = HEADER_FILL
        c.alignment = CENTER
        c.border = BORDER
    ws.freeze_panes = "A2"
    ws.row_dimensions[1].height = 22


def set_widths(ws, widths: list[int]) -> None:
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
