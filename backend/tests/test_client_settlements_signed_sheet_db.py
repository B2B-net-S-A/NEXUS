"""Podpisany arkusz zbiorczy klienta przy rozliczeniu osoby (E6.2). Dane fikcyjne.

Próba IX–X 2026 na kopii produkcji (24.11): przy kliencie z arkuszami zbiorczymi
żadne rozliczenie z MD nie przeszło samo, bo stały przy nim dwie fałszywe uwagi.

* „Arkusz czeka na podpis klienta” (``pay.per_person``). Podpisane arkusze wróciły
  od klienta, ale rozpoznawanie szukało ich tylko od miesiąca, od którego NEXUS sam
  robi arkusz (``cl.client_document`` „od miesiąca”). Zapłata czekała na arkusz od
  początku reguł. Do tego arkusz z drugiego strumienia klienta („Nazwisko Imię …
  Okres od … MD.”, plik „B2B_09_2026.pdf”) nie ma w nazwie słowa „arkusz”, więc szedł
  jako faktura i nikt go nie czytał.
* „Brak maila z akceptacją godzin” (``proof.excel_with_mail``: Excel z mailem
  akceptującym usługi, gdy brak podpisu). Podpis klienta na arkuszu z MD osoby to
  akceptacja jej usług.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import local_now
from app.models.client_settlement import ClientSettlement
from app.models.consultant_portal import CpDocument
from app.models.contract import Contract
from app.services.client_settlements import signoffs
from app.services.consultant_portal import documents
from app.services.consultant_portal.mailbox import kind_of_file
from tests.test_client_settlements_client_invoice_db import _month, _rules
from tests.test_client_settlements_consultant_db import _module, _restore
from tests.test_client_settlements_pko_velo import _plain_pdf, _signed_pdf
from tests.test_client_settlements_pko_velo_db import (
    _drop_documents,
    _person,
    _store,
    _titles,
)
from tests.test_client_settlements_service_db import _cleanup, _world
from tests.test_client_settlements_timesheet_db import _timesheet

pytestmark = pytest.mark.asyncio

WAITS = "Arkusz czeka na podpis klienta"
NO_MAIL = "Brak maila z akceptacją godzin"
BY_SIGNATURE = "Godziny zaakceptowane podpisem klienta na arkuszu zbiorczym"


def _sheet_rules(**changes: dict) -> dict:
    rules = {
        "proof.month": {"level": "block", "params": {}},
        "proof.excel_with_mail": {"level": "warn", "params": {"domain": ""}},
        "proof.name_match": {"level": "off", "params": {}},
        "pay.per_person": {"level": "block", "params": {}},
        "cl.client_document": {
            "level": "warn",
            "params": {"kind": "Arkusz zbiorczy", "per": "podpisujący", "from": ""},
        },
    }
    rules.update(changes)
    return rules


def _sheet_lines(person: str, month: str, md: str) -> list[str]:
    year, mon = (int(x) for x in month.split("-"))
    return [
        "Nazwisko i imie Rodzaj kompetencji (profil) Zlecenie od Zlecenie do Liczba MD",
        f"{person} Tester 01-{mon:02d}-{year} 28-{mon:02d}-{year} {md}",
    ]


async def _settlement(contract_id: int, month: str) -> ClientSettlement:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(ClientSettlement).where(
                ClientSettlement.contract_id == contract_id,
                ClientSettlement.period_month == month,
                ClientSettlement.kind == "actual",
            )
        )


async def _document(document_id: int) -> CpDocument:
    async with AsyncSessionLocal() as db:
        return await db.get(CpDocument, document_id)


async def _with_time_sheet(contract_id: int, month: str) -> ClientSettlement:
    days = list(range(1, 18))  # 17 dni po 8 h = 17 MD
    await _store(
        contract_id,
        month,
        _timesheet(month, [(d, "ALFA", "Praca", 8, None) for d in days]),
        "Time Sheet.xlsx",
    )
    return await _settlement(contract_id, month)


@pytest.fixture
def _storage(tmp_path, monkeypatch):
    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)


@pytest.mark.usefixtures("_storage")
async def test_arkusz_rozpoznany_przed_miesiacem_arkusza_z_nexusa() -> None:
    """Zapłata czeka na podpisany arkusz od początku reguł, a NEXUS robi arkusz
    dopiero od przyszłego miesiąca: podpisany arkusz od klienta i tak trafia do osoby."""

    client_id, contract_id, _line = await _world(md_total="60")
    month = _month(-1)
    previous = await _module(True)
    stored: list[int] = []
    try:
        later = {"kind": "Arkusz zbiorczy", "per": "podpisujący", "from": _month(1)}
        await _rules(
            client_id,
            _sheet_rules(
                **{
                    "proof.excel_with_mail": {"level": "off", "params": {}},
                    "cl.client_document": {"level": "warn", "params": later},
                }
            ),
        )
        s = await _with_time_sheet(contract_id, month)
        assert _titles(s)[WAITS] == "fail"

        lines = _sheet_lines(await _person(contract_id), month, "17")
        pdf = await asyncio.to_thread(_signed_pdf, lines, 1)
        document = await _store(None, month, pdf, "Arkusz podpisany.pdf")
        stored.append(document.id)

        again = await _document(document.id)
        assert again.contract_id is None and again.status == "accepted"
        s = await _settlement(contract_id, month)
        assert signoffs.is_complete(s.checks, signoffs.SHEET)
        assert WAITS not in _titles(s)
    finally:
        await _restore(previous)
        await _drop_documents(stored)
        await _cleanup(client_id)


@pytest.mark.usefixtures("_storage")
async def test_podpisany_arkusz_zastepuje_mail_z_akceptacja_godzin() -> None:
    client_id, contract_id, _line = await _world(md_total="60")
    month = _month(-1)
    previous = await _module(True)
    stored: list[int] = []
    try:
        await _rules(client_id, _sheet_rules())
        s = await _with_time_sheet(contract_id, month)
        assert _titles(s)[NO_MAIL] == "warn"

        lines = _sheet_lines(await _person(contract_id), month, "17")
        pdf = await asyncio.to_thread(_signed_pdf, lines, 1)
        document = await _store(None, month, pdf, "Arkusz podpisany.pdf")
        stored.append(document.id)

        s = await _settlement(contract_id, month)
        titles = _titles(s)
        assert NO_MAIL not in titles and WAITS not in titles
        assert titles[BY_SIGNATURE] == "ok"
        assert s.status == "ok"
    finally:
        await _restore(previous)
        await _drop_documents(stored)
        await _cleanup(client_id)


@pytest.mark.usefixtures("_storage")
async def test_inne_md_w_podpisanym_arkuszu_zostaja_uwaga() -> None:
    """Podpis jest, ale klient podpisał inną liczbę MD: akceptacja jest, liczby do
    sprawdzenia przez człowieka."""

    client_id, contract_id, _line = await _world(md_total="60")
    month = _month(-1)
    previous = await _module(True)
    stored: list[int] = []
    try:
        await _rules(client_id, _sheet_rules())
        await _with_time_sheet(contract_id, month)

        lines = _sheet_lines(await _person(contract_id), month, "15")
        pdf = await asyncio.to_thread(_signed_pdf, lines, 1)
        document = await _store(None, month, pdf, "Arkusz podpisany.pdf")
        stored.append(document.id)

        s = await _settlement(contract_id, month)
        titles = _titles(s)
        assert NO_MAIL not in titles
        assert titles["W arkuszu 15 MD, w Time Sheet 17 MD"] == "warn"
        assert s.status == "warnings"
    finally:
        await _restore(previous)
        await _drop_documents(stored)
        await _cleanup(client_id)


@pytest.mark.usefixtures("_storage")
async def test_arkusz_bez_podpisu_niczego_nie_zmienia() -> None:
    client_id, contract_id, _line = await _world(md_total="60")
    month = _month(-1)
    previous = await _module(True)
    stored: list[int] = []
    try:
        await _rules(client_id, _sheet_rules())
        await _with_time_sheet(contract_id, month)

        lines = _sheet_lines(await _person(contract_id), month, "17")
        document = await _store(None, month, _plain_pdf(lines), "Arkusz.pdf")
        stored.append(document.id)

        assert (await _document(document.id)).status == "received"
        s = await _settlement(contract_id, month)
        titles = _titles(s)
        assert titles[NO_MAIL] == "warn" and titles[WAITS] == "fail"
        assert signoffs.marker(s.checks) is None
    finally:
        await _restore(previous)
        await _drop_documents(stored)
        await _cleanup(client_id)


@pytest.mark.usefixtures("_storage")
@pytest.mark.parametrize("source", ["panel", "adres osoby", "podpis osoby"])
async def test_arkusz_od_samej_osoby_nie_zastepuje_maila(source: str) -> None:
    """Podpisu nie sprawdzamy łańcuchem zaufania, więc arkusz z panelu konsultanta,
    z jego adresu albo podpisany jego nazwiskiem nie jest akceptacją klienta (#3884)."""

    client_id, contract_id, _line = await _world(md_total="60")
    month = _month(-1)
    year, mon = (int(x) for x in month.split("-"))
    previous = await _module(True)
    stored: list[int] = []
    try:
        await _rules(client_id, _sheet_rules())
        await _with_time_sheet(contract_id, month)
        person = await _person(contract_id)
        lines = _sheet_lines(person, month, "17")
        signer = person if source == "podpis osoby" else None
        pdf = await asyncio.to_thread(_signed_pdf, lines, 1, signer)
        if source == "panel":
            document = await _store(contract_id, month, pdf, "Arkusz.pdf")
        elif source == "podpis osoby":
            document = await _store(None, month, pdf, "Arkusz.pdf")
        else:
            address = f"osoba-{uuid.uuid4().hex[:8]}@klient.example"
            async with AsyncSessionLocal() as db:
                contract = await db.get(Contract, contract_id)
                contract.candidate_email = address
                saved = await documents.store(
                    db,
                    contract_id=None,
                    kind="report",
                    year=year,
                    month=mon,
                    content=pdf,
                    file_name="Arkusz.pdf",
                    channel="mailbox",
                    now=local_now(),
                    sender_email=address,
                )
                await db.commit()
            document = saved.document
        stored.append(document.id)

        s = await _settlement(contract_id, month)
        assert signoffs.is_complete(s.checks, signoffs.SHEET)
        assert not signoffs.client_signed(s.checks, signoffs.SHEET)
        titles = _titles(s)
        assert titles[NO_MAIL] == "warn" and BY_SIGNATURE not in titles
        assert s.status == "warnings"
    finally:
        await _restore(previous)
        await _drop_documents(stored)
        await _cleanup(client_id)


@pytest.mark.usefixtures("_storage")
async def test_arkusz_klienta_bez_slowa_arkusz_w_nazwie_pliku() -> None:
    """Wzór klienta „Nazwisko Imię … Okres od … MD.” w pliku „B2B_MM_RRRR.pdf”
    z tematem „[BL] Rozliczenie MM.RRRR”: przekazany przez naszego opiekuna, bez osoby."""

    client_id, contract_id, _line = await _world(md_total="60")
    month = _month(-1)
    year, mon = (int(x) for x in month.split("-"))
    previous = await _module(True)
    stored: list[int] = []
    try:
        await _rules(client_id, _sheet_rules())
        await _with_time_sheet(contract_id, month)

        person = (await _person(contract_id)).upper()
        lines = [
            "Dostawca B2B",
            "Nazwisko Imie Stanowisko Okres od: Okres do: MD.",
            f"{person} INZYNIER TESTOW {year}-{mon:02d}-01 {year}-{mon:02d}-28 17,00",
            f"Suma koncowa {year}-{mon:02d}-01 {year}-{mon:02d}-28 17,00",
        ]
        pdf = await asyncio.to_thread(_signed_pdf, lines, 1)
        name = f"B2B_{mon:02d}_{year}.pdf"
        kind = kind_of_file(
            f"FW: [BL] Rozliczenie {mon:02d}.{year} [ABC] [B2B]", name, pdf
        )
        assert kind == "report"
        async with AsyncSessionLocal() as db:
            saved = await documents.store(
                db,
                contract_id=None,
                kind=kind,
                year=year,
                month=mon,
                content=pdf,
                file_name=name,
                channel="mailbox",
                now=local_now(),
            )
            await db.commit()
        stored.append(saved.document.id)

        s = await _settlement(contract_id, month)
        assert signoffs.client_signed(s.checks, signoffs.SHEET)
        titles = _titles(s)
        assert WAITS not in titles and NO_MAIL not in titles
    finally:
        await _restore(previous)
        await _drop_documents(stored)
        await _cleanup(client_id)
