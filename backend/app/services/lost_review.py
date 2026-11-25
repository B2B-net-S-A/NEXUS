"""Insights → „Przegrane”: przegląd przegranych rekrutacji na spotkanie z DL.

Decyzje Artura z 25.11.2026 (makiety: https://claude.ai/artifact/H3BNSMHGbmc33Uwuy7PK4K):
co miesiąc Delivery Leadzi z Head of Recruitment omawiają przegrane. Fakty liczy
NEXUS (etap przegranej, pierwsze CV, oceny klienta), DL dopowiada „Co zdecydowało?”
(okno zamknięcia albo spotkanie), a wnioski „ten klient” zostają zasadami klienta
z wynikiem „czy pomogło”. Reguła: ``docs/claude/finanse-insights/przegrane-przeglad-z-dl.md``.

- Wygrana / przegrana jak w hit ratio (``hit_ratio_closures.closure_group``):
  przegrana = ``competitor`` albo ``no_activity`` bez zatrudnienia od nas.
  „Do przejrzenia” (``other``/NULL) i „Nie liczy się” są poza modułem.
- Okno nie sięga przed 12.10.2026 (``competition_history.cutover_utc``) — wcześniej
  zamknięcia nie miały powodów.
- Etap przegranej = najdalszy etap, do którego doszła jakakolwiek nasza osoba
  (``analytics_first_milestones``).
- Ocena klienta = odrzucenie „Odrzuca klient” z powodem innym niż automatyczne
  ``client_chose_other`` / ``request_closed`` (te nadaje zamknięcie rekrutacji).
"""

from __future__ import annotations

import hashlib
import json
import logging
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Optional, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import DEFAULT_TZ, is_business_day
from app.models.ai_feature import AIFeatureKey
from app.models.client import Client
from app.models.job import Job, JobCloseReason, JobStatus
from app.models.lost_review import JobLossReview, LostReviewLesson
from app.models.user import User, UserRole
from app.services import competition_history
from app.services.client_identity import client_display_name_expression
from app.services.hit_ratio_closures import closure_group
from app.services.job_fill import filled_by_job
from app.services.rejection_reason_labels import rejection_reason_label

logger = logging.getLogger(__name__)

FEATURE = AIFeatureKey.lost_review_summary

# Kto widzi moduł i zapisuje wnioski — lustro `LOST_REVIEW_ROLES` na froncie.
VIEWER_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.head_of_recruitment,
    UserRole.delivery_lead,
)

# „Co zdecydowało?” — stała lista, do dwóch powodów. Lustro `LOST_WHY` na froncie.
WHY: dict[str, str] = {
    "competitor_faster": "Konkurent był szybszy",
    "competitor_cheaper": "Konkurent tańszy",
    "weaker_profile": "Słabszy profil od wybranego",
    "client_had_own": "Klient miał już swoją osobę",
    "candidate_withdrew": "Nasz kandydat się wycofał",
    "too_few_cvs": "Za mało CV / brak ludzi",
}
WHY_MAX = 2
SOURCES: dict[str, str] = {
    "client": "Klient powiedział",
    "ours": "Nasza ocena",
    "unknown": "Nie wiemy — zapytam klienta",
}
LESSON_SCOPES = ("job", "client", "all")
LESSON_MAX = 300
ASK_AFTER_BUSINESS_DAYS = 3
TREND_MONTHS = 6

STAGES = ("no_cv", "cv_only", "interview", "acceptance")
# Powody odrzuceń, które nadaje zamknięcie rekrutacji, a nie ocena klienta.
_AUTO_CLIENT_REASONS = ("client_chose_other", "request_closed")
_LOST_REASONS = (JobCloseReason.competitor, JobCloseReason.no_activity)
_MONTHS_PL = (
    "sty",
    "lut",
    "mar",
    "kwi",
    "maj",
    "cze",
    "lip",
    "sie",
    "wrz",
    "paź",
    "lis",
    "gru",
)


class LostReviewError(ValueError):
    """Błąd wejścia — trasa zamienia go na 422 z ``code``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ── Walidacja „Co zdecydowało?” ────────────────────────────────────────────


def clean_why(
    why: Optional[Iterable[str]], source: Optional[str]
) -> tuple[list[str], Optional[str]]:
    """Powody bez powtórzeń, w kolejności kliknięcia; 422 przy nieznanym kluczu."""
    keys: list[str] = []
    for key in why or ():
        if key not in WHY:
            raise LostReviewError("lost_why_unknown", "Nieznany powód przegranej.")
        if key not in keys:
            keys.append(key)
    if len(keys) > WHY_MAX:
        raise LostReviewError("lost_why_too_many", "Wybierz najwyżej dwa powody.")
    if source is not None and source not in SOURCES:
        raise LostReviewError(
            "lost_why_source_unknown", "Nieznana odpowiedź „Skąd wiesz?”."
        )
    return keys, source


def is_lost(job: Job) -> bool:
    return job.status == JobStatus.closed and job.close_reason in _LOST_REASONS


async def save_why(
    db: AsyncSession,
    job: Job,
    *,
    why: Optional[Iterable[str]],
    source: Optional[str],
    user_id: Optional[int],
    now: Optional[datetime] = None,
) -> Optional[JobLossReview]:
    """Zapis „Co zdecydowało?” bieżącego zamknięcia. Puste = usunięcie wiersza.

    Wołający sprawdza dostęp i commituje. Zmiana na „Nie wiemy” zaczyna liczenie
    przypomnienia od nowa.
    """
    keys, src = clean_why(why, source)
    if not is_lost(job) or job.closed_at is None:
        raise LostReviewError(
            "lost_why_not_lost",
            "„Co zdecydowało?” zapisuje się tylko przy przegranej rekrutacji.",
        )
    if await has_hire(db, job.id):
        raise LostReviewError(
            "lost_why_has_hire",
            "W tej rekrutacji jest zatrudnienie od nas — to nie jest przegrana.",
        )
    row = await db.get(JobLossReview, job.id)
    if not keys and src is None:
        if row is not None:
            await db.delete(row)
        return None
    moment = now or datetime.now(timezone.utc)
    if row is None:
        row = JobLossReview(job_id=job.id, closed_at=job.closed_at, why=keys)
        db.add(row)
    elif row.closed_at != job.closed_at or row.source != src:
        row.ask_reminded_at = None
    row.closed_at = job.closed_at
    row.why = keys
    row.source = src
    row.updated_by_id = user_id
    row.updated_at = moment
    return row


async def has_hire(db: AsyncSession, job_id: int) -> bool:
    return bool((await filled_by_job(db, [job_id])).get(job_id))


# ── Zamknięcia okna ─────────────────────────────────────────────────────────


@dataclass
class Closure:
    job_id: int
    title: str
    client_id: int
    client_name: str
    dl_id: Optional[int]
    close_reason: Optional[str]
    close_notes: Optional[str]
    closed_at: datetime
    opened_at: Optional[datetime]
    group: str


async def closures(
    db: AsyncSession, *, start: datetime, end: datetime
) -> list[Closure]:
    """Wygrane i przegrane zamknięte w [start, end), nie wcześniej niż 12.10.2026."""
    start = max(start, competition_history.cutover_utc())
    if start >= end:
        return []
    name = client_display_name_expression()
    rows = (
        await db.execute(
            select(
                Job.id,
                Job.title,
                Job.working_title,
                Job.client_id,
                name.label("client_name"),
                Job.delivery_lead_id,
                Job.close_reason,
                Job.close_notes,
                Job.closed_at,
                Job.opened_at,
                Job.created_at,
            )
            .join(Client, Client.id == Job.client_id)
            .where(
                Job.status == JobStatus.closed,
                Job.closed_at >= start,
                Job.closed_at < end,
            )
            .order_by(Job.closed_at.desc(), Job.id.desc())
        )
    ).all()
    hired = await filled_by_job(db, [r.id for r in rows])
    out: list[Closure] = []
    for r in rows:
        group = closure_group(r.close_reason, bool(hired.get(r.id)))
        if group not in ("won", "lost"):
            continue
        out.append(
            Closure(
                job_id=r.id,
                title=r.working_title or r.title,
                client_id=r.client_id,
                client_name=r.client_name or "—",
                dl_id=r.delivery_lead_id,
                close_reason=r.close_reason.value if r.close_reason else None,
                close_notes=(r.close_notes or "").strip() or None,
                closed_at=r.closed_at,
                opened_at=r.opened_at or r.created_at,
                group=group,
            )
        )
    return out


_MILESTONES_SQL = text(
    """
    SELECT job_id,
           count(*) FILTER (WHERE stage = 'cv_sent') AS cvs,
           count(*) FILTER (WHERE stage = 'client_interview') AS interviews,
           count(*) FILTER (WHERE stage IN ('acceptance', 'negotiation', 'onboarding', 'hired')) AS accepted,
           min(first_reached_at) FILTER (WHERE stage = 'cv_sent') AS first_cv
    FROM analytics_first_milestones
    WHERE job_id = ANY(:job_ids)
    GROUP BY job_id
    """
)

_VERDICTS_SQL = text(
    """
    SELECT cs.job_id, rr.name
    FROM candidate_stages cs
    JOIN rejection_reasons rr ON rr.id = cs.rejection_reason_id
    WHERE cs.job_id = ANY(:job_ids)
      AND cs.stage = 'rejected'
      AND cs.ended_by = 'client'
      AND rr.name <> ALL(:auto_reasons)
    """
)


@dataclass
class JobFacts:
    cvs: int = 0
    interviews: int = 0
    accepted: int = 0
    first_cv: Optional[datetime] = None
    verdicts: list[str] = field(default_factory=list)


async def job_facts(db: AsyncSession, job_ids: Sequence[int]) -> dict[int, JobFacts]:
    facts: dict[int, JobFacts] = {jid: JobFacts() for jid in job_ids}
    if not job_ids:
        return facts
    ids = list(job_ids)
    for r in (await db.execute(_MILESTONES_SQL, {"job_ids": ids})).all():
        f = facts[int(r.job_id)]
        f.cvs, f.interviews, f.accepted, f.first_cv = (
            int(r.cvs),
            int(r.interviews),
            int(r.accepted),
            r.first_cv,
        )
    rows = await db.execute(
        _VERDICTS_SQL, {"job_ids": ids, "auto_reasons": list(_AUTO_CLIENT_REASONS)}
    )
    for r in rows.all():
        facts[int(r.job_id)].verdicts.append(rejection_reason_label(r.name) or r.name)
    return facts


def loss_stage(f: JobFacts) -> str:
    if f.cvs == 0:
        return "no_cv"
    if f.accepted > 0:
        return "acceptance"
    if f.interviews > 0:
        return "interview"
    return "cv_only"


def client_pattern(stages: dict[str, int]) -> Optional[str]:
    """Jedno zdanie o tym, gdzie przegrywamy u klienta (reguła, nie model)."""
    if not any(stages.values()):
        return None
    top = max(STAGES, key=lambda s: (stages.get(s, 0), -STAGES.index(s)))
    return {
        "no_cv": "Nie wysyłamy CV",
        "cv_only": "CV nie przechodzą do rozmów",
        "interview": "Przegrywamy po rozmowach",
        "acceptance": "Tracimy po akceptacji",
    }[top]


def _days(a: Optional[datetime], b: Optional[datetime]) -> Optional[float]:
    if a is None or b is None:
        return None
    return round((b - a).total_seconds() / 86400, 1)


def _median(values: Iterable[Optional[float]]) -> Optional[float]:
    xs = [v for v in values if v is not None]
    return round(statistics.median(xs), 1) if xs else None


def _share(part: int, whole: int) -> Optional[int]:
    return round(part / whole * 100) if whole else None


def _hit(won: int, lost: int) -> Optional[float]:
    return round(won / (won + lost) * 100, 1) if won + lost else None


def _pl(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def _month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def _local(moment: datetime) -> date:
    return moment.astimezone(ZoneInfo(DEFAULT_TZ)).date()


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    return date(d.year + y, m + 1, 1)


def _local_midnight(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=ZoneInfo(DEFAULT_TZ))


# ── Odczyt modułu ───────────────────────────────────────────────────────────


async def compute(
    db: AsyncSession, *, start: datetime, end: datetime, now: Optional[datetime] = None
) -> dict[str, Any]:
    """Cała zawartość zakładki dla okna [start, end)."""
    now = now or datetime.now(timezone.utc)
    rows = await closures(db, start=start, end=end)
    won = [r for r in rows if r.group == "won"]
    lost = [r for r in rows if r.group == "lost"]
    facts = await job_facts(db, [r.job_id for r in rows])
    reviews = await _current_reviews(db, lost)
    names = await _user_names(db, {r.dl_id for r in rows if r.dl_id})

    stages = {s: 0 for s in STAGES}
    jobs: list[dict[str, Any]] = []
    for r in lost:
        f = facts[r.job_id]
        stage = loss_stage(f)
        stages[stage] += 1
        review = reviews.get(r.job_id)
        jobs.append(
            {
                "job_id": r.job_id,
                "title": r.title,
                "client_id": r.client_id,
                "client_name": r.client_name,
                "dl_id": r.dl_id,
                "dl_name": names.get(r.dl_id) if r.dl_id else None,
                "outcome": "idle" if r.close_reason == "no_activity" else "competitor",
                "stage": stage,
                "closed_at": r.closed_at.isoformat(),
                "days_open": _days(r.opened_at, r.closed_at),
                "days_first_cv": _days(r.opened_at, f.first_cv),
                "cvs": f.cvs,
                "interviews": f.interviews,
                "client_verdicts": f.verdicts,
                "notes": r.close_notes,
                "why": list(review.why) if review else [],
                "source": review.source if review else None,
                "ask_pending": bool(review and review.source == "unknown"),
            }
        )

    why_counter: Counter[str] = Counter()
    source_counter: Counter[str] = Counter()
    for j in jobs:
        why_counter.update(j["why"])
        if j["source"]:
            source_counter[j["source"]] += 1
    verdict_counter: Counter[str] = Counter(
        v for r in lost for v in facts[r.job_id].verdicts
    )
    known = sum(1 for j in jobs if j["client_verdicts"] or j["source"] == "client")

    def side(group: list[Closure]) -> dict[str, Any]:
        return {
            "count": len(group),
            "first_cv_days": _median(
                _days(r.opened_at, facts[r.job_id].first_cv) for r in group
            ),
            "cvs": _median(float(facts[r.job_id].cvs) for r in group),
            "interview_share": _share(
                sum(1 for r in group if facts[r.job_id].interviews), len(group)
            ),
        }

    lessons = await active_lessons(db)
    lesson_clients = await _client_names(db, {lesson.client_id for lesson in lessons})
    clients = await _clients(db, rows, facts, jobs, lessons, now=now)
    trend = await _trend(db, end=end, now=now)
    counts = {
        "won": len(won),
        "lost": len(lost),
        "competitor": sum(1 for r in lost if r.close_reason == "competitor"),
        "idle": sum(1 for r in lost if r.close_reason == "no_activity"),
    }
    payload = {
        "since": competition_history.cutover_utc().isoformat(),
        "counts": counts,
        "hit_ratio": _hit(len(won), len(lost)),
        "known": known,
        "why_filled": sum(1 for j in jobs if j["why"] or j["source"]),
        "stages": stages,
        "compare": {"won": side(won), "lost": side(lost)},
        "trend": trend,
        "why_counts": [
            {"key": k, "label": WHY[k], "count": why_counter[k]}
            for k in WHY
            if why_counter[k]
        ],
        "source_counts": {k: source_counter[k] for k in SOURCES},
        "client_verdicts": [
            {"label": label, "count": n} for label, n in verdict_counter.most_common(8)
        ],
        "clients": clients,
        "jobs": jobs,
        "lessons": [
            {
                **_lesson_payload(lesson),
                "client_name": lesson_clients.get(lesson.client_id),
            }
            for lesson in lessons
        ],
    }
    payload["findings"] = findings(payload)
    return payload


async def _current_reviews(
    db: AsyncSession, lost: list[Closure]
) -> dict[int, JobLossReview]:
    if not lost:
        return {}
    closed = {r.job_id: r.closed_at for r in lost}
    rows = (
        await db.execute(
            select(JobLossReview).where(JobLossReview.job_id.in_(list(closed)))
        )
    ).scalars()
    return {row.job_id: row for row in rows if row.closed_at == closed[row.job_id]}


async def _client_names(db: AsyncSession, ids: set[Optional[int]]) -> dict[int, str]:
    clean = [i for i in ids if i]
    if not clean:
        return {}
    name = client_display_name_expression()
    rows = await db.execute(
        select(Client.id, name.label("name")).where(Client.id.in_(clean))
    )
    return {int(r.id): r.name for r in rows.all()}


async def _user_names(db: AsyncSession, ids: set[Optional[int]]) -> dict[int, str]:
    clean = [i for i in ids if i]
    if not clean:
        return {}
    rows = await db.execute(select(User.id, User.name).where(User.id.in_(clean)))
    return {int(r.id): r.name for r in rows.all()}


async def _clients(
    db: AsyncSession,
    rows: list[Closure],
    facts: dict[int, JobFacts],
    jobs: list[dict[str, Any]],
    lessons: list[LostReviewLesson],
    *,
    now: datetime,
) -> list[dict[str, Any]]:
    by_client: dict[int, dict[str, Any]] = {}
    for r in rows:
        c = by_client.setdefault(
            r.client_id,
            {
                "client_id": r.client_id,
                "name": r.client_name,
                "won": 0,
                "lost": 0,
                "idle": 0,
                "stages": {s: 0 for s in STAGES},
                "_verdicts": Counter(),
                "_why": Counter(),
            },
        )
        if r.group == "won":
            c["won"] += 1
            continue
        c["lost"] += 1
        c["idle"] += int(r.close_reason == "no_activity")
        c["_verdicts"].update(facts[r.job_id].verdicts)
    for j in jobs:
        c = by_client[j["client_id"]]
        c["stages"][j["stage"]] += 1
        c["_why"].update(WHY[k] for k in j["why"])

    client_lessons = [
        lesson for lesson in lessons if lesson.scope == "client" and lesson.client_id
    ]
    effects = await lesson_effects(db, client_lessons, now=now)
    out = []
    for c in by_client.values():
        verdicts, why = c.pop("_verdicts"), c.pop("_why")
        c["hit_ratio"] = _hit(c["won"], c["lost"])
        c["pattern"] = client_pattern(c["stages"])
        c["verdicts"] = [{"label": k, "count": n} for k, n in verdicts.most_common(3)]
        c["why"] = [{"label": k, "count": n} for k, n in why.most_common(3)]
        c["lessons"] = [
            {**_lesson_payload(lesson), "effect": effects.get(lesson.id)}
            for lesson in client_lessons
            if lesson.client_id == c["client_id"]
        ][:3]
        out.append(c)
    # Klienci bez przegranych (same wygrane) na końcu, najpierw najwięcej przegranych.
    out.sort(key=lambda c: (-c["lost"], -c["won"], c["name"]))
    return out


async def _trend(
    db: AsyncSession, *, end: datetime, now: datetime
) -> list[dict[str, Any]]:
    """Wygrane / przegrane per miesiąc: do ``TREND_MONTHS`` miesięcy do końca okna."""
    last_day = _local(min(end, now) - timedelta(seconds=1))
    first = max(
        _add_months(_month_start(last_day), -(TREND_MONTHS - 1)),
        _month_start(_local(competition_history.cutover_utc())),
    )
    rows = await closures(
        db,
        start=_local_midnight(first),
        end=_local_midnight(_add_months(_month_start(last_day), 1)),
    )
    months: list[dict[str, Any]] = []
    m = first
    while m <= _month_start(last_day):
        won = sum(
            1
            for r in rows
            if r.group == "won" and _month_start(_local(r.closed_at)) == m
        )
        lost = sum(
            1
            for r in rows
            if r.group == "lost" and _month_start(_local(r.closed_at)) == m
        )
        months.append(
            {
                "month": m.strftime("%Y-%m"),
                "label": f"{_MONTHS_PL[m.month - 1]} {m.year % 100:02d}",
                "won": won,
                "lost": lost,
                "hit_ratio": _hit(won, lost),
            }
        )
        m = _add_months(m, 1)
    return months


def findings(p: dict[str, Any]) -> list[str]:
    """Wnioski z reguł kodu — zawsze na ekranie, także bez modelu AI."""
    out: list[str] = []
    won, lost = p["compare"]["won"], p["compare"]["lost"]
    n_lost = p["counts"]["lost"]
    if not n_lost:
        return ["W tym okresie nie ma przegranych rekrutacji."]
    if won["interview_share"] is not None and lost["interview_share"] is not None:
        gap = won["interview_share"] - lost["interview_share"]
        if gap >= 15:
            out.append(
                f"Przegrywamy na przejściu z CV do rozmowy: rozmowę u klienta miało "
                f"{lost['interview_share']}% przegranych i {won['interview_share']}% wygranych."
            )
    if won["first_cv_days"] is not None and lost["first_cv_days"] is not None:
        diff = lost["first_cv_days"] - won["first_cv_days"]
        if diff >= 2:
            out.append(
                f"W przegranych pierwsze CV szło o {_pl(diff)} dnia później "
                f"(mediana {_pl(lost['first_cv_days'])} wobec {_pl(won['first_cv_days'])})."
            )
        elif abs(diff) < 2 and n_lost >= 5:
            out.append(
                "Szybkość pierwszego CV nie różni wygranych od przegranych "
                f"(mediana {_pl(won['first_cv_days'])} i {_pl(lost['first_cv_days'])} dnia)."
            )
    stages = p["stages"]
    if stages["cv_only"] and stages["cv_only"] >= n_lost / 2:
        out.append(
            f"W {stages['cv_only']} z {n_lost} przegranych klient nie zaprosił nikogo od nas na rozmowę."
        )
    unknown = n_lost - p["known"]
    if unknown:
        out.append(
            f"W {unknown} z {n_lost} przegranych nie wiemy, co klient myśli o naszych osobach — "
            "warto zapytać przed spotkaniem."
        )
    if p["counts"]["idle"]:
        out.append(
            f"{p['counts']['idle']} przegranych zamknął NEXUS po 28 dniach bez ruchu — "
            "sprawdźcie, czy klient naprawdę wybrał kogoś innego."
        )
    top = next((c for c in p["clients"] if c["lost"] >= 3 and c["pattern"]), None)
    if top:
        out.append(f"{top['name']}: {top['lost']} przegranych. {top['pattern']}.")
    if p["why_counts"]:
        best = max(p["why_counts"], key=lambda w: w["count"])
        out.append(
            f"Najczęstszy powód według DL: „{best['label']}” ({best['count']}×)."
        )
    return out


# ── Wnioski ze spotkania (zasady klienta) ──────────────────────────────────


async def active_lessons(db: AsyncSession) -> list[LostReviewLesson]:
    rows = await db.execute(
        select(LostReviewLesson)
        .where(LostReviewLesson.archived_at.is_(None))
        .order_by(LostReviewLesson.created_at.desc(), LostReviewLesson.id.desc())
        .limit(200)
    )
    return list(rows.scalars())


def _lesson_payload(lesson: LostReviewLesson) -> dict[str, Any]:
    return {
        "id": lesson.id,
        "scope": lesson.scope,
        "client_id": lesson.client_id,
        "job_id": lesson.job_id,
        "text": lesson.text,
        "created_at": lesson.created_at.isoformat() if lesson.created_at else None,
    }


async def lesson_effects(
    db: AsyncSession, lessons: list[LostReviewLesson], *, now: datetime
) -> dict[int, dict[str, Any]]:
    """„Czy pomogło”: wygrane i przegrane klienta przed zasadą i po niej (od 12.10)."""
    if not lessons:
        return {}
    rows = await closures(db, start=competition_history.cutover_utc(), end=now)
    out: dict[int, dict[str, Any]] = {}
    for lesson in lessons:
        mine = [r for r in rows if r.client_id == lesson.client_id]
        before = [r for r in mine if r.closed_at < lesson.created_at]
        after = [r for r in mine if r.closed_at >= lesson.created_at]

        def tally(group: list[Closure]) -> dict[str, Any]:
            w = sum(1 for r in group if r.group == "won")
            lo = sum(1 for r in group if r.group == "lost")
            return {"won": w, "lost": lo, "hit_ratio": _hit(w, lo)}

        out[lesson.id] = {"before": tally(before), "after": tally(after)}
    return out


async def add_lesson(
    db: AsyncSession,
    *,
    scope: str,
    text_value: str,
    job_id: Optional[int],
    client_id: Optional[int],
    user_id: Optional[int],
) -> LostReviewLesson:
    body = " ".join((text_value or "").split())
    if not body:
        raise LostReviewError("lesson_text_required", "Wpisz, co zmieniamy.")
    if len(body) > LESSON_MAX:
        raise LostReviewError("lesson_text_too_long", f"Najwyżej {LESSON_MAX} znaków.")
    if scope not in LESSON_SCOPES:
        raise LostReviewError("lesson_scope_unknown", "Nieznany zakres wniosku.")
    if job_id is not None:
        job = await db.get(Job, job_id)
        if job is None:
            raise LostReviewError("lesson_job_not_found", "Nie ma takiej rekrutacji.")
        client_id = job.client_id
    if scope in ("job", "client") and client_id is None:
        raise LostReviewError(
            "lesson_client_required",
            "Wniosek dla klienta wymaga rekrutacji albo klienta.",
        )
    if scope == "job" and job_id is None:
        raise LostReviewError(
            "lesson_job_required", "Wniosek dla rekrutacji wymaga rekrutacji."
        )
    lesson = LostReviewLesson(
        scope=scope,
        text=body,
        job_id=job_id,
        client_id=None if scope == "all" else client_id,
        created_by_id=user_id,
    )
    db.add(lesson)
    await db.flush()
    return lesson


async def archive_lesson(
    db: AsyncSession, lesson_id: int, *, now: Optional[datetime] = None
) -> bool:
    lesson = await db.get(LostReviewLesson, lesson_id)
    if lesson is None or lesson.archived_at is not None:
        return False
    lesson.archived_at = now or datetime.now(timezone.utc)
    return True


async def client_rules(db: AsyncSession, client_id: int) -> list[dict[str, Any]]:
    """Aktywne zasady klienta i wnioski dla wszystkich — do strony rekrutacji klienta."""
    rows = await db.execute(
        select(LostReviewLesson)
        .where(
            LostReviewLesson.archived_at.is_(None),
            (LostReviewLesson.scope == "all")
            | (
                (LostReviewLesson.scope == "client")
                & (LostReviewLesson.client_id == client_id)
            ),
        )
        .order_by(LostReviewLesson.created_at.desc())
        .limit(5)
    )
    return [_lesson_payload(lesson) for lesson in rows.scalars()]


# ── R3: pytanie do hiring managera i przypomnienie ─────────────────────────


def client_question(
    *, title: str, cvs: int, interviews: int, sender: Optional[str]
) -> dict[str, str]:
    """Krótki mail do HM — DL wysyła go ze swojej skrzynki. Bez nazwisk kandydatów."""
    ours = "naszym kandydatom" if cvs != 1 else "naszemu kandydatowi"
    first = (
        "1. Co zdecydowało o wyborze innej osoby po rozmowach?"
        if interviews
        else "1. Co zdecydowało o wyborze innej osoby?"
    )
    lines = [
        "Dzień dobry,",
        "",
        f"dziękujemy za proces na stanowisko {title}. Wiemy, że wybrali Państwo inną osobę. "
        "Chcemy lepiej dobierać kandydatów do kolejnych Państwa potrzeb, dlatego mamy trzy krótkie pytania:",
        "",
        first,
        f"2. Czego zabrakło {ours}?"
        if cvs
        else "2. Czy brakowało Państwu kandydatów od nas na czas?",
        "3. Czy znaczenie miały stawka albo termin dostępności?",
        "",
        "Wystarczą dwa–trzy zdania. Każda uwaga bardzo nam pomoże.",
        "",
        "Pozdrawiam,",
        sender or "",
    ]
    return {
        "subject": f"Krótkie pytanie o proces: {title}",
        "body": "\n".join(lines).rstrip(),
    }


def business_days_since(start: datetime, now: datetime) -> int:
    zone = ZoneInfo(DEFAULT_TZ)
    day = start.astimezone(zone).date() + timedelta(days=1)
    last = now.astimezone(zone).date()
    n = 0
    while day <= last:
        if is_business_day(datetime(day.year, day.month, day.day, 12, tzinfo=zone)):
            n += 1
        day += timedelta(days=1)
    return n


async def run_ask_reminders(db: AsyncSession, *, now: datetime) -> int:
    """Dzwonek do DL po 3 dniach roboczych od „Nie wiemy — zapytam klienta”.

    Typ `request_review_needed` (zadanie dla DL, bez maila), jeden na zamknięcie.
    Bez commitu — wołający commituje.
    """
    from app.services.notification_triggers import emit  # noqa: PLC0415
    from app.models.notification import NotificationType  # noqa: PLC0415

    rows = (
        await db.execute(
            select(JobLossReview, Job)
            .join(Job, Job.id == JobLossReview.job_id)
            .where(
                JobLossReview.source == "unknown",
                JobLossReview.ask_reminded_at.is_(None),
                Job.status == JobStatus.closed,
                Job.closed_at == JobLossReview.closed_at,
            )
        )
    ).all()
    sent = 0
    for review, job in rows:
        if business_days_since(review.updated_at, now) < ASK_AFTER_BUSINESS_DAYS:
            continue
        target = job.delivery_lead_id or review.updated_by_id
        review.ask_reminded_at = now
        if target is None:
            continue
        title = job.working_title or job.title
        created = await emit(
            db,
            user_id=target,
            title="Zapytaj klienta, dlaczego przegraliśmy",
            message=(
                f"„{title}”: przy zamknięciu zaznaczono „Nie wiemy — zapytam klienta”. "
                "Gotowe pytanie do hiring managera czeka w Insights → Przegrane."
            ),
            ntype=NotificationType.request_review_needed,
            related_entity_type="job_loss_review",
            related_entity_id=job.id,
            link=f"/insights?tab=przegrane&job={job.id}",
        )
        sent += int(created is not None)
    await db.flush()
    return sent


async def run_ask_reminders_safely(now: datetime) -> Optional[int]:
    """Własna sesja i commit; nigdy nie rzuca (pętla ``job_idle``)."""
    from app.core.database import AsyncSessionLocal  # noqa: PLC0415

    try:
        async with AsyncSessionLocal() as db:
            sent = await run_ask_reminders(db, now=now)
            await db.commit()
    except Exception:  # noqa: BLE001 — pętla nie może przez to stanąć
        logger.exception("lost_review: przypomnienia nie powiodły się")
        return None
    if sent:
        logger.info("lost_review: przypomnienia o pytaniu do klienta: %s", sent)
    return sent


# ── Wnioski AI (F56) ────────────────────────────────────────────────────────


_STAGE_LABELS = {
    "no_cv": "bez CV",
    "cv_only": "CV bez rozmowy",
    "interview": "po rozmowie u klienta",
    "acceptance": "po akceptacji",
}


def _stages_pl(stages: dict[str, int]) -> dict[str, int]:
    return {_STAGE_LABELS[k]: stages.get(k, 0) for k in STAGES}


def _side_pl(side: dict[str, Any]) -> dict[str, Any]:
    return {
        "rekrutacji": side["count"],
        "pierwsze_cv_po_dniach_mediana": side["first_cv_days"],
        "cv_na_rekrutacje_mediana": side["cvs"],
        "z_rozmowa_u_klienta_pct": side["interview_share"],
    }


def model_input(p: dict[str, Any]) -> dict[str, Any]:
    """To, co dostaje model: liczby i etykiety z list. Bez nazwisk, notatek i stawek.

    Klucze i etapy po polsku — model cytuje je w tekście dla ludzi.
    """
    counts = p["counts"]
    return {
        "okres": p.get("period_label"),
        "liczby": {
            "wygrane": counts["won"],
            "przegrane": counts["lost"],
            "przegrane_konkurencja": counts["competitor"],
            "przegrane_zamkniete_przez_NEXUS_po_28_dniach_bez_ruchu": counts["idle"],
        },
        "hit_ratio_pct": p["hit_ratio"],
        "etap_przegranej": _stages_pl(p["stages"]),
        "wygrane": _side_pl(p["compare"]["won"]),
        "przegrane": _side_pl(p["compare"]["lost"]),
        "trend": [
            {
                "miesiac": m["label"],
                "wygrane": m["won"],
                "przegrane": m["lost"],
                "hit_ratio_pct": m["hit_ratio"],
            }
            for m in p["trend"]
        ],
        "co_zdecydowalo_wg_DL": [
            {"powod": w["label"], "ile": w["count"]} for w in p["why_counts"]
        ],
        "skad_wiedza": {SOURCES[k]: n for k, n in p["source_counts"].items()},
        "oceny_klienta_naszych_osob": [
            {"ocena": v["label"], "ile": v["count"]} for v in p["client_verdicts"]
        ],
        "przegrane_bez_oceny_klienta": counts["lost"] - p["known"],
        "klienci": [
            {
                "klient": c["name"],
                "wygrane": c["won"],
                "przegrane": c["lost"],
                "zamkniete_przez_NEXUS_bez_ruchu": c["idle"],
                "etap_przegranej": _stages_pl(c["stages"]),
                "oceny_klienta": [
                    {"ocena": v["label"], "ile": v["count"]} for v in c["verdicts"]
                ],
                "co_zdecydowalo": [
                    {"powod": v["label"], "ile": v["count"]} for v in c["why"]
                ],
                "zasady_z_poprzednich_spotkan": [
                    {"tekst": lesson["text"], "efekt": lesson.get("effect")}
                    for lesson in c["lessons"]
                ],
            }
            for c in p["clients"][:12]
        ],
        "wnioski_dla_wszystkich": [
            lesson["text"] for lesson in p["lessons"] if lesson["scope"] == "all"
        ][:10],
    }


def input_hash(data: dict[str, Any]) -> str:
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _json_object(raw: str) -> dict[str, Any]:
    body = raw.strip()
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("model nie zwrócił obiektu JSON")
    parsed = json.loads(body[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("model nie zwrócił obiektu JSON")
    return parsed


def _texts(value: Any, limit: int, size: int = 400) -> list[str]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip()[:size])
        if len(out) >= limit:
            break
    return out


def check_summary(raw: str, client_names: Iterable[str]) -> dict[str, Any]:
    """Kształt odpowiedzi modelu; rada dla klienta spoza okresu idzie do „wszyscy”."""
    data = _json_object(raw)
    known = {n.casefold(): n for n in client_names}
    advice = []
    for item in data.get("rady") or []:
        if not isinstance(item, dict):
            continue
        tekst = item.get("tekst")
        if not isinstance(tekst, str) or not tekst.strip():
            continue
        dla = item.get("dla")
        target = known.get(dla.casefold()) if isinstance(dla, str) else None
        advice.append({"for": target or "wszyscy", "text": tekst.strip()[:400]})
        if len(advice) >= 8:
            break
    result = {
        "conclusions": _texts(data.get("wnioski"), 6),
        "advice": advice,
        "questions": _texts(data.get("pytania_na_spotkanie"), 5),
    }
    if not result["conclusions"] and not advice:
        raise ValueError("pusta odpowiedź modelu")
    return result


def _call_model(prompt: str) -> str:
    """Jedno wywołanie modelu (w wątku). Osobna funkcja: testy ją podmieniają."""
    from app.services.ai_models import fallbacks_for, model_for  # noqa: PLC0415
    from app.services.claude_client import call_claude, text_of  # noqa: PLC0415
    from app.services.llm_prompts import LOST_REVIEW_SUMMARY  # noqa: PLC0415

    message = call_claude(
        model=model_for(FEATURE),
        fallback_models=list(fallbacks_for(FEATURE)),
        max_tokens=3000,
        timeout=90,
        max_retries=1,
        total_timeout=150,
        system=LOST_REVIEW_SUMMARY.system_prompt or "",
        thinking={"type": "disabled"},
        messages=[{"role": "user", "content": prompt}],
    )
    return text_of(message)


def build_prompt(data: dict[str, Any]) -> str:
    from app.services.llm_prompts import LOST_REVIEW_SUMMARY  # noqa: PLC0415
    from app.services.prompt_fencing import fence, json_for_prompt  # noqa: PLC0415

    return LOST_REVIEW_SUMMARY.render(dane=fence("dane", json_for_prompt(data)))


async def ai_summary(
    db: AsyncSession, payload: dict[str, Any], *, user_id: Optional[int]
) -> dict[str, Any]:
    """Wnioski, rady i pytania na spotkanie. Błąd modelu = ``LostReviewError``."""
    from starlette.concurrency import run_in_threadpool  # noqa: PLC0415

    from app.services.ai_models import model_for  # noqa: PLC0415
    from app.services.ai_quota import ai_feature  # noqa: PLC0415
    from app.services.llm_providers import api_key_configured  # noqa: PLC0415

    if not payload["counts"]["lost"]:
        raise LostReviewError(
            "lost_review_nothing", "W tym okresie nie ma przegranych do omówienia."
        )
    if not api_key_configured(model_for(FEATURE)):
        raise LostReviewError(
            "lost_review_ai_unconfigured", "Model AI nie jest skonfigurowany."
        )
    data = model_input(payload)
    try:
        async with ai_feature(db, FEATURE, user_id=user_id):
            # Licznik AI zapisuje wiersz w tej sesji — commit PRZED modelem.
            await db.commit()
            raw = await run_in_threadpool(_call_model, build_prompt(data))
        result = check_summary(raw, (c["name"] for c in payload["clients"]))
    except LostReviewError:
        raise
    except Exception as exc:  # noqa: BLE001 — wynik modelu to dodatek
        logger.warning("[lost_review] wnioski AI nieudane (%s)", type(exc).__name__)
        raise LostReviewError(
            "lost_review_ai_failed",
            "Nie udało się przygotować wniosków AI. Liczby i wnioski z reguł są na ekranie — spróbuj za chwilę.",
        ) from exc
    return {
        **result,
        "model": model_for(FEATURE),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
