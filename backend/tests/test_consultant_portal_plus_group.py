"""Raport godzin Polkomtelu albo Cyfrowego Polsatu wybiera kontrakt (próba IX–X 2026).

Konsultanci grupy mają dwa działające kontrakty, po jednym w każdej spółce: ta sama
data startu, zamówienia każdej spółki osobno (Polkomtel 471 / Cyfrowy Polsat 633,
577 / 634). To celowy podział, nie duplikat (decyzja Artura z 23.11.2026), więc nadawca
nie rozstrzyga i do 23.11 raport czekał na ręczne przypisanie. Rozstrzyga plik:

- arkusz Polsatu („B2B_RRRR_MM.xls”) ma w wierszu numer zamówienia → kontrakt
  z linią tego zamówienia (CP 634 X: kierowniczka u klienta z ``plus.pl``);
- „Project timesheet Report” Polkomtelu prawie zawsze bez numeru zlecenia → kontrakt
  osoby u Polkomtelu, a wpisany numer wygrywa (Polkomtel 471 IX i X: konsultant
  przekazuje raport ze skrzynki firmowej).

Dane fikcyjne.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import update

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup
from app.services.consultant_portal import identity
from tests.care_announcements_seed import care_on, tag  # noqa: F401  (fixture)
from tests.consultant_portal_seed import (  # noqa: F401  (fixture'y)
    make_person,
    portal_restored,
)
from tests.test_client_settlements_timesheet_plus import (
    polkomtel_html,
    polsat_xlsx,
    polsat_xml,
)
from tests.test_consultant_portal_internal import (  # noqa: F401  (fixture'y)
    FakeMailbox,
    _attachment,
    _documents,
    _message,
    _quiet_documents,
    _read,
    _storage,
    internal,
)
from tests.test_consultant_portal_two_clients import (
    GROUP_DOMAIN,
    _nip,
    _nip_for_test,
    _person_at_two_clients,
    _registry,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.usefixtures("care_on", "internal"),
]

COMPANY = "firma-testowa.example"


@pytest.fixture(autouse=True)
def _company_domain(monkeypatch):
    # Adres rozliczeń w ustawieniach przy osobnych skrzynkach zatrzymuje czytnik
    # („route_not_shared”), więc domenę firmy podajemy wprost.
    monkeypatch.setattr(identity, "_company_domains", lambda: frozenset({COMPANY}))


async def _order(contract_id: int, client_id: int, number: str) -> None:
    start = business_today() - timedelta(days=120)
    async with AsyncSessionLocal() as db:
        group = ClientOrderGroup(
            client_id=client_id,
            order_number=number,
            start_date=start,
            order_type="md",
            md_budget_mode="per_person",
            status="active",
        )
        db.add(group)
        await db.flush()
        db.add(
            ClientOrder(
                client_id=client_id,
                contract_id=contract_id,
                order_group_id=group.id,
                title=f"Zamówienie {number}",
                status=ClientOrderStatus.active,
                start_date=start,
            )
        )
        await db.commit()


async def _group_person(monkeypatch, last: str):
    """Osoba z kontraktem w „Polkomtelu” (``plk``) i w „Polsacie” (``cp``)."""

    plk, cp = await _person_at_two_clients("Jan", last)
    nip_plk, nip_cp = _nip_for_test(), _nip_for_test()
    await _nip(plk.client_id, nip_plk)
    await _nip(cp.client_id, nip_cp)
    _registry(
        monkeypatch,
        {GROUP_DOMAIN: "polkomtel"},
        {"polkomtel": (nip_plk,), "cyfrowy_polsat": (nip_cp,)},
        shared={GROUP_DOMAIN: ("polkomtel", "cyfrowy_polsat")},
    )
    await _order(plk.contract_id, plk.client_id, f"SAP 45{tag()}")
    number = f"Z{tag()}"
    await _order(cp.contract_id, cp.client_id, f"CP {number}")
    return plk, cp, number


def _mail(sender: str, files: list[dict], subject: str) -> FakeMailbox:
    message = {**_message("m1", sender), "subject": subject}
    return FakeMailbox([message], {"m1": files})


async def test_polsat_sheet_from_client_goes_to_contract_of_its_order(
    monkeypatch,
) -> None:
    """CP 634 X: „Rozliczenie za 10.2026” z ``B2B_2026_10.xls`` od kierowniczki."""

    last = f"Testowy{tag()}"
    _, cp, number = await _group_person(monkeypatch, last)
    sheet = polsat_xml([(f"{last} Jan", number, "80", {d: "8" for d in range(1, 11)})])
    reader = _mail(
        f"kierowniczka@{GROUP_DOMAIN}",
        [_attachment("B2B_2026_10.xls", sheet)],
        "Rozliczenie za 10.2026",
    )

    await _read(reader)

    by_name = {d.file_name: d.contract_id for d in await _documents()}
    assert by_name["B2B_2026_10.xls"] == cp.contract_id


async def test_polkomtel_report_without_order_goes_to_polkomtel(monkeypatch) -> None:
    """Polkomtel 471 IX: konsultant przekazuje raport i fakturę ze skrzynki firmowej.
    Raport idzie do kontraktu u Polkomtelu, faktura dalej czeka na człowieka."""

    last = f"Testowy{tag()}"
    plk, _, _ = await _group_person(monkeypatch, last)
    reader = _mail(
        f"jan.{last.lower()}@{COMPANY}",
        [
            _attachment("A1_9_2026.pdf", b"%PDF-1.4 faktura"),
            _attachment(
                f"jan.{last.lower()}_timesheet za 09_2026.xls",
                polkomtel_html(person=f"Jan {last}"),
            ),
        ],
        "Fwd: PD: Raport Timesheet za 09/2026",
    )

    await _read(reader)

    by_name = {d.file_name: d.contract_id for d in await _documents()}
    assert by_name[f"jan.{last.lower()}_timesheet za 09_2026.xls"] == plk.contract_id
    assert by_name["A1_9_2026.pdf"] is None


async def test_order_number_in_polkomtel_report_wins(monkeypatch) -> None:
    last = f"Testowy{tag()}"
    _, cp, number = await _group_person(monkeypatch, last)
    reader = _mail(
        f"jan.{last.lower()}@{COMPANY}",
        [_attachment("ts.xls", polkomtel_html(person=f"Jan {last}", order=number))],
        "Raport Timesheet za 09/2026",
    )

    await _read(reader)

    assert [d.contract_id for d in await _documents()] == [cp.contract_id]


async def test_sheet_from_stranger_decides_nothing(monkeypatch) -> None:
    """Treść pliku wskazuje osobę tylko od skrzynki firmy, od klienta z grupy albo od
    samej osoby: obcy adres nie dopisze nikomu godzin własnym plikiem."""

    last = f"Testowy{tag()}"
    await _group_person(monkeypatch, last)
    reader = _mail(
        "ktos@obca-firma.example",
        [_attachment("ts.xls", polkomtel_html(person=f"Jan {last}"))],
        "Raport Timesheet za 09/2026",
    )

    await _read(reader)

    assert [d.contract_id for d in await _documents()] == [None]


async def test_polsat_sheet_without_known_order_still_waits(monkeypatch) -> None:
    last = f"Testowy{tag()}"
    await _group_person(monkeypatch, last)
    sheet = polsat_xml([(f"{last} Jan", "Z000000000", "80", {1: "80"})])
    reader = _mail(
        f"kierowniczka@{GROUP_DOMAIN}",
        [_attachment("B2B_2026_10.xls", sheet)],
        "Rozliczenie za 10.2026",
    )

    await _read(reader)

    assert [d.contract_id for d in await _documents() if d.kind == "report"] == [None]


async def test_cancelled_order_line_does_not_count(monkeypatch) -> None:
    last = f"Testowy{tag()}"
    _, cp, number = await _group_person(monkeypatch, last)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(ClientOrder)
            .where(ClientOrder.contract_id == cp.contract_id)
            .values(status=ClientOrderStatus.cancelled)
        )
        await db.commit()
    sheet = polsat_xml([(f"{last} Jan", number, "80", {d: "8" for d in range(1, 11)})])
    reader = _mail(
        f"kierowniczka@{GROUP_DOMAIN}",
        [_attachment("B2B_2026_10.xls", sheet)],
        "Rozliczenie za 10.2026",
    )

    await _read(reader)

    assert [d.contract_id for d in await _documents() if d.kind == "report"] == [None]


async def test_jeden_arkusz_xlsx_dla_kontraktu_w_polsacie_i_w_polkomtelu(
    monkeypatch,
) -> None:
    """VII 2026: wykaz od kierownika klienta (``.xlsx``) z wierszem zamówienia Polsatu
    i wierszem zamówienia Polkomtelu tej samej osoby: plik idzie do obu kontraktów."""

    last = f"Testowy{tag()}"
    plk, cp, number = await _group_person(monkeypatch, last)
    sap = f"45{tag()}"
    await _order(plk.contract_id, plk.client_id, f"SAP {sap}")
    sheet = polsat_xlsx(
        [
            (f"{last} Jan", number, "88", {d: "8" for d in range(1, 12)}),
            (f"{last} Jan", sap, "8", {14: "8"}),
        ]
    )
    reader = _mail(
        f"kierowniczka@{GROUP_DOMAIN}",
        [_attachment("B2B_2026_07.xlsx", sheet)],
        "Rozliczenie za 07.2026",
    )

    await _read(reader)

    owners = sorted(
        d.contract_id for d in await _documents() if d.file_name == "B2B_2026_07.xlsx"
    )
    assert owners == sorted([cp.contract_id, plk.contract_id])


async def test_arkusz_kilku_kontraktow_od_obcego_nic_nie_przypisuje(
    monkeypatch,
) -> None:
    last = f"Testowy{tag()}"
    plk, _cp, number = await _group_person(monkeypatch, last)
    sap = f"45{tag()}"
    await _order(plk.contract_id, plk.client_id, f"SAP {sap}")
    sheet = polsat_xlsx(
        [
            (f"{last} Jan", number, "88", {d: "8" for d in range(1, 12)}),
            (f"{last} Jan", sap, "8", {14: "8"}),
        ]
    )
    reader = _mail(
        "ktos@obca-domena.example",
        [_attachment("B2B_2026_07.xlsx", sheet)],
        "Rozliczenie za 07.2026",
    )

    await _read(reader)

    assert all(
        d.contract_id is None
        for d in await _documents()
        if d.file_name == "B2B_2026_07.xlsx"
    )
