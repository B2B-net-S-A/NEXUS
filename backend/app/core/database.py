import json
from typing import Any, AsyncGenerator

from fastapi.encoders import jsonable_encoder
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


def _json_serializer(value: Any) -> str:
    """Serializer for JSON / JSONB columns.

    Routes values through FastAPI's ``jsonable_encoder`` before ``json.dumps``
    so non-native types serialize instead of raising
    ``TypeError: Object of type date is not JSON serializable``.

    The trigger in the wild: editing a job that has a ``deadline`` sends a
    ``date`` into ``JobUpdate``; ``update_job`` then writes the raw update dict
    into ``Activity.details`` (JSONB). With the stdlib default serializer the
    ``date`` blew up the flush, killing the request with a non-CORS 503 that
    the frontend surfaced as "Błąd podczas zapisywania". ``jsonable_encoder``
    also covers ``datetime``, ``Decimal``, ``UUID`` and ``Enum``, hardening
    every JSONB write app-wide, not just this one call site.
    """
    return json.dumps(jsonable_encoder(value))


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=40,
    json_serializer=_json_serializer,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields a database session per request."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
