"""Plik umowy z ludźmi: DOCX z wersji wzoru i PDF tym samym mechanizmem co protokoły.

Pola (``agreements_templates.FIELDS``) liczą się z wiersza umowy, dopóki jest
szkicem; przy wysyłce do podpisu albo ręcznym podpisie wartości zamrażają się
w ``hr_agreements.document_fields`` — dokument wysłany i podpisany to ten sam
dokument, nawet gdy ktoś później zmieni nazwisko koordynatora w kartotece.

PDF: ``cv_pdf_preview.pdf_from_docx`` (LibreOffice w kontenerze, kolejka,
limit czasu). Brak LibreOffice = ``AgreementUnavailable`` (503), a DOCX dalej
da się pobrać.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_agreement import HrAgreement
from app.models.user import User
from app.services import cv_pdf_preview
from app.services.b2b_contract_generator.number_words import pln_words_with_fraction
from app.services.hr import agreements_templates as templates
from app.services.hr.agreements_errors import AgreementUnavailable

#: Forma współpracy słownie do pola ``employment_form`` (bez treści prawnej).
FORM_WORDS: dict[str, str] = {
    "b2b": "umowa B2B",
    "zlecenie": "umowa zlecenia",
    "uop": "umowa o pracę",
}


def pl_date(value: Optional[date]) -> str:
    return "" if value is None else f"{value.day:02d}.{value.month:02d}.{value.year}"


def rate_text(value: Decimal) -> str:
    """Stawka jak w umowach: „1 234,50” (spacja tysięcy, przecinek)."""

    whole, _, fraction = f"{value.quantize(Decimal('0.01')):.2f}".partition(".")
    groups: list[str] = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    groups.insert(0, whole)
    return " ".join(groups) + "," + fraction


async def _names(db: AsyncSession, ids: set[Optional[int]]) -> dict[int, str]:
    wanted = [value for value in ids if value is not None]
    if not wanted:
        return {}
    rows = await db.execute(select(User.id, User.name).where(User.id.in_(wanted)))
    return {row.id: row.name or "" for row in rows}


async def context_for(db: AsyncSession, agreement: HrAgreement) -> dict[str, Any]:
    """Wartości pól wzoru — zamrożone po wysyłce, liczone na żywo w szkicu."""

    if agreement.document_fields:
        return dict(agreement.document_fields)
    names = await _names(db, {agreement.user_id, agreement.coordinator_user_id})
    base_date: Optional[date] = None
    if agreement.base_agreement_id is not None:
        base_date = await db.scalar(
            select(HrAgreement.agreement_date).where(
                HrAgreement.id == agreement.base_agreement_id
            )
        )
    rate = Decimal(agreement.hourly_rate)
    return {
        "person_name": names.get(agreement.user_id, ""),
        "employment_form": FORM_WORDS[agreement.employment_type],
        "rate": rate_text(rate),
        "rate_words": (
            pln_words_with_fraction(float(rate)) if agreement.currency == "PLN" else ""
        ),
        "currency": agreement.currency,
        "rate_basis": "netto" if agreement.employment_type == "b2b" else "brutto",
        "start_date": pl_date(agreement.start_date),
        "end_date": pl_date(agreement.end_date),
        "indefinite": agreement.end_date is None,
        "hours_confirmation": bool(agreement.hours_confirmation),
        "payout_day": agreement.payout_day if agreement.payout_day is not None else "",
        "coordinator_name": names.get(agreement.coordinator_user_id or 0, ""),
        "agreement_date": pl_date(agreement.agreement_date),
        "base_agreement_date": pl_date(base_date),
    }


async def render_docx(db: AsyncSession, agreement: HrAgreement) -> bytes:
    content = await templates.version_content(db, agreement.template_version_id)
    return templates.render(content, await context_for(db, agreement))


async def pdf_from_docx(document: bytes) -> bytes:
    try:
        return await cv_pdf_preview.pdf_from_docx(document)
    except cv_pdf_preview.PdfPreviewUnavailable as exc:
        raise AgreementUnavailable(
            "PDF umowy jest chwilowo niedostępny — pobierz plik Word albo spróbuj za chwilę."
        ) from exc


async def render_pdf(db: AsyncSession, agreement: HrAgreement) -> bytes:
    return await pdf_from_docx(await render_docx(db, agreement))


def file_stem(agreement: HrAgreement, person_name: str) -> str:
    """Nazwa pliku bez polskich znaków: ``Umowa_zlecenia_Anna_Przykladowa_2026-11-01``."""

    label = (
        "Aneks"
        if agreement.kind == "annex"
        else templates.KIND_LABELS[agreement.employment_type]
    )
    raw = f"{label} {person_name} {agreement.start_date.isoformat()}"
    table = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")
    cleaned = "".join(
        char if char.isalnum() or char in "-" else "_" for char in raw.translate(table)
    )
    return "_".join(part for part in cleaned.split("_") if part)[:120] or "umowa"


__all__ = [
    "FORM_WORDS",
    "context_for",
    "file_stem",
    "pdf_from_docx",
    "pl_date",
    "rate_text",
    "render_docx",
    "render_pdf",
]
