"""Poranna porcja jako lekcje (decyzje Artura 23.11.2026).

Przeklikanie nie uczyło: od 19.11 mediana 12 s na nowość, 61% przeklikań to
sam „Rozumiem”. Teraz nowość przechodzi się w lekcji na Poligonie:

1. pokaz — kroki wpisów z podświetleniem (dawne przeklikanie),
2. sam — zadanie bez podświetlenia, zalicza warunek ``check`` lekcji,
3. pytanie „po co / kiedy”.

Nie wyszło samemu albo dwa razy źle na pytanie → z powrotem do pokazu.
Najwyżej ``DAILY_LIMIT`` lekcji dziennie (Olaf, 23.11: „nie chcę mieć z rana
40 funkcji”), porcję można odłożyć raz dziennie najpóźniej do 15:00, a admin
może ją pominąć. W piątek dochodzi powtórka: 3 lekcje zaliczone w tym
tygodniu, od razu etap „sam”; nieudana wraca jako lekcja od pokazu.

Funkcje są czyste (bez bazy), żeby reguły porcji dało się przetestować
bez Postgresa; endpointy w ``app/api/novelties.py``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Literal, Optional
from zoneinfo import ZoneInfo

from app.core.scheduling import DEFAULT_TZ
from app.data.novelties import Lesson, Novelty, load_lessons

#: Najwyżej tyle lekcji dziennie (razem z powtórką piątkową).
DAILY_LIMIT = 5
#: Ile lekcji z tygodnia wraca w piątek do powtórki.
REVIEW_COUNT = 3
#: Piątek (``date.weekday()``).
REVIEW_WEEKDAY = 4
#: Odłożyć można najpóźniej do tej godziny (Europe/Warsaw).
POSTPONE_LATEST = time(15, 0)

PostponeOption = Literal["30min", "12:00", "15:00"]
POSTPONE_LABELS: dict[str, str] = {
    "30min": "Za 30 min",
    "12:00": "Na 12:00",
    "15:00": "Na 15:00",
}

LessonState = Literal["todo", "shown", "retry", "done"]


@dataclass(frozen=True)
class LessonRow:
    """Stan osoby w lekcji — kopia wiersza ``novelty_lesson_progress``."""

    shown_at: Optional[datetime] = None
    solo_failed_count: int = 0
    solo_passed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None
    review_failed_at: Optional[datetime] = None


@dataclass(frozen=True)
class DayRow:
    """Porcja osoby w jednym dniu — kopia wiersza ``novelty_daily_state``."""

    day: date
    postponed_until: Optional[datetime] = None
    skipped_at: Optional[datetime] = None


@dataclass
class LessonPlan:
    """Lekcja osoby: tylko wpisy z jej roli, w kolejności pokazu."""

    lesson: Lesson
    novelties: list[Novelty]
    shipped_on: date
    #: Wpisy przeklikane przed lekcjami (zaliczone w ``novelty_progress``) —
    #: lekcja, której wszystkie wpisy osoba już przeszła, nie wraca.
    legacy_done: bool = False


@dataclass
class DailyPlan:
    today: list[tuple[LessonPlan, bool]] = field(default_factory=list)
    """Lekcje na dziś: (lekcja, czy to powtórka piątkowa)."""
    later: int = 0


def _local(moment: datetime) -> datetime:
    return moment.astimezone(ZoneInfo(DEFAULT_TZ))


def lesson_plans(
    novelties: Collection[Novelty],
    done_novelty_ids: Collection[str],
    lessons: Optional[Mapping[str, Lesson]] = None,
) -> list[LessonPlan]:
    """Lekcje, w których osoba ma choć jeden wpis ze swojej roli, po dacie.

    ``novelties`` to wpisy z roli osoby (odbiorcy, sekcja, przełącznik).
    Wpis bez lekcji (wpis sprzed ``LESSONS_FLOOR``) nie trafia do lekcji."""
    lessons = load_lessons() if lessons is None else lessons
    mine = {n.id: n for n in novelties}
    done = set(done_novelty_ids)
    plans: list[LessonPlan] = []
    for lesson in lessons.values():
        members = [mine[nid] for nid in lesson.novelties if nid in mine]
        if not members:
            continue
        plans.append(
            LessonPlan(
                lesson=lesson,
                novelties=members,
                shipped_on=min(n.shipped_on for n in members),
                legacy_done=all(n.id in done for n in members),
            )
        )
    return sorted(plans, key=lambda p: (p.shipped_on, p.lesson.title))


def lesson_state(row: Optional[LessonRow]) -> LessonState:
    if row is None:
        return "todo"
    if row.completed_at is not None:
        return "done"
    if row.shown_at is not None and row.solo_failed_count > 0:
        return "retry"
    if row.shown_at is not None:
        return "shown"
    return "todo"


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def review_picks(
    plans: list[LessonPlan],
    rows: Mapping[str, LessonRow],
    today: date,
    user_id: int,
) -> list[LessonPlan]:
    """Piątek: 3 lekcje zaliczone od poniedziałku do wczoraj, stały wybór na
    dany dzień (hash osoby i daty), żeby lista nie skakała po odświeżeniu."""
    if today.weekday() != REVIEW_WEEKDAY:
        return []
    monday = _week_start(today)

    def eligible(plan: LessonPlan) -> bool:
        row = rows.get(plan.lesson.id)
        if row is None or row.completed_at is None:
            return False
        completed_on = _local(row.completed_at).date()
        if not monday <= completed_on < today:
            return False
        # Powtórka z dziś zostaje na liście (z wynikiem).
        return True

    pool = [p for p in plans if eligible(p)]

    def order(plan: LessonPlan) -> str:
        seed = f"{user_id}:{today.isoformat()}:{plan.lesson.id}".encode()
        return hashlib.sha256(seed).hexdigest()

    return sorted(pool, key=order)[:REVIEW_COUNT]


def review_state(row: Optional[LessonRow], today: date) -> str:
    """``todo`` / ``passed`` / ``failed`` powtórki z dzisiaj."""
    if row is None:
        return "todo"
    if row.reviewed_at is not None and _local(row.reviewed_at).date() == today:
        return "passed"
    if (
        row.review_failed_at is not None
        and _local(row.review_failed_at).date() == today
    ):
        return "failed"
    return "todo"


def daily_plan(
    plans: list[LessonPlan],
    rows: Mapping[str, LessonRow],
    today: date,
    user_id: int,
    floor: date,
) -> DailyPlan:
    """Lekcje na dziś: powtórka piątkowa, zaliczone dziś i zaległe — razem
    najwyżej ``DAILY_LIMIT``. Dzisiejsze wpisy czekają do jutra, więc lista
    nie rośnie w ciągu dnia; zaliczenie lekcji nie wciąga następnej."""

    def completed_today(plan: LessonPlan) -> bool:
        row = rows.get(plan.lesson.id)
        return (
            row is not None
            and row.completed_at is not None
            and _local(row.completed_at).date() == today
        )

    in_window = [p for p in plans if floor <= p.shipped_on < today]
    reviews = review_picks(plans, rows, today, user_id)
    review_ids = {p.lesson.id for p in reviews}
    done_today = [
        p for p in in_window if completed_today(p) and p.lesson.id not in review_ids
    ]
    pending = [
        p
        for p in in_window
        if not p.legacy_done
        and lesson_state(rows.get(p.lesson.id)) != "done"
        and p.lesson.id not in review_ids
    ]
    slots = max(0, DAILY_LIMIT - len(reviews) - len(done_today))
    chosen = pending[:slots]
    today_list = (
        [(p, True) for p in reviews]
        + [(p, False) for p in done_today]
        + [(p, False) for p in chosen]
    )
    return DailyPlan(today=today_list, later=len(pending) - len(chosen))


def open_count(plan: DailyPlan, rows: Mapping[str, LessonRow], today: date) -> int:
    """Ile pozycji z dzisiejszej listy jeszcze czeka."""
    count = 0
    for lesson_plan, review in plan.today:
        row = rows.get(lesson_plan.lesson.id)
        if review:
            count += review_state(row, today) == "todo"
        else:
            count += lesson_state(row) != "done"
    return count


def postpone_until(option: str, now: datetime) -> Optional[datetime]:
    """Godzina, do której porcja milczy, albo ``None``, gdy ta opcja już
    nie ma sensu (minęła albo wypada po 15:00)."""
    local = _local(now)
    latest = datetime.combine(local.date(), POSTPONE_LATEST, tzinfo=local.tzinfo)
    if option == "30min":
        until = local + timedelta(minutes=30)
    elif option in ("12:00", "15:00"):
        hour = int(option.split(":")[0])
        until = datetime.combine(local.date(), time(hour, 0), tzinfo=local.tzinfo)
    else:
        return None
    if until <= local or until > latest:
        return None
    return until


def postpone_options(now: datetime) -> list[dict[str, str]]:
    return [
        {"key": key, "label": label, "until": until.isoformat()}
        for key, label in POSTPONE_LABELS.items()
        if (until := postpone_until(key, now)) is not None
    ]


def can_postpone(
    today_row: Optional[DayRow],
    previous_row: Optional[DayRow],
    open_items: int,
    now: datetime,
    today: date,
) -> bool:
    """Raz dziennie, do 15:00, gdy coś czeka. Kto odłożył wczoraj (ostatni
    dzień z porcją) i nie skończył, dziś odkładać nie może."""
    if open_items == 0:
        return False
    if today_row is not None and today_row.postponed_until is not None:
        return False
    if (
        previous_row is not None
        and previous_row.postponed_until is not None
        and previous_row.day >= today - timedelta(days=4)
    ):
        return False
    return bool(postpone_options(now))


def shape_lesson(
    plan: LessonPlan,
    row: Optional[LessonRow],
    *,
    review: bool,
    today: date,
    novelty_items: list[dict[str, Any]],
) -> dict[str, Any]:
    lesson = plan.lesson
    return {
        "id": lesson.id,
        "title": lesson.title,
        "task": lesson.task,
        "solo_href": lesson.solo_href,
        "check": lesson.check.model_dump(),
        "questions": [q.model_dump() for q in lesson.questions],
        "shipped_on": plan.shipped_on.isoformat(),
        "novelties": novelty_items,
        "state": lesson_state(row),
        "solo_failed_count": row.solo_failed_count if row else 0,
        "review": review,
        "review_state": review_state(row, today) if review else None,
    }
