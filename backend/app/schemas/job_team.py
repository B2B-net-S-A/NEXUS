"""Osoba w roli „Rekruter” — jeden kształt dla listy, pulpitu i panelu rekrutacji."""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


class JobRecruiterOut(BaseModel):
    user_id: int
    name: str
    role: Literal["recruiter"]  # jedna rola pracy od 0411
    # Skąd osoba jest przy rekrutacji: prowadzący (``jobs.recruiter_id``),
    # przypisanie z pulpitu/automatu albo ręcznie dopisany współpracownik.
    via: Literal["owner", "assignment", "collaborator"]
    # Propozycja automatu czekająca na akceptację — to jeszcze nie praca.
    proposed: bool = False
    # Kto przypisał (akceptacja propozycji, dodanie z pulpitu); brak = nie wiadomo.
    assigned_by_name: Optional[str] = None


class JobPreviousRecruiterOut(BaseModel):
    """„Poprzedni rekruter” (14.10.2026): pracował, aż rekrutacja zeszła z P1
    albo została zamknięta. Wraca przy P1 (``will_return``) — chyba że konto
    jest nieaktywne albo bez roli rekrutera."""

    user_id: int
    name: str
    via: Literal["owner", "assignment", "collaborator"]
    reason: Literal["closed", "priority"]
    parked_at: datetime
    parked_by_name: Optional[str] = None
    will_return: bool = True
