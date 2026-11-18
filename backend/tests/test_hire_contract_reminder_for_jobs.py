"""„Brak umowy w Kontraktach” dla wielu Tablic naraz (`missing_contract_ids_for_jobs`)
i rodziny klientów hurtem (`job_client_families`).

Umowa u klienta jednej rekrutacji (albo u jego scalonego rekordu) nie może
zdjąć plakietki w rekrutacji innego klienta. Osoby i firmy są zmyślone.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from sqlalchemy import event

import app.models  # noqa: F401  (rejestracja wszystkich mapperów)
from app.core.database import AsyncSessionLocal, engine
from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus
from app.services.employment_marker import job_client_families, job_client_family
from app.services.hire_contract_reminder import (
    MISSING_CONTRACT_HIRE_DAYS,
    missing_contract_ids,
    missing_contract_ids_for_jobs,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@contextmanager
def count_statements():
    seen: list[str] = []

    def _on(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _on)
    try:
        yield seen
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _on)


async def _seed() -> dict:
    """Klient A z duplikatem scalonym w A, klient B, klient C bez nikogo.

    * ``at_dup`` — umowa u duplikatu A (liczy się dla A),
    * ``at_b`` — umowa u B,
    * ``void_a`` — tylko unieważniona umowa u A,
    * ``nobody`` — bez umów.
    """
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client_a = Client(name=f"RodzinaA-{tag}")
        client_b = Client(name=f"RodzinaB-{tag}")
        client_c = Client(name=f"RodzinaC-{tag}")
        db.add_all([client_a, client_b, client_c])
        await db.flush()
        duplicate = Client(
            name=f"RodzinaA-dup-{tag}", merged_into_client_id=client_a.id
        )
        people = [
            Candidate(
                name="Jan",
                lastname=f"{label}-{tag}",
                email=f"{label}-{tag}@example.com",
            )
            for label in ("atdup", "atb", "voida", "nobody")
        ]
        db.add_all([duplicate, *people])
        await db.flush()
        at_dup, at_b, void_a, nobody = (p.id for p in people)
        start = business_today() - timedelta(days=10)
        db.add_all(
            [
                Contract(
                    candidate_id=at_dup,
                    client_id=duplicate.id,
                    start_date=start,
                    status=ContractStatus.active,
                ),
                Contract(
                    candidate_id=at_b,
                    client_id=client_b.id,
                    start_date=start,
                    status=ContractStatus.draft,
                ),
                Contract(
                    candidate_id=void_a,
                    client_id=client_a.id,
                    start_date=start,
                    status=ContractStatus.void,
                ),
            ]
        )
        await db.commit()
        return {
            "a": client_a.id,
            "dup": duplicate.id,
            "b": client_b.id,
            "c": client_c.id,
            "at_dup": at_dup,
            "at_b": at_b,
            "void_a": void_a,
            "nobody": nobody,
        }


def _boards(w: dict) -> dict:
    recent = _now() - timedelta(days=3)
    old = _now() - timedelta(days=MISSING_CONTRACT_HIRE_DAYS + 5)
    everyone = [(w[k], recent) for k in ("at_dup", "at_b", "void_a", "nobody")]
    # Klucze to umowne id rekrutacji — funkcja nie czyta tabeli `jobs`.
    return {
        101: (w["a"], everyone),
        102: (w["b"], everyone),
        103: (w["dup"], everyone),
        104: (w["c"], [(w["nobody"], old), (w["at_b"], None)]),
        105: (None, everyone),
    }


async def test_each_board_gets_exactly_what_the_single_call_gives():
    w = await _seed()
    boards = _boards(w)
    async with AsyncSessionLocal() as db:
        bulk = await missing_contract_ids_for_jobs(db, boards=boards, now=_now())
        assert set(bulk) == set(boards)
        for job_id, (client_id, hired) in boards.items():
            single = await missing_contract_ids(
                db, job_client_id=client_id, hired=hired, now=_now()
            )
            assert bulk[job_id] == single, job_id
    # Umowa u duplikatu liczy się w całej rodzinie A, ale nie u B.
    assert bulk[101] == {w["at_b"], w["void_a"], w["nobody"]}
    assert bulk[103] == bulk[101]
    assert bulk[102] == {w["at_dup"], w["void_a"], w["nobody"]}
    # Stare zatrudnienie i karta bez daty nie dają plakietki; bez klienta — nic.
    assert bulk[104] == set()
    assert bulk[105] == set()


async def test_families_from_the_caller_are_reused():
    w = await _seed()
    async with AsyncSessionLocal() as db:
        families = await job_client_families(db, [w["a"]])
        with count_statements() as seen:
            out = await missing_contract_ids_for_jobs(
                db,
                boards={1: (w["a"], [(w["at_dup"], _now()), (w["nobody"], _now())])},
                now=_now(),
                families=families,
            )
    assert out == {1: {w["nobody"]}}
    # Same umowy — rodziny nie liczymy drugi raz.
    assert len(seen) == 1, seen


async def test_job_client_families_match_the_single_call():
    w = await _seed()
    keys = [w["a"], w["dup"], w["b"], None]
    async with AsyncSessionLocal() as db:
        bulk = await job_client_families(db, keys)
        assert set(bulk) == set(keys)
        for key in keys:
            assert bulk[key] == await job_client_family(db, key), key
        with count_statements() as one:
            await job_client_families(db, [w["a"]])
        with count_statements() as many:
            await job_client_families(db, keys)
        with count_statements() as none_only:
            assert await job_client_families(db, [None]) == {None: None}
    assert bulk[w["a"]] == bulk[w["dup"]] == {w["a"], w["dup"]}
    assert bulk[w["b"]] == {w["b"]}
    assert bulk[None] is None
    assert len(one) == 2 and len(many) == 2, (len(one), len(many))
    assert none_only == []


async def test_query_count_does_not_grow_with_boards():
    w = await _seed()
    boards = _boards(w)
    async with AsyncSessionLocal() as db:
        with count_statements() as one:
            await missing_contract_ids_for_jobs(
                db, boards={101: boards[101]}, now=_now()
            )
        with count_statements() as three:
            await missing_contract_ids_for_jobs(
                db, boards={k: boards[k] for k in (101, 102, 103)}, now=_now()
            )
    # Rodziny klientów (2) + umowy (1).
    assert len(one) == 3, one
    assert len(three) == len(one), (len(one), len(three))
