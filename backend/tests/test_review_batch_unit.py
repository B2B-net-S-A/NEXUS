"""Porcja dnia (07.11.2026) — logika bez bazy.

Kontrakty:

- podział kart w zespole: po równo, od najlepszej osoby, karty z właścicielem
  z zespołu zostają, „Dodaj 20 kolejnych” idzie do klikającego;
- minimum: kto ma w porcji mniej niż brakuje do minimum, przegląda całą porcję;
- blokada 423 ``REVIEW_MINIMUM_PENDING`` tylko dla rekrutera, przy włączonej
  porcji i niezrobionym minimum;
- lista kandydatów: filtry i opis to ręczne wyszukiwanie, samo nazwisko,
  mail albo telefon — nie;
- kolejka przeglądu: rekrutacje na zmianę (P0 i priorytet pierwsze), w każdej
  od najlepszej osoby.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.datastructures import QueryParams

from app.models.job import JobPriority, JobStatus
from app.models.user import UserRole
from app.services import review_batch as rb
from app.services.candidate_search_predicates import TextInterpretation

NOW = datetime(2026, 11, 9, 9, 0, tzinfo=timezone.utc)


def _card(pid: int, job: int, score: float, owner: int | None = None) -> rb.PendingCard:
    return rb.PendingCard(
        process_id=pid,
        job_id=job,
        candidate_id=1000 + pid,
        owner_id=owner,
        score=score,
        opened_at=NOW,
    )


# ── Podział w zespole ───────────────────────────────────────────────────────


def test_solo_recruiter_gets_every_card():
    cards = [_card(i, 1, 90 - i) for i in range(5)]
    plan = rb.plan_owners(cards, [7], seed="x")
    assert set(plan.values()) == {7} and len(plan) == 5


def test_two_recruiters_split_evenly_alternating_from_the_best():
    cards = [_card(i, 1, 90 - i) for i in range(20)]
    plan = rb.plan_owners(cards, [7, 8], seed="x")
    owners = [plan[c.process_id] for c in cards]
    assert owners.count(7) == 10 and owners.count(8) == 10
    # na zmianę od najlepszej: nikt nie dostaje samych słabszych
    assert owners[0] != owners[1]
    assert set(owners[:2]) == {7, 8}


def test_three_recruiters_get_seven_seven_six():
    plan = rb.plan_owners([_card(i, 1, 90 - i) for i in range(20)], [7, 8, 9], seed="s")
    counts = sorted(list(plan.values()).count(u) for u in (7, 8, 9))
    assert counts == [6, 7, 7]


def test_existing_owner_in_team_keeps_card_and_counts_to_balance():
    cards = [_card(1, 1, 90, owner=7), _card(2, 1, 89, owner=7), _card(3, 1, 80)]
    plan = rb.plan_owners(cards, [7, 8], seed="x")
    assert plan == {3: 8}


def test_owner_who_left_the_team_loses_cards():
    cards = [_card(1, 1, 90, owner=99), _card(2, 1, 80, owner=99)]
    plan = rb.plan_owners(cards, [7, 8], seed="x")
    assert set(plan) == {1, 2} and set(plan.values()) == {7, 8}


def test_add_more_goes_to_the_clicker_only():
    cards = [_card(i, 1, 90 - i) for i in range(4)]
    plan = rb.plan_owners(cards, [7, 8], seed="x", only=8)
    assert set(plan.values()) == {8}


def test_no_team_no_plan():
    assert rb.plan_owners([_card(1, 1, 90)], [], seed="x") == {}


# ── Minimum i blokada ───────────────────────────────────────────────────────


def _user(role=UserRole.recruiter, uid=7):
    return SimpleNamespace(id=uid, role=role)


@pytest.fixture
def batch_on(monkeypatch):
    monkeypatch.setattr(rb.settings, "REVIEW_BATCH_ENABLED", True, raising=False)

    async def _settings(_db):
        return rb.BatchSettings(minimum=50)

    monkeypatch.setattr(rb, "read_settings", _settings)
    return monkeypatch


def _fake_state(monkeypatch, *, pending: int, done: int):
    async def _own(_db, _uid):
        return [_card(i, 1, 80) for i in range(pending)]

    async def _done(_db, _uid, *, now):
        return done

    monkeypatch.setattr(rb, "_own_cards", _own)
    monkeypatch.setattr(rb, "decided_today", _done)


class _Db:
    async def scalars(self, _stmt):
        return SimpleNamespace(
            all=lambda: [
                SimpleNamespace(
                    id=1,
                    title="Senior Fullstack",
                    priority=JobPriority.medium,
                    p0_until=None,
                    status=JobStatus.published,
                )
            ]
        )


async def test_minimum_not_met_blocks_search_with_423(batch_on):
    _fake_state(batch_on, pending=120, done=12)
    with pytest.raises(HTTPException) as exc:
        await rb.assert_search_allowed(_Db(), _user())
    assert exc.value.status_code == 423
    detail = exc.value.detail
    assert detail["code"] == rb.BLOCK_CODE
    assert detail["required"] == 50 and detail["remaining"] == 38
    assert "38 z 50" in detail["message"]


async def test_minimum_met_unblocks(batch_on):
    _fake_state(batch_on, pending=70, done=50)
    await rb.assert_search_allowed(_Db(), _user())


async def test_small_batch_must_be_reviewed_whole(batch_on):
    # 15 osób w porcji, 0 decyzji: wymagane 15, nie 50
    _fake_state(batch_on, pending=15, done=0)
    status = await rb.status_for(_Db(), _user(), now=NOW)
    assert status.required == 15 and not status.met
    _fake_state(batch_on, pending=0, done=15)
    status = await rb.status_for(_Db(), _user(), now=NOW)
    assert status.required == 15 and status.met


async def test_empty_batch_never_blocks(batch_on):
    _fake_state(batch_on, pending=0, done=0)
    status = await rb.status_for(_Db(), _user(), now=NOW)
    assert status.met and status.required == 0


@pytest.mark.parametrize(
    "role",
    [UserRole.admin, UserRole.head_of_recruitment, UserRole.delivery_lead],
)
async def test_other_roles_are_never_blocked(batch_on, role):
    _fake_state(batch_on, pending=100, done=0)
    await rb.assert_search_allowed(_Db(), _user(role=role))


async def test_switched_off_never_blocks(monkeypatch):
    monkeypatch.setattr(rb.settings, "REVIEW_BATCH_ENABLED", False, raising=False)
    _fake_state(monkeypatch, pending=100, done=0)
    await rb.assert_search_allowed(_Db(), _user())


# ── Lista kandydatów: wyszukiwanie czy osoba ────────────────────────────────


def _interp(kind: str):
    async def _fake(_db, _q):
        return TextInterpretation(kind=kind, mode="x", rule="test")

    return _fake


@pytest.mark.parametrize(
    "query, kind, broad",
    [
        ("q=Jan+Kowalski", "name", False),
        ("q=jan%40example.com", "email", False),
        ("q=600100200", "phone", False),
        ("q=java+developer+warszawa", "text", True),
        ("page=2&page_size=20&sort=updated", "empty", False),
        ("include_match_stats=true&q=Kowalski", "name", False),
        ("skills=Java", "empty", True),
        ("q=Kowalski&location=Warszawa", "name", True),
        ("q=Kowalski&text_mode=semantic", "name", True),
        ("recruitment_id=12", "empty", True),
    ],
)
async def test_broad_list_query(monkeypatch, query, kind, broad):
    import app.services.candidate_search_predicates as preds

    monkeypatch.setattr(preds, "interpret_text", _interp(kind))
    assert await rb.is_broad_list_query(None, QueryParams(query)) is broad


async def test_person_lookup_passes_even_when_blocked(batch_on):
    import app.services.candidate_search_predicates as preds

    batch_on.setattr(preds, "interpret_text", _interp("name"))
    _fake_state(batch_on, pending=100, done=0)
    await rb.assert_list_search_allowed(None, _user(), QueryParams("q=Kowalski"))


async def test_filtered_list_is_blocked(batch_on):
    _fake_state(batch_on, pending=100, done=0)
    with pytest.raises(HTTPException) as exc:
        await rb.assert_list_search_allowed(
            _Db(), _user(), QueryParams("skills=Java&skills=Angular")
        )
    assert exc.value.status_code == 423


# ── Kolejka przeglądu ───────────────────────────────────────────────────────


async def test_queue_alternates_jobs_priority_first(monkeypatch):
    cards = [
        _card(1, 10, 90),
        _card(2, 10, 80),
        _card(3, 10, 70),
        _card(4, 20, 60),
        _card(5, 20, 50),
        _card(6, 30, 95),
    ]

    async def _own(_db, _uid):
        return cards

    monkeypatch.setattr(rb, "_own_cards", _own)
    jobs = [
        SimpleNamespace(
            id=10,
            priority=JobPriority.medium,
            p0_until=None,
            status=JobStatus.published,
        ),
        SimpleNamespace(
            id=20,
            priority=JobPriority.urgent,
            p0_until=None,
            status=JobStatus.published,
        ),
        SimpleNamespace(
            id=30,
            priority=JobPriority.low,
            p0_until=NOW + timedelta(hours=5),
            status=JobStatus.published,
        ),
    ]

    class _JobsDb:
        async def scalars(self, _stmt):
            return SimpleNamespace(all=lambda: jobs)

    queue = await rb.review_queue(_JobsDb(), _user(), now=NOW)
    # P0 (30), potem pilna (20), potem średnia (10); w każdej od najlepszej
    assert [c.process_id for c in queue] == [6, 4, 1, 5, 2, 3]


def _multi(role: UserRole, extra: list[str]):
    roles = {role.value, *extra}
    return SimpleNamespace(
        id=9,
        role=role,
        has_role=lambda r: (r.value if hasattr(r, "value") else str(r)) in roles,
    )


@pytest.mark.parametrize(
    "role, extra, applies",
    [
        (UserRole.recruiter, [], True),
        (UserRole.recruiter, ["delivery_lead"], False),
        (UserRole.admin, ["head_of_recruitment", "recruiter"], False),
        (UserRole.delivery_lead, ["recruiter"], False),
        (UserRole.talent_community_manager, [], False),
    ],
)
def test_who_gets_the_batch(role, extra, applies):
    assert rb.applies_to(_multi(role, extra)) is applies
