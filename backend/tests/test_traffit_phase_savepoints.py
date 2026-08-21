"""Jeden zły wiersz kosztuje SIEBIE, nie całą fazę — dla sześciu pozostałych faz.

Poprawka przez SAVEPOINT została napisana dla `workflows` i `candidates`, a
pozostałych sześć nocnych faz — `clients`, `contacts`, `users`, `jobs`,
`talents`, `candidate_sources` — zostało z gołym `await self.db.rollback()`
w handlerze per rekord, przy jednym `commit()` po pętli. `rollback()` podnosi
SESJĘ, więc kasował wszystko, co ta faza zapisała do tej pory, a liczniki
`progress.inserted`/`updated` — zbijane PRZED rollbackiem — dalej raportowały te
rekordy jako zapisane. Na prodzie wyglądało to jak `processed: 400,
updated: 400, errors: 1` przy 149 wierszach faktycznie w bazie.

Stawka: rekrutacje, klienci, kontakty, konta rekruterów i atrybucja źródeł.
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.services.traffit.importer import TraffitImporter

BACKEND = Path(__file__).resolve().parents[1]
IMPORTER = BACKEND / "app/services/traffit/importer.py"

# Fazy, których per-rekordowy handler musi siedzieć za savepointem. Klucz =
# fragment instrukcji jednoznacznie identyfikujący zapis tej fazy.
_PER_ROW_WRITES = [
    "_UPSERT_CLIENT, payload",
    "_UPSERT_CONTACT, payload",
    "_UPSERT_USER, payload",
    "_UPSERT_JOB, params",
    "_UPSERT_TALENT_POOL, payload",
    "UPDATE candidates SET tags=CAST(:tags AS JSONB), ",
]


@pytest.mark.parametrize("needle", _PER_ROW_WRITES)
def test_per_row_write_sits_in_a_savepoint(needle: str) -> None:
    """Sprawdzane na źródle, bo to własność KAŻDEJ z sześciu faz.

    Test wykonaniowy pokryje tę fazę, do której akurat go napiszemy (niżej —
    `clients`); pozostałe pięć zostałoby bez dozoru, a defekt jest dosłownie
    ten sam sześć razy.
    """
    source = IMPORTER.read_text(encoding="utf-8")
    at = source.index(needle)
    window = source[max(0, at - 1500) : at]
    assert "begin_nested()" in window, (
        f"zapis fazy przy `{needle}` musi siedzieć w savepoincie — bez niego "
        "błąd jednego wiersza przewraca transakcję, a handler ratuje się "
        "rollbackiem SESJI i wyrzuca całą niezacommitowaną paczkę"
    )


def test_no_unguarded_session_rollback_in_a_per_row_handler() -> None:
    """`db.rollback()` w handlerze per rekord musi przechodzić przez decyzję.

    `needs_session_rollback` odróżnia błąd INSTRUKCJI (savepoint już go cofnął,
    sesji ruszać nie wolno) od utraty POŁĄCZENIA (savepoint nie ma dokąd się
    cofnąć, sesję trzeba podnieść). Goły rollback nie odróżnia niczego.
    """
    source = IMPORTER.read_text(encoding="utf-8")
    lines = source.splitlines()
    offenders: list[str] = []
    for idx, line in enumerate(lines):
        if not re.match(r"^\s+await self\.db\.rollback\(\)\s*$", line):
            continue
        # Poprzedzająca gałąź decyzyjna albo świadomy handler całej operacji.
        window = "\n".join(lines[max(0, idx - 6) : idx])
        if "needs_session_rollback" in window:
            continue
        offenders.append(f"{idx + 1}: {line.strip()}")
    for needle in _PER_ROW_WRITES:
        at = source.index(needle)
        line_no = source[:at].count("\n") + 1
        for entry in offenders:
            bad_line = int(entry.split(":", 1)[0])
            assert not (line_no < bad_line < line_no + 60), (
                f"faza przy `{needle}` wciąż podnosi sesję bezwarunkowo "
                f"({entry}) — to jest ten rollback, który kasował paczkę"
            )


class _FakePaginator:
    """Minimalny zamiennik `TraffitClient` dla jednej fazy."""

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    async def total_count(self, path: str) -> int:  # noqa: ARG002
        return len(self._rows)

    async def get_paginated(self, path, page_size=100, **kwargs):  # noqa: ARG002
        for row in self._rows:
            yield row


@pytest.mark.asyncio
async def test_one_poisoned_client_does_not_discard_the_rows_before_it() -> None:
    """Dowód wykonaniem, na prawdziwej fazie `import_clients`.

    Trzeci wiersz ma nazwę dłuższą niż kolumna, więc zapis go odrzuca. Przed
    poprawką `db.rollback()` kasował dwa poprawne wiersze zapisane wcześniej,
    a `progress.inserted` dalej pokazywał 2.
    """
    url = os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set")

    marker = "savepoint-regression"
    rows = [
        {"id": 900001, "name": f"{marker} A"},
        {"id": 900002, "name": f"{marker} B"},
        # `clients.external_id` to varchar(100), a mapper przepisuje `id` bez
        # ucinania — ten wiersz MUSI zostać odrzucony przez bazę.
        {"id": "9" * 200, "name": f"{marker} trucizna"},
    ]

    engine = create_async_engine(url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as db:
            importer = TraffitImporter(_FakePaginator(rows), db)  # type: ignore[arg-type]
            progress = await importer.import_clients()

            stored = (
                await db.execute(
                    text(
                        "SELECT external_id FROM clients "
                        "WHERE external_source='traffit' "
                        "AND external_id IN ('900001','900002')"
                    )
                )
            ).fetchall()
            surviving = {r[0] for r in stored}

            # Sprzątanie zanim cokolwiek zaasertujemy — inaczej nieudany test
            # zostawia po sobie wiersze, które psują następny bieg.
            await db.execute(
                text(
                    "DELETE FROM clients WHERE external_source='traffit' "
                    "AND external_id IN ('900001','900002','900003')"
                )
            )
            await db.commit()

        assert progress.errors == 1, (
            "zatruty wiersz musi zostać zgłoszony jako błąd tej jednej pozycji"
        )
        assert surviving == {"900001", "900002"}, (
            "dwa poprawne wiersze muszą przetrwać commit fazy — to jest cała "
            f"istota savepointu; w bazie zostało {surviving!r}"
        )
        assert progress.inserted + progress.updated == 2, (
            "liczniki muszą opisywać ZAPISY, nie PRÓBY — inkrementacja przed "
            "utrzymaniem się savepointu jest tym, co kazało prodowi raportować "
            f"zapisane rekordy, których nie było (dostałem {progress.as_dict()})"
        )
    finally:
        await engine.dispose()
        await asyncio.sleep(0)
