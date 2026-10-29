# UWAGA: bez `from __future__ import annotations` — `@limiter.limit` na
# module z PEP 563 zamienia ciało żądania w parametry query (slowapi #579).
"""„Karta przed CV” (Credit Agricole, 29.10.2026) — wzór klienta i karta pary.

Credit Agricole wymaga z każdym CV jednostronicowej karty dostawcy w Wordzie.
Kartę wysyła Delivery Lead z przeglądu „Przejrzyj i wyślij”; ma stawkę do
klienta, więc rekruter jej nie widzi (403).

* ``GET/PUT/DELETE /api/clients/{id}/cover-sheet-template`` — wzór w edytorze
  reguły CV klienta; te same bramki co zapis reguły (``client_cv_rules``).
  Wzór jest = karta włączona dla klienta, usunięty = wyłączona.
* ``GET /api/candidates/{cid}/recruitments/{jid}/cover-sheet`` — pola karty
  z wartościami i źródłami (``enabled: false`` u klienta bez wzoru),
* ``PUT …/cover-sheet`` — poprawki DL-a (poziom, staż, profil, dostępność,
  lokalizacja), puste = wartość wyliczona,
* ``GET …/cover-sheet/docx`` — osobny plik Word obok CV.

Stawka: z parametrów ``client_rate`` / ``client_rate_unit`` (DL wpisuje ją
właśnie w przeglądzie), bez nich — ostatnia zapisana stawka do klienta pary.
Decyzje i powody: ``docs/claude/generator-cv/karta-przed-cv-credit-agricole.md``.
"""

import hashlib
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Path,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.api.candidate_access import (
    CandidatePIIAccess,
    CandidateWriteAccess,
    client_rate_write_denied,
    resolve_client_rate_write,
    user_can_view_client_rate,
)
from app.api.client_cv_rules import (
    CLIENTS_EDIT_DEPENDENCIES,
    _client_or_404,
    _require_client_rule_access,
    _require_shared_rule_section_read,
    _writable_client_or_404,
)
from app.api.deps import OperationalUser, get_db
from app.api.recruitment_access import ensure_job_membership, ensure_job_read_access
from app.api.section_access import DeliverySectionUser
from app.core.http_headers import content_disposition
from app.core.rate_limit import limiter, user_or_ip_key
from app.core.scheduling import business_today
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.candidate_client_form import CandidateClientForm
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.client_cover_sheet_template import ClientCoverSheetTemplate
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User
from app.services import cover_sheet
from app.services.cover_sheet_schema import KIND_COVER
from app.services.stage_client_rate import latest_client_rates

router = APIRouter()

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_INT32_MAX = 2_147_483_647
DbIdPath = Annotated[int, Path(ge=1, le=_INT32_MAX)]
RateUnit = Literal["hourly", "daily", "monthly"]

# Pola, które Delivery Lead poprawia; imię, rolę i wynagrodzenie bierze NEXUS.
EDITABLE = (
    cover_sheet.LEVEL,
    cover_sheet.EXPERIENCE,
    cover_sheet.PROFILE,
    cover_sheet.AVAILABILITY,
    cover_sheet.LOCATION,
)
SOURCE_DL = "dl"
SOURCE_LABELS = {
    "profile": "z profilu",
    "job": "z rekrutacji",
    "years": "ze stażu w profilu",
    "cv": "z „Dlaczego nasz kandydat” w CV",
    "job_skills": "z wymagań rekrutacji",
    "rate_hourly": "Twoja stawka × 8 h",
    "rate_daily": "Twoja stawka",
    SOURCE_DL: "wpisane przez DL",
}

MSG_ROLE = "Karty przed CV nie widzi ta rola — ma stawkę do klienta."
MSG_NO_PAIR = "Ta osoba nie jest w tej rekrutacji."
MSG_NO_TEMPLATE = (
    "Klient tej rekrutacji nie ma wzoru karty — dodaje go Delivery Lead "
    "w regule CV klienta."
)
MSG_NO_RATE = "Wpisz stawkę do klienta — bez niej karta nie ma wynagrodzenia."
MSG_MONTHLY = (
    "Karta podaje stawkę za 1 MD — wpisz stawkę do klienta godzinową albo dzienną."
)
MSG_CURRENCY = "Karta podaje wynagrodzenie w PLN — wpisz stawkę do klienta w złotych."
MSG_UNKNOWN_FIELD = "Tego pola karty nie poprawia się ręcznie — odśwież okno."
MSG_LEVEL = "Poziom doświadczenia: wybierz Junior, Specjalista albo Expert."
MSG_NO_FILE = "Dodaj plik Word ze wzorem karty."


# ── Wzór klienta ─────────────────────────────────────────────────────────────


async def _template(
    db: AsyncSession, client_id: int, *, with_content: bool = False
) -> Optional[ClientCoverSheetTemplate]:
    query = select(ClientCoverSheetTemplate).where(
        ClientCoverSheetTemplate.client_id == client_id
    )
    if with_content:
        query = query.options(undefer(ClientCoverSheetTemplate.content))
    return await db.scalar(query)


async def _template_meta(
    db: AsyncSession, row: Optional[ClientCoverSheetTemplate]
) -> dict[str, Any]:
    if row is None:
        return {"template": None}
    by_name = (
        await db.scalar(select(User.name).where(User.id == row.uploaded_by))
        if row.uploaded_by
        else None
    )
    return {
        "template": {
            "filename": row.filename,
            "uploaded_at": row.uploaded_at,
            "uploaded_by_name": by_name,
            "fields": row.fields or [],
        }
    }


@router.get("/clients/{client_id}/cover-sheet-template")
@limiter.limit("120/minute", key_func=user_or_ip_key)
async def get_cover_sheet_template(
    request: Request,
    client_id: DbIdPath,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Czy klient ma wzór karty i co NEXUS w nim rozpoznał (bez pliku)."""
    client = await _client_or_404(db, client_id)
    _require_shared_rule_section_read(current_user)
    await _require_client_rule_access(db, current_user, client.id, write=False)
    return await _template_meta(db, await _template(db, client.id))


@router.put(
    "/clients/{client_id}/cover-sheet-template",
    dependencies=CLIENTS_EDIT_DEPENDENCIES,
)
@limiter.limit("20/minute", key_func=user_or_ip_key)
async def upload_cover_sheet_template(
    request: Request,
    client_id: DbIdPath,
    current_user: DeliverySectionUser,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
) -> dict:
    """Wgraj albo podmień wzór — od teraz karta idzie z każdym CV klienta."""
    client = await _writable_client_or_404(db, client_id)
    await _require_client_rule_access(db, current_user, client.id, write=True)
    filename = (file.filename or "").strip()[:255]
    if not filename:
        raise HTTPException(status_code=422, detail=MSG_NO_FILE)
    if not filename.lower().endswith(".docx"):
        raise HTTPException(status_code=422, detail=cover_sheet.MSG_NOT_DOCX)
    content = await file.read(cover_sheet.MAX_TEMPLATE_BYTES + 1)
    try:
        structure = cover_sheet.read_template(content)
    except cover_sheet.SheetRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    fields = structure.fields()
    row = await _template(db, client.id)
    replaced = row is not None
    if row is None:
        row = ClientCoverSheetTemplate(client_id=client.id)
        db.add(row)
    row.filename = filename
    row.content = content
    row.sha256 = hashlib.sha256(content).hexdigest()
    row.fields = fields
    row.uploaded_by = current_user.id
    row.uploaded_at = datetime.now(timezone.utc)
    db.add(
        Activity(
            entity_type="client",
            entity_id=client.id,
            action=(
                "cover_sheet_template_replaced"
                if replaced
                else "cover_sheet_template_added"
            ),
            user_id=current_user.id,
            details={
                "filename": filename,
                "fields": [item["id"] for item in fields],
            },
        )
    )
    await db.flush()
    return await _template_meta(db, row)


@router.delete(
    "/clients/{client_id}/cover-sheet-template",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=CLIENTS_EDIT_DEPENDENCIES,
)
@limiter.limit("20/minute", key_func=user_or_ip_key)
async def delete_cover_sheet_template(
    request: Request,
    client_id: DbIdPath,
    current_user: DeliverySectionUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Usuń wzór — karta przestaje być potrzebna przy CV tego klienta."""
    client = await _client_or_404(db, client_id)
    await _require_client_rule_access(db, current_user, client.id, write=True)
    row = await _template(db, client.id)
    if row is not None:
        db.add(
            Activity(
                entity_type="client",
                entity_id=client.id,
                action="cover_sheet_template_removed",
                user_id=current_user.id,
                details={"filename": row.filename},
            )
        )
        await db.delete(row)
        await db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Karta pary osoba × rekrutacja ────────────────────────────────────────────


class CoverSheetEdit(BaseModel):
    # id pola → wartość; pusta wartość = z powrotem wartość wyliczona.
    fields: dict[str, str] = Field(default_factory=dict, max_length=20)


async def _pair(
    db: AsyncSession, candidate_id: int, job_id: int, user: User, *, write: bool
) -> tuple[Job, Candidate]:
    if not user_can_view_client_rate(user):
        raise HTTPException(status_code=403, detail=MSG_ROLE)
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Rekrutacja nie istnieje.")
    if write:
        if not await resolve_client_rate_write(db, user, job):
            raise client_rate_write_denied()
        await ensure_job_membership(db, user, job.id)
    else:
        await ensure_job_read_access(db, user, job.id)
    candidate = await db.get(Candidate, candidate_id)
    in_job = await db.scalar(
        select(CandidateStage.id)
        .where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == job_id,
        )
        .limit(1)
    )
    if candidate is None or in_job is None:
        raise HTTPException(status_code=404, detail=MSG_NO_PAIR)
    return job, candidate


async def _edits(
    db: AsyncSession, candidate_id: int, job_id: int
) -> Optional[CandidateClientForm]:
    return await db.scalar(
        select(CandidateClientForm).where(
            CandidateClientForm.candidate_id == candidate_id,
            CandidateClientForm.job_id == job_id,
            CandidateClientForm.kind == KIND_COVER,
        )
    )


async def _locked_edits(
    db: AsyncSession, candidate_id: int, job_id: int
) -> CandidateClientForm:
    """Wiersz poprawek pary pod blokadą do końca transakcji.

    Dwa zapisy naraz (DL zmienia lokalizację i od razu poziom): pierwszy zapis
    pary nie kończy się błędem klucza, a drugi czeka na blokadę wiersza
    i dokłada swoje pole do zapisanych, zamiast je nadpisać.
    """
    await db.execute(
        pg_insert(CandidateClientForm)
        .values(candidate_id=candidate_id, job_id=job_id, kind=KIND_COVER)
        .on_conflict_do_nothing(index_elements=["candidate_id", "job_id", "kind"])
    )
    return await db.scalar(
        select(CandidateClientForm)
        .where(
            CandidateClientForm.candidate_id == candidate_id,
            CandidateClientForm.job_id == job_id,
            CandidateClientForm.kind == KIND_COVER,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def _company_cv_html(
    db: AsyncSession, candidate_id: int, job_id: int
) -> Optional[str]:
    return await db.scalar(
        select(CandidateStageCV.branded_draft_html)
        .where(
            CandidateStageCV.candidate_id == candidate_id,
            CandidateStageCV.job_id == job_id,
            CandidateStageCV.branded_draft_html.is_not(None),
        )
        .order_by(
            CandidateStageCV.branded_updated_at.desc().nulls_last(),
            CandidateStageCV.id.desc(),
        )
        .limit(1)
    )


def _name(candidate: Candidate) -> str:
    return " ".join(
        part.strip() for part in (candidate.name, candidate.lastname) if part
    ).strip()


async def _rate(
    db: AsyncSession,
    candidate_id: int,
    job_id: int,
    value: Optional[float],
    unit: Optional[str],
    currency: Optional[str],
) -> dict[str, Any]:
    """Stawka za MD: z przeglądu (parametry) albo zapisana stawka pary."""
    origin = "review"
    if value is None:
        stored = (await latest_client_rates(db, [(candidate_id, job_id)])).get(
            (candidate_id, job_id)
        )
        if stored is None:
            return {"md": None, "unit": None, "origin": None, "problem": MSG_NO_RATE}
        value, unit, currency = stored
        origin = "stored"
    unit = unit or "hourly"
    if (currency or "PLN").upper() != "PLN":
        return {"md": None, "unit": unit, "origin": origin, "problem": MSG_CURRENCY}
    md = cover_sheet.md_rate(value, unit)
    if md is None:
        problem = MSG_MONTHLY if unit == "monthly" else MSG_NO_RATE
        return {"md": None, "unit": unit, "origin": origin, "problem": problem}
    return {"md": md, "unit": unit, "origin": origin, "problem": None}


async def _computed(
    db: AsyncSession, job: Job, candidate: Candidate, rate: dict[str, Any]
) -> dict[str, tuple[Optional[str], Optional[str]]]:
    """Wartość i źródło każdego pola, zanim DL cokolwiek poprawi."""
    years = candidate.years_it_experience
    terms = cover_sheet.profile_from_cv_html(
        await _company_cv_html(db, candidate.id, job.id)
    )
    profile_source = "cv"
    if not terms:
        terms = cover_sheet.profile_from_skills(job.must_skills, candidate.skills)
        profile_source = "job_skills"
    availability = cover_sheet.availability_text(
        available_from=candidate.availability_date,
        notice_period=candidate.notice_period,
        notice_unit=candidate.notice_period_unit,
        today=business_today(),
    )
    md = rate["md"]
    city = (candidate.city or "").strip() or None
    return {
        cover_sheet.NAME: (_name(candidate) or None, "profile"),
        cover_sheet.ROLE: ((job.title or "").strip() or None, "job"),
        cover_sheet.LEVEL: (cover_sheet.level_for_years(years), "years"),
        cover_sheet.EXPERIENCE: (cover_sheet.experience_text(years), "years"),
        cover_sheet.PROFILE: (", ".join(terms) or None, profile_source),
        cover_sheet.AVAILABILITY: (availability, "profile"),
        cover_sheet.LOCATION: (city, "profile"),
        cover_sheet.RATE: (
            cover_sheet.amount_text(md) if md is not None else None,
            f"rate_{rate['unit']}" if md is not None else None,
        ),
    }


def _values(
    computed: dict[str, tuple[Optional[str], Optional[str]]],
    edits: Optional[CandidateClientForm],
) -> dict[str, tuple[Optional[str], Optional[str]]]:
    values = dict(computed)
    for field_id, item in ((edits.fields if edits else None) or {}).items():
        value = (item or {}).get("value")
        if field_id in EDITABLE and value:
            values[field_id] = (value, SOURCE_DL)
    return values


def _level_hint(years: Optional[int], source: Optional[str]) -> str:
    if source == SOURCE_DL:
        return "wpisane przez DL — sprawdź"
    if years is None:
        return "brak stażu w profilu — wybierz"
    return f"z {cover_sheet.experience_text(years)} stażu — sprawdź"


async def _view(
    db: AsyncSession,
    job: Job,
    candidate: Candidate,
    template: Optional[ClientCoverSheetTemplate],
    *,
    client_rate: Optional[float],
    client_rate_unit: Optional[str],
    client_rate_currency: Optional[str],
) -> dict[str, Any]:
    if template is None:
        return {"enabled": False}
    rate = await _rate(
        db,
        candidate.id,
        job.id,
        client_rate,
        client_rate_unit,
        client_rate_currency,
    )
    values = _values(
        await _computed(db, job, candidate, rate),
        await _edits(db, candidate.id, job.id),
    )
    try:
        structure = cover_sheet.read_template(template.content)
    except cover_sheet.SheetRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    fields = []
    for slot in structure.slots:
        value, source = values.get(slot.field, (None, None))
        to_check = slot.field == cover_sheet.LEVEL
        fields.append(
            {
                "id": slot.field,
                "label": slot.label or cover_sheet.FIELD_LABELS[slot.field],
                "value": value,
                "source": source,
                "source_label": (
                    _level_hint(candidate.years_it_experience, source)
                    if to_check
                    else SOURCE_LABELS.get(source or "")
                ),
                "suffix": slot.suffix,
                "to_check": to_check,
                "editable": slot.field in EDITABLE,
                "options": list(cover_sheet.LEVELS) if to_check else None,
            }
        )
    md = rate["md"]
    return {
        "enabled": True,
        "template": {"filename": template.filename},
        "layout": list(structure.layout),
        "fields": fields,
        "md_rate": float(md) if md is not None else None,
        "md_rate_label": cover_sheet.amount_text(md) if md is not None else None,
        "rate_origin": rate["origin"],
        "rate_problem": rate["problem"],
        "missing": [item["id"] for item in fields if not item["value"]],
    }


RATE_QUERY = Query(
    None, gt=0, le=1_000_000, description="Stawka do klienta z przeglądu"
)
UNIT_QUERY = Query(None, description="hourly | daily | monthly")
CURRENCY_QUERY = Query(None, min_length=3, max_length=3)


@router.get("/candidates/{candidate_id}/recruitments/{job_id}/cover-sheet")
@limiter.limit("120/minute", key_func=user_or_ip_key)
async def get_cover_sheet(
    request: Request,
    candidate_id: DbIdPath,
    job_id: DbIdPath,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
    client_rate: Optional[float] = RATE_QUERY,
    client_rate_unit: Optional[RateUnit] = UNIT_QUERY,
    client_rate_currency: Optional[str] = CURRENCY_QUERY,
) -> dict:
    job, candidate = await _pair(db, candidate_id, job_id, current_user, write=False)
    template = await _template(db, job.client_id, with_content=True)
    return await _view(
        db,
        job,
        candidate,
        template,
        client_rate=client_rate,
        client_rate_unit=client_rate_unit,
        client_rate_currency=client_rate_currency,
    )


@router.put("/candidates/{candidate_id}/recruitments/{job_id}/cover-sheet")
@limiter.limit("60/minute", key_func=user_or_ip_key)
async def save_cover_sheet(
    request: Request,
    candidate_id: DbIdPath,
    job_id: DbIdPath,
    payload: CoverSheetEdit,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
    client_rate: Optional[float] = RATE_QUERY,
    client_rate_unit: Optional[RateUnit] = UNIT_QUERY,
    client_rate_currency: Optional[str] = CURRENCY_QUERY,
) -> dict:
    """Poprawki DL-a; pusta wartość = wraca wartość wyliczona przez NEXUS."""
    job, candidate = await _pair(db, candidate_id, job_id, current_user, write=True)
    template = await _template(db, job.client_id, with_content=True)
    if template is None:
        raise HTTPException(status_code=409, detail=MSG_NO_TEMPLATE)
    if any(field_id not in EDITABLE for field_id in payload.fields):
        raise HTTPException(status_code=422, detail=MSG_UNKNOWN_FIELD)
    level = (payload.fields.get(cover_sheet.LEVEL) or "").strip()
    if level and level not in cover_sheet.LEVELS:
        raise HTTPException(status_code=422, detail=MSG_LEVEL)
    form = await _locked_edits(db, candidate.id, job.id)
    fields = dict(form.fields or {})
    changed = []
    for field_id, raw in payload.fields.items():
        value = cover_sheet.clean_value(raw)[: cover_sheet.VALUE_MAX]
        if value == (fields.get(field_id) or {}).get("value"):
            continue
        changed.append(field_id)
        if value:
            fields[field_id] = {"value": value, "source": SOURCE_DL}
        else:
            fields.pop(field_id, None)
    form.fields = fields
    form.updated_by = current_user.id
    if changed:
        # Bez wartości: karta niesie stawkę do klienta, a historia osoby nie.
        db.add(
            Activity(
                entity_type="candidate",
                entity_id=candidate.id,
                action="cover_sheet_saved",
                user_id=current_user.id,
                details={"job_id": job.id, "fields": changed},
            )
        )
    await db.flush()
    return await _view(
        db,
        job,
        candidate,
        template,
        client_rate=client_rate,
        client_rate_unit=client_rate_unit,
        client_rate_currency=client_rate_currency,
    )


def _download_name(candidate: Candidate) -> str:
    parts = [p.strip().replace(" ", "_") for p in (candidate.name, candidate.lastname)]
    name = "_".join(part for part in parts if part)
    return f"Karta_{name}.docx" if name else "Karta.docx"


@router.get("/candidates/{candidate_id}/recruitments/{job_id}/cover-sheet/docx")
@limiter.limit("60/minute", key_func=user_or_ip_key)
async def download_cover_sheet(
    request: Request,
    candidate_id: DbIdPath,
    job_id: DbIdPath,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
    client_rate: Optional[float] = RATE_QUERY,
    client_rate_unit: Optional[RateUnit] = UNIT_QUERY,
    client_rate_currency: Optional[str] = CURRENCY_QUERY,
) -> Response:
    """Karta jako osobny plik Word; bez stawki do klienta — 409."""
    job, candidate = await _pair(db, candidate_id, job_id, current_user, write=False)
    template = await _template(db, job.client_id, with_content=True)
    if template is None:
        raise HTTPException(status_code=409, detail=MSG_NO_TEMPLATE)
    rate = await _rate(
        db,
        candidate.id,
        job.id,
        client_rate,
        client_rate_unit,
        client_rate_currency,
    )
    if rate["md"] is None:
        raise HTTPException(status_code=409, detail=rate["problem"] or MSG_NO_RATE)
    values = _values(
        await _computed(db, job, candidate, rate),
        await _edits(db, candidate.id, job.id),
    )
    try:
        document = cover_sheet.render(
            template.content, {key: value or "" for key, (value, _) in values.items()}
        )
    except cover_sheet.SheetRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(
        content=document,
        media_type=DOCX_TYPE,
        headers={
            "Content-Disposition": content_disposition(
                _download_name(candidate), "attachment", fallback="karta.docx"
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )
