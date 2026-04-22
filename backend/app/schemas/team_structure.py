"""Pydantic schemas for team structure endpoints.

Endpointy `/api/team-structure/*` — macierze zespołu rekrutacji:
  - sourcer × kategoria kompetencji (1st/2nd priority)
  - TAC → DL
  - TAC → LinkedIn farming kategorie
  - DL → klienci (Head vs Regular)
"""

from typing import Optional

from pydantic import BaseModel, Field


# ── Shared ────────────────────────────────────────────────────────────────


class UserBrief(BaseModel):
    id: int
    name: str
    email: Optional[str] = None


class CategoryBrief(BaseModel):
    id: int
    slug: str
    name_pl: str
    name_en: str


class ClientBrief(BaseModel):
    id: int
    name: str


# ── Sourcer × Category ────────────────────────────────────────────────────


class SourcerInCategory(BaseModel):
    user_id: int
    name: str
    email: Optional[str] = None
    priority: Optional[int] = Field(None, description="1 = 1st, 2 = 2nd, None = brak")
    is_primary: bool = False


class SourcerCategoryRow(BaseModel):
    category: CategoryBrief
    first_priority: list[SourcerInCategory]
    second_priority: list[SourcerInCategory]


class AssignSourcerPayload(BaseModel):
    user_id: int
    competence_category_id: int
    priority: int = Field(ge=1, le=2, description="1 lub 2")


# ── TAC → DL ──────────────────────────────────────────────────────────────


class TacOfDl(BaseModel):
    user_id: int
    name: str
    email: Optional[str] = None
    linkedin_farming: list[CategoryBrief] = []


class DlWithTacsRow(BaseModel):
    delivery_lead: UserBrief
    tacs: list[TacOfDl]


class AssignTacToDlPayload(BaseModel):
    tac_user_id: int
    delivery_lead_user_id: int


# ── TAC LinkedIn Farming ──────────────────────────────────────────────────


class AssignTacLinkedInFarmingPayload(BaseModel):
    tac_user_id: int
    competence_category_id: int


# ── DL → Clients ──────────────────────────────────────────────────────────


class ClientOfDl(BaseModel):
    id: int
    name: str
    is_head: bool


class DlClientsRow(BaseModel):
    delivery_lead: UserBrief
    clients: list[ClientOfDl]


class AssignDlClientPayload(BaseModel):
    delivery_lead_user_id: int
    client_id: int
    is_head: bool = False


# ── Summary ───────────────────────────────────────────────────────────────


class TeamStructureSummary(BaseModel):
    """Kompletny snapshot macierzy — używany przez panel Head of Recruitment."""

    categories: list[SourcerCategoryRow]
    delivery_leads: list[DlWithTacsRow]
    dl_clients: list[DlClientsRow]
    totals: dict = Field(
        default_factory=dict,
        description="Liczby: sourcers, tacs, recruiters, delivery_leads, clients",
    )
