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
    def __init__(self, data=None, status=200):
        self._data = data
        self.status_code = status
        self.text = ""

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
    meta = ["a-bare-string", {"key": "x", "value": ""}, {"key": "x", "value": "7"},
            {"key": "y", "value": "z"}]
    assert C.meta_get(meta, "x") == "7"        # first non-empty for x, non-dict skipped
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
    monkeypatch.setattr(client, "get_with_retry", lambda url, params=None: FakeResp([{"x": 1}]))
    assert len(list(client.paged("/products"))) == 2  # stopped at cap, no hang


@pytest.mark.feature("F-005")
def test_paged_sets_truncated_flag_on_cap(monkeypatch):
    client = _client(per_page=1, max_pages=2)
    monkeypatch.setattr(client, "get_with_retry", lambda url, params=None: FakeResp([{"x": 1}]))
    assert client.truncated is False
    list(client.paged("/products"))
    assert client.truncated is True  # cap hit -> caller can detect truncation


@pytest.mark.feature("F-005")
def test_paged_stops_on_short_page(monkeypatch):
    client = _client(per_page=10, max_pages=50)
    monkeypatch.setattr(client, "get_with_retry",
                        lambda url, params=None: FakeResp([{"x": 1}, {"x": 2}]))
    assert len(list(client.paged("/orders"))) == 2  # short page ends pagination
    assert client.truncated is False                # natural end -> not truncated


@pytest.mark.feature("F-005")
def test_paged_stops_on_empty(monkeypatch):
    client = _client()
    monkeypatch.setattr(client, "get_with_retry", lambda url, params=None: FakeResp([]))
    assert list(client.paged("/orders")) == []


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

    assert C.detect_shop_currency(FakeClient({"settings": {"currency": "usd"}})) == "USD"
    # Fail-soft to EUR on error or missing value.
    assert C.detect_shop_currency(FakeClient(exc=RuntimeError("boom"))) == "EUR"
    assert C.detect_shop_currency(FakeClient({"settings": {}})) == "EUR"


# ---------------------------------------------------------------------------
# F-007 ISO-week windows
# ---------------------------------------------------------------------------


@pytest.mark.feature("F-007")
def test_iso_week_windows_aligned():
    cur, pri = C.iso_week_windows(4, now=datetime(2026, 5, 30, tzinfo=timezone.utc))
    assert cur.before.date() == date(2026, 5, 25)   # Monday of in-progress week
    assert cur.after.date() == date(2026, 4, 27)
    assert cur.days == 28
    assert cur.after.weekday() == 0                 # Monday
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
        app_key="a", app_secret="b", refresh_token="c",
        local_path=str(f), remote_path="/Reports/report.xlsx", timeout_seconds=5)
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
        C.upload_to_dropbox(app_key="a", app_secret="b", refresh_token="c",
                            local_path=str(f), remote_path="/x", timeout_seconds=5)


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
    from wc_client import (CURRENCY_SYMBOLS, build_remote_path, currency_symbol,
                           env_float, env_get, env_int, env_opt, env_required, log,
                           parse_num)

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
    assert env_opt("KNOB", "def", prefix="STOCK") == "def"            # prefix-required
    assert env_opt("KNOB", "def", prefix="STOCK", shared=True) == "plain"  # shared fallback
