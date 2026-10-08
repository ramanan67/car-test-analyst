"""
app/core/database.py
Async SQLAlchemy engine and session factory.
"""
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.models.orm_models import Base

settings = get_settings()

_engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    pool_timeout=settings.DATABASE_POOL_TIMEOUT,
    echo=settings.DEBUG,
    future=True,
)

_async_session_factory = async_sessionmaker(
    bind=_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields an async DB session per request."""
    async with _async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """Context-manager version for use outside of FastAPI request scope."""
    async with _async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_all_tables() -> None:
    """Create all ORM-mapped tables (development / testing only)."""
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_all_tables() -> None:
    """Drop all ORM-mapped tables (testing teardown only)."""
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
