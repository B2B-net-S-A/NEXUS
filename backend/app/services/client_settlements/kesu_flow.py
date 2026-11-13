"""KEŚU osoby w miesiącu z plików w NEXUS-ie (roadmapa E6.3, Alior).

Pliki przychodzą na rozliczenia@ jako ``cp_documents`` rozliczanego miesiąca:

* mail z Jiry (EML z czytnika skrzynki albo MSG wgrany ręcznie) z treścią
  akceptacji, a w załącznikach KEŚU (``.xls``) i faktury kosztów;
* KEŚU jako osobny plik (``application/vnd.ms-excel``);
* odesłany PDF z podpisami (spółka, potem klient).

Faktury kosztów do paczki to PDF-y z tego samego maila co KEŚU (załączniki
pliku maila albo dokumenty z tym samym ``graph_message_id``). Podpisane
pliki to PDF-y raportu miesiąca i PDF-y w załącznikach maili odpowiedzi.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.consultant_portal import CpDocument
from app.models.contract import Contract, RateUnit
from app.services.client_order_lines import month_bounds
from app.services.client_settlements import kesu, mail_file, rcp_bnp
from app.services.client_settlements.rcp_bnp import SignatureInfo
from app.services.client_settlements.rcp_checks import ProofResult
from app.services.consultant_portal import documents as portal_documents

logger = logging.getLogger(__name__)

PDF = "application/pdf"
MAIL_MIMES = (mail_file.MSG_MIME, mail_file.EML_MIME)
#: Pliki, które mogą nieść KEŚU: sam arkusz albo mail z Jiry.
SOURCE_MIMES = (kesu.KESU_MIME, *MAIL_MIMES)


@dataclass
class Collected:
    kesu: Optional[kesu.ParsedKesu] = None
    kesu_document_id: Optional[int] = None
    jira: Optional[kesu.JiraAcceptance] = None
    signatures: list[list[SignatureInfo]] = field(default_factory=list)
    cost_pdfs: list[bytes] = field(default_factory=list)


def _read(document: CpDocument) -> Optional[bytes]:
    try:
        return portal_documents.path_for(document.file_path).read_bytes()
    except OSError as exc:
        logger.warning(
            "rozliczenia KEŚU: pliku %s nie da się odczytać (%s)",
            document.id,
            type(exc).__name__,
        )
        return None


def _is_pdf(name: str, content: bytes) -> bool:
    return content.startswith(b"%PDF") or name.lower().endswith(".pdf")


def _collect_files(
    files: list[tuple[CpDocument, bytes]], extra_costs: list[tuple[CpDocument, bytes]]
) -> Collected:
    """Praca CPU (parsery, pyHanko) poza pętlą zdarzeń. ``files`` od najnowszego."""

    found = Collected()
    source_message: Optional[str] = None
    mail_costs: Optional[list[bytes]] = None
    for document, content in files:
        if document.mime == kesu.KESU_MIME:
            parsed = kesu.parse(content)
            if parsed is not None and found.kesu is None:
                found.kesu, found.kesu_document_id = parsed, document.id
                source_message = document.graph_message_id
            continue
        if document.mime in MAIL_MIMES:
            mail = mail_file.read(content, document.mime)
            if mail is None:
                continue
            jira = kesu.parse_jira(mail.subject, mail.body)
            if jira is not None and found.jira is None:
                found.jira = jira
            sheets = [kesu.parse(a.content) for a in mail.attachments]
            sheet = next((s for s in sheets if s is not None), None)
            if sheet is not None and found.kesu is None:
                found.kesu, found.kesu_document_id = sheet, document.id
                source_message = document.graph_message_id
                mail_costs = [
                    a.content
                    for a in mail.attachments
                    if _is_pdf(a.name, a.content)
                    and not kesu.is_transport_statement(a.name)
                ]
            elif jira is None:
                # Odpowiedź klienta jako plik maila: podpisany PDF w załączniku.
                for attachment in mail.attachments:
                    if _is_pdf(attachment.name, attachment.content):
                        found.signatures.append(rcp_bnp.signatures(attachment.content))
            continue
        if document.mime == PDF:
            found.signatures.append(rcp_bnp.signatures(content))
    # KEŚU z pliku maila: faktury kosztów to jego załączniki. KEŚU jako osobny
    # plik: faktury z tego samego maila (``graph_message_id``) zapisane obok.
    found.cost_pdfs = (
        mail_costs
        if mail_costs is not None
        else [
            content
            for document, content in extra_costs
            if source_message and document.graph_message_id == source_message
        ]
    )
    return found


async def collect(db: AsyncSession, reports: list[CpDocument]) -> Collected:
    """KEŚU, akceptacja z Jiry, podpisy i faktury kosztów z plików miesiąca."""

    files = [(d, c) for d in reports if (c := _read(d)) is not None]
    message_ids = [
        d.graph_message_id for d in reports if d.graph_message_id is not None
    ]
    costs: list[tuple[CpDocument, bytes]] = []
    if message_ids:
        invoices = (
            await db.scalars(
                select(CpDocument).where(
                    CpDocument.graph_message_id.in_(message_ids),
                    CpDocument.kind == "invoice",
                    CpDocument.mime == PDF,
                    CpDocument.status != "rejected",
                )
            )
        ).all()
        costs = [
            (d, c)
            for d in invoices
            if not kesu.is_transport_statement(d.file_name or "")
            and (c := _read(d)) is not None
        ]
    return await asyncio.to_thread(_collect_files, files, costs)


def has_source(reports: list[CpDocument]) -> bool:
    return any(d.mime in SOURCE_MIMES for d in reports)


def md_hours(rules: dict[str, dict[str, Any]]) -> Decimal:
    raw = str(rules["fields.md_hours"]["params"].get("hours") or "8").replace(",", ".")
    try:
        value = Decimal(raw)
    except ArithmeticError:
        return Decimal("8")
    return value if value > 0 else Decimal("8")


async def contract_rate_md(
    db: AsyncSession, contract_id: int, month: str, *, per_md: Decimal
) -> Optional[Decimal]:
    """Stawka klienta z kontraktu na MD w zł: godzinowa × godziny MD, dzienna wprost.

    Stawka miesięczna i waluta inna niż zł nie dają stawki MD do KEŚU.
    """

    contract = await db.scalar(
        select(Contract)
        .options(selectinload(Contract.client_rate_schedule))
        .where(Contract.id == contract_id)
    )
    if contract is None or contract.resolved_rate_client_currency != "PLN":
        return None
    first, _last = month_bounds(month)
    raw = contract.effective_client_rate(first)
    if raw is None:
        return None
    unit = RateUnit(contract.rate_unit)
    if unit == RateUnit.hourly:
        return (Decimal(str(raw)) * per_md).quantize(Decimal("0.01"))
    if unit == RateUnit.daily:
        return Decimal(str(raw)).quantize(Decimal("0.01"))
    return None


async def proof(
    db: AsyncSession,
    reports: list[CpDocument],
    *,
    contract_id: int,
    month: str,
    person_name: str,
    order_rate_md: Optional[Decimal],
    rules: dict[str, dict[str, Any]],
) -> Optional[ProofResult]:
    """Kontrole KEŚU; ``None``, gdy w plikach miesiąca nie ma KEŚU."""

    found = await collect(db, reports)
    if found.kesu is None:
        return None
    rates = kesu.Rates(
        contract_md=await contract_rate_md(
            db, contract_id, month, per_md=md_hours(rules)
        ),
        order_md=None if order_rate_md is None else Decimal(order_rate_md),
    )
    result = kesu.evaluate(
        found.kesu,
        month=month,
        person_name=person_name,
        jira=found.jira,
        signatures=found.signatures,
        rates=rates,
        cost_invoices=len(found.cost_pdfs),
        rules=rules,
    )
    result.meta["kesu"]["document_id"] = found.kesu_document_id
    return result


async def package(
    db: AsyncSession,
    reports: list[CpDocument],
    *,
    contract_id: int,
    month: str,
    rules: dict[str, dict[str, Any]],
    order_rate_md: Optional[Decimal],
) -> Optional[bytes]:
    """PDF do podpisu spółki: KEŚU ze stawką, za nim faktury kosztów."""

    found = await collect(db, reports)
    if found.kesu is None:
        return None
    per_md = md_hours(rules)
    rate = await contract_rate_md(db, contract_id, month, per_md=per_md)
    if rate is None:
        rate = None if order_rate_md is None else Decimal(order_rate_md)
    if rate is None:
        return None
    html = kesu.render_html(found.kesu, rate_md=rate, md_hours=per_md, month=month)

    def _build() -> bytes:
        return kesu.merge_pdfs(kesu.render_pdf(html), found.cost_pdfs)

    return await asyncio.to_thread(_build)
