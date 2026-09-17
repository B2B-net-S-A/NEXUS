"""Jednorazowe zamknięcie kolejki „Oczekuje" (pending verification).

Revision ID: 0325_pending_verification_retired
Revises: 0324_candidate_auto_match

Decyzja Artura 17.09.2026 („żadna bramka nie blokuje przepływu"): ruch na
„Zweryfikowany" nie ustawia już `verification_status='pending'`, a kolejka
akceptacji (trasy i ekrany) została usunięta. Wiersze, które zdążyły utknąć,
są ODBLOKOWANE (`active`), a te na etapie „Zweryfikowany" dodatkowo ZALICZONE
jak dawna ręczna akceptacja (pierwszy weryfikator = osoba, która przesunęła
kartę).

Logika jest ORM-owa (`record_accepted_verification`), więc migracja nie ma
własnego SQL-a: woła TEN SAM serwis co `entrypoint.sh`
(`app/services/pending_verification_promotion.py`) na połączeniu migracji
(sesja w SAVEPOINCIE, transakcję zatwierdza alembic). Wspólny marker
`pending_verification_promotion_2026_09_17` w `app_settings` + advisory lock →
drugi kanał kończy się natychmiast.

ORM czyta WSZYSTKIE kolumny modeli z kodu HEAD, więc na bazie, która nie jest
jeszcze na HEAD (kolejne migracje dokładają kolumny, np. 0326
`jobs.managed_in_nexus`), zapytania serwisu padałyby na nieistniejącej
kolumnie. Dlatego migracja uruchamia serwis TYLKO, gdy schemat bazy ma już
każdą tabelę i kolumnę modeli; w przeciwnym razie nic nie robi (bez znacznika),
a karty odblokowuje i zalicza blok w `entrypoint.sh`, który biegnie PO
`alembic upgrade heads`. Pilnuje `tests/test_pending_verification_retired.py`.
"""

from alembic import op

revision = "0325_pending_verification_retired"
down_revision = "0324_candidate_auto_match"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # env.py prowadzi migracje przez `AsyncConnection.run_sync`, więc jesteśmy
    # w greenlecie SQLAlchemy: `await_only` wykona asynchroniczny serwis na tym
    # samym połączeniu i w tej samej transakcji co reszta migracji.
    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession
    from sqlalchemy.util import await_only

    import app.models  # noqa: F401 — komplet mapperów przed pierwszym zapytaniem
    from app.services.pending_verification_promotion import (
        run_pending_verification_promotion,
    )

    bind = op.get_bind()
    missing = _missing_model_columns(bind)
    if missing:
        print(
            "0325: schemat bazy jeszcze nie na HEAD "
            f"(brak m.in. {', '.join(missing[:3])}) — promocję kart „Oczekuje” "
            "wykona entrypoint po `alembic upgrade heads`."
        )
        return

    async_connection = AsyncConnection._retrieve_proxy_for_target(bind)

    async def _promote() -> None:
        session = AsyncSession(
            bind=async_connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )
        try:
            await run_pending_verification_promotion(session)
            await session.commit()
        finally:
            await session.close()

    await_only(_promote())


def _missing_model_columns(bind) -> list[str]:
    """Tabele/kolumny modeli ORM, których baza jeszcze nie ma (``[]`` = HEAD)."""
    import sqlalchemy as sa

    import app.models  # noqa: F401
    from app.core.database import Base

    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    missing: list[str] = []
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            missing.append(table.name)
            continue
        present = {col["name"] for col in inspector.get_columns(table.name)}
        missing.extend(
            f"{table.name}.{col.name}"
            for col in table.columns
            if col.name not in present
        )
    return missing


def downgrade() -> None:
    # Stanu „pending" nie da się odtworzyć; marker zostaje, żeby ponowny
    # upgrade nie przeliczał niczego drugi raz.
    pass
