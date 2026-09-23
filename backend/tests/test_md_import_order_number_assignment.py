"""Import MD: wiersz z numerem zamówienia trafia wyłącznie na to zamówienie.

Ticket 23.09.2026 (BIK, import za sierpień): jedna osoba na dwóch kolejnych
zamówieniach MD — stare kończy się w połowie miesiąca, nowe (następca) zaczyna
się dzień później. Arkusz niesie dwa wiersze z numerami obu zamówień
w „Uwagach". Do tej poprawki:

* numer był czytany wyłącznie u Polkomtela, więc oba wiersze (osoba ma dwie
  linie zakończone) wpadały do „Wymaga przypisania",
* ręczne przypisanie drugiego wiersza do następcy przekierowywało zapis na
  poprzednika (FIN-MD-01) i NADPISYWAŁO wartość pierwszego wiersza,
* nadwyżka ponad budżet poprzednika przechodziła na następcę, choć arkusz
  wskazał zamówienie wprost.

Nazwiska, numery i liczby są zmyślone (repo jest publiczne).
"""

from __future__ import annotations

import io
import random
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

_TODAY = date.today()
#: Miesiąc raportu: poprzedni pełny miesiąc — raport przychodzi po jego końcu.
_MONTH_FIRST = (date(_TODAY.year, _TODAY.month, 1) - timedelta(days=1)).replace(day=1)
_PERIOD = _MONTH_FIRST.strftime("%Y-%m")
_PREV_PERIOD = (_MONTH_FIRST - timedelta(days=1)).strftime("%Y-%m")
#: Zamiana zamówień w połowie miesiąca raportu (jak 14.08 → 15.08).
_SPLIT_END = _MONTH_FIRST + timedelta(days=13)
_SPLIT_START = _SPLIT_END + timedelta(days=1)
_OLD_START = (_MONTH_FIRST - timedelta(days=70)).replace(day=1)
#: Koniec współpracy po miesiącu raportu (jak 03.09).
_LEFT_ON = date(_TODAY.year, _TODAY.month, 1) + timedelta(days=2)


def _number() -> str:
    return f"45{random.randint(10**7, 10**8 - 1)}"


def _sheet(rows: list[tuple[str, float, str, float]]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Imię i nazwisko", "Ilość MD", "Uwagi", "Faktura"])
    for name, md, notes, invoice in rows:
        ws.append([name, md, notes, invoice])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _enable_multi(monkeypatch, *client_ids: int) -> None:
    from app.services import multi_consultant_orders as mco

    monkeypatch.setattr(
        mco, "multi_consultant_client_ids", lambda: frozenset(client_ids)
    )


async def _seed() -> tuple[int, int, str]:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus

    suffix = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"MdNumberClient-{suffix}")
        cand = Candidate(
            name="Marek",
            lastname=f"Numerowy-{suffix}",
            email=f"mdnum-{suffix}@example.com",
        )
        db.add_all([client, cand])
        await db.commit()
        contract = Contract(
            candidate_id=cand.id,
            client_id=client.id,
            status=ContractStatus.active,
            start_date=_OLD_START,
            rate_candidate=Decimal("1040.000"),
            rate_client=Decimal("1360.000"),
        )
        db.add(contract)
        await db.commit()
        return client.id, contract.id, f"{cand.name} {cand.lastname}"


async def _create_group(
    app_client: AsyncClient,
    headers: dict,
    client_id: int,
    contract_id: int,
    *,
    number: str,
    start: date,
    end: date | None,
    md_total: float,
) -> dict:
    body = {
        "order_number": number,
        "start_date": start.isoformat(),
        "order_type": "md",
        "md_budget_mode": "per_person",
        "lines": [
            {
                "contract_id": contract_id,
                "rate_cost": 1040,
                "rate_revenue": 1360,
                "input_mode": "md",
                "input_value": md_total,
                "start_date": start.isoformat(),
            }
        ],
    }
    if end is not None:
        body["end_date"] = end.isoformat()
    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups", json=body, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _link_and_end(
    *,
    predecessor_group_id: int,
    successor_group_id: int,
    line_ids: list[int],
    contract_id: int,
    line_ends: dict[int, date] | None = None,
) -> None:
    """Następca wskazuje poprzednika, współpraca kończy się po miesiącu raportu."""
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.client_order_group import ClientOrderGroup
    from app.models.contract import Contract, ContractStatus

    async with AsyncSessionLocal() as db:
        successor = await db.get(ClientOrderGroup, successor_group_id)
        successor.predecessor_group_id = predecessor_group_id
        for line_id in line_ids:
            line = await db.get(ClientOrder, line_id)
            line.status = ClientOrderStatus.completed
            line.end_date = (line_ends or {}).get(line_id, _LEFT_ON)
        contract = await db.get(Contract, contract_id)
        contract.status = ContractStatus.ended
        contract.end_date = _LEFT_ON
        await db.commit()


async def _finance_headers(app_client: AsyncClient) -> dict:
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    suffix = uuid.uuid4().hex[:8]
    email = f"mdnum-fin-{suffix}@example.com"
    password = f"T3st_{suffix}!PassX"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name=f"MdNum Fin {suffix}",
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


async def _consumptions(order_id: int) -> dict[str, Decimal]:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.md_consumption import ClientOrderMdConsumption

    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(
                ClientOrderMdConsumption.period_month,
                ClientOrderMdConsumption.md_reported,
            ).where(ClientOrderMdConsumption.order_id == order_id)
        )
        return {month: Decimal(str(md)).normalize() for month, md in rows}


async def _events(group_id: int) -> list[tuple[str, str]]:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.client_order_group import ClientOrderGroupEvent

    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(
                ClientOrderGroupEvent.event_type, ClientOrderGroupEvent.description
            ).where(ClientOrderGroupEvent.group_id == group_id)
        )
        return [(t, d) for t, d in rows]


async def _group(app_client: AsyncClient, headers: dict, client_id: int, gid: int):
    listing = await app_client.get(
        f"/api/clients/{client_id}/order-groups", headers=headers
    )
    assert listing.status_code == 200, listing.text
    return next(g for g in listing.json()["groups"] if g["id"] == gid)


async def _ticket_setup(app_client, headers, monkeypatch, *, old_md: float = 35.75):
    """Poprzednik (do połowy miesiąca) + następca (od połowy), obie linie
    zakończone po miesiącu raportu — kształt z produkcji z 23.09.2026."""
    client_id, contract_id, name = await _seed()
    _enable_multi(monkeypatch, client_id)
    old_number, new_number = _number(), _number()
    old = await _create_group(
        app_client,
        headers,
        client_id,
        contract_id,
        number=old_number,
        start=_OLD_START,
        end=_SPLIT_END,
        md_total=old_md,
    )
    new = await _create_group(
        app_client,
        headers,
        client_id,
        contract_id,
        number=new_number,
        start=_SPLIT_START,
        end=None,
        md_total=22.24,
    )
    old_line, new_line = old["lines"][0]["id"], new["lines"][0]["id"]
    await _link_and_end(
        predecessor_group_id=old["id"],
        successor_group_id=new["id"],
        line_ids=[old_line, new_line],
        contract_id=contract_id,
    )
    return {
        "client_id": client_id,
        "contract_id": contract_id,
        "name": name,
        "old": old,
        "new": new,
        "old_line": old_line,
        "new_line": new_line,
        "old_number": old_number,
        "new_number": new_number,
    }


async def test_each_row_lands_only_on_the_order_named_in_it(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """13,75 MD na stare zamówienie, 6,25 MD na następcę — razem 20 MD."""
    case = await _ticket_setup(app_client, app_auth_headers, monkeypatch)
    finance = await _finance_headers(app_client)

    detail = await _import(
        app_client,
        finance,
        _sheet(
            [
                (case["name"], 13.75, case["old_number"], 18700),
                (case["name"], 6.25, case["new_number"], 8500),
            ]
        ),
    )

    assert detail["rows_applied"] == 2, detail
    assert detail["rows_ambiguous"] == 0, detail
    by_number = {row["order_number_hint"]: row for row in detail["rows"]}
    assert by_number[case["old_number"]]["matched_order_id"] == case["old_line"]
    assert by_number[case["new_number"]]["matched_order_id"] == case["new_line"]
    # Numer, który wskazał zamówienie MD, nie świeci się jako „brak zamówienia
    # kosztowego o tym numerze".
    assert all(row["cost_status"] is None for row in detail["rows"]), detail

    assert await _consumptions(case["old_line"]) == {_PERIOD: Decimal("13.75")}
    assert await _consumptions(case["new_line"]) == {_PERIOD: Decimal("6.25")}

    old_after = await _group(
        app_client, app_auth_headers, case["client_id"], case["old"]["id"]
    )
    new_after = await _group(
        app_client, app_auth_headers, case["client_id"], case["new"]["id"]
    )
    assert old_after["lines"][0]["md_used"] == pytest.approx(13.75)
    assert old_after["lines"][0]["md_remaining"] == pytest.approx(35.75 - 13.75)
    assert new_after["lines"][0]["md_used"] == pytest.approx(6.25)
    assert new_after["lines"][0]["md_remaining"] == pytest.approx(22.24 - 6.25)
    # Zakończona współpraca nie chowa zużycia — osoba jest w „Zakończonych".
    assert new_after["lines"][0]["is_active"] is False

    for event_type, description in await _events(case["old"]["id"]):
        assert "nadpisano" not in description, description
        assert event_type != "transfer_md", description
    assert not any(t == "transfer_md" for t, _ in await _events(case["new"]["id"]))


async def test_manual_assignment_does_not_overwrite_another_row_of_the_import(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Wymaganie 2: przypisanie wiersza następcy nie nadpisuje wiersza
    poprzednika z tej samej paczki (przekierowanie FIN-MD-01)."""
    case = await _ticket_setup(app_client, app_auth_headers, monkeypatch)
    finance = await _finance_headers(app_client)

    # Bez numerów: obie linie zakończone, więc obie wymagają przypisania.
    detail = await _import(
        app_client,
        finance,
        _sheet([(case["name"], 13.75, "", 18700), (case["name"], 6.25, "", 8500)]),
    )
    assert detail["rows_ambiguous"] == 2, detail
    rows = sorted(detail["rows"], key=lambda r: r["row_number"])

    for row, target in ((rows[0], case["old_line"]), (rows[1], case["new_line"])):
        resp = await app_client.post(
            f"/api/md-consumption/imports/{detail['id']}/rows/{row['id']}/assign",
            json={"order_id": target},
            headers=finance,
        )
        assert resp.status_code == 200, resp.text

    assert await _consumptions(case["old_line"]) == {_PERIOD: Decimal("13.75")}
    assert await _consumptions(case["new_line"]) == {_PERIOD: Decimal("6.25")}
    assert not any("nadpisano" in d for _, d in await _events(case["old"]["id"]))


async def test_manual_assignment_refuses_an_order_other_than_the_row_names(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Numer w wierszu wiąże też człowieka: 422, nic nie zapisane."""
    from app.core.database import AsyncSessionLocal
    from app.models.md_consumption import (
        IMPORT_ROW_NEEDS_ASSIGNMENT,
        MdConsumptionImportRow,
    )

    case = await _ticket_setup(app_client, app_auth_headers, monkeypatch)
    finance = await _finance_headers(app_client)
    detail = await _import(
        app_client, finance, _sheet([(case["name"], 6.25, "", 8500)])
    )
    row_id = detail["rows"][0]["id"]
    # Wiersz sprzed poprawki: numer w „Uwagach", a mimo to „Wymaga przypisania".
    async with AsyncSessionLocal() as db:
        row = await db.get(MdConsumptionImportRow, row_id)
        row.notes_raw = case["new_number"]
        row.status = IMPORT_ROW_NEEDS_ASSIGNMENT
        row.candidate_order_ids = [case["old_line"], case["new_line"]]
        await db.commit()

    resp = await app_client.post(
        f"/api/md-consumption/imports/{detail['id']}/rows/{row_id}/assign",
        json={"order_id": case["old_line"]},
        headers=finance,
    )
    assert resp.status_code == 422, resp.text
    assert case["new_number"] in resp.json()["detail"]
    assert await _consumptions(case["old_line"]) == {}


async def test_a_row_naming_an_order_outside_the_month_goes_to_verification(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Osoba z zamówieniem zakończonym PRZED miesiącem raportu nie dostaje
    zużycia — ani na tym zamówieniu, ani na innym (wymaganie 3)."""
    client_id, contract_id, name = await _seed()
    _enable_multi(monkeypatch, client_id)
    old_number, new_number = _number(), _number()
    before_month = _MONTH_FIRST - timedelta(days=1)
    old = await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        contract_id,
        number=old_number,
        start=_OLD_START,
        end=before_month,
        md_total=30,
    )
    new = await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        contract_id,
        number=new_number,
        start=_MONTH_FIRST,
        end=None,
        md_total=40,
    )
    await _link_and_end(
        predecessor_group_id=old["id"],
        successor_group_id=new["id"],
        line_ids=[old["lines"][0]["id"]],
        contract_id=contract_id,
        line_ends={old["lines"][0]["id"]: before_month},
    )
    finance = await _finance_headers(app_client)

    detail = await _import(app_client, finance, _sheet([(name, 12, old_number, 16320)]))

    row = detail["rows"][0]
    assert row["status"] == "unmatched", row
    assert row["status_label"] != "Zaktualizowano"
    assert row["order_number_hint"] == old_number
    assert "nie obejmuje miesiąca raportu" in row["status_reason"], row
    assert await _consumptions(old["lines"][0]["id"]) == {}
    assert await _consumptions(new["lines"][0]["id"]) == {}


async def test_an_unknown_order_number_is_not_guessed(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Numer, którego nie ma w NEXUSIE (literówka, niezarejestrowane
    zamówienie), nie spada na jedyne zamówienie tej osoby po nazwisku."""
    client_id, contract_id, name = await _seed()
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        contract_id,
        number=_number(),
        start=_OLD_START,
        end=None,
        md_total=40,
    )
    finance = await _finance_headers(app_client)
    unknown = _number()

    detail = await _import(app_client, finance, _sheet([(name, 5, unknown, 6800)]))

    row = detail["rows"][0]
    assert row["status"] == "unmatched", row
    assert "nie ma w NEXUSIE" in row["status_reason"], row
    assert await _consumptions(group["lines"][0]["id"]) == {}


async def test_a_row_without_a_number_keeps_name_matching(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Klienci bez numeru w arkuszu (BNP) i dopiski typu „w tym delegacja 318"
    nie zmieniają dotychczasowego dopasowania po nazwisku."""
    client_id, contract_id, name = await _seed()
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        contract_id,
        number=f"87_{_TODAY.year}",
        start=_OLD_START,
        end=None,
        md_total=40,
    )
    finance = await _finance_headers(app_client)

    detail = await _import(
        app_client, finance, _sheet([(name, 5, "w tym delegacja 318", 6800)])
    )

    assert detail["rows_applied"] == 1, detail
    assert await _consumptions(group["lines"][0]["id"]) == {_PERIOD: Decimal("5")}


async def test_overflow_of_a_named_order_is_not_moved_to_its_successor(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Lipiec z produkcji: 22 MD z numerem starego zamówienia przy budżecie
    13,75 — nadwyżka zostaje na nim (przekroczenie widać), a następca, który
    w tym miesiącu jeszcze nie istniał, nie dostaje nic."""
    case = await _ticket_setup(app_client, app_auth_headers, monkeypatch, old_md=13.75)
    finance = await _finance_headers(app_client)

    detail = await _import(
        app_client,
        finance,
        _sheet([(case["name"], 22, case["old_number"], 29920)]),
        period=_PREV_PERIOD,
    )

    assert detail["rows_applied"] == 1, detail
    assert await _consumptions(case["old_line"]) == {_PREV_PERIOD: Decimal("22")}
    assert await _consumptions(case["new_line"]) == {}


def test_explicit_hints_ignore_short_side_notes():
    from app.services.finance_order_matching import (
        explicit_order_hints,
        known_order_number_keys,
    )

    known = known_order_number_keys(
        [(1, "4500030067"), (15, "SAP 4500724825"), (2, "445")]
    )
    assert explicit_order_hints(["2026", "318"], known) == []
    assert explicit_order_hints(["445"], known) == ["445"]
    assert explicit_order_hints(["4500724825"], known) == ["4500724825"]
    # Nieznany, ale długi — wiąże (literówka nie może trafić gdzie indziej).
    assert explicit_order_hints(["4599999999"], known) == ["4599999999"]


# ── Jednorazowa korekta danych przypadku z ticketu ─────────────────────────


async def _seed_repair_state(app_client, headers, monkeypatch):
    """Stan z produkcji z 23.09.2026, odtworzony na świeżych ID."""
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder
    from app.models.client_order_group import ClientOrderGroupEvent
    from app.models.md_consumption import (
        ClientOrderMdConsumption,
        MdConsumptionImport,
    )
    from app.services.client_order_lines import recompute_remaining

    case = await _ticket_setup(app_client, headers, monkeypatch)
    async with AsyncSessionLocal() as db:
        july = MdConsumptionImport(period_month=_PREV_PERIOD, filename="lipiec.xlsx")
        august = MdConsumptionImport(period_month=_PERIOD, filename="sierpien.xlsx")
        db.add_all([july, august])
        await db.flush()
        for order_id, month, md, batch in (
            (case["old_line"], _PREV_PERIOD, "13.75", july),
            (case["old_line"], _PERIOD, "6.25", august),
            (case["new_line"], _PREV_PERIOD, "8.25", july),
        ):
            db.add(
                ClientOrderMdConsumption(
                    order_id=order_id,
                    period_month=month,
                    md_reported=Decimal(md),
                    source="import",
                    import_id=batch.id,
                )
            )
        old_line = await db.get(ClientOrder, case["old_line"])
        new_line = await db.get(ClientOrder, case["new_line"])
        old_line.md_manual_adjustment = Decimal("-8.25")
        new_line.md_manual_adjustment = Decimal("8.25")
        wrong = [
            ClientOrderGroupEvent(
                group_id=case["old"]["id"],
                order_id=case["old_line"],
                event_type="import_md",
                description="… (nadpisano wcześniejsze 13,75 MD) …",
            ),
            ClientOrderGroupEvent(
                group_id=case["new"]["id"],
                order_id=case["new_line"],
                event_type="transfer_md",
                description="przejęcie zużycia (8,25 MD)",
            ),
        ]
        db.add_all(wrong)
        await db.flush()
        await recompute_remaining(db, old_line)
        await recompute_remaining(db, new_line)
        await db.commit()
        events = list(
            (
                await db.execute(
                    select(ClientOrderGroupEvent.id).where(
                        ClientOrderGroupEvent.id.in_([e.id for e in wrong])
                    )
                )
            ).scalars()
        )
    return case, july.id, august.id, tuple(events)


def _repair_case(case, july_id, august_id, event_ids, **overrides):
    from app.services.md_import_order_number_repair import RepairCase

    values = dict(
        client_id=case["client_id"],
        contract_id=case["contract_id"],
        predecessor_order_id=case["old_line"],
        predecessor_group_id=case["old"]["id"],
        predecessor_number=case["old_number"],
        successor_order_id=case["new_line"],
        successor_group_id=case["new"]["id"],
        successor_number=case["new_number"],
        report_month=_PERIOD,
        august_import_id=august_id,
        previous_month=_PREV_PERIOD,
        july_import_id=july_id,
        expected_before={
            (case["old_line"], _PREV_PERIOD): Decimal("13.75"),
            (case["old_line"], _PERIOD): Decimal("6.25"),
            (case["new_line"], _PREV_PERIOD): Decimal("8.25"),
        },
        expected_adjustments={
            case["old_line"]: Decimal("-8.25"),
            case["new_line"]: Decimal("8.25"),
        },
        target={
            (case["old_line"], _PREV_PERIOD): Decimal("22"),
            (case["old_line"], _PERIOD): Decimal("13.75"),
            (case["new_line"], _PERIOD): Decimal("6.25"),
        },
        wrong_event_ids=event_ids,
    )
    values.update(overrides)
    return RepairCase(**values)


async def test_repair_restores_the_ticket_numbers(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.core.database import AsyncSessionLocal
    from app.services import md_import_order_number_repair as repair

    case, july_id, august_id, event_ids = await _seed_repair_state(
        app_client, app_auth_headers, monkeypatch
    )
    marker = f"test_md_repair_{uuid.uuid4().hex[:8]}"
    spec = _repair_case(case, july_id, august_id, event_ids)

    async with AsyncSessionLocal() as db:
        summary = await repair.run_md_import_order_number_repair(
            db, case=spec, marker=marker, details_key=f"{marker}_details"
        )
        await db.commit()
    assert summary["applied"] is True, summary
    assert summary["skipped"] is None

    assert await _consumptions(case["old_line"]) == {
        _PREV_PERIOD: Decimal("22"),
        _PERIOD: Decimal("13.75"),
    }
    assert await _consumptions(case["new_line"]) == {_PERIOD: Decimal("6.25")}

    old_after = await _group(
        app_client, app_auth_headers, case["client_id"], case["old"]["id"]
    )
    new_after = await _group(
        app_client, app_auth_headers, case["client_id"], case["new"]["id"]
    )
    old_line = old_after["lines"][0]
    new_line = new_after["lines"][0]
    assert old_line["md_used"] == pytest.approx(35.75)
    assert old_line["md_remaining"] == pytest.approx(0)
    assert new_line["md_used"] == pytest.approx(6.25)
    assert new_line["md_remaining"] == pytest.approx(22.24 - 6.25)
    assert new_line["md_manual_adjustment"] in (0, None)

    old_events = await _events(case["old"]["id"])
    new_events = await _events(case["new"]["id"])
    assert not any("nadpisano" in d for _, d in old_events)
    assert not any("8,25 MD)" in d for _, d in new_events)
    assert any("Korekta importu MD" in d for _, d in old_events)
    assert any("Korekta importu MD" in d for _, d in new_events)

    # Drugi przebieg — nic nie robi.
    async with AsyncSessionLocal() as db:
        again = await repair.run_md_import_order_number_repair(
            db, case=spec, marker=marker, details_key=f"{marker}_details"
        )
    assert again is None


async def test_repair_leaves_a_hand_corrected_state_alone(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder
    from app.services import md_import_order_number_repair as repair

    case, july_id, august_id, event_ids = await _seed_repair_state(
        app_client, app_auth_headers, monkeypatch
    )
    async with AsyncSessionLocal() as db:
        line = await db.get(ClientOrder, case["new_line"])
        line.md_manual_adjustment = Decimal("1")
        await db.commit()

    marker = f"test_md_repair_{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        summary = await repair.run_md_import_order_number_repair(
            db,
            case=_repair_case(case, july_id, august_id, event_ids),
            marker=marker,
            details_key=f"{marker}_details",
        )
        await db.commit()
    assert summary["applied"] is False
    assert summary["skipped"] == "edited_since_snapshot"
    assert await _consumptions(case["new_line"]) == {_PREV_PERIOD: Decimal("8.25")}
