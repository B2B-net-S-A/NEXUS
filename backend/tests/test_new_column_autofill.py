"""Silnik „System trzyma Nowych na 20” (23.10.2026) — prawdziwy Postgres.

Kontrakty:

- brakujące do ``TARGET`` osoby wchodzą do „Nowych” najlepszymi z puli
  nocnego przeglądu i otwartych propozycji (``full_base``, ``new_cv``),
  także z wynikiem poniżej progu propozycji;
- wejście ``system``: bez blokady 12 h, bez osoby dodającej, z migawką
  wyniku, wymagań, „Stawki od” i dostępności;
- osoby dodane przez zespół też się liczą; pełna kolumna = nic;
- system nie dodaje: kogoś, kto był w tej rekrutacji, pominiętej propozycji,
  zatrudnionego, zgłoszenia z portalu, osoby na czarnej liście ani off-limits;
- rekrutacja poza pracą nie dostaje nikogo; rytm: dni robocze 7–19, pełny
  przebieg co 15 min, a między nimi rekrutacje z ruchem karty.

Baza testowa jest wspólna i nieczyszczona: asercje dotyczą własnych wierszy.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.job_autofill_pool import JobAutofillPool
from app.models.job_proposal import JobProposal
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.recruitment_process import RecruitmentProcess
from app.models.user import User, UserRole
from app.services import new_column_autofill as autofill

_WARSAW = ZoneInfo("Europe/Warsaw")
# Środa 21.10.2026, 10:00 w Warszawie — dzień roboczy w godzinach pracy.
_WORKDAY = datetime(2026, 10, 21, 10, 0, tzinfo=_WARSAW).astimezone(timezone.utc)


async def _user() -> int:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"ncf-{tag}@example.com",
            password_hash=hash_password(f"T3st_{tag}!Fill"),
            name="NCF rekruter",
            role=UserRole.recruiter,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        return user.id


async def _world(people: int, *, work_state: str = "searching") -> dict:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"NCF client {tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"NCF job {tag}",
            client_id=client.id,
            status=JobStatus.published,
            work_state=work_state,
        )
        candidates = [
            Candidate(name="Dopełnienie", lastname=f"{i}-{tag}") for i in range(people)
        ]
        db.add_all([job, *candidates])
        await db.commit()
        return {"job_id": job.id, "ids": [c.id for c in candidates]}


async def _pool(job_id: int, scores: dict[int, float]) -> None:
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                JobAutofillPool(
                    job_id=job_id,
                    candidate_id=cid,
                    score=Decimal(str(score)),
                    run_id="run-ncf",
                    evidence={"matched_must": ["Java"], "missing_must": ["AWS"]},
                )
                for cid, score in scores.items()
            ]
        )
        await db.commit()


async def _stage(cid: int, job_id: int, stage: PipelineStage, by: int | None) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(candidate_id=cid, job_id=job_id, stage=stage, moved_by=by)
        )
        await db.commit()


async def _fill(job_id: int) -> list[int]:
    async with AsyncSessionLocal() as db:
        added = await autofill.fill_job(db, job_id, now=_WORKDAY)
        await db.commit()
        return added


async def _processes(job_id: int) -> dict[int, RecruitmentProcess]:
    async with AsyncSessionLocal() as db:
        return {
            p.candidate_id: p
            for p in (
                await db.scalars(
                    select(RecruitmentProcess).where(
                        RecruitmentProcess.job_id == job_id
                    )
                )
            ).all()
        }


async def test_fills_missing_places_with_the_best_of_the_pool(monkeypatch):
    monkeypatch.setattr(autofill, "TARGET", 2)
    world = await _world(3)
    best, second, third = world["ids"]
    # Wynik poniżej progu propozycji też wchodzi („zawsze 20”).
    await _pool(world["job_id"], {best: 64.5, second: 52.0, third: 40.0})
    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, best)
        candidate.rate_from_hourly = Decimal("140")
        candidate.rate_from_computed_at = datetime.now(timezone.utc)
        candidate.availability_date = datetime(2026, 11, 1).date()
        await db.commit()

    assert await _fill(world["job_id"]) == [best, second]

    processes = await _processes(world["job_id"])
    assert set(processes) == {best, second}
    process = processes[best]
    assert process.entry_source == "system"
    assert process.claimed_by_user_id is None and process.claimed_until is None
    meta = process.entry_meta
    assert meta["kind"] == "autofill" and meta["score"] == 64.5
    assert meta["matched_must"] == ["Java"] and meta["missing_must"] == ["AWS"]
    assert meta["rate_from_hourly"] == 140.0
    assert meta["availability_date"] == "2026-11-01"
    assert processes[second].entry_meta["rate_from_hourly"] is None
    async with AsyncSessionLocal() as db:
        stages = (
            await db.scalars(
                select(CandidateStage).where(CandidateStage.job_id == world["job_id"])
            )
        ).all()
        assert {s.stage for s in stages} == {PipelineStage.new}
        assert {s.moved_by for s in stages} == {None}
        [event] = (
            await db.scalars(
                select(Activity).where(
                    Activity.entity_type == "job_automation",
                    Activity.entity_id == world["job_id"],
                    Activity.action == autofill.ACTION,
                )
            )
        ).all()
    assert event.details["count"] == 2 and event.details["had"] == 0


async def test_people_added_by_the_team_count_and_a_full_column_gets_nothing(
    monkeypatch,
):
    monkeypatch.setattr(autofill, "TARGET", 3)
    recruiter = await _user()
    world = await _world(5)
    a, b, c, d, e = world["ids"]
    await _stage(a, world["job_id"], PipelineStage.new, recruiter)
    await _stage(b, world["job_id"], PipelineStage.new, recruiter)
    # Osoba w Screeningu nie liczy się do „Nowych”.
    await _stage(c, world["job_id"], PipelineStage.screening, recruiter)
    await _pool(world["job_id"], {d: 90, e: 80})

    assert await _fill(world["job_id"]) == [d]
    assert await _fill(world["job_id"]) == []


async def test_never_adds_people_the_system_must_skip(monkeypatch):
    monkeypatch.setattr(autofill, "TARGET", 20)
    recruiter = await _user()
    world = await _world(7)
    closed, dismissed, hired, blacklisted, off_limits, board, ok = world["ids"]
    other = await _world(0)
    async with AsyncSessionLocal() as db:
        db.add(
            JobProposal(
                job_id=world["job_id"],
                candidate_id=dismissed,
                source="full_base",
                score=Decimal("95"),
                status="dismissed",
            )
        )
        db.add(
            JobProposal(
                job_id=world["job_id"],
                candidate_id=board,
                source="job_board",
                score=Decimal("99"),
                status="proposed",
            )
        )
        (await db.get(Candidate, blacklisted)).status = "blacklisted"
        await db.commit()
    await _stage(closed, world["job_id"], PipelineStage.rejected, recruiter)
    await _stage(hired, other["job_id"], PipelineStage.hired, recruiter)
    await _pool(
        world["job_id"],
        {closed: 99, dismissed: 98, hired: 97, blacklisted: 96, off_limits: 95, ok: 50},
    )

    from app.services import client_off_limits

    async def _needs_confirmation(db, *, job_id, candidates):
        return [
            type("Person", (), {"candidate_id": c.id})()
            for c in candidates
            if c.id == off_limits
        ]

    monkeypatch.setattr(
        client_off_limits, "people_needing_confirmation", _needs_confirmation
    )

    assert await _fill(world["job_id"]) == [ok]


async def test_open_proposals_from_new_cvs_join_the_pool(monkeypatch):
    monkeypatch.setattr(autofill, "TARGET", 2)
    world = await _world(3)
    from_pool, from_cv, expired = world["ids"]
    await _pool(world["job_id"], {from_pool: 60})
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                JobProposal(
                    job_id=world["job_id"],
                    candidate_id=from_cv,
                    source="new_cv",
                    score=Decimal("88"),
                    status="proposed",
                    evidence={"matched_must": ["Kotlin"]},
                ),
                JobProposal(
                    job_id=world["job_id"],
                    candidate_id=expired,
                    source="full_base",
                    score=Decimal("99"),
                    status="expired",
                ),
            ]
        )
        await db.commit()

    assert await _fill(world["job_id"]) == [from_cv, from_pool]
    processes = await _processes(world["job_id"])
    assert processes[from_cv].entry_meta["matched_must"] == ["Kotlin"]


async def test_job_out_of_work_gets_nobody(monkeypatch):
    world = await _world(1, work_state="client_silent")
    await _pool(world["job_id"], {world["ids"][0]: 90})
    assert await _fill(world["job_id"]) == []


@pytest.mark.parametrize(
    ("local", "expected"),
    [
        (datetime(2026, 10, 21, 7, 0), True),
        (datetime(2026, 10, 21, 18, 59), True),
        (datetime(2026, 10, 21, 19, 0), False),
        (datetime(2026, 10, 21, 6, 59), False),
        (datetime(2026, 10, 24, 10, 0), False),  # sobota
        (datetime(2026, 11, 11, 10, 0), False),  # Święto Niepodległości
    ],
)
def test_work_hours_are_business_days_7_to_19(local, expected):
    moment = local.replace(tzinfo=_WARSAW).astimezone(timezone.utc)
    assert autofill.in_work_hours(moment) is expected


async def test_tick_runs_a_full_pass_then_only_touched_jobs(monkeypatch):
    monkeypatch.setattr(autofill.settings, "NEW_COLUMN_AUTOFILL_ENABLED", True)
    monkeypatch.setattr(autofill, "_state", autofill._State())
    seen: list[list[int]] = []

    async def _fill_job(db, job_id, *, now, limit=None):
        seen[-1].append(job_id)
        return []

    async def _all(db):
        return [1, 2, 3]

    async def _touched(db, since):
        return [2]

    monkeypatch.setattr(autofill, "fill_job", _fill_job)
    monkeypatch.setattr(autofill, "_jobs_in_work", _all)
    monkeypatch.setattr(autofill, "_jobs_touched_since", _touched)

    seen.append([])
    assert (await autofill.tick(now=_WORKDAY))["pass"] == "full"
    seen.append([])
    later = _WORKDAY + timedelta(minutes=1)
    assert (await autofill.tick(now=later))["pass"] == "touched"
    seen.append([])
    much_later = _WORKDAY + autofill.FULL_PASS_EVERY
    assert (await autofill.tick(now=much_later))["pass"] == "full"
    # Rekrutacja z ruchem karty idzie pierwsza, potem reszta pełnego przebiegu.
    assert seen == [[2, 1, 3], [2], [2, 1, 3]]


async def test_budget_spreads_the_first_pass_over_ticks(monkeypatch):
    """Bezpiecznik: najwyżej ``NEW_COLUMN_AUTOFILL_MAX_PER_TICK`` dodań na tick;
    przebieg wraca w następnym ticku od miejsca przerwania, także do
    rekrutacji, której limit nie dał dojść do 20."""
    monkeypatch.setattr(autofill.settings, "NEW_COLUMN_AUTOFILL_ENABLED", True)
    monkeypatch.setattr(autofill.settings, "NEW_COLUMN_AUTOFILL_MAX_PER_TICK", 25)
    monkeypatch.setattr(autofill, "_state", autofill._State())
    missing = {1: 20, 2: 20, 3: 20}
    calls: list[tuple[int, int]] = []

    async def _fill_job(db, job_id, *, now, limit=None):
        n = min(missing[job_id], limit)
        missing[job_id] -= n
        calls.append((job_id, n))
        return list(range(n))

    async def _all(db):
        return [1, 2, 3]

    async def _touched(db, since):
        return []

    monkeypatch.setattr(autofill, "fill_job", _fill_job)
    monkeypatch.setattr(autofill, "_jobs_in_work", _all)
    monkeypatch.setattr(autofill, "_jobs_touched_since", _touched)

    first = await autofill.tick(now=_WORKDAY)
    assert first["filled"] == {1: 20, 2: 5} and first["pending"] == 2
    second = await autofill.tick(now=_WORKDAY + timedelta(minutes=1))
    assert second["pass"] == "touched" and second["filled"] == {2: 15, 3: 10}
    third = await autofill.tick(now=_WORKDAY + timedelta(minutes=2))
    assert third["filled"] == {3: 10} and third["pending"] == 0
    assert missing == {1: 0, 2: 0, 3: 0}


async def test_tick_does_nothing_when_disabled_or_after_hours(monkeypatch):
    monkeypatch.setattr(autofill.settings, "NEW_COLUMN_AUTOFILL_ENABLED", False)
    assert await autofill.tick(now=_WORKDAY) == {"skipped": "disabled"}
    monkeypatch.setattr(autofill.settings, "NEW_COLUMN_AUTOFILL_ENABLED", True)
    evening = datetime(2026, 10, 21, 20, 0, tzinfo=_WARSAW).astimezone(timezone.utc)
    assert await autofill.tick(now=evening) == {"skipped": "outside_hours"}


# ── Reguły z odrzuceń (decyzje Artura 25.10.2026) ───────────────────────────


async def _rates(job_id: int, budget: float | None, rates: dict[int, float]) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        job.rate_budget_hourly = Decimal(str(budget)) if budget is not None else None
        for cid, rate in rates.items():
            candidate = await db.get(Candidate, cid)
            candidate.rate_from_hourly = Decimal(str(rate))
            candidate.rate_from_computed_at = datetime.now(timezone.utc)
        await db.commit()


async def test_budget_skips_far_above_and_puts_slightly_above_last(monkeypatch):
    """Ponad 15% nad budżetem = nie dodaje (do 27.10.2026: 25%); 0–15% nad
    budżetem = za osobami w budżecie i z nieznaną stawką. Stawka poniżej
    20 zł/h to błąd odczytu, nie stawka — liczy się jak nieznana."""
    monkeypatch.setattr(autofill, "TARGET", 5)
    world = await _world(6)
    far, slight, fits, unknown, garbage, consents = world["ids"]
    await _pool(
        world["job_id"],
        {far: 99, slight: 98, consents: 97, fits: 50, unknown: 40, garbage: 30},
    )
    await _rates(
        world["job_id"],
        100,
        {far: 116, slight: 115, fits: 100, garbage: 0.6, consents: 200},
    )
    async with AsyncSessionLocal() as db:
        # Zgoda z rozmowy na ofertę poniżej minimum — stawka nie przeszkadza.
        (await db.get(Candidate, consents)).accepts_below_min_rate = True
        await db.commit()

    assert await _fill(world["job_id"]) == [consents, fits, unknown, garbage, slight]
    processes = await _processes(world["job_id"])
    assert processes[slight].entry_meta["cautions"] == [
        {"key": "budget", "over_pct": 15, "rate": 115.0, "budget": 100.0}
    ]
    assert processes[fits].entry_meta["cautions"] == []


async def test_office_and_city_cautions_go_last_with_a_note(monkeypatch):
    """Mniej dni w biurze, niż chce klient, „tylko zdalnie” albo inne miasto
    przy pracy z biurem = za resztą, z ostrzeżeniem w migawce (27.10.2026).
    Zgoda na więcej dni w biurze znosi ostrzeżenie o dniach."""
    monkeypatch.setattr(autofill, "TARGET", 5)
    world = await _world(5)
    fewer, remote, krakow, consents, ok = world["ids"]
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world["job_id"])
        job.onsite_days_per_week = 3
        job.location = "Gdynia"
        (await db.get(Candidate, fewer)).max_onsite_days_per_week = 1
        (await db.get(Candidate, remote)).preferences = {"remote_modes": ["remote"]}
        (await db.get(Candidate, krakow)).city = "Kraków"
        person = await db.get(Candidate, consents)
        person.max_onsite_days_per_week = 1
        person.accepts_more_office_days = True
        await db.commit()
    await _pool(
        world["job_id"], {fewer: 95, remote: 90, krakow: 85, consents: 80, ok: 50}
    )

    assert await _fill(world["job_id"]) == [consents, ok, fewer, remote, krakow]
    processes = await _processes(world["job_id"])
    assert processes[fewer].entry_meta["cautions"] == [
        {"key": "office_days", "candidate_days": 1, "required_days": 3}
    ]
    assert processes[remote].entry_meta["cautions"] == [
        {"key": "remote_only", "required_days": 3}
    ]
    assert processes[krakow].entry_meta["cautions"] == [
        {"key": "office_city", "city": "Kraków", "office": "Gdynia", "required_days": 3}
    ]
    assert processes[consents].entry_meta["cautions"] == []


async def test_budget_rules_need_a_budget(monkeypatch):
    monkeypatch.setattr(autofill, "TARGET", 2)
    world = await _world(2)
    pricey, cheap = world["ids"]
    await _pool(world["job_id"], {pricey: 90, cheap: 50})
    await _rates(world["job_id"], None, {pricey: 400, cheap: 80})

    assert await _fill(world["job_id"]) == [pricey, cheap]


async def test_skips_people_who_work_at_the_client_now(monkeypatch):
    """Osoba, która według CV albo LinkedIna pracuje teraz u klienta tej
    rekrutacji, nie wchodzi od systemu — także przy wpisie CV bez dat
    (import gubi daty, a rekruterzy odrzucali takie osoby: „pracuje
    w Nordei przez inną firmę”)."""
    monkeypatch.setattr(autofill, "TARGET", 5)
    world = await _world(4)
    undated, linkedin, left, ok = world["ids"]
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world["job_id"])
        client = await db.get(Client, job.client_id)
        company = f"{client.name} Sp. z o.o."
        (await db.get(Candidate, undated)).experience = [
            {"company": "Inna firma", "role": "Dev", "start": "2015", "end": "2019"},
            {"company": company, "role": "Dev", "start": "", "end": ""},
        ]
        (await db.get(Candidate, linkedin)).linkedin_current_company = client.name
        (await db.get(Candidate, left)).experience = [
            {"company": company, "role": "Dev", "start": "2018", "end": "2021"}
        ]
        await db.commit()
    await _pool(world["job_id"], {undated: 90, linkedin: 80, left: 70, ok: 60})

    assert await _fill(world["job_id"]) == [left, ok]


async def test_never_readds_people_removed_from_the_recruitment(monkeypatch):
    """Usunięcie z rekrutacji kasuje wiersze etapu — archiwum
    ``candidate_stage_removals`` zostaje i system tej osoby nie przywraca."""
    from app.models.candidate_stage_removal import CandidateStageRemoval

    monkeypatch.setattr(autofill, "TARGET", 5)
    world = await _world(2)
    removed, ok = world["ids"]
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStageRemoval(
                candidate_id=removed,
                job_id=world["job_id"],
                reason="remove_from_recruitment: test",
                last_stage="new",
                stage_count=1,
                stages_snapshot=[],
            )
        )
        await db.commit()
    await _pool(world["job_id"], {removed: 90, ok: 60})

    assert await _fill(world["job_id"]) == [ok]
