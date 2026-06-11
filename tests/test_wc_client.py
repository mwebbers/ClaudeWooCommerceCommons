"""Tests for the shared WooCommerce client.

Every test is tagged with the SCOPE.md feature it covers. All network is mocked
— the suite never touches a real shop or Dropbox. The generic helpers are tested
in `claude-code-commons`; here F-011 only checks they remain importable from
`wc_client` (back-compat).
"""

from datetime import date, datetime, timezone

import pytest
import requests

import wc_client as C

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeResp:
    def __init__(self, data=None, status=200, headers=None):
        self._data = data
        self.status_code = status
        self.text = ""
        self.headers = headers or {}

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)


# ---------------------------------------------------------------------------
# F-003 Tolerant meta_data parsing
# ---------------------------------------------------------------------------


@pytest.mark.feature("F-003")
def test_meta_get():
    meta = [
        "a-bare-string",
        {"key": "x", "value": ""},
        {"key": "x", "value": "7"},
        {"key": "y", "value": "z"},
    ]
    assert C.meta_get(meta, "x") == "7"  # first non-empty for x, non-dict skipped
    assert C.meta_get(meta, "missing", "y") == "z"
    assert C.meta_get(meta, "nope") is None
    assert C.meta_get(None, "x") is None


# ---------------------------------------------------------------------------
# F-004 Retry-with-backoff
# ---------------------------------------------------------------------------


def _client(**kw):
    return C.WooClient("https://shop.example", "k", "s", **kw)


@pytest.mark.feature("F-004")
def test_retry_then_success(monkeypatch):
    client = _client(max_retries=2, retry_backoff_base=0)
    calls = {"n": 0}

    def flaky(url, params=None, timeout=None):
        calls["n"] += 1
        if calls["n"] < 2:
            raise requests.ConnectionError("reset")
        return FakeResp({"ok": True})

    monkeypatch.setattr(client.session, "get", flaky)
    monkeypatch.setattr(C.time, "sleep", lambda s: None)
    assert client.get_with_retry("https://shop.example/x").json() == {"ok": True}
    assert calls["n"] == 2


@pytest.mark.feature("F-004")
def test_5xx_retried_then_raises(monkeypatch):
    client = _client(max_retries=2, retry_backoff_base=0)
    calls = {"n": 0}

    def always_500(url, params=None, timeout=None):
        calls["n"] += 1
        return FakeResp(status=500)

    monkeypatch.setattr(client.session, "get", always_500)
    monkeypatch.setattr(C.time, "sleep", lambda s: None)
    with pytest.raises(requests.HTTPError):
        client.get_with_retry("https://shop.example/x")
    assert calls["n"] == 3  # initial + 2 retries


@pytest.mark.feature("F-004")
def test_mid_body_drop_retried(monkeypatch):
    # A connection that dies while the body is being read surfaces as
    # ChunkedEncodingError (not ConnectionError) — must hit the same retry path.
    client = _client(max_retries=2, retry_backoff_base=0)
    calls = {"n": 0}

    def drops_mid_body(url, params=None, timeout=None):
        calls["n"] += 1
        if calls["n"] < 2:
            raise requests.exceptions.ChunkedEncodingError("connection broken")
        return FakeResp({"ok": True})

    monkeypatch.setattr(client.session, "get", drops_mid_body)
    monkeypatch.setattr(C.time, "sleep", lambda s: None)
    assert client.get_with_retry("https://shop.example/x").json() == {"ok": True}
    assert calls["n"] == 2


@pytest.mark.feature("F-004")
def test_4xx_not_retried(monkeypatch):
    client = _client(max_retries=3)
    calls = {"n": 0}

    def always_404(url, params=None, timeout=None):
        calls["n"] += 1
        return FakeResp(status=404)

    monkeypatch.setattr(client.session, "get", always_404)
    with pytest.raises(requests.HTTPError):
        client.get_with_retry("https://shop.example/x")
    assert calls["n"] == 1


# ---------------------------------------------------------------------------
# F-005 Pagination + MAX_PAGES + truncation flag
# ---------------------------------------------------------------------------


@pytest.mark.feature("F-005")
def test_paged_max_pages_cap(monkeypatch):
    client = _client(per_page=1, max_pages=2)
    monkeypatch.setattr(
        client, "get_with_retry", lambda url, params=None: FakeResp([{"x": 1}])
    )
    assert len(list(client.paged("/products"))) == 2  # stopped at cap, no hang


@pytest.mark.feature("F-005")
def test_paged_sets_truncated_flag_on_cap(monkeypatch):
    client = _client(per_page=1, max_pages=2)
    monkeypatch.setattr(
        client, "get_with_retry", lambda url, params=None: FakeResp([{"x": 1}])
    )
    assert client.truncated is False
    list(client.paged("/products"))
    assert client.truncated is True  # cap hit -> caller can detect truncation


@pytest.mark.feature("F-005")
def test_paged_stops_on_short_page(monkeypatch):
    client = _client(per_page=10, max_pages=50)
    monkeypatch.setattr(
        client,
        "get_with_retry",
        lambda url, params=None: FakeResp([{"x": 1}, {"x": 2}]),
    )
    assert len(list(client.paged("/orders"))) == 2  # short page ends pagination
    assert client.truncated is False  # natural end -> not truncated


@pytest.mark.feature("F-005")
def test_paged_stops_on_empty(monkeypatch):
    client = _client()
    monkeypatch.setattr(client, "get_with_retry", lambda url, params=None: FakeResp([]))
    assert list(client.paged("/orders")) == []


@pytest.mark.feature("F-005")
def test_paged_pins_stable_sort_by_default(monkeypatch):
    # Without a pinned sort, WC's newest-first default lets a row created
    # mid-pull shift the page boundaries (duplicate/skipped items).
    client = _client()
    seen = {}

    def capture(url, params=None):
        seen.update(params)
        return FakeResp([])

    monkeypatch.setattr(client, "get_with_retry", capture)
    list(client.paged("/orders"))
    assert seen["orderby"] == "id" and seen["order"] == "asc"
    # An explicit caller choice wins over the default.
    list(client.paged("/orders", {"orderby": "date", "order": "desc"}))
    assert seen["orderby"] == "date" and seen["order"] == "desc"


@pytest.mark.feature("F-005")
def test_paged_exact_max_pages_fit_is_not_truncated(monkeypatch):
    # Dataset of exactly max_pages full pages: X-WP-TotalPages says the pull is
    # complete, so the truncated flag must NOT be set (no false "incomplete").
    client = _client(per_page=1, max_pages=2)
    calls = {"n": 0}

    def serve(url, params=None):
        calls["n"] += 1
        return FakeResp([{"x": params["page"]}], headers={"X-WP-TotalPages": "2"})

    monkeypatch.setattr(client, "get_with_retry", serve)
    assert len(list(client.paged("/products"))) == 2
    assert client.truncated is False
    assert calls["n"] == 2  # page max_pages+1 was never requested


# ---------------------------------------------------------------------------
# F-006 Shop-currency detection
# ---------------------------------------------------------------------------


@pytest.mark.feature("F-006")
def test_detect_shop_currency(monkeypatch):
    class FakeClient:
        base = "https://shop.example/wp-json/wc/v3"

        def __init__(self, resp=None, exc=None):
            self._resp, self._exc = resp, exc

        def get_with_retry(self, url, params=None):
            if self._exc:
                raise self._exc
            return FakeResp(self._resp)

    assert (
        C.detect_shop_currency(FakeClient({"settings": {"currency": "usd"}})) == "USD"
    )
    # Fail-soft to EUR on error or missing value.
    assert C.detect_shop_currency(FakeClient(exc=RuntimeError("boom"))) == "EUR"
    assert C.detect_shop_currency(FakeClient({"settings": {}})) == "EUR"


# ---------------------------------------------------------------------------
# F-007 ISO-week windows
# ---------------------------------------------------------------------------


@pytest.mark.feature("F-007")
def test_iso_week_windows_aligned():
    cur, pri = C.iso_week_windows(4, now=datetime(2026, 5, 30, tzinfo=timezone.utc))
    assert cur.before.date() == date(2026, 5, 25)  # Monday of in-progress week
    assert cur.after.date() == date(2026, 4, 27)
    assert cur.days == 28
    assert cur.after.weekday() == 0  # Monday
    assert pri.after.weekday() == 0
    assert pri.days == 28
    assert (cur.after.date() - pri.after.date()).days in (364, 371)


@pytest.mark.feature("F-007")
def test_week_53_clamp():
    monday = C._safe_iso_monday(2025, 53)  # 2025 has no week 53
    assert monday.weekday() == 0
    assert monday.isocalendar()[:2] == (2025, 52)


# ---------------------------------------------------------------------------
# F-008 Dropbox upload
# ---------------------------------------------------------------------------


@pytest.mark.feature("F-008")
def test_upload_to_dropbox_success(monkeypatch, tmp_path):
    f = tmp_path / "report.xlsx"
    f.write_bytes(b"xlsx-bytes")
    calls = []

    def fake_post(url, **kw):
        calls.append(url)
        if "oauth2/token" in url:
            return FakeResp({"access_token": "tok"})
        return FakeResp({"path_display": "/Reports/report.xlsx"})

    monkeypatch.setattr(C.requests, "post", fake_post)
    out = C.upload_to_dropbox(
        app_key="a",
        app_secret="b",
        refresh_token="c",
        local_path=str(f),
        remote_path="/Reports/report.xlsx",
        timeout_seconds=5,
    )
    assert out == "/Reports/report.xlsx"
    assert any("oauth2/token" in u for u in calls)
    assert any("files/upload" in u for u in calls)


@pytest.mark.feature("F-008")
def test_upload_to_dropbox_failure(monkeypatch, tmp_path):
    f = tmp_path / "report.xlsx"
    f.write_bytes(b"x")

    def fake_post(url, **kw):
        if "oauth2/token" in url:
            return FakeResp({"access_token": "tok"})
        return FakeResp(status=500)  # upload fails

    monkeypatch.setattr(C.requests, "post", fake_post)
    with pytest.raises(requests.HTTPError):
        C.upload_to_dropbox(
            app_key="a",
            app_secret="b",
            refresh_token="c",
            local_path=str(f),
            remote_path="/x",
            timeout_seconds=5,
        )


# ---------------------------------------------------------------------------
# F-009 Excel helpers
# ---------------------------------------------------------------------------


@pytest.mark.feature("F-009")
def test_excel_helpers():
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["A", "B", "C"])
    C.style_header(ws, 3)
    assert ws.cell(row=1, column=1).font.bold is True
    assert ws.freeze_panes == "A2"
    C.set_widths(ws, [10, 20, 30])
    assert ws.column_dimensions["B"].width == 20
    # Shared fills exposed for the reports.
    assert C.RED is not None and C.GREEN is not None and C.HEADER_FILL is not None


# ---------------------------------------------------------------------------
# F-011 Re-exports of the vendor-agnostic core (back-compat)
# ---------------------------------------------------------------------------


@pytest.mark.feature("F-011")
def test_reexports_core_helpers(monkeypatch):
    # The generic helpers remain importable from wc_client and behave as before.
    from wc_client import (
        CURRENCY_SYMBOLS,
        build_remote_path,
        currency_symbol,
        env_float,
        env_get,
        env_int,
        env_opt,
        env_required,
        log,
        parse_num,
    )

    assert parse_num("1,234") == 1234.0
    assert currency_symbol("EUR") == "€"
    assert "EUR" in CURRENCY_SYMBOLS
    assert build_remote_path("/Reports", "Stock", "r.xlsx") == "/Reports/Stock/r.xlsx"
    monkeypatch.setenv("WC_URL", "https://x")
    assert env_required("WC_URL") == "https://x"
    assert env_opt("MISSING", "d") == "d"
    assert env_get("MISSING", "d") == "d"
    # env_int/env_float are now re-exported too (core F-006).
    monkeypatch.setenv("PAGES", "200")
    assert env_int("PAGES", 50) == 200
    assert env_float("RATE", 1.0) == 1.0
    assert callable(log)


@pytest.mark.feature("F-011")
def test_reexported_shared_flag_passthrough(monkeypatch):
    # The core `shared` flag (F-001/F-007) passes through the re-export: a prefixed
    # routine-own key ignores the plain form, while shared=True still falls back.
    from wc_client import env_opt

    for k in ("KNOB", "STOCK_KNOB"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("KNOB", "plain")
    assert env_opt("KNOB", "def", prefix="STOCK") == "def"  # prefix-required
    assert (
        env_opt("KNOB", "def", prefix="STOCK", shared=True) == "plain"
    )  # shared fallback


# ---------------------------------------------------------------------------
# F-012 / F-013 / F-014 Goal / KPI arithmetic
# ---------------------------------------------------------------------------


@pytest.mark.feature("F-012")
def test_yoy_pct():
    assert C.yoy_pct(150, 100) == 50.0
    assert C.yoy_pct(0, 100) == -100.0  # lost all revenue -> -100, defined
    assert C.yoy_pct(100, 0) is None  # new seller -> undefined, no infinite spike
    assert C.yoy_pct(100, -5) is None  # negative prior is also undefined


@pytest.mark.feature("F-013")
def test_house_brand_share():
    curr = {"HuisMerk": 300.0, "Other": 700.0}
    prev = {"HuisMerk": 200.0, "Other": 800.0}
    r = C.house_brand_share(curr, prev, "huismerk")  # case-insensitive label match
    assert r["hb_curr"] == 300.0 and r["total_curr"] == 1000.0
    assert r["hb_share_curr"] == 30.0
    assert r["hb_share_prev"] == 20.0
    # No/empty label -> zero house-brand revenue; share undefined on a zero total.
    assert C.house_brand_share(curr, prev, None)["hb_curr"] == 0.0
    assert C.house_brand_share({}, {}, "huismerk")["hb_share_curr"] is None


@pytest.mark.feature("F-014")
def test_revenue_goal():
    # Growth-% target takes precedence over an absolute target. Kernel values are
    # unrounded by design (the caller rounds), so compare with approx.
    g = C.revenue_goal(660, 500, target_growth_pct=20.0, target_absolute=9999.0)
    assert g["revenue_target"] == pytest.approx(600.0)  # 500 * 1.2, growth wins
    assert g["revenue_target_pct"] == pytest.approx(110.0)  # 660 / 600 * 100
    assert g["revenue_yoy"] == pytest.approx(32.0)
    assert "vs prior year" in g["revenue_target_basis"]
    # Absolute target when no growth-% is given.
    a = C.revenue_goal(800, 500, target_absolute=1000.0)
    assert a["revenue_target"] == 1000.0
    assert a["revenue_target_pct"] == pytest.approx(80.0)
    assert a["revenue_target_basis"] == "absolute"
    # No target -> undefined; a growth target needs a positive prior.
    assert C.revenue_goal(800, 500)["revenue_target"] is None
    assert C.revenue_goal(800, 0, target_growth_pct=20.0)["revenue_target"] is None
    # A basis is never returned without a target (no orphaned "+20% vs ...").
    assert (
        C.revenue_goal(800, 0, target_growth_pct=20.0)["revenue_target_basis"] is None
    )
    # Unresolvable growth target falls back to a supplied absolute target.
    fb = C.revenue_goal(800, 0, target_growth_pct=20.0, target_absolute=1000.0)
    assert fb["revenue_target"] == 1000.0
    assert fb["revenue_target_basis"] == "absolute"
    # A decline target renders signed, not "+-10%".
    d = C.revenue_goal(450, 500, target_growth_pct=-10.0)
    assert d["revenue_target"] == pytest.approx(450.0)
    assert d["revenue_target_basis"] == "-10% vs prior year"
