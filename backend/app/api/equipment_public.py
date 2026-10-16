"""Publiczny link do podpisu protokołu wydania/zwrotu sprzętu.

Prefiks ``/api/public/equipment-protocols`` (wpięty w ``app/main.py``). Trasy
mają ``@limiter.limit`` — dlatego moduł NIE ma ``from __future__ import
annotations`` (ciało żądania lądowałoby jako parametr query → 422).
Token w adresie jest porównywany z hashem w bazie; bez logowania.

Strona pokazuje wyłącznie ten jeden protokół (treść z pliku, pozycje,
termin linku). Zły, zużyty, wygasły i unieważniony token dają to samo 404
z tym samym zdaniem — z zewnątrz nie da się odróżnić przyczyny. Osoba wpisuje
imię i nazwisko i potwierdza odbiór; podpis zatwierdza potem recepcja (D4).
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.http_headers import content_disposition
from app.core.rate_limit import limiter
from app.services.equipment import protocol_document, protocols
from app.services.equipment.registry import EquipmentError, EquipmentNotFound

router = APIRouter()

GENERIC_404 = "Link nieprawidłowy lub wygasły."

# slowapi liczy ``@limiter.limit`` osobno dla każdego ADRESU (``key_style="url"``),
# czyli osobno dla każdego tokenu. Wspólny kubełek per IP na wszystkie tokeny
# (``shared_limit``) zamyka zgadywanie tokenów seriami różnych adresów.
SHARED_READ = "60/minute"
SHARED_SIGN = "10/minute"


class SignIn(BaseModel):
    signer_name: str = Field(min_length=3, max_length=200)
    accepted: Literal[True]


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail=GENERIC_404)


@router.get("/{token}")
@limiter.limit("30/minute")
@limiter.shared_limit(SHARED_READ, scope="equipment-protocols-read")
async def get_protocol_for_signature(
    token: str,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        link, protocol = await protocols.load_link(db, token)
    except EquipmentNotFound as exc:
        raise _not_found() from exc
    view = await protocols.render(db, protocol)
    return {
        "number": protocol.number,
        "kind": protocol.kind,
        "protocol_date": protocol.protocol_date.isoformat(),
        "holder_name": protocol.holder_name,
        "issuer_name": protocol.issuer_name,
        "expires_at": link.expires_at.isoformat(),
        "lines": [
            {
                "position": line.position,
                "name": line.name,
                "identifier": line.identifier,
                "value": protocol_document.amount(line.unit_value)
                if line.unit_value is not None
                else None,
                "condition": line.condition,
            }
            for line in view.lines
        ],
        "total": protocol_document.total_amount(protocol.total_value),
        "document": protocol_document.document_blocks(
            protocol_document.render_docx(view)
        ),
    }


@router.get("/{token}/document.pdf")
@limiter.limit("10/minute")
@limiter.shared_limit(SHARED_READ, scope="equipment-protocols-read")
async def get_protocol_pdf(
    token: str,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        _link, protocol = await protocols.load_link(db, token)
    except EquipmentNotFound as exc:
        raise _not_found() from exc
    try:
        content = await protocol_document.render_pdf(
            await protocols.render(db, protocol)
        )
    except protocol_document.ProtocolPdfUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="PDF jest chwilowo niedostępny."
        ) from exc
    return Response(
        content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": content_disposition(
                protocols.protocol_filename(protocol, "pdf"), "inline"
            )
        },
    )


@router.post("/{token}/sign")
@limiter.limit("5/minute;30/hour")
@limiter.shared_limit(SHARED_SIGN, scope="equipment-protocols-sign")
async def sign_protocol(
    token: str,
    payload: SignIn,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        protocol = await protocols.sign_by_link(
            db, token, signer_name=payload.signer_name
        )
    except EquipmentNotFound as exc:
        raise _not_found() from exc
    except EquipmentError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    return {"number": protocol.number, "status": protocol.status}
