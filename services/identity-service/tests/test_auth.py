import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models.user import User, UserRole
from app.utils.security import hash_password


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
    assert second.status_code == 409
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
    assert resp.status_code == 401
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


@pytest.mark.asyncio
async def test_verify_returns_current_normal_user_role(client, test_user) -> None:
    _ = test_user
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "seed@example.com", "password": "password123"},
    )
    token = login.json()["data"]["access_token"]
    verified = await client.get(
        "/api/v1/auth/verify", headers={"Authorization": f"Bearer {token}"}
    )
    assert verified.status_code == 200
    assert verified.json()["data"] == {
        "valid": True,
        "sub": "seed@example.com",
        "role": "user",
    }


@pytest.mark.asyncio
async def test_verify_returns_admin_role(client, test_engine) -> None:
    session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        session.add(
            User(
                email="admin@example.com",
                hashed_password=hash_password("password123"),
                display_name="Admin",
                role=UserRole.ADMIN,
                is_active=True,
            )
        )
        await session.commit()
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "password123"},
    )
    token = login.json()["data"]["access_token"]
    verified = await client.get(
        "/api/v1/auth/verify", headers={"Authorization": f"Bearer {token}"}
    )
    assert verified.status_code == 200
    assert verified.json()["data"]["role"] == "admin"


@pytest.mark.asyncio
async def test_inactive_user_cannot_login_refresh_or_verify_existing_token(
    client, test_engine, test_user
) -> None:
    _ = test_user
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "seed@example.com", "password": "password123"},
    )
    assert login.status_code == 200
    tokens = login.json()["data"]

    session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        user = await session.get(User, test_user.id)
        assert user is not None
        user.is_active = False
        await session.commit()

    rejected_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "seed@example.com", "password": "password123"},
    )
    assert rejected_login.status_code == 401
    rejected_verify = await client.get(
        "/api/v1/auth/verify",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert rejected_verify.status_code == 401
    rejected_refresh = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert rejected_refresh.status_code == 401


@pytest.mark.parametrize(
    "raw_key",
    [b"", b"short", b"change_me" * 5, b"x" * 64],
    ids=["empty", "short", "placeholder", "low-entropy"],
)
def test_production_rejects_unsafe_jwt_secret_files(tmp_path, raw_key: bytes) -> None:
    path = tmp_path / "jwt-secret"
    path.write_bytes(raw_key)
    config = Settings(
        _env_file=None,
        app_env="production",
        jwt_secret_key_file=str(path),
        jwt_secret_key=None,
    )
    with pytest.raises(RuntimeError, match="unsafe"):
        _ = config.jwt_signing_key


def test_production_requires_external_jwt_secret_file() -> None:
    config = Settings(
        _env_file=None,
        app_env="production",
        jwt_secret_key_file=None,
        jwt_secret_key="inline-key-that-is-long-but-production-forbidden-12345",
    )
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY_FILE is required"):
        _ = config.jwt_signing_key


def test_jwt_secret_file_preserves_exact_raw_bytes(tmp_path) -> None:
    raw = b"\xff\x00identity-binary-key-material-with-enough-entropy-123456789"
    path = tmp_path / "jwt-secret"
    path.write_bytes(raw)
    config = Settings(
        _env_file=None,
        app_env="production",
        jwt_secret_key_file=str(path),
        jwt_secret_key=None,
    )
    assert config.jwt_signing_key == raw


@pytest.mark.asyncio
async def test_health_readiness_proves_db_auth_and_only_baked_build_identity(
    client, monkeypatch
) -> None:
    monkeypatch.setenv("OMNI_BUILD_COMMIT", "baked-commit")
    monkeypatch.setenv("OMNI_BUILD_SOURCE_FINGERPRINT", "sha256:baked")
    monkeypatch.setenv("OMNI_SOURCE_FINGERPRINT", "sha256:runtime-expected")

    health = await client.get("/health")
    readiness = await client.get("/health/readiness")

    assert health.status_code == 200
    assert health.json()["build_commit"] == "baked-commit"
    assert health.json()["build_source_fingerprint"] == "sha256:baked"
    assert "runtime-expected" not in str(health.json())
    assert readiness.status_code == 200
    assert readiness.json()["readable"] is True
    assert readiness.json()["authenticated"] is True
