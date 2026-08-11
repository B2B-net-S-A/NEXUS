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
