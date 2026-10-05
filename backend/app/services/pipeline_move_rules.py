"""Reguły ruchu Pipeline v4/v5 (decyzje Artura 23.09.2026).

Dwa wyjątki od „kanbanu bez bramek" (17.09.2026), oba świadome:

* **„CV wysłane" poza Nordeą wysyła Delivery Lead i wpisuje stawkę do
  klienta.** O tym, kto wysyła, decyduje uprawnienie „Rekrutacje:
  zakładanie, zamykanie, wysyłka CV do klienta” (``recruitment_manage``;
  domyślnie Delivery Lead i admin). Stawka, za którą osobę wysłano, jest
  potrzebna później do umowy i zamówienia — a do 23.09 była opcjonalna
  i zwykle pusta. Nordea
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
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline_template import PipelineStageDef
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services.action_permissions import ProductAction
from app.services.board_stage_badges import (
    BOARD_COLUMN_ORDER,
    board_column_for,
    cpro_enabled_for_client,
)
from app.services.permission_denial import ensure_permission

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
) -> tuple[Optional[CandidateStage], str]:
    """Wiersz etapu pary i jego kolumna, względem których liczą się bramki ruchu.

    Zwykle to najnowszy wiersz pary. Gdy para stoi w „Zamkniętych"
    (odrzucony, wycofany, rezerwa), bramki (QC CV, Cpro, debrief) liczą się
    względem OSTATNIEJ kolumny sprzed zamknięcia — inaczej droga „Nowi →
    Odrzucony → CV wysłane" albo „Rozmowa u klienta → Odrzucony → Umowa"
    omijała każdą z nich (audyt 25.09.2026). Para bez żadnego wiersza spoza
    „Zamkniętych" zaczyna drogę od początku („new", jak ``_index`` w
    ``move_requirements``). Para BEZ wierszy też stoi na początku drogi:
    ``(None, "new")`` — do rundy 2 audytu (25.09.2026) wracało ``(None, None)``
    i świeży kandydat wysłany przez API wprost na „CV wysłane"/Cpro omijał
    QC i osobę od Cpro.

    Kolumny liczy jedno zapytanie o definicje etapów pary, nie zapytanie na
    wiersz — para z długą historią importu z Traffita ma dziesiątki wierszy.
    Reguła ta sama co ``candidate_claim.stage_column``.
    """
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
        return None, "new"
    def_ids = {r.stage_def_id for r in rows if r.stage_def_id is not None}
    defs: dict[int, tuple] = {}
    if def_ids:
        for d in (
            await db.execute(
                select(
                    PipelineStageDef.id,
                    PipelineStageDef.name,
                    PipelineStageDef.category,
                    PipelineStageDef.terminal_type,
                ).where(PipelineStageDef.id.in_(def_ids))
            )
        ).all():
            defs[d.id] = (
                d.name,
                getattr(d.category, "value", d.category),
                getattr(d.terminal_type, "value", d.terminal_type),
            )
    for row in rows:
        name, category, terminal_type = defs.get(row.stage_def_id, (None, None, None))
        column = board_column_for(
            name,
            getattr(row.stage, "value", row.stage),
            category=category,
            terminal_type=terminal_type,
        )
        if column != "closed":
            return row, column
    return rows[0], "new"


# Kolumny, z których wejście na „Zweryfikowany” jest bramkowane (D1). Zwrot
# z „QC CV” i dalszych („Wróć do poprawy”) przechodzi bez sprawdzenia.
VERIFIED_GATE_FROM_COLUMNS = frozenset({"new", "screening"})

# Kolumny docelowe objęte bramką: „Zweryfikowany” i każda dalsza — skok
# z Nowych/Screeningu ponad „Zweryfikowany” (API, Jarvis, ruch zbiorczy)
# omijał arkusz i stawkę, a para bez wiersza `verified` traciła kredyt
# weryfikacji w KPI, wyścigach i Lidze (audyt 05.10.2026). Front blokował
# taki skok od początku (`move_requirements` liczy pominięte kolumny).
VERIFIED_GATE_TARGETS = frozenset(
    BOARD_COLUMN_ORDER[BOARD_COLUMN_ORDER.index("verified") :]
)

VERIFIED_REQUIREMENT_LABELS = {
    "screening_sheet": "arkusz screeningu",
    "candidate_rate": "stawka kandydata",
}


async def assert_verified_requirements(
    db: AsyncSession,
    *,
    candidate_id: int,
    job: Any,
    user: User,
    target_column: str,
    pending_rate: bool,
) -> None:
    """409 `VERIFIED_REQUIREMENTS_MISSING` — wejście na „Zweryfikowany” bez
    arkusza screeningu albo bez stawki kandydata (decyzja Artura 04.10.2026).

    Braki liczy ``move_requirements.load_pair_facts`` — ta sama reguła co
    okno „Przesuń dalej” i ramka „Następny etap”, więc ekran i serwer nie
    mogą się rozjechać. Arkusz = zapisany arkusz pary albo odpowiedzi
    w karcie rekomendacji; stawka = profil, wcześniejszy etap pary albo ta
    w żądaniu (``pending_rate``). Para w „Zamkniętych” liczy się kolumną
    sprzed zamknięcia (``gate_stage_row``).
    """
    from app.core.config import settings  # noqa: PLC0415
    from app.models.candidate import Candidate  # noqa: PLC0415
    from app.services import move_requirements  # noqa: PLC0415

    if not settings.VERIFIED_GATE_ENABLED or target_column not in VERIFIED_GATE_TARGETS:
        return
    _row, column = await gate_stage_row(db, candidate_id=candidate_id, job_id=job.id)
    if column not in VERIFIED_GATE_FROM_COLUMNS:
        return
    candidate = await db.get(Candidate, candidate_id)
    if candidate is None:
        return
    facts = await move_requirements.load_pair_facts(
        db, candidate=candidate, job=job, user=user
    )
    missing: list[str] = []
    if not (facts.screening_done or facts.card_answers):
        missing.append("screening_sheet")
    if not (facts.candidate_rate or pending_rate):
        missing.append("candidate_rate")
    if not missing:
        return
    labels = [VERIFIED_REQUIREMENT_LABELS[key] for key in missing]
    raise HTTPException(
        status_code=409,
        detail={
            "code": "VERIFIED_REQUIREMENTS_MISSING",
            "missing": missing,
            "screening_stage_id": facts.screening_stage_id,
            "message": "Przed „Zweryfikowany” uzupełnij: " + ", ".join(labels) + ".",
        },
    )


HIRED_SIGNED_VIA = ("b2b_offline", "uop", "zlecenie", "other")


def assert_hired_signed_via(
    target: PipelineStage, signed_via: Optional[str], note: Optional[str]
) -> None:
    """Ręczny ruch na „Zatrudniony” mówi, jak podpisano umowę (D2, 04.10.2026).

    Umowa B2B z Generatora przesuwa kartę sama („Oznacz jako podpisaną”).
    Ręcznie zostają umowy spoza Generatora — wtedy człowiek wybiera rodzaj,
    a „inny” wymaga opisu.
    """
    from app.core.config import settings  # noqa: PLC0415

    if target != PipelineStage.hired or not settings.HIRED_SIGNED_VIA_REQUIRED:
        return
    if signed_via not in HIRED_SIGNED_VIA:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "HIRED_SIGNED_VIA_REQUIRED",
                "message": (
                    "Napisz, jak podpisano umowę. Umowę B2B z Generatora "
                    "potwierdź przyciskiem „Oznacz jako podpisaną” — karta "
                    "przejdzie na „Zatrudniony” sama."
                ),
            },
        )
    if signed_via == "other" and not (note or "").strip():
        raise HTTPException(
            status_code=422,
            detail={
                "code": "HIRED_SIGNED_VIA_REQUIRED",
                "message": "Przy „inna umowa” opisz, jak ją podpisano.",
            },
        )


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
    if column not in PRE_CONTRACT_COLUMNS:
        return
    missing = await missing_debrief(db, candidate_id=candidate_id, job_id=job_id)
    if missing is not None:
        raise HTTPException(status_code=409, detail=missing)


def requires_dl_client_rate(target: PipelineStage, client_id: Optional[int]) -> bool:
    """Ruch na „CV wysłane" u klienta innego niż Nordea."""

    return target == PipelineStage.cv_sent and not cpro_enabled_for_client(client_id)


async def arrives_from_before_client_send(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> bool:
    """Czy para wchodzi na „CV wysłane” z kolumny PRZED nim.

    Wymóg DL i stawki do klienta dotyczy WYSŁANIA, nie cofnięcia karty
    z „Rozmowy u klienta” czy „Umowy” — tam osoba już jest u klienta.
    Kolumna jak przy pozostałych bramkach (``gate_stage_row``: para
    w „Zamkniętych” liczy się kolumną sprzed zamknięcia, bez wierszy — „Nowi”).
    Runda 9 (R9-N11-6).
    """
    _row, column = await gate_stage_row(db, candidate_id=candidate_id, job_id=job_id)
    if column not in BOARD_COLUMN_ORDER:
        return True
    return BOARD_COLUMN_ORDER.index(column) < BOARD_COLUMN_ORDER.index("cv_sent")


def assert_client_send_allowed(user: User, rate_value: Optional[Decimal]) -> None:
    """403 z nazwą uprawnienia, gdy konto nie wysyła CV do klienta; 422 bez
    dodatniej stawki do klienta.

    Wysyłka do klienta to część uprawnienia „Rekrutacje: zakładanie,
    zamykanie, wysyłka CV do klienta” — kto go nie ma, przekazuje osobę do
    przeglądu (zostaje w „QC CV”).
    """

    ensure_permission(user, ProductAction.recruitment_manage)
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
