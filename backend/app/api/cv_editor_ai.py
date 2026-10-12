"""Router AI w edytorze CV — `/api/pipeline/stages/{stage_id}/cv-ai/…` (Edytor CV 2, PR 3).

„AI na zaznaczeniu”: rekruter zaznacza fragment CV dla klienta i prosi o jego
skrócenie, rozwinięcie z oryginału, redakcję, korektę albo tłumaczenie. Trasa
zwraca PROPOZYCJĘ i niczego nie zapisuje w szkicu CV — przyjętą propozycję
nakłada edytor, a utrwala ją zwykły autozapis. Klient wysyła tekst (fragment,
jego akapit, opis roli), nigdy HTML ani pozycji w dokumencie.

Te same bramki co poprawki QC: kto może ruszać kartą w pipeline
(`RecruiterPlus` + członkostwo w rekrutacji). Każde wywołanie to płatny model,
więc tokeny integracji dostają 403. Logika i kontrola „bez nowych faktów”:
`app/services/cv_selection_ai.py`.

Bez ``from __future__ import annotations`` — slowapi #579 (PEP 563 zamienia
guardy `Annotated` w parametry QUERY).
"""

from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, StringConstraints, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RecruiterPlus
from app.api.recruitment_access import ensure_job_membership
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.core.rate_limit import limiter, user_or_ip_key
from app.models.recruitment_pipeline import CandidateStage
from app.services import cv_selection_ai
from app.services.candidate_claim import is_integration_request

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)

_Point = Annotated[str, StringConstraints(max_length=400)]
_Previous = Annotated[str, StringConstraints(max_length=cv_selection_ai.FRAGMENT_MAX)]


class SelectionRole(BaseModel):
    """Stanowisko w CV, w którym stoi fragment — tak, jak widzi je rekruter."""

    title: str = Field(default="", max_length=200)
    employer: str = Field(default="", max_length=200)
    points: list[_Point] = Field(default_factory=list, max_length=12)


class SelectionRequest(BaseModel):
    action: Literal["shorten", "expand", "rephrase", "proofread", "translate"]
    # Zaznaczony tekst; pogrubienie jako `**tekst**`.
    fragment: str = Field(min_length=3, max_length=cv_selection_ai.FRAGMENT_MAX)
    # Akapit albo punkt, w którym stoi zaznaczenie (kontekst dla modelu).
    block_text: str = Field(min_length=3, max_length=cv_selection_ai.BLOCK_MAX)
    block_kind: Literal["li", "p"] = "p"
    section: Optional[
        Literal[
            "experience",
            "why_points",
            "education",
            "skills",
            "certifications",
            "languages",
        ]
    ] = None
    role: Optional[SelectionRole] = None
    # „Doprecyzuj”: wskazówka do stylu — nie jest źródłem faktów.
    instruction: Optional[str] = Field(
        default=None, max_length=cv_selection_ai.INSTRUCTION_MAX
    )
    # „Jeszcze raz”: propozycje już pokazane, żeby model dał inną.
    previous: list[_Previous] = Field(
        default_factory=list, max_length=cv_selection_ai.PREVIOUS_MAX
    )

    @model_validator(mode="after")
    def _fragment_inside_block(self) -> "SelectionRequest":
        def flat(text: str) -> str:
            return " ".join(text.replace("**", "").split())

        if flat(self.fragment) not in flat(self.block_text):
            raise ValueError("Zaznaczony fragment nie należy do podanego akapitu.")
        return self


class SelectionSource(BaseModel):
    kind: Literal["original", "notes"]
    quote: str


class SelectionResponse(BaseModel):
    """`ok` = propozycja; pozostałe statusy niosą `message` dla rekrutera."""

    status: Literal["ok", "rejected", "no_source", "not_supported", "unavailable"]
    action: str
    # `**tekst**` = pogrubienie; edytor zamienia je na znaczniki, nie na HTML.
    proposed_text: Optional[str] = None
    # Rozwinięcie oparte na cytacie, który serwer znalazł w źródle.
    verified: bool = False
    sources: list[SelectionSource] = []
    cautions: list[str] = []
    reason: Optional[str] = None
    problem: Optional[str] = None
    message: Optional[str] = None


@router.post("/stages/{stage_id}/cv-ai/selection", response_model=SelectionResponse)
@limiter.limit("20/minute", key_func=user_or_ip_key)
async def propose_for_selection(
    request: Request,
    stage_id: int,
    payload: SelectionRequest,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> SelectionResponse:
    """Propozycja AI dla zaznaczonego fragmentu CV. Nigdy 5xx z powodu modelu.

    Wynik biznesowy zawsze wraca jako 200 ze statusem: propozycja (`ok`),
    odmowa kontroli „bez nowych faktów” (`rejected` z powodem), brak źródeł do
    rozwinięcia (`no_source`), klauzula zgody (`not_supported`) albo chwilowa
    niedostępność modelu (`unavailable`).
    """

    if is_integration_request(request):
        raise HTTPException(
            status_code=403,
            detail="Podpowiedzi AI w edytorze CV zamawia osoba, nie integracja.",
        )
    stage = await db.get(CandidateStage, stage_id)
    if stage is None:
        raise HTTPException(status_code=404, detail="Nie ma takiego etapu kandydata.")
    await ensure_job_membership(db, current_user, stage.job_id)
    result = await cv_selection_ai.propose(
        db,
        stage,
        user_id=current_user.id,
        payload=payload.model_dump(exclude_none=True),
    )
    await db.commit()
    return SelectionResponse(**result)
