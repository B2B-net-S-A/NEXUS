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
  od najlepszej osoby;
- bezpieczne włączenie (08.11.2026): w porcji tylko karty od 65% i do 7 dni,
  blokada w dni robocze od 7:00, wyłącznik i pilot HoR, minimum domyślnie 10.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.datastructures import QueryParams

from app.models.job import JobPriority, JobStatus
from app.models.user import UserRole
from app.services import review_batch as rb

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
    # Poniedziałek 09.11, 10:00 w Warszawie — dzień roboczy po 7:00.
    monkeypatch.setattr(rb, "_now", lambda: NOW)
    return monkeypatch


def _fake_state(monkeypatch, *, pending: int, done: int):
    async def _own(_db, _uid, *, now=None):
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


@pytest.mark.parametrize(
    "query, broad",
    [
        ("q=Jan+Kowalski", False),
        ("q=jan%40example.com", False),
        ("q=600100200", False),
        ("q=java+developer+warszawa", True),
        ("page=2&page_size=20&sort=updated", False),
        ("include_match_stats=true&q=Kowalski", False),
        ("skills=Java", True),
        ("q=Kowalski&location=Warszawa", True),
        ("q=Kowalski&text_mode=semantic", True),
        ("recruitment_id=12", True),
    ],
)
async def test_broad_list_query(query, broad):
    assert await rb.is_broad_list_query(None, QueryParams(query)) is broad


@pytest.mark.parametrize(
    "q, person",
    [
        ("Kowal", True),  # w trakcie pisania „Kowalski”
        ("Jan Kowalski", True),
        ("jan.kow", True),  # początek maila
        ("jan@", True),
        ("600 100", True),  # cyfry telefonu
        ("", True),
        ("java", False),
        ("java developer", False),
        ("Warszawa", False),
    ],
)
def test_person_lookup_while_typing(q, person):
    assert rb.is_person_lookup(q) is person


def test_broad_body_query():
    from app.schemas.candidate_search import CandidateSearchRequest

    assert not rb.is_broad_body_query(CandidateSearchRequest(q="Jan Kowalski"))
    assert not rb.is_broad_body_query(
        CandidateSearchRequest(sort="recent", text_mode="auto")
    )
    assert rb.is_broad_body_query(CandidateSearchRequest(q="java developer"))
    assert rb.is_broad_body_query(
        CandidateSearchRequest(q="Kowalski", skills_must=["Java"])
    )
    assert rb.is_broad_body_query(
        CandidateSearchRequest(q="Kowalski", text_mode="semantic")
    )


async def test_person_lookup_passes_even_when_blocked(batch_on):
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

    async def _own(_db, _uid, *, now=None):
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


# ── Bezpieczne włączenie (08.11.2026) ───────────────────────────────────────


def _dated(pid: int, score: float, age_days: float) -> rb.PendingCard:
    return rb.PendingCard(
        process_id=pid,
        job_id=1,
        candidate_id=1000 + pid,
        owner_id=None,
        score=score,
        opened_at=NOW - timedelta(days=age_days),
    )


@pytest.mark.parametrize(
    "score, age, inside",
    [
        (80, 1, True),
        (65, 6.9, True),
        (64.9, 1, False),  # poniżej progu porcji
        (90, 7.1, False),  # starsza niż 7 dni
        (90, 30, False),
    ],
)
def test_only_fresh_cards_from_threshold_are_the_batch(score, age, inside):
    assert rb.in_batch(_dated(1, score, age), NOW) is inside


def test_card_without_open_date_is_not_the_batch():
    card = rb.PendingCard(1, 1, 1001, None, 90, None)
    assert not rb.in_batch(card, NOW)


def test_default_minimum_is_ten():
    assert rb.BatchSettings().minimum == 10


@pytest.mark.parametrize(
    "moment, blocks",
    [
        (datetime(2026, 11, 9, 9, 0, tzinfo=timezone.utc), True),  # pon. 10:00
        (datetime(2026, 11, 9, 5, 30, tzinfo=timezone.utc), False),  # pon. 6:30
        (datetime(2026, 11, 9, 6, 0, tzinfo=timezone.utc), True),  # pon. 7:00
        (datetime(2026, 11, 8, 10, 0, tzinfo=timezone.utc), False),  # niedziela
        (datetime(2026, 11, 7, 10, 0, tzinfo=timezone.utc), False),  # sobota
    ],
)
def test_block_only_on_business_days_from_seven(moment, blocks):
    assert rb.blocking_now(rb.BatchSettings(), 7, moment) is blocks


def test_hor_switch_turns_the_block_off():
    assert not rb.blocking_now(rb.BatchSettings(block_enabled=False), 7, NOW)


def test_pilot_blocks_only_listed_people():
    pilot = rb.BatchSettings(pilot_user_ids=(7, 8))
    assert rb.blocking_now(pilot, 7, NOW)
    assert not rb.blocking_now(pilot, 9, NOW)


async def test_weekend_never_blocks(batch_on):
    _fake_state(batch_on, pending=100, done=0)
    batch_on.setattr(
        rb, "_now", lambda: datetime(2026, 11, 8, 10, 0, tzinfo=timezone.utc)
    )
    await rb.assert_search_allowed(_Db(), _user())


async def test_switch_off_unblocks_without_deploy(batch_on):
    _fake_state(batch_on, pending=100, done=0)

    async def _off(_db):
        return rb.BatchSettings(minimum=50, block_enabled=False)

    batch_on.setattr(rb, "read_settings", _off)
    await rb.assert_search_allowed(_Db(), _user())


async def test_person_outside_pilot_is_not_blocked(batch_on):
    _fake_state(batch_on, pending=100, done=0)

    async def _pilot(_db):
        return rb.BatchSettings(minimum=50, pilot_user_ids=(8,))

    batch_on.setattr(rb, "read_settings", _pilot)
    await rb.assert_search_allowed(_Db(), _user(uid=7))
    with pytest.raises(HTTPException):
        await rb.assert_search_allowed(_Db(), _user(uid=8))


class _SettingsDb:
    def __init__(self, value):
        self.value = value

    async def get(self, _model, _key):
        return SimpleNamespace(value=self.value)


async def test_settings_read_switch_and_pilot():
    value = await rb.read_settings(
        _SettingsDb(
            {"minimum": 20, "block_enabled": False, "pilot_user_ids": [8, "7", "x", 8]}
        )
    )
    assert value == rb.BatchSettings(
        minimum=20, block_enabled=False, pilot_user_ids=(7, 8)
    )


async def test_old_settings_without_switch_keep_the_block_on():
    value = await rb.read_settings(_SettingsDb({"minimum": 50}))
    assert value.block_enabled is True and value.pilot_user_ids == ()
