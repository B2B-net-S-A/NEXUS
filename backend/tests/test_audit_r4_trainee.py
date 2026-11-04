"""Audyt 25.09.2026, runda 4 — praktykant i Akademia (R4-9…R4-12), bez bazy.

- R4-9: oddzwonienie „później” nie może wypaść po końcu programu (422 przy
  zapisie), a przy awansie otwarte oddzwonienia trafiają do „Moich ludzi”;
- R4-10: nowe minimum stawki bez odpowiedzi o zgodzie czyści starą zgodę
  „można dzwonić poniżej minimum”;
- R4-11: w odczycie Luny pusty koniec pracy nie znaczy „do dziś”;
- R4-12: dostępność „później” ustawia datę nie wcześniej niż za 3 miesiące.
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.services import academy_rules
from app.services import trainee_program
from app.services import trainee_rules as rules_mod

USER = SimpleNamespace(id=7)


def _candidate(**kw) -> Candidate:
    base = dict(
        expected_rate_hourly=Decimal("150.00"),
        expected_rate_currency="PLN",
        profile_rate_version=3,
        accepts_below_min_rate=True,
        cv_extracted_data={},
        availability_date=None,
    )
    base.update(kw)
    return Candidate(**base)


def _facts(**kw) -> trainee_program.CallFacts:
    base = dict(b2b_willingness="b2b")
    base.update(kw)
    return trainee_program.CallFacts(**base)


# ── R4-10: zgoda poniżej minimum dotyczy minimum z rozmowy ────────────────


def test_new_minimum_without_consent_answer_clears_old_consent() -> None:
    cand = _candidate()
    audit = trainee_program._apply_facts(
        cand, _facts(min_rate_value=Decimal("180"), min_rate_unit="hour"), USER
    )
    assert cand.expected_rate_hourly == Decimal("180.00")
    assert cand.accepts_below_min_rate is None
    assert audit["accepts_below_min_rate_cleared"] is True


def test_same_minimum_without_answer_keeps_the_consent() -> None:
    cand = _candidate()
    audit = trainee_program._apply_facts(
        cand, _facts(min_rate_value=Decimal("150"), min_rate_unit="hour"), USER
    )
    assert cand.accepts_below_min_rate is True
    assert "accepts_below_min_rate_cleared" not in audit


def test_new_minimum_with_an_answer_stores_that_answer() -> None:
    cand = _candidate()
    trainee_program._apply_facts(
        cand,
        _facts(
            min_rate_value=Decimal("180"),
            min_rate_unit="hour",
            accepts_below_min_rate=False,
        ),
        USER,
    )
    assert cand.accepts_below_min_rate is False


def test_no_minimum_given_keeps_the_consent() -> None:
    cand = _candidate()
    trainee_program._apply_facts(cand, _facts(), USER)
    assert cand.accepts_below_min_rate is True


# ── R4-12: „później” = co najmniej za 3 miesiące ─────────────────────────


def test_later_availability_replaces_a_past_date() -> None:
    cand = _candidate(availability_date=business_today() - timedelta(days=40))
    trainee_program._apply_facts(cand, _facts(availability="later"), USER)
    floor = business_today() + timedelta(
        days=trainee_program.AVAILABILITY_LATER_MIN_DAYS
    )
    assert cand.availability_date == floor
    # „Później” nigdy nie wypada wcześniej niż „w ciągu 3 miesięcy”.
    assert (
        trainee_program.AVAILABILITY_LATER_MIN_DAYS
        > (trainee_program.AVAILABILITY_DAYS["within_3m"])
    )


def test_later_availability_keeps_a_known_further_date() -> None:
    far = business_today() + timedelta(days=200)
    cand = _candidate(availability_date=far)
    trainee_program._apply_facts(cand, _facts(availability="later"), USER)
    assert cand.availability_date == far


def test_no_availability_answer_leaves_the_date() -> None:
    past = business_today() - timedelta(days=5)
    cand = _candidate(availability_date=past)
    trainee_program._apply_facts(cand, _facts(), USER)
    assert cand.availability_date == past


# ── R4-9: oddzwonienie nie wypada po końcu programu ──────────────────────


def _next_workday_after(day: date) -> date:
    day += timedelta(days=1)
    while not rules_mod.is_workday(day):
        day += timedelta(days=1)
    return day


async def test_later_after_program_end_is_rejected(monkeypatch) -> None:
    today = business_today()
    program = SimpleNamespace(start_date=today, total_workdays=2)
    end = rules_mod.program_end_date(today, 2)
    item = SimpleNamespace(outcome=None, list_date=today, candidate_id=5)
    monkeypatch.setattr(trainee_program, "_own_item", AsyncMock(return_value=item))
    monkeypatch.setattr(
        trainee_program, "_locked_candidate", AsyncMock(return_value=_candidate())
    )
    monkeypatch.setattr(trainee_program, "program_for", AsyncMock(return_value=program))
    add_call = AsyncMock()
    monkeypatch.setattr(trainee_program, "_add_call", add_call)

    with pytest.raises(HTTPException) as exc:
        await trainee_program.record_outcome(
            SimpleNamespace(), USER, 1, "later", _next_workday_after(end)
        )
    assert exc.value.status_code == 422
    assert end.strftime("%d.%m.%Y") in exc.value.detail
    add_call.assert_not_called()


async def test_later_on_the_last_program_day_is_accepted(monkeypatch) -> None:
    today = business_today()
    program = SimpleNamespace(start_date=today, total_workdays=3)
    end = rules_mod.program_end_date(today, 3)
    item = SimpleNamespace(outcome=None, list_date=today, candidate_id=5)
    monkeypatch.setattr(trainee_program, "_own_item", AsyncMock(return_value=item))
    monkeypatch.setattr(
        trainee_program, "_locked_candidate", AsyncMock(return_value=_candidate())
    )
    monkeypatch.setattr(trainee_program, "program_for", AsyncMock(return_value=program))
    monkeypatch.setattr(
        trainee_program, "_add_call", lambda *a, **kw: SimpleNamespace(id=9)
    )
    monkeypatch.setattr(trainee_program, "_close", lambda *a, **kw: None)
    monkeypatch.setattr(
        trainee_program, "_item_response", AsyncMock(return_value={"ok": True})
    )
    db = SimpleNamespace(flush=AsyncMock(), commit=AsyncMock())
    if end <= today:
        pytest.skip("program kończy się dziś — brak dnia po dziś w programie")

    result = await trainee_program.record_outcome(db, USER, 1, "later", end)

    assert result == {"ok": True}
    assert item.later_date == end


def test_promotion_pins_open_callbacks_too() -> None:
    """`_pin_people` pyta też o oddzwonienia bez późniejszej pozycji."""
    import inspect

    source = inspect.getsource(trainee_program._pin_people)
    assert 'outcome == "later"' in source
    assert "followup.list_date > later_item.list_date" in source


def test_today_view_program_carries_end_date() -> None:
    """Front ustawia `max` w wyborze dnia z `program.end_date`."""
    import inspect

    assert '"end_date": view["end_date"]' in inspect.getsource(
        trainee_program.today_view
    )


# ── R4-11: Luna — pusty koniec pracy nie znaczy „do dziś” ─────────────────

TODAY = date(2026, 9, 24)


def test_luna_empty_end_is_undated_not_present() -> None:
    cv = "Kierownik sprzedaży 2012, firma X"
    parsed = {
        "work": [{"start": "2012-01", "end": None, "quote": "Kierownik sprzedaży 2012"}]
    }
    _s, work, _p = academy_rules.facts_from_model(parsed, cv, TODAY)
    assert work is not None
    assert work.periods == ()
    assert work.undated == 1

    parsed = {
        "work": [{"start": "2012-01", "end": "", "quote": "Kierownik sprzedaży 2012"}]
    }
    _s, work, _p = academy_rules.facts_from_model(parsed, cv, TODAY)
    assert work is not None and work.periods == () and work.undated == 1


@pytest.mark.parametrize(
    "quote",
    [
        "Asystent HR od 2024 do chwili obecnej",
        "Asystent HR 2024 – obecnie",
        "Asystent HR 2024 – present",
        "Asystent HR od 2024, nadal",
    ],
)
def test_luna_empty_end_with_explicit_ongoing_quote_counts_to_today(quote) -> None:
    parsed = {"work": [{"start": "2024-01", "end": None, "quote": quote}]}
    _s, work, _p = academy_rules.facts_from_model(parsed, quote, TODAY)
    assert work is not None and len(work.periods) == 1
    assert work.periods[0].end == (TODAY.year, TODAY.month)


def test_luna_empty_end_no_longer_yields_a_permanent_skip() -> None:
    cv = "Specjalista ds. sprzedaży 2010"
    parsed = {
        "work": [
            {"start": "2010-01", "end": None, "quote": "Specjalista ds. sprzedaży 2010"}
        ]
    }
    result = academy_rules.evaluate(
        education=[],
        experience=[],
        languages=[{"code": "PL", "lang": "polski", "level": "native"}],
        model_parsed=parsed,
        cv_text=cv,
        max_experience_years=6,
        require_polish=True,
        today=TODAY,
    )
    assert result.verdict != academy_rules.VERDICT_SKIP
    assert result.facts["experience_years"] is None


needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL")
    or "@localhost:5432/x" in os.environ.get("DATABASE_URL", ""),
    reason="wymaga PostgreSQL",
)


@needs_db
async def test_promotion_pins_a_callback_that_never_happened() -> None:
    """Oddzwonienie „później” bez późniejszej pozycji → przypięte przy awansie;
    oddzwonienie, które się odbyło (późniejsza pozycja), nie jest przypinane."""
    import uuid
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.my_people import MyPeopleOverride
    from app.models.trainee import TraineeCallItem, TraineeCallList
    from app.models.user import User, UserRole

    today = business_today()
    async with AsyncSessionLocal() as db:
        marker = uuid.uuid4().hex[:10]
        trainee = User(
            email=f"r4-trainee-{marker}@example.com",
            name=f"Praktykant {marker}",
            role=UserRole.trainee,
            roles=["trainee"],
            is_active=True,
            profile_completed=True,
        )
        db.add(trainee)
        waiting = Candidate(name="Oddzwoń", lastname=f"R4{marker}")
        called_back = Candidate(name="Oddzwoniony", lastname=f"R4{marker}")
        db.add_all([waiting, called_back])
        await db.flush()
        closed = datetime.now(timezone.utc)
        earlier = TraineeCallList(
            user_id=trainee.id, list_date=today - timedelta(days=7), size=2
        )
        later_list = TraineeCallList(
            user_id=trainee.id, list_date=today - timedelta(days=2), size=1
        )
        db.add_all([earlier, later_list])
        await db.flush()
        for cand in (waiting, called_back):
            db.add(
                TraineeCallItem(
                    list_id=earlier.id,
                    user_id=trainee.id,
                    candidate_id=cand.id,
                    list_date=earlier.list_date,
                    outcome="later",
                    later_date=today + timedelta(days=30),
                    closed_at=closed,
                )
            )
        db.add(
            TraineeCallItem(
                list_id=later_list.id,
                user_id=trainee.id,
                candidate_id=called_back.id,
                list_date=later_list.list_date,
                outcome="declined",
                closed_at=closed,
            )
        )
        await db.flush()
        waiting_id = waiting.id

        pinned = await trainee_program._pin_people(db, trainee.id)
        rows = set(
            (
                await db.execute(
                    select(MyPeopleOverride.candidate_id).where(
                        MyPeopleOverride.user_id == trainee.id
                    )
                )
            )
            .scalars()
            .all()
        )
        await db.rollback()
    assert pinned == 1
    assert rows == {waiting_id}
