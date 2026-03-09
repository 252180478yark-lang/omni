import pytest


@pytest.mark.asyncio
async def test_register_success(client) -> None:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "demo@example.com", "password": "password123", "display_name": "Demo"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    assert body["data"]["email"] == "demo@example.com"


@pytest.mark.asyncio
async def test_register_duplicate_email(client) -> None:
    payload = {"email": "dup@example.com", "password": "password123", "display_name": "Dup"}
    first = await client.post("/api/v1/auth/register", json=payload)
    second = await client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 200
    assert second.status_code == 400
    assert second.json()["message"] == "email already exists"


@pytest.mark.asyncio
async def test_login_success(client, test_user) -> None:
    _ = test_user
    resp = await client.post("/api/v1/auth/login", json={"email": "seed@example.com", "password": "password123"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["access_token"]
    assert data["refresh_token"]


@pytest.mark.asyncio
async def test_login_wrong_password(client, test_user) -> None:
    _ = test_user
    resp = await client.post("/api/v1/auth/login", json={"email": "seed@example.com", "password": "wrong-password"})
    assert resp.status_code == 400
    assert resp.json()["message"] == "invalid credentials"


@pytest.mark.asyncio
async def test_get_me_authenticated(client, test_user) -> None:
    _ = test_user
    login = await client.post("/api/v1/auth/login", json={"email": "seed@example.com", "password": "password123"})
    token = login.json()["data"]["access_token"]
    resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["data"]["email"] == "seed@example.com"


@pytest.mark.asyncio
async def test_get_me_unauthenticated(client) -> None:
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401
