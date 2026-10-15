"""Router AI w edytorze CV — `/api/pipeline/stages/{stage_id}/cv-ai/…` (Edytor CV 2, PR 3).

„AI na zaznaczeniu”: rekruter zaznacza fragment CV dla klienta i prosi o jego
skrócenie, rozwinięcie z oryginału, redakcję, korektę albo tłumaczenie. Trasa
zwraca PROPOZYCJĘ i niczego nie zapisuje w szkicu CV — przyjętą propozycję
nakłada edytor, a utrwala ją zwykły autozapis. Klient wysyła tekst (fragment,
jego akapit, opis roli), nigdy HTML ani pozycji w dokumencie.

„Polecenie dla całego CV” (PR 4): rekruter pisze, co zmienić, a trasa zwraca
PLAN — operacje na wierszach, które przeszły kontrolę. Też bez zapisu.

Edytor CV 3, PR 4 (asystent w kolumnie): ta sama trasa przyjmuje kilka
ostatnich wiadomości rozmowy i wiersze zaznaczone w edytorze, a operacja
z faktem spoza CV wraca z pytaniem (`ask`). „Tak, dopisz” zapisuje fakt jako
notatkę pary (`…/cv-ai/confirm-fact`), zanim edytor nałoży zmianę.

Te same bramki co poprawki QC: kto może ruszać kartą w pipeline
(`RecruiterPlus` + członkostwo w rekrutacji). Każde wywołanie to płatny model,
więc tokeny integracji dostają 403. Logika i kontrola „bez nowych faktów”:
`app/services/cv_selection_ai.py`.

Bez ``from __future__ import annotations`` — slowapi #579 (PEP 563 zamienia
guardy `Annotated` w parametry QUERY).
"""

from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, StringConstraints, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RecruiterPlus
from app.api.recruitment_access import ensure_job_membership
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.core.rate_limit import limiter, user_or_ip_key
from app.models.recruitment_pipeline import CandidateStage
from app.services import cv_command_ai, cv_selection_ai
from app.services.candidate_claim import is_integration_request

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)

_Point = Annotated[str, StringConstraints(max_length=400)]
# Propozycja bywa dłuższa niż fragment (rozwinięcie, tłumaczenie) — limit jak dla odpowiedzi.
_Previous = Annotated[str, StringConstraints(max_length=cv_selection_ai.PROPOSED_MAX)]


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


# ── Polecenie własnymi słowami dla całego CV (PR 4) ──────────────────────────

# Łączna długość tekstu CV w żądaniu: trzy–cztery strony to kilkanaście tysięcy
# znaków; limit trzyma koszt jednego wywołania modelu w ryzach.
COMMAND_TEXT_TOTAL_MAX = 60_000


class CommandLine(BaseModel):
    """Wiersz CV: blok dokumentu albo punkt listy, w kolejności dokumentu."""

    id: int = Field(ge=0, le=10_000)
    kind: Literal[
        "title",
        "heading",
        "role",
        "employer",
        "label",
        "technologies",
        "bullet",
        "text",
    ]
    # Pogrubienie jako `**tekst**`.
    text: str = Field(default="", max_length=cv_command_ai.LINE_TEXT_MAX)
    section: Optional[str] = Field(default=None, max_length=40)
    # Numer stanowiska w CV (od zera), gdy wiersz do niego należy.
    role: Optional[int] = Field(default=None, ge=0, le=200)


class CommandMessage(BaseModel):
    """Wcześniejsza wiadomość rozmowy z asystentem (kontekst, nie polecenie)."""

    role: Literal["user", "assistant"]
    text: str = Field(default="", max_length=cv_command_ai.HISTORY_TEXT_MAX)


class CommandRequest(BaseModel):
    preset: Optional[
        Literal[
            "shorten",
            "drop_old_roles",
            "order_by_requirements",
            "unify_sentences",
            "more_requirements",
            "proofread",
        ]
    ] = None
    command: Optional[str] = Field(default=None, max_length=cv_command_ai.COMMAND_MAX)
    lines: list[CommandLine] = Field(min_length=1, max_length=cv_command_ai.LINES_MAX)
    # Asystent (Edytor CV 3, PR 4): rozmowa i zaznaczenie w edytorze.
    history: list[CommandMessage] = Field(
        default_factory=list, max_length=cv_command_ai.HISTORY_MAX
    )
    focus: list[Annotated[int, Field(ge=0, le=10_000)]] = Field(
        default_factory=list, max_length=cv_command_ai.FOCUS_MAX
    )

    @model_validator(mode="after")
    def _command_and_lines(self) -> "CommandRequest":
        if self.preset is None and len((self.command or "").strip()) < 3:
            raise ValueError("Napisz, co asystent ma zmienić w CV.")
        if len({line.id for line in self.lines}) != len(self.lines):
            raise ValueError("Wiersze CV mają powtórzone numery.")
        if sum(len(line.text) for line in self.lines) > COMMAND_TEXT_TOTAL_MAX:
            raise ValueError("To CV jest za długie na polecenie dla całego dokumentu.")
        return self


class CommandOperation(BaseModel):
    id: int
    type: Literal[
        "remove",
        "replace",
        "merge",
        "reorder",
        "remove_role",
        "remove_section",
        "add",
        "bold",
        "unbold",
        "considered_for",
    ]
    # Wiersze, których dotyczy operacja (dla `reorder` — w nowej kolejności).
    lines: list[int]
    # Nowa treść (`replace`, `merge`); `**tekst**` = pogrubienie.
    text: Optional[str] = None
    why: str = ""
    # Wymagania rekrutacji, które po tej operacji znikają z CV.
    loses: list[str] = []
    # Słowa nowej treści, których nie było w zastępowanych wierszach — kontrola
    # faktów ich nie ocenia, więc edytor pokazuje je przy zmianie.
    new_words: list[str] = []
    # Pytanie przed nałożeniem: `source` — fakt spoza CV i źródeł (`problem`),
    # `loses` — znika jedyne miejsce z wymaganiem klienta.
    ask: Optional[Literal["source", "loses"]] = None
    problem: Optional[str] = None
    # `bold` / `unbold`: terminy, które stoją w CV.
    terms: list[str] = []


class CommandDropped(BaseModel):
    type: Optional[str] = None
    reason: str
    problem: Optional[str] = None


class CommandResponse(BaseModel):
    """`ok` = plan z co najmniej jedną operacją; pozostałe statusy niosą `message`."""

    status: Literal["ok", "empty", "unavailable"]
    operations: list[CommandOperation] = []
    # Operacje modelu, które nie przeszły kontroli — do zdania „N zmian odrzuconych”.
    dropped: list[CommandDropped] = []
    message: Optional[str] = None
    # Model zaproponował więcej niż `OPERATIONS_MAX` zmian — reszta nie weszła.
    truncated: bool = False


@router.post("/stages/{stage_id}/cv-ai/command", response_model=CommandResponse)
@limiter.limit("6/minute", key_func=user_or_ip_key)
async def propose_plan_for_command(
    request: Request,
    stage_id: int,
    payload: CommandRequest,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> CommandResponse:
    """Plan zmian dla całego CV z polecenia rekrutera. Nigdy 5xx z powodu modelu.

    Wynik biznesowy zawsze wraca jako 200 ze statusem: plan (`ok`), brak zmian
    albo wszystkie odrzucone przez kontrolę (`empty`), chwilowa niedostępność
    modelu (`unavailable`). Trasa niczego nie zapisuje w szkicu CV.
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
    result = await cv_command_ai.propose_plan(
        db,
        stage,
        user_id=current_user.id,
        payload=payload.model_dump(exclude_none=True),
    )
    await db.commit()
    return CommandResponse(**result)


class ConfirmFactRequest(BaseModel):
    # Fakt, o który pytał asystent („Terraform”), i zmiana, którą rekruter przyjmuje.
    term: str = Field(min_length=1, max_length=cv_command_ai.CONFIRM_TERM_MAX)
    text: str = Field(default="", max_length=cv_command_ai.LINE_TEXT_MAX)


@router.post("/stages/{stage_id}/cv-ai/confirm-fact", status_code=204)
@limiter.limit("20/minute", key_func=user_or_ip_key)
async def confirm_fact_from_conversation(
    request: Request,
    stage_id: int,
    payload: ConfirmFactRequest,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """„Tak, dopisz”: fakt z rozmowy z kandydatem jako notatka pary (autor, data).

    Zmianę w CV nakłada edytor po tej odpowiedzi — notatka jest źródłem, na
    którym fakt się opiera, także dla QC i kolejnych generacji.
    """
    if is_integration_request(request):
        raise HTTPException(
            status_code=403,
            detail="Fakt z rozmowy z kandydatem potwierdza osoba, nie integracja.",
        )
    stage = await db.get(CandidateStage, stage_id)
    if stage is None:
        raise HTTPException(status_code=404, detail="Nie ma takiego etapu kandydata.")
    await ensure_job_membership(db, current_user, stage.job_id)
    try:
        await cv_command_ai.confirm_fact(
            db,
            stage,
            user_id=current_user.id,
            term=payload.term,
            text=payload.text,
        )
    except cv_command_ai.ConfirmRefused as refusal:
        detail = (
            "Kwot i stawek nie dopisujemy do CV dla klienta."
            if str(refusal) == "amount"
            else "Napisz, co kandydat potwierdził."
        )
        raise HTTPException(status_code=422, detail=detail) from refusal
    await db.commit()
    return Response(status_code=204)
