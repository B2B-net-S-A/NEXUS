"""Blokada 12 h osoby w kolumnach „Nowi" i „Screening" (Pipeline v4, decyzja
Artura 23.09.2026; Screening od 24.09.2026).

Osoba, którą rekruter sam dodał do rekrutacji (albo wziął z propozycji
przyciskiem „Biorę"), jest przez ``CLAIM_HOURS`` na jego wyłączność W TEJ
rekrutacji. Chodzi o chaos: dwóch rekruterów dzwoniących do tej samej osoby
w sprawie tej samej rekrutacji. Po upływie blokady każdy z zespołu może osobę
przejąć; wcześniej — wyłącznie admin, Delivery Lead albo Head of Recruitment.

Blokada dotyczy tylko kolumn „Nowi" i „Screening" (rozmowa i pytania
z Championa — od 24.09.2026 Screening jest osobną kolumną, a rozmowa trwa
w nim dalej). Ruch na „Zweryfikowany" i dalej ją zdejmuje — wtedy osoba ma już
właściciela procesu.

Stan żyje na ``RecruitmentProcess`` (``claimed_by_user_id`` + ``claimed_until``,
CHECK: oba albo żadne). Wygaśnięcie jest liczone przy odczycie — bez pętli.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline_template import PipelineStageDef
from app.models.recruitment_pipeline import CandidateStage
from app.models.recruitment_process import RecruitmentProcess
from app.models.user import User, UserRole
from app.services.board_stage_badges import CLAIM_COLUMNS as _CLAIM_COLUMNS
from app.services.board_stage_badges import NEW_COLUMN as _NEW_COLUMN
from app.services.board_stage_badges import board_column_for

CLAIM_HOURS = 12
NEW_COLUMN = _NEW_COLUMN
# Kolumny Tablicy, w których obowiązuje blokada.
CLAIM_COLUMNS = _CLAIM_COLUMNS

# Kto może przejąć cudzą osobę przed upływem blokady.
CLAIM_OVERRIDE_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.delivery_lead,
    UserRole.head_of_recruitment,
)

# Źródła wejścia do rekrutacji (CHECK w 0352).
ENTRY_ADDED_MANUAL = "added_manual"
ENTRY_APPLICATION = "application"
ENTRY_PROPOSAL = "proposal"
ENTRY_REASSIGN = "reassign"
ENTRY_AUTO_MATCH = "auto_match"
ENTRY_IMPORT = "import"
ENTRY_SOURCES = frozenset(
    {
        ENTRY_ADDED_MANUAL,
        ENTRY_APPLICATION,
        ENTRY_PROPOSAL,
        ENTRY_REASSIGN,
        ENTRY_AUTO_MATCH,
        ENTRY_IMPORT,
    }
)

_WARSAW = ZoneInfo("Europe/Warsaw")


@dataclass(frozen=True)
class ClaimState:
    user_id: Optional[int]
    until: Optional[datetime]

    def active(self, now: datetime) -> bool:
        return self.user_id is not None and self.until is not None and self.until > now


def is_integration_request(request: object) -> bool:
    """Czy żądanie przyszło od integracji (token klienta OAuth, np. scraper
    pracuj.pl / JJIT), a nie od człowieka.

    Integracja dodaje kandydatów sama — to wejście z automatu, bez 12 h
    blokady na koncie integracji (decyzja 23.09.2026: blokada należy się
    wyłącznie człowiekowi, który dodał osobę ręcznie).
    """
    state = getattr(request, "state", None)
    return bool(getattr(state, "oauth_client_id", None))


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def claim_state(
    process: Optional[RecruitmentProcess],
    inactive_user_ids: frozenset[int] | set[int] = frozenset(),
) -> ClaimState:
    """Blokada procesu. Blokada konta nieaktywnego = brak blokady (runda 8,
    R8-N8-7): nieaktywne konto nie prowadzi nikogo, więc nie wiąże zespołu."""

    if process is None or process.claimed_by_user_id in inactive_user_ids:
        return ClaimState(None, None)
    return ClaimState(process.claimed_by_user_id, process.claimed_until)


async def inactive_holders(
    db: AsyncSession, processes: Iterable[Optional[RecruitmentProcess]]
) -> set[int]:
    """Id nieaktywnych kont trzymających blokady tych procesów — jedno zapytanie."""

    ids = {
        p.claimed_by_user_id
        for p in processes
        if p is not None and p.claimed_by_user_id is not None
    }
    if not ids:
        return set()
    return set(
        (
            await db.execute(
                select(User.id).where(User.id.in_(ids), User.is_active.is_(False))
            )
        )
        .scalars()
        .all()
    )


def can_override(user: User) -> bool:
    return user.has_any_role(*CLAIM_OVERRIDE_ROLES)


def set_claim(
    process: RecruitmentProcess, user_id: int, now: Optional[datetime] = None
) -> None:
    process.claimed_by_user_id = user_id
    process.claimed_until = (now or utcnow()) + timedelta(hours=CLAIM_HOURS)


def clear_claim(process: RecruitmentProcess) -> None:
    process.claimed_by_user_id = None
    process.claimed_until = None


async def stage_column(db: AsyncSession, stage: CandidateStage) -> str:
    """Kolumna Tablicy wiersza etapu (ta sama reguła co front)."""

    name: Optional[str] = None
    category: Optional[str] = None
    terminal_type: Optional[str] = None
    if stage.stage_def_id is not None:
        row = (
            await db.execute(
                select(
                    PipelineStageDef.name,
                    PipelineStageDef.category,
                    PipelineStageDef.terminal_type,
                ).where(PipelineStageDef.id == stage.stage_def_id)
            )
        ).first()
        if row is not None:
            name = row.name
            category = getattr(row.category, "value", row.category)
            terminal_type = getattr(row.terminal_type, "value", row.terminal_type)
    stage_value = getattr(stage.stage, "value", stage.stage)
    return board_column_for(
        name, stage_value, category=category, terminal_type=terminal_type
    )


async def load_process(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> Optional[RecruitmentProcess]:
    """Najnowsza próba pary (bez blokady wiersza — tylko odczyt blokady)."""

    return await db.scalar(
        select(RecruitmentProcess)
        .where(
            RecruitmentProcess.candidate_id == candidate_id,
            RecruitmentProcess.job_id == job_id,
        )
        .order_by(RecruitmentProcess.attempt_no.desc(), RecruitmentProcess.id.desc())
        .limit(1)
    )


def _holder_label(holder: Optional[User]) -> str:
    if holder is None:
        return "inną osobę"
    return (holder.name or "").strip() or holder.email or "inną osobę"


def _local_hhmm(moment: datetime) -> str:
    return moment.astimezone(_WARSAW).strftime("%d.%m %H:%M")


async def assert_can_act(
    db: AsyncSession,
    *,
    process: Optional[RecruitmentProcess],
    user: User,
    now: Optional[datetime] = None,
) -> None:
    """Odmawia 423, gdy osoba jest zarezerwowana przez kogoś innego.

    Admin, Delivery Lead i Head of Recruitment przechodzą zawsze — to oni
    rozstrzygają spory o osobę.
    """

    moment = now or utcnow()
    state = claim_state(process, await inactive_holders(db, [process]))
    if not state.active(moment) or state.user_id == user.id or can_override(user):
        return
    # Blokada dotyczy wyłącznie „Nowych" i „Screeningu". Import z Traffita i synchronizacja
    # procesów przesuwają osobę bez `transition_process`, więc blokada może
    # przeżyć wyjście z kolumny — wtedy nie wiąże nikogo (przegląd 23.09.2026).
    latest = await db.scalar(
        select(CandidateStage)
        .where(
            CandidateStage.candidate_id == process.candidate_id,
            CandidateStage.job_id == process.job_id,
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        .limit(1)
    )
    if latest is None or await stage_column(db, latest) not in CLAIM_COLUMNS:
        return
    holder = await db.get(User, state.user_id)
    raise HTTPException(
        status_code=423,
        detail={
            "code": "CANDIDATE_CLAIMED",
            "message": (
                f"Tę osobę prowadzi {_holder_label(holder)} do "
                f"{_local_hhmm(state.until)}. Po tym czasie każdy może ją przejąć."
            ),
            "claimed_by_user_id": state.user_id,
            "claimed_until": state.until.isoformat(),
        },
    )


def can_take(
    process: Optional[RecruitmentProcess],
    user: User,
    now: datetime,
    inactive_user_ids: frozenset[int] | set[int] = frozenset(),
) -> bool:
    """Czy ``user`` może kliknąć „Biorę"/„Przejmij" na tej karcie."""

    state = claim_state(process, inactive_user_ids)
    if state.user_id == user.id and state.active(now):
        return False
    return not state.active(now) or can_override(user)
