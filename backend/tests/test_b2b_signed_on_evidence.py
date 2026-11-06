"""Dzień podpisu umowy B2B z podpisu konsultanta w pliku (decyzja Artura 06.11.2026).

Bez bazy: prawdziwy PDF podpisany pyHanko w teście (``tests/_signed_pdf``).
Przypadek z 06.11.2026: DL oznaczył podpis 30.10, konsultant podpisał 02.11.2026 07:32 —
dzień z pliku ma wygrać z dniem kliknięcia. Dane fikcyjne.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from fastapi import HTTPException

pytest.importorskip("pyhanko")

from app.services.b2b_contract_generator import signed_on_evidence as evidence  # noqa: E402
from tests._signed_pdf import blank_pdf, signed_by  # noqa: E402

CONSULTANT_AT = datetime(2026, 11, 2, 6, 32, tzinfo=timezone.utc)  # 07:32 w Warszawie
COMPANY_AT = datetime(2026, 11, 3, 9, 0, tzinfo=timezone.utc)


async def _entries(data: bytes, *, partner: str = "Jan Przykładowy"):
    found = await evidence.read_pdf_signatures(data)
    if found is None:
        return None
    return evidence.classify(
        found, partner_name=partner, company_names=["Anna Reprezentant"]
    )


@pytest.mark.asyncio
async def test_reads_signers_and_times_from_a_signed_pdf() -> None:
    data = await signed_by(
        ("Jan Piotr Przykładowy", CONSULTANT_AT), ("Anna Reprezentant", COMPANY_AT)
    )
    entries = await _entries(data)
    assert [(e.signer, e.party, e.intact) for e in entries] == [
        ("Jan Piotr Przykładowy", "consultant", True),
        ("Anna Reprezentant", "company", True),
    ]
    assert entries[0].signed_at == CONSULTANT_AT
    assert entries[0].time_source == "declared"


@pytest.mark.asyncio
async def test_consultant_signature_sets_the_day_in_warsaw() -> None:
    entries = await _entries(
        await signed_by(
            ("Anna Reprezentant", COMPANY_AT), ("Jan Przykładowy", CONSULTANT_AT)
        )
    )
    # Ręczna data z okna (30.10) nie liczy się, gdy plik ma podpis konsultanta.
    result = evidence.resolve(entries, manual_on=date(2026, 10, 30), reason=None)
    assert result.source == "pdf"
    assert result.signed_on == date(2026, 11, 2)
    assert result.consultant_signed_at == CONSULTANT_AT


@pytest.mark.asyncio
async def test_late_evening_utc_signature_is_next_day_in_warsaw() -> None:
    late = datetime(2026, 10, 31, 23, 30, tzinfo=timezone.utc)  # 1.11 00:30
    entries = await _entries(await signed_by(("Jan Przykładowy", late)))
    assert evidence.resolve(entries, manual_on=None, reason=None).signed_on == date(
        2026, 11, 1
    )


@pytest.mark.asyncio
async def test_pdf_without_the_consultant_signature_is_refused() -> None:
    entries = await _entries(await signed_by(("Anna Reprezentant", COMPANY_AT)))
    with pytest.raises(HTTPException) as error:
        evidence.resolve(entries, manual_on=date(2026, 11, 2), reason="odręczny")
    assert error.value.status_code == 422
    assert evidence.MSG_NO_CONSULTANT in error.value.detail
    assert "Anna Reprezentant" in error.value.detail
    assert evidence.preview(entries)["mode"] == "blocked"


@pytest.mark.asyncio
async def test_tampered_consultant_signature_is_refused() -> None:
    data = bytearray(await signed_by(("Jan Przykładowy", CONSULTANT_AT)))
    # Zmiana bajtu w treści objętej podpisem (nagłówek strony) psuje skrót.
    index = bytes(data).index(b"/MediaBox")
    data[index + 1] = ord("N")
    entries = await _entries(bytes(data))
    assert entries is not None and entries[0].party == "consultant"
    assert entries[0].intact is False
    with pytest.raises(HTTPException) as error:
        evidence.resolve(entries, manual_on=None, reason=None)
    assert error.value.detail == evidence.MSG_CONSULTANT_BROKEN


@pytest.mark.asyncio
async def test_scan_without_electronic_signature_needs_date_and_reason() -> None:
    entries = await _entries(blank_pdf())
    assert entries == []
    assert evidence.preview(entries)["mode"] == "manual"
    with pytest.raises(HTTPException) as no_date:
        evidence.resolve(entries, manual_on=None, reason="podpis odręczny")
    assert no_date.value.detail == evidence.MSG_MANUAL_DATE
    with pytest.raises(HTTPException) as no_reason:
        evidence.resolve(entries, manual_on=date(2026, 10, 9), reason="  ")
    assert no_reason.value.detail == evidence.MSG_MANUAL_REASON
    result = evidence.resolve(
        entries, manual_on=date(2026, 10, 9), reason=" podpis  odręczny 09.10 "
    )
    assert (result.source, result.signed_on, result.reason) == (
        "manual",
        date(2026, 10, 9),
        "podpis odręczny 09.10",
    )


@pytest.mark.asyncio
async def test_image_scan_has_no_signatures() -> None:
    assert await evidence.read_pdf_signatures(b"\x89PNG\r\n\x1a\nxxxx") == []


@pytest.mark.asyncio
async def test_broken_pdf_is_unreadable() -> None:
    assert await evidence.read_pdf_signatures(b"%PDF-1.7\nto nie jest pdf") is None
    with pytest.raises(HTTPException) as error:
        evidence.resolve(None, manual_on=date(2026, 11, 2), reason="odręczny")
    assert error.value.detail == evidence.MSG_NOT_READABLE


def test_name_without_common_name_uses_given_name_and_surname() -> None:
    assert (
        evidence._common_name("Given Name: Jan, Surname: Kowalski, Country: PL")
        == "Jan Kowalski"
    )
    assert evidence._common_name("Common Name: Jan Kowalski, Country: PL") == (
        "Jan Kowalski"
    )


def test_preview_reports_consultant_day() -> None:
    entries = [
        evidence.SignatureEntry(
            signer="Jan Przykładowy",
            signed_at=CONSULTANT_AT,
            time_source="timestamp",
            intact=True,
            party="consultant",
        )
    ]
    payload = evidence.preview(entries)
    assert payload["mode"] == "pdf"
    assert payload["consultant_signed_on"] == "2026-11-02"
