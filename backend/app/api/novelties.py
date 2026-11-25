"""Nowości do przeklikania (0625) — kropki, przeklikanie i panel „kto już umie”.

Treść nowości to rejestr ``app/data/novelties/novelties.json`` (bez danych
domenowych); tabela ``novelty_progress`` trzyma tylko stan osoby przy nowości.

- ``GET /novelties/mine`` i ``POST /novelties/{id}/events`` — każda zalogowana
  osoba, wyłącznie o sobie i o nowościach swojej roli;
- ``GET /novelties/adoption`` i ``POST /novelties/{id}/remind`` — admin i Head
  of Recruitment (decyzja Artura 28.10.2026), bo panel pokazuje imiennie, kto
  jeszcze nie umie;
- ``GET /novelties/daily`` — poranna porcja (decyzja Artura 18.11.2026): przy
  pierwszym wejściu dnia osoba przechodzi to, co weszło do jej roli; potem do
  jutra nic nie wyskakuje. Od 23.11.2026 porcja to lekcje na Poligonie
  (pokaz → sam → pytanie, ``app/services/novelty_lessons.py``), najwyżej 5
  dziennie; ``POST /novelties/daily/postpone`` odkłada je raz dziennie do
  15:00, ``POST /novelties/daily/skip`` — pominięcie dnia, tylko admin;
  ``POST /novelties/lessons/{id}/events`` zapisuje etapy, ``GET
  /novelties/lessons`` to lista dla Szkoleń. Wyłącznik porcji jest osobny od
  Startu (``PUT /novelties/start/gate`` z ``daily``);
- ``GET /novelties/start`` — „Start w NEXUSIE” osoby (``app/data/novelties/start.json``):
  dopóki nie przeklika najważniejszych funkcji swojej roli, front wpuszcza ją
  tylko na pulpit i ekrany przeklikania (decyzja Artura 30.10.2026: twarda
  blokada, wszyscy). ``PUT /novelties/start/gate`` — wyłącznik blokady dla
  admina i HoR, gdyby rano coś zablokowało ludzi (bez deployu).

Moduł ma ``@limiter.limit``, więc bez ``from __future__ import annotations``
(ciało żądania trafiłoby do query → 422).
"""

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Literal, Optional
from zoneinfo import ZoneInfo

import sentry_sdk

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser, CurrentUser, HeadOfRecruitmentPlus
from app.core.database import get_db
from app.core.rate_limit import limiter, user_or_ip_key
from app.core.scheduling import DEFAULT_TZ, business_today
from app.data.novelties import (
    Novelty,
    in_audience,
    load_lessons,
    load_novelties,
    load_poligon,
    load_start_tours,
)
from app.models.app_setting import AppSetting
from app.models.novelty import (
    NoveltyDailyState,
    NoveltyLessonProgress,
    NoveltyProgress,
)
from app.models.user import User
from app.services.action_permissions import named_permissions_of
from app.services.onboarding_day import (
    POLIGON_ID_PREFIX,
    PoligonRequirement,
    poligon_exercises,
    poligon_open,
    poligon_replaces,
    poligon_requirement,
)
from app.services.poligon_luki import (
    FEATURES as LUKI_FEATURES,
    LUKI_KEY,
    campaign_entry,
    credited_exercises,
    default_due,
    feature_usage,
    load_campaign,
    overdue,
    targets as luki_targets,
)
from app.services import novelty_lessons as lessons_rules
from app.services.section_permissions import SectionAccess, section_access_for_user

logger = logging.getLogger(__name__)
router = APIRouter()

NoveltyEvent = Literal[
    "seen", "card_dismissed", "postponed", "toured", "used", "dot_clicked", "broken"
]

#: Zdarzenie, które zalicza nowość, i jak to zapisujemy. ``broken`` to
#: „Coś nie działa — zalicz i dalej” (Artur, 25.11.2026): zepsute ćwiczenie
#: nie może nikogo zatrzymać, a ślad zostaje w logu i Sentry (`_report_broken`).
_COMPLETING: dict[str, str] = {
    "toured": "tour",
    "used": "used",
    "dot_clicked": "dot",
    "broken": "used",
}

#: Nowości z obowiązkowym oknem (odłożyć można raz, do rana). Drobiazg
#: zalicza pierwsze kliknięcie kropki.
MANDATORY_TIERS = frozenset({"tour", "process"})

#: Okno zmiany procesu wraca następnego dnia o tej godzinie (Europe/Warsaw).
POSTPONE_TO = time(8, 0)


class NoveltyEventIn(BaseModel):
    event: NoveltyEvent


class StartGateIn(BaseModel):
    """Wyłączniki blokad: Startu (``enforced``), Poligonu nowych osób
    (``poligon``) i porannej porcji nowości (``daily``)."""

    enforced: Optional[bool] = None
    poligon: Optional[bool] = None
    daily: Optional[bool] = None

    @model_validator(mode="after")
    def _one_switch(self) -> "StartGateIn":
        if self.enforced is None and self.poligon is None and self.daily is None:
            raise ValueError("Podaj enforced, poligon albo daily.")
        return self


#: Wyłącznik blokady Startu w ``app_settings``. Brak wiersza = blokada włączona.
START_GATE_KEY = "start_gate"
#: Blokada Poligonu nowych osób. Wyłącznik ma admin i HoR w „Nowości — kto już
#: umie” (Artur, 15.11.2026: na wypadek, gdyby ćwiczenie przestało się zaliczać);
#: seed stacku E2E (`scripts/seed_e2e.py`) też ją wyłącza, bo scenariusze
#: zakładają świeże konta rekruterów.
POLIGON_GATE_KEY = "poligon_gate"
#: Poranna porcja nowości (18.11.2026). Osobny wyłącznik, bo blokada Startu
#: jest wyłączona od 30.10 — porcja nie może od niej zależeć.
DAILY_GATE_KEY = "novelty_daily_gate"
#: Pierwsza porcja = nowości z ostatnich 7 dni przed jej wdrożeniem (Artur,
#: 18.11.2026). Starszych nikt nie nadrabia; od tej daty porcja nie ma limitu,
#: więc po urlopie czeka wszystko, co weszło w tym czasie.
DAILY_FLOOR = date(2026, 11, 12)


class RemindIn(BaseModel):
    #: Brak listy = wszyscy z grupy docelowej, którzy jeszcze nie zaliczyli.
    user_ids: Optional[list[int]] = Field(default=None, max_length=500)


def _find(novelty_id: str) -> Optional[Novelty]:
    """Nowość albo przeklikanie Startu — zdarzenia obu zapisujemy tak samo."""
    return load_novelties().get(novelty_id) or load_start_tours().get(novelty_id)


def _impersonating(request: Request) -> bool:
    return getattr(request.state, "impersonator_id", None) is not None


def _role_values(user: Any) -> set[str]:
    try:
        return {getattr(r, "value", str(r)) for r in user.get_all_roles()}
    except Exception:  # noqa: BLE001 — rola główna wystarcza jako zapas
        return {getattr(user.role, "value", str(user.role))}


def _audience_of(user: Any, novelty: Novelty) -> bool:
    """Rola albo uprawnienie z odbiorców i odczyt w sekcji ekranu nowości.

    Sekcję czyta ta sama funkcja co bramka tras (``section_access``), więc
    osoba z odebraną sekcją nie dostaje przeklikania ekranu, którego nie
    otworzy — ani okna, ani pozycji Startu, która by ją zablokowała."""
    if novelty.section is not None and (
        section_access_for_user(user, novelty.section) < SectionAccess.read
    ):
        return False
    return in_audience(novelty, _role_values(user), named_permissions_of(user))


def next_morning(now: datetime) -> datetime:
    """Jutro o 8:00 czasu firmy — do tej chwili okno zmiany procesu milczy."""
    tz = ZoneInfo(DEFAULT_TZ)
    tomorrow = now.astimezone(tz).date() + timedelta(days=1)
    return datetime.combine(tomorrow, POSTPONE_TO, tzinfo=tz)


def shape_for_user(
    novelty: Novelty,
    progress: Optional[NoveltyProgress],
    now: datetime,
    *,
    start: bool = False,
    tours_mandatory: bool = True,
) -> dict[str, Any]:
    """Nowość z punktu widzenia osoby: co pokazać i czy już umie.

    Przeklikanie Startu (``start=True``) nie ma kropki, karty ani okna — prowadzi
    do niego ekran ``/start``."""
    done = progress is not None and progress.completed_at is not None
    # Wyłącznik blokady Startu wyłącza też obowiązkowe okno nowości do
    # przeklikania (awaryjnie i na stacku E2E); zmiana procesu zostaje.
    mandatory = novelty.tier == "process" or (
        novelty.tier == "tour" and tours_mandatory
    )
    dismissed = progress is not None and progress.card_dismissed_at is not None
    reminded_after_dismiss = (
        dismissed
        and progress.reminded_at is not None
        and progress.reminded_at > progress.card_dismissed_at
    )
    postponed = (
        progress is not None
        and progress.postponed_until is not None
        and progress.postponed_until > now
    )
    return {
        "id": novelty.id,
        "title": novelty.title,
        "why": novelty.why,
        "tier": novelty.tier,
        "shipped_on": novelty.shipped_on.isoformat(),
        "where": novelty.where,
        "href": novelty.href,
        "practice_href": novelty.practice_href,
        "dot_anchor": novelty.dot_anchor,
        "used_anchor": novelty.used_anchor,
        "path_prefix": novelty.path_prefix,
        "steps": [step.model_dump() for step in novelty.steps],
        "done": done,
        "start": start,
        "completed_via": progress.completed_via if progress else None,
        # Karta przy kropce: aż do „Później”, chyba że ktoś potem przypomniał.
        "show_card": not start
        and not done
        and novelty.tier != "dot"
        and (not dismissed or reminded_after_dismiss),
        # Okno przy wejściu na ekran nowości: do zaliczenia, poza czasem
        # odłożenia. Od 30.10.2026 (decyzja Artura) każdą nowość do
        # przeklikania trzeba przejść, nie tylko zmianę procesu; drobiazg nie.
        "required_now": not start and not done and mandatory and not postponed,
        "can_postpone": not start
        and mandatory
        and (progress is None or progress.postponed_until is None),
    }


async def _progress_rows(
    db: AsyncSession, user_id: int, ids: list[str]
) -> dict[str, NoveltyProgress]:
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(NoveltyProgress).where(
                NoveltyProgress.user_id == user_id, NoveltyProgress.novelty_id.in_(ids)
            )
        )
    ).scalars()
    return {row.novelty_id: row for row in rows}


@router.get("/novelties/mine")
async def my_novelties(
    request: Request, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> list[dict[str, Any]]:
    """W podglądzie jako inna osoba bez karty i bez okna zmiany procesu:
    zapisy są wtedy zablokowane (``deps.py``), więc okna nie dałoby się zamknąć."""
    today = business_today()
    mine = [
        n
        for n in load_novelties().values()
        if n.switched_on() and n.active_on(today) and _audience_of(current_user, n)
    ]
    starts = [t for t in load_start_tours().values() if _audience_of(current_user, t)]
    progress = await _progress_rows(
        db, current_user.id, [n.id for n in mine] + [t.id for t in starts]
    )
    now = datetime.now(timezone.utc)
    gate_on = await start_gate_on(db)
    shaped = [
        shape_for_user(n, progress.get(n.id), now, tours_mandatory=gate_on)
        for n in mine
    ] + [shape_for_user(t, progress.get(t.id), now, start=True) for t in starts]
    if _impersonating(request):
        return [quiet_for_preview(item) for item in shaped]
    return shaped


def _utcnow() -> datetime:
    """Zegar porcji lekcji — testy odkładania ustawiają go na rano."""
    return datetime.now(timezone.utc)


def _lesson_row(
    row: Optional[NoveltyLessonProgress],
) -> Optional[lessons_rules.LessonRow]:
    if row is None:
        return None
    return lessons_rules.LessonRow(
        shown_at=row.shown_at,
        solo_failed_count=row.solo_failed_count or 0,
        solo_passed_at=row.solo_passed_at,
        completed_at=row.completed_at,
        reviewed_at=row.reviewed_at,
        review_failed_at=row.review_failed_at,
    )


async def _lesson_rows(
    db: AsyncSession, user_id: int
) -> dict[str, lessons_rules.LessonRow]:
    rows = (
        await db.execute(
            select(NoveltyLessonProgress).where(
                NoveltyLessonProgress.user_id == user_id
            )
        )
    ).scalars()
    return {row.lesson_id: _lesson_row(row) for row in rows}  # type: ignore[misc]


async def _day_rows(
    db: AsyncSession, user_id: int, today: date
) -> tuple[Optional[lessons_rules.DayRow], Optional[lessons_rules.DayRow]]:
    """Wiersz porcji z dziś i ostatni wcześniejszy (odłożenie wczoraj)."""
    rows = (
        (
            await db.execute(
                select(NoveltyDailyState)
                .where(
                    NoveltyDailyState.user_id == user_id,
                    NoveltyDailyState.day <= today,
                )
                .order_by(NoveltyDailyState.day.desc())
                .limit(2)
            )
        )
        .scalars()
        .all()
    )
    today_row: Optional[lessons_rules.DayRow] = None
    previous: Optional[lessons_rules.DayRow] = None
    for row in rows:
        shaped = lessons_rules.DayRow(
            day=row.day, postponed_until=row.postponed_until, skipped_at=row.skipped_at
        )
        if row.day == today:
            today_row = shaped
        elif previous is None:
            previous = shaped
    return today_row, previous


def _my_novelties(user: Any) -> list[Novelty]:
    return [
        n
        for n in load_novelties().values()
        if n.switched_on() and _audience_of(user, n)
    ]


def _is_admin(user: Any) -> bool:
    return "admin" in _role_values(user)


@router.get("/novelties/daily")
async def my_daily_novelties(
    request: Request, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Poranna porcja osoby jako lekcje. Podgląd jako inna osoba i praktykant
    niczego nie blokują; wyłącznik porcji zdejmuje blokadę, lista zostaje.
    ``items`` to wpisy lekcji z dziś (kroki pokazu dla warstwy przeklikania)."""
    today = business_today()
    now = _utcnow()
    mine = _my_novelties(current_user)
    progress = await _progress_rows(db, current_user.id, [n.id for n in mine])
    done_ids = [nid for nid, row in progress.items() if row.completed_at is not None]
    plans = lessons_rules.lesson_plans(mine, done_ids, load_lessons())
    rows = await _lesson_rows(db, current_user.id)
    plan = lessons_rules.daily_plan(plans, rows, today, current_user.id, DAILY_FLOOR)
    open_items = lessons_rules.open_count(plan, rows, today)
    today_row, previous_row = await _day_rows(db, current_user.id, today)

    items: list[dict[str, Any]] = []
    lessons: list[dict[str, Any]] = []
    for lesson_plan, review in plan.today:
        shaped_items = [
            shape_for_user(n, progress.get(n.id), now) for n in lesson_plan.novelties
        ]
        items.extend(shaped_items)
        lessons.append(
            lessons_rules.shape_lesson(
                lesson_plan,
                rows.get(lesson_plan.lesson.id),
                review=review,
                today=today,
                novelty_items=shaped_items,
            )
        )

    gate_on = await start_gate_on(db, DAILY_GATE_KEY)
    trainee = "trainee" in _role_values(current_user)
    postponed = (
        today_row is not None
        and today_row.postponed_until is not None
        and today_row.postponed_until > now
    )
    skipped = today_row is not None and today_row.skipped_at is not None
    carried = previous_row is not None and lessons_rules.carried_over(
        plan, rows, previous_row.day
    )
    can_postpone = lessons_rules.can_postpone(
        today_row, previous_row, open_items, now, today, carried=carried
    )
    done_count = len(plan.today) - open_items
    return {
        "gate_on": gate_on,
        "enforced": gate_on
        and open_items > 0
        and not trainee
        and not postponed
        and not skipped
        and not _impersonating(request),
        "today": today.isoformat(),
        "done": done_count,
        "total": len(plan.today),
        "later": plan.later,
        "novelty_count": sum(len(p.novelties) for p, _ in plan.today),
        "lessons": lessons,
        "items": items,
        "postponed_until": today_row.postponed_until.isoformat()
        if postponed and today_row and today_row.postponed_until
        else None,
        "can_postpone": can_postpone,
        "postpone_options": lessons_rules.postpone_options(now) if can_postpone else [],
        "can_skip": _is_admin(current_user) and open_items > 0 and not skipped,
        "skipped": skipped,
    }


class PostponeIn(BaseModel):
    option: lessons_rules.PostponeOption


async def _locked_day(db: AsyncSession, user_id: int, day: date) -> NoveltyDailyState:
    await db.execute(
        pg_insert(NoveltyDailyState)
        .values(user_id=user_id, day=day)
        .on_conflict_do_nothing(index_elements=["user_id", "day"])
    )
    return (
        await db.execute(
            select(NoveltyDailyState)
            .where(NoveltyDailyState.user_id == user_id, NoveltyDailyState.day == day)
            .with_for_update()
        )
    ).scalar_one()


@router.post("/novelties/daily/postpone")
@limiter.limit("20/minute", key_func=user_or_ip_key)
async def postpone_daily(
    request: Request,
    payload: PostponeIn,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Odłożenie porcji: raz dziennie, najpóźniej do 15:00 (Olaf, 23.11.2026:
    rano daily). O tej godzinie porcja wraca jak rano. Reguły liczy sama
    porcja (``can_postpone`` w ``GET /novelties/daily``)."""
    today = business_today()
    now = _utcnow()
    status_now = await my_daily_novelties(request, current_user, db)
    if not status_now["can_postpone"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "postpone_used",
                "message": "Dziś lekcji nie da się już odłożyć — zrób je teraz.",
            },
        )
    until = lessons_rules.postpone_until(payload.option, now)
    if until is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "postpone_too_late",
                "message": "Ta godzina już minęła albo wypada po 15:00.",
            },
        )
    row = await _locked_day(db, current_user.id, today)
    row.postponed_until = until
    row.updated_at = now
    await db.commit()
    return {"postponed_until": until.isoformat()}


@router.post("/novelties/daily/skip")
@limiter.limit("20/minute", key_func=user_or_ip_key)
async def skip_daily(
    request: Request, current_user: AdminUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Admin może pominąć porcję dnia (Artur, 23.11.2026). Pominięcie niczego
    nie zalicza — lekcje czekają w Szkoleniach i w jutrzejszej porcji."""
    now = _utcnow()
    row = await _locked_day(db, current_user.id, business_today())
    row.skipped_at = row.skipped_at or now
    row.updated_at = now
    await db.commit()
    return {"skipped": True}


LessonEvent = Literal[
    "shown",
    "solo_failed",
    "solo_passed",
    "quiz_wrong",
    "restart",
    "completed",
    "review_passed",
    "review_failed",
    "broken",
]


class LessonEventIn(BaseModel):
    event: LessonEvent


def _report_broken(kind: str, item_id: str, user_id: int) -> None:
    """Ślad po „Coś nie działa — zalicz mimo to”: która lekcja albo które
    ćwiczenie jest zepsute i u kogo (bez treści, samo id)."""
    logger.warning(
        "%s zaliczone przyciskiem „Coś nie działa”: %s (osoba %s)",
        kind,
        item_id,
        user_id,
    )
    sentry_sdk.capture_message(f"{kind}: „Coś nie działa” — {item_id}", level="warning")


def apply_lesson_event(row: NoveltyLessonProgress, event: str, now: datetime) -> bool:
    """Jedno zdarzenie lekcji. Zwraca ``True``, gdy lekcja właśnie się zaliczyła.

    Kolejność pilnuje serwer: „sam” dopiero po pokazie, zaliczenie dopiero po
    samodzielnym zadaniu. Powrót do pokazu (``restart``) kasuje samodzielne
    zaliczenie, więc pytania nie da się odpowiedzieć bez ponownej próby."""

    def conflict(code: str, message: str) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": code, "message": message},
        )

    just_completed = False
    if event == "shown":
        row.shown_count = (row.shown_count or 0) + 1
        row.shown_at = now
    elif event == "solo_failed":
        row.solo_failed_count = (row.solo_failed_count or 0) + 1
    elif event == "solo_passed":
        if row.shown_at is None:
            raise conflict("show_first", "Najpierw pokaz — potem samodzielnie.")
        row.solo_passed_at = now
    elif event == "quiz_wrong":
        row.quiz_wrong_count = (row.quiz_wrong_count or 0) + 1
    elif event == "restart":
        row.solo_passed_at = None
    elif event == "completed":
        if row.solo_passed_at is None:
            raise conflict("solo_first", "Lekcja zalicza się po samodzielnym zadaniu.")
        if row.completed_at is None:
            row.completed_at = now
            just_completed = True
    elif event == "review_passed":
        if row.completed_at is None:
            raise conflict("not_completed", "Powtórka dotyczy zaliczonej lekcji.")
        row.reviewed_at = now
    elif event == "broken":
        # „Coś nie działa — zalicz mimo to” (Artur, 25.11.2026): zepsuty pokaz,
        # zadanie albo pytanie nie zatrzymuje lekcji. Zalicza z każdego etapu,
        # a zaliczona lekcja (powtórka) liczy się jako powtórzona.
        row.shown_at = row.shown_at or now
        row.solo_passed_at = row.solo_passed_at or now
        if row.completed_at is None:
            row.completed_at = now
            just_completed = True
        else:
            row.reviewed_at = now
    elif event == "review_failed":
        # Lekcja wraca od pokazu w najbliższej porcji (Artur, 23.11.2026).
        row.review_failed_at = now
        row.completed_at = None
        row.solo_passed_at = None
        row.shown_at = None
    row.updated_at = now
    return just_completed


@router.post(
    "/novelties/lessons/{lesson_id}/events", status_code=status.HTTP_204_NO_CONTENT
)
@limiter.limit("60/minute", key_func=user_or_ip_key)
async def record_lesson_event(
    request: Request,
    lesson_id: str,
    payload: LessonEventIn,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Etap lekcji osoby. Zaliczenie lekcji zalicza też jej wpisy (``tour``),
    więc panel „kto już umie” i archiwum ✦ widzą to bez zmian."""
    lesson = load_lessons().get(lesson_id)
    mine = {n.id for n in _my_novelties(current_user)}
    members = [nid for nid in (lesson.novelties if lesson else []) if nid in mine]
    if lesson is None or not members:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Nie ma takiej lekcji."
        )
    now = _utcnow()
    await db.execute(
        pg_insert(NoveltyLessonProgress)
        .values(user_id=current_user.id, lesson_id=lesson_id)
        .on_conflict_do_nothing(index_elements=["user_id", "lesson_id"])
    )
    row = (
        await db.execute(
            select(NoveltyLessonProgress)
            .where(
                NoveltyLessonProgress.user_id == current_user.id,
                NoveltyLessonProgress.lesson_id == lesson_id,
            )
            .with_for_update()
        )
    ).scalar_one()
    if apply_lesson_event(row, payload.event, now):
        for novelty_id in members:
            novelty_row = await _locked_row(db, current_user.id, novelty_id)
            apply_event(novelty_row, load_novelties()[novelty_id], "toured", now)
    await db.commit()
    if payload.event == "broken":
        _report_broken("Lekcja nowości", lesson_id, current_user.id)


@router.get("/novelties/lessons")
async def my_lessons(
    current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> list[dict[str, Any]]:
    """Szkolenia → „Nowości w NEXUSIE”: wszystkie lekcje z roli osoby, bez
    terminu ważności, z jej stanem. Powtórka idzie na Poligonie."""
    today = business_today()
    now = _utcnow()
    mine = _my_novelties(current_user)
    progress = await _progress_rows(db, current_user.id, [n.id for n in mine])
    done_ids = [nid for nid, row in progress.items() if row.completed_at is not None]
    rows = await _lesson_rows(db, current_user.id)
    out: list[dict[str, Any]] = []
    for plan in reversed(lessons_rules.lesson_plans(mine, done_ids, load_lessons())):
        shaped = lessons_rules.shape_lesson(
            plan,
            rows.get(plan.lesson.id),
            review=False,
            today=today,
            novelty_items=[
                shape_for_user(n, progress.get(n.id), now) for n in plan.novelties
            ],
        )
        row = rows.get(plan.lesson.id)
        # Oblana powtórka wraca jako lekcja, choć jej wpisy są zaliczone.
        shaped["legacy_done"] = plan.legacy_done and not (
            row is not None
            and row.review_failed_at is not None
            and row.completed_at is None
        )
        out.append(shaped)
    return out


def quiet_for_preview(item: dict[str, Any]) -> dict[str, Any]:
    """Podgląd admina pokazuje kropki, ale niczego nie wymusza."""
    return {**item, "show_card": False, "required_now": False, "can_postpone": False}


async def _locked_row(
    db: AsyncSession, user_id: int, novelty_id: str
) -> NoveltyProgress:
    """Wiersz osoby przy nowości, założony bez wyścigu i zablokowany do końca
    transakcji. Dwie karty przeglądarki wysyłają pierwsze ``seen`` naraz —
    ``db.get`` + ``db.add`` dawało wtedy 500 na kluczu głównym."""
    await db.execute(
        pg_insert(NoveltyProgress)
        .values(user_id=user_id, novelty_id=novelty_id, seen_count=0)
        .on_conflict_do_nothing(index_elements=["user_id", "novelty_id"])
    )
    return (
        await db.execute(
            select(NoveltyProgress)
            .where(
                NoveltyProgress.user_id == user_id,
                NoveltyProgress.novelty_id == novelty_id,
            )
            .with_for_update()
        )
    ).scalar_one()


def apply_event(
    row: NoveltyProgress, novelty: Novelty, event: str, now: datetime
) -> None:
    """Jedno zdarzenie na wierszu osoby. Odłożenie drugi raz = 409."""
    if event == "seen":
        row.first_seen_at = row.first_seen_at or now
        row.seen_count = (row.seen_count or 0) + 1
    elif event == "card_dismissed":
        row.card_dismissed_at = now
    elif event == "postponed":
        if novelty.tier not in MANDATORY_TIERS:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "postpone_not_allowed",
                    "message": "Drobiazgu się nie odkłada — wystarczy go kliknąć.",
                },
            )
        if row.postponed_until is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "postpone_used",
                    "message": "Tę zmianę odłożono już raz — przeklikaj ją teraz.",
                },
            )
        row.postponed_until = next_morning(now)
    elif event in _COMPLETING:
        if row.completed_at is None:
            row.completed_at = now
            row.completed_via = _COMPLETING[event]
    row.updated_at = now


def apply_poligon_event(row: NoveltyProgress, event: str, now: datetime) -> None:
    """Ćwiczenie poligonu: pokazane albo zaliczone. Odkładać go nie można."""
    if event == "seen":
        row.first_seen_at = row.first_seen_at or now
        row.seen_count = (row.seen_count or 0) + 1
    elif event in _COMPLETING:
        if row.completed_at is None:
            row.completed_at = now
            row.completed_via = "used"
    else:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "postpone_not_allowed",
                "message": "Ćwiczenia poligonu się nie odkłada.",
            },
        )
    row.updated_at = now


@router.post("/novelties/{novelty_id}/events", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("60/minute", key_func=user_or_ip_key)
async def record_novelty_event(
    request: Request,
    novelty_id: str,
    payload: NoveltyEventIn,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Kropka pokazana, karta odłożona, nowość przeklikana albo użyta.

    Podgląd jako inna osoba tu nie dochodzi — ``deps.py`` odmawia w nim zapisów.
    Ćwiczenie Poligonu (``poligon-…``) zapisuje się tym samym zdarzeniem."""
    if novelty_id.startswith(POLIGON_ID_PREFIX):
        plan = load_poligon()
        # Ćwiczenie spoza ścieżki ról osoby nie istnieje dla niej (np. TCM
        # i ćwiczenie przeglądu Delivery Leada).
        if not poligon_open(current_user, plan) or novelty_id not in poligon_exercises(
            current_user, plan
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Nie ma takiego ćwiczenia.",
            )
        row = await _locked_row(db, current_user.id, novelty_id)
        apply_poligon_event(row, payload.event, datetime.now(timezone.utc))
        await db.commit()
        if payload.event == "broken":
            _report_broken("Ćwiczenie Poligonu", novelty_id, current_user.id)
        return
    novelty = _find(novelty_id)
    if novelty is None or not _audience_of(current_user, novelty):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Nie ma takiej nowości."
        )
    row = await _locked_row(db, current_user.id, novelty_id)
    apply_event(row, novelty, payload.event, datetime.now(timezone.utc))
    await db.commit()


def person_state(progress: Optional[NoveltyProgress]) -> str:
    if progress is None or (
        progress.first_seen_at is None and progress.completed_at is None
    ):
        return "untouched"
    if progress.completed_at is not None:
        return progress.completed_via or "used"
    return "seen"


async def _active_users(db: AsyncSession) -> list[User]:
    return list(
        (await db.execute(select(User).where(User.is_active.is_(True)))).scalars().all()
    )


async def _audience_users(db: AsyncSession, novelty: Novelty) -> list[User]:
    return [u for u in await _active_users(db) if _audience_of(u, novelty)]


@router.get("/novelties/adoption")
async def novelties_adoption(
    current_user: HeadOfRecruitmentPlus, db: AsyncSession = Depends(get_db)
) -> list[dict[str, Any]]:
    """Kto już umie: per nowość z ostatnich 90 dni, imiennie (admin, HoR)."""
    today = business_today()
    novelties = [n for n in load_novelties().values() if n.in_panel_on(today)]
    # Start w NEXUSIE nie wygasa — panel pokazuje go zawsze, po nowościach.
    start_tours = list(load_start_tours().values())
    starts = {t.id for t in start_tours}
    novelties += start_tours
    rows = (
        (
            await db.execute(
                select(NoveltyProgress).where(
                    NoveltyProgress.novelty_id.in_([n.id for n in novelties] or [""])
                )
            )
        )
        .scalars()
        .all()
    )
    by_key = {(r.novelty_id, r.user_id): r for r in rows}
    active = await _active_users(db)
    out = []
    for novelty in novelties:
        people = []
        for user in (u for u in active if _audience_of(u, novelty)):
            progress = by_key.get((novelty.id, user.id))
            people.append(
                {
                    "user_id": user.id,
                    "name": user.name,
                    "state": person_state(progress),
                    "completed_at": progress.completed_at.isoformat()
                    if progress and progress.completed_at
                    else None,
                    "seen_count": progress.seen_count if progress else 0,
                    "reminded_at": progress.reminded_at.isoformat()
                    if progress and progress.reminded_at
                    else None,
                }
            )
        counts = {s: 0 for s in ("used", "tour", "dot", "seen", "untouched")}
        for person in people:
            counts[person["state"]] += 1
        out.append(
            {
                "id": novelty.id,
                "title": novelty.title,
                "tier": novelty.tier,
                "shipped_on": novelty.shipped_on.isoformat(),
                "pr": novelty.pr,
                "where": novelty.where,
                "active": novelty.id in starts or novelty.active_on(today),
                "start": novelty.id in starts,
                "audience": len(people),
                "counts": counts,
                "people": sorted(
                    people,
                    key=lambda p: (p["state"] in ("used", "tour", "dot"), p["name"]),
                ),
            }
        )
    return out


#: Tyle nieudanych prób samodzielnych w jednej lekcji = temat dla HoR na
#: szkolenie (Artur, 23.11.2026).
STRUGGLE_AT = 3


@router.get("/novelties/lessons/struggles")
async def lesson_struggles(
    current_user: HeadOfRecruitmentPlus, db: AsyncSession = Depends(get_db)
) -> list[dict[str, Any]]:
    """Kto utknął w lekcji: ``STRUGGLE_AT`` i więcej nieudanych prób „sam”
    bez zaliczenia. Imiennie, więc tylko admin i HoR (jak panel „kto umie”)."""
    lessons = load_lessons()
    rows = (
        await db.execute(
            select(NoveltyLessonProgress, User)
            .join(User, User.id == NoveltyLessonProgress.user_id)
            .where(
                NoveltyLessonProgress.solo_failed_count >= STRUGGLE_AT,
                NoveltyLessonProgress.completed_at.is_(None),
                User.is_active.is_(True),
            )
            .order_by(NoveltyLessonProgress.solo_failed_count.desc())
        )
    ).all()
    return [
        {
            "user_id": user.id,
            "name": user.name,
            "lesson_id": row.lesson_id,
            "title": lessons[row.lesson_id].title,
            "solo_failed_count": row.solo_failed_count,
            "quiz_wrong_count": row.quiz_wrong_count,
            "updated_at": row.updated_at.isoformat(),
        }
        for row, user in rows
        if row.lesson_id in lessons
    ]


@router.post("/novelties/{novelty_id}/remind")
async def remind_novelty(
    novelty_id: str,
    payload: RemindIn,
    current_user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Przypomnienie = karta przy kropce wraca u wskazanych osób (bez maila)."""
    novelty = _find(novelty_id)
    is_start = novelty_id in load_start_tours()
    if novelty is None or not (is_start or novelty.active_on(business_today())):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nie ma takiej aktywnej nowości.",
        )
    audience = {u.id for u in await _audience_users(db, novelty)}
    wanted = audience if payload.user_ids is None else audience & set(payload.user_ids)
    if not wanted:
        return {"reminded": 0}
    # Brakujące wiersze bez wyścigu z pierwszym kliknięciem tej osoby, potem
    # jeden UPDATE tylko u tych, którzy jeszcze nie zaliczyli.
    await db.execute(
        pg_insert(NoveltyProgress)
        .values(
            [
                {"user_id": uid, "novelty_id": novelty_id, "seen_count": 0}
                for uid in sorted(wanted)
            ]
        )
        .on_conflict_do_nothing(index_elements=["user_id", "novelty_id"])
    )
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(NoveltyProgress)
        .where(
            NoveltyProgress.novelty_id == novelty_id,
            NoveltyProgress.user_id.in_(sorted(wanted)),
            NoveltyProgress.completed_at.is_(None),
        )
        .values(reminded_at=now, reminded_by_user_id=current_user.id, updated_at=now)
    )
    await db.commit()
    return {"reminded": int(result.rowcount or 0)}


async def start_gate_on(db: AsyncSession, key: str = START_GATE_KEY) -> bool:
    row = await db.get(AppSetting, key)
    if row is None or not isinstance(row.value, dict):
        return True
    return bool(row.value.get("enforced", True))


def poligon_status(
    progress: dict[str, NoveltyProgress],
    path_ids: list[str],
    *,
    open_: bool,
    required: bool,
    required_ids: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Poligon osoby: zaliczone ćwiczenia jej ścieżki i czy blokuje resztę ekranów.

    ``path_ids`` to ścieżka ról osoby (mapa), ``required_ids`` — ćwiczenia,
    których poligon od niej wymaga (``PoligonRequirement``; domyślnie cała
    ścieżka). Licznik ``done``/``total`` i blokada liczą wymagane: Delivery
    Lead nie czeka na screening rekrutera, a po zmianie roli zostają tylko
    niezaliczone ćwiczenia nowej roli."""
    counted = list(path_ids if required_ids is None else required_ids)
    done_ids = [
        eid
        for eid in path_ids
        if eid in progress and progress[eid].completed_at is not None
    ]
    return {
        "open": open_,
        "required": required,
        "exercise_ids": counted,
        "done_ids": done_ids,
        "done": sum(1 for eid in counted if eid in done_ids),
        "total": len(counted),
    }


def start_status(
    tours: list[Novelty],
    progress: dict[str, NoveltyProgress],
    *,
    gate_on: bool,
    impersonating: bool,
    poligon: Optional[dict[str, Any]] = None,
    poligon_gate_on: bool = True,
) -> dict[str, Any]:
    """Start osoby: lista przeklikań i czy front ma ją zatrzymać.

    Osobie, której poligon jest wymagany, zastępuje on przeklikania
    rekrutacji (``poligon.json`` → ``replaces``) i blokuje ekrany, dopóki
    nie zaliczy wszystkich ćwiczeń — wtedy front prowadzi na ``/poligon``."""
    items = [
        {
            "id": t.id,
            "title": t.title,
            "why": t.why,
            "where": t.where,
            "href": t.href,
            "done": t.id in progress and progress[t.id].completed_at is not None,
        }
        for t in tours
    ]
    done = sum(1 for item in items if item["done"])
    poligon_due = bool(
        poligon_gate_on
        and poligon
        and poligon["required"]
        and poligon["done"] < poligon["total"]
    )
    # Wyłącznik Startu (`gate_on`) dotyczy tylko przeklikań; poligon nowej
    # osoby blokuje zawsze (Artur, 15.11.2026 — Start wyłączony od 30.10).
    return {
        "enforced": not impersonating
        and (poligon_due or (gate_on and done < len(items))),
        "gate_on": gate_on,
        "poligon_gate_on": poligon_gate_on,
        "done": done,
        "total": len(items),
        "items": items,
        "redirect": "/poligon" if poligon_due else "/start",
        "poligon": poligon,
    }


@router.get("/novelties/start")
async def my_start(
    request: Request, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Podgląd jako inna osoba niczego nie blokuje — zapisy są wtedy zablokowane."""
    tours = [t for t in load_start_tours().values() if _audience_of(current_user, t)]
    plan = load_poligon()
    open_ = poligon_open(current_user, plan)
    # Wymagany od nadania roli z poligonem (Artur, 15.11.2026) — z historii ról.
    need = (
        await poligon_requirement(db, current_user, plan)
        if open_
        else PoligonRequirement((), ())
    )
    required = need.required
    poligon_ids = poligon_exercises(current_user, plan) if open_ else []
    required_ids = list(need.exercise_ids) if required else None
    # Poligon dla obecnych (Artur, 16.11.2026): do terminu prosi, po terminie
    # blokuje jak u nowej osoby — cała ścieżka, część zaliczona z pracy.
    luki = (
        campaign_entry(await load_campaign(db), current_user.id)
        if open_ and not required
        else None
    )
    if luki:
        required = overdue(luki["due"], business_today())
        required_ids = poligon_ids
    if required and need.required:
        replaced = poligon_replaces(current_user, plan)
        tours = [t for t in tours if t.id not in replaced]
    progress = await _progress_rows(
        db, current_user.id, [t.id for t in tours] + poligon_ids
    )
    return start_status(
        tours,
        progress,
        gate_on=await start_gate_on(db),
        impersonating=_impersonating(request),
        poligon=(
            {
                **poligon_status(
                    progress,
                    poligon_ids,
                    open_=open_,
                    required=required,
                    required_ids=required_ids,
                ),
                "luki": luki,
            }
            if open_
            else None
        ),
        poligon_gate_on=await start_gate_on(db, POLIGON_GATE_KEY),
    )


@router.put("/novelties/start/gate")
async def set_start_gate(
    payload: StartGateIn,
    current_user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    """Wyłączniki blokad dla całej firmy (admin, HoR): Startu, Poligonu nowych
    osób i porannej porcji nowości."""
    for key, enforced in (
        (START_GATE_KEY, payload.enforced),
        (POLIGON_GATE_KEY, payload.poligon),
        (DAILY_GATE_KEY, payload.daily),
    ):
        if enforced is None:
            continue
        value = {"enforced": enforced}
        row = await db.get(AppSetting, key)
        if row is None:
            db.add(AppSetting(key=key, value=value, updated_by=current_user.id))
        else:
            row.value = value
            row.updated_by = current_user.id
    await db.commit()
    return {
        "enforced": await start_gate_on(db),
        "poligon": await start_gate_on(db, POLIGON_GATE_KEY),
        "daily": await start_gate_on(db, DAILY_GATE_KEY),
    }


# ── Poligon dla obecnych: tylko luki (Artur, 16.11.2026) ─────────────────────


class LukiIn(BaseModel):
    """Start kampanii: termin (domyślnie za tydzień)."""

    due: Optional[date] = None


@router.get("/novelties/poligon/luki")
async def poligon_luki_matrix(
    current_user: HeadOfRecruitmentPlus, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """„Kto zna NEXUS”: rekruterzy × ważne funkcje z 60 dni pracy (admin, HoR)."""
    plan = load_poligon()
    people = await luki_targets(db)
    usage = await feature_usage(db, [u.id for u in people], datetime.now(timezone.utc))
    campaign = await load_campaign(db)
    done_rows = (
        await db.execute(
            select(NoveltyProgress.user_id, NoveltyProgress.novelty_id).where(
                NoveltyProgress.user_id.in_([u.id for u in people] or [0]),
                NoveltyProgress.novelty_id.like(f"{POLIGON_ID_PREFIX}%"),
                NoveltyProgress.completed_at.is_not(None),
            )
        )
    ).all()
    done_by: dict[int, set[str]] = {}
    for uid, nid in done_rows:
        done_by.setdefault(int(uid), set()).add(nid)
    rows = []
    for u in people:
        used = usage.get(u.id, set())
        entry = campaign_entry(campaign, u.id)
        path = poligon_exercises(u, plan)
        rows.append(
            {
                "id": u.id,
                "name": u.name,
                "used": sorted(used),
                "gaps": sum(1 for f in LUKI_FEATURES if f.key not in used),
                "poligon": (
                    {
                        "done": sum(1 for e in path if e in done_by.get(u.id, set())),
                        "total": len(path),
                    }
                    if entry
                    else None
                ),
            }
        )
    return {
        "window_days": 60,
        "features": [
            {
                "key": f.key,
                "label": f.label,
                "group": f.group,
                "users": sum(1 for r in rows if f.key in r["used"]),
            }
            for f in LUKI_FEATURES
        ],
        "people": rows,
        "campaign": (
            {"due": campaign["due"], "started_at": campaign.get("started_at")}
            if campaign
            else None
        ),
    }


@router.post("/novelties/poligon/luki")
async def start_poligon_luki(
    payload: LukiIn,
    current_user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Wysyła poligon z lukami: zalicza z pracy, ustawia termin (admin, HoR)."""
    today = business_today()
    due = payload.due or default_due(today)
    if due < today:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Termin nie może być w przeszłości.",
        )
    plan = load_poligon()
    now = datetime.now(timezone.utc)
    people = await luki_targets(db)
    usage = await feature_usage(db, [u.id for u in people], now)
    users: dict[str, dict[str, list[str]]] = {}
    credited_total = 0
    for u in people:
        credited = credited_exercises(
            usage.get(u.id, set()), poligon_exercises(u, plan)
        )
        users[str(u.id)] = {"credited": credited}
        credited_total += len(credited)
        for eid in credited:
            await db.execute(
                pg_insert(NoveltyProgress)
                .values(
                    user_id=u.id,
                    novelty_id=eid,
                    seen_count=0,
                    completed_at=now,
                    completed_via="used",
                )
                .on_conflict_do_update(
                    index_elements=["user_id", "novelty_id"],
                    set_={
                        "completed_at": now,
                        "completed_via": "used",
                        "updated_at": now,
                    },
                    where=NoveltyProgress.completed_at.is_(None),
                )
            )
    value = {
        "due": due.isoformat(),
        "started_at": now.isoformat(),
        "started_by": current_user.id,
        "users": users,
    }
    row = await db.get(AppSetting, LUKI_KEY)
    if row is None:
        db.add(AppSetting(key=LUKI_KEY, value=value, updated_by=current_user.id))
    else:
        row.value = value
        row.updated_by = current_user.id
    await db.commit()
    return {"due": value["due"], "people": len(users), "credited": credited_total}
