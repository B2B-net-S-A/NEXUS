"""Rekrutacja bez znanego klienta trafia do sieroty, nie do kosza.

Zaobserwowane na prodzie 2026-08-11, w pełnym przebiegu: faza `jobs` kończy
się z `skipped: 28`, a wszystkie próbki brzmią `skip job ext=<id>: no client
mapping`. `external_id` są bardzo niskie (38, 57, 59, 65, 71, 76, 92–95 przy
4121 rekordach) — to najstarsze rekrutacje, których klient został w Traffitcie
skasowany albo nigdy nie był przypisany. Liczniki klientów się zgadzają
(148 = 148), więc to nie jest błąd mapowania po naszej stronie.

`jobs.client_id` ma NOT NULL od migracji 0120, więc bezklientowy INSERT
faktycznie by się wywalił — ale z tego wynika tylko tyle, że trzeba podstawić
JAKIEGOŚ klienta, a nie że wiersz należy wyrzucić.

Prawdziwy koszt jest niewidoczny w liczniku `jobs`:
`traffit_recruitment_history_to_stage` zwraca None, gdy `job_id` nie ma w
mapie, więc razem z rekrutacją przepadała **cała historia kandydatów**, którzy
przez nią przechodzili. Faza `pipelines` liczyła to jako `skipped` i nikt
nigdy nie powiązał jednego z drugim.

Wzorzec sieroty nie jest tu nowy — kontakty robią to od zawsze
(`import_contacts` → `_ensure_orphan_client`), co opisuje nagłówek
`importer.py`. Ta sama sytuacja miała dwa różne rozstrzygnięcia zależnie od
fazy; to była asymetria, nie decyzja.

Testy idą przez REALNEGO Postgresa i przez prawdziwe metody fazy, bo cała
zmiana dotyczy zachowania wobec ograniczenia bazy — atrapa sesji
udowodniłaby wyłącznie samą siebie.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.services.traffit.importer import ORPHAN_CLIENT_NAME, TraffitImporter


@pytest_asyncio.fixture
async def db():
    async with AsyncSessionLocal() as session:
        yield session


class _JobsTraffit:
    """Serwuje zadany zestaw rekrutacji z `/recruitments/`."""

    def __init__(self, recruitments: list[dict]):
        self.recruitments = recruitments

    async def total_count(self, path):
        return len(self.recruitments)

    async def get_paginated(self, path, *, page_size=100, filter_=None, **kw):
        for r in self.recruitments:
            yield r


def _recruitment(ext: str, *, client: dict | None, title: str = "Backend Dev") -> dict:
    raw = {"id": ext, "name": title, "status": "open"}
    if client is not None:
        raw["client"] = client
    return raw


async def _job_row(db, ext: str):
    row = await db.execute(
        text(
            """
            SELECT j.id, c.name
            FROM jobs j JOIN clients c ON c.id = j.client_id
            WHERE j.external_id = :e AND j.external_source = 'traffit'
            """
        ),
        {"e": ext},
    )
    return row.fetchone()


async def _mk_client(db, *, ext: str) -> int:
    row = await db.execute(
        text(
            """
            INSERT INTO clients (
                name, status, external_id, external_source,
                nda_signed, created_at, updated_at
            ) VALUES (
                :n, CAST('active' AS clientstatus), :e, 'traffit',
                false, NOW(), NOW()
            ) RETURNING id
            """
        ),
        {"n": f"Klient {ext}", "e": ext},
    )
    return row.scalar_one()


@pytest.mark.asyncio
async def test_recruitment_without_a_client_is_imported_under_the_orphan(db) -> None:
    """Sedno: wiersz ma powstać, nie zniknąć."""
    ext = f"o{uuid.uuid4().hex[:10]}"
    traffit = _JobsTraffit([_recruitment(ext, client=None)])

    progress = await TraffitImporter(
        traffit, db, dry_run=False, batch_size=10
    ).import_jobs()

    assert progress.errors == 0
    assert progress.unresolved_client == 1
    # NIE `skipped` — to wiersz ZAPISANY, tylko z zastępczym klientem.
    # Zlanie obu liczników mówiłoby operatorowi coś przeciwnego do prawdy.
    assert progress.skipped == 0

    row = await _job_row(db, ext)
    assert row is not None, "rekrutacja nadal przepada"
    assert row[1] == ORPHAN_CLIENT_NAME


@pytest.mark.asyncio
async def test_recruitment_pointing_at_an_unknown_client_also_lands(db) -> None:
    """Drugi realny przypadek z produkcji: klient JEST w payloadzie, ale został
    w Traffitcie skasowany, więc nie ma go w feedzie `/clients/` ani u nas."""
    ext = f"o{uuid.uuid4().hex[:10]}"
    traffit = _JobsTraffit([_recruitment(ext, client={"id": "nie-istnieje-9999"})])

    progress = await TraffitImporter(
        traffit, db, dry_run=False, batch_size=10
    ).import_jobs()

    assert progress.unresolved_client == 1
    row = await _job_row(db, ext)
    assert row is not None
    assert row[1] == ORPHAN_CLIENT_NAME


@pytest.mark.asyncio
async def test_recruitment_with_a_known_client_is_untouched(db) -> None:
    """Strażnik przed nadgorliwością: sierota nie może przejąć rekrutacji,
    która ma poprawnego klienta."""
    cext = f"c{uuid.uuid4().hex[:8]}"
    await _mk_client(db, ext=cext)
    await db.commit()

    ext = f"o{uuid.uuid4().hex[:10]}"
    traffit = _JobsTraffit([_recruitment(ext, client={"id": cext})])

    progress = await TraffitImporter(
        traffit, db, dry_run=False, batch_size=10
    ).import_jobs()

    assert progress.unresolved_client == 0
    row = await _job_row(db, ext)
    assert row is not None
    assert row[1] == f"Klient {cext}"


@pytest.mark.asyncio
async def test_orphan_never_takes_a_client_away_from_an_existing_job(db) -> None:
    """Sierota obsługuje BRAK przypisania — nie odbiera istniejącego.

    Regresja wprowadzona razem z tą poprawką i złapana w review. UPSERT robi
    `client_id = COALESCE(EXCLUDED.client_id, jobs.client_id)`. Dopóki
    bezklientowe rekrutacje były pomijane, ta gałąź nigdy się nie wykonywała.
    Odkąd zawsze podajemy niepustego klienta, COALESCE zawsze bierze wartość
    przychodzącą — więc rekrutacja zaimportowana kiedyś z realnym klientem
    zostałaby po cichu przeniesiona do sierot, gdyby jej klient wypadł z mapy.

    Realny scenariusz to nie skasowanie klienta (FK na to nie pozwala), tylko
    utrata MAPOWANIA: wyczyszczony `external_id`, zmieniony `external_source`,
    scalone duplikaty. Klient dalej istnieje i jest poprawny.
    """
    cext = f"c{uuid.uuid4().hex[:8]}"
    client_id = await _mk_client(db, ext=cext)
    await db.commit()

    ext = f"o{uuid.uuid4().hex[:10]}"
    await TraffitImporter(
        _JobsTraffit([_recruitment(ext, client={"id": cext})]),
        db,
        dry_run=False,
        batch_size=10,
    ).import_jobs()
    assert (await _job_row(db, ext))[1] == f"Klient {cext}"

    # Mapowanie znika (ktoś wyczyścił external_id), sam klient zostaje.
    await db.execute(
        text("UPDATE clients SET external_id = NULL WHERE id = :i"), {"i": client_id}
    )
    await db.commit()

    progress = await TraffitImporter(
        _JobsTraffit([_recruitment(ext, client={"id": cext})]),
        db,
        dry_run=False,
        batch_size=10,
    ).import_jobs()

    # `orphaned` liczy to, CO PRZYSZŁO z Traffita (rekrutacja bez
    # rozwiązywalnego klienta), a nie to, co z tym zrobiliśmy — więc rośnie
    # także tutaj. Dowodem, że sierota niczego nie przejęła, jest przypisanie
    # w bazie, nie licznik.
    assert progress.unresolved_client == 1
    assert (await _job_row(db, ext))[1] == f"Klient {cext}", (
        "sierota przejęła rekrutację, która miała już poprawnego klienta"
    )


@pytest.mark.asyncio
async def test_orphan_client_is_created_lazily(db, monkeypatch) -> None:
    """Instalacja, w której każda rekrutacja ma klienta, nie powinna dostać
    pustego `__traffit_orphans` w liście klientów.

    Sprawdzane przez podmianę `_ensure_orphan_client` na wybuchową, a nie przez
    skasowanie sieroty i sprawdzenie, czy wróciła: sierota jest globalna dla
    bazy, więc wersja kasująca przewracała się na kluczu obcym o rekrutacje
    zostawione przez inne testy, a nawet gdyby przeszła — dowodziłaby stanu
    bazy, nie zachowania kodu.
    """
    cext = f"c{uuid.uuid4().hex[:8]}"
    await _mk_client(db, ext=cext)
    await db.commit()

    imp = TraffitImporter(
        _JobsTraffit([_recruitment(f"o{uuid.uuid4().hex[:10]}", client={"id": cext})]),
        db,
        dry_run=False,
        batch_size=10,
    )

    async def _boom():
        raise AssertionError("sierota zakładana mimo braku sierot")

    monkeypatch.setattr(imp, "_ensure_orphan_client", _boom)

    progress = await imp.import_jobs()

    assert progress.unresolved_client == 0
    assert progress.errors == 0


@pytest.mark.asyncio
async def test_reimport_does_not_duplicate_or_multiply_the_orphan(db) -> None:
    """Faza chodzi przy każdym syncu — musi być idempotentna, inaczej nocna
    delta mnożyłaby klientów `__traffit_orphans` albo wiersze `jobs`."""
    ext = f"o{uuid.uuid4().hex[:10]}"
    traffit = _JobsTraffit([_recruitment(ext, client=None)])

    for _ in range(2):
        await TraffitImporter(traffit, db, dry_run=False, batch_size=10).import_jobs()

    jobs = await db.execute(
        text("SELECT count(*) FROM jobs WHERE external_id = :e"), {"e": ext}
    )
    assert jobs.scalar_one() == 1

    # Licznik jest STABILNY między biegami — drugi przebieg nadal raportuje tę
    # sierotę. Gdyby liczył tylko pierwsze przypisanie, `/sync/status` po
    # pierwszym biegu pokazywałby 0 przy rekrutacjach wciąż siedzących u
    # zastępczego klienta: zielona liczba nad realną luką.
    third = await TraffitImporter(
        traffit, db, dry_run=False, batch_size=10
    ).import_jobs()
    assert third.unresolved_client == 1

    orphans = await db.execute(
        text("SELECT count(*) FROM clients WHERE name = :n"), {"n": ORPHAN_CLIENT_NAME}
    )
    assert orphans.scalar_one() == 1


@pytest.mark.asyncio
async def test_unresolved_client_count_reaches_sync_status(db) -> None:
    """Licznik ma być widoczny operatorowi — inaczej sierota jest cichym
    pomijaniem pod inną nazwą."""
    from app.tasks.traffit_sync import _summarize

    ext = f"o{uuid.uuid4().hex[:10]}"
    progress = await TraffitImporter(
        _JobsTraffit([_recruitment(ext, client=None)]),
        db,
        dry_run=False,
        batch_size=10,
    ).import_jobs()

    assert (
        _summarize(progress.as_dict())["unresolved_client"]
        == progress.unresolved_client
        == 1
    )
