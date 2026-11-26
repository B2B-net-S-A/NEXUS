"""Faktura z przekazanym wątkiem od osoby pracującej u dwóch klientów.

Konsultant z kontraktem w Banku Pocztowym i VeloBanku wysyła z adresu firmy
fakturę razem z przekazanym wątkiem ze skrzynki w jednym z banków. Wątek
wskazywał kontrakt tego banku, więc faktura trafiała do niego sama, choć bywa
jedna na oba kontrakty (poczta za VII 2026). Czeka na człowieka, a pozostałe
pliki i treść maila zostają jak dotąd.

Osoby, adresy i numery fikcyjne.
"""

from __future__ import annotations

from datetime import timedelta
from email.message import EmailMessage

import pytest
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.client_settlement import ClientSettlementRuleSet
from app.models.contract import ContractStatus
from tests.care_announcements_seed import care_on, tag  # noqa: F401  (fixture)
from tests.consultant_portal_seed import (  # noqa: F401  (fixture'y)
    make_person,
    portal_restored,
)
from tests.test_consultant_portal_internal import (  # noqa: F401  (fixture'y)
    FakeMailbox,
    _attachment,
    _message,
    _quiet_documents,
    _read,
    _storage,
    company_domain,
    internal,
)
from tests.test_consultant_portal_template_mail_db import (
    COMPANY_DOMAIN,
    INVOICE,
    VELO_DOMAIN,
    _Thread,
    _card,
    _contract,
    _month_start,
    _owners,
    _sheet,
    _two_banks,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.usefixtures("care_on", "internal", "company_domain"),
]

COORDINATOR = f"koordynator@{COMPANY_DOMAIN}"


def _invoice() -> dict:
    """Numer faktury niesie miesiąc wystawienia („FV1_8_2026” za VII)."""

    today = business_today()
    return _attachment(f"Faktura_FV1_{today.month}_{today.year}.pdf", INVOICE)


def _velo_box(person) -> str:
    return f"{person.first.lower()}.{person.last.lower()}@{VELO_DOMAIN}"


async def _read_thread(sender: str, quoted_from: str, *files: dict) -> dict:
    reader = _Thread([_message("m1", sender)], {"m1": list(files)}, quoted_from)
    await _read(reader)
    return await _owners()


async def test_faktura_z_watkiem_z_jednego_banku_czeka_na_czlowieka(
    monkeypatch,
) -> None:
    person = await _two_banks(monkeypatch)
    month = _month_start()
    invoice = _invoice()
    card = _card(person.on_card, month)
    sheet = _sheet(person.on_sheet, month)

    owners = await _read_thread(person.alias, _velo_box(person), invoice, card, sheet)

    assert owners == {
        invoice["name"]: None,
        card["name"]: person.bank.contract_id,
        sheet["name"]: person.velo.contract_id,
    }


async def test_faktura_od_koordynatora_z_watkiem_konsultanta_czeka(
    monkeypatch,
) -> None:
    """Nadawca nikogo nie wskazuje, a skrzynka z wątku wskazuje jeden bank."""

    person = await _two_banks(monkeypatch)
    invoice = _invoice()

    owners = await _read_thread(COORDINATOR, _velo_box(person), invoice)

    assert owners == {invoice["name"]: None}


async def test_faktura_po_zmianie_klienta_z_watkiem_czeka(monkeypatch) -> None:
    """Kontrakt w banku zakończony przed miesiącem działa jeszcze 60 dni, a ostatnia
    faktura za niego przychodzi po końcu: wątek z VeloBanku jej nie wybiera."""

    person = await _two_banks(monkeypatch)
    await _contract(
        person.bank.contract_id,
        status=ContractStatus.ended,
        end_date=_month_start() - timedelta(days=1),
    )
    invoice = _invoice()

    owners = await _read_thread(person.alias, _velo_box(person), invoice)

    assert owners == {invoice["name"]: None}


async def test_faktura_nie_idzie_do_osoby_z_cudzego_watku(monkeypatch) -> None:
    """Adresy nadawcy nie rozstrzygają, a w wątku pisze kolega z jednym kontraktem:
    faktura osoby u dwóch klientów nie przechodzi na niego."""

    person = await _two_banks(monkeypatch)
    colleague = await make_person(activated=False)
    invoice = _invoice()

    owners = await _read_thread(person.alias, colleague.email, invoice)

    assert owners == {invoice["name"]: None}


async def test_faktura_osoby_z_jednym_dzialajacym_kontraktem_idzie_z_watku(
    monkeypatch,
) -> None:
    """Kontrakt zakończony dawniej niż 60 dni temu się nie liczy: jak dotąd."""

    person = await _two_banks(monkeypatch)
    await _contract(
        person.bank.contract_id,
        status=ContractStatus.ended,
        end_date=business_today() - timedelta(days=90),
    )
    invoice = _invoice()

    owners = await _read_thread(COORDINATOR, _velo_box(person), invoice)

    assert owners == {invoice["name"]: person.velo.contract_id}


async def test_raport_bez_wzoru_dalej_idzie_z_watku(monkeypatch) -> None:
    """Reguła dotyczy tylko faktury: raport bez wzoru klienta bierze kontrakt wątku."""

    person = await _two_banks(monkeypatch)
    report = _attachment(
        f"Raport godzin {_month_start():%m.%Y}.pdf", b"%PDF-1.4 fikcyjny raport"
    )

    owners = await _read_thread(person.alias, _velo_box(person), report)

    assert owners == {report["name"]: person.velo.contract_id}


class _Accepted(FakeMailbox):
    """Przekazany wątek, w którym kierownik z banku potwierdza godziny."""

    def __init__(self, messages, files, quoted_from: str) -> None:
        super().__init__(messages, files)
        mail = EmailMessage()
        mail["From"] = f"ktos@{COMPANY_DOMAIN}"
        mail["Subject"] = "Faktura"
        mail.set_content(
            "Przesyłam fakturę.\n\n"
            f"From: Konsultant <{quoted_from}>\nSubject: akceptacja\n\nProszę o OK.\n\n"
            f"From: Kierownik <kierownik@{VELO_DOMAIN}>\n"
            "Sent: Monday, October 5, 2026 11:02 AM\n"
            "Subject: ODP: akceptacja\n\nPotwierdzam\n"
        )
        self.raw = mail.as_bytes()

    async def mime(self, message_id):
        return self.raw


async def test_tresc_maila_z_sama_faktura_dalej_trafia_do_kontraktu_z_watku(
    monkeypatch,
) -> None:
    """Faktura czeka, ale mail z akceptacją kierownika to dalej dowód godzin."""

    person = await _two_banks(monkeypatch)
    rules = {
        "proof.excel_with_mail": {"level": "warn", "params": {"domain": VELO_DOMAIN}}
    }
    async with AsyncSessionLocal() as db:
        db.add(
            ClientSettlementRuleSet(
                client_id=person.velo.client_id, effective_from="2026-01", rules=rules
            )
        )
        await db.commit()
    subject = f"Faktura {tag()}"
    message = _message("m1", person.alias)
    message["subject"] = subject
    invoice = _invoice()
    try:
        await _read(_Accepted([message], {"m1": [invoice]}, _velo_box(person)))

        assert await _owners() == {
            invoice["name"]: None,
            f"{subject}.eml": person.velo.contract_id,
        }
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(ClientSettlementRuleSet).where(
                    ClientSettlementRuleSet.client_id == person.velo.client_id
                )
            )
            await db.commit()
