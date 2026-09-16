"""Kto stoi w „Aktywnej obsadzie" zamówienia, a kto w „Zakończonych" (09.2026).

Ticket: osoba, która zakończyła współpracę na zamówieniu, wisiała wśród
aktywnych. Linia MD **kończy się budżetem, nie kalendarzem**
(``sync_md_line_status``, ``dl_portal_expiry_scanner._promote_statuses``), więc
zapisana data zejścia nie zmieniała statusu — a to po statusie szedł podział
sekcji na karcie.

Poprawka jest wyłącznie PREZENTACYJNA (``OrderLineRead.is_active``). Status
w bazie zostaje nietknięty, bo to on rządzi importem zużycia: raport za
sierpień przychodzi w połowie września, już po zejściu osoby, i nadal musi
doliczyć się do jej historii oraz do sum zamówienia. Te dwa kryteria mają tu
własne testy — bez nich „naprawa" polegająca na domknięciu linii datą wygląda
na zieloną.

Nazwiska, numery i kwoty są zmyślone (repo jest publiczne).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from httpx import AsyncClient

from app.core.scheduling import business_today

_TODAY = business_today()


def _month_first(day: date) -> date:
    return day.replace(day=1)


#: Pierwszy i ostatni dzień POPRZEDNIEGO miesiąca — okres, za który raport
#: z Finansów przychodzi już po zejściu konsultanta.
_LAST_MONTH_LAST = _month_first(_TODAY) - timedelta(days=1)
_LAST_MONTH_FIRST = _month_first(_LAST_MONTH_LAST)
_LAST_MONTH = f"{_LAST_MONTH_FIRST.year:04d}-{_LAST_MONTH_FIRST.month:02d}"


async def _seed_client_with_contracts(n: int = 2) -> tuple[int, list[int], list[str]]:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus

    suffix = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"RosterClient-{suffix}")
        db.add(client)
        await db.flush()
        contract_ids: list[int] = []
        names: list[str] = []
        for i in range(n):
            cand = Candidate(
                name=f"Kon{i}",
                lastname=f"Sultant-{suffix}-{i}",
                email=f"roster-{suffix}-{i}@example.com",
            )
            db.add(cand)
            await db.flush()
            contract = Contract(
                candidate_id=cand.id,
                client_id=client.id,
                status=ContractStatus.active,
                start_date=_TODAY - timedelta(days=200),
                rate_candidate=Decimal("100.000"),
                rate_client=Decimal("150.000"),
            )
            db.add(contract)
            await db.flush()
            contract_ids.append(contract.id)
            names.append(f"{cand.name} {cand.lastname}")
        await db.commit()
        return client.id, contract_ids, names


def _enable_multi(monkeypatch, *client_ids: int) -> None:
    from app.services import multi_consultant_orders as mco

    monkeypatch.setattr(
        mco, "multi_consultant_client_ids", lambda: frozenset(client_ids)
    )


def _md_line(contract_id: int, **overrides) -> dict:
    payload = {
        "contract_id": contract_id,
        "rate_cost": 1000,
        "rate_revenue": 1200,
        "input_mode": "md",
        "input_value": 50,
        "start_date": (_TODAY - timedelta(days=150)).isoformat(),
    }
    payload.update(overrides)
    return payload


async def _create_group(
    app_client: AsyncClient, headers: dict, client_id: int, lines: list[dict], **extra
) -> dict:
    body = {
        "order_number": f"CeZ-{uuid.uuid4().hex[:4]}/2026",
        "start_date": (_TODAY - timedelta(days=150)).isoformat(),
        "lines": lines,
    }
    body.update(extra)
    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups", json=body, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _read_group(
    app_client: AsyncClient, headers: dict, client_id: int, group_id: int
) -> dict:
    resp = await app_client.get(
        f"/api/clients/{client_id}/order-groups", headers=headers
    )
    assert resp.status_code == 200, resp.text
    return next(g for g in resp.json()["groups"] if g["id"] == group_id)


def _line_by_contract(group: dict, contract_id: int) -> dict:
    return next(line for line in group["lines"] if line["contract_id"] == contract_id)


# ── Reguła jako czysta funkcja ──────────────────────────────────────────────


def _order(status_value: str, end_date: date | None):
    from app.models.client_order import ClientOrder, ClientOrderStatus

    return ClientOrder(
        status=ClientOrderStatus(status_value),
        end_date=end_date,
    )


def test_line_without_an_end_date_stays_on_the_roster():
    from app.services.client_order_lines import is_line_on_active_roster

    assert is_line_on_active_roster(_order("active", None), _TODAY + timedelta(days=90))


def test_line_ending_in_the_future_stays_on_the_roster():
    from app.services.client_order_lines import is_line_on_active_roster

    assert is_line_on_active_roster(
        _order("active", _TODAY + timedelta(days=10)), _TODAY + timedelta(days=90)
    )


def test_line_ended_before_the_order_leaves_the_roster():
    from app.services.client_order_lines import is_line_on_active_roster

    assert not is_line_on_active_roster(
        _order("active", _LAST_MONTH_LAST), _TODAY + timedelta(days=90)
    )


def test_whole_expired_order_keeps_its_roster():
    """Wygasłe zamówienie NIE może wyrzucić całej obsady do „Zakończonych".

    Linia dziedziczy `end_date` grupy (`_build_line`), więc porównanie z samym
    „dziś" opróżniałoby aktywną obsadę każdego zamówienia czekającego na
    przedłużenie — łącznie z ludźmi, którzy dalej pracują.
    """
    from app.services.client_order_lines import is_line_on_active_roster

    expired = _TODAY - timedelta(days=5)
    assert is_line_on_active_roster(_order("active", expired), expired)
    # Kto zszedł WCZEŚNIEJ niż zamówienie, schodzi z obsady także tutaj.
    assert not is_line_on_active_roster(
        _order("active", expired - timedelta(days=30)), expired
    )


def test_open_ended_order_uses_today_as_the_boundary():
    from app.services.client_order_lines import is_line_on_active_roster

    assert not is_line_on_active_roster(
        _order("active", _TODAY - timedelta(days=1)), None
    )
    assert is_line_on_active_roster(_order("active", _TODAY), None)


def test_closed_and_cancelled_lines_are_never_on_the_roster():
    from app.services.client_order_lines import is_line_on_active_roster

    future = _TODAY + timedelta(days=90)
    assert not is_line_on_active_roster(_order("completed", None), future)
    assert not is_line_on_active_roster(_order("cancelled", None), future)
    assert not is_line_on_active_roster(_order("draft", None), future)


# ── Karta zamówienia ────────────────────────────────────────────────────────


async def test_consultant_with_a_saved_end_date_leaves_the_active_roster(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Zapisanie daty zejścia wystarcza — status linii zostaje `active`."""
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus

    client_id, contracts, _ = await _seed_client_with_contracts(2)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        [_md_line(contracts[0]), _md_line(contracts[1])],
        end_date=(_TODAY + timedelta(days=90)).isoformat(),
    )
    departed_id = _line_by_contract(group, contracts[0])["id"]

    resp = await app_client.patch(
        f"/api/clients/{client_id}/order-groups/{group['id']}/lines/{departed_id}",
        json={"end_date": _LAST_MONTH_LAST.isoformat()},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_active"] is False

    fresh = await _read_group(app_client, app_auth_headers, client_id, group["id"])
    assert _line_by_contract(fresh, contracts[0])["is_active"] is False
    assert _line_by_contract(fresh, contracts[1])["is_active"] is True, (
        "reszta obsady musi zostać w „Aktywnych"
    )
    assert fresh["active_consultants"] == 1

    async with AsyncSessionLocal() as db:
        stored = await db.get(ClientOrder, departed_id)
    assert stored.status == ClientOrderStatus.active, (
        "status w bazie musi zostać aktywny — od niego zależy import zużycia"
    )


async def test_departed_consultant_keeps_usage_and_still_gets_a_late_import(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Raport za poprzedni miesiąc, wrzucony po zejściu, dalej się dolicza.

    Kryterium 3 i 5 ticketu naraz: import widzi linię (`active_md_lines`),
    `md_used` osoby rośnie, a sumy zamówienia liczą się tą samą metodą co
    przed jej zejściem.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder
    from app.services.client_order_lines import active_md_lines, upsert_consumption

    client_id, contracts, _ = await _seed_client_with_contracts(2)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        [_md_line(contracts[0]), _md_line(contracts[1])],
        end_date=(_TODAY + timedelta(days=90)).isoformat(),
    )
    before = await _read_group(app_client, app_auth_headers, client_id, group["id"])
    positions_before = before["md_positions_total"]
    departed_id = _line_by_contract(group, contracts[0])["id"]

    resp = await app_client.patch(
        f"/api/clients/{client_id}/order-groups/{group['id']}/lines/{departed_id}",
        json={"end_date": _LAST_MONTH_LAST.isoformat()},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text

    async with AsyncSessionLocal() as db:
        matches = await active_md_lines(db, _LAST_MONTH)
        assert departed_id in {m.order.id for m in matches}, (
            "linia zdjęta z obsady wypadła z importu zużycia za miesiąc, "
            "w którym osoba jeszcze pracowała"
        )
        order = await db.get(ClientOrder, departed_id)
        await upsert_consumption(
            db, order=order, period_month=_LAST_MONTH, md_reported=Decimal("12")
        )
        await db.commit()

    after = await _read_group(app_client, app_auth_headers, client_id, group["id"])
    departed = _line_by_contract(after, contracts[0])
    assert departed["is_active"] is False
    assert Decimal(str(departed["md_used"])) == Decimal("12")
    assert after["md_used_total"] is not None
    assert Decimal(str(after["md_used_total"])) == Decimal("12"), (
        "zużycie osoby po zejściu musi nadal wchodzić do sumy zamówienia"
    )
    assert after["md_positions_total"] == positions_before, (
        "wartość zamówienia nie może się zmienić przez samo zejście osoby"
    )


async def test_departed_line_reports_its_end_and_keeps_the_swap_gate(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Wiersz w „Zakończonych" niesie datę zejścia; serwer nadal pozwala na zamianę.

    `cooperation_ended_on` było czyszczone dla każdej linii `active`, więc
    osoba po zejściu opisywała się w interfejsie jako „Konsultant".
    """
    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        [_md_line(contracts[0])],
        end_date=(_TODAY + timedelta(days=90)).isoformat(),
    )
    line = group["lines"][0]

    resp = await app_client.patch(
        f"/api/clients/{client_id}/order-groups/{group['id']}/lines/{line['id']}",
        json={"end_date": _LAST_MONTH_LAST.isoformat()},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text

    fresh = await _read_group(app_client, app_auth_headers, client_id, group["id"])
    departed = fresh["lines"][0]
    assert departed["is_active"] is False
    assert departed["end_date"] == _LAST_MONTH_LAST.isoformat()
    assert departed["status"] == "active", (
        "bramka zamiany po stronie serwera pyta o status, nie o obsadę"
    )
