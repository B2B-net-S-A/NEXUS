"""Osoba w roli „Rekruter” — jeden kształt dla listy, pulpitu i panelu rekrutacji."""

from typing import Literal, Optional

from pydantic import BaseModel


class JobRecruiterOut(BaseModel):
    user_id: int
    name: str
    role: Literal["recruiter", "sourcer"]
    # Skąd osoba jest przy rekrutacji: prowadzący (``jobs.recruiter_id``),
    # przypisanie z pulpitu/automatu albo ręcznie dopisany współpracownik.
    via: Literal["owner", "assignment", "collaborator"]
    # Propozycja automatu czekająca na akceptację — to jeszcze nie praca.
    proposed: bool = False
    # Kto przypisał (akceptacja propozycji, dodanie z pulpitu); brak = nie wiadomo.
    assigned_by_name: Optional[str] = None
