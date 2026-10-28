"""Protokoły sprzętu: numer, migawka, podpis i jednorazowy link (D4, D8).

* Numer ``PZO/<rok>/<miesiąc>/<kolejny w roku>`` — kolejność pod blokadą
  doradczą transakcji, więc dwa równoległe wydania nie dostaną tego samego
  numeru (a ``UNIQUE (year, seq)`` i tak by to odrzuciło).
* Podpis: link (osoba wpisuje imię i nazwisko i potwierdza), papier albo
  profil zaufany (skan wgrywa recepcja). Stan „podpisany” potwierdza
  CZŁOWIEK — automatyczna weryfikacja podpisu zaufanego bywa „nieokreślona”.
* Link: token tylko w adresie, w bazie SHA-256; 14 dni, jednorazowy. Nowy
  link unieważnia poprzednie niezużyte. Zły, zużyty, wygasły i unieważniony
  token wyglądają z zewnątrz tak samo.
* Wzór (etap 3, O3): protokół kontraktu bierze wzór wydania albo zwrotu
  z pakietu klienta (``client_pack.template_for``) i zapamiętuje go
  (``template_id``); bez wzoru w pakiecie — wbudowany standard. Plik
  protokołu powstaje zawsze z TEGO wzoru (``render_docx`` / ``render_pdf``),
  wgrany wypełnia się w sandboxie (``protocol_template.render_uploaded``).
"""

from __future__ import annotations

import hashlib
import io
import secrets
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional, Sequence
from zoneinfo import ZoneInfo

from jinja2 import TemplateError
from jinja2.exceptions import SecurityError
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.scheduling import DEFAULT_TZ
from app.models.contract import Contract
from app.models.equipment import (
    EquipmentAssignment,
    EquipmentProtocol,
    EquipmentProtocolLine,
    EquipmentProtocolLink,
    EquipmentProtocolTemplate,
    EquipmentTask,
)
from app.models.notification import NotificationType
from app.models.user import User
from app.services import cv_pdf_preview, storage_service
from app.services.equipment import protocol_document, protocol_template
from app.services.equipment.protocol_template import TEMPLATE_VERSION
from app.services.equipment.errors import (
    EquipmentConflict,
    EquipmentError,
    EquipmentNotFound,
)
from app.services.equipment.holders import Holder, holder_columns, holder_of
from app.services.hr import audit
from app.services.hr.notify import notify_each

LINK_VALID_DAYS = 14
SIGNED_DIR = storage_service.STORAGE_ROOT / "equipment_protocols"
MAX_SIGNED_BYTES = 20 * 1024 * 1024
_SEQ_LOCK = "equipment_protocol_number"


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def public_url(token: str) -> str:
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/protocol/{token}"


async def next_number(db: AsyncSession, protocol_date: date) -> tuple[int, int, str]:
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": _SEQ_LOCK}
    )
    year = protocol_date.year
    current = await db.scalar(
        select(EquipmentProtocol.seq)
        .where(EquipmentProtocol.year == year)
        .order_by(EquipmentProtocol.seq.desc())
        .limit(1)
    )
    seq = (current or 0) + 1
    return year, seq, f"PZO/{year}/{protocol_date.month:02d}/{seq:03d}"


def uploaded_template_version(template_id: int) -> str:
    """``template_version`` protokołu z wgranego wzoru (mieści się w 16 znakach)."""
    return f"wzor-{template_id}"[:16]


async def template_for_holder(
    db: AsyncSession, kind: str, holder: Holder
) -> Optional[EquipmentProtocolTemplate]:
    """Wzór z pakietu klienta dla konsultanta (kontrakt); reszta — standard."""
    if holder.kind != "contract":
        return None
    from app.services.hr import client_pack

    client_id = await db.scalar(
        select(Contract.client_id).where(Contract.id == holder.id)
    )
    return await client_pack.template_for(db, client_id, kind)


async def create_protocol(
    db: AsyncSession,
    *,
    kind: str,
    holder: Holder,
    lines: Sequence[dict[str, Any]],
    protocol_date: date,
    actor: User,
    issuer_name: Optional[str] = None,
) -> EquipmentProtocol:
    """Protokół z migawką pozycji (``lines``: name, identifier, unit_value…)."""
    template = await template_for_holder(db, kind, holder)
    year, seq, number = await next_number(db, protocol_date)
    views = [
        protocol_document.LineView(
            position=index,
            name=line["name"],
            identifier=line.get("identifier"),
            quantity=line.get("quantity", 1),
            unit_value=line.get("unit_value"),
        )
        for index, line in enumerate(lines, start=1)
    ]
    protocol = EquipmentProtocol(
        kind=kind,
        year=year,
        seq=seq,
        number=number,
        protocol_date=protocol_date,
        holder_name=holder.name,
        holder_email=holder.email,
        issuer_user_id=actor.id,
        issuer_name=(issuer_name or actor.name or actor.email)[:200],
        total_value=protocol_document.protocol_total(views),
        template_version=(
            uploaded_template_version(template.id) if template else TEMPLATE_VERSION
        ),
        template_id=template.id if template else None,
        **holder_columns(holder.kind, holder.id),
    )
    db.add(protocol)
    await db.flush()
    for index, line in enumerate(lines, start=1):
        db.add(
            EquipmentProtocolLine(
                protocol_id=protocol.id,
                position=index,
                item_id=line.get("item_id"),
                assignment_id=line.get("assignment_id"),
                category=line["category"],
                name=line["name"][:300],
                identifier=(line.get("identifier") or None),
                quantity=line.get("quantity", 1),
                unit_value=line.get("unit_value"),
                condition=line.get("condition"),
                notes=line.get("notes"),
            )
        )
    await db.flush()
    return protocol


async def protocol_lines(
    db: AsyncSession, protocol_id: int
) -> list[EquipmentProtocolLine]:
    return list(
        (
            await db.scalars(
                select(EquipmentProtocolLine)
                .where(EquipmentProtocolLine.protocol_id == protocol_id)
                .order_by(EquipmentProtocolLine.position)
            )
        ).all()
    )


def view_of(
    protocol: EquipmentProtocol, lines: Sequence[EquipmentProtocolLine]
) -> protocol_document.ProtocolView:
    return protocol_document.ProtocolView(
        kind=protocol.kind,
        number=protocol.number,
        protocol_date=protocol.protocol_date,
        holder_name=protocol.holder_name,
        issuer_name=protocol.issuer_name,
        lines=tuple(
            protocol_document.LineView(
                position=line.position,
                name=line.name,
                identifier=line.identifier,
                quantity=line.quantity,
                unit_value=line.unit_value,
                condition=line.condition,
                notes=line.notes,
            )
            for line in lines
        ),
    )


async def get_protocol(db: AsyncSession, protocol_id: int) -> EquipmentProtocol:
    protocol = await db.get(EquipmentProtocol, protocol_id)
    if protocol is None:
        raise EquipmentNotFound("Nie ma takiego protokołu.")
    return protocol


async def render(
    db: AsyncSession, protocol: EquipmentProtocol
) -> protocol_document.ProtocolView:
    view = view_of(protocol, await protocol_lines(db, protocol.id))
    confirmer = (
        await db.get(User, protocol.confirmed_by) if protocol.confirmed_by else None
    )
    return replace(
        view,
        holder_signature=holder_signature(protocol),
        issuer_signature=issuer_signature(protocol, confirmer),
    )


def _stamp(moment: datetime) -> str:
    local = moment.astimezone(ZoneInfo(DEFAULT_TZ))
    return f"{local:%d.%m.%Y}, godz. {local:%H:%M}"


def holder_signature(protocol: EquipmentProtocol) -> str:
    """Dopisek pod podpisem osoby: odbiór potwierdzony linkiem (D8)."""
    if protocol.signature_method != "link" or protocol.signed_at is None:
        return ""
    return (
        f"Potwierdzono elektronicznie linkiem z NEXUSA jako "
        f"„{protocol.signer_name}”, {_stamp(protocol.signed_at)}"
    )


def issuer_signature(protocol: EquipmentProtocol, confirmer: Optional[User]) -> str:
    """Dopisek pod podpisem recepcji: kto potwierdził podpis w NEXUSIE (D4)."""
    if protocol.status != "potwierdzony" or protocol.confirmed_at is None:
        return ""
    who = (confirmer.name or confirmer.email) if confirmer else protocol.issuer_name
    return f"Zatwierdzono w NEXUSIE: {who}, {_stamp(protocol.confirmed_at)}"


async def render_docx(db: AsyncSession, protocol: EquipmentProtocol) -> bytes:
    """Plik Word protokołu z wzoru, z którego powstał (wgrany albo standard)."""
    view = await render(db, protocol)
    if protocol.template_id is None:
        return protocol_document.render_docx(view)
    content = await db.scalar(
        select(EquipmentProtocolTemplate.content).where(
            EquipmentProtocolTemplate.id == protocol.template_id
        )
    )
    if content is None:
        raise EquipmentNotFound("Nie ma już wzoru, z którego powstał ten protokół.")
    try:
        return protocol_template.render_uploaded(
            content, protocol_document.context_for(view)
        )
    except (SecurityError, TemplateError) as exc:
        # Wzór przeszedł sprawdzenie przy wgraniu; tu trafia tylko protokół,
        # którego dane różnią się od próbnych (np. pole użyte warunkowo).
        raise EquipmentError(
            "Wzoru tego protokołu nie da się wypełnić — sprawdź wzór w zakładce "
            "„Wzory protokołów”."
        ) from exc


async def render_pdf(db: AsyncSession, protocol: EquipmentProtocol) -> bytes:
    """PDF z tego samego pliku Word (``ProtocolPdfUnavailable`` → trasa 503)."""
    content = await render_docx(db, protocol)
    try:
        return await cv_pdf_preview.pdf_from_docx(content)
    except cv_pdf_preview.PdfPreviewUnavailable as exc:
        raise protocol_document.ProtocolPdfUnavailable(str(exc)) from exc


def line_payload(line: EquipmentProtocolLine) -> dict[str, Any]:
    return {
        "position": line.position,
        "item_id": line.item_id,
        "category": line.category,
        "name": line.name,
        "identifier": line.identifier,
        "quantity": line.quantity,
        "unit_value": None if line.unit_value is None else str(line.unit_value),
        "condition": line.condition,
        "notes": line.notes,
    }


def protocol_payload(
    protocol: EquipmentProtocol,
    lines: Sequence[EquipmentProtocolLine] | None = None,
    *,
    link: EquipmentProtocolLink | None = None,
) -> dict[str, Any]:
    kind, holder_id = holder_of(protocol) or (None, None)
    payload: dict[str, Any] = {
        "id": protocol.id,
        "kind": protocol.kind,
        "number": protocol.number,
        "protocol_date": protocol.protocol_date.isoformat(),
        "holder": {
            "kind": kind,
            "id": holder_id,
            "name": protocol.holder_name,
            "email": protocol.holder_email,
        },
        "issuer_name": protocol.issuer_name,
        "total_value": str(protocol.total_value),
        "status": protocol.status,
        "signature_method": protocol.signature_method,
        "signed_at": protocol.signed_at.isoformat() if protocol.signed_at else None,
        "signer_name": protocol.signer_name,
        "has_signed_file": bool(protocol.signed_file_path),
        "confirmed_at": (
            protocol.confirmed_at.isoformat() if protocol.confirmed_at else None
        ),
        "template_version": protocol.template_version,
        "template_id": protocol.template_id,
        "created_at": protocol.created_at.isoformat() if protocol.created_at else None,
        "link": (
            {
                "expires_at": link.expires_at.isoformat(),
                "used_at": link.used_at.isoformat() if link.used_at else None,
                "created_at": link.created_at.isoformat() if link.created_at else None,
            }
            if link
            else None
        ),
    }
    if lines is not None:
        payload["lines"] = [line_payload(line) for line in lines]
    return payload


async def latest_link(
    db: AsyncSession, protocol_id: int
) -> Optional[EquipmentProtocolLink]:
    return await db.scalar(
        select(EquipmentProtocolLink)
        .where(
            EquipmentProtocolLink.protocol_id == protocol_id,
            EquipmentProtocolLink.revoked_at.is_(None),
        )
        .order_by(EquipmentProtocolLink.id.desc())
        .limit(1)
    )


async def list_protocols(
    db: AsyncSession,
    *,
    status: Optional[str] = None,
    kind: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    query = select(EquipmentProtocol).order_by(
        EquipmentProtocol.protocol_date.desc(), EquipmentProtocol.id.desc()
    )
    if status == "waiting":
        query = query.where(EquipmentProtocol.status.in_(("oczekuje", "podpisany")))
    elif status:
        query = query.where(EquipmentProtocol.status == status)
    if kind:
        query = query.where(EquipmentProtocol.kind == kind)
    if q and q.strip():
        needle = f"%{q.strip()}%"
        query = query.where(
            EquipmentProtocol.number.ilike(needle)
            | EquipmentProtocol.holder_name.ilike(needle)
        )
    protocols = (await db.scalars(query.limit(limit))).all()
    links: dict[int, EquipmentProtocolLink] = {}
    if protocols:
        rows = (
            await db.scalars(
                select(EquipmentProtocolLink)
                .where(
                    EquipmentProtocolLink.protocol_id.in_([p.id for p in protocols]),
                    EquipmentProtocolLink.revoked_at.is_(None),
                )
                .order_by(EquipmentProtocolLink.id)
            )
        ).all()
        links = {row.protocol_id: row for row in rows}
    return [protocol_payload(p, link=links.get(p.id)) for p in protocols]


def _ensure_open(protocol: EquipmentProtocol) -> None:
    if protocol.status in ("potwierdzony", "anulowany"):
        raise EquipmentConflict("Ten protokół jest już zamknięty.")


async def create_link(
    db: AsyncSession, protocol: EquipmentProtocol, *, actor: User
) -> tuple[EquipmentProtocolLink, str]:
    """Nowy link (poprzednie niezużyte przestają działać). Zwraca surowy token."""
    _ensure_open(protocol)
    if protocol.status == "podpisany":
        raise EquipmentConflict("Protokół jest już podpisany — czeka na potwierdzenie.")
    now = datetime.now(timezone.utc)
    await db.execute(
        update(EquipmentProtocolLink)
        .where(
            EquipmentProtocolLink.protocol_id == protocol.id,
            EquipmentProtocolLink.used_at.is_(None),
            EquipmentProtocolLink.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    raw = secrets.token_urlsafe(32)
    link = EquipmentProtocolLink(
        protocol_id=protocol.id,
        token_sha256=token_hash(raw),
        expires_at=now + timedelta(days=LINK_VALID_DAYS),
        created_by=actor.id,
    )
    db.add(link)
    if protocol.signature_method == "brak":
        protocol.signature_method = "link"
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=protocol.user_id,
        entity_type="equipment_protocol",
        entity_id=protocol.id,
        action="signature_link_created",
    )
    return link, raw


async def load_link(
    db: AsyncSession, token: str, *, for_update: bool = False
) -> tuple[EquipmentProtocolLink, EquipmentProtocol]:
    """Ważny, niezużyty link albo ``EquipmentNotFound`` (jedno zdanie dla wszystkich przyczyn)."""
    if not token or len(token) > 200:
        raise EquipmentNotFound("Link nieprawidłowy lub wygasły.")
    query = select(EquipmentProtocolLink).where(
        EquipmentProtocolLink.token_sha256 == token_hash(token)
    )
    if for_update:
        query = query.with_for_update()
    link = await db.scalar(query)
    now = datetime.now(timezone.utc)
    if (
        link is None
        or link.used_at is not None
        or link.revoked_at is not None
        or link.expires_at <= now
    ):
        raise EquipmentNotFound("Link nieprawidłowy lub wygasły.")
    protocol = await db.get(EquipmentProtocol, link.protocol_id)
    if protocol is None or protocol.status != "oczekuje":
        raise EquipmentNotFound("Link nieprawidłowy lub wygasły.")
    return link, protocol


async def sign_by_link(
    db: AsyncSession, token: str, *, signer_name: str
) -> EquipmentProtocol:
    """Osoba z linku potwierdza odbiór; recepcja potwierdza potem podpis (D4)."""
    name = " ".join(signer_name.split())
    if len(name) < 3:
        raise EquipmentError("Wpisz imię i nazwisko.")
    link, protocol = await load_link(db, token, for_update=True)
    now = datetime.now(timezone.utc)
    link.used_at = now
    protocol.status = "podpisany"
    protocol.signature_method = "link"
    protocol.signed_at = now
    protocol.signer_name = name[:200]
    await db.flush()
    audit.record(
        db,
        actor_user_id=None,
        subject_user_id=protocol.user_id,
        entity_type="equipment_protocol",
        entity_id=protocol.id,
        action="signed_by_link",
    )
    # Podpis zapisany, dzwonek to dodatek — jego awaria idzie do logu.
    await notify_each(
        db,
        [protocol.issuer_user_id],
        title=f"Protokół {protocol.number} podpisany linkiem",
        message=(
            f"{protocol.holder_name} potwierdził(a) odbiór sprzętu. "
            "Sprawdź podpis i potwierdź protokół."
        ),
        ntype=NotificationType.equipment_protocol_signed,
        related_entity_type="equipment_protocol",
        related_entity_id=protocol.id,
        link=f"/equipment?tab=protocols&protocol={protocol.id}",
        log_tag="equipment",
    )
    return protocol


async def save_signed_file(
    db: AsyncSession,
    protocol: EquipmentProtocol,
    *,
    filename: str,
    content: bytes,
    method: str,
    actor: User,
) -> EquipmentProtocol:
    """Skan albo PDF z podpisem zaufanym, wgrany przez recepcję."""
    _ensure_open(protocol)
    if method not in ("papier", "profil_zaufany"):
        raise EquipmentError("Wybierz: podpis na papierze albo profilem zaufanym.")
    if not content or len(content) > MAX_SIGNED_BYTES:
        raise EquipmentError("Plik jest pusty albo większy niż 20 MB.")
    if not (
        content.startswith(b"%PDF")
        or content[:3] == b"\xff\xd8\xff"
        or content.startswith(b"\x89PNG")
    ):
        raise EquipmentError("Wgraj PDF albo zdjęcie (JPG, PNG).")
    relative, _size = storage_service._save_to(  # noqa: SLF001 — wspólny zapis magazynu
        SIGNED_DIR / str(protocol.id), filename or "protokol.pdf", io.BytesIO(content)
    )
    previous = protocol.signed_file_path
    protocol.signed_file_path = relative
    protocol.signature_method = method
    if protocol.status == "oczekuje":
        protocol.status = "podpisany"
        protocol.signed_at = datetime.now(timezone.utc)
        protocol.signer_name = protocol.signer_name or protocol.holder_name
    await db.flush()
    if previous and previous != relative:
        storage_service._delete_relative(previous, "equipment protocol scan")  # noqa: SLF001
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=protocol.user_id,
        entity_type="equipment_protocol",
        entity_id=protocol.id,
        action="signed_file_uploaded",
        details={"method": method},
    )
    return protocol


def signed_file_path(protocol: EquipmentProtocol):
    if not protocol.signed_file_path:
        raise EquipmentNotFound("Ten protokół nie ma wgranego podpisanego pliku.")
    try:
        return storage_service._resolve_under_root(protocol.signed_file_path)  # noqa: SLF001
    except FileNotFoundError as exc:
        raise EquipmentNotFound("Pliku nie ma już w magazynie.") from exc


async def confirm(
    db: AsyncSession,
    protocol: EquipmentProtocol,
    *,
    method: Optional[str],
    signer_name: Optional[str],
    actor: User,
) -> EquipmentProtocol:
    """Człowiek potwierdza podpis (link, papier, profil zaufany)."""
    _ensure_open(protocol)
    now = datetime.now(timezone.utc)
    if protocol.status == "oczekuje":
        # Podpis na papierze bez skanu: recepcja potwierdza to, co widzi.
        if method not in ("papier", "profil_zaufany"):
            raise EquipmentError(
                "Protokół nie jest jeszcze podpisany — wybierz papier albo profil zaufany."
            )
        protocol.signature_method = method
        protocol.signed_at = now
        protocol.signer_name = " ".join((signer_name or protocol.holder_name).split())[
            :200
        ]
    protocol.status = "potwierdzony"
    protocol.confirmed_by = actor.id
    protocol.confirmed_at = now
    await db.execute(
        update(EquipmentProtocolLink)
        .where(
            EquipmentProtocolLink.protocol_id == protocol.id,
            EquipmentProtocolLink.used_at.is_(None),
            EquipmentProtocolLink.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    await db.execute(
        update(EquipmentTask)
        .where(
            EquipmentTask.protocol_id == protocol.id,
            EquipmentTask.kind == "podpis",
            EquipmentTask.status == "otwarte",
        )
        .values(status="zrobione", done_at=now, done_by=actor.id)
    )
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=protocol.user_id,
        entity_type="equipment_protocol",
        entity_id=protocol.id,
        action="signature_confirmed",
        details={"method": protocol.signature_method},
    )
    return protocol


async def assignments_of_protocol(
    db: AsyncSession, protocol_id: int
) -> list[EquipmentAssignment]:
    return list(
        (
            await db.scalars(
                select(EquipmentAssignment).where(
                    (EquipmentAssignment.issue_protocol_id == protocol_id)
                    | (EquipmentAssignment.return_protocol_id == protocol_id)
                )
            )
        ).all()
    )


def protocol_filename(protocol: EquipmentProtocol, extension: str) -> str:
    stem = protocol.number.replace("/", "_")
    return f"Protokol_{stem}.{extension}"
