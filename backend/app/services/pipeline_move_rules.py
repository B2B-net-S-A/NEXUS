"""Reguły ruchu Pipeline v4/v5 (decyzje Artura 23.09.2026).

Dwa wyjątki od „kanbanu bez bramek" (17.09.2026), oba świadome:

* **„CV wysłane" poza Nordeą wysyła Delivery Lead i wpisuje stawkę do
  klienta.** Stawka, za którą osobę wysłano, jest potrzebna później do
  umowy i zamówienia — a do 23.09 była opcjonalna i zwykle pusta. Nordea
  zostaje przy swojej ścieżce QC CV → kolejka Cpro (wysyła jedna osoba od
  Cpro na firmę, `services/cpro_sender.py`). Zatwierdzenia DZ od 24.09.2026
  nie ma — przed wysłaniem liczy się QC CV (`services/cv_qc.py`).
* **Zamknięcie procesu mówi, kto je zakończył** — kandydat, my, Delivery Lead
  albo klient. Bez tego „odrzucony przez klienta" i „przez nas" wyglądały
  w statystykach tak samo.

Import z Traffita nie idzie przez ``/move``, więc żadna z tych reguł go nie
dotyczy.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services.board_stage_badges import cpro_enabled_for_client

# Kto może przenieść osobę na „CV wysłane" poza Nordeą.
CLIENT_SEND_ROLES: tuple[UserRole, ...] = (UserRole.admin, UserRole.delivery_lead)

# Kto może zapisać „Odrzucony przez DL".
DL_REJECT_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.delivery_lead,
    UserRole.head_of_recruitment,
)

ENDED_BY_CANDIDATE = "candidate"
ENDED_BY_RECRUITER = "recruiter"
ENDED_BY_DELIVERY_LEAD = "delivery_lead"
ENDED_BY_CLIENT = "client"
REJECTION_ENDED_BY = frozenset(
    {ENDED_BY_RECRUITER, ENDED_BY_DELIVERY_LEAD, ENDED_BY_CLIENT}
)


# Kolumny PRZED umową — osoba stąd wchodząca do „Umowy"/„Zatrudnionego" musi
# mieć debrief po rozmowie u klienta (jeśli rozmowa jest w kalendarzu — także
# zaplanowana, która jeszcze się nie odbyła).
PRE_CONTRACT_COLUMNS = frozenset(
    {"new", "screening", "verified", "cv_qc", "cv_sent", "client_interview"}
)


async def gate_stage_row(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> tuple[Optional[CandidateStage], Optional[str]]:
    """Wiersz etapu pary i jego kolumna, względem których liczą się bramki ruchu.

    Zwykle to najnowszy wiersz pary. Gdy para stoi w „Zamkniętych"
    (odrzucony, wycofany, rezerwa), bramki (QC CV, Cpro, debrief) liczą się
    względem OSTATNIEJ kolumny sprzed zamknięcia — inaczej droga „Nowi →
    Odrzucony → CV wysłane" albo „Rozmowa u klienta → Odrzucony → Umowa"
    omijała każdą z nich (audyt 25.09.2026). Para bez żadnego wiersza spoza
    „Zamkniętych" zaczyna drogę od początku („new", jak ``_index`` w
    ``move_requirements``). ``(None, None)`` = para nie ma jeszcze wierszy.
    """
    from app.services import candidate_claim

    rows = (
        await db.scalars(
            select(CandidateStage)
            .where(
                CandidateStage.candidate_id == candidate_id,
                CandidateStage.job_id == job_id,
            )
            .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        )
    ).all()
    if not rows:
        return None, None
    for row in rows:
        column = await candidate_claim.stage_column(db, row)
        if column != "closed":
            return row, column
    return rows[0], "new"


async def assert_debrief_before_contract(
    db: AsyncSession, *, candidate_id: int, job_id: int, target_column: str
) -> None:
    """409 `DEBRIEF_REQUIRED`, gdy osoba wchodzi do „Umowy"/„Zatrudnionego"
    bez debriefu po rozmowie u klienta — także gdy rozmowa jest dopiero
    zaplanowana (debrief będzie możliwy po niej, ``debrief_gate``).

    Liczy się bieżąca kolumna pary, nie tylko „Rozmowa u klienta" — inaczej
    okrężna droga Rozmowa → CV wysłane → Umowa omijała bramkę. Para
    w „Zamkniętych" liczy się kolumną sprzed zamknięcia (``gate_stage_row``).
    Ruchy wewnątrz „Umowy" i dalej nie są bramkowane (historia sprzed bramki).
    """
    from app.services.debrief_gate import missing_debrief

    if target_column not in ("contract", "hired"):
        return
    _row, column = await gate_stage_row(db, candidate_id=candidate_id, job_id=job_id)
    if column is None or column not in PRE_CONTRACT_COLUMNS:
        return
    missing = await missing_debrief(db, candidate_id=candidate_id, job_id=job_id)
    if missing is not None:
        raise HTTPException(status_code=409, detail=missing)


def requires_dl_client_rate(target: PipelineStage, client_id: Optional[int]) -> bool:
    """Ruch na „CV wysłane" u klienta innego niż Nordea."""

    return target == PipelineStage.cv_sent and not cpro_enabled_for_client(client_id)


def assert_client_send_allowed(user: User, rate_value: Optional[Decimal]) -> None:
    """403 dla roli spoza DL/admina, 422 bez dodatniej stawki do klienta."""

    if not user.has_any_role(*CLIENT_SEND_ROLES):
        raise HTTPException(
            status_code=403,
            detail=(
                "Do klienta wysyła Delivery Lead — przekaż osobę do przeglądu "
                "(zostaje w „QC CV”)."
            ),
        )
    if rate_value is None or Decimal(rate_value) <= 0:
        raise HTTPException(
            status_code=422,
            detail=(
                "Wpisz stawkę, za którą wysyłasz kandydata do klienta — bez niej "
                "nie przeniesiesz na „CV wysłane”."
            ),
        )


def resolve_ended_by(requested: Optional[str], *, withdrawn: bool, user: User) -> str:
    """Kto zakończył proces — wartość do zapisu na wierszu etapu.

    Rezygnacja to zawsze kandydat. Odrzucenie bez podanego „kto" (stare
    klienty API, Jarvis) = „odrzucony przez nas", jak do 23.09.
    """

    if withdrawn:
        if requested not in (None, ENDED_BY_CANDIDATE):
            raise HTTPException(
                status_code=422,
                detail="Rezygnację zapisuje się zawsze jako decyzję kandydata.",
            )
        return ENDED_BY_CANDIDATE
    value = requested or ENDED_BY_RECRUITER
    if value not in REJECTION_ENDED_BY:
        raise HTTPException(
            status_code=422,
            detail="Odrzucić może: rekruter, Delivery Lead albo klient.",
        )
    if value == ENDED_BY_DELIVERY_LEAD and not user.has_any_role(*DL_REJECT_ROLES):
        raise HTTPException(
            status_code=403,
            detail=(
                "„Odrzucony przez DL” zapisuje Delivery Lead, Head of Recruitment "
                "albo admin."
            ),
        )
    return value
