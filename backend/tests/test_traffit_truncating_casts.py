"""Import Traffita nie tnie po cichu i nie gubi paczki przez jeden wiersz.

Dwie własności, które trzymają się tylko razem:

* `CAST(:p AS varchar(n))` UCINA wartość do n znaków. Dopiero przypisanie do
  kolumny `varchar(n)` odrzuca za długą. Ucięty `filename` jest kosmetyczny,
  ale ucięty `storage_key` wskazuje na plik, którego nie da się już pobrać, a
  ucięty `external_id` może scalić dwa różne rekordy źródłowe przez
  `ON CONFLICT (external_source, external_id)`. Dwa casty były wręcz KRÓTSZE od
  swoich kolumn (`varchar(255)` przy kolumnie `varchar(500)`), więc niszczyły
  dane, które schemat przyjąłby w całości — zmierzone: 29 znaków z 284.

* Sama zamiana na `text` byłaby jednak pogorszeniem, gdyby została sama:
  w PostgreSQL błąd instrukcji przewraca CAŁĄ transakcję, a handler ratował się
  `db.rollback()` — rollbackiem SESJI, który wyrzuca wszystko zapisane od
  ostatniego commita. Jeden za długi rekord kosztowałby wtedy setki cudzych.
  Stąd savepoint: wiersz ma kosztować siebie.
"""

import asyncio
import re
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

BACKEND = Path(__file__).resolve().parents[1]
IMPORTER = BACKEND / "app/services/traffit/importer.py"


def test_no_bind_parameter_is_cast_to_a_length_bounded_type():
    """Sprawdzane na źródle, bo to własność KAŻDEJ instrukcji, nie jednej ścieżki.

    Test wykonaniowy pokryłby ten upsert, do którego akurat go napiszemy;
    dwadzieścia kilka pozostałych instrukcji zostałoby bez dozoru.
    """

    source = IMPORTER.read_text(encoding="utf-8")
    offenders = re.findall(r"CAST\(:\w+ AS (?:var)?char\(\d+\)\)", source)

    assert not offenders, (
        "rzutowanie parametru na typ z ograniczoną długością ucina po cichu; "
        f"użyj `text` i pozwól kolumnie odrzucić za długą wartość: {offenders}"
    )


def test_row_write_sits_in_a_savepoint():
    """Bez savepointa błąd wiersza kosztuje paczkę — patrz docstring modułu."""

    source = IMPORTER.read_text(encoding="utf-8")
    upsert_at = source.index("_UPSERT_CANDIDATE, params")
    window = source[max(0, upsert_at - 4000) : upsert_at]

    assert "begin_nested()" in window, (
        "zapis kandydata musi siedzieć w savepoincie, inaczej jeden zły wiersz "
        "przewraca transakcję i handler wyrzuca całą niezacommitowaną paczkę"
    )


@pytest.mark.asyncio
async def test_overlong_value_costs_its_own_row_not_the_batch():
    """Dowód wykonaniem: savepoint izoluje błąd, sesja zostaje zdatna do użytku."""

    import os

    url = os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set")

    engine = create_async_engine(url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as db:
            await db.begin()
            try:
                # Wiersz, który się nie mieści — `name` to varchar(100).
                try:
                    async with db.begin_nested():
                        await db.execute(
                            text(
                                "INSERT INTO candidates "
                                "(name, lastname, created_at, updated_at) "
                                "VALUES (CAST(:n AS text), 'T', NOW(), NOW())"
                            ),
                            {"n": "x" * 300},
                        )
                except Exception:
                    pass  # savepoint cofnięty — o to chodzi
                else:  # pragma: no cover - obrona przed cichą zmianą schematu
                    pytest.fail("za długa wartość powinna zostać odrzucona")

                # Sedno: następny kandydat MUSI się zapisać.
                inserted = await db.scalar(
                    text(
                        "INSERT INTO candidates "
                        "(name, lastname, created_at, updated_at) "
                        "VALUES ('Kolejny', 'Kandydat', NOW(), NOW()) RETURNING id"
                    )
                )
                assert inserted is not None, (
                    "po błędzie wiersza sesja musi zostać zdatna do użytku — "
                    "inaczej jeden zły rekord kładzie resztę paczki"
                )
            finally:
                await db.rollback()
    finally:
        await engine.dispose()
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_session_recovers_when_the_connection_dies_not_just_the_statement():
    """Savepoint nie cofnie się, jeśli nie ma czego pytać.

    Pierwsza wersja bramki rollbackowała sesję tylko wtedy, gdy błąd przyszedł
    ze ścieżki commita — bo „awaria zapisu jest już cofnięta przez savepoint,
    więc transakcja zewnętrzna żyje". To prawda dla błędu INSTRUKCJI i fałsz dla
    utraty POŁĄCZENIA: gdy backend Postgresa znika (restart, failover,
    `idle_in_transaction_session_timeout`, reaper), `ROLLBACK TO SAVEPOINT` nie
    ma dokąd pójść, sesja wpada w `PendingRollbackError`, a jedynym, co ją
    podnosi, jest `rollback()` — którego warunek właśnie pomijał.

    Kosztowało to nie jedną paczkę, tylko RESZTĘ fazy: każdy kolejny wiersz padał
    i `import_candidates` rzucało zamiast zwrócić `PhaseProgress`.

    `is_active` i `in_transaction()` raportują to samo przy martwym i zdrowym
    połączeniu — dyskryminatorem jest `connection_invalidated`.
    """

    import os

    import asyncpg

    url = os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set")

    raw_url = url.replace("postgresql+asyncpg://", "postgresql://")
    engine = create_async_engine(url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as db:
            await db.begin()
            pid = await db.scalar(text("SELECT pg_backend_pid()"))

            killer = await asyncpg.connect(raw_url)
            try:
                await killer.execute("SELECT pg_terminate_backend($1)", pid)
            finally:
                await killer.close()

            invalidated = None
            try:
                async with db.begin_nested():
                    await db.execute(text("SELECT 1"))
            except Exception as exc:  # noqa: BLE001 - to jest badany przypadek
                invalidated = getattr(exc, "connection_invalidated", False)

            assert invalidated is True, (
                "utrata połączenia musi być rozpoznawalna po `connection_invalidated` "
                f"— dostałem {invalidated!r}; bez tego handler nie wie, że musi "
                "podnieść sesję"
            )

            await db.rollback()
            assert await db.scalar(text("SELECT 1")) == 1, (
                "po rollbacku sesja musi znów działać — inaczej jeden blip "
                "połączenia kosztuje resztę fazy importu"
            )
    finally:
        await engine.dispose()
        await asyncio.sleep(0)


def test_rollback_decision_covers_connection_loss_not_only_the_commit_path():
    """Decyzja jest osobną funkcją właśnie po to, żeby dało się ją tak przetestować.

    Pierwsza wersja tego testu asertowała obecność stringu `connection_invalidated`
    w źródle — i przechodziła po cofnięciu poprawki, bo string został w linii obok.
    Test, który nie pada po usunięciu pilnowanej własności, nie jest testem.
    """

    from sqlalchemy.exc import DBAPIError

    from app.services.traffit.importer import needs_session_rollback

    statement_error = DBAPIError("stmt", None, Exception("boom"))
    statement_error.connection_invalidated = False
    connection_error = DBAPIError("stmt", None, Exception("gone"))
    connection_error.connection_invalidated = True

    # Błąd instrukcji: savepoint już go cofnął, sesji ruszać NIE wolno —
    # rollback wyrzuciłby całą niezacommitowaną paczkę.
    assert needs_session_rollback(statement_error, past_savepoint=False) is False

    # Utrata połączenia: savepoint nie miał się jak wycofać, tylko rollback
    # podnosi sesję. Bez tego padnie każdy kolejny wiersz fazy.
    assert needs_session_rollback(connection_error, past_savepoint=False) is True

    # Awaria ścieżki commita: savepoint zamknięty, rollback konieczny niezależnie
    # od rodzaju błędu.
    assert needs_session_rollback(statement_error, past_savepoint=True) is True

    # Wyjątek bez atrybutu (nie-DBAPI) nie może wywrócić decyzji.
    assert needs_session_rollback(ValueError("x"), past_savepoint=False) is False
