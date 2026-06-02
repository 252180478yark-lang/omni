from datetime import date
from pathlib import Path

import pytest

from app.services.catalog_loader import CatalogLoader
from app.services.live_fetch import LiveFetchExecutor

FIXT = Path(__file__).parent / "fixtures" / "catalog_yuntu_sample.json"
CONTEXT = {"yuntu": {"aadvid": "1805203190148185"}}


class FakeExecutor(LiveFetchExecutor):
    """覆写浏览器层：记录最终 URL，返回预置 raw 结果。"""
    def __init__(self, *a, raw=None, **kw):
        super().__init__(*a, **kw)
        self._raw = raw or {"status": 200, "ct": "application/json",
                            "parsed": {"status": 0, "data": {"total_count": 9}},
                            "firstChars": "{}", "len": 2, "attempts": 1}
        self.last_call = None

    def has_cookies(self, platform: str) -> bool:
        return True

    async def _run_in_page(self, host, method, url, body):
        self.last_call = {"host": host, "method": method, "url": url, "body": body}
        return dict(self._raw)


def _exec(**kw):
    cat = CatalogLoader.from_files({"yuntu": FIXT}, CONTEXT)
    return FakeExecutor(catalog=cat, sessions_root=Path("/tmp/nonexistent"),
                        today=date(2026, 6, 1), **kw)


@pytest.mark.asyncio
async def test_fetch_resolves_endpoint_and_url():
    ex = _exec()
    res = await ex.fetch(platform="yuntu", endpoint="yuntu.5a.asset_structure")
    assert ex.last_call["method"] == "GET"
    assert "audience_end_date=20260601" in ex.last_call["url"]
    assert "aadvid=1805203190148185" in ex.last_call["url"]
    assert ex.last_call["url"].startswith("https://yuntu.oceanengine.com/yuntu_ng/api/v1/GetAudienceAssetStructure?")
    assert res["verdict"] == "PASS"
    assert res["fields"] == {"total_count": 9}
    assert res["endpoint_key"] == "yuntu.5a.asset_structure"


@pytest.mark.asyncio
async def test_fetch_param_override():
    ex = _exec()
    await ex.fetch(platform="yuntu", endpoint="yuntu.5a.asset_structure",
                  params={"audience_end_date": "20260520"})
    assert "audience_end_date=20260520" in ex.last_call["url"]


@pytest.mark.asyncio
async def test_fetch_unknown_endpoint_returns_error():
    ex = _exec()
    res = await ex.fetch(platform="yuntu", endpoint="nope.nope")
    assert res["verdict"] == "FAIL_OTHER"
    assert res["error"] == "endpoint_not_in_catalog"


@pytest.mark.asyncio
async def test_fetch_missing_cookies_returns_auth():
    ex = _exec()
    res = await ex.fetch(platform="yuntu", endpoint="yuntu.5a.asset_structure",
                        _force_no_cookies=True)
    assert res["verdict"] == "FAIL_AUTH"
    assert "登录" in res["hint"]


@pytest.mark.asyncio
async def test_batch_runs_all():
    ex = _exec()
    out = await ex.batch([
        {"platform": "yuntu", "endpoint": "yuntu.5a.asset_structure"},
        {"platform": "yuntu", "endpoint": "yuntu.gta.profile"},
    ])
    assert len(out) == 2
    assert {o["endpoint_key"] for o in out} == {"yuntu.5a.asset_structure", "yuntu.gta.profile"}
