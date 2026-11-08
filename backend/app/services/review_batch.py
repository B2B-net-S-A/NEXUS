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
* Dopóki rekruter nie podejmie dziś ``minimum`` decyzji (domyślnie 10, ustawia
  HoR), a w porcji ma jeszcze osoby, ręczne wyszukiwanie zwraca 423
  ``REVIEW_MINIMUM_PENDING`` (``assert_search_allowed``). Admin, HoR i DL
  bez blokady.
* Bezpieczne włączenie (decyzja Artura 08.11.2026, audyt na kopii z 06.11):
  w porcji tylko karty od ``MIN_SCORE`` nie starsze niż ``MAX_AGE_DAYS``
  (``in_batch``), blokada tylko w dni robocze od ``BLOCK_START_HOUR``,
  a HoR ma wyłącznik blokady i listę pilotażową bez wdrożenia
  (``BatchSettings.block_enabled``, ``pilot_user_ids``).
* Etap 0 przed pilotem (audyt 08.11.2026): decyzja to tylko wyjście z „Nowych”,
  „Do screeningu” liczy się po ruchu dalej albo zapisanym screeningu
  (``_decisions``), kolejność jak na Tablicy (``review_batch_order``), osoba
  nieobecna nie dostaje kart i nie ma blokady, filtry własnej pracy przechodzą
  (``is_broad_list_query``).
"""

from __future__ import annotations

import logging
import random
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.core.scheduling import business_today, is_business_day, local_day_start_utc
from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.job import Job, JobPriority
from app.models.recruitment_pipeline import CandidateStage
from app.models.recruitment_process import RecruitmentProcess
from app.models.user import User, UserRole
from app.services import candidate_claim, review_batch_levels

logger = logging.getLogger(__name__)

BATCH_SIZE = 20
MIN_SCORE = 65.0
# Próg porcji ustawia HoR; poniżej 50% system i tak nie proponuje nikogo sensownego.
MIN_SCORE_FLOOR = 50.0
MIN_SCORE_CEIL = 95.0
# W pierwszym przebiegu każda rekrutacja dostaje tyle osób, zanim inne dostaną
# resztę: 2 100 dodań przy 100 na tick to ponad 20 minut od 7:00 (W8).
FIRST_ROUND_CARDS = 5
# „Do screeningu” liczy się po domknięciu w tylu dniach roboczych (P5).
SCREENING_CLOSE_DAYS = 2
# 08.11.2026: 50 → 10. Na kopii z 06.11 rekruterzy podejmowali 4,7–7,8 decyzji
# dziennie o kartach od systemu (najwięcej 29), więc 50 blokowało 12 z 16 osób
# na cały dzień. Kolejne progi (20, 30) ustawia HoR po pomiarze.
DEFAULT_MINIMUM = 10
# Karta starsza niż tyle dni nie jest porcją: pierwsza porcja z 06.11 miała
# 1 440 kart, z czego ok. 850 starszych niż 7 dni i 147 poniżej 65%.
MAX_AGE_DAYS = 7
# Blokada od godziny porcji (silnik „Nowych” rusza o 7:00), nie od północy.
BLOCK_START_HOUR = 7
MAX_MINIMUM = 300
SETTING_KEY = "review_batch"
OWNER_KEY = "review_owner_id"
BLOCK_CODE = "REVIEW_MINIMUM_PENDING"
BLOCK_ACTION = "review_batch.blocked"
BLOCK_ENTITY = "review_batch"
# Ślad blokady: jeden wpis na osobę na tyle czasu, bo front ponawia zapytania.
BLOCK_LOG_EVERY = timedelta(minutes=10)
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
    # Wyłącznik samej blokady 423 bez wdrożenia (porcja dalej się rozdziela).
    block_enabled: bool = True
    # Pilot: blokada tylko dla tych kont; pusta lista = wszyscy rekruterzy.
    pilot_user_ids: tuple[int, ...] = ()
    # Od jakiego wyniku karta wchodzi do porcji.
    min_score: float = MIN_SCORE

    def as_dict(self) -> dict:
        out = asdict(self)
        out["pilot_user_ids"] = list(self.pilot_user_ids)
        return out

    def blocks(self, user_id: int) -> bool:
        if not self.block_enabled:
            return False
        return not self.pilot_user_ids or user_id in self.pilot_user_ids


def validation_error(value: BatchSettings) -> Optional[str]:
    if not 1 <= value.minimum <= MAX_MINIMUM:
        return f"Minimum musi być w zakresie 1–{MAX_MINIMUM}."
    if not MIN_SCORE_FLOOR <= value.min_score <= MIN_SCORE_CEIL:
        return (
            f"Próg wyniku musi być w zakresie {MIN_SCORE_FLOOR:.0f}–"
            f"{MIN_SCORE_CEIL:.0f}%."
        )
    return None


def _pilot(raw) -> tuple[int, ...]:
    if not isinstance(raw, (list, tuple)):
        return ()
    out: set[int] = set()
    for value in raw:
        try:
            out.add(int(value))
        except (TypeError, ValueError):
            continue
    return tuple(sorted(out))


async def read_settings(db: AsyncSession) -> BatchSettings:
    row = await db.get(AppSetting, SETTING_KEY)
    if row is None or not isinstance(row.value, dict):
        return BatchSettings()
    try:
        minimum = int(row.value.get("minimum", DEFAULT_MINIMUM))
    except (TypeError, ValueError):
        minimum = DEFAULT_MINIMUM
    try:
        min_score = float(row.value.get("min_score", MIN_SCORE))
    except (TypeError, ValueError):
        min_score = MIN_SCORE
    return BatchSettings(
        minimum=minimum,
        min_score=min_score,
        block_enabled=row.value.get("block_enabled", True) is not False,
        pilot_user_ids=_pilot(row.value.get("pilot_user_ids")),
    )


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
    # Migawka z ``entry_meta`` do kolejności (``review_batch_order``).
    cautions: tuple = ()
    missing_must: tuple = ()
    availability_status: Optional[str] = None
    rate_from_hourly: Optional[float] = None
    rate_currency: Optional[str] = None
    # Dołożone przez ``review_batch_order.with_order_facts``.
    facts: object = None
    # Ktoś wziął kartę („Dzwonię”, aktywna blokada): stoi w „Nowych”, ale już
    # nie czeka (lustro ``waitsInSystemQueue`` z frontu).
    taken: bool = False


async def _other_column_def_ids(db: AsyncSession) -> list[int]:
    """Etapy z enumem „new”, które Tablica pokazuje w innej kolumnie (np.
    „Wysłać do Cpro”). Karta tam nie jest porcją: „Odrzuć” dostawało 422,
    bo trasa ruchu czyta kolumnę, i taka karta zatykała początek kolejki."""
    from app.models.pipeline_template import PipelineStageDef
    from app.services.board_stage_badges import board_column_for

    rows = await db.execute(
        select(
            PipelineStageDef.id,
            PipelineStageDef.name,
            PipelineStageDef.category,
            PipelineStageDef.terminal_type,
        )
    )
    return [
        int(def_id)
        for def_id, name, category, terminal_type in rows.all()
        if board_column_for(
            name,
            "new",
            category=getattr(category, "value", category),
            terminal_type=getattr(terminal_type, "value", terminal_type),
        )
        != "new"
    ]


def _latest_stage_is_new(other_column_defs: Iterable[int] = ()):
    """Ostatni etap pary stoi w „Nowych” także na Tablicy."""
    later = CandidateStage.__table__.alias("later")
    return exists(
        select(CandidateStage.id).where(
            CandidateStage.job_id == RecruitmentProcess.job_id,
            CandidateStage.candidate_id == RecruitmentProcess.candidate_id,
            CandidateStage.stage.in_(_NEW_STAGES),
            or_(
                CandidateStage.stage_def_id.is_(None),
                CandidateStage.stage_def_id.not_in(list(other_column_defs)),
            ),
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


def in_batch(
    card: "PendingCard", now: datetime, min_score: Optional[float] = None
) -> bool:
    """Karta należy do porcji: od progu (``BatchSettings.min_score``) i nie
    starsza niż ``MAX_AGE_DAYS``. Starsze i słabsze karty zostają na Tablicy,
    ale nikogo nie blokują i nie zajmują miejsca w porcji."""
    if card.score < (MIN_SCORE if min_score is None else min_score):
        return False
    if card.opened_at is None:
        return False
    opened = card.opened_at
    if opened.tzinfo is None:
        opened = opened.replace(tzinfo=timezone.utc)
    return opened >= now - timedelta(days=MAX_AGE_DAYS)


def batch_cards(
    cards: Iterable["PendingCard"], now: datetime, min_score: Optional[float] = None
) -> list["PendingCard"]:
    return [card for card in cards if in_batch(card, now, min_score)]


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
        RecruitmentProcess.claimed_by_user_id,
        RecruitmentProcess.claimed_until,
    ).where(
        RecruitmentProcess.entry_source == candidate_claim.ENTRY_SYSTEM,
        RecruitmentProcess.voided_at.is_(None),
        _latest_stage_is_new(await _other_column_def_ids(db)),
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
    moment = _now()
    for pid, job_id, candidate_id, meta, opened_at, claimed_by, claimed_until in rows:
        card = PendingCard(
            process_id=int(pid),
            job_id=int(job_id),
            candidate_id=int(candidate_id),
            owner_id=_owner(meta),
            score=_score(meta),
            opened_at=opened_at,
            cautions=tuple((meta or {}).get("cautions") or ()),
            missing_must=tuple((meta or {}).get("missing_must") or ()),
            availability_status=(meta or {}).get("availability_status"),
            rate_from_hourly=(meta or {}).get("rate_from_hourly"),
            rate_currency=(meta or {}).get("rate_currency"),
            taken=bool((meta or {}).get("decided_at"))
            or (
                claimed_by is not None
                and (claimed_until is None or claimed_until > moment)
            ),
        )
        key = (card.job_id, card.candidate_id)
        prev = by_pair.get(key)
        if prev is None or (
            card.opened_at or datetime.min.replace(tzinfo=timezone.utc)
        ) > (prev.opened_at or datetime.min.replace(tzinfo=timezone.utc)):
            by_pair[key] = card
    return list(by_pair.values())


async def absent_today(db: AsyncSession, user_ids: Iterable[int]) -> set[int]:
    """Kto ma dziś zatwierdzoną nieobecność (urlop, L4). Tych kont porcja nie
    dotyczy, a ich karty nie stoją przez cały urlop."""
    from app.services.hr.absence import absences_on

    return set(await absences_on(db, user_ids, business_today()))


async def recruiter_ids_for_jobs(
    db: AsyncSession, job_ids: Iterable[int]
) -> dict[int, list[int]]:
    """Aktywni rekruterzy rekrutacji (reguła ``job_team``), bez propozycji
    automatu, bez kont innych ról (DL dopisany do zespołu porcji nie dostaje)
    i bez osób nieobecnych dziś: ich karty przechodzą na resztę zespołu (P11)."""
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
    allowed -= await absent_today(db, allowed)
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
    rank: Optional[dict[int, int]] = None,
) -> dict[int, int]:
    """Kto dostaje którą kartę: proces → właściciel.

    Karty z właścicielem spoza zespołu wracają do podziału. Nowe idą od
    najlepszej do osoby z najmniejszą liczbą kart w tej rekrutacji; remis
    rozstrzyga losowa (stała w ciągu dnia) kolejność zespołu. ``only`` =
    wszystkie nowe karty do jednej osoby („Dodaj 20 kolejnych”). ``rank`` =
    miejsce karty w kolejce Tablicy (proces → miejsce)."""
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
    last = len(cards) + 1
    for card in sorted(
        free,
        key=lambda c: ((rank or {}).get(c.process_id, last), -c.score, c.candidate_id),
    ):
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
    min_score = (await read_settings(db)).min_score
    cards = batch_cards(await pending_cards(db, job_ids=[job_id]), now, min_score)
    rank = None
    if team and any(card.owner_id not in team for card in cards):
        ordered = await _board_order(db, job_id, cards, now=now)
        rank = {card.process_id: i for i, card in enumerate(ordered)}
    plan = plan_owners(
        cards,
        team,
        seed=f"{job_id}:{business_today().isoformat()}",
        only=only,
        rank=rank,
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


async def _board_order(
    db: AsyncSession, job_id: int, cards: list[PendingCard], *, now: datetime
) -> list[PendingCard]:
    """Karty w kolejności kolumny „Nowi” z faktami do plakietek."""
    from app.services import review_batch_order

    job = await db.get(Job, job_id)
    if job is None:
        return sorted(cards, key=lambda c: (-c.score, c.candidate_id))
    return review_batch_order.order_cards(
        await review_batch_order.with_order_facts(db, job, cards, now=now)
    )


async def _own_cards(
    db: AsyncSession, user_id: int, *, now: datetime
) -> list[PendingCard]:
    """Karty osoby, tylko z rekrutacji, w których nadal jest rekruterem —
    osoba zdjęta z zespołu w ciągu dnia nie jest blokowana cudzą porcją."""
    from app.models.job import JobStatus
    from app.services.request_work_state import IN_WORK_STATES

    min_score = (await read_settings(db)).min_score
    cards = batch_cards(await pending_cards(db, owner_id=user_id), now, min_score)
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


@dataclass(frozen=True)
class Decision:
    """Wyjście karty od systemu z „Nowych”. ``counted_at`` = kiedy liczy się do
    minimum; ``None`` = „Do screeningu” jeszcze niedomknięte. ``own_batch`` =
    karta należała do porcji tej osoby (właściciel i ``in_batch``)."""

    process_id: int
    job_id: int
    candidate_id: int
    user_id: int
    stage: str
    moved_at: datetime
    counted_at: Optional[datetime]
    own_batch: bool


@dataclass(frozen=True)
class DayCounts:
    done: int = 0
    # Dzisiejsze „Do screeningu” bez domknięcia z własnej porcji: nie zmniejszają
    # wymaganego minimum. Starsze i cudze karty nikogo nie blokują.
    open_today: int = 0
    open_cards: tuple[Decision, ...] = ()
    # Wszystkie niedomknięte w oknie ``SCREENING_CLOSE_DAYS`` (do licznika na ekranie).
    open_screenings: int = 0
    screened_today: int = 0
    rejected_today: int = 0
    counted_times: tuple[datetime, ...] = ()


def _value(stage: object) -> str:
    return str(getattr(stage, "value", stage))


def close_window_start(before: Optional[date] = None) -> datetime:
    """Początek okna domknięcia: dziś (albo ``before``) minus
    ``SCREENING_CLOSE_DAYS`` dni roboczych."""
    tz = settings.BUSINESS_TZ
    day = before or business_today()
    left = SCREENING_CLOSE_DAYS
    while left:
        day -= timedelta(days=1)
        if is_business_day(datetime.combine(day, time(12), tzinfo=ZoneInfo(tz)), tz):
            left -= 1
    return local_day_start_utc(day, tz)


def counted_at_for(
    stage: str,
    moved_at: datetime,
    later: list[tuple[str, datetime]],
    answered: list[datetime],
) -> Optional[datetime]:
    """Kiedy wyjście z „Nowych” liczy się do minimum.

    Odrzucenie i każdy ruch dalej niż screening od razu. Samo „Do screeningu”
    dopiero po kolejnym ruchu (poza „Nowych”) albo zapisanym screeningu, bo
    bez tego wciśnięcie S przez kilka minut odblokowywało wyszukiwanie (P5)."""
    if stage != "screening":
        return moved_at
    moves = [at for name, at in later if name not in (*_NEW_STAGES, "screening")]
    # Screening zapisany jeszcze w „Nowych” też się liczy: formularz nie wymaga
    # przesunięcia karty.
    closed = sorted([*moves, *answered])
    return max(closed[0], moved_at) if closed else None


async def _decisions(
    db: AsyncSession,
    user_ids: Iterable[int],
    *,
    now: datetime,
    since: Optional[datetime] = None,
) -> dict[int, list[Decision]]:
    """Wyjścia z „Nowych” w oknie domknięcia, per osoba. Ruch karty już po
    „Nowych” (screening → CV) to nie decyzja o propozycji, tak samo karta, która
    do „Nowych” wróciła (P6)."""
    ids = sorted({int(u) for u in user_ids})
    out: dict[int, list[Decision]] = {uid: [] for uid in ids}
    if not ids:
        return out
    since = since or close_window_start()
    min_score = (await read_settings(db)).min_score
    earlier = aliased(CandidateStage)
    previous_stage = (
        select(earlier.stage)
        .where(
            earlier.job_id == CandidateStage.job_id,
            earlier.candidate_id == CandidateStage.candidate_id,
            or_(
                earlier.moved_at < CandidateStage.moved_at,
                and_(
                    earlier.moved_at == CandidateStage.moved_at,
                    earlier.id < CandidateStage.id,
                ),
            ),
        )
        .order_by(earlier.moved_at.desc(), earlier.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    rows = (
        await db.execute(
            select(
                RecruitmentProcess.id,
                RecruitmentProcess.job_id,
                RecruitmentProcess.candidate_id,
                CandidateStage.id,
                CandidateStage.stage,
                CandidateStage.moved_at,
                CandidateStage.moved_by,
                RecruitmentProcess.entry_meta,
                RecruitmentProcess.opened_at,
            )
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
                CandidateStage.moved_by.in_(ids),
                CandidateStage.moved_at >= since,
                CandidateStage.moved_at >= RecruitmentProcess.opened_at,
                CandidateStage.stage.not_in(_NEW_STAGES),
                previous_stage.in_(_NEW_STAGES),
            )
        )
    ).all()
    if not rows:
        return out
    # Ponowne wyjście z „Nowych” zastępuje poprzednie: jedna karta, jedna decyzja.
    exits: dict[int, tuple] = {}
    for row in rows:
        prev = exits.get(row[0])
        if prev is None or (row[5], row[3]) > (prev[5], prev[3]):
            exits[row[0]] = row
    job_ids = {row[1] for row in exits.values()}
    candidate_ids = {row[2] for row in exits.values()}
    stage_rows = (
        await db.execute(
            select(
                CandidateStage.job_id,
                CandidateStage.candidate_id,
                CandidateStage.id,
                CandidateStage.stage,
                CandidateStage.moved_at,
            )
            .where(
                CandidateStage.job_id.in_(job_ids),
                CandidateStage.candidate_id.in_(candidate_ids),
            )
            .order_by(CandidateStage.moved_at, CandidateStage.id)
        )
    ).all()
    by_pair: dict[tuple[int, int], list] = {}
    pair_of_stage: dict[int, tuple[int, int]] = {}
    for job_id, candidate_id, stage_id, stage, moved_at in stage_rows:
        by_pair.setdefault((job_id, candidate_id), []).append(
            (stage_id, _value(stage), moved_at)
        )
        pair_of_stage[stage_id] = (job_id, candidate_id)
    # Notatka screeningu to ``Activity screening_answered`` (tabela
    # ``screening_notes`` od dawna stoi pusta, formularz pisze tu i na etap).
    answered_rows = (
        await db.execute(
            select(Activity.entity_id, Activity.created_at).where(
                Activity.entity_type == "candidate_stage",
                Activity.entity_id.in_(list(pair_of_stage)),
                Activity.action == "screening_answered",
                Activity.created_at >= since,
            )
        )
    ).all()
    answered: dict[tuple[int, int], list[datetime]] = {}
    for entity_id, created_at in answered_rows:
        answered.setdefault(pair_of_stage[entity_id], []).append(created_at)
    for (
        process_id,
        job_id,
        candidate_id,
        stage_id,
        stage,
        moved_at,
        user,
        meta,
        opened_at,
    ) in exits.values():
        pair = by_pair.get((job_id, candidate_id), [])
        if pair and pair[-1][1] in _NEW_STAGES:
            continue  # karta wróciła do „Nowych” — decyzji nie ma
        later = [
            (name, at) for sid, name, at in pair if (at, sid) > (moved_at, stage_id)
        ]
        name = _value(stage)
        out[int(user)].append(
            Decision(
                process_id=int(process_id),
                job_id=int(job_id),
                candidate_id=int(candidate_id),
                user_id=int(user),
                stage=name,
                moved_at=moved_at,
                counted_at=counted_at_for(
                    name, moved_at, later, answered.get((job_id, candidate_id), [])
                ),
                own_batch=_owner(meta) == int(user)
                and in_batch(
                    PendingCard(
                        process_id=int(process_id),
                        job_id=int(job_id),
                        candidate_id=int(candidate_id),
                        owner_id=int(user),
                        score=_score(meta),
                        opened_at=opened_at,
                    ),
                    moved_at,
                    min_score,
                ),
            )
        )
    return out


def summarize_day(decisions: Iterable[Decision], since: datetime) -> DayCounts:
    done = sorted(
        d.counted_at for d in decisions if d.counted_at and d.counted_at >= since
    )
    items = list(decisions)
    waiting = [d for d in items if d.stage == "screening" and d.counted_at is None]
    open_cards = tuple(d for d in waiting if d.moved_at >= since and d.own_batch)
    return DayCounts(
        done=len(done),
        open_today=len(open_cards),
        open_cards=open_cards,
        open_screenings=len(waiting),
        screened_today=sum(
            1 for d in items if d.stage == "screening" and d.moved_at >= since
        ),
        rejected_today=sum(
            1 for d in items if d.stage == "rejected" and d.moved_at >= since
        ),
        counted_times=tuple(done),
    )


async def day_counts(db: AsyncSession, user_id: int, *, now: datetime) -> DayCounts:
    decisions = await _decisions(db, [user_id], now=now)
    return summarize_day(decisions.get(user_id, []), day_start(now))


async def decided_today(db: AsyncSession, user_id: int, *, now: datetime) -> int:
    """Ile decyzji o kartach od systemu liczy się dziś do minimum tej osoby."""
    return (await day_counts(db, user_id, now=now)).done


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
class OpenScreening:
    """Dzisiejsze niedomknięte S z porcji, które trzyma minimum."""

    job_id: int
    job_title: str
    candidate_id: int
    name: str


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
    # Czy niezrobione minimum teraz blokuje wyszukiwanie (wyłącznik, pilot,
    # dzień roboczy od 7:00) — licznik w pasku zostaje zachętą także bez blokady.
    blocks: bool = False
    # „Do screeningu” z ostatnich dni roboczych, jeszcze bez wyniku.
    open_screenings: int = 0
    # Rekrutacje w pracy, w których osoba jest rekruterem (z czekającymi u niej
    # osobami albo bez) — lista do „Dodaj 20 kolejnych”.
    team_jobs: tuple[JobShare, ...] = ()
    # Przy niezrobionym minimum: co domknąć na Tablicy, gdy kolejka jest pusta.
    open_today_screenings: tuple[OpenScreening, ...] = ()

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


def can_edit_settings(user: User) -> bool:
    """Ustawienia porcji zmienia admin i Head of Recruitment (``HeadOfRecruitmentPlus``)."""
    has_role = getattr(user, "has_role", None)
    if callable(has_role):
        return has_role(UserRole.admin) or has_role(UserRole.head_of_recruitment)
    return getattr(user, "role", None) in (UserRole.admin, UserRole.head_of_recruitment)


async def batch_recruiters(db: AsyncSession) -> list[dict]:
    """Aktywne konta, które dostają porcję — do wyboru pilota."""
    users = (await db.scalars(select(User).where(User.is_active.is_(True)))).all()
    return sorted(
        (
            {"id": u.id, "name": (u.name or u.email or str(u.id))}
            for u in users
            if applies_to(u)
        ),
        key=lambda row: row["name"].lower(),
    )


def _priority_rank(job: Job, now: datetime) -> int:
    from app.services import job_p0

    if job_p0.is_active(job, now):
        return 0
    return _PRIORITY_RANK.get(job.priority, 3)


async def _open_screenings(
    db: AsyncSession, decisions: Iterable[Decision]
) -> list[OpenScreening]:
    from app.models.candidate import Candidate

    items = sorted(decisions, key=lambda d: (d.moved_at, d.process_id))
    if not items:
        return []
    titles = dict(
        (
            await db.execute(
                select(Job.id, Job.title).where(Job.id.in_({d.job_id for d in items}))
            )
        ).all()
    )
    people = {
        row.id: f"{row.name} {row.lastname}".strip()
        for row in (
            await db.execute(
                select(Candidate.id, Candidate.name, Candidate.lastname).where(
                    Candidate.id.in_({d.candidate_id for d in items})
                )
            )
        ).all()
    }
    return [
        OpenScreening(
            job_id=d.job_id,
            job_title=titles.get(d.job_id) or "",
            candidate_id=d.candidate_id,
            name=people.get(d.candidate_id, ""),
        )
        for d in items
    ]


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
    if await absent_today(db, [user.id]):
        return BatchStatus(
            enabled=True,
            applies=False,
            minimum=settings_value.minimum,
            done_today=0,
            pending=0,
            required=0,
            met=True,
        )
    minimum = review_batch_levels.level_of(
        await review_batch_levels.read_levels(db), user.id, settings_value.minimum
    )
    cards = await _own_cards(db, user.id, now=now)
    day = await day_counts(db, user.id, now=now)
    done = day.done
    # Kto ma w porcji mniej, niż brakuje do minimum, przegląda całą porcję.
    # Dzisiejsze niedomknięte S z własnej porcji zostają w rachunku: inaczej
    # przesunięcie całej porcji na screening zerowałoby wymagane minimum.
    required = min(minimum, done + len(cards) + day.open_today)
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
        minimum=minimum,
        done_today=done,
        pending=len(cards),
        required=required,
        met=met,
        jobs=tuple(jobs),
        blocks=not met and blocking_now(settings_value, user.id, now),
        open_screenings=day.open_screenings,
        team_jobs=tuple(await _team_jobs(db, user.id, counts, now=now)),
        open_today_screenings=(
            () if met else tuple(await _open_screenings(db, day.open_cards))
        ),
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


def _now() -> datetime:
    return datetime.now(timezone.utc)


def blocking_now(value: BatchSettings, user_id: int, now: datetime) -> bool:
    """Blokada działa w dni robocze od ``BLOCK_START_HOUR`` (porcja rusza o 7:00),
    przy włączonym wyłączniku HoR i dla osoby z pilota (pusty = wszyscy)."""
    if not value.blocks(user_id):
        return False
    if not is_business_day(now, settings.BUSINESS_TZ):
        return False
    local = now.astimezone(ZoneInfo(settings.BUSINESS_TZ))
    return local.hour >= BLOCK_START_HOUR


async def _record_block(user_id: int, status: BatchStatus, *, now: datetime) -> None:
    """Ślad blokady dla HoR (raz na ``BLOCK_LOG_EVERY``). Własna sesja, bo sesja
    żądania cofa się po 423, a awaria zapisu nie może zmienić odpowiedzi."""
    from app.core.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            recent = await db.scalar(
                select(Activity.id)
                .where(
                    Activity.entity_type == BLOCK_ENTITY,
                    Activity.entity_id == user_id,
                    Activity.action == BLOCK_ACTION,
                    Activity.created_at >= now - BLOCK_LOG_EVERY,
                )
                .limit(1)
            )
            if recent is not None:
                return
            db.add(
                Activity(
                    entity_type=BLOCK_ENTITY,
                    entity_id=user_id,
                    action=BLOCK_ACTION,
                    user_id=user_id,
                    details={
                        "remaining": status.remaining,
                        "required": status.required,
                    },
                )
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001 — ślad nie może zmienić odpowiedzi 423
        logger.warning("[review_batch] block log failed: %s", type(exc).__name__)


async def assert_search_allowed(db: AsyncSession, user: User) -> None:
    """423 ``REVIEW_MINIMUM_PENDING``, dopóki rekruter nie zrobi minimum."""
    if not enabled() or not applies_to(user):
        return
    now = _now()
    if not blocking_now(await read_settings(db), user.id, now):
        return
    status = await status_for(db, user, now=now)
    if status.met:
        return
    await _record_block(user.id, status, now=now)
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
    priorytet), w każdej w kolejności kolumny „Nowi” na Tablicy (P7)."""
    cards = await _own_cards(db, user.id, now=now)
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
    for job_id, items in by_job.items():
        mine = {card.process_id for card in items}
        # Cała kolumna, nie tylko moje karty: miejsca „co 5.” liczą się od góry.
        column = await pending_cards(db, job_ids=[job_id])
        by_job[job_id] = [
            card
            for card in await _board_order(db, job_id, column, now=now)
            if card.process_id in mine
        ]
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
# Filtry własnej pracy: przechodzą przy blokadzie, gdy wskazują zalogowaną osobę
# (P9). „Moi kandydaci” to przegląd swojej pracy, nie przeszukiwanie bazy.
_OWN_WORK_PERSON_PARAMS = frozenset(
    {"added_by_user_id", "stage_moved_by", "contacted_by"}
)
# Zawężenia, które mają sens tylko razem z filtrem własnej pracy: same dalej
# przeszukują całą bazę (np. wszyscy odrzuceni przez nas).
_OWN_WORK_QUALIFIERS = frozenset(
    {
        "stage_moved_after",
        "stage_moved_before",
        "stage_current_only",
        "stage_column",
        "stage_category",
        "pipeline_stage",
        "contacted",
        "contacted_from",
        "contacted_to",
        "rejection_by",
        "rejection_key",
        "rejection_within_months",
        "sent_to_client_from",
        "sent_to_client_to",
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


async def _is_own_work(db: AsyncSession, own: dict[str, list[str]], user: User) -> bool:
    """Wszystkie filtry wskazują tę osobę albo rekrutacje z jej zespołu."""
    for key, values in own.items():
        if key != "recruitment_id" and values != [str(user.id)] * len(values):
            return False
    raw_jobs = own.get("recruitment_id")
    if not raw_jobs:
        return True
    try:
        job_ids = {int(value) for value in raw_jobs}
    except ValueError:
        return False
    teams = await recruiter_ids_for_jobs(db, job_ids)
    return all(user.id in teams.get(job_id, []) for job_id in job_ids)


async def is_broad_list_query(db, params, user: Optional[User] = None) -> bool:
    """Filtry albo opis w ``q`` = ręczne wyszukiwanie; samo nazwisko, mail
    albo telefon (wybór osoby, ⌘K, telefon od kandydata) i filtry własnej pracy
    zalogowanej osoby — nie."""
    items = params.multi_items() if hasattr(params, "multi_items") else params.items()
    own: dict[str, list[str]] = {}
    qualified = False
    for key, value in items:
        if value in (None, ""):
            continue
        if key == "text_mode":
            if str(value).lower() == "semantic":
                return True
            continue
        if key in _NEUTRAL_LIST_PARAMS or key.startswith("include_"):
            continue
        if user is not None:
            # ``contacted_by`` zawęża dopiero przy ``contacted=yes``: bez tego
            # nie filtruje nikogo, a przy ``no`` to wszyscy poza moimi.
            if key == "contacted_by" and params.get("contacted") != "yes":
                return True
            if key in _OWN_WORK_PERSON_PARAMS or key == "recruitment_id":
                own.setdefault(key, []).append(str(value))
                continue
            if key in _OWN_WORK_QUALIFIERS:
                qualified = True
                continue
            if key == "recruitment_match" and value == "assigned":
                continue
        return True
    if qualified and not own:
        return True
    if own and not await _is_own_work(db, own, user):
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
    if not await is_broad_list_query(db, params, user):
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
    now = _now()
    min_score = (await read_settings(db)).min_score
    cards = batch_cards(await pending_cards(db, job_ids=[job_id]), now, min_score)
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
    # Dzisiejsze niedomknięte S trzyma wymagane minimum: usunięcie karty po
    # klawiszu S zerowałoby je tak samo jak usunięcie z „Nowych”.
    since = day_start(now)
    decisions = (await _decisions(db, [user.id], now=now)).get(user.id, [])
    if any(
        d.job_id == job_id
        and d.candidate_id == candidate_id
        and d.counted_at is None
        and d.moved_at >= since
        for d in decisions
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": REMOVAL_CODE,
                "message": (
                    "To osoba z porcji dnia, którą dziś przesunięto do screeningu. "
                    "Wpisz wynik albo odrzuć z powodem — usunięcie z rekrutacji "
                    "nie jest decyzją."
                ),
            },
        )
