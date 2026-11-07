"""Porcja dnia od Nexusa (decyzje Artura z 07.11.2026).

Raport i makiety M5–M11: https://claude.ai/artifact/36VRtoCfN6WXhTsRjfKmNi.
Od 03.11 system dodał karty do „Nowych” w 120 rekrutacjach, a w 101 z nich nikt
nie ruszył żadnej, więc kolumna stała pełna i lepsze osoby z nowszego
przeglądu nie wchodziły (26 z 26 wysłanych, które system miał w puli).

* Rano w dni robocze każda rekrutacja w pracy z rekruterem dostaje porcję do
  ``BATCH_SIZE`` osób od ``MIN_SCORE`` (silnik ``new_column_autofill`` w trybie
  porcji). Bez rekrutera porcji nie ma.
* Porcja dzieli się po równo między rekruterów rekrutacji, na zmianę od
  najlepszej osoby (``assign_owners``). Właściciel siedzi w
  ``entry_meta.review_owner_id`` karty od systemu.
* Decyzja = ruch karty od systemu z „Nowych” (screening albo odrzucenie
  z powodem), z przeglądu porcji albo z Tablicy. Pomijania nie ma.
* Dopóki rekruter nie podejmie dziś ``minimum`` decyzji (domyślnie 50, ustawia
  HoR), a w porcji ma jeszcze osoby, ręczne wyszukiwanie zwraca 423
  ``REVIEW_MINIMUM_PENDING`` (``assert_search_allowed``). Admin, HoR i DL
  bez blokady.
"""

from __future__ import annotations

import logging
import random
import re
from dataclasses import asdict, dataclass
from datetime import datetime, time, timezone
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import and_, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.core.scheduling import business_today
from app.models.app_setting import AppSetting
from app.models.job import Job, JobPriority
from app.models.recruitment_pipeline import CandidateStage
from app.models.recruitment_process import RecruitmentProcess
from app.models.user import User, UserRole
from app.services import candidate_claim

logger = logging.getLogger(__name__)

BATCH_SIZE = 20
MIN_SCORE = 65.0
DEFAULT_MINIMUM = 50
MAX_MINIMUM = 300
SETTING_KEY = "review_batch"
OWNER_KEY = "review_owner_id"
BLOCK_CODE = "REVIEW_MINIMUM_PENDING"
# Kolumna „Nowi” po samym etapie (lustro ``board_column_for`` dla enumów).
_NEW_STAGES = ("new", "posting")
_PRIORITY_RANK = {
    JobPriority.urgent: 1,
    JobPriority.high: 2,
    JobPriority.medium: 3,
    JobPriority.low: 4,
}


def enabled() -> bool:
    return bool(getattr(settings, "REVIEW_BATCH_ENABLED", False))


# ── Ustawienie HoR ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BatchSettings:
    minimum: int = DEFAULT_MINIMUM

    def as_dict(self) -> dict:
        return asdict(self)


def validation_error(value: BatchSettings) -> Optional[str]:
    if not 1 <= value.minimum <= MAX_MINIMUM:
        return f"Minimum musi być w zakresie 1–{MAX_MINIMUM}."
    return None


async def read_settings(db: AsyncSession) -> BatchSettings:
    row = await db.get(AppSetting, SETTING_KEY)
    if row is None or not isinstance(row.value, dict):
        return BatchSettings()
    try:
        return BatchSettings(minimum=int(row.value.get("minimum", DEFAULT_MINIMUM)))
    except (TypeError, ValueError):
        return BatchSettings()


async def write_settings(
    db: AsyncSession, value: BatchSettings, *, user_id: Optional[int]
) -> None:
    row = await db.get(AppSetting, SETTING_KEY)
    if row is None:
        db.add(AppSetting(key=SETTING_KEY, value=value.as_dict(), updated_by=user_id))
    else:
        row.value = value.as_dict()
        row.updated_by = user_id
    await db.flush()


# ── Karty porcji ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PendingCard:
    process_id: int
    job_id: int
    candidate_id: int
    owner_id: Optional[int]
    score: float
    opened_at: Optional[datetime]


def _latest_stage_is_new():
    """Ostatni etap pary stoi w „Nowych”."""
    later = CandidateStage.__table__.alias("later")
    return exists(
        select(CandidateStage.id).where(
            CandidateStage.job_id == RecruitmentProcess.job_id,
            CandidateStage.candidate_id == RecruitmentProcess.candidate_id,
            CandidateStage.stage.in_(_NEW_STAGES),
            ~exists(
                select(later.c.id).where(
                    later.c.job_id == CandidateStage.job_id,
                    later.c.candidate_id == CandidateStage.candidate_id,
                    (later.c.moved_at > CandidateStage.moved_at)
                    | (
                        and_(
                            later.c.moved_at == CandidateStage.moved_at,
                            later.c.id > CandidateStage.id,
                        )
                    ),
                )
            ),
        )
    )


def _score(meta) -> float:
    try:
        return float((meta or {}).get("score") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def owner_of(meta) -> Optional[int]:
    """Właściciel karty z porcji (``entry_meta.review_owner_id``)."""
    return _owner(meta)


def _owner(meta) -> Optional[int]:
    value = (meta or {}).get(OWNER_KEY) if isinstance(meta, dict) else None
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


async def pending_cards(
    db: AsyncSession,
    *,
    job_ids: Optional[Iterable[int]] = None,
    owner_id: Optional[int] = None,
) -> list[PendingCard]:
    """Karty od systemu, które czekają w „Nowych” na decyzję."""
    newer = RecruitmentProcess.__table__.alias("newer")
    stmt = select(
        RecruitmentProcess.id,
        RecruitmentProcess.job_id,
        RecruitmentProcess.candidate_id,
        RecruitmentProcess.entry_meta,
        RecruitmentProcess.opened_at,
    ).where(
        RecruitmentProcess.entry_source == candidate_claim.ENTRY_SYSTEM,
        RecruitmentProcess.voided_at.is_(None),
        _latest_stage_is_new(),
        # Karta od systemu jest najnowszym podejściem pary — osoba dodana potem
        # ręcznie (nowy proces) nie jest już porcją starego właściciela.
        ~exists(
            select(newer.c.id).where(
                newer.c.job_id == RecruitmentProcess.job_id,
                newer.c.candidate_id == RecruitmentProcess.candidate_id,
                newer.c.voided_at.is_(None),
                newer.c.opened_at > RecruitmentProcess.opened_at,
            )
        ),
    )
    if job_ids is not None:
        ids = sorted({int(j) for j in job_ids})
        if not ids:
            return []
        stmt = stmt.where(RecruitmentProcess.job_id.in_(ids))
    if owner_id is not None:
        stmt = stmt.where(
            RecruitmentProcess.entry_meta[OWNER_KEY].astext == str(int(owner_id))
        )
    rows = (await db.execute(stmt)).all()
    # Jedna karta na parę: najnowszy proces (ponowne podejście ma nowy wiersz).
    by_pair: dict[tuple[int, int], PendingCard] = {}
    for pid, job_id, candidate_id, meta, opened_at in rows:
        card = PendingCard(
            process_id=int(pid),
            job_id=int(job_id),
            candidate_id=int(candidate_id),
            owner_id=_owner(meta),
            score=_score(meta),
            opened_at=opened_at,
        )
        key = (card.job_id, card.candidate_id)
        prev = by_pair.get(key)
        if prev is None or (
            card.opened_at or datetime.min.replace(tzinfo=timezone.utc)
        ) > (prev.opened_at or datetime.min.replace(tzinfo=timezone.utc)):
            by_pair[key] = card
    return list(by_pair.values())


async def recruiter_ids_for_jobs(
    db: AsyncSession, job_ids: Iterable[int]
) -> dict[int, list[int]]:
    """Aktywni rekruterzy rekrutacji (reguła ``job_team``), bez propozycji
    automatu i bez kont innych ról (DL dopisany do zespołu porcji nie dostaje)."""
    from app.services.job_team import recruiters_for_jobs, working

    teams = await recruiters_for_jobs(db, job_ids)
    user_ids = {p.user_id for people in teams.values() for p in working(people)}
    if not user_ids:
        return {job_id: [] for job_id in teams}
    allowed = {
        user.id
        for user in (await db.scalars(select(User).where(User.id.in_(user_ids)))).all()
        if user.is_active and applies_to(user)
    }
    return {
        job_id: sorted({p.user_id for p in working(people) if p.user_id in allowed})
        for job_id, people in teams.items()
    }


def plan_owners(
    cards: list[PendingCard],
    team: list[int],
    *,
    seed: str,
    only: Optional[int] = None,
) -> dict[int, int]:
    """Kto dostaje którą kartę: proces → właściciel.

    Karty z właścicielem spoza zespołu wracają do podziału. Nowe idą od
    najlepszej do osoby z najmniejszą liczbą kart w tej rekrutacji; remis
    rozstrzyga losowa (stała w ciągu dnia) kolejność zespołu. ``only`` =
    wszystkie nowe karty do jednej osoby („Dodaj 20 kolejnych”)."""
    if not team:
        return {}
    members = list(team)
    random.Random(seed).shuffle(members)
    order = {uid: i for i, uid in enumerate(members)}
    load = {uid: 0 for uid in members}
    free: list[PendingCard] = []
    for card in cards:
        if card.owner_id in load:
            load[card.owner_id] += 1
        else:
            free.append(card)
    plan: dict[int, int] = {}
    for card in sorted(free, key=lambda c: (-c.score, c.candidate_id)):
        if only is not None and only in load:
            uid = only
        else:
            uid = min(members, key=lambda u: (load[u], order[u]))
        load[uid] += 1
        plan[card.process_id] = uid
    return plan


async def assign_owners(
    db: AsyncSession,
    job_id: int,
    *,
    now: datetime,
    only: Optional[int] = None,
) -> int:
    """Rozdziel czekające karty od systemu tej rekrutacji. Bez commitu."""
    team = (await recruiter_ids_for_jobs(db, [job_id])).get(job_id, [])
    cards = await pending_cards(db, job_ids=[job_id])
    plan = plan_owners(
        cards, team, seed=f"{job_id}:{business_today().isoformat()}", only=only
    )
    if not plan:
        return 0
    processes = (
        await db.scalars(
            select(RecruitmentProcess).where(RecruitmentProcess.id.in_(list(plan)))
        )
    ).all()
    for process in processes:
        meta = dict(process.entry_meta or {})
        meta[OWNER_KEY] = plan[process.id]
        process.entry_meta = meta
        flag_modified(process, "entry_meta")
    await db.flush()
    return len(plan)


async def _own_cards(db: AsyncSession, user_id: int) -> list[PendingCard]:
    """Karty osoby, tylko z rekrutacji, w których nadal jest rekruterem —
    osoba zdjęta z zespołu w ciągu dnia nie jest blokowana cudzą porcją."""
    from app.models.job import JobStatus
    from app.services.request_work_state import IN_WORK_STATES

    cards = await pending_cards(db, owner_id=user_id)
    if not cards:
        return []
    # Karty z rekrutacji zamkniętej albo wstrzymanej nie blokują nikogo.
    working = set(
        (
            await db.scalars(
                select(Job.id).where(
                    Job.id.in_({c.job_id for c in cards}),
                    Job.status == JobStatus.published,
                    Job.work_state.in_(IN_WORK_STATES),
                )
            )
        ).all()
    )
    cards = [c for c in cards if c.job_id in working]
    teams = await recruiter_ids_for_jobs(db, {c.job_id for c in cards})
    return [c for c in cards if user_id in teams.get(c.job_id, [])]


# ── Decyzje dziś ────────────────────────────────────────────────────────────


def day_start(now: Optional[datetime] = None) -> datetime:
    """Początek dzisiejszego dnia firmy (Europe/Warsaw) w UTC."""
    tz = ZoneInfo(settings.BUSINESS_TZ)
    today = business_today()
    return datetime.combine(today, time.min, tzinfo=tz).astimezone(timezone.utc)


async def decided_today(db: AsyncSession, user_id: int, *, now: datetime) -> int:
    """Ile kart od systemu ta osoba dziś wyprowadziła z „Nowych”."""
    since = day_start(now)
    stmt = (
        select(func.count(func.distinct(RecruitmentProcess.id)))
        .select_from(RecruitmentProcess)
        .join(
            CandidateStage,
            and_(
                CandidateStage.job_id == RecruitmentProcess.job_id,
                CandidateStage.candidate_id == RecruitmentProcess.candidate_id,
            ),
        )
        .where(
            RecruitmentProcess.entry_source == candidate_claim.ENTRY_SYSTEM,
            RecruitmentProcess.voided_at.is_(None),
            CandidateStage.moved_by == user_id,
            CandidateStage.moved_at >= since,
            CandidateStage.moved_at >= RecruitmentProcess.opened_at,
            CandidateStage.stage.not_in(_NEW_STAGES),
        )
    )
    return int((await db.scalar(stmt)) or 0)


# ── Stan osoby i blokada ────────────────────────────────────────────────────


@dataclass(frozen=True)
class JobShare:
    job_id: int
    title: str
    pending: int
    p0: bool

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class BatchStatus:
    enabled: bool
    applies: bool
    minimum: int
    done_today: int
    pending: int
    required: int
    met: bool
    jobs: tuple[JobShare, ...] = ()
    # Rekrutacje w pracy, w których osoba jest rekruterem (z czekającymi u niej
    # osobami albo bez) — lista do „Dodaj 20 kolejnych”.
    team_jobs: tuple[JobShare, ...] = ()

    @property
    def remaining(self) -> int:
        return max(0, self.required - self.done_today)

    def as_dict(self) -> dict:
        out = asdict(self)
        out["jobs"] = [j.as_dict() for j in self.jobs]
        out["team_jobs"] = [j.as_dict() for j in self.team_jobs]
        out["remaining"] = self.remaining
        return out


# Kto przegląda porcję i jest blokowany: rekruter bez żadnej z tych ról
# (konta mają role dodatkowe, np. admin z rolą rekrutera).
_EXEMPT_ROLES = (
    UserRole.admin,
    UserRole.head_of_recruitment,
    UserRole.delivery_lead,
)


def applies_to(user: User) -> bool:
    """Porcję dostaje i blokadę ma konto z rolą rekrutera bez roli admina,
    Head of Recruitment ani Delivery Leada (także jako roli dodatkowej)."""
    has_role = getattr(user, "has_role", None)
    if callable(has_role):
        return has_role(UserRole.recruiter) and not any(
            has_role(r) for r in _EXEMPT_ROLES
        )
    return getattr(user, "role", None) == UserRole.recruiter


def _priority_rank(job: Job, now: datetime) -> int:
    from app.services import job_p0

    if job_p0.is_active(job, now):
        return 0
    return _PRIORITY_RANK.get(job.priority, 3)


async def status_for(db: AsyncSession, user: User, *, now: datetime) -> BatchStatus:
    settings_value = await read_settings(db)
    if not enabled() or not applies_to(user):
        return BatchStatus(
            enabled=enabled(),
            applies=False,
            minimum=settings_value.minimum,
            done_today=0,
            pending=0,
            required=0,
            met=True,
        )
    cards = await _own_cards(db, user.id)
    done = await decided_today(db, user.id, now=now)
    # Kto ma w porcji mniej, niż brakuje do minimum, przegląda całą porcję.
    required = min(settings_value.minimum, done + len(cards))
    met = done >= required
    counts: dict[int, int] = {}
    for card in cards:
        counts[card.job_id] = counts.get(card.job_id, 0) + 1
    jobs: list[JobShare] = []
    if counts:
        from app.services import job_p0

        rows = (await db.scalars(select(Job).where(Job.id.in_(list(counts))))).all()
        ordered = sorted(rows, key=lambda j: (_priority_rank(j, now), j.id))
        jobs = [
            JobShare(
                job_id=j.id,
                title=j.title or "",
                pending=counts[j.id],
                p0=job_p0.is_active(j, now),
            )
            for j in ordered
        ]
    return BatchStatus(
        enabled=True,
        applies=True,
        minimum=settings_value.minimum,
        done_today=done,
        pending=len(cards),
        required=required,
        met=met,
        jobs=tuple(jobs),
        team_jobs=tuple(await _team_jobs(db, user.id, counts, now=now)),
    )


async def _team_jobs(
    db: AsyncSession, user_id: int, counts: dict[int, int], *, now: datetime
) -> list[JobShare]:
    from app.models.job import JobStatus
    from app.services import job_p0
    from app.services.job_team import jobs_worked_by_clause
    from app.services.request_work_state import IN_WORK_STATES

    rows = (
        await db.scalars(
            select(Job).where(
                jobs_worked_by_clause([user_id]),
                Job.status == JobStatus.published,
                Job.work_state.in_(IN_WORK_STATES),
            )
        )
    ).all()
    ordered = sorted(rows, key=lambda j: (_priority_rank(j, now), j.id))
    return [
        JobShare(
            job_id=j.id,
            title=j.title or "",
            pending=counts.get(j.id, 0),
            p0=job_p0.is_active(j, now),
        )
        for j in ordered
    ]


async def assert_search_allowed(db: AsyncSession, user: User) -> None:
    """423 ``REVIEW_MINIMUM_PENDING``, dopóki rekruter nie zrobi minimum."""
    if not enabled() or not applies_to(user):
        return
    status = await status_for(db, user, now=datetime.now(timezone.utc))
    if status.met:
        return
    raise HTTPException(
        status_code=423,
        detail={
            "code": BLOCK_CODE,
            "message": (
                f"Najpierw porcja od Nexusa: zostało {status.remaining} z "
                f"{status.required} decyzji. Wyszukiwanie ręczne wróci po "
                "minimum. Konkretną osobę znajdziesz po nazwisku, telefonie "
                "albo mailu."
            ),
            "done_today": status.done_today,
            "required": status.required,
            "remaining": status.remaining,
            "pending": status.pending,
        },
    )


# ── Kolejka przeglądu ───────────────────────────────────────────────────────


async def review_queue(
    db: AsyncSession, user: User, *, now: datetime, limit: int = 50
) -> list[PendingCard]:
    """Karty osoby w kolejności przeglądu: rekrutacje na zmianę (P0, potem
    priorytet), w każdej od najlepszej osoby."""
    cards = await _own_cards(db, user.id)
    if not cards:
        return []
    jobs = {
        j.id: j
        for j in (
            await db.scalars(select(Job).where(Job.id.in_({c.job_id for c in cards})))
        ).all()
    }
    by_job: dict[int, list[PendingCard]] = {}
    for card in cards:
        by_job.setdefault(card.job_id, []).append(card)
    for items in by_job.values():
        items.sort(key=lambda c: (-c.score, c.candidate_id))
    job_order = sorted(
        by_job,
        key=lambda jid: (
            _priority_rank(jobs[jid], now) if jid in jobs else 3,
            jid,
        ),
    )
    queue: list[PendingCard] = []
    depth = max(len(v) for v in by_job.values())
    for i in range(depth):
        for jid in job_order:
            items = by_job[jid]
            if i < len(items):
                queue.append(items[i])
    return queue[:limit]


# ── Czy zapytanie listy kandydatów to ręczne wyszukiwanie ──────────────────

# Parametry ``GET /api/candidates``, które nie zawężają bazy: strona,
# kolejność, dociągnięcia (``include_*``) i znaczniki stronicowania.
_NEUTRAL_LIST_PARAMS = frozenset(
    {
        "page",
        "page_size",
        "q",
        "sort",
        "status",
        "id_after",
        "updated_after",
        "changed_after",
        "semantics_version",
        "text_mode",
    }
)
_PERSON_KINDS = frozenset({"name", "email", "phone", "empty"})
_PHONE_PART = re.compile(r"^[+\d\s()\-]{3,}$")
_SKILL_RULES = frozenset({"known_skill", "known_city"})


def is_person_lookup(q: Optional[str]) -> bool:
    """Wyszukanie konkretnej osoby, także w trakcie pisania: 1–3 słowa jak
    imię i nazwisko (pojedyncze słowo spoza słownika umiejętności i miast,
    np. „Kowal” w drodze do „Kowalski”), mail albo jego początek („jan.kow”,
    „jan@”), telefon albo jego cyfry. Słowo ze słownika („java”, „node.js”)
    i opis to wyszukiwanie."""
    from app.services.candidate_search_predicates import detect_text_mode

    raw = (q or "").strip()
    found = detect_text_mode(raw)
    if found.kind in _PERSON_KINDS:
        return True
    if found.rule in _SKILL_RULES or " " in raw:
        return False
    return "@" in raw or "." in raw or bool(_PHONE_PART.match(raw))


async def is_broad_list_query(db: AsyncSession, params) -> bool:
    """Filtry albo opis w ``q`` = ręczne wyszukiwanie; samo nazwisko, mail
    albo telefon (wybór osoby, ⌘K, telefon od kandydata) — nie."""
    items = params.multi_items() if hasattr(params, "multi_items") else params.items()
    for key, value in items:
        if value in (None, ""):
            continue
        if key == "text_mode":
            if str(value).lower() == "semantic":
                return True
            continue
        if key in _NEUTRAL_LIST_PARAMS or key.startswith("include_"):
            continue
        return True
    return not is_person_lookup(params.get("q"))


# Pola ``POST /api/search/candidates`` (okno „+ Dodaj” na Tablicy), które nie
# zawężają bazy.
_NEUTRAL_BODY_FIELDS = frozenset(
    {
        "q",
        "sort",
        "page",
        "page_size",
        "search_mode",
        "text_mode",
        "semantics_version",
        "exclude_in_job_id",
        "exclude_blacklisted",
        "status",
    }
)


def is_broad_body_query(body) -> bool:
    """Ciało wyszukiwania zaawansowanego: same pola neutralne i ``q`` jak osoba
    = wyszukanie osoby, nie ręczne wyszukiwanie."""
    data = body.model_dump(exclude_defaults=True) if hasattr(body, "model_dump") else {}
    if str(data.get("text_mode") or "").lower() == "semantic":
        return True
    if any(key not in _NEUTRAL_BODY_FIELDS for key, value in data.items() if value):
        return True
    return not is_person_lookup(data.get("q"))


async def assert_body_search_allowed(db: AsyncSession, user: User, body) -> None:
    if not enabled() or not applies_to(user):
        return
    if not is_broad_body_query(body):
        return
    await assert_search_allowed(db, user)


async def assert_list_search_allowed(db: AsyncSession, user: User, params) -> None:
    if not enabled() or not applies_to(user):
        return
    if not await is_broad_list_query(db, params):
        return
    await assert_search_allowed(db, user)


REMOVAL_CODE = "REVIEW_CARD_NEEDS_DECISION"


async def assert_removal_allowed(
    db: AsyncSession, user: User, *, candidate_id: int, job_id: int
) -> None:
    """Karty z porcji nie da się zdjąć z rekrutacji zamiast decyzji (409).

    Usunięcie z rekrutacji kasuje kartę, więc znikała z porcji bez decyzji
    i bez powodu, a wymagane minimum malało — tak dało się przejść do
    wyszukiwania bez przeglądu (przegląd kodu 07.11.2026)."""
    if not enabled() or not applies_to(user):
        return
    cards = await pending_cards(db, job_ids=[job_id])
    if any(card.candidate_id == candidate_id for card in cards):
        raise HTTPException(
            status_code=409,
            detail={
                "code": REMOVAL_CODE,
                "message": (
                    "To osoba z porcji dnia od Nexusa. Zdecyduj: screening albo "
                    "odrzucenie z powodem — usunięcie z rekrutacji nie jest decyzją."
                ),
            },
        )
