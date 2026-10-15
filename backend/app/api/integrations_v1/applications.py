"""Zgłoszenia z linku rekrutacji w API v1: odczyt i rozpatrzenie.

Scope ``applications:read`` (lista, szczegóły; plik CV dodatkowo z
``candidates:cv``) i ``applications:write`` (rozpatrzenie). Zgłoszenie to zapis
tego, co osoba wysłała formularzem kariery albo starym ``/apply/{token}``,
gdy jej e-mail był już w bazie. Od 22.09.2026 takie zgłoszenie jest podpinane
od razu (``linked``); ``pending_review`` mają tylko wiersze sprzed tej daty.
Nowa osoba ze zgłoszenia jest od razu kandydatem (``/candidates``, Tablica)
— tu jej nie ma. Projekcje: ``services/integration_application_reads``.

Rozpatrzenie (``POST …/resolve``) idzie tym samym ciałem co ekran
(``application_submissions.resolve_application_submission``) z autorem
``WriteAuthor.service_account`` (kandydat bez ``created_by``, ``Activity`` bez
osoby, ``details.via`` ze stempla klucza, bez ``UserActivity``). Klucz
dostaje te same akcje co rekruter (``link``, ``merge``, ``create``,
``reject``) i reguły węższe niż ekran:

* „ta sama osoba = ten sam e-mail”: ``link``/``merge`` tylko do kandydata
  z adresem ze zgłoszenia (409 ``not_same_person``), ``create`` nie zakłada
  drugiego profilu z tym adresem (409 ``duplicate_candidate`` z
  ``candidate_id``) — ekran w tej sytuacji zakłada profil bez e-maila;
* adres osoby usuniętej na jej żądanie (RODO) nie wraca przez ``create``
  (409 ``candidate_erased``, jak ``POST /candidates``);
* ``reject`` wymaga powodu — trafia do historii zamiast osoby, która odrzuca.

Moduł NIE MOŻE mieć ``from __future__ import annotations`` (slowapi #579).
"""

from datetime import date, datetime
from typing import Annotated, Any, Literal, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
)
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import application_submissions as screen
from app.api.deps import Caller, require_service_scope
from app.api.integrations_v1.candidate_writes import _assert_not_erased
from app.api.integrations_v1.common import (
    INT4_MAX,
    AmountLevel,
    ApplicationsRead,
    ApplicationsWrite,
    IdPath,
    IntegrationRoute,
    Money,
    Page,
    PageQuery,
    PageSizeQuery,
    amount_level,
    dry_run_response,
    idempotent_write,
    integration_actor,
    page_of,
    principal_rate_key,
    read_rate_limit,
    reads_candidate_cv,
    sees_candidate_contact,
    write_rate_limit,
)
from app.core.database import get_db
from app.core.http_headers import content_disposition
from app.core.rate_limit import limiter
from app.models.application_submission import (
    ApplicationSubmission,
    ApplicationSubmissionStatus,
)
from app.models.recruitment_pipeline import CandidateStage
from app.models.service_account import ServiceScope
from app.services import candidate_audit
from app.services import integration_application_reads as reads
from app.services.dedup_service import find_candidate_by_email
from app.services.write_author import WriteAuthor

router = APIRouter(route_class=IntegrationRoute)

_NOT_FOUND = "Zgłoszenie nie istnieje."

#: Plik CV zgłoszenia: oba scope'y naraz (komplet, jak każda bramka v1).
ApplicationsCv = Annotated[
    Caller,
    Depends(
        require_service_scope(
            ServiceScope.applications_read,
            ServiceScope.candidates_cv,
            allow_admin_jwt=False,
        )
    ),
]

StatusFilter = Literal["pending_review", "linked", "merged", "created", "rejected"]


# ── Wyjście ──────────────────────────────────────────────────────────────────


class ScreeningReasonOut(BaseModel):
    text: str
    quote: Optional[str] = Field(
        description="Cytat z CV — tylko z ``candidates:cv``, inaczej null."
    )


class AiScreeningOut(BaseModel):
    """Ocena zgłoszenia przez AI przed „Nowi” (podpowiedź, nie decyzja)."""

    status: str
    verdict: Optional[str] = Field(description="fits · unclear · not_fit")
    outcome: str = Field(
        description="pending · added · screened_out · blocked · job_closed · "
        "already_in_job · failed"
    )
    must_found: Optional[int]
    must_total: Optional[int]
    reasons: list[ScreeningReasonOut]
    decided_at: Optional[datetime]
    overridden_at: Optional[datetime]


class ApplicationOut(BaseModel):
    id: int
    status: str = Field(
        description="pending_review · linked · merged · created · rejected"
    )
    job_id: Optional[int] = Field(description="null = stały link rekrutera.")
    job_title: Optional[str]
    submitted_at: datetime
    reviewed_at: Optional[datetime]
    matched_candidate_id: Optional[int] = Field(
        description="Kandydat z tym samym e-mailem w chwili zgłoszenia."
    )
    contact_redacted: bool
    first_name: Optional[str]
    last_name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    linkedin: Optional[str]
    has_cv: bool
    ai_screening: Optional[AiScreeningOut]
    updated_at: datetime


class ApplicationAnswersOut(BaseModel):
    message: Optional[str] = Field(
        description="Wiadomość z formularza — tylko z ``candidates:contact``."
    )
    message_redacted: bool
    city: Optional[str]
    availability_date: Optional[date]
    work_mode: Optional[str]
    costs_redacted: bool
    expected_rate_hourly: Money = Field(
        description="Oczekiwana stawka PLN/h z formularza — tylko z ``amounts:read``."
    )
    link_kind: Optional[str] = Field(description="job · recruiter")
    via: Optional[str] = Field(description="career (strona kariery) · invite_link")
    utm_source: Optional[str]


class ApplicationDetailOut(ApplicationOut):
    answers: ApplicationAnswersOut
    cv_file_name: Optional[str] = Field(
        description="Nazwa pliku CV — tylko z ``candidates:cv``."
    )
    cv_mime_type: Optional[str]
    cv_size_bytes: Optional[int]


class ResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["link", "merge", "create", "reject"] = Field(
        description="link — CV do profilu kandydata bez zmiany pól; merge — CV "
        "i puste pola kontaktu + wiadomość; create — nowy kandydat; reject — "
        "odrzucenie bez zmian w kandydatach."
    )
    candidate_id: Optional[int] = Field(
        None,
        ge=1,
        le=INT4_MAX,
        description="Dla link/merge: kandydat z tym samym e-mailem co zgłoszenie "
        "(domyślnie dopasowany przy zgłoszeniu).",
    )
    reason: Optional[str] = Field(
        None, max_length=500, description="Wymagany przy reject — trafia do historii."
    )

    @model_validator(mode="after")
    def _fields_for_action(self) -> "ResolveIn":
        if self.candidate_id is not None and self.action not in ("link", "merge"):
            raise ValueError("candidate_id podaje się tylko przy link i merge.")
        reason = (self.reason or "").strip()
        if self.action == "reject" and not reason:
            raise ValueError("Podaj powód odrzucenia (reason).")
        if reason and self.action != "reject":
            raise ValueError("reason podaje się tylko przy reject.")
        self.reason = reason or None
        return self


class ResolveOut(BaseModel):
    id: int
    status: str
    candidate_id: Optional[int] = Field(
        description="Kandydat, którego dotyczy rozpatrzenie (null przy reject; "
        "w próbie także przy create)."
    )
    added_to_recruitment: bool = Field(
        description="Osoba weszła do „Nowi” rekrutacji zgłoszenia."
    )


# ── Odczyt ───────────────────────────────────────────────────────────────────


@router.get(
    "/applications",
    response_model=Page[ApplicationOut],
    summary="Zgłoszenia z linku rekrutacji",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def list_applications(
    request: Request,
    caller: ApplicationsRead,
    db: AsyncSession = Depends(get_db),
    page: PageQuery = 1,
    page_size: PageSizeQuery = 100,
    job_id: Optional[int] = Query(None, ge=1, le=INT4_MAX),
    status: Optional[list[StatusFilter]] = Query(
        None, description="Powtarzalny; brak = wszystkie."
    ),
    updated_since: Optional[datetime] = Query(
        None,
        description="Zgłoszenie, rozpatrzenie albo ocena AI od tej chwili; "
        "bez strefy = UTC.",
    ),
) -> dict:
    """Zgłoszenia całej firmy rosnąco po id, z oceną AI. Imię i kontakt
    z formularza tylko z ``candidates:contact``; pliku CV na liście nie ma."""
    filters = reads.ApplicationFilters(
        job_id=job_id, statuses=tuple(status or ()), updated_since=updated_since
    )
    rows, total = await reads.list_page(db, filters, page=page, page_size=page_size)
    screenings = await reads.screenings_for(db, [row[0].id for row in rows])
    contact = sees_candidate_contact(caller)
    cv = reads_candidate_cv(caller)
    items = [
        reads.item_out(
            submission,
            job_title,
            screenings.get(submission.id),
            contact=contact,
            cv=cv,
        )
        for submission, job_title in rows
    ]
    return page_of(items, page=page, page_size=page_size, total=total)


@router.get(
    "/applications/{application_id}",
    response_model=ApplicationDetailOut,
    summary="Zgłoszenie",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def get_application(
    request: Request,
    application_id: IdPath,
    caller: ApplicationsRead,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Pola listy, odpowiedzi z formularza i opis pliku CV. Oczekiwana stawka
    tylko z ``amounts:read``, nazwa pliku z ``candidates:cv``."""
    row = await reads.load_visible(db, application_id)
    if row is None:
        raise HTTPException(404, detail=_NOT_FOUND)
    submission, job_title = row
    screening = (await reads.screenings_for(db, [submission.id])).get(submission.id)
    cv = reads_candidate_cv(caller)
    return {
        **reads.item_out(
            submission,
            job_title,
            screening,
            contact=sees_candidate_contact(caller),
            cv=cv,
        ),
        "answers": reads.answers_out(
            submission,
            show_costs=amount_level(caller) is AmountLevel.all,
            show_contact=sees_candidate_contact(caller),
        ),
        **reads.cv_fields(submission, visible=cv),
    }


@router.get(
    "/applications/{application_id}/cv",
    summary="Plik CV zgłoszenia",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def download_application_cv(
    request: Request,
    application_id: IdPath,
    _caller: ApplicationsCv,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Bajty CV ze zgłoszenia (zawsze ``attachment``); wymaga
    ``applications:read`` i ``candidates:cv``. Każde pobranie zostawia ślad
    ``document_downloaded`` w dzienniku kandydata, jak pobranie pliku na
    ekranie."""
    row = await reads.load_visible(db, application_id, with_cv_bytes=True)
    if row is None:
        raise HTTPException(404, detail=_NOT_FOUND)
    submission = row[0]
    content = await screen._load_submission_cv_bytes(submission)
    if not submission.cv_filename or not content:
        raise HTTPException(404, detail="Zgłoszenie nie ma pliku CV.")
    # Ślad dopiero przy oddanych bajtach; bez osoby — ``details.via`` dopisuje
    # sesja klucza. Zgłoszenie bez kandydata = wpis modułowy (``entity_id=0``).
    candidate_audit.record_candidate_audit(
        db,
        action=candidate_audit.DOCUMENT_DOWNLOADED,
        user_id=None,
        entity_id=submission.matched_candidate_id or 0,
        details={
            "submission_id": submission.id,
            "source": "application_submission",
            "disposition": "attachment",
        },
    )
    await db.commit()
    return Response(
        content=content,
        media_type=submission.cv_content_type or "application/octet-stream",
        headers={
            "Content-Disposition": content_disposition(
                submission.cv_filename, "attachment"
            ),
            "Content-Length": str(len(content)),
        },
    )


# ── Rozpatrzenie ─────────────────────────────────────────────────────────────


def _conflict(code: str, message: str, **details: Any) -> HTTPException:
    return HTTPException(409, detail={"error": code, "message": message, **details})


async def _same_email_candidate_ids(
    db: AsyncSession, submission: ApplicationSubmission
) -> list[int]:
    rows = await find_candidate_by_email(db, submission.submitted_email)
    return [row["candidate_id"] for row in rows]


async def _link_target(
    db: AsyncSession, submission: ApplicationSubmission, candidate_id: Optional[int]
) -> int:
    """Kandydat dla ``link``/``merge``: ten z e-mailem zgłoszenia — nikt inny."""
    target = candidate_id or submission.matched_candidate_id
    same_email = await _same_email_candidate_ids(db, submission)
    if target is None:
        raise _conflict(
            "no_matching_candidate",
            "Zgłoszenie nie ma kandydata z tym adresem e-mail — użyj create.",
        )
    if target not in same_email:
        raise _conflict(
            "not_same_person",
            "Kandydat ma inny adres e-mail niż zgłoszenie (ta sama osoba = ten "
            "sam e-mail).",
            candidate_id=same_email[0] if same_email else None,
        )
    return target


async def _assert_new_email(
    db: AsyncSession, submission: ApplicationSubmission
) -> None:
    same_email = await _same_email_candidate_ids(db, submission)
    if same_email:
        raise _conflict(
            "duplicate_candidate",
            "Kandydat z tym adresem e-mail już istnieje (ta sama osoba = ten sam "
            "e-mail) — dołącz zgłoszenie akcją link.",
            candidate_id=same_email[0],
        )


async def _opens_process(
    db: AsyncSession, submission: ApplicationSubmission, candidate_id: Optional[int]
) -> bool:
    """Czy rozpatrzenie otworzy kartę „Nowi” — a gdy bramka (czarna lista,
    weto hiring managera) na to nie pozwala, 409 ``blocked`` z powodem."""
    if submission.job_id is None:
        return False
    if candidate_id is None:
        # Nowy kandydat: nie ma jeszcze ani karty, ani weta, ani czarnej listy.
        return True
    in_job = await db.scalar(
        select(CandidateStage.id).where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == submission.job_id,
        )
    )
    if in_job is not None:
        return False
    reason = await screen.submission_block_reason(
        db, job_id=submission.job_id, candidate_id=candidate_id
    )
    if reason is not None:
        raise _conflict("blocked", reason)
    return True


@router.post(
    "/applications/{application_id}/resolve",
    response_model=ResolveOut,
    summary="Rozpatrz zgłoszenie",
)
@limiter.limit(write_rate_limit, key_func=principal_rate_key)
async def resolve_application(
    request: Request,
    application_id: IdPath,
    body: ResolveIn,
    caller: ApplicationsWrite,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    dry_run: bool = Query(
        False, description="Tylko sprawdzenie reguł i wynik, bez zapisu."
    ),
) -> Response:
    """Jak „Zgłoszenia” na ekranie: link (CV do profilu), merge (CV i puste
    pola kontaktu), create (nowy kandydat), reject (z powodem). Rekrutacja
    zgłoszenia dostaje osobę w „Nowi”, chyba że już tam jest; czarna lista
    i weto hiring managera → 409 ``blocked``. Zgłoszenie rozpatrzone wcześniej
    → 409 ``already_resolved``; inny e-mail niż w zgłoszeniu → 409
    ``not_same_person``; create przy istniejącym e-mailu → 409
    ``duplicate_candidate``; adres osoby usuniętej (RODO) → 409
    ``candidate_erased``."""
    author = WriteAuthor.service_account(integration_actor(caller))
    resolutions: list[screen.SubmissionResolution] = []

    async def run():
        row = await reads.load_visible(db, application_id)
        if row is None:
            raise HTTPException(404, detail=_NOT_FOUND)
        submission = row[0]
        if submission.status != ApplicationSubmissionStatus.pending_review.value:
            raise _conflict(
                "already_resolved",
                "Zgłoszenie jest już rozpatrzone.",
                status=submission.status,
            )
        candidate_id: Optional[int] = None
        if body.action in ("link", "merge"):
            candidate_id = await _link_target(db, submission, body.candidate_id)
        elif body.action == "create":
            await _assert_new_email(db, submission)
            await _assert_not_erased(db, submission.submitted_email)
        opens = body.action != "reject" and await _opens_process(
            db, submission, candidate_id
        )
        if dry_run:
            return 200, {
                "id": submission.id,
                "status": _resolved_status(body.action),
                "candidate_id": candidate_id,
                "added_to_recruitment": opens,
            }

        async def still_visible(locked: ApplicationSubmission) -> None:
            # Pod blokadą wiersza: klient rekrutacji mógł zostać ukryty.
            if await reads.load_visible(db, locked.id) is None:
                raise HTTPException(404, detail=_NOT_FOUND)

        resolution = await screen.resolve_application_submission(
            db,
            application_id,
            body.action,
            author=author,
            authorize=still_visible,
            candidate_id=candidate_id,
            reason=body.reason,
        )
        resolutions.append(resolution)
        return 200, {
            "id": resolution.submission.id,
            "status": resolution.submission.status,
            "candidate_id": resolution.candidate_id,
            "added_to_recruitment": resolution.opened_stage is not None,
        }

    if dry_run:
        return await dry_run_response(db, run)
    response = await idempotent_write(
        request,
        db,
        caller,
        payload={"application_id": application_id, **body.model_dump(mode="json")},
        run=run,
    )
    # Po commicie, jak na ekranie: odczyt AI głównego CV nowego kandydata.
    # Powtórka z paragonu nie wywołuje ``run``, więc nie czyta CV drugi raz.
    for resolution in resolutions:
        screen.schedule_primary_cv_read(background_tasks, resolution)
    return response


def _resolved_status(action: str) -> str:
    return {
        "link": ApplicationSubmissionStatus.linked.value,
        "merge": ApplicationSubmissionStatus.merged.value,
        "create": ApplicationSubmissionStatus.created.value,
        "reject": ApplicationSubmissionStatus.rejected.value,
    }[action]
