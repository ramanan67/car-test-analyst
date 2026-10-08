"""
app/api/v1/routers/auth.py
Authentication endpoints: login, token refresh, user management.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user, require_role
from app.core.database import get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.models.enums import UserRole
from app.models.orm_models import User
from app.schemas.schemas import LoginRequest, TokenResponse, UserCreate, UserResponse

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    """
    Authenticate with corporate ID and password.
    Returns a JWT bearer token on success.
    """
    result = await db.execute(
        select(User).where(User.corporate_id == payload.corporate_id)
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid corporate ID or password.",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated. Contact your administrator.",
        )

    user.last_login_at = datetime.now(timezone.utc)
    await db.flush()

    from app.core.config import get_settings
    settings = get_settings()
    token = create_access_token(subject=user.user_id, role=user.role)

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register_user(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(UserRole.ADMIN)),
):
    """Register a new user (Admin only)."""
    existing = await db.execute(
        select(User).where(
            (User.corporate_id == payload.corporate_id) | (User.email == payload.email)
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Corporate ID or email already registered.",
        )

    user_data = payload.model_dump(exclude={"password"})
    user = User(**user_data, password_hash=hash_password(payload.password))
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """Return the currently authenticated user's profile."""
    return current_user
