import pytest

import app.mcp.tools.platform_fetch as pf


class _FakeResp:
    def __init__(self, payload, status=200):
        self._p = payload
        self.status_code = status

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class _FakeClient:
    def __init__(self, payload):
        self._p = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None):
        return _FakeResp(self._p)

    async def get(self, url, params=None):
        return _FakeResp(self._p)


@pytest.mark.asyncio
async def test_platform_fetch_ok(monkeypatch):
    payload = {"endpoint_key": "yuntu.5a.asset_structure", "verdict": "PASS",
               "status": 200, "code": 0, "has_data": True, "fields": {"total_count": 9}}
    monkeypatch.setattr(pf.httpx, "AsyncClient", lambda *a, **k: _FakeClient(payload))
    res = await pf._platform_fetch_impl("yuntu", "yuntu.5a.asset_structure")
    assert res["ok"] is True
    assert res["result"]["verdict"] == "PASS"
    assert res["result"]["fields"]["total_count"] == 9


@pytest.mark.asyncio
async def test_platform_fetch_auth_fail_surfaces(monkeypatch):
    payload = {"endpoint_key": "x", "verdict": "FAIL_AUTH", "hint": "去 /scout 扫码登录"}
    monkeypatch.setattr(pf.httpx, "AsyncClient", lambda *a, **k: _FakeClient(payload))
    res = await pf._platform_fetch_impl("yuntu", "x")
    assert res["ok"] is False
    assert res["error"] == "FAIL_AUTH"
    assert "登录" in res["hint"]


@pytest.mark.asyncio
async def test_list_endpoints(monkeypatch):
    payload = [{"key": "yuntu.5a.asset_structure", "category": "5A资产", "verified": True}]
    monkeypatch.setattr(pf.httpx, "AsyncClient", lambda *a, **k: _FakeClient(payload))
    res = await pf._list_endpoints_impl("yuntu", "5A", False)
    assert res["ok"] is True
    assert res["result"]["count"] == 1


@pytest.mark.asyncio
async def test_auth_status(monkeypatch):
    payload = {"yuntu": {"has_cookies": True}, "compass": {"has_cookies": False},
               "doudian": {"has_cookies": False}}
    monkeypatch.setattr(pf.httpx, "AsyncClient", lambda *a, **k: _FakeClient(payload))
    res = await pf._auth_status_impl()
    assert res["ok"] is True
    assert res["result"]["yuntu"]["has_cookies"] is True
