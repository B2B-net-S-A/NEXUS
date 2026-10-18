"""Protokoły sprzętu w e-teczce — odnośniki, bez kopiowania plików.

E-teczka czyta ``equipment_protocols`` osoby (posiadacz = konto NEXUSA) i podaje
plik z modułu sprzętu: wgrany podpisany skan, a bez skanu — protokół
wypełniony z jego wzoru (``protocols.render_pdf`` / ``render_docx``). Widzą je
osoba, Kadry, admin i recepcja („Sprzęt”); Płace i przełożony nie. Bez
wartości i bez pozycji — szczegóły zostają w module sprzętu.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.equipment import EquipmentProtocol
from app.services.hr.documents import HrDocumentError

_SCAN_TYPES = {
    "pdf": "application/pdf",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
}
#: Protokoły unieważnione nie należą do e-teczki.
SKIPPED_STATUSES = ("anulowany",)


async def protocols_of(db: AsyncSession, user_id: int) -> list[EquipmentProtocol]:
    rows = await db.scalars(
        select(EquipmentProtocol)
        .where(
            EquipmentProtocol.user_id == user_id,
            EquipmentProtocol.status.not_in(SKIPPED_STATUSES),
        )
        .order_by(EquipmentProtocol.protocol_date.desc(), EquipmentProtocol.id.desc())
    )
    return list(rows)


def protocol_payload(protocol: EquipmentProtocol) -> dict[str, Any]:
    return {
        "id": protocol.id,
        "number": protocol.number,
        "kind": protocol.kind,
        "protocol_date": protocol.protocol_date,
        "status": protocol.status,
        "signed_at": protocol.signed_at,
        "has_signed_file": bool(protocol.signed_file_path),
    }


async def protocol_of_person(
    db: AsyncSession, user_id: int, protocol_id: int
) -> EquipmentProtocol:
    protocol = await db.get(EquipmentProtocol, protocol_id)
    if (
        protocol is None
        or protocol.user_id != user_id
        or protocol.status in SKIPPED_STATUSES
    ):
        raise HrDocumentError("Nie ma takiego protokołu.", 404)
    return protocol


@dataclass(frozen=True)
class ProtocolFile:
    content: Optional[bytes]
    path: Optional[Any]
    media_type: str
    filename: str


async def protocol_file(db: AsyncSession, protocol: EquipmentProtocol) -> ProtocolFile:
    """Podpisany skan, jeśli jest; inaczej PDF z wzoru (bez LibreOffice — Word)."""

    from app.services.equipment import protocol_document, protocols
    from app.services.equipment.errors import EquipmentError

    if protocol.signed_file_path:
        try:
            path = protocols.signed_file_path(protocol)
        except EquipmentError as exc:
            raise HrDocumentError(exc.message, 404) from None
        suffix = path.suffix.lstrip(".").lower() or "pdf"
        media = _SCAN_TYPES.get(suffix, "application/octet-stream")
        return ProtocolFile(
            content=None,
            path=path,
            media_type=media,
            filename=protocols.protocol_filename(protocol, suffix),
        )
    try:
        content = await protocols.render_pdf(db, protocol)
        return ProtocolFile(
            content=content,
            path=None,
            media_type="application/pdf",
            filename=protocols.protocol_filename(protocol, "pdf"),
        )
    except protocol_document.ProtocolPdfUnavailable:
        pass
    except EquipmentError as exc:
        raise HrDocumentError(exc.message, exc.status) from None
    try:
        content = await protocols.render_docx(db, protocol)
    except EquipmentError as exc:
        raise HrDocumentError(exc.message, exc.status) from None
    return ProtocolFile(
        content=content,
        path=None,
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        filename=protocols.protocol_filename(protocol, "docx"),
    )


__all__ = [
    "ProtocolFile",
    "protocol_file",
    "protocol_of_person",
    "protocol_payload",
    "protocols_of",
]
