"""Dostępność i stawka z żywej umowy na prawdziwym schemacie (15.10.2026).

Regułę bez bazy sprawdza ``test_contract_availability_rule.py``. Tu:

* zapytanie ``load_contract_free`` daje to samo co znacznik (lustro SQL),
* filtr „Dostępny do daty” nie przepuszcza osoby trzymanej przez umowę,
* wyzwalacze umów i harmonogramu stawek kolejkują przeliczenie „Stawki od”,
  a żywa umowa nadpisuje stawkę ze screeningu i znika po końcu umowy,
* rekruter widzi w historii stawek kwotę żywej umowy (D4), a zakończonej nie,
* status „Czy szuka pracy” chowa ten sam warunek w Pythonie, w SQL i na
  froncie (znacznik ze źródłem ``contract``), a historia umów dla automatu
  notatek zna żywą umowę i start ostatniej (S2, S3).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

import app.models  # noqa: F401  (zarejestruj wszystkie mappery)
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.user import UserRole
from app.services import candidate_rate_from as rf
from app.models.candidate_conflict import CandidateConflict, ConflictType
from app.services.contract_availability import (
    NO_CONTRACTS,
    ContractFree,
    ContractHistory,
    availability_status_hidden,
    contract_free_by_clause,
    from_marker,
    load_contract_free,
    load_contract_history,
    without_live_contract_clause,
)
from app.services.employment_marker import load_employment_markers
from tests.test_interview_cycle import _user


async def _seed_people() -> dict:
    """Pięć osób u jednego klienta — po jednej na każdy przypadek reguły.

    * ``ends``     — zamówienie kończy się za 40 dni bez kontynuacji,
    * ``open``     — umowa bez zamówień (bez daty końca),
    * ``starting`` — umowa z startem za 14 dni,
    * ``follow``   — zamówienie kończy się za 40 dni, a kolejna umowa u tego
      samego klienta startuje dzień później,
    * ``idle``     — bez umowy; profil mówi „dostępny od” 10 dni temu.
    """
    tag = uuid.uuid4().hex[:8]
    today = business_today()
    ends_on = today + timedelta(days=40)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Availability-{tag}")
        people = {
            key: Candidate(
                name=key.capitalize(),
                lastname=f"Availability-{tag}",
                email=f"availability-{key}-{tag}@example.com",
                availability_date=today - timedelta(days=10),
            )
            for key in ("ends", "open", "starting", "follow", "idle")
        }
        db.add_all([client, *people.values()])
        await db.flush()

        def contract(key: str, start: date) -> Contract:
            return Contract(
                candidate_id=people[key].id,
                client_id=client.id,
                start_date=start,
                status=ContractStatus.active,
            )

        contracts = {
            "ends": contract("ends", today - timedelta(days=100)),
            "open": contract("open", today - timedelta(days=100)),
            "starting": contract("starting", today + timedelta(days=14)),
            "follow": contract("follow", today - timedelta(days=100)),
            "follow_next": contract("follow", ends_on + timedelta(days=1)),
        }
        db.add_all(contracts.values())
        await db.flush()
        for key in ("ends", "follow"):
            db.add(
                ClientOrder(
                    client_id=client.id,
                    contract_id=contracts[key].id,
                    title=f"Availability-{key}-{tag}",
                    status=ClientOrderStatus.active,
                    start_date=today - timedelta(days=100),
                    end_date=ends_on,
                    rate_client=Decimal("150"),
                    rate_unit=RateUnit.hourly,
                )
            )
        await db.commit()
        return {
            "today": today,
            "ends_on": ends_on,
            **{key: person.id for key, person in people.items()},
        }


@pytest.mark.asyncio
async def test_loader_gives_the_same_answer_as_the_marker(app_client: AsyncClient):
    world = await _seed_people()
    ids = [world[k] for k in ("ends", "open", "starting", "follow", "idle")]
    async with AsyncSessionLocal() as db:
        loaded = await load_contract_free(db, ids, today=world["today"])
        markers = await load_employment_markers(db, ids, today=world["today"])

    from_markers = {
        cid: free for cid, m in markers.items() if (free := from_marker(m)) is not None
    }
    assert loaded == from_markers
    assert loaded[world["ends"]] == ContractFree(
        world["ends_on"] + timedelta(days=1), "work_end"
    )
    assert loaded[world["open"]].basis == "no_end_date"
    assert loaded[world["starting"]].basis == "starting"
    assert loaded[world["follow"]].basis == "no_end_date"
    assert world["idle"] not in loaded


@pytest.mark.asyncio
async def test_available_by_date_filter_waits_for_the_end_of_work(
    app_client: AsyncClient,
):
    world = await _seed_people()
    ids = [world[k] for k in ("ends", "open", "starting", "follow", "idle")]

    async def available_by(day: date) -> set[int]:
        async with AsyncSessionLocal() as db:
            rows = await db.execute(
                select(Candidate.id).where(
                    Candidate.id.in_(ids),
                    contract_free_by_clause(Candidate.id, day, today=world["today"]),
                )
            )
            return {row[0] for row in rows.all()}

    # Dzień końca pracy: osoba jeszcze pracuje.
    assert await available_by(world["ends_on"]) == {world["idle"]}
    # Dzień po końcu: wolna. Bez daty końca, przed startem i z kolejną
    # umową — dalej trzymana przez umowę.
    assert await available_by(world["ends_on"] + timedelta(days=1)) == {
        world["idle"],
        world["ends"],
    }


async def _seed_past_and_conflict(world: dict) -> dict:
    """Dwie osoby spoza żywych umów: ``past`` — umowa zakończona (i szkic
    nowszej, który się nie liczy), ``conflict`` — sam ręczny konflikt
    „Obecne zatrudnienie” bez umowy w NEXUSIE."""
    tag = uuid.uuid4().hex[:8]
    today = world["today"]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"StatusRule-{tag}")
        past = Candidate(
            name="Past", lastname=f"StatusRule-{tag}", email=f"past-{tag}@example.com"
        )
        conflict = Candidate(
            name="Conflict",
            lastname=f"StatusRule-{tag}",
            email=f"conflict-{tag}@example.com",
        )
        db.add_all([client, past, conflict])
        await db.flush()
        db.add_all(
            [
                Contract(
                    candidate_id=past.id,
                    client_id=client.id,
                    start_date=today - timedelta(days=300),
                    end_date=today - timedelta(days=30),
                    status=ContractStatus.ended,
                ),
                Contract(
                    candidate_id=past.id,
                    client_id=client.id,
                    start_date=today + timedelta(days=30),
                    status=ContractStatus.draft,
                ),
                CandidateConflict(
                    candidate_id=conflict.id,
                    client_id=client.id,
                    type=ConflictType.current_employment,
                    reason="pytest — obecne zatrudnienie",
                    active=True,
                ),
            ]
        )
        await db.commit()
        return {"past": past.id, "conflict": conflict.id}


@pytest.mark.asyncio
async def test_status_rule_is_the_same_in_python_sql_and_the_marker(
    app_client: AsyncClient,
):
    world = await _seed_people()
    world.update(await _seed_past_and_conflict(world))
    keys = ("ends", "open", "starting", "follow", "idle", "past", "conflict")
    ids = [world[k] for k in keys]
    async with AsyncSessionLocal() as db:
        loaded = await load_contract_free(db, ids, today=world["today"])
        markers = await load_employment_markers(db, ids, today=world["today"])
        counted = set(
            (
                await db.execute(
                    select(Candidate.id).where(
                        Candidate.id.in_(ids),
                        without_live_contract_clause(Candidate.id),
                    )
                )
            )
            .scalars()
            .all()
        )

    python_hidden = {cid for cid in ids if availability_status_hidden(loaded.get(cid))}
    sql_hidden = set(ids) - counted
    pill_hidden = {
        cid for cid, m in markers.items() if m is not None and m.source == "contract"
    }
    expected = {world[k] for k in ("ends", "open", "starting", "follow")}
    assert python_hidden == sql_hidden == pill_hidden == expected
    # Sam ręczny konflikt „Obecne zatrudnienie” od 17.10.2026 nie daje
    # znacznika (tylko umowa) i nie chowa statusu — jak pigułka na froncie.
    assert markers[world["conflict"]] is None


@pytest.mark.asyncio
async def test_contract_history_for_the_notes_automation(app_client: AsyncClient):
    world = await _seed_people()
    world.update(await _seed_past_and_conflict(world))
    today = world["today"]
    async with AsyncSessionLocal() as db:
        history = {
            key: await load_contract_history(db, world[key])
            for key in ("ends", "starting", "follow", "idle", "past", "conflict")
        }

    assert history["ends"] == ContractHistory(True, today - timedelta(days=100))
    assert history["starting"] == ContractHistory(True, today + timedelta(days=14))
    # Kolejna umowa po bieżącej — start ostatniej, nie bieżącej.
    assert history["follow"] == ContractHistory(
        True, world["ends_on"] + timedelta(days=1)
    )
    assert history["idle"] == NO_CONTRACTS
    # Szkic nowszej umowy się nie liczy.
    assert history["past"] == ContractHistory(False, today - timedelta(days=300))
    assert history["conflict"] == NO_CONTRACTS


async def _queued(candidate_id: int) -> bool:
    async with AsyncSessionLocal() as db:
        return bool(
            await db.scalar(
                text("SELECT 1 FROM candidate_rate_from_queue WHERE candidate_id = :c"),
                {"c": candidate_id},
            )
        )


async def _drain() -> None:
    for _ in range(100):
        async with AsyncSessionLocal() as db:
            done = await rf.process_queue(db, limit=500)
            await db.commit()
        if not done:
            return
    raise AssertionError("kolejka „Stawki od” nie doszła do końca")


async def _rate_from(candidate_id: int):
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                select(Candidate.rate_from_hourly, Candidate.rate_from_source).where(
                    Candidate.id == candidate_id
                )
            )
        ).one()


async def _seed_rate_pair() -> dict:
    tag = uuid.uuid4().hex[:8]
    today = business_today()
    async with AsyncSessionLocal() as db:
        client = Client(name=f"ContractRate-{tag}")
        candidate = Candidate(
            name="Konsultant",
            lastname=f"Umowny{tag}",
            email=f"contract-rate-{tag}@example.com",
            expected_rate_hourly=Decimal("130.00"),
            expected_rate_currency="PLN",
        )
        db.add_all([client, candidate])
        await db.commit()
        return {"today": today, "client": client.id, "candidate": candidate.id}


@pytest.mark.asyncio
async def test_live_contract_rate_overrides_and_returns_after_the_end(
    app_client: AsyncClient,
):
    pair = await _seed_rate_pair()
    await _drain()
    assert (await _rate_from(pair["candidate"])).rate_from_hourly == Decimal("130.00")

    async with AsyncSessionLocal() as db:
        contract = Contract(
            candidate_id=pair["candidate"],
            client_id=pair["client"],
            start_date=pair["today"] - timedelta(days=700),
            status=ContractStatus.active,
            rate_candidate=Decimal("150"),
            rate_candidate_currency="PLN",
            rate_unit=RateUnit.hourly,
        )
        db.add(contract)
        await db.commit()
        contract_id = contract.id

    assert await _queued(pair["candidate"])
    await _drain()
    row = await _rate_from(pair["candidate"])
    # Start umowy sprzed 18 miesięcy nie wypycha jej stawki z okna.
    assert row.rate_from_hourly == Decimal("150.00")
    assert row.rate_from_source == "contract"

    async with AsyncSessionLocal() as db:
        await db.execute(
            text("UPDATE contracts SET status = 'ended' WHERE id = :id"),
            {"id": contract_id},
        )
        await db.commit()

    assert await _queued(pair["candidate"])
    await _drain()
    row = await _rate_from(pair["candidate"])
    assert row.rate_from_hourly == Decimal("130.00")
    assert row.rate_from_source != "contract"


@pytest.mark.asyncio
async def test_schedule_step_and_future_start_enqueue(app_client: AsyncClient):
    from app.models.contract_candidate_rate import ContractCandidateRate

    pair = await _seed_rate_pair()
    async with AsyncSessionLocal() as db:
        contract = Contract(
            candidate_id=pair["candidate"],
            client_id=pair["client"],
            start_date=pair["today"] + timedelta(days=5),
            status=ContractStatus.active,
            rate_candidate=Decimal("160"),
            rate_candidate_currency="PLN",
            rate_unit=RateUnit.hourly,
        )
        db.add(contract)
        await db.commit()
        contract_id = contract.id
    await _drain()
    # Umowa przed startem nie jest jeszcze „Stawką od”.
    assert (await _rate_from(pair["candidate"])).rate_from_source != "contract"

    async with AsyncSessionLocal() as db:
        db.add(
            ContractCandidateRate(
                contract_id=contract_id,
                rate=Decimal("170"),
                effective_from=pair["today"] + timedelta(days=30),
            )
        )
        await db.commit()
    assert await _queued(pair["candidate"])
    await _drain()

    async with AsyncSessionLocal() as db:
        requeued = await rf.requeue_live_contracts(db)
        await db.commit()
    assert requeued >= 1
    assert await _queued(pair["candidate"])


@pytest.mark.asyncio
async def test_recruiter_sees_live_contract_amount_but_not_ended(
    app_client: AsyncClient,
):
    pair = await _seed_rate_pair()
    _, recruiter_headers = await _user(UserRole.recruiter)
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                Contract(
                    candidate_id=pair["candidate"],
                    client_id=pair["client"],
                    start_date=pair["today"] - timedelta(days=900),
                    end_date=pair["today"] - timedelta(days=400),
                    status=ContractStatus.ended,
                    rate_candidate=Decimal("120"),
                    rate_candidate_currency="PLN",
                    rate_unit=RateUnit.hourly,
                ),
                Contract(
                    candidate_id=pair["candidate"],
                    client_id=pair["client"],
                    start_date=pair["today"] - timedelta(days=100),
                    status=ContractStatus.active,
                    rate_candidate=Decimal("150"),
                    rate_candidate_currency="PLN",
                    rate_unit=RateUnit.hourly,
                ),
            ]
        )
        await db.commit()

    response = await app_client.get(
        f"/api/candidates/{pair['candidate']}/rate-overview", headers=recruiter_headers
    )

    assert response.status_code == 200, response.text
    paid = {row["start_date"]: row for row in response.json()["paid"]}
    live = paid[(pair["today"] - timedelta(days=100)).isoformat()]
    ended = paid[(pair["today"] - timedelta(days=900)).isoformat()]
    assert Decimal(str(live["amount_hourly"])) == Decimal("150.00")
    assert live["redacted"] is False
    assert ended["amount_hourly"] is None
    assert ended["redacted"] is True


@pytest.mark.asyncio
async def test_profile_shows_declared_rate_below_live_contract(app_client: AsyncClient):
    # R4 (17.10.2026): „Stawka u nas” 150 z umowy, a profil mówi 130 —
    # odpowiedź profilu niesie „deklarował od 130”.
    pair = await _seed_rate_pair()
    _, recruiter_headers = await _user(UserRole.recruiter)
    async with AsyncSessionLocal() as db:
        db.add(
            Contract(
                candidate_id=pair["candidate"],
                client_id=pair["client"],
                start_date=pair["today"] - timedelta(days=100),
                status=ContractStatus.active,
                rate_candidate=Decimal("150"),
                rate_candidate_currency="PLN",
                rate_unit=RateUnit.hourly,
            )
        )
        await db.commit()
    await _drain()

    response = await app_client.get(
        f"/api/candidates/{pair['candidate']}", headers=recruiter_headers
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rate_from_source"] == "contract"
    assert Decimal(str(body["rate_from_hourly"])) == Decimal("150.00")
    assert Decimal(str(body["rate_declared_from_hourly"])) == Decimal("130.00")
    assert body["rate_declared_from_at"] is not None
