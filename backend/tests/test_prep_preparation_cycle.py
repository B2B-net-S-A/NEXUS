"""Przygotowanie rekrutera jako trzeci prep (F3, decyzje Artura z 24.11.2026).

Przygotowanie ma ``prep_no`` 0 i stoi przed Prepem 1 z Delivery Leadem.
Na start jest opcjonalne: krok, planowanie i zaproszenie są, ale bez zadań,
plakietek i dzwonków o braku. Kandydat dostaje spotkania numerowane po kolei
(spotkanie 1–3), a nagranie trafia do notatki bez oceny (ocena to F4).
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.services import prep_availability as pa
from app.services import prep_invitation, prep_labels
from app.services.interview_cycle import (
    LATE_PREP_META,
    PREPARATION_RECORDED_META,
    PREPARATION_SKIPPED_META,
    EventRef,
    PairSnapshot,
    _prep_agenda_entry,
    assign_prep_ordinals,
    compute_badge,
    compute_steps,
    compute_todos,
    current_step_key,
)
from app.services.prep_review_scoring import preparation_note_content

NOW = datetime(2031, 6, 10, 12, 0, tzinfo=timezone.utc)


def _ev(eid: int, start: datetime, **extra) -> EventRef:
    return EventRef(
        id=eid,
        start=start,
        end=start + timedelta(minutes=45),
        title="E",
        status="scheduled",
        **extra,
    )


def _pair(*, iv_in: timedelta, preps: list[EventRef], **extra) -> PairSnapshot:
    return PairSnapshot(
        1,
        2,
        interview=_ev(9, NOW + iv_in),
        preps=assign_prep_ordinals(preps),
        **extra,
    )


def _steps(pair: PairSnapshot) -> dict[str, dict]:
    return {s["key"]: s for s in compute_steps(pair, NOW, call_window_minutes=30)}


def _kinds(pair: PairSnapshot) -> list[str]:
    return [
        t["kind"]
        for t in compute_todos(
            pair, NOW, call_window_minutes=30, user_id=11, is_dl_view=True
        )
    ]


# ── Numeracja ────────────────────────────────────────────────────────────────


def test_preparation_keeps_number_zero_and_sorts_first() -> None:
    """Do 24.11 ``if p.prep_no`` traktował 0 jak prep spoza NEXUSA: samotne
    Przygotowanie zostawało „Prepem 1”, a z Prepem 1 — „Prepem 2”."""
    prep0 = _ev(1, NOW + timedelta(days=1), prep_no=0)
    prep1 = _ev(2, NOW + timedelta(days=2), prep_no=1)
    outlook = _ev(3, NOW + timedelta(days=2, hours=3))  # prep spoza NEXUSA
    out = assign_prep_ordinals([outlook, prep1, prep0])
    assert [(p.id, p.ordinal) for p in out] == [(1, 0), (2, 1), (3, 2)]


def test_preparation_alone_does_not_fill_the_prep1_slot() -> None:
    pair = _pair(
        iv_in=timedelta(days=3), preps=[_ev(1, NOW + timedelta(days=1), prep_no=0)]
    )
    assert pair.prep_slot(1) is None
    assert pair.prep_slot(0) is not None
    steps = _steps(pair)
    assert steps["prep0"]["state"] == "scheduled"
    assert steps["prep"]["state"] == "current"
    assert _kinds(pair) == ["prep_missing"]


def test_preparation_and_prep1_still_ask_for_prep2() -> None:
    preps = [
        _ev(1, NOW - timedelta(days=1), prep_no=0),
        _ev(2, NOW - timedelta(hours=3), prep_no=1),
    ]
    pair = _pair(iv_in=timedelta(days=2), preps=preps)
    assert pair.prep_slot(2) is None
    assert _kinds(pair) == ["prep2_missing"]


# ── Opcjonalne na start: bez zadań, plakietek i dzwonków ─────────────────────


def test_unplanned_preparation_is_visible_but_never_the_current_step() -> None:
    pair = _pair(iv_in=timedelta(days=3), preps=[])
    steps = compute_steps(pair, NOW, call_window_minutes=30)
    by_key = {s["key"]: s for s in steps}
    assert [s["key"] for s in steps][2:5] == ["prep0", "prep", "prep2"]
    assert by_key["prep0"]["state"] == "todo"
    assert by_key["prep"]["state"] == "current"
    assert current_step_key(steps) == "prep"
    assert "prep0_missing" not in _kinds(pair)


def test_missing_preparation_gives_no_badge_even_a_day_before() -> None:
    preps = [
        _ev(2, NOW - timedelta(hours=5), prep_no=1),
        _ev(3, NOW + timedelta(hours=2), prep_no=2),
    ]
    pair = _pair(iv_in=timedelta(hours=20), preps=preps)
    badge = compute_badge(pair, NOW, call_window_minutes=30)
    assert badge is not None and badge["kind"] == "prep2"
    assert _kinds(pair) == []


def test_all_preps_scheduled_lands_in_the_preparation_column() -> None:
    preps = [
        _ev(1, NOW + timedelta(days=1), prep_no=0),
        _ev(2, NOW + timedelta(days=2), prep_no=1),
        _ev(3, NOW + timedelta(days=3), prep_no=2),
    ]
    steps = compute_steps(
        _pair(iv_in=timedelta(days=4), preps=preps), NOW, call_window_minutes=30
    )
    assert current_step_key(steps) == "prep0"


def test_preparation_is_skipped_once_prep1_started_without_it() -> None:
    pair = _pair(
        iv_in=timedelta(days=1), preps=[_ev(2, NOW - timedelta(hours=1), prep_no=1)]
    )
    step = _steps(pair)["prep0"]
    assert step["state"] == "skipped"
    assert step["meta"] == PREPARATION_SKIPPED_META


def test_late_preparation_is_overdue_without_a_todo() -> None:
    iv_start = NOW + timedelta(days=1)
    late = _ev(5, iv_start + timedelta(hours=2), prep_no=0)
    pair = PairSnapshot(
        1,
        2,
        interview=_ev(9, iv_start),
        preps=assign_prep_ordinals([_ev(2, NOW + timedelta(hours=2), prep_no=1)]),
        late_preps=assign_prep_ordinals([late]),
    )
    step = _steps(pair)["prep0"]
    assert step["state"] == "overdue"
    assert step["meta"] == LATE_PREP_META
    assert "prep_late" not in _kinds(pair)


def test_recorded_preparation_has_no_quality_until_f4() -> None:
    done = _ev(1, NOW - timedelta(days=1), prep_no=0, transcript_status="fetched")
    pair = _pair(iv_in=timedelta(days=1), preps=[done])
    step = _steps(pair)["prep0"]
    assert step["state"] == "done"
    assert step["meta"] == PREPARATION_RECORDED_META
    assert step["quality"] is None
    unrecorded = _ev(1, NOW - timedelta(days=1), prep_no=0, transcript_status="missing")
    kinds = _kinds(_pair(iv_in=timedelta(days=1), preps=[unrecorded]))
    assert "prep_unrecorded" not in kinds


def test_preparation_alone_is_not_a_prep_done_badge() -> None:
    pair = _pair(
        iv_in=timedelta(days=3), preps=[_ev(1, NOW - timedelta(hours=2), prep_no=0)]
    )
    badge = compute_badge(pair, NOW, call_window_minutes=30)
    assert badge is not None and badge["kind"] == "slot"


def test_refused_preparation_badge_names_the_meeting() -> None:
    refused = _ev(1, NOW + timedelta(days=1), prep_no=0, candidate_response="declined")
    badge = compute_badge(
        _pair(iv_in=timedelta(days=3), preps=[refused]), NOW, call_window_minutes=30
    )
    assert badge is not None and badge["label"] == "Przygotowanie: kandydat odrzucił"


def test_agenda_entry_of_preparation_has_its_own_kind() -> None:
    prep0 = assign_prep_ordinals([_ev(1, NOW + timedelta(days=1), prep_no=0)])[0]
    entry = _prep_agenda_entry({}, prep0, NOW, late=False)
    assert entry["kind"] == "prep0"
    assert entry["from_nexus"] is True


# ── Nazwy i zaproszenie ──────────────────────────────────────────────────────


def test_labels_agree_with_neuter_preparation() -> None:
    assert prep_labels.with_participle(0, "zaplanowany") == "Przygotowanie zaplanowane"
    assert prep_labels.with_participle(2, "zaplanowany") == "Prep 2 zaplanowany"
    assert prep_labels.agree(0, "słaby") == "słabe"
    assert prep_labels.genitive(0) == "przygotowania"
    assert prep_labels.step_key(0) == "prep0"


def test_candidate_gets_meetings_numbered_one_to_three_with_preparation() -> None:
    assert prep_invitation.meeting_number(0, has_preparation=False) == 1
    assert prep_invitation.meeting_number(1, has_preparation=True) == 2
    assert prep_invitation.meeting_number(2, has_preparation=True) == 3
    # Bez Przygotowania tytuły jak dotąd: Prep 1 bez numeru, Prep 2 drugi.
    assert prep_invitation.meeting_number(1, has_preparation=False) is None
    assert prep_invitation.meeting_number(2, has_preparation=False) == 2
    titles = [
        prep_invitation.title(n, "Jan Testowy", "Bank Przykładowy", number=no)
        for n, no in ((0, 1), (1, 2), (2, 3))
    ]
    assert [t.rsplit(" - ", 1)[1] for t in titles] == [
        "Jan Testowy (spotkanie 1)",
        "Jan Testowy (spotkanie 2)",
        "Jan Testowy (spotkanie 3)",
    ]
    assert len(set(titles)) == 3


def test_invitation_text_says_which_preparatory_meeting_it_is() -> None:
    def lead(prep_no: int, number: int | None) -> str:
        body = prep_invitation.text(
            prep_no=prep_no,
            client_name="Bank Przykładowy",
            job_title="Analityk",
            interview_start=None,
            note=None,
            organizer_name="Rekruterka",
            number=number,
        )
        return body.split("\n\n")[1]

    assert lead(0, 1).startswith("Zapraszam na pierwsze spotkanie przygotowujące")
    assert lead(1, 2).startswith("Zapraszam na drugie spotkanie przygotowujące")
    assert lead(2, 3).startswith("Zapraszam na trzecie spotkanie przygotowujące")
    assert lead(1, None).startswith("Zapraszam na spotkanie przygotowujące")


def test_preparation_note_has_facts_and_no_rating() -> None:
    note = preparation_note_content(talk_share=0.61, duration_seconds=24 * 60)
    assert note.startswith("# Przygotowanie")
    assert "Czas: 24 min · kandydat mówił 61% czasu" in note
    assert "Ocena:" not in note


# ── Podpowiedź godzin ────────────────────────────────────────────────────────

WAW = ZoneInfo("Europe/Warsaw")
# Wtorek 20.10.2026, 11:00; rozmowa u klienta w czwartek 22.10 o 14:30.
TUE = datetime(2026, 10, 20, 11, 0, tzinfo=WAW)
THU_INTERVIEW = datetime(2026, 10, 22, 14, 30, tzinfo=WAW)


def _local(options) -> list[str]:
    return [o.start.astimezone(WAW).strftime("%a %d.%m %H:%M") for o in options]


def test_preparation_is_suggested_as_early_as_possible_before_prep1() -> None:
    prep0 = pa.suggest(prep_no=0, interview_start=THU_INTERVIEW, now=TUE, busy=None)
    prep1 = pa.suggest(prep_no=1, interview_start=THU_INTERVIEW, now=TUE, busy=None)
    # Dwa dni robocze przed rozmową to dziś — od 13:00 (≥ 2 h od teraz),
    # podpowiedzi nie nachodzą na siebie.
    assert _local(prep0) == ["Tue 20.10 13:00", "Tue 20.10 14:00", "Tue 20.10 15:00"]
    assert prep0[0].start < prep1[0].start


def test_preparation_ends_before_a_scheduled_prep1() -> None:
    prep1_start = datetime(2026, 10, 21, 9, 0, tzinfo=WAW)
    out = pa.suggest(
        prep_no=0,
        interview_start=THU_INTERVIEW,
        now=datetime(2026, 10, 20, 17, 0, tzinfo=WAW),
        busy=None,
        candidate_windows=[(time(8, 0), time(20, 0))],
        end_by=prep1_start,
    )
    assert out and all(o.end <= prep1_start for o in out)


def test_prep1_is_suggested_after_the_preparation() -> None:
    after = datetime(2026, 10, 21, 12, 0, tzinfo=WAW)
    out = pa.suggest(
        prep_no=1, interview_start=THU_INTERVIEW, now=TUE, busy=None, not_before=after
    )
    assert out and all(o.start >= after for o in out)


async def test_recorded_preparation_gets_a_note_and_no_review(monkeypatch) -> None:
    """Nagrane Przygotowanie (F3): notatka z faktami z Teams, bez modelu i bez
    oceny według listy Prepu 1 — ocena przygotowania to F4."""
    from types import SimpleNamespace

    from app.services import prep_review

    called: list = []
    monkeypatch.setattr(prep_review, "_call_model", lambda *a: called.append(a))
    prep = SimpleNamespace(
        id=1, job_id=2, candidate_id=3, prep_no=0, organizer_user_id=4
    )
    transcript = SimpleNamespace(
        plain_text="Rekruter: Dzień dobry.", talk_share=0.55, duration_seconds=1800
    )
    added: list = []
    notes: list = []

    class _Db:
        async def get(self, model, _id):
            return prep if model.__name__ == "PrepMeeting" else SimpleNamespace(id=2)

        async def scalar(self, statement):
            return transcript if "prep_transcripts" in str(statement) else None

        def add(self, obj):
            added.append(obj)

        async def commit(self):
            return None

    async def upsert_note(db, p, t, content):
        notes.append(content)

    monkeypatch.setattr(prep_review, "_upsert_note", upsert_note)
    assert await prep_review.review_prep(_Db(), 1) is None
    assert called == [] and added == []
    assert notes and notes[0].startswith("# Przygotowanie")
    assert "kandydat mówił 55% czasu" in notes[0]


async def test_prep1_suggestions_fall_back_when_the_preparation_order_leaves_none(
    monkeypatch,
) -> None:
    """Przygotowanie zaplanowane po nowej, wcześniejszej rozmowie: Prep 1 „po
    przygotowaniu” nie miałby żadnej godziny, więc podpowiedź liczy się bez
    tej kolejności (okno ostrzeże o kolejności)."""
    from types import SimpleNamespace

    from app.api import prep_meetings as api
    from app.models.calendar_event import CalendarEvent
    from app.models.job import Job
    from app.services import prep_meetings as svc

    now = datetime.now(timezone.utc)
    interview = (
        (now + timedelta(days=6))
        .astimezone(WAW)
        .replace(hour=14, minute=0, second=0, microsecond=0)
    )
    # Przygotowanie już po rozmowie — nic przed rozmową nie jest „po nim”.
    late_preparation = SimpleNamespace(
        start_time=interview + timedelta(hours=3),
        end_time=interview + timedelta(hours=3, minutes=45),
    )

    class _Db:
        async def get(self, model, _id):
            if model is Job:
                return SimpleNamespace(id=_id)
            if model is CalendarEvent:
                return late_preparation
            return None

    async def _noop(*_a, **_kw):
        return None

    async def _summary(*_a, **_kw):
        return {0: None, 1: None, 2: None}

    async def _users(*_a, **_kw):
        return {}

    async def _active(_db, *, candidate_id, job_id, prep_no):
        return SimpleNamespace(calendar_event_id=97) if prep_no == 0 else None

    monkeypatch.setattr(api, "ensure_job_membership", _noop)
    monkeypatch.setattr(svc, "suggestion_summary", _summary)
    monkeypatch.setattr(api, "_active_users", _users)
    monkeypatch.setattr(svc, "app_only_ready", lambda: False)
    monkeypatch.setattr(svc, "active_prep", _active)

    out = await api.prep_suggestions(
        current_user=SimpleNamespace(id=1),
        candidate_id=1,
        job_id=2,
        interview_start=interview,
        candidate_from=None,
        candidate_to=None,
        prep0_minutes=45,
        prep1_minutes=45,
        prep2_minutes=45,
        db=_Db(),
    )
    prep1 = next(p for p in out.preps if p.prep_no == 1)
    assert prep1.options
    assert all(o.end <= interview - pa.PREP1_GAP for o in prep1.options)
