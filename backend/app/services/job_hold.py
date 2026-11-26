"""Rekrutacja „Wstrzymana” (``work_state = on_hold``) — decyzje Artura 26.11.2026.

Zgłoszenie rekruterki z 26.11: zaproponowała kandydatowi projekt i zrobiła
weryfikację, a dopiero potem Delivery Lead powiedział, że klient wstrzymał
rekrutację. Na produkcji 26.11 wszystkie 141 otwartych rekrutacji stały
w „Szukamy”, „Klient milczy” użyto 3 razy od 01.09, a zamknięcia z powodem
„Wstrzymana przez klienta” — 6 razy.

* **Osobny stan pracy** obok „Klient milczy”: wypada z automatów
  (``IN_WORK_STATES`` bez zmian), z licznika „bez ruchu” i z przydziału, ale
  zespół (przypisania, „Poprzedni rekruter”) zostaje do wznowienia.
* **Wstrzymuje** DL, HoR albo admin z powodem i terminem „Sprawdzę
  z klientem”; rekruterzy z kartami w toku i zespół dostają dzwonek i mail
  obowiązkowy (``job_hold_changed``). Wznowienie tak samo. Zmiana powodu albo
  terminu nie wysyła drugi raz.
* **Rekruter zgłasza** („Słyszysz, że klient wstrzymał?”, przy wstrzymanej:
  „Zapytaj DL”) — dzwonek ``job_hold_check`` do DL rekrutacji (bez aktywnego
  DL: Head of Recruitment). Jedno nieodpowiedziane zgłoszenie na osobę.
* **Panel DL** „Czy te rekrutacje nadal trwają?” (``hold_checks``) zbiera
  sygnały: zgłoszenie, notatkę z „on hold”, zejście z P1 przy pracujących
  rekruterach i ciszę DL przy pracy rekruterów. „Szukamy” zamyka zgłoszenia.
* **Pętla ``job_idle``** pyta DL w dniu „Sprawdzę z klientem” i po 30 dniach
  wstrzymania (``run_hold_notices``). Nigdy nie zamyka sama.

Kontrakt tras: ``api/job_hold.py``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Optional, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.activity import Activity
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.note import Note
from app.models.notification import NotificationType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services.request_work_state import ON_HOLD, set_work_state

logger = logging.getLogger(__name__)

REASON_MAX = 500
NOTE_MAX = 500
REVIEW_MAX_DAYS = 120
LONG_HOLD_DAYS = 30
DL_SILENT_DAYS = 14
RECRUITER_WINDOW_DAYS = 7
# Zejście z P1 jest sygnałem tylko przy prawdziwej pracy w tym tygodniu: na
# stagingu 26.11 bez progu 8 z 10 wierszy panelu DL miało 0–1 ruchu rekrutera.
PARKED_MIN_MOVES_7D = 3
NOTE_WINDOW_DAYS = 30
CHECKS_LIMIT = 10
# Panel pyta tylko o rekrutacje, nad którymi ktoś pracuje.
CHECK_STATES = ("to_review", "searching")
RESUME_STATE = "searching"

REPORT_ACTION = "hold_reported"
ANSWER_ACTION = "hold_check_answered"
UPDATED_ACTION = "hold_updated"
REVIEW_NOTICE_ACTION = "hold_review_notice"
LONG_NOTICE_ACTION = "hold_long_notice"
WORK_STATE_ACTION = "work_state_changed"
PARKED_ACTION = "recruiters_parked"
# Zgłoszenie rekrutera jest odpowiedziane, gdy po nim DL kliknął „Szukamy”,
# zmienił stan pracy (wstrzymał, wznowił, zamknął) albo powód wstrzymania.
ANSWERING_ACTIONS = (ANSWER_ACTION, WORK_STATE_ACTION, UPDATED_ACTION)
# ILIKE po treści notatki; samej treści panel nie zwraca.
NOTE_PATTERNS = ("%on hold%", "%onhold%", "%on-hold%", "%wstrzyma%")
SIGNAL_ORDER = ("report", "note", "parked_still_working", "dl_silent")
_SIGNAL_RANK = {kind: rank for rank, kind in enumerate(SIGNAL_ORDER)}
# Ruch rekrutera = etap poza wejściem z ogłoszenia i zamknięciem osoby
# (lustro ``request_work_state._NOT_WORK``).
_NOT_WORK = (
    PipelineStage.posting,
    PipelineStage.new,
    PipelineStage.rejected,
    PipelineStage.withdrawn,
)


class HoldError(Exception):
    """Odmowa z kodem dla frontu i zdaniem po polsku."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message

    def detail(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class Report:
    user_id: Optional[int]
    at: datetime
    note: str
    while_state: Optional[str]


# ── Czyste reguły ───────────────────────────────────────────────────────────


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.BUSINESS_TZ)


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def local_day(moment: datetime) -> date:
    return _aware(moment).astimezone(_tz()).date()


def _ddmm(moment: Optional[date]) -> str:
    """„26.11” — chwila w kalendarzu firmy albo sama data."""
    if moment is None:
        return ""
    day = local_day(moment) if isinstance(moment, datetime) else moment
    return day.strftime("%d.%m")


def review_on_error(review_on: Optional[date], today: date) -> Optional[HoldError]:
    """Termin „Sprawdzę z klientem”: od dziś do 120 dni (kalendarz firmy)."""
    if review_on is None:
        return None
    if review_on < today:
        return HoldError(
            422, "review_on_past", "Termin sprawdzenia nie może być w przeszłości."
        )
    if review_on > today + timedelta(days=REVIEW_MAX_DAYS):
        return HoldError(
            422,
            "review_on_too_far",
            f"Termin sprawdzenia ustaw najpóźniej za {REVIEW_MAX_DAYS} dni.",
        )
    return None


def open_reports(
    reports: Iterable[Report], last_answer_at: Optional[datetime]
) -> list[Report]:
    """Zgłoszenia bez odpowiedzi: nowsze niż ostatnia odpowiedź DL."""
    out = [
        report
        for report in reports
        if last_answer_at is None or _aware(report.at) > _aware(last_answer_at)
    ]
    return sorted(out, key=lambda report: report.at)


def parked_still_working(*, moves_after_park: int, moves_7d: int) -> bool:
    """Zejście z P1, po którym rekruterzy nadal pracują (co najmniej 3 ruchy w 7 dni)."""
    return moves_after_park > 0 and moves_7d >= PARKED_MIN_MOVES_7D


def dl_silent_since(
    *,
    last_dl_move_at: Optional[datetime],
    opened_at: Optional[datetime],
    anchor_at: Optional[datetime],
    recruiter_moves_7d: int,
    now: datetime,
) -> Optional[datetime]:
    """Cisza DL przy pracy rekruterów → od kiedy cisza, inaczej ``None``.

    Ruch DL jak w ``job_idle`` (CV do klienta, odpowiedź klienta). Po
    odpowiedzi DL albo zmianie stanu pracy sygnał wraca najwcześniej po 14
    dniach."""
    if recruiter_moves_7d <= 0:
        return None
    known = [_aware(m) for m in (last_dl_move_at, opened_at) if m is not None]
    if not known:
        return None
    since = max(known)
    window = timedelta(days=DL_SILENT_DAYS)
    if _aware(now) - since < window:
        return None
    if anchor_at is not None and _aware(now) - _aware(anchor_at) < window:
        return None
    return since


def best_rank(signals: Sequence[dict[str, Any]]) -> int:
    return min(
        (_SIGNAL_RANK.get(s["kind"], len(SIGNAL_ORDER)) for s in signals),
        default=len(SIGNAL_ORDER),
    )


def sort_signals(signals: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        signals,
        key=lambda s: (
            _SIGNAL_RANK.get(s["kind"], len(SIGNAL_ORDER)),
            -_ts(s.get("at")),
        ),
    )


def _ts(value: Any) -> float:
    if isinstance(value, datetime):
        return _aware(value).timestamp()
    if isinstance(value, str):
        try:
            return _aware(datetime.fromisoformat(value)).timestamp()
        except ValueError:
            return 0.0
    return 0.0


def sort_items(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Kolejność panelu: najmocniejszy sygnał, potem liczba ruchów rekruterów."""
    return sorted(
        items,
        key=lambda item: (
            best_rank(item["signals"]),
            -int(item.get("recruiter_moves_7d") or 0),
            -int(item["job_id"]),
        ),
    )


def held_notice_text(
    *,
    job_title: str,
    client_name: Optional[str],
    actor_name: Optional[str],
    reason: str,
    review_on: Optional[date],
) -> tuple[str, str]:
    head = f"{job_title} · {client_name}" if client_name else job_title
    who = f" Wstrzymał(a): {actor_name}." if actor_name else ""
    term = f" Sprawdzenie z klientem: {_ddmm(review_on)}." if review_on else ""
    message = (
        f"{head}. Klient wstrzymał rekrutację.{who} Powód: {reason}.{term} "
        "Nie proponuj kandydatom tego projektu, dopóki rekrutacja nie wróci do "
        "„Szukamy”. Osoby w toku zostają na Tablicy."
    )
    return f"Rekrutacja wstrzymana: {job_title}", message


def resumed_notice_text(
    *, job_title: str, client_name: Optional[str], actor_name: Optional[str]
) -> tuple[str, str]:
    head = f"{job_title} · {client_name}" if client_name else job_title
    who = f" Wznowił(a): {actor_name}." if actor_name else ""
    message = (
        f"{head}. Rekrutacja wraca do „Szukamy”.{who} Możesz znowu proponować "
        "ten projekt kandydatom."
    )
    return f"Rekrutacja wznowiona: {job_title}", message


# ── Odczyt ──────────────────────────────────────────────────────────────────


async def hold_fields(
    db: AsyncSession, jobs: Sequence[Job]
) -> dict[int, dict[str, Any]]:
    """``hold_since`` i ``hold_by_name`` dla wstrzymanych (wiersz i szczegół)."""
    held = [job for job in jobs if job.work_state == ON_HOLD]
    if not held:
        return {}
    by_ids = {job.work_state_changed_by for job in held if job.work_state_changed_by}
    names = (
        dict(
            (
                await db.execute(select(User.id, User.name).where(User.id.in_(by_ids)))
            ).all()
        )
        if by_ids
        else {}
    )
    return {
        job.id: {
            "hold_since": job.work_state_changed_at,
            "hold_by_name": names.get(job.work_state_changed_by),
        }
        for job in held
    }


async def _last_answers(
    db: AsyncSession, job_ids: Sequence[int]
) -> dict[int, datetime]:
    ids = list(job_ids)
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(Activity.entity_id, func.max(Activity.created_at))
            .where(
                Activity.entity_type == "job",
                Activity.entity_id.in_(ids),
                Activity.action.in_(ANSWERING_ACTIONS),
            )
            .group_by(Activity.entity_id)
        )
    ).all()
    return {job_id: at for job_id, at in rows}


async def load_open_reports(
    db: AsyncSession, job_ids: Sequence[int]
) -> dict[int, list[Report]]:
    """Nieodpowiedziane zgłoszenia rekruterów per rekrutacja."""
    ids = list(job_ids)
    if not ids:
        return {}
    answers = await _last_answers(db, ids)
    rows = (
        await db.execute(
            select(
                Activity.entity_id,
                Activity.user_id,
                Activity.created_at,
                Activity.details,
            ).where(
                Activity.entity_type == "job",
                Activity.entity_id.in_(ids),
                Activity.action == REPORT_ACTION,
            )
        )
    ).all()
    by_job: dict[int, list[Report]] = {}
    for job_id, user_id, created_at, details in rows:
        details = details if isinstance(details, dict) else {}
        by_job.setdefault(job_id, []).append(
            Report(
                user_id=user_id,
                at=created_at,
                note=str(details.get("note") or ""),
                while_state=details.get("while_state"),
            )
        )
    return {
        job_id: open_reports(reports, answers.get(job_id))
        for job_id, reports in by_job.items()
    }


async def _active_names(db: AsyncSession, user_ids: Iterable[int]) -> dict[int, str]:
    ids = {int(uid) for uid in user_ids if uid}
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(User.id, User.name).where(User.id.in_(ids), User.is_active.is_(True))
        )
    ).all()
    return {uid: name or f"Konto #{uid}" for uid, name in rows}


async def hold_recipients(
    db: AsyncSession, job: Job, *, exclude_user_id: Optional[int]
) -> list[dict[str, Any]]:
    """Kto dostanie wiadomość o wstrzymaniu albo wznowieniu.

    Osoby prowadzące kandydatów z bieżącą kartą w toku (bez „Zamkniętych”
    i „Zatrudnionych”, ``job_closed_notices``) ∪ zespół, który pracuje
    (prowadzący, aktywne przypisania, ręczni współpracownicy) ∪ autorzy
    otwartych zgłoszeń. Bez osoby, która to robi, i bez kont nieaktywnych.
    ``people`` = ile osób tej osoby jest w toku.
    """
    from app.services.job_closed_notices import load_recipients  # noqa: PLC0415
    from app.services.job_team import recruiters_for_jobs, working  # noqa: PLC0415

    people: dict[int, int] = {}
    for recipient in await load_recipients(
        db, job.id, exclude_user_id=exclude_user_id, columns=None
    ):
        people[recipient.user_id] = len(recipient.people)
    team = working((await recruiters_for_jobs(db, [job.id])).get(job.id, []))
    for person in team:
        people.setdefault(person.user_id, 0)
    for report in (await load_open_reports(db, [job.id])).get(job.id, []):
        if report.user_id is not None:
            people.setdefault(report.user_id, 0)
    people.pop(exclude_user_id or 0, None)
    names = await _active_names(db, people)
    out = [
        {"user_id": uid, "name": names[uid], "people": count}
        for uid, count in people.items()
        if uid in names
    ]
    return sorted(out, key=lambda r: (-r["people"], r["name"], r["user_id"]))


async def hold_payload(
    db: AsyncSession, job: Job, *, viewer_id: int, can_manage: bool
) -> dict[str, Any]:
    """Kształt ``GET /api/jobs/{id}/hold`` (ten sam po PUT i DELETE)."""
    held = job.work_state == ON_HOLD
    by_name = (
        (await hold_fields(db, [job])).get(job.id, {}).get("hold_by_name")
        if held
        else None
    )
    mine = next(
        (
            report
            for report in reversed(
                (await load_open_reports(db, [job.id])).get(job.id, [])
            )
            if report.user_id == viewer_id
        ),
        None,
    )
    from app.services.request_work_state import visible_state  # noqa: PLC0415

    return {
        "job_id": job.id,
        "state": visible_state(job.work_state, job.champion_found_at),
        "reason": job.hold_reason if held else None,
        "review_on": job.hold_review_on.isoformat()
        if held and job.hold_review_on
        else None,
        "since": job.work_state_changed_at.isoformat()
        if held and job.work_state_changed_at
        else None,
        "by_id": job.work_state_changed_by if held else None,
        "by_name": by_name,
        "can_manage": can_manage,
        "recipients": await hold_recipients(db, job, exclude_user_id=viewer_id),
        "my_open_report": (
            {"at": _aware(mine.at).isoformat(), "note": mine.note} if mine else None
        ),
    }


# ── Zapis ───────────────────────────────────────────────────────────────────


def _ensure_open(job: Job) -> None:
    if job.status != JobStatus.published:
        raise HoldError(
            409,
            "job_not_open",
            "Rekrutacja nie jest otwarta — wstrzymać można tylko otwartą rekrutację.",
        )


async def _names(
    db: AsyncSession, job: Job, actor_id: Optional[int]
) -> tuple[str, Optional[str], Optional[str]]:
    from app.services.job_working_title import display_title  # noqa: PLC0415

    client_name = (
        await db.scalar(
            select(func.coalesce(Client.name, Client.display_name)).where(
                Client.id == job.client_id
            )
        )
        if job.client_id
        else None
    )
    actor_name = (
        await db.scalar(select(User.name).where(User.id == actor_id))
        if actor_id is not None
        else None
    )
    return display_title(job), client_name, actor_name


async def _bell(
    db: AsyncSession,
    *,
    user_ids: Iterable[int],
    title: str,
    message: str,
    ntype: NotificationType,
    job_id: int,
    related_entity_id: Optional[int],
) -> list[int]:
    """Dzwonek na osobę w savepoincie — nieudany wpis nie cofa zmiany stanu."""
    from app.services.notification_triggers import emit  # noqa: PLC0415

    sent: list[int] = []
    for uid in sorted(set(user_ids)):
        try:
            async with db.begin_nested():
                row = await emit(
                    db,
                    user_id=uid,
                    title=title,
                    message=message,
                    ntype=ntype,
                    related_entity_type="job",
                    related_entity_id=related_entity_id,
                    link=f"/jobs/{job_id}",
                )
            if row is not None:
                sent.append(uid)
        except Exception:  # noqa: BLE001 — dzwonek nie może cofnąć zmiany
            logger.exception(
                "job_hold: dzwonek %s dla user_id=%s job_id=%s nie powstał",
                ntype.value,
                uid,
                job_id,
            )
    return sent


async def put_hold(
    db: AsyncSession,
    job: Job,
    *,
    actor_id: int,
    reason: str,
    review_on: Optional[date],
    notify: bool,
    today: date,
) -> list[int]:
    """Wstrzymaj albo (już wstrzymaną) zmień powód / termin. Bez commitu.

    Zwraca listę osób, do których poszedł dzwonek (przy zmianie powodu —
    pusta). Wołający trzyma blokadę wiersza rekrutacji."""
    _ensure_open(job)
    error = review_on_error(review_on, today)
    if error is not None:
        raise error
    if job.work_state == ON_HOLD:
        before = {
            "reason": job.hold_reason,
            "review_on": job.hold_review_on.isoformat() if job.hold_review_on else None,
        }
        after = {
            "reason": reason,
            "review_on": review_on.isoformat() if review_on else None,
        }
        if before != after:
            job.hold_reason = reason
            job.hold_review_on = review_on
            db.add(
                Activity(
                    entity_type="job",
                    entity_id=job.id,
                    action=UPDATED_ACTION,
                    user_id=actor_id,
                    details={"from": before, "to": after},
                )
            )
        return []
    # Adresaci PRZED zmianą stanu — po niej zgłoszenia są już odpowiedziane.
    recipients = (
        await hold_recipients(db, job, exclude_user_id=actor_id) if notify else []
    )
    await set_work_state(
        db,
        job,
        ON_HOLD,
        actor_id=actor_id,
        reason="hold",
        details={
            "hold_reason": reason,
            "review_on": review_on.isoformat() if review_on else None,
        },
    )
    job.hold_reason = reason
    job.hold_review_on = review_on
    if not recipients:
        return []
    title_text, client_name, actor_name = await _names(db, job, actor_id)
    title, message = held_notice_text(
        job_title=title_text,
        client_name=client_name,
        actor_name=actor_name,
        reason=reason,
        review_on=review_on,
    )
    # Bez ``related_entity_id``: wstrzymanie i wznowienie tego samego dnia to
    # dwa wpisy, a dobowy dedup ``emit`` zjadłby drugi.
    return await _bell(
        db,
        user_ids=[r["user_id"] for r in recipients],
        title=title,
        message=message,
        ntype=NotificationType.job_hold_changed,
        job_id=job.id,
        related_entity_id=None,
    )


async def end_hold(db: AsyncSession, job: Job, *, actor_id: int) -> list[int]:
    """„Wznów rekrutację” → „Szukamy”; dzwonek do tych samych adresatów."""
    if job.work_state != ON_HOLD:
        raise HoldError(409, "job_not_on_hold", "Ta rekrutacja nie jest wstrzymana.")
    recipients = await hold_recipients(db, job, exclude_user_id=actor_id)
    await set_work_state(db, job, RESUME_STATE, actor_id=actor_id, reason="hold_ended")
    if not recipients:
        return []
    title_text, client_name, actor_name = await _names(db, job, actor_id)
    title, message = resumed_notice_text(
        job_title=title_text, client_name=client_name, actor_name=actor_name
    )
    return await _bell(
        db,
        user_ids=[r["user_id"] for r in recipients],
        title=title,
        message=message,
        ntype=NotificationType.job_hold_changed,
        job_id=job.id,
        related_entity_id=None,
    )


async def lead_recipients(db: AsyncSession, lead_id: Optional[int]) -> list[int]:
    """DL rekrutacji, a bez aktywnego DL — aktywni Head of Recruitment."""
    if lead_id is not None and await db.scalar(
        select(User.id).where(User.id == lead_id, User.is_active.is_(True))
    ):
        return [lead_id]
    return list(
        (
            await db.scalars(
                select(User.id)
                .where(
                    User.roles.contains([UserRole.head_of_recruitment.value]),
                    User.is_active.is_(True),
                )
                .order_by(User.id)
            )
        ).all()
    )


async def report(db: AsyncSession, job: Job, *, actor_id: int, note: str) -> list[int]:
    """Rekruter zgłasza DL-owi, że klient chyba wstrzymał. Bez commitu."""
    if job.status != JobStatus.published:
        raise HoldError(
            409, "job_not_open", "Rekrutacja nie jest otwarta — nie ma czego zgłaszać."
        )
    mine = [
        r
        for r in (await load_open_reports(db, [job.id])).get(job.id, [])
        if r.user_id == actor_id
    ]
    if mine:
        raise HoldError(
            409,
            "already_reported",
            f"Zgłosiłeś to już {_ddmm(mine[-1].at)} — czekamy na odpowiedź DL.",
        )
    db.add(
        Activity(
            entity_type="job",
            entity_id=job.id,
            action=REPORT_ACTION,
            user_id=actor_id,
            details={"note": note, "while_state": job.work_state},
        )
    )
    title_text, client_name, actor_name = await _names(db, job, actor_id)
    head = f"{title_text} · {client_name}" if client_name else title_text
    who = actor_name or "Rekruter"
    said = f": „{note}”" if note else "."
    if job.work_state == ON_HOLD:
        title = f"Rekruter pyta o wstrzymaną rekrutację: {title_text}"
        message = (
            f"{head}. {who} pyta, czy rekrutacja nadal jest wstrzymana{said} "
            "Wznów ją albo zmień termin sprawdzenia na rekrutacji."
        )
    else:
        title = f"Czy rekrutacja trwa? {title_text}"
        message = (
            f"{head}. {who} słyszy, że klient mógł wstrzymać rekrutację{said} "
            "Odpowiedz na rekrutacji albo na pulpicie: „Szukamy”, „Wstrzymana…” "
            "albo zamknięcie."
        )
    leads = [
        uid
        for uid in await lead_recipients(db, job.delivery_lead_id)
        if uid != actor_id
    ]
    # Bez ``related_entity_id``: kilka zgłoszeń jednego dnia to kilka wpisów.
    return await _bell(
        db,
        user_ids=leads,
        title=title,
        message=message,
        ntype=NotificationType.job_hold_check,
        job_id=job.id,
        related_entity_id=None,
    )


async def answer_check(db: AsyncSession, job: Job, *, actor_id: int) -> list[int]:
    """DL: „Szukamy” — zamyka zgłoszenia i daje znać zgłaszającym. Bez commitu."""
    if job.status != JobStatus.published:
        raise HoldError(409, "job_not_open", "Rekrutacja nie jest otwarta.")
    if job.work_state == ON_HOLD:
        raise HoldError(
            409,
            "job_on_hold",
            "Rekrutacja jest wstrzymana — wznów ją przyciskiem „Wznów rekrutację”.",
        )
    reports = (await load_open_reports(db, [job.id])).get(job.id, [])
    db.add(
        Activity(
            entity_type="job",
            entity_id=job.id,
            action=ANSWER_ACTION,
            user_id=actor_id,
            details={"answer": RESUME_STATE, "reports": len(reports)},
        )
    )
    reporters = {r.user_id for r in reports if r.user_id and r.user_id != actor_id}
    if not reporters:
        return []
    title_text, client_name, actor_name = await _names(db, job, actor_id)
    head = f"{title_text} · {client_name}" if client_name else title_text
    who = actor_name or "Delivery Lead"
    return await _bell(
        db,
        user_ids=reporters,
        title="DL potwierdził: szukamy",
        message=(
            f"{head}. {who} potwierdza, że rekrutacja trwa — możesz proponować "
            "ten projekt kandydatom."
        ),
        ntype=NotificationType.job_hold_check,
        job_id=job.id,
        related_entity_id=None,
    )


# ── Panel „Czy te rekrutacje nadal trwają?” ─────────────────────────────────


async def _recruiter_moves(
    db: AsyncSession, job_ids: Sequence[int], *, since: datetime
) -> list[tuple[int, int, datetime]]:
    """(job_id, kto, kiedy) — ruchy rekruterów (nie DL rekrutacji) od ``since``."""
    if not job_ids:
        return []
    rows = (
        await db.execute(
            select(
                CandidateStage.job_id, CandidateStage.moved_by, CandidateStage.moved_at
            )
            .join(Job, Job.id == CandidateStage.job_id)
            .where(
                CandidateStage.job_id.in_(list(job_ids)),
                CandidateStage.moved_at >= since,
                CandidateStage.moved_by.is_not(None),
                CandidateStage.stage.not_in(_NOT_WORK),
                or_(
                    Job.delivery_lead_id.is_(None),
                    CandidateStage.moved_by != Job.delivery_lead_id,
                ),
            )
        )
    ).all()
    return [(job_id, uid, at) for job_id, uid, at in rows]


async def hold_checks(
    db: AsyncSession,
    *,
    viewer_id: int,
    all_jobs: bool,
    now: Optional[datetime] = None,
    only_job_ids: Optional[Sequence[int]] = None,
) -> dict[str, Any]:
    """Do 10 rekrutacji z sygnałem, że klient mógł je wstrzymać.

    ``all_jobs`` = wszystkie (HoR, admin), inaczej ``delivery_lead_id = viewer``.
    ``only_job_ids`` zawęża zbiór (testy na wspólnej bazie)."""
    from app.services.job_idle import load_facts  # noqa: PLC0415

    moment = _aware(now or datetime.now(timezone.utc))
    query = (
        select(
            Job.id,
            Job.title,
            Job.working_title,
            Job.reference_number,
            Job.priority,
            Job.work_state,
            Job.work_state_changed_at,
            Job.delivery_lead_id,
            func.coalesce(Client.name, Client.display_name),
        )
        .join(Client, Client.id == Job.client_id, isouter=True)
        .where(Job.status == JobStatus.published, Job.work_state.in_(CHECK_STATES))
    )
    if not all_jobs:
        query = query.where(Job.delivery_lead_id == viewer_id)
    if only_job_ids is not None:
        query = query.where(Job.id.in_(list(only_job_ids)))
    jobs = (await db.execute(query)).all()
    if not jobs:
        return {"items": [], "total": 0}
    ids = [row[0] for row in jobs]
    answers = await _last_answers(db, ids)
    anchors: dict[int, Optional[datetime]] = {}
    for row in jobs:
        known = [_aware(m) for m in (answers.get(row[0]), row[6]) if m is not None]
        anchors[row[0]] = max(known) if known else None

    def fresh(job_id: int, at: Optional[datetime]) -> bool:
        anchor = anchors.get(job_id)
        return at is not None and (anchor is None or _aware(at) > anchor)

    signals: dict[int, list[dict[str, Any]]] = {job_id: [] for job_id in ids}

    report_rows = (
        await db.execute(
            select(
                Activity.entity_id,
                Activity.user_id,
                Activity.created_at,
                Activity.details,
            ).where(
                Activity.entity_type == "job",
                Activity.entity_id.in_(ids),
                Activity.action == REPORT_ACTION,
            )
        )
    ).all()
    reporter_names = await _active_names(
        db, [uid for _j, uid, _a, _d in report_rows if uid]
    )
    for job_id, uid, at, details in report_rows:
        if not fresh(job_id, at):
            continue
        details = details if isinstance(details, dict) else {}
        note = str(details.get("note") or "").strip()
        signals[job_id].append(
            {
                "kind": "report",
                "at": _aware(at).isoformat(),
                "by_name": reporter_names.get(uid),
                "text": note or "Rekruter słyszy, że klient mógł wstrzymać rekrutację",
            }
        )

    note_since = moment - timedelta(days=NOTE_WINDOW_DAYS)
    note_rows = (
        await db.execute(
            select(Note.job_id, func.max(Note.created_at))
            .where(
                Note.job_id.in_(ids),
                Note.created_at >= note_since,
                Note.source_deleted_at.is_(None),
                or_(*(Note.content.ilike(pattern) for pattern in NOTE_PATTERNS)),
            )
            .group_by(Note.job_id)
        )
    ).all()
    for job_id, at in note_rows:
        if fresh(job_id, at):
            signals[job_id].append(
                {
                    "kind": "note",
                    "at": _aware(at).isoformat(),
                    "text": "Notatka zawiera „on hold”",
                }
            )

    week_ago = moment - timedelta(days=RECRUITER_WINDOW_DAYS)
    park_rows = (
        await db.execute(
            select(Activity.entity_id, Activity.created_at, Activity.details).where(
                Activity.entity_type == "job",
                Activity.entity_id.in_(ids),
                Activity.action == PARKED_ACTION,
                Activity.created_at >= note_since,
            )
        )
    ).all()
    parked: dict[int, datetime] = {}
    for job_id, at, details in park_rows:
        reason = (details or {}).get("reason") if isinstance(details, dict) else None
        if reason != "priority" or not fresh(job_id, at):
            continue
        if job_id not in parked or at > parked[job_id]:
            parked[job_id] = _aware(at)
    since = min([week_ago, *parked.values()])
    moves = await _recruiter_moves(db, ids, since=since)
    moves_7d: dict[int, int] = {}
    people_7d: dict[int, set[int]] = {}
    after_park: dict[int, int] = {}
    for job_id, uid, at in moves:
        at = _aware(at)
        if at >= week_ago:
            moves_7d[job_id] = moves_7d.get(job_id, 0) + 1
            people_7d.setdefault(job_id, set()).add(uid)
        if job_id in parked and at > parked[job_id]:
            after_park[job_id] = after_park.get(job_id, 0) + 1
    for job_id, at in parked.items():
        if parked_still_working(
            moves_after_park=after_park.get(job_id, 0),
            moves_7d=moves_7d.get(job_id, 0),
        ):
            signals[job_id].append(
                {
                    "kind": "parked_still_working",
                    "at": at.isoformat(),
                    "text": f"Zejście z P1 {_ddmm(at)}, rekruterzy dalej pracują",
                }
            )

    facts = await load_facts(db, ids)
    info = {row[0]: row for row in jobs}
    for job_id in ids:
        fact = facts.get(job_id)
        if fact is None:
            continue
        quiet = dl_silent_since(
            last_dl_move_at=fact.last_move_at,
            opened_at=fact.opened_at,
            anchor_at=anchors.get(job_id),
            recruiter_moves_7d=moves_7d.get(job_id, 0),
            now=moment,
        )
        if quiet is None:
            continue
        own = info[job_id][7] == viewer_id
        if fact.last_move_at is not None:
            text = f"{'Twój ostatni ruch' if own else 'Ostatni ruch DL'} {_ddmm(fact.last_move_at)}"
        else:
            text = f"Bez CV do klienta od otwarcia {_ddmm(fact.opened_at)}"
        signals[job_id].append(
            {"kind": "dl_silent", "at": quiet.isoformat(), "text": text}
        )

    items = []
    for row in jobs:
        job_id = row[0]
        if not signals[job_id]:
            continue
        priority = getattr(row[4], "value", row[4])
        items.append(
            {
                "job_id": job_id,
                "title": row[2] or row[1],
                "client_name": row[8],
                "reference": row[3],
                "priority": priority,
                "work_state": row[5],
                "recruiter_moves_7d": moves_7d.get(job_id, 0),
                "recruiters_7d": len(people_7d.get(job_id, set())),
                "signals": sort_signals(signals[job_id]),
            }
        )
    ordered = sort_items(items)
    return {"items": ordered[:CHECKS_LIMIT], "total": len(ordered)}


# ── Pętla ``job_idle``: termin sprawdzenia i 30 dni wstrzymania ────────────


async def _notice_markers(
    db: AsyncSession, job_ids: Sequence[int]
) -> set[tuple[int, str, str]]:
    """(job_id, akcja, klucz) — ``on`` terminu albo ``since`` wstrzymania."""
    if not job_ids:
        return set()
    rows = (
        await db.execute(
            select(Activity.entity_id, Activity.action, Activity.details).where(
                Activity.entity_type == "job",
                Activity.entity_id.in_(list(job_ids)),
                Activity.action.in_((REVIEW_NOTICE_ACTION, LONG_NOTICE_ACTION)),
            )
        )
    ).all()
    out: set[tuple[int, str, str]] = set()
    for job_id, action, details in rows:
        if not isinstance(details, dict):
            continue
        key = (
            details.get("on")
            if action == REVIEW_NOTICE_ACTION
            else details.get("since")
        )
        if key:
            out.add((job_id, action, str(key)))
    return out


def review_due(review_on: Optional[date], today: date) -> bool:
    return review_on is not None and review_on <= today


def long_hold_days(since: Optional[datetime], today: date) -> Optional[int]:
    """Dni wstrzymania od progu 30 dni, inaczej ``None``."""
    if since is None:
        return None
    days = (today - local_day(since)).days
    return days if days >= LONG_HOLD_DAYS else None


async def run_hold_notices(
    db: AsyncSession,
    *,
    now: datetime,
    only_job_ids: Optional[Sequence[int]] = None,
    leads_of: Optional[Callable[[Optional[int]], list[int]]] = None,
) -> dict[str, int]:
    """Jeden dzwonek do DL na termin „Sprawdzę z klientem” i jeden po 30 dniach.

    Znaczniki w ``Activity`` (``hold_review_notice`` z ``on`` = termin,
    ``hold_long_notice`` z ``since`` = początek wstrzymania), więc kolejne
    przebiegi i restart niczego nie powtarzają, a nowy termin to nowy dzwonek.
    Nigdy nie zamyka. Bez commitu — commituje pętla ``job_idle``."""
    today = local_day(now)
    query = (
        select(
            Job.id,
            Job.title,
            Job.working_title,
            Job.delivery_lead_id,
            Job.hold_reason,
            Job.hold_review_on,
            Job.work_state_changed_at,
            func.coalesce(Client.name, Client.display_name),
        )
        .join(Client, Client.id == Job.client_id, isouter=True)
        .where(Job.status == JobStatus.published, Job.work_state == ON_HOLD)
    )
    if only_job_ids is not None:
        query = query.where(Job.id.in_(list(only_job_ids)))
    rows = (await db.execute(query)).all()
    counts = {"hold_review": 0, "hold_long": 0, "hold_sent": 0}
    if not rows:
        return counts
    seen = await _notice_markers(db, [row[0] for row in rows])
    for job_id, title, working_title, lead_id, reason, review_on, since, client in rows:
        parts: list[str] = []
        review = review_due(review_on, today) and (
            (job_id, REVIEW_NOTICE_ACTION, review_on.isoformat()) not in seen
        )
        long_days = long_hold_days(since, today)
        long_hold = long_days is not None and (
            (job_id, LONG_NOTICE_ACTION, _aware(since).isoformat()) not in seen
        )
        if not review and not long_hold:
            continue
        name = working_title or title
        head = f"{name} · {client}" if client else name
        held = f"Wstrzymana od {_ddmm(since)}" + (f" ({reason})" if reason else "")
        if review:
            parts.append(
                f"Dziś termin „Sprawdzę z klientem” ({_ddmm(review_on)}). Wznów "
                "rekrutację, ustaw nowy termin albo ją zamknij."
            )
            db.add(
                Activity(
                    entity_type="job",
                    entity_id=job_id,
                    action=REVIEW_NOTICE_ACTION,
                    user_id=None,
                    details={"on": review_on.isoformat(), "day": today.isoformat()},
                )
            )
            counts["hold_review"] += 1
        if long_hold:
            parts.append(
                f"Rekrutacja jest wstrzymana od {long_days} dni. Jeśli klient nie "
                "wróci, zamknij ją z powodem „Wstrzymana przez klienta”. NEXUS nie "
                "zamknie jej sam."
            )
            db.add(
                Activity(
                    entity_type="job",
                    entity_id=job_id,
                    action=LONG_NOTICE_ACTION,
                    user_id=None,
                    details={
                        "since": _aware(since).isoformat(),
                        "days": long_days,
                        "on": today.isoformat(),
                    },
                )
            )
            counts["hold_long"] += 1
        title_text = (
            f"Wznawiamy? {name}"
            if review
            else f"{LONG_HOLD_DAYS} dni wstrzymania: {name}"
        )
        recipients = (
            leads_of(lead_id)
            if leads_of is not None
            else await lead_recipients(db, lead_id)
        )
        sent = await _bell(
            db,
            user_ids=recipients,
            title=title_text,
            message=f"{head}. {held}. " + " ".join(parts),
            ntype=NotificationType.job_hold_check,
            job_id=job_id,
            related_entity_id=job_id,
        )
        counts["hold_sent"] += len(sent)
    return counts
