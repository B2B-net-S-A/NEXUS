"""Reguły ruchu Pipeline v4 (decyzje Artura 23.09.2026).

Dwa wyjątki od „kanbanu bez bramek" (17.09.2026), oba świadome:

* **„CV wysłane" poza Nordeą wysyła Delivery Lead i wpisuje stawkę do
  klienta.** Stawka, za którą osobę wysłano, jest potrzebna później do
  umowy i zamówienia — a do 23.09 była opcjonalna i zwykle pusta. Nordea
  zostaje przy swojej ścieżce DZ → Cpro (wysyła osoba wytypowana do Cpro).
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

from app.models.recruitment_pipeline import PipelineStage
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
                "(zostaje w „Zweryfikowanym”)."
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
