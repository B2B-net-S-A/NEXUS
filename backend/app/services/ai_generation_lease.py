"""Cross-worker single flight with a short lease and compare-and-swap save."""

from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert

from app.models.ai_metering import AIGenerationLease


class GenerationBusy(Exception):
    pass


@asynccontextmanager
async def generation_lease(key: str):
    from app.core.database import AsyncSessionLocal

    token = str(uuid4())
    async with AsyncSessionLocal() as db:
        claimed = await db.scalar(
            insert(AIGenerationLease)
            .values(key=key, token=token, expires_at=func.now() + timedelta(minutes=15))
            .on_conflict_do_update(
                index_elements=[AIGenerationLease.key],
                set_={"token": token, "expires_at": func.now() + timedelta(minutes=15)},
                where=AIGenerationLease.expires_at <= func.now(),
            )
            .returning(AIGenerationLease.token)
        )
        await db.commit()
    if claimed != token:
        raise GenerationBusy(
            "Uzasadnienie jest już generowane. Spróbuj ponownie za chwilę."
        )
    try:
        yield token
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(AIGenerationLease).where(
                    AIGenerationLease.key == key, AIGenerationLease.token == token
                )
            )
            await db.commit()


async def lock_owned_lease(db, key: str, token: str) -> None:
    """Hold the lease row only for the final local write, never during AI."""
    owned = await db.scalar(
        select(AIGenerationLease.key)
        .where(
            AIGenerationLease.key == key,
            AIGenerationLease.token == token,
            AIGenerationLease.expires_at > func.now(),
        )
        .with_for_update()
    )
    if owned is None:
        raise GenerationBusy("Wygasła rezerwacja generowania. Ponów próbę.")
