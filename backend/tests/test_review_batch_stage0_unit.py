"""Etap 0 porcji dnia (audyt 08.11.2026) — logika bez bazy."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.datastructures import QueryParams

from app.api.proposals_bulk import _found_via_meta
from app.models.user import UserRole
from app.services import review_batch as rb
from app.services import review_batch_order as order
from app.services import review_batch_streams as streams
from app.services import review_batch_team as team
from app.services.known_queue_points import KnownFacts

NOW = datetime(2026, 11, 9, 9, 0, tzinfo=timezone.utc)


def _card(pid, score, *, cid=None, facts=None, **kw) -> rb.PendingCard:
    return rb.PendingCard(
        process_id=pid,
        job_id=1,
        candidate_id=cid if cid is not None else 1000 + pid,
        owner_id=None,
        score=score,
        opened_at=NOW,
        facts=facts,
        **kw,
    )


def _known(points: int) -> KnownFacts:
    return KnownFacts(
        points=points,
        client_points=0,
        note_points=points,
        verified_at_client=0,
        last_note_days=12,
    )


# ── P7: kolejność jak na Tablicy ────────────────────────────────────────────


def test_known_points_beat_higher_score_like_on_the_board():
    plain = _card(1, 72.0)
    known = _card(2, 70.0, facts=order.OrderFacts(known=_known(8)))
    assert [c.process_id for c in order.order_cards([plain, known])] == [2, 1]


def test_tiers_mirror_order_new_column():
    gap = _card(1, 95.0, missing_must=("Java",))
    caution = _card(2, 90.0, cautions=({"key": "budget"},))
    clean = _card(3, 70.0)
    fresh = _card(4, 66.0, facts=order.OrderFacts(fresh_first=True))
    ordered = order.order_cards([gap, caution, clean, fresh])
    assert [c.process_id for c in ordered] == [4, 3, 2, 1]


def test_every_fifth_place_goes_to_person_without_process():
    cards = [_card(i, 90.0 - i) for i in range(1, 6)]
    cards[-1] = _card(5, 40.0, facts=order.OrderFacts(fresh=True))
    ordered = order.order_cards(cards)
    assert ordered[4].process_id == 5


def test_plan_owners_follows_board_rank_not_raw_score():
    high = _card(1, 90.0)
    low = _card(2, 60.0)
    # Ranga stawia słabszy wynik pierwszy, więc to on trafia do osoby z kolejki.
    plan = rb.plan_owners([high, low], [7, 8], seed="x", rank={2: 0, 1: 1})
    assert set(plan) == {1, 2} and plan[1] != plan[2]
    first_owner = rb.plan_owners([low], [7, 8], seed="x")[2]
    assert plan[2] == first_owner


# ── S-C4: premia ────────────────────────────────────────────────────────────


@pytest.fixture
def porcja_on(monkeypatch):
    monkeypatch.setattr(rb.settings, "REVIEW_BATCH_ENABLED", True, raising=False)


@pytest.mark.usefixtures("porcja_on")
def test_bonus_active_and_in_budget():
    assert order.bonus_for("actively_looking", 150, "PLN", 170.0).points == 8
    assert order.bonus_for("open_to_offers", 150, "PLN", 170.0).points == 3
    assert order.bonus_for("actively_looking", None, None, 170.0).points == 5


@pytest.mark.usefixtures("porcja_on")
@pytest.mark.parametrize(
    ("rate", "currency", "budget"),
    [
        (180, "PLN", 170.0),  # ponad budżet
        (150, "EUR", 170.0),  # nieporównywalna waluta
        (150, "PLN", None),  # brak budżetu
        (5, "PLN", 170.0),  # literówka w stawce
    ],
)
def test_no_budget_bonus_when_rate_is_not_a_known_fit(rate, currency, budget):
    assert order.bonus_for(None, rate, currency, budget).in_budget is False


def test_bonus_is_zero_while_batch_is_off(monkeypatch):
    monkeypatch.setattr(rb.settings, "REVIEW_BATCH_ENABLED", False, raising=False)
    assert order.bonus_for("actively_looking", 150, "PLN", 170.0).points == 0


def test_bonus_changes_order_but_not_the_score():
    plain = _card(1, 76.0)
    active = _card(
        2, 74.0, facts=order.OrderFacts(bonus=order.Bonus(active=True, in_budget=True))
    )
    ordered = order.order_cards([plain, active])
    assert ordered[0].process_id == 2 and ordered[0].score == 74.0


@pytest.mark.parametrize("value", [49.9, 95.1])
def test_min_score_out_of_range_is_refused(value):
    assert rb.validation_error(rb.BatchSettings(min_score=value)) is not None


def test_min_score_inside_range_passes():
    assert rb.validation_error(rb.BatchSettings(min_score=70.0)) is None


def test_card_below_custom_min_score_is_not_in_batch():
    assert rb.in_batch(_card(1, 68.0), NOW, 70.0) is False
    assert rb.in_batch(_card(1, 68.0), NOW) is True


# ── P5: kiedy wyjście się liczy ─────────────────────────────────────────────


def test_rejection_counts_when_it_happened():
    assert rb.counted_at_for("rejected", NOW, [], []) == NOW


def test_screening_without_follow_up_does_not_count():
    assert rb.counted_at_for("screening", NOW, [], []) is None


def test_going_back_to_screening_is_not_closing():
    later = [("screening", NOW + timedelta(hours=1))]
    assert rb.counted_at_for("screening", NOW, later, []) is None


def test_saved_screening_closes_at_save_time():
    saved = NOW + timedelta(hours=3)
    assert rb.counted_at_for("screening", NOW, [], [saved]) == saved


def test_screening_saved_before_the_move_counts_at_the_move():
    saved = NOW - timedelta(minutes=5)
    assert rb.counted_at_for("screening", NOW, [], [saved]) == NOW


def test_minimum_reached_at_is_the_nth_decision():
    times = (NOW, NOW + timedelta(hours=1), NOW + timedelta(hours=2))
    assert team.minimum_reached_at(times, 2) == NOW + timedelta(hours=1)
    assert team.minimum_reached_at(times, 4) is None
    assert team.minimum_reached_at(times, 0) is None


# ── P9: własna praca przechodzi ─────────────────────────────────────────────

_ME = SimpleNamespace(id=7, has_role=lambda r: r == UserRole.recruiter)


@pytest.fixture
def my_team(monkeypatch):
    async def _teams(_db, job_ids):
        return {job_id: [7] if job_id == 100 else [9] for job_id in job_ids}

    monkeypatch.setattr(rb, "recruiter_ids_for_jobs", _teams)


@pytest.mark.usefixtures("my_team")
@pytest.mark.parametrize(
    "query",
    [
        "added_by_user_id=7",
        "stage_moved_by=7&pipeline_stage=rejected&stage_moved_after=2026-11-01",
        "contacted_by=7&contacted=yes",
        "stage_moved_by=7&rejection_by=us",
        "recruitment_id=100",
        "recruitment_id=100&recruitment_match=assigned",
        "added_by_user_id=7&q=Kowalski",
    ],
)
async def test_own_work_filters_pass_the_block(query):
    assert await rb.is_broad_list_query(None, QueryParams(query), _ME) is False


@pytest.mark.usefixtures("my_team")
@pytest.mark.parametrize(
    "query",
    [
        "added_by_user_id=9",  # cudze id
        "added_by_user_id=7&added_by_user_id=9",
        "added_by_user_id=0",  # „system”
        "stage_moved_by=9",
        "contacted_by=9&contacted=yes",
        "contacted_by=7",  # bez „contacted=yes” nie zawęża listy
        "pipeline_stage=rejected&contacted_by=7",
        "rejection_by=us&contacted_by=7&contacted=no",
        "recruitment_id=200",  # rekrutacja spoza zespołu
        "recruitment_id=100&recruitment_id=200",
        "recruitment_id=abc",
        "recruitment_id=100&recruitment_match=not_assigned",
        "pipeline_stage=rejected",  # samo zawężenie to przeszukanie bazy
        "rejection_by=us",
        "added_by_user_id=7&skills_required=java",  # własna praca + umiejętność
        "added_by_user_id=7&q=senior+java+developer",  # własna praca + opis
    ],
)
async def test_foreign_or_broad_filters_stay_blocked(query):
    assert await rb.is_broad_list_query(None, QueryParams(query), _ME) is True


@pytest.mark.usefixtures("porcja_on", "my_team")
async def test_foreign_filter_gets_423_and_own_filter_does_not(monkeypatch):
    async def _settings(_db):
        return rb.BatchSettings(minimum=10)

    async def _status(_db, _user, *, now):
        return rb.BatchStatus(
            enabled=True,
            applies=True,
            minimum=10,
            done_today=0,
            pending=5,
            required=5,
            met=False,
        )

    async def _skip(*_args, **_kwargs):
        return None

    monkeypatch.setattr(rb, "read_settings", _settings)
    monkeypatch.setattr(rb, "status_for", _status)
    monkeypatch.setattr(rb, "_record_block", _skip)
    monkeypatch.setattr(rb, "_now", lambda: NOW)
    user = SimpleNamespace(
        id=7,
        has_role=lambda r: r == UserRole.recruiter,
    )

    await rb.assert_list_search_allowed(None, user, QueryParams("added_by_user_id=7"))
    with pytest.raises(HTTPException) as exc:
        await rb.assert_list_search_allowed(
            None, user, QueryParams("added_by_user_id=9")
        )
    assert exc.value.status_code == 423


# ── P4 ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("found_via", "source", "expected"),
    [
        (None, "manual_search", "search"),
        (None, "talent_radar", "search"),
        (None, "proposal_inbox", "proposals"),
        ("outside_base", "quick_add", "outside_base"),
    ],
)
def test_found_via_from_source(found_via, source, expected):
    assert _found_via_meta(found_via, source) == {"found_via": expected}


def test_found_via_unknown_source_writes_nothing():
    assert _found_via_meta(None, None) is None


def _week(total: int, complete: bool = True) -> dict:
    return {"all": total, "complete": complete}


def test_stop_needs_two_full_weeks_below_limit():
    # Baza 170,5 na tydzień, próg 153,45.
    assert streams.stop_triggered([_week(150), _week(140)]) is True


def test_one_bad_week_is_not_a_stop():
    assert streams.stop_triggered([_week(170), _week(140)]) is False


def test_running_week_does_not_count():
    assert streams.stop_triggered([_week(150), _week(10, complete=False)]) is False


def test_no_data_is_not_a_stop():
    assert streams.stop_triggered([]) is False


# ── Nowość zależna od przełącznika ──────────────────────────────────────────


def test_novelty_requires_known_setting():
    from app.data.novelties import Novelty

    with pytest.raises(ValidationError):
        Novelty(
            id="x-y",
            title="T",
            why="W",
            tier="dot",
            shipped_on="2026-11-08",
            where="Tu",
            href="/x",
            dot_anchor="a.b",
            requires_setting="NO_SUCH_FLAG",
        )


def test_batch_novelty_follows_the_flag(monkeypatch):
    from app.data.novelties import load_novelties

    novelty = load_novelties()["porcja-dnia-od-nexusa"]
    monkeypatch.setattr(rb.settings, "REVIEW_BATCH_ENABLED", False, raising=False)
    assert novelty.switched_on() is False
    monkeypatch.setattr(rb.settings, "REVIEW_BATCH_ENABLED", True, raising=False)
    assert novelty.switched_on() is True
