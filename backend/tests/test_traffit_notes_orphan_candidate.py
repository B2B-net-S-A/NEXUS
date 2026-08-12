"""Osierocona aktywność nie może wywracać promocji notatek.

`promote_notes` to JEDEN `INSERT ... SELECT`, a `notes.candidate_id` ma klucz
obcy. Aktywność wskazująca kandydata, którego w Nexusie nie ma, nie psuła więc
własnego wiersza — wywracała CAŁĄ instrukcję.

Skutek zmierzony na produkcji 12.08: `candidate_activities` raportowało
`errors: 1` przy `updated: 396 779`. Ponieważ błąd fazy wstrzymuje watermark,
`__full__` stał od **19 lipca** — pełny reconcile nie mógł się domknąć z powodu
jednej notatki, a sonda kompletności milczała o 396 tysiącach poprawnych wierszy.

Pominięcie takiego wiersza NIE jest cichą stratą w rozumieniu M2-IMP-01:
kandydata nie ma w bazie, więc notatki i tak nie da się zapisać — mówi to sam
klucz obcy. Aktywność źródłowa zostaje nietknięta, a dedup idzie po
`source_ref`, więc gdy kandydat zostanie kiedyś zaimportowany, najbliższy sync
dopisze notatkę. To jest samoleczące, w przeciwieństwie do przewracania fazy.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.services.traffit.importer import TraffitImporter


# Wspólny prefiks/znacznik, po którym teardown pozna SWOJE wiersze. Bez tego
# każde uruchomienie zostawia kandydatów, aktywności i notatki — testy nadal
# przechodzą (identyfikatory są losowe), ale osad w bazie deweloperskiej mści
# się gdzie indziej. Dziś zdarzyło się dokładnie to: inny test asertował
# `1` i dostał `100`, bo przebieg naprawczy zobaczył setkę zostawionych wierszy.
_TAG = "orphantest"
_LASTNAME = "OrphanTestFixture"


@pytest_asyncio.fixture
async def db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            # Kolejność ma znaczenie — notatki i aktywności trzymają FK.
            await session.rollback()
            await session.execute(
                text("DELETE FROM notes WHERE source_ref LIKE :p"),
                {"p": f"traffit:activity:{_TAG}%"},
            )
            await session.execute(
                text("DELETE FROM activities WHERE external_id LIKE :p"),
                {"p": f"{_TAG}%"},
            )
            await session.execute(
                text("DELETE FROM candidates WHERE lastname = :l"), {"l": _LASTNAME}
            )
            await session.commit()


async def _mk_candidate(db) -> int:
    row = await db.execute(
        text(
            "INSERT INTO candidates (name, lastname, created_at, updated_at) "
            "VALUES ('Jan', :l, NOW(), NOW()) RETURNING id"
        ),
        {"l": _LASTNAME},
    )
    return row.scalar_one()


async def _mk_activity(db, *, entity_id: int, ext: str) -> None:
    await db.execute(
        text(
            """
            INSERT INTO activities (
                external_id, external_source, action, entity_type, entity_id,
                details, created_at, updated_at
            ) VALUES (
                :ext, 'traffit', 'traffit:Notatka', 'candidate', :eid,
                CAST(:details AS jsonb), NOW(), NOW()
            )
            """
        ),
        {"ext": ext, "eid": entity_id, "details": '{"content": "tresc notatki"}'},
    )


async def _free_candidate_id(db) -> int:
    """Id, którego na pewno nie ma w `candidates`."""
    row = await db.execute(text("SELECT COALESCE(MAX(id), 0) + 100000 FROM candidates"))
    return int(row.scalar_one())


@pytest.mark.asyncio
async def test_orphan_activity_does_not_sink_the_whole_batch(db) -> None:
    """Najważniejszy strażnik: zdrowa notatka MUSI wejść mimo osieroconej obok.

    Bez filtra `EXISTS` obie przepadały — jeden nieistniejący kandydat kasował
    całą paczkę, bo to pojedyncza instrukcja INSERT.
    """
    ok_id = await _mk_candidate(db)
    orphan_id = await _free_candidate_id(db)
    ok_ext = f"{_TAG}-{uuid.uuid4().hex[:10]}"
    orphan_ext = f"{_TAG}-{uuid.uuid4().hex[:10]}"

    await _mk_activity(db, entity_id=ok_id, ext=ok_ext)
    await _mk_activity(db, entity_id=orphan_id, ext=orphan_ext)
    await db.commit()

    imp = TraffitImporter(object(), db, dry_run=False, batch_size=100)
    promoted = await imp.promote_notes(since=None)

    assert promoted >= 1, "zdrowa notatka nie została promowana"

    row = await db.execute(
        text("SELECT count(*) FROM notes WHERE source_ref = :r"),
        {"r": f"traffit:activity:{ok_ext}"},
    )
    assert row.scalar_one() == 1, "notatka istniejącego kandydata musi wejść"

    row = await db.execute(
        text("SELECT count(*) FROM notes WHERE source_ref = :r"),
        {"r": f"traffit:activity:{orphan_ext}"},
    )
    assert row.scalar_one() == 0, "notatka nieistniejącego kandydata nie ma prawa wejść"


@pytest.mark.asyncio
async def test_note_appears_once_the_candidate_exists(db) -> None:
    """Samoleczenie — to ono odróżnia pominięcie od utraty.

    Aktywność zostaje w bazie, dedup idzie po `source_ref`, więc gdy kandydat
    się pojawi, kolejny sync dopisze notatkę. Gdyby promocja kasowała albo
    trwale oznaczała pominięte wiersze, ta notatka nie wróciłaby nigdy.
    """
    orphan_id = await _free_candidate_id(db)
    ext = f"{_TAG}-{uuid.uuid4().hex[:10]}"
    await _mk_activity(db, entity_id=orphan_id, ext=ext)
    await db.commit()

    imp = TraffitImporter(object(), db, dry_run=False, batch_size=100)
    await imp.promote_notes(since=None)

    row = await db.execute(
        text("SELECT count(*) FROM notes WHERE source_ref = :r"),
        {"r": f"traffit:activity:{ext}"},
    )
    assert row.scalar_one() == 0

    # Kandydat pojawia się później — dokładnie tym id, którego brakowało.
    await db.execute(
        text(
            "INSERT INTO candidates (id, name, lastname, created_at, updated_at) "
            "VALUES (:i, 'Pozny', :l, NOW(), NOW())"
        ),
        {"i": orphan_id, "l": _LASTNAME},
    )
    await db.commit()

    await imp.promote_notes(since=None)

    row = await db.execute(
        text("SELECT count(*) FROM notes WHERE source_ref = :r"),
        {"r": f"traffit:activity:{ext}"},
    )
    assert row.scalar_one() == 1, (
        "notatka nie wróciła po zaimportowaniu kandydata — pominięcie zamieniło "
        "się w trwałą stratę"
    )
