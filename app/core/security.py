"""
app/core/security.py
Password hashing, JWT token creation/verification, and RBAC helpers.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings
from app.models.enums import UserRole

settings = get_settings()

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ---------------------------------------------------------------------------
# Password utilities
# ---------------------------------------------------------------------------

def hash_password(plain: str) -> str:
    """Return bcrypt hash of the plain-text password."""
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plain-text password against a stored bcrypt hash."""
    return _pwd_context.verify(plain, hashed)


# ---------------------------------------------------------------------------
# JWT utilities
# ---------------------------------------------------------------------------

def create_access_token(
    subject: str | uuid.UUID,
    role: UserRole,
    extra_claims: Optional[Dict[str, Any]] = None,
) -> str:
    """Create a signed JWT access token."""
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload: Dict[str, Any] = {
        "sub": str(subject),
        "role": role.value,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "jti": str(uuid.uuid4()),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> Dict[str, Any]:
    """
    Decode and validate a JWT access token.
    Raises jose.JWTError on invalid or expired tokens.
    """
    return jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )


# ---------------------------------------------------------------------------
# RBAC role hierarchy
# ---------------------------------------------------------------------------

_ROLE_HIERARCHY: Dict[UserRole, int] = {
    UserRole.VIEWER:        0,
    UserRole.TECHNICIAN:    1,
    UserRole.TEST_ANALYST:  2,
    UserRole.LEAD_ENGINEER: 3,
    UserRole.ADMIN:         4,
}


def role_has_permission(user_role: UserRole, minimum_role: UserRole) -> bool:
    """
    Return True if user_role meets or exceeds the minimum required role.
    """
    return _ROLE_HIERARCHY.get(user_role, -1) >= _ROLE_HIERARCHY.get(minimum_role, 999)
