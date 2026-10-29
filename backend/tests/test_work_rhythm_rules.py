"""Reguły „Rytmu dnia” (Insights, decyzje Artura 28.10.2026) — bez bazy."""

from datetime import date, datetime

import pytest

from app.services.work_rhythm import (
    DEFAULT_RULES,
    RHYTHM_START,
    clamp_window,
    day_index,
    diagnose,
    hour_level,
    hour_points,
    intensity_level,
    meeting_hours,
    period_index,
    rules_from_json,
    work_hours,
)

RULES = rules_from_json(None)


def test_defaults_match_decision():
    assert RULES.weights["screening"] == 5
    assert RULES.weights["action"] == 1
    assert RULES.hour_levels == (4, 11, 25)
    assert RULES.norm_work_hours == 7
    assert RULES.norm_day_points == 120


def test_partial_saved_rules_keep_defaults():
    rules = rules_from_json({"weights": {"screening": 8}, "norm_day_points": 100})
    assert rules.weights["screening"] == 8
    assert rules.weights["note"] == DEFAULT_RULES["weights"]["note"]
    assert rules.norm_day_points == 100
    assert rules.norm_work_hours == 7


def test_hour_points_use_weights_and_ignore_unknown_kinds():
    assert hour_points({"screening": 2, "action": 3, "nieznany": 10}, RULES) == 13


@pytest.mark.parametrize(
    ("points", "level"),
    [(0, 0), (0.5, 1), (3.5, 1), (4, 2), (10.9, 2), (11, 3), (24, 3), (25, 4), (80, 4)],
)
def test_hour_level_thresholds(points, level):
    assert hour_level(points, RULES) == level


def test_work_hours_count_meetings_without_actions_only_in_8_to_18():
    points = {7: 30.0, 9: 4.0, 10: 3.9, 18: 50.0}
    # 7 i 18 poza oknem, 10 za mało punktów, ale 10 i 14 mają spotkanie.
    assert work_hours(points, meetings=[10, 14], rules=RULES) == 3


def test_day_index_full_day_and_caps_at_100():
    points = {h: 30.0 for h in range(8, 18)}
    assert day_index(points, [], RULES) == 100


def test_day_index_half_and_half():
    # 7 godzin po 4 pkt = pełne pokrycie, 28 pkt z 120 = 0,23.
    points = {h: 4.0 for h in range(9, 16)}
    assert day_index(points, [], RULES) == round((1 + 28 / 120) / 2 * 100)


def test_full_leave_day_is_not_counted():
    assert day_index({9: 50.0}, [], RULES, available=0) is None


def test_half_day_leave_halves_the_norms():
    # 3,5 h po 4 pkt i 60 pkt to pełny dzień przy pół dnia urlopu.
    points = {9: 15.0, 10: 15.0, 11: 15.0, 12: 15.0}
    assert day_index(points, [], RULES, available=0.5) == 100
    assert day_index(points, [], RULES) < 100


def test_empty_working_day_is_zero_not_missing():
    assert day_index({}, [], RULES) == 0


def test_period_index_skips_leave_days():
    assert period_index([100, None, 50]) == 75
    assert period_index([None, None]) is None


@pytest.mark.parametrize(
    ("index", "level"), [(75, "high"), (74, "mid"), (50, "mid"), (49, "low")]
)
def test_intensity_levels(index, level):
    assert intensity_level(index, RULES) == level


@pytest.mark.parametrize(
    ("index", "pct", "diag"),
    [
        (90, 120, "model"),
        (90, 40, "quality"),
        (40, 120, "more_volume"),
        (40, 40, "more_work"),
        (60, 80, "model"),
        (59, 79, "more_work"),
    ],
)
def test_diagnosis_quadrants(index, pct, diag):
    assert diagnose(index, pct, RULES) == diag


def test_diagnosis_needs_both_numbers():
    assert diagnose(None, 100, RULES) is None
    assert diagnose(80, None, RULES) is None


def test_meeting_hours_need_30_minutes_in_the_hour():
    s = datetime(2026, 10, 20, 9, 40)
    e = datetime(2026, 10, 20, 11, 15)
    # 9:40–10:00 = 20 min (nie), 10–11 pełna, 11:00–11:15 = 15 min (nie).
    assert meeting_hours(s, e) == [(date(2026, 10, 20), 10)]


def test_window_defaults_to_last_10_business_days_but_not_before_12_10():
    start, end = clamp_window(None, None, today=date(2026, 10, 29))
    assert end == date(2026, 10, 29)
    assert start == date(2026, 10, 16)
    start, _ = clamp_window(None, None, today=date(2026, 10, 14))
    assert start == RHYTHM_START


def test_window_caps_length_and_future():
    start, end = clamp_window(
        date(2026, 10, 12), date(2027, 1, 31), today=date(2026, 12, 31)
    )
    assert end == date(2026, 12, 31)
    assert (end - start).days == 30


# ── Kto co widzi i odmowa złych reguł ───────────────────────────────────────


def _user(*roles):
    from app.models.user import User, UserRole

    return User(
        id=1,
        email="x@example.com",
        name="Test",
        role=UserRole(roles[0]),
        roles=list(roles),
    )


@pytest.mark.parametrize(
    ("roles", "allowed"),
    [
        (("recruiter",), False),
        (("talent_community_manager",), False),
        (("delivery_lead",), False),
        (("finance",), False),
        (("head_of_recruitment",), True),
        (("head_of_recruitment", "recruiter"), True),
        (("admin",), True),
    ],
)
def test_only_hor_and_admin_see_and_edit(roles, allowed):
    """Decyzja Artura 29.10.2026: na razie tylko Head of Recruitment i admin."""
    from app.api.insights_work_rhythm import can_edit_rules
    from app.services.work_rhythm import VIEWER_ROLES

    user = _user(*roles)
    assert user.has_any_role(*VIEWER_ROLES) is allowed
    assert can_edit_rules(user) is allowed


def _payload(**over):
    from app.services.work_rhythm import DEFAULT_RULES

    data = {**DEFAULT_RULES, "weights": dict(DEFAULT_RULES["weights"])}
    data.update(over)
    return data


def test_valid_rules_payload_round_trips():
    from app.api.insights_work_rhythm import WorkRhythmRulesIn

    parsed = WorkRhythmRulesIn(**_payload(norm_day_points=100))
    assert rules_from_json(parsed.model_dump()).norm_day_points == 100


@pytest.mark.parametrize(
    "over",
    [
        {"hour_levels": [11, 4, 25]},
        {"hour_levels": [4, 11]},
        {"level_mid": 80, "level_high": 75},
        {"weights": {"screening": 5}},
        {"weights": {**DEFAULT_RULES["weights"], "screening": 50}},
        {"norm_work_hours": 0},
    ],
)
def test_invalid_rules_are_refused(over):
    from pydantic import ValidationError

    from app.api.insights_work_rhythm import WorkRhythmRulesIn

    with pytest.raises(ValidationError):
        WorkRhythmRulesIn(**_payload(**over))


def test_days_before_account_creation_are_not_counted():
    from datetime import timezone

    from app.services.work_rhythm import account_start

    user = _user("recruiter")
    # 18.10 23:30 UTC = 19.10 01:30 w Warszawie.
    user.created_at = datetime(2026, 10, 18, 23, 30, tzinfo=timezone.utc)
    assert account_start(user) == date(2026, 10, 19)


def test_unfinished_today_does_not_enter_period_numbers():
    """Rano dzisiejszy dzień ma pół akcji — nie może zaniżać okresu (przegląd 29.10)."""
    from app.services.work_rhythm import summarize_days

    def d(index, *, in_progress=False):
        return {
            "before_start": False,
            "in_progress": in_progress,
            "leave": 0.0,
            "index": index,
            "work_hours": 5,
            "day_points": 80.0,
        }

    days = [d(64) for _ in range(9)] + [d(10, in_progress=True)]
    summary = summarize_days(days)
    assert summary["index"] == 64
    assert summary["worked_days"] == 9
    assert summary["leave_days"] == 0


def test_only_nexus_preps_count_as_meetings():
    """Decyzja Artura 29.10.2026: cykliczne „Spotkania” bez uczestników to blokady
    kalendarza (ok. 12,5 tys. od 12.10) — godzinę pracy daje tylko prep z NEXUSA."""
    from app.services.work_rhythm import _MEETINGS_SQL

    sql = " ".join(_MEETINGS_SQL.split())
    assert "FROM prep_meetings" in sql
    assert "JOIN calendar_events" in sql
    assert "microsoft365" not in sql


@pytest.mark.parametrize(
    ("roles", "shown"),
    [
        (("recruiter",), True),
        (("recruiter", "talent_community_manager", "delivery_lead"), True),
        (("delivery_lead", "recruiter"), True),
        (("talent_community_manager", "recruiter"), True),
        (("talent_community_manager",), False),
        (("delivery_lead",), False),
        (("admin", "head_of_recruitment", "recruiter"), False),
        (("head_of_recruitment", "recruiter"), False),
    ],
)
def test_everyone_with_recruiter_role_is_shown(roles, shown):
    """Decyzja Artura 29.10.2026: każdy z rolą rekrutera (też DL), bez samych
    TCM; HoR i admin to widzowie, nie wiersze."""
    from app.services.work_rhythm import is_rhythm_person

    assert is_rhythm_person(_user(*roles)) is shown


# ── Ochrona przed nabijaniem (decyzja Artura 29.10.2026) ────────────────────


def _ev(minute, kind="action", src="act", act="x", ent="1", hour=10, day=20, second=0):
    from app.services.work_rhythm import Event

    return Event(
        uid=7,
        ts=datetime(2026, 10, day, hour, minute, second),
        kind=kind,
        src=src,
        act=act,
        ent=ent,
    )


def _classify(events, **over):
    from app.services.work_rhythm import classify_events

    rules = rules_from_json(over or None)
    return [(round(p, 2), r) for _, p, r in classify_events(events, rules)]


def test_guard_defaults():
    r = RULES
    assert r.weights["contact"] == 1
    assert (r.auto_cv_points, r.stage_return_points) == (0, 0)
    assert (r.screening_per_candidate_day, r.repeats_per_hour) == (1, 1)
    assert (r.views_per_hour, r.bulk_per_minute) == (4, 10)
    assert (r.contacts_per_day, r.thin_hour_candidates) == (10, 2)


def test_auto_generated_cv_scores_nothing():
    out = _classify(
        [
            _ev(1, kind="cv", src="cv", act="auto"),
            _ev(2, kind="cv", src="cv", act="manual", ent="2"),
        ]
    )
    assert out == [(0, "automat"), (3, None)]


def test_same_candidate_screening_counts_once_a_day():
    evs = [
        _ev(1, kind="screening", act="screening_form_saved", ent="5"),
        _ev(30, kind="screening", src="note", act="card", ent="5", hour=14),
        _ev(31, kind="screening", act="screening_form_saved", ent="6", hour=14),
    ]
    assert _classify(evs) == [(5, None), (0, "powtorka"), (5, None)]


def test_same_save_counts_once_per_hour():
    evs = [
        _ev(1, act="recommendation_card_updated", ent="5"),
        _ev(40, act="recommendation_card_updated", ent="5"),
        _ev(5, act="recommendation_card_updated", ent="5", hour=11),
    ]
    assert _classify(evs) == [(1, None), (0, "powtorka"), (1, None)]


def test_views_dedupe_and_cap_per_hour():
    evs = [_ev(i, kind="view", act="document_downloaded", ent=str(i)) for i in range(6)]
    evs.append(_ev(10, kind="view", act="document_downloaded", ent="0"))
    out = _classify(evs)
    assert [r for _, r in out] == [None] * 4 + ["limit_podgladow"] * 2 + ["powtorka"]
    assert sum(p for p, _ in out) == 2


def test_bulk_action_counts_as_one():
    evs = [
        _ev(3, kind="action", src="stage", act="new", ent=f"{i}:1", second=i)
        for i in range(12)
    ]
    out = _classify(evs)
    assert out[0] == (1, None)
    assert all(r == "masowa" for _, r in out[1:])


def test_below_bulk_threshold_counts_each():
    evs = [
        _ev(3, kind="action", src="stage", act="new", ent=f"{i}:1", second=i)
        for i in range(9)
    ]
    assert all(r is None for _, r in _classify(evs))


def test_card_back_to_same_stage_same_day_scores_nothing():
    evs = [
        _ev(1, src="stage", act="screening", ent="5:1"),
        _ev(2, src="stage", act="new", ent="5:1"),
        _ev(3, src="stage", act="screening", ent="5:1"),
    ]
    assert _classify(evs) == [(1, None), (1, None), (0, "powrot")]


def test_contact_attempts_capped_per_day():
    evs = [
        _ev(i, kind="contact", src="note", act="contact_attempt", ent=str(i))
        for i in range(12)
    ]
    out = _classify(evs)
    assert sum(p for p, _ in out) == 10
    assert [r for _, r in out][-2:] == ["limit_kontaktu", "limit_kontaktu"]


def test_zero_limit_means_no_limit():
    evs = [_ev(i, kind="view", act="document_downloaded", ent=str(i)) for i in range(8)]
    assert all(r is None for _, r in _classify(evs, views_per_hour=0))


def test_thin_hour_is_not_a_work_hour():
    """4 ruchy jednej karty to 4 pkt, ale nie godzina pracy (furtka „podtrzymywania”)."""
    from app.services.work_rhythm import thin_hours

    evs = [_ev(i, src="stage", act=f"s{i}", ent="5:1") for i in range(4)]
    counted = [(e, p, r) for e, (p, r) in zip(evs, _classify(evs))]
    assert thin_hours(counted, RULES) == {10}
    assert work_hours({10: 4.0}, [], RULES, thin={10}) == 0


def test_screening_alone_makes_a_work_hour():
    from app.services.work_rhythm import classify_events, thin_hours

    evs = [_ev(1, kind="screening", act="screening_form_saved", ent="5")]
    assert thin_hours(classify_events(evs, RULES), RULES) == set()


def test_guard_payload_validated():
    from pydantic import ValidationError

    from app.api.insights_work_rhythm import WorkRhythmRulesIn

    WorkRhythmRulesIn(**_payload(views_per_hour=0, bulk_per_minute=20))
    for bad in (
        {"views_per_hour": -1},
        {"auto_cv_points": 30},
        {"thin_hour_candidates": 50},
    ):
        with pytest.raises(ValidationError):
            WorkRhythmRulesIn(**_payload(**bad))


@pytest.mark.parametrize(
    ("src", "act", "label"),
    [
        ("stage", "cv_sent", "Ruch karty → CV Wysłane"),
        ("note", "contact_attempt", "Próba kontaktu („nie odbiera”)"),
        ("act", "document_downloaded", "Podgląd dokumentu"),
        ("act", "cos_nowego", "Inny zapis (cos_nowego)"),
        ("cv", "auto", "CV z automatu"),
    ],
)
def test_event_labels_for_day_breakdown(src, act, label):
    from app.services.work_rhythm import event_label

    assert event_label(src, act) == label


def test_candidate_id_from_entity():
    from app.services.work_rhythm import candidate_id_of

    assert candidate_id_of("stage", "15:7") == 15
    assert candidate_id_of("act", "42") == 42
    assert candidate_id_of("act", "candidate_stage_cv/9") is None
    assert candidate_id_of("email", "m3") is None


def test_light_hour_is_not_marked_thin():
    """Godzina poniżej progu i tak nie jest godziną pracy — bez znacznika."""
    from app.services.work_rhythm import classify_events, thin_hours

    evs = [
        _ev(1, src="stage", act="a", ent="5:1"),
        _ev(2, src="stage", act="b", ent="5:1"),
    ]
    assert thin_hours(classify_events(evs, RULES), RULES) == set()


def test_cv_without_candidate_is_its_own_entity():
    """CV z wgranego pliku nie ma kandydata — nie może zlepiać się z innymi
    w „ponowny zapis” (przegląd 29.10.2026)."""
    from app.services.work_rhythm import _EVENTS_SQL

    sql = " ".join(_EVENTS_SQL.split())
    assert "'g' || g.id" in sql
