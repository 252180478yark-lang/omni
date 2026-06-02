from fastapi.testclient import TestClient

import app.routers.fetch as fetch_router


class _StubExec:
    def __init__(self):
        self.catalog = type("C", (), {"search": staticmethod(
            lambda platform=None, query=None, verified_only=False: [
                {"key": "yuntu.5a.asset_structure", "platform": "yuntu",
                 "category": "5A资产", "verified": True}
            ])})()

    def has_cookies(self, platform):
        return platform == "yuntu"

    async def fetch(self, platform, endpoint, params=None, body=None):
        return {"endpoint_key": endpoint, "platform": platform, "verdict": "PASS",
                "status": 200, "code": 0, "has_data": True, "fields": {"total_count": 9}}

    async def batch(self, requests):
        return [await self.fetch(**r) for r in requests]


def _client():
    from fastapi import FastAPI
    fetch_router.set_executor(_StubExec())
    app = FastAPI()
    app.include_router(fetch_router.router, prefix="/api/v1/scout")
    return TestClient(app)


def test_fetch_endpoint():
    c = _client()
    r = c.post("/api/v1/scout/fetch",
               json={"platform": "yuntu", "endpoint": "yuntu.5a.asset_structure"})
    assert r.status_code == 200
    assert r.json()["verdict"] == "PASS"
    assert r.json()["fields"]["total_count"] == 9


def test_batch_endpoint():
    c = _client()
    r = c.post("/api/v1/scout/fetch/batch",
               json={"requests": [{"platform": "yuntu", "endpoint": "yuntu.5a.asset_structure"}]})
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_auth_status():
    c = _client()
    r = c.get("/api/v1/scout/fetch/auth-status")
    assert r.status_code == 200
    body = r.json()
    assert body["yuntu"]["has_cookies"] is True
    assert body["compass"]["has_cookies"] is False


def test_list_endpoints():
    c = _client()
    r = c.get("/api/v1/scout/fetch/endpoints?platform=yuntu&query=5A")
    assert r.status_code == 200
    assert r.json()[0]["key"] == "yuntu.5a.asset_structure"
