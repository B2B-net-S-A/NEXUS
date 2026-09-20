"""Rozliczenie, które przychodzi PO zejściu konsultanta, i tak dolicza mu MD.

Zgłoszenie (CeZ/242/2025, 09.2026): konsultant kończy współpracę na zamówieniu
z podstawą 356 MD, mając zapisane 4 MD zużycia, i trafia do zakładki
„Zakończone". Kilka tygodni później Finanse przysyłają rozliczenie za miesiąc,
w którym jeszcze pracował — wynika z niego dodatkowe 21 MD. System ma pokazać
łącznie 25 MD u tej osoby i doliczyć te 21 MD do wykorzystania CAŁEGO
zamówienia.

Do 09.2026 było to niemożliwe: import pytał wyłącznie o linie ``active``, więc
wiersz lądował jako „Brak aktywnego zamówienia" i nie dawał się przypisać
nawet ręcznie. Teraz decyduje OKRES linii, nie jej status
(``client_order_lines.line_settles_in_month``).

Nazwiska, numery i liczby są zmyślone (repo jest publiczne).
"""

from __future__ import annotations

import io
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

#: Miesiąc raportu leży w przeszłości, tak jak w zgłoszeniu: osoba już zeszła,
#: a rozliczenie za ten miesiąc dopiero wpływa.
_TODAY = date.today()
_REPORTED = date(_TODAY.year, _TODAY.month, 1) - timedelta(days=45)
_PERIOD = _REPORTED.strftime("%Y-%m")
#: Ostatni dzień miesiąca, którego dotyczy raport — wtedy konsultant zszedł.
_LEFT_ON = date(_TODAY.year, _TODAY.month, 1) - timedelta(days=1)
_STARTED = _REPORTED - timedelta(days=60)


def _sheet(rows: list[tuple[str, float]]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Imię i nazwisko", "Ilość MD"])
    for name, md in rows:
        ws.append([name, md])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _enable_multi(monkeypatch, *client_ids: int) -> None:
    from app.services import multi_consultant_orders as mco

    monkeypatch.setattr(
        mco, "multi_consultant_client_ids", lambda: frozenset(client_ids)
    )


async def _seed_client_with_contracts(n: int) -> tuple[int, list[int], list[str]]:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus

    suffix = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"EndedMdClient-{suffix}")
        db.add(client)
        await db.commit()
        await db.refresh(client)

        contract_ids: list[int] = []
        names: list[str] = []
        for i in range(n):
            cand = Candidate(
                name=f"Anna{i}",
                lastname=f"Zejscie-{suffix}-{i}",
                email=f"endedmd-{suffix}-{i}@example.com",
            )
            db.add(cand)
            await db.commit()
            await db.refresh(cand)
            contract = Contract(
                candidate_id=cand.id,
                client_id=client.id,
                status=ContractStatus.active,
                start_date=_STARTED,
                rate_candidate=Decimal("100.000"),
                rate_client=Decimal("150.000"),
            )
            db.add(contract)
            await db.commit()
            await db.refresh(contract)
            contract_ids.append(contract.id)
            names.append(f"{cand.name} {cand.lastname}")
        return client.id, contract_ids, names


def _md_line(contract_id: int, md_total: int) -> dict:
    return {
        "contract_id": contract_id,
        "rate_cost": 1000,
        "rate_revenue": 1200,
        "input_mode": "md",
        "input_value": md_total,
        "start_date": _STARTED.isoformat(),
    }


async def _create_group(
    app_client: AsyncClient, headers: dict, client_id: int, lines: list[dict]
) -> dict:
    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups",
        json={
            "order_number": f"CeZ-{uuid.uuid4().hex[:6]}",
            "start_date": _STARTED.isoformat(),
            "order_type": "md",
            "md_budget_mode": "per_person",
            "lines": lines,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _finance_headers(app_client: AsyncClient) -> dict:
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    suffix = uuid.uuid4().hex[:8]
    email = f"endedmd-fin-{suffix}@example.com"
    password = f"T3st_{suffix}!PassX"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name=f"EndedMd Fin {suffix}",
                role=UserRole.finance,
                is_active=True,
                profile_completed=True,
            )
        )
        await db.commit()
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _import(
    app_client: AsyncClient, headers: dict, payload: bytes, period: str = _PERIOD
) -> dict:
    resp = await app_client.post(
        "/api/md-consumption/imports",
        files={
            "file": (
                "raport.xlsx",
                payload,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={"period_month": period},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _group(app_client: AsyncClient, headers: dict, client_id: int, gid: int):
    listing = await app_client.get(
        f"/api/clients/{client_id}/order-groups", headers=headers
    )
    assert listing.status_code == 200, listing.text
    return next(g for g in listing.json()["groups"] if g["id"] == gid)


async def _end_cooperation(
    line_id: int, *, on: date = _LEFT_ON, status: str = "completed"
) -> None:
    """Kształt linii po zejściu konsultanta — jak na produkcji po zasiewie CeZ.

    Kontrakt idzie na ``ended``, linia dostaje datę udziału i status
    końcowy. Nie ma tu sprawy offboardingu: ta wersja odpowiada wierszom
    CeZ/242/2025, które powstały z importu danych startowych.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.contract import Contract, ContractStatus

    async with AsyncSessionLocal() as db:
        order = await db.get(ClientOrder, line_id)
        assert order is not None
        order.end_date = on
        order.status = ClientOrderStatus(status)
        contract = await db.get(Contract, order.contract_id)
        assert contract is not None
        contract.status = ContractStatus.ended
        contract.end_date = on
        await db.commit()


async def test_a_report_landing_after_the_departure_adds_md_to_the_ended_line(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """4 MD + 21 MD z zaległego raportu = 25 MD u osoby i w sumie zamówienia."""
    client_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_md_line(contracts[0], 356)]
    )
    line_id = group["lines"][0]["id"]
    finance = await _finance_headers(app_client)

    # Stan sprzed zgłoszenia: 4 MD zapisane, konsultant schodzi z zamówienia.
    await _import(app_client, finance, _sheet([(names[0], 4)]))
    await _end_cooperation(line_id)

    before = await _group(app_client, app_auth_headers, client_id, group["id"])
    ended = before["lines"][0]
    assert ended["is_active"] is False, "osoba ma być w sekcji „Zakończone”"
    assert ended["md_used"] == pytest.approx(4.0)
    assert before["md_used_total"] == pytest.approx(4.0)

    # Zaległe rozliczenie za miesiąc, w którym jeszcze pracowała.
    detail = await _import(app_client, finance, _sheet([(names[0], 25)]))
    assert detail["rows_applied"] == 1, detail
    assert detail["rows_unmatched"] == 0, detail

    after = await _group(app_client, app_auth_headers, client_id, group["id"])
    line = after["lines"][0]
    assert line["md_used"] == pytest.approx(25.0)
    assert line["md_remaining"] == pytest.approx(356.0 - 25.0)
    # Zejście z obsady nie zmienia statusu linii z powrotem na aktywny.
    assert line["is_active"] is False
    assert line["status"] == "completed"
    # Suma zamówienia rośnie o te same MD — kryterium 6 zgłoszenia.
    assert after["md_used_total"] == pytest.approx(25.0)
    assert after["used_value_pln"] == pytest.approx(25 * 1200)
    assert after["md_positions_total"] == pytest.approx(356.0)


async def test_a_cancelled_line_never_takes_the_report(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Anulowana linia znaczy „tej osoby tu nie było", więc nic nie rozlicza."""
    client_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_md_line(contracts[0], 356)]
    )
    await _end_cooperation(group["lines"][0]["id"], status="cancelled")
    finance = await _finance_headers(app_client)

    detail = await _import(app_client, finance, _sheet([(names[0], 21)]))
    assert detail["rows_applied"] == 0, detail
    assert detail["rows_unmatched"] == 1, detail


async def test_an_active_line_wins_over_the_persons_ended_one(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Linia zakończona jest celem ZAPASOWYM, nigdy konkurentem dla aktywnej.

    Osoba, która w tym samym miesiącu zeszła z jednego zamówienia i weszła na
    drugie, ma dwa trafienia nazwiskiem. Bez preferencji linii aktywnej
    rozliczenie, które dziś dopasowuje się samo, wpadałoby do „wymaga
    przypisania" — czyli naprawa jednego defektu robiłaby drugi.
    """
    client_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    left = await _create_group(
        app_client, app_auth_headers, client_id, [_md_line(contracts[0], 100)]
    )
    await _end_cooperation(left["lines"][0]["id"])

    # Ta sama osoba wchodzi na kolejne zamówienie tego klienta.
    from app.core.database import AsyncSessionLocal
    from app.models.contract import Contract, ContractStatus

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contracts[0])
        contract.status = ContractStatus.active
        contract.end_date = None
        await db.commit()

    joined = await _create_group(
        app_client, app_auth_headers, client_id, [_md_line(contracts[0], 200)]
    )
    finance = await _finance_headers(app_client)

    detail = await _import(app_client, finance, _sheet([(names[0], 21)]))
    assert detail["rows_applied"] == 1, detail
    assert detail["rows_ambiguous"] == 0, detail

    joined_after = await _group(app_client, app_auth_headers, client_id, joined["id"])
    left_after = await _group(app_client, app_auth_headers, client_id, left["id"])
    assert joined_after["lines"][0]["md_used"] == pytest.approx(21.0)
    assert left_after["lines"][0]["md_used"] == pytest.approx(0.0)


def test_the_active_preference_never_runs_before_the_order_number_filter():
    """Remis rozstrzyga linia aktywna — ale DOPIERO po zawężeniu numerem.

    Pierwsza wersja tej poprawki wpięła preferencję do `match_by_name`, czyli
    PRZED filtrem numeru z „Uwag". Wiersz z poprawnym numerem, wskazującym
    linię zakończoną, tracił ją wtedy na rzecz aktywnej linii tej samej osoby
    z INNEGO zamówienia i kończył jako niedopasowany. Złapał to
    `test_polkomtel_finance_order_matching`; ten test nazywa regułę wprost.
    """
    from types import SimpleNamespace

    from app.api.md_consumption import _match_per_consultant_md_row
    from app.models.client_order import ClientOrderStatus
    from app.services import finance_order_matching
    from app.services.client_order_lines import LineMatch

    def _match(order_id: int, status, number: str) -> LineMatch:
        return LineMatch(
            order=SimpleNamespace(id=order_id, status=status),
            group=SimpleNamespace(
                client_id=finance_order_matching.POLKOMTEL_CLIENT_ID,
                order_number=number,
            ),
            consultant_name="Anna Zejście",
        )

    ended = _match(1, ClientOrderStatus.completed, "SAP 4500000111")
    still_working = _match(2, ClientOrderStatus.active, "SAP 4500000222")

    picked = _match_per_consultant_md_row(
        parsed_row=SimpleNamespace(
            consultant_name="Anna Zejście",
            notes_raw="zlecenie 4500000111",
        ),
        candidates=[ended, still_working],
    )

    assert picked == [ended]
