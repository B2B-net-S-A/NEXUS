"""Jedna karta DRAFT przez istniejącą sesję WWW; bez publicznego tokenu bota."""

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import CandidateDocumentAccess, user_can_view_client_rate
from app.api.candidate_stage_cv import (
    _load_csv_for_stage,
    approved_version_for_download,
)
from app.api.deps import OperationalUser
from app.core.database import get_db
from app.core.http_headers import content_disposition_attachment
from app.models.cpro_bot import CproBotRun
from app.models.activity import Activity
from app.models.user import User
from app.services import candidate_audit, cpro_sender, cv_new_pdf as new_cv_pdf
from app.services.cpro_bot import flow, ingest, offer_text, runs
from app.services.cpro_bot import operator_browser as service
from app.services.cpro_bot.cv_file import render_approved_pdf
from app.services.cv_download_log import log_cv_download
from app.services.cv_pdf_preview import MSG_UNAVAILABLE, PdfPreviewUnavailable

router = APIRouter()


class DraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    delivery_lead_id: StrictInt = Field(gt=0)
    request_number: str = Field(pattern=r"^[0-9]{4,7}$")


class DraftConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    offer_id: str | StrictInt
    confirmed_draft: Literal[True]
    confirmed_pdf: Literal[True]

    @field_validator("offer_id", mode="before")
    @classmethod
    def numeric_offer(cls, value):
        if (
            type(value) not in (str, int)
            or not str(value).isascii()
            or not str(value).isdigit()
            or not 1 <= len(str(value)) <= 20
            or int(value) <= 0
        ):
            raise ValueError("Podaj numeryczny identyfikator oferty Cpro.")
        return str(int(value))

    @field_validator("confirmed_draft", "confirmed_pdf", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("Potwierdź DRAFT i podgląd PDF w Cpro.")
        return value


class AbsentConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    confirmed_absent: Literal[True]

    @field_validator("confirmed_absent", mode="before")
    @classmethod
    def explicit_absence(cls, value):
        if value is not True:
            raise ValueError("Potwierdź brak oferty na liście Our offers.")
        return value


async def require_operator(
    request: Request,
    current_user: OperationalUser,
    document_user: CandidateDocumentAccess,
    db: AsyncSession = Depends(get_db),
) -> User:
    if (
        getattr(request.state, "oauth_client_id", None)
        or getattr(request.state, "service_principal", None)
        or getattr(request.state, "impersonator_id", None)
    ):
        raise HTTPException(403, "Ten pilot wymaga własnej sesji WWW operatora.")
    now = datetime.now(timezone.utc)
    can_send = await cpro_sender.can_send_to_cpro(db, current_user, now)
    show_rate = (
        user_can_view_client_rate(current_user)
        or (await cpro_sender.effective_sender(db, now)).user_id == current_user.id
    )
    if not service.can_use(current_user, can_send=can_send, show_rate=show_rate):
        raise HTTPException(403, "Brak uprawnień operatora Cpro do danych tej karty.")
    return current_user


async def owned_run(db: AsyncSession, run_id: int, user: User) -> CproBotRun:
    run = await db.get(CproBotRun, run_id, with_for_update=True, populate_existing=True)
    if run is None or not service.owned_by(run, user.id):
        raise HTTPException(404, "Nie ma takiego biegu operatora.")
    if run.submit is not False or run.token_hash is not None:
        raise HTTPException(409, "Bieg nie jest bezpiecznym szkicem operatora.")
    await service.ensure_run_access(db, run, user)
    return run


@router.post("/stages/{stage_id}/draft")
async def claim_draft(
    stage_id: int,
    payload: DraftRequest,
    user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        run, created = await service.claim(
            db,
            user,
            stage_id,
            delivery_lead_id=payload.delivery_lead_id,
            request_number=payload.request_number,
            now=datetime.now(timezone.utc),
        )
    except flow.NotReady as error:
        raise HTTPException(409, error.detail) from None
    return {"run_id": run.id, "created": created}


@router.get("/runs/{run_id}")
async def read_run(
    run_id: int,
    response: Response,
    user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    run = await owned_run(db, run_id, user)
    response.headers["Cache-Control"] = "private, no-store"
    now = datetime.now(timezone.utc)
    return service.view(
        run,
        current=await service.current_snapshot(db, run, now=now),
        allow_close_absent=service.can_close_absent(
            run, identity_matches=await service.identity_current(db, run), now=now
        ),
    )


@router.get("/runs/{run_id}/cv")
async def download_cv(
    run_id: int,
    user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> Response:
    run = await owned_run(db, run_id, user)
    if not service.pdf_available(
        run, now=datetime.now(timezone.utc)
    ) or not await service.current_snapshot(db, run, now=datetime.now(timezone.utc)):
        raise HTTPException(
            409, "Dane karty lub PDF zmieniły się — sprawdź istniejącą ofertę ręcznie."
        )
    item = service.item_for(run)
    card = run.request["cards"][str(item["ref"])]
    csv = await _load_csv_for_stage(
        db, int(card["cv_stage_id"]), user, read_access=True
    )
    offer = item["offer"]
    version_number = offer.get("cv_version")
    if (
        offer.get("cv_format") != "pdf"
        or type(version_number) is not int
        or version_number <= 0
    ):
        raise HTTPException(409, "Bieg nie zawiera zatwierdzonej wersji PDF.")
    version = await approved_version_for_download(db, csv, version_number)
    version_id, csv_id, candidate_id = version.version, csv.id, csv.candidate_id
    try:
        content, layout = await render_approved_pdf(db, version)
    except (PdfPreviewUnavailable, new_cv_pdf.NewCvPdfError) as error:
        raise HTTPException(503, MSG_UNAVAILABLE) from error
    if not content.startswith(b"%PDF-"):
        raise HTTPException(503, MSG_UNAVAILABLE)
    fresh_run = await owned_run(db, run_id, user)
    if not service.pdf_available(
        fresh_run, now=datetime.now(timezone.utc)
    ) or not await service.current_snapshot(
        db, fresh_run, now=datetime.now(timezone.utc)
    ):
        raise HTTPException(409, "Dane karty lub PDF zmieniły się podczas pobierania.")
    await log_cv_download(
        db,
        intent="download",
        surface=None,
        entity_type="candidate_stage_cv",
        entity_id=csv_id,
        user=user,
        file_format="pdf",
        state="approved",
        version=version_id,
    )
    candidate_audit.record_candidate_audit(
        db,
        action=candidate_audit.CV_DOWNLOADED,
        user_id=user.id,
        entity_id=candidate_id,
        details={"endpoint": "cpro_operator_cv", "format": "pdf", "run_id": run_id},
    )
    await db.commit()
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": content_disposition_attachment(
                offer_text.safe_filename(offer.get("cv_file_name"), extension=".pdf")
            ),
            "X-CV-Version": str(version_id),
            "X-CV-Layout": layout,
        },
    )


@router.post("/runs/{run_id}/confirm")
async def confirm_draft(
    run_id: int,
    payload: DraftConfirmation,
    user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await runs.lock_new_run(db)
    run = await owned_run(db, run_id, user)
    offer_id = str(payload.offer_id)
    if run.status == "received":
        if run.request.get("operator_offer_id") != offer_id:
            raise HTTPException(409, "Ten bieg potwierdza inną ofertę.")
        return {"run_id": run.id, "status": "received", "offer_id": offer_id}
    if run.status not in ("started", "expired", "failed") or run.report:
        raise HTTPException(
            409, "Bieg wymaga ręcznego rozstrzygnięcia istniejącej oferty."
        )
    await service.ensure_offer_available(db, run.id, offer_id)
    if not await service.identity_current(db, run):
        raise HTTPException(
            409, "Karta zmieniła konto lub request — wymaga ręcznego rozstrzygnięcia."
        )
    item = service.item_for(run)
    now = datetime.now(timezone.utc)
    run.request = {
        **run.request,
        "operator_offer_id": offer_id,
        "operator_confirmed_by_user_id": user.id,
        "operator_confirmed_at": now.isoformat(),
        "operator_confirmed_pdf": True,
    }
    report = ingest.CproReport(
        items=[
            ingest.ReportItem(
                ref=item["ref"],
                outcome="draft",
                cpro_status="DRAFT",
                offer_url=f"https://nordea.onevms.se/nordea/vendor/OfferController?action=view&id={offer_id}",
            )
        ]
    )
    await ingest.apply_report(db, run, report, now=now)
    return {"run_id": run.id, "status": "received", "offer_id": offer_id}


@router.post("/runs/{run_id}/close-absent")
async def close_absent(
    run_id: int,
    payload: AbsentConfirmation,
    user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await runs.lock_new_run(db)
    run = await owned_run(db, run_id, user)
    item = service.item_for(run)
    if run.request.get("operator_absent_confirmed") is True:
        return {
            "run_id": run.id,
            "status": "closed_absent",
            "reservation_released": True,
        }
    now = datetime.now(timezone.utc)
    if not service.can_close_absent(
        run, identity_matches=await service.identity_current(db, run), now=now
    ):
        raise HTTPException(
            409, "Brak możliwości zamknięcia tej rezerwacji bez oferty."
        )
    run.status = "failed"
    run.token_hash = None
    run.received_at = now
    run.error = "Operator potwierdził brak oferty w Our offers po upływie czasu pilota."
    run.request = {
        **run.request,
        "operator_absent_confirmed": True,
        "operator_absent_confirmed_by_user_id": user.id,
        "operator_absent_confirmed_at": now.isoformat(),
    }
    run.report = ingest.summarize(
        run,
        ingest.CproReport(
            items=[
                ingest.ReportItem(
                    ref=item["ref"],
                    outcome="skipped",
                    reason="operator_confirmed_absent",
                )
            ]
        ),
    )
    db.add(
        Activity(
            entity_type="pipeline",
            entity_id=item["ref"],
            action="cpro_operator_closed_absent",
            user_id=user.id,
            details={"run_id": run.id, "stage_id": item["ref"]},
        )
    )
    await db.commit()
    return {"run_id": run.id, "status": "closed_absent", "reservation_released": True}
