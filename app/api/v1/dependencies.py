"""
app/api/v1/dependencies.py
FastAPI shared dependencies: authentication, RBAC, common DB helpers.
"""
from __future__ import annotations

from functools import partial
from typing import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_access_token, role_has_permission
from app.models.enums import UserRole
from app.models.orm_models import User

_bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    FastAPI dependency that extracts and validates the JWT bearer token,
    then loads and returns the authenticated User from the database.
    Raises HTTP 401 for invalid/expired tokens and HTTP 403 for inactive users.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired authentication token.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(credentials.credentials)
        user_id: str = payload.get("sub")
        if not user_id:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    result = await db.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated.",
        )
    return user


def require_role(minimum_role: UserRole) -> Callable:
    """
    FastAPI dependency factory. Returns a dependency that enforces a
    minimum RBAC role. Usage: Depends(require_role(UserRole.LEAD_ENGINEER))
    """
    async def _check(current_user: User = Depends(get_current_user)) -> User:
        if not role_has_permission(current_user.role, minimum_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Minimum required role: {minimum_role.value}.",
            )
        return current_user
    return _check
