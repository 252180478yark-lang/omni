from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import AppException
from app.models.user import User, UserRole
from app.schemas.auth import RegisterRequest, TokenResponse
from app.utils.security import create_access_token, create_refresh_token, decode_token, hash_password, verify_password


async def register_user(db: AsyncSession, payload: RegisterRequest) -> User:
    existed = await db.scalar(select(User).where(User.email == payload.email))
    if existed:
        raise AppException(code=409, message="email already exists", detail="duplicate email")

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        display_name=payload.display_name,
        role=UserRole.USER,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User:
    user = await db.scalar(select(User).where(User.email == email))
    if not user or not verify_password(password, user.hashed_password):
        raise AppException(code=401, message="invalid credentials", detail="")
    return user


def issue_tokens(user: User) -> TokenResponse:
    access_token = create_access_token(user.email, {"role": user.role.value})
    refresh_token = create_refresh_token(user.email, {"role": user.role.value})
    return TokenResponse(access_token=access_token, refresh_token=refresh_token, token_type="bearer")


async def refresh_tokens(db: AsyncSession, refresh_token: str) -> TokenResponse:
    claims = decode_token(refresh_token)
    if claims.get("type") != "refresh":
        raise AppException(code=401, message="invalid refresh token", detail="")
    email = claims.get("sub")
    if not isinstance(email, str):
        raise AppException(code=401, message="invalid refresh token", detail="")
    user = await db.scalar(select(User).where(User.email == email))
    if not user:
        raise AppException(code=401, message="invalid refresh token", detail="")
    return issue_tokens(user)
