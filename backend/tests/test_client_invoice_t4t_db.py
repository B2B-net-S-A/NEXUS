"""„Do faktury dla klienta” z raportu T4T na bazie (Nordea, 23.11.2026).

Klient z regułą ``report.time_for_teams``: pozycja osoby z godzin zatwierdzonych
w ostatniej wersji raportu; godziny niezatwierdzone wstrzymują pozycję; mailowa
akceptacja managera klienta przechodzi tylko po odejściu osoby z projektu;
ostrzeżenie o terminie faktury (15. dzień następnego miesiąca).

Osoby, numery, domeny i kwoty fikcyjne.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.core.scheduling import local_now
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_settlement import ClientSettlementRuleSet
from app.models.contact import Contact
from app.models.consultant_portal import CpDocument
from app.models.contract import Contract, ContractStatus, RateUnit
from app.services.client_settlements import client_invoice, time_reports
from tests.test_client_audit_2026_09_24 import _client
from tests.test_client_settlements_pko_velo_db import _store
from tests.test_client_time_reports_db import (
    MONTH,
    _drop,
    _person,
    _rows,
    _upload,
    _xlsx,
)

pytestmark = pytest.mark.asyncio

ACTOR = SimpleNamespace(id=None)
DOMAIN = "klient-t4t.example"


def _mail(body: str, quoted: str, *, sender: str) -> bytes:
    return (
        f"From: Manager <{sender}>\r\nTo: koordynatorka@b2b.example\r\n"
        "Subject: RE: September Time for Teams Approvals\r\n"
        "Date: Mon, 12 Oct 2026 09:00:00 +0200\r\nMIME-Version: 1.0\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n\r\n"
        f"{body}\r\n\r\nFrom: Koordynatorka <koordynatorka@b2b.example>\r\n"
        f"Sent: Friday, October 9, 2026 10:00\r\n{quoted}\r\n"
    ).encode()


async def _world() -> tuple[int, dict[str, int]]:
    client_id = await _client()
    people = {
        "jan": await _person(client_id, "Jan", "Testowy"),
        "anna": await _person(client_id, "Anna", "Przykładowa"),
        "ewa": await _person(client_id, "Ewa", "Próbna"),
        "piotr": await _person(client_id, "Piotr", "Wzorcowy"),
    }
    async with AsyncSessionLocal() as db:
        db.add(
            ClientSettlementRuleSet(
                client_id=client_id,
                effective_from="2020-01",
                rules={
                    "report.time_for_teams": {
                        "level": "warn",
                        "params": {"warn_days": "5"},
                    }
                },
            )
        )
        db.add(Contact(client_id=client_id, name="Manager", email=f"pm@{DOMAIN}"))
        for contract_id in people.values():
            db.add(
                ClientOrder(
                    client_id=client_id,
                    contract_id=contract_id,
                    title="linia godzinowa",
                    status=ClientOrderStatus.active,
                    start_date=date(2026, 1, 1),
                    rate_unit=RateUnit.hourly,
                    rate_client=Decimal("150"),
                )
            )
        # Ewa odeszła z projektu z końcem września.
        ewa = await db.get(Contract, people["ewa"])
        ewa.end_date = date(2026, 9, 30)
        ewa.status = ContractStatus.ended
        await db.commit()
    async with AsyncSessionLocal() as db:
        for number, key in enumerate(("jan", "anna", "ewa", "piotr"), start=1):
            await time_reports.add_manual_id(
                db,
                client_id,
                contract_id=people[key],
                kind="client_person_no",
                value=f"M00000{number}",
                actor=ACTOR,
                now=local_now(),
            )
        await db.commit()
    return client_id, people


async def _invoice(client_id: int, today: date | None = None) -> dict:
    async with AsyncSessionLocal() as db:
        return await client_invoice.invoice_month(
            db, client_id, MONTH, amounts=True, today=today
        )


async def _cleanup(client_id: int, people: dict[str, int]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(CpDocument).where(CpDocument.contract_id.in_(list(people.values())))
        )
        await db.execute(delete(Contact).where(Contact.client_id == client_id))
        await db.execute(
            delete(ClientSettlementRuleSet).where(
                ClientSettlementRuleSet.client_id == client_id
            )
        )
        await db.commit()
    await _drop(client_id, list(people.values()))


async def test_pozycja_z_zatwierdzonych_godzin_ostatniej_wersji(
    tmp_path, monkeypatch
) -> None:
    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    client_id, people = await _world()
    try:
        # Wersja 1: Anna i Piotr mają ostatni przedział (32 h) w statusie 1.
        await _upload(
            client_id,
            _xlsx(
                _rows("M000001", "Jan Testowy"),
                _rows("M000002", "Anna Przykladowa", last_status=1),
                _rows("M000003", "Ewa Probna", last_status=1),
                _rows("M000004", "Piotr Wzorcowy", last_status=1),
            ),
            date(2026, 10, 1),
        )
        data = await _invoice(client_id)
        by_id = {r["contract_id"]: r for r in data["rows"]}
        assert data["time_report"]["label"] == "wersja z 01.10"
        anna = by_id[people["anna"]]
        assert anna["state"] == "awaiting_t4t"
        assert anna["hold_reason"].startswith(
            "Godziny niezatwierdzone w T4T (wersja z 01.10)"
        )
        # Pozycja pokazuje tylko zatwierdzone godziny, ale nie idzie do kopiowania.
        assert anna["positions"][0]["quantity"] == "144"
        assert anna["t4t"]["pending"] == "32.00"

        # Wersja 2 (nowsza): Anna ma wszystko zatwierdzone; wersje się nie sumują.
        await _upload(
            client_id,
            _xlsx(
                _rows("M000001", "Jan Testowy"),
                _rows("M000002", "Anna Przykladowa"),
                _rows("M000003", "Ewa Probna", last_status=1),
                _rows("M000004", "Piotr Wzorcowy", last_status=1),
            ),
            date(2026, 10, 5),
        )
        data = await _invoice(client_id)
        by_id = {r["contract_id"]: r for r in data["rows"]}
        assert data["time_report"]["label"] == "wersja z 05.10"
        jan = by_id[people["jan"]]
        assert jan["state"] == "ready" and jan["kind"] == "time_report"
        (position,) = jan["positions"]
        assert (position["unit"], position["quantity"]) == ("godz.", "176")
        assert (position["unit_price"], position["net"]) == ("150.00", "26400.00")
        # Koszt: 176 h × 100 zł stawki kontraktora.
        assert jan["cost"] == "17600.00" and jan["margin"] == "8800.00"
        assert by_id[people["anna"]]["state"] == "ready"
        assert by_id[people["anna"]]["positions"][0]["quantity"] == "176"

        piotr = by_id[people["piotr"]]
        assert piotr["state"] == "awaiting_t4t"
        assert "wersja z 05.10" in piotr["hold_reason"]

        # Ewa: odeszła, akceptacja managera tylko od nas (bez odpowiedzi) nie wystarcza.
        await _store(
            people["ewa"],
            "2026-10",
            _mail(
                "Please approve the 176 hours for September 2026.",
                "Hi,",
                sender="koordynatorka@b2b.example",
            ),
            "prosba.eml",
        )
        ewa = {r["contract_id"]: r for r in (await _invoice(client_id))["rows"]}[
            people["ewa"]
        ]
        assert ewa["state"] == "awaiting_t4t"
        assert ewa["t4t"]["notes"] == [
            "Mail z akceptacją nie pochodzi od managera klienta."
        ]

        # Odpowiedź managera z domeny klienta: pozycja na 176 h z maila.
        await _store(
            people["ewa"],
            "2026-10",
            _mail(
                "Approved.",
                "Please approve the 176 hours for September 2026.",
                sender=f"pm@{DOMAIN}",
            ),
            "akceptacja.eml",
        )
        data = await _invoice(client_id, today=date(2026, 10, 12))
        by_id = {r["contract_id"]: r for r in data["rows"]}
        ewa = by_id[people["ewa"]]
        assert ewa["state"] == "ready"
        assert ewa["positions"][0]["quantity"] == "176"
        assert ewa["t4t"]["notes"] == [
            "Akceptacja mailowa managera: 176 h za wrzesień 2026."
        ]

        # Piotr pracuje dalej: ta sama akceptacja go nie odblokowuje.
        await _store(
            people["piotr"],
            "2026-09",
            _mail(
                "Approved.",
                "Please approve the 176 hours for September 2026.",
                sender=f"pm@{DOMAIN}",
            ),
            "akceptacja.eml",
        )
        data = await _invoice(client_id, today=date(2026, 10, 12))
        piotr = {r["contract_id"]: r for r in data["rows"]}[people["piotr"]]
        assert piotr["state"] == "awaiting_t4t"
        assert "nadal pracuje u klienta" in piotr["t4t"]["notes"][0]

        # Termin 15.10: 3 dni przed nim (parametr 5) — ostrzeżenie z jedną osobą.
        assert data["deadline"] == {
            "date": "2026-10-15",
            "days_left": 3,
            "overdue": False,
            "missing": 1,
            "people": ["Piotr Wzorcowy"],
        }
        assert (await _invoice(client_id, today=date(2026, 10, 1)))["deadline"] is None
    finally:
        await _cleanup(client_id, people)


async def test_bez_reguly_t4t_faktura_z_rcp_jak_dotad() -> None:
    client_id, people = await _world()
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(ClientSettlementRuleSet).where(
                    ClientSettlementRuleSet.client_id == client_id
                )
            )
            await db.commit()
        await _upload(
            client_id, _xlsx(_rows("M000001", "Jan Testowy")), date(2026, 10, 1)
        )
        data = await _invoice(client_id, today=date(2026, 10, 12))
        assert data["time_report"] is None and data["deadline"] is None
        assert {r["state"] for r in data["rows"]} == {"waiting"}
        assert all(r["kind"] is None for r in data["rows"])
    finally:
        await _cleanup(client_id, people)
