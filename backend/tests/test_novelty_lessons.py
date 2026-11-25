"""Lekcje nowości (0760, decyzje Artura 23.11.2026).

Porcja to lekcje na Poligonie: pokaz → sam → pytanie, najwyżej 5 dziennie,
odłożenie raz dziennie do 15:00, pominięcie tylko dla admina, w piątek
powtórka. Testy reguł są bez bazy; przepływ przez API — z bazą (CI).
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from pydantic import ValidationError

from app.api.novelties import apply_lesson_event
from app.data.novelties import (
    LESSONS_FLOOR,
    Lesson,
    Novelty,
    load_lessons,
    load_novelties,
)
from app.models.novelty import NoveltyDailyState, NoveltyLessonProgress
from app.services import novelty_lessons as rules
from app.services.novelty_schema import LESSON_DDL

_DB = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="wymaga PostgreSQL")
BACKEND = Path(__file__).resolve().parent.parent
TZ = ZoneInfo("Europe/Warsaw")
# Wtorek — bez powtórki piątkowej.
TUESDAY = date(2026, 11, 24)
FRIDAY = date(2026, 11, 27)


def _at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=TZ)


def _novelty(nid: str, shipped: date, **extra) -> Novelty:
    return Novelty.model_validate(
        {
            "id": nid,
            "title": f"Wpis {nid}",
            "why": "Po co",
            "tier": "dot",
            "shipped_on": shipped.isoformat(),
            "where": "Rekrutacja → Tablica",
            "href": "/jobs",
            "dot_anchor": "jobs.list.scope",
            **extra,
        }
    )


_QUESTIONS = [
    {
        "q": "Pytanie pierwsze?",
        "options": ["a", "b", "c"],
        "answer": 0,
        "explain": "Bo tak jest.",
    },
    {
        "q": "Pytanie drugie?",
        "options": ["a", "b", "c"],
        "answer": 1,
        "explain": "Bo tak jest.",
    },
]


def _lesson(lid: str, novelties: list[str], **extra) -> Lesson:
    return Lesson.model_validate(
        {
            "id": lid,
            "title": f"Lekcja {lid}",
            "novelties": novelties,
            "task": "Zrób to samodzielnie na Poligonie.",
            "solo_href": "/jobs/990001",
            "check": {"kind": "click", "anchor": "jobs.list.scope"},
            "questions": _QUESTIONS,
            **extra,
        }
    )


def _plans(count: int, *, shipped: date = TUESDAY - timedelta(days=3), done=()):
    novelties = [_novelty(f"wpis-{i:02d}", shipped) for i in range(count)]
    lessons = {
        f"lekcja-{i:02d}": _lesson(f"lekcja-{i:02d}", [f"wpis-{i:02d}"])
        for i in range(count)
    }
    return rules.lesson_plans(novelties, done, lessons)


# ── Rejestr ───────────────────────────────────────────────────────────────────


def test_every_novelty_since_the_floor_is_in_exactly_one_lesson() -> None:
    """Porcja to same lekcje — wpis bez lekcji nie miałby etapu „sam”."""
    owners: dict[str, list[str]] = {}
    for lesson in load_lessons().values():
        for nid in lesson.novelties:
            owners.setdefault(nid, []).append(lesson.id)
    missing = [
        n.id
        for n in load_novelties().values()
        if n.shipped_on >= LESSONS_FLOOR and n.id not in owners
    ]
    assert missing == [], f"Wpisy bez lekcji (dopisz w lessons.json): {missing}"


def test_lesson_rejects_duplicate_answers_and_answer_out_of_range() -> None:
    with pytest.raises(ValidationError):
        _lesson(
            "lekcja-zle",
            ["x"],
            questions=[{**_QUESTIONS[0], "options": ["a", "A", "c"]}, _QUESTIONS[1]],
        )
    with pytest.raises(ValidationError):
        _lesson(
            "lekcja-zle",
            ["x"],
            questions=[{**_QUESTIONS[0], "answer": 3}, _QUESTIONS[1]],
        )
    with pytest.raises(ValidationError):
        _lesson("lekcja-zle", ["x"], questions=[_QUESTIONS[0]])


def test_move_check_needs_feedback() -> None:
    with pytest.raises(ValidationError):
        _lesson("lekcja-ruch", ["x"], check={"kind": "move", "to": "withdrawn"})
    lesson = _lesson(
        "lekcja-ruch",
        ["x"],
        check={
            "kind": "move",
            "to": "withdrawn",
            "feedback": "Karta poszła gdzie indziej.",
        },
    )
    assert lesson.check.kind == "move"


def test_registry_lessons_use_known_novelties_and_real_texts() -> None:
    lessons = load_lessons()
    assert lessons, "lessons.json jest pusty"
    for lesson in lessons.values():
        assert not re.search(r"/api/|\bPR\b|#\d{3,}", lesson.task), lesson.id


def test_step_that_says_click_is_not_passed_with_understood() -> None:
    """Krok, który każe coś kliknąć albo przejść, przechodzi kliknięciem, nie „Rozumiem”.

    25.11.2026 pokaz „Monit płatności” miał krok 1 „Przejdź na zakładkę
    „Po terminie”” z `ack`: „Rozumiem” przepuszczało dalej bez zmiany zakładki,
    a krok 2 („Lista na koniec miesiąca”) stoi tylko w „Po terminie” — pokaz
    kończył się „Nie widzę tego miejsca”, a zadanie „sam” wymaga właśnie tej
    drogi. Ostatni krok wpisu może być `ack` (nic po nim nie czeka)."""
    imperative = re.compile(
        r"(Kliknij|Przejdź|Otwórz|Wybierz|Wejdź|Rozwiń|Zaznacz|Przesuń|Wpisz)\b"
    )
    wrong = [
        (novelty.id, i, step.anchor)
        for novelty in load_novelties().values()
        for i, step in enumerate(novelty.steps[:-1])
        if step.ack and imperative.match(step.text)
    ]
    assert wrong == [], (
        f"Krok „Rozumiem” każe coś zrobić, a następny krok tego wymaga: {wrong}"
    )


def test_lesson_show_starts_where_its_first_step_is_not_on_the_jobs_list() -> None:
    """Pokaz lekcji zaczyna tam, gdzie jest element, a nie na liście `/jobs`.

    24.11.2026 pokaz „Arkusz rozmowy” startował na liście i pisał „Nie widzę
    tego miejsca”: wpis nowości miał tylko `href` listy, a „Tryb rozmowy” jest
    w panelu osoby na rekrutacji ćwiczebnej. Pokaz idzie na
    `practice_href ?? href` wpisu (`practiceHref` w `lib/novelties/lessons.ts`),
    a pierwszy krok wpisu bez kroków to jego kropka (`withSteps`). Na liście
    stoją tylko kotwice `jobs.list.*`; reszta potrzebuje `practice_href`
    (np. `/jobs/990001?candidate=…&panel=screening`)."""
    novelties = load_novelties()

    def first_anchor(nid: str) -> str:
        novelty = novelties[nid]
        return novelty.steps[0].anchor if novelty.steps else novelty.dot_anchor

    def show_start(nid: str) -> str:
        return novelties[nid].practice_href or novelties[nid].href

    wrong = [
        (lesson.id, nid, first_anchor(nid))
        for lesson in load_lessons().values()
        for nid in lesson.novelties
        if show_start(nid).split("?")[0] == "/jobs"
        and not first_anchor(nid).startswith("jobs.list.")
    ]
    assert wrong == [], (
        f"Pokaz na liście /jobs, element gdzie indziej (dopisz practice_href): {wrong}"
    )


# ── Porcja dnia ──────────────────────────────────────────────────────────────


def test_daily_plan_caps_at_five_and_leaves_the_rest_for_later() -> None:
    plans = _plans(8)
    plan = rules.daily_plan(plans, {}, TUESDAY, 1, LESSONS_FLOOR)
    assert len(plan.today) == rules.DAILY_LIMIT and plan.later == 3
    assert all(not review for _, review in plan.today)


def test_todays_novelties_wait_until_tomorrow_and_legacy_done_does_not_return() -> None:
    old = _plans(2, done=["wpis-00"])
    today = rules.lesson_plans(
        [_novelty("wpis-dzis", TUESDAY)],
        [],
        {"lekcja-dzis": _lesson("lekcja-dzis", ["wpis-dzis"])},
    )
    plan = rules.daily_plan(old + today, {}, TUESDAY, 1, LESSONS_FLOOR)
    # Przeklikany przed lekcjami wpis nie wraca; dzisiejszy czeka do jutra.
    assert [p.lesson.id for p, _ in plan.today] == ["lekcja-01"]


def test_completing_a_lesson_does_not_pull_the_next_one_today() -> None:
    plans = _plans(7)
    done = {
        "lekcja-00": rules.LessonRow(
            shown_at=_at(TUESDAY, 8),
            solo_passed_at=_at(TUESDAY, 8, 5),
            completed_at=_at(TUESDAY, 8, 6),
        )
    }
    plan = rules.daily_plan(plans, done, TUESDAY, 1, LESSONS_FLOOR)
    ids = [p.lesson.id for p, _ in plan.today]
    assert ids == ["lekcja-00", "lekcja-01", "lekcja-02", "lekcja-03", "lekcja-04"]
    assert rules.open_count(plan, done, TUESDAY) == 4


def test_friday_review_picks_three_from_this_week_inside_the_limit() -> None:
    plans = _plans(9, shipped=FRIDAY - timedelta(days=7))
    rows = {
        f"lekcja-{i:02d}": rules.LessonRow(
            shown_at=_at(FRIDAY - timedelta(days=2), 9),
            solo_passed_at=_at(FRIDAY - timedelta(days=2), 9),
            completed_at=_at(FRIDAY - timedelta(days=2), 9),
        )
        for i in range(4)
    }
    plan = rules.daily_plan(plans, rows, FRIDAY, 7, LESSONS_FLOOR)
    reviews = [p.lesson.id for p, review in plan.today if review]
    assert len(reviews) == rules.REVIEW_COUNT
    assert set(reviews) <= set(rows)
    assert len(plan.today) == rules.DAILY_LIMIT
    # Ten sam dzień i ta sama osoba = ta sama powtórka po odświeżeniu.
    again = rules.daily_plan(plans, rows, FRIDAY, 7, LESSONS_FLOOR)
    assert [p.lesson.id for p, r in again.today if r] == reviews


def test_no_review_on_other_days() -> None:
    plans = _plans(3)
    rows = {
        "lekcja-00": rules.LessonRow(completed_at=_at(TUESDAY - timedelta(days=1), 9))
    }
    assert rules.review_picks(plans, rows, TUESDAY, 1) == []


def test_lesson_state_follows_the_stages() -> None:
    assert rules.lesson_state(None) == "todo"
    assert rules.lesson_state(rules.LessonRow(shown_at=_at(TUESDAY, 8))) == "shown"
    assert (
        rules.lesson_state(
            rules.LessonRow(shown_at=_at(TUESDAY, 8), solo_failed_count=1)
        )
        == "retry"
    )
    assert rules.lesson_state(rules.LessonRow(completed_at=_at(TUESDAY, 9))) == "done"


# ── Odłożenie ────────────────────────────────────────────────────────────────


def test_postpone_options_end_at_three_pm() -> None:
    morning = _at(TUESDAY, 8, 40)
    assert [o["key"] for o in rules.postpone_options(morning)] == [
        "30min",
        "12:00",
        "15:00",
    ]
    afternoon = _at(TUESDAY, 13, 0)
    assert [o["key"] for o in rules.postpone_options(afternoon)] == ["30min", "15:00"]
    assert rules.postpone_until("30min", _at(TUESDAY, 14, 45)) is None
    assert rules.postpone_options(_at(TUESDAY, 15, 1)) == []


def test_postpone_once_a_day_and_not_again_after_postponing_yesterday() -> None:
    now = _at(TUESDAY, 9)
    assert rules.can_postpone(None, None, 2, now, TUESDAY) is True
    assert rules.can_postpone(None, None, 0, now, TUESDAY) is False
    used = rules.DayRow(day=TUESDAY, postponed_until=_at(TUESDAY, 12))
    assert rules.can_postpone(used, None, 2, now, TUESDAY) is False
    yesterday = rules.DayRow(
        day=TUESDAY - timedelta(days=1), postponed_until=_at(TUESDAY, 12)
    )
    assert rules.can_postpone(None, yesterday, 2, now, TUESDAY, carried=True) is False
    long_ago = rules.DayRow(
        day=TUESDAY - timedelta(days=10), postponed_until=_at(TUESDAY, 12)
    )
    assert rules.can_postpone(None, long_ago, 2, now, TUESDAY, carried=True) is True
    # Poniedziałek po piątkowym odłożeniu z zaległą lekcją: bez odkładania.
    friday = TUESDAY - timedelta(days=4)
    monday = TUESDAY - timedelta(days=1)
    after_weekend = rules.DayRow(day=friday, postponed_until=_at(friday, 12))
    assert (
        rules.can_postpone(None, after_weekend, 2, _at(monday, 9), monday, carried=True)
        is False
    )


# ── Zdarzenia lekcji ─────────────────────────────────────────────────────────


def _row(**values) -> NoveltyLessonProgress:
    row = NoveltyLessonProgress(user_id=1, lesson_id="lekcja-x")
    row.shown_count = 0
    row.solo_failed_count = 0
    row.quiz_wrong_count = 0
    for key, value in values.items():
        setattr(row, key, value)
    return row


def _status(exc: pytest.ExceptionInfo[HTTPException]) -> tuple[int, Optional[str]]:
    detail = exc.value.detail
    return exc.value.status_code, detail.get("code") if isinstance(
        detail, dict
    ) else None


def test_solo_needs_the_show_and_completion_needs_the_solo() -> None:
    now = _at(TUESDAY, 9)
    row = _row()
    with pytest.raises(HTTPException) as exc:
        apply_lesson_event(row, "solo_passed", now)
    assert _status(exc) == (409, "show_first")
    with pytest.raises(HTTPException) as exc:
        apply_lesson_event(row, "completed", now)
    assert _status(exc) == (409, "solo_first")

    assert apply_lesson_event(row, "shown", now) is False
    apply_lesson_event(row, "solo_failed", now)
    apply_lesson_event(row, "solo_passed", now)
    # Dwa razy źle na pytanie → powrót do pokazu kasuje samodzielne zaliczenie.
    apply_lesson_event(row, "restart", now)
    with pytest.raises(HTTPException):
        apply_lesson_event(row, "completed", now)
    apply_lesson_event(row, "solo_passed", now)
    assert apply_lesson_event(row, "completed", now) is True
    assert apply_lesson_event(row, "completed", now) is False
    assert (row.shown_count, row.solo_failed_count) == (1, 1)


def test_failed_review_sends_the_lesson_back_to_the_show() -> None:
    now = _at(FRIDAY, 9)
    row = _row(shown_at=now, solo_passed_at=now, completed_at=now)
    apply_lesson_event(row, "review_failed", now)
    assert (
        row.completed_at is None and row.shown_at is None and row.solo_passed_at is None
    )
    assert rules.lesson_state(rules.LessonRow(review_failed_at=now)) == "todo"


# ── Schemat ───────────────────────────────────────────────────────────────────


def test_migration_and_entrypoint_use_the_one_ddl_source() -> None:
    entrypoint = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    assert "_NOVELTY_LESSON_DDL = list(_novelty_schema.LESSON_DDL)" in entrypoint
    assert "*_NOVELTY_LESSON_DDL," in entrypoint
    migration = (BACKEND / "alembic/versions/0760_novelty_lessons.py").read_text(
        encoding="utf-8"
    )
    assert "from app.services.novelty_schema import LESSON_DDL" in migration


@pytest.mark.parametrize(
    ("ddl", "model"),
    [(LESSON_DDL[0], NoveltyLessonProgress), (LESSON_DDL[2], NoveltyDailyState)],
)
def test_models_match_the_ddl(ddl: str, model) -> None:
    columns = set(
        re.findall(r"^\s+([a-z_]+) (?:INTEGER|VARCHAR|TIMESTAMPTZ|DATE)", ddl, re.M)
    )
    assert columns == set(model.__table__.columns.keys())


# ── Trasy (z bazą) ────────────────────────────────────────────────────────────


async def _user(
    role: str, roles: list[str] | None = None
) -> tuple[int, dict[str, str]]:
    from app.core.database import AsyncSessionLocal
    from app.core.security import create_access_token
    from app.models.user import User, UserRole

    tag = uuid.uuid4().hex[:8]
    values = roles or [role]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"lekcje-{role}-{tag}@example.com",
            name=f"Lekcje {role} {tag}",
            role=UserRole(role),
            roles=values,
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        token = create_access_token(
            user.id,
            role,
            roles=values,
            authorization_version=user.authorization_version,
        )
        return user.id, {"Authorization": f"Bearer {token}"}


@pytest.fixture
def one_lesson(monkeypatch):
    """Jeden wpis rekrutera z wczoraj w jednej lekcji; zegar porcji na 8:30."""
    from app.api import novelties as api

    today = datetime.now(TZ).date()
    yesterday = today - timedelta(days=1)
    novelty = _novelty("test-lekcja-wpis", yesterday, audience={"roles": ["recruiter"]})
    lesson = _lesson("lekcja-test", [novelty.id])
    monkeypatch.setattr(api, "load_novelties", lambda: {novelty.id: novelty})
    monkeypatch.setattr(api, "load_lessons", lambda: {lesson.id: lesson})
    monkeypatch.setattr(api, "DAILY_FLOOR", yesterday - timedelta(days=7))
    monkeypatch.setattr(
        api, "_utcnow", lambda: _at(today, 8, 30).astimezone(timezone.utc)
    )
    return lesson


@_DB
@pytest.mark.asyncio
async def test_lesson_flow_blocks_until_done_alone_and_marks_the_novelty(
    app_client: AsyncClient, one_lesson
) -> None:
    _, recruiter = await _user("recruiter")
    _, finance = await _user("finance")
    daily = (await app_client.get("/api/novelties/daily", headers=recruiter)).json()
    assert [lesson["id"] for lesson in daily["lessons"]] == ["lekcja-test"]
    assert daily["enforced"] is True and (daily["done"], daily["total"]) == (0, 1)
    assert daily["can_skip"] is False and daily["can_postpone"] is True
    other = (await app_client.get("/api/novelties/daily", headers=finance)).json()
    assert other["lessons"] == [] and other["enforced"] is False

    url = "/api/novelties/lessons/lekcja-test/events"
    early = await app_client.post(url, json={"event": "solo_passed"}, headers=recruiter)
    assert early.status_code == 409
    for event in ("shown", "solo_passed", "quiz_wrong", "completed"):
        resp = await app_client.post(url, json={"event": event}, headers=recruiter)
        assert resp.status_code == 204, (event, resp.text)

    daily = (await app_client.get("/api/novelties/daily", headers=recruiter)).json()
    assert daily["enforced"] is False and (daily["done"], daily["total"]) == (1, 1)
    assert daily["lessons"][0]["state"] == "done"
    mine = (await app_client.get("/api/novelties/lessons", headers=recruiter)).json()
    assert mine[0]["id"] == "lekcja-test" and mine[0]["state"] == "done"
    assert daily["items"][0]["done"] is True  # wpis zaliczony jako „tour”

    refused = await app_client.post(url, json={"event": "shown"}, headers=finance)
    assert refused.status_code == 404


@_DB
@pytest.mark.asyncio
async def test_postpone_once_then_conflict_and_only_admin_skips(
    app_client: AsyncClient, one_lesson
) -> None:
    _, recruiter = await _user("recruiter")
    _, admin = await _user("admin", ["admin", "recruiter"])
    resp = await app_client.post(
        "/api/novelties/daily/postpone", json={"option": "12:00"}, headers=recruiter
    )
    assert resp.status_code == 200, resp.text
    daily = (await app_client.get("/api/novelties/daily", headers=recruiter)).json()
    assert daily["enforced"] is False and daily["postponed_until"] is not None
    assert daily["can_postpone"] is False
    again = await app_client.post(
        "/api/novelties/daily/postpone", json={"option": "15:00"}, headers=recruiter
    )
    assert again.status_code == 409

    assert (
        await app_client.post("/api/novelties/daily/skip", headers=recruiter)
    ).status_code == 403
    daily = (await app_client.get("/api/novelties/daily", headers=admin)).json()
    assert daily["can_skip"] is True and daily["enforced"] is True
    assert (
        await app_client.post("/api/novelties/daily/skip", headers=admin)
    ).status_code == 200
    daily = (await app_client.get("/api/novelties/daily", headers=admin)).json()
    assert daily["enforced"] is False and daily["skipped"] is True
    # Pominięcie niczego nie zalicza.
    assert daily["lessons"][0]["state"] == "todo"


def test_page_check_is_not_met_on_the_starting_screen() -> None:
    """Warunek „ekran” spełniony już na ekranie startowym zaliczyłby zadanie
    samym wejściem — osoba ma do niego dojść sama."""
    from urllib.parse import parse_qs, urlparse

    instant = []
    for lesson in load_lessons().values():
        check = lesson.check
        if check.kind != "page":
            continue
        start = urlparse(lesson.solo_href)
        query = {k: v[0] for k, v in parse_qs(start.query).items()}
        prefix = check.path_prefix.rstrip("/")
        on_path = start.path == prefix or start.path.startswith(f"{prefix}/")
        if on_path and all(query.get(k) == v for k, v in check.query.items()):
            instant.append(lesson.id)
    assert instant == []


@_DB
@pytest.mark.asyncio
async def test_hor_sees_who_is_stuck_after_three_failed_solo_tries(
    app_client: AsyncClient, one_lesson
) -> None:
    user_id, recruiter = await _user("recruiter")
    _, hor = await _user("head_of_recruitment")
    url = "/api/novelties/lessons/lekcja-test/events"
    await app_client.post(url, json={"event": "shown"}, headers=recruiter)
    for _ in range(3):
        await app_client.post(url, json={"event": "solo_failed"}, headers=recruiter)
    refused = await app_client.get(
        "/api/novelties/lessons/struggles", headers=recruiter
    )
    assert refused.status_code == 403
    stuck = (
        await app_client.get("/api/novelties/lessons/struggles", headers=hor)
    ).json()
    mine = [s for s in stuck if s["user_id"] == user_id]
    assert (
        mine
        and mine[0]["solo_failed_count"] == 3
        and mine[0]["lesson_id"] == "lekcja-test"
    )


def test_failed_review_lesson_returns_to_the_next_porcja() -> None:
    """Zaliczenie lekcji zalicza jej wpisy, więc „przeklikane przed lekcjami”
    nie może zdjąć z porcji lekcji, która oblała powtórkę."""
    plans = _plans(1, shipped=FRIDAY - timedelta(days=10), done=["wpis-00"])
    failed = {"lekcja-00": rules.LessonRow(review_failed_at=_at(FRIDAY, 9))}
    monday = FRIDAY + timedelta(days=3)
    plan = rules.daily_plan(plans, failed, monday, 1, LESSONS_FLOOR)
    assert [p.lesson.id for p, _ in plan.today] == ["lekcja-00"]
    # Bez oblanej powtórki wpis przeklikany przed lekcjami nadal nie wraca.
    assert rules.daily_plan(plans, {}, monday, 1, LESSONS_FLOOR).today == []


def test_postponing_on_monday_does_not_block_the_rest_of_the_week() -> None:
    monday = TUESDAY - timedelta(days=1)
    postponed_monday = rules.DayRow(day=monday, postponed_until=_at(monday, 12))
    now = _at(TUESDAY, 9)
    # Wtorek po poniedziałkowym odłożeniu z zaległą lekcją: bez odkładania.
    assert (
        rules.can_postpone(None, postponed_monday, 2, now, TUESDAY, carried=True)
        is False
    )
    # Wtorek, ale poniedziałkowe lekcje zrobione — dzisiejsze nowe można odłożyć.
    assert (
        rules.can_postpone(None, postponed_monday, 2, now, TUESDAY, carried=False)
        is True
    )
    # Środa: poniedziałek to nie „wczoraj”.
    wednesday = TUESDAY + timedelta(days=1)
    assert (
        rules.can_postpone(
            None, postponed_monday, 2, _at(wednesday, 9), wednesday, carried=True
        )
        is True
    )
