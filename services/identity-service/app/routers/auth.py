from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_session
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.auth import LoginRequest, RefreshRequest, RegisterRequest, UserResponse
from app.schemas.common import ResponseModel
from app.services.auth_service import authenticate_user, issue_tokens, refresh_tokens, register_user

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register", response_model=ResponseModel[UserResponse])
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db_session)) -> ResponseModel[UserResponse]:
    user = await register_user(db, payload)
    return ResponseModel(
        data=UserResponse(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            role=user.role,
            created_at=user.created_at,
        )
    )


@router.post("/login", response_model=ResponseModel[dict])
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db_session)) -> ResponseModel[dict]:
    user = await authenticate_user(db, payload.email, payload.password)
    tokens = issue_tokens(user)
    return ResponseModel(data=tokens.model_dump())


@router.post("/refresh", response_model=ResponseModel[dict])
async def refresh(payload: RefreshRequest, db: AsyncSession = Depends(get_db_session)) -> ResponseModel[dict]:
    tokens = await refresh_tokens(db, payload.refresh_token)
    return ResponseModel(data=tokens.model_dump())


@router.get("/me", response_model=ResponseModel[UserResponse])
async def me(current_user: User = Depends(get_current_user)) -> ResponseModel[UserResponse]:
    return ResponseModel(
        data=UserResponse(
            id=current_user.id,
            email=current_user.email,
            display_name=current_user.display_name,
            role=current_user.role,
            created_at=current_user.created_at,
        )
    )


@router.get("/verify", response_model=ResponseModel[dict])
async def verify_token(current_user: User = Depends(get_current_user)) -> ResponseModel[dict]:
    return ResponseModel(data={"valid": True, "sub": current_user.email, "role": current_user.role.value})
