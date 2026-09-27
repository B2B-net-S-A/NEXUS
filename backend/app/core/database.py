import json
from typing import Any, AsyncGenerator

from fastapi.encoders import jsonable_encoder
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, ORMExecuteState, Session

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


def _connect_args(url: str) -> dict[str, Any]:
    """`application_name` odróżnia połączenia NEXUSA w `pg_stat_activity`.

    Audyt F06: bez tego nie da się policzyć, ile ze 100 połączeń Postgresa
    zajmuje aplikacja, a ile backup, alembic czy ręczna sesja. Tylko asyncpg —
    inne sterowniki (testowe SQLite) nie znają `server_settings`.
    """
    if not url.startswith("postgresql+asyncpg://"):
        return {}
    return {"server_settings": {"application_name": "nexus-backend"}}


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=40,
    json_serializer=_json_serializer,
    connect_args=_connect_args(settings.DATABASE_URL),
    # Treść błędu SQLAlchemy (IntegrityError, DataError…) domyślnie niesie
    # `[parameters: …]` — e-maile, telefony, nazwiska i stawki kandydatów,
    # które idą do logów i Sentry. SQL zostaje, wartości nie.
    hide_parameters=True,
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


# ── Śledzenie niezatwierdzonych zapisów w sesji ─────────────────────────────
#
# `session.new/dirty/deleted` opisują wyłącznie zmiany ORM, które jeszcze NIE
# poszły do bazy. Po `flush()` są puste, choć INSERT/UPDATE siedzi już
# w otwartej transakcji; zapis surowym SQL-em (`text("UPDATE …")`) nie pojawia
# się w nich wcale. `release_idle_connection` robi `commit()`, więc bez tej
# flagi mógłby zatwierdzić cudzy, niedokończony zapis (reaudyt v2 14.09.2026,
# N02). Flaga jest konserwatywna: każde wykonanie, które NIE jest SELECT-em
# ORM/Core (także tekstowy SELECT), liczy się jako możliwy zapis — w najgorszym
# razie tracimy optymalizację, nigdy atomowość.
_UNCOMMITTED_WRITES_KEY = "nexus_uncommitted_writes"


@event.listens_for(Session, "after_flush")
def _mark_flushed_writes(session: Session, _flush_context: Any) -> None:
    session.info[_UNCOMMITTED_WRITES_KEY] = True


@event.listens_for(Session, "do_orm_execute")
def _mark_statement_writes(orm_execute_state: ORMExecuteState) -> None:
    if not orm_execute_state.is_select:
        orm_execute_state.session.info[_UNCOMMITTED_WRITES_KEY] = True


@event.listens_for(Session, "after_commit")
@event.listens_for(Session, "after_rollback")
def _clear_write_marker(session: Session) -> None:
    session.info.pop(_UNCOMMITTED_WRITES_KEY, None)


def session_has_uncommitted_writes(db: AsyncSession) -> bool:
    """Czy bieżąca transakcja sesji mogła już coś zapisać (flush albo DML)."""
    return bool(
        db.new or db.dirty or db.deleted or db.info.get(_UNCOMMITTED_WRITES_KEY)
    )


async def release_idle_connection(db: AsyncSession) -> bool:
    """Oddaj połączenie sesji do puli PRZED długim czekaniem — tylko po samych odczytach.

    Sesja requestu trzyma połączenie od pierwszego zapytania (np. auth) aż do
    zamknięcia po handlerze. Czekanie w tym czasie na cudze obliczenie cache'u
    albo na zewnętrzne AI zajmuje połączenie z puli, choć nic nie robi — przy
    zimnym kluczu i 50 oczekujących to 50 zajętych połączeń (reaudyt 14.09,
    R05). `commit()` bez zapisów kończy transakcję i zwalnia połączenie;
    kolejne zapytanie pobierze nowe.

    Kontrakt: wołać WYŁĄCZNIE po fazie tylko do odczytu. Helper i tak odmawia,
    gdy transakcja mogła coś zapisać — niezapisane zmiany ORM, wykonany
    `flush()` albo instrukcja inna niż SELECT (`session_has_uncommitted_writes`)
    — bo wcześniejszy commit zmieniłby atomowość operacji, gdyby handler padł
    później. `rollback()` odpada: wygasiłby wszystkie obiekty ORM (także
    `current_user`), a sięgnięcie po atrybut w async to `MissingGreenlet`.
    Zwraca, czy połączenie zostało zwolnione.
    """
    if session_has_uncommitted_writes(db):
        return False
    if not db.in_transaction():
        return False
    await db.commit()
    return True


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


def enforce_function_scope(app: Any, dependency: Any = None) -> int:
    """Ustaw ``scope="function"`` każdemu ``Depends(get_db)`` w trasach aplikacji.

    Runda 9 (R9-X1-2): od FastAPI 0.121 zależność z ``yield`` bez jawnego
    ``scope`` ma zasięg ``"request"`` — jej część po ``yield`` biegnie PO
    wysłaniu odpowiedzi i PO ``BackgroundTasks`` (``fastapi/routing.py``,
    ``request_response``). Skutki: 2xx mimo nieudanego commitu (FK, UNIQUE),
    zadanie w tle nie widzi wierszy z tego żądania, a połączenie wisi „idle in
    transaction” przez całe zadanie. Zasięg ``"function"`` zamyka sesję
    (commit/rollback) zaraz po handlerze i serializacji, przed odpowiedzią.

    Jedno miejsce zamiast ~1100 wywołań ``Depends(get_db, scope="function")``:
    klucz cache zależności zawiera zasięg, więc mieszanka dwóch zasięgów dałaby
    DWIE sesje w jednym żądaniu (``current_user`` z innej sesji niż handler).
    Wołane raz, po zarejestrowaniu wszystkich tras. Zwraca liczbę zmienionych
    zależności. Strumieniowe odpowiedzi nie mogą czytać sesji żądania w
    generatorze — otwierają własną (eksport kandydatów).
    """
    import inspect

    target = dependency or get_db
    changed = 0
    seen: set[int] = set()

    def walk(dependant: Any) -> None:
        nonlocal changed
        if id(dependant) in seen:
            return
        seen.add(id(dependant))
        call = inspect.unwrap(dependant.call) if dependant.call is not None else None
        parent_is_request_gen = (
            call is not None
            and (inspect.isgeneratorfunction(call) or inspect.isasyncgenfunction(call))
            and dependant.scope in (None, "request")
        )
        for sub in dependant.dependencies:
            if sub.call is target:
                if parent_is_request_gen:
                    # FastAPI odrzuca to przy deklaracji (DependencyScopeError);
                    # my ustawiamy zasięg po fakcie, więc pilnujemy tego sami.
                    raise RuntimeError(
                        "Zależność z yield o zasięgu 'request' nie może używać "
                        f"get_db o zasięgu 'function': {dependant.call!r}"
                    )
                if sub.scope != "function":
                    sub.scope = "function"
                    changed += 1
            walk(sub)

    for route in getattr(app, "routes", []):
        dependant = getattr(route, "dependant", None)
        if dependant is not None:
            walk(dependant)
    return changed
