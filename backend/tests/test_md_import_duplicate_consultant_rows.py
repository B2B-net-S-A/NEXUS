"""Dwa wiersze tej samej osoby w jednym arkuszu MD SUMUJĄ się, nie nadpisują.

Klucz idempotencji zużycia to ``(linia, miesiąc)`` i zapis idzie przez
``INSERT … ON CONFLICT DO UPDATE``. Zapisywanie wiersz po wierszu zostawiało
więc MD z OSTATNIEGO wiersza, a wcześniejsze znikały — przy „15 MD" i „5 MD"
budżet tracił 15 dni. Objaw jest cichy podwójnie: oba wiersze i tak są
w podsumowaniu importu oznaczone jako „Zaktualizowano", a ponowny import tego
samego pliku niczego nie naprawia, bo nadal wygrywa ostatni wiersz.

Bratni przypadek dla kolumny FAKTUR jest pokryty w
``test_order_lifecycle_and_cost.py::test_two_rows_for_one_person_are_summed_not_overwritten``
— ta połowa pętli buforowała od początku. Linia kosztowa ma ``md_total IS NULL``,
więc tamten test nigdy nie przechodził przez ścieżkę MD.
"""

from __future__ import annotations

import io
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

_TODAY = date.today()
#: Miesiąc importu musi zachodzić na okres linii — inaczej `active_md_lines`
#: nie zwraca nic i test „przechodzi" z zerem zmian.
_PERIOD = _TODAY.strftime("%Y-%m")


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


async def _seed_client_with_contracts(
    n: int, *, same_name: bool = False
) -> tuple[int, list[int], list[str]]:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus

    suffix = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"MdDupClient-{suffix}")
        db.add(client)
        await db.commit()
        await db.refresh(client)

        contract_ids: list[int] = []
        names: list[str] = []
        for i in range(n):
            # Niejednoznaczność w arkuszu bierze się z DWÓCH osób o tym samym
            # imieniu i nazwisku — dopasowanie idzie wyłącznie po nim.
            lastname = f"Dublet-{suffix}" if same_name else f"Dublet-{suffix}-{i}"
            cand = Candidate(
                name="Jan",
                lastname=lastname,
                email=f"mddup-{suffix}-{i}@example.com",
            )
            db.add(cand)
            await db.commit()
            await db.refresh(cand)
            contract = Contract(
                candidate_id=cand.id,
                client_id=client.id,
                status=ContractStatus.active,
                start_date=_TODAY - timedelta(days=30),
                rate_candidate=Decimal("100.000"),
                rate_client=Decimal("150.000"),
            )
            db.add(contract)
            await db.commit()
            await db.refresh(contract)
            contract_ids.append(contract.id)
            names.append(f"{cand.name} {cand.lastname}")
        return client.id, contract_ids, names


def _md_line(contract_id: int, md_total: int = 50) -> dict:
    return {
        "contract_id": contract_id,
        "rate_cost": 1000,
        "rate_revenue": 1200,
        "input_mode": "md",
        "input_value": md_total,
        "start_date": (_TODAY - timedelta(days=10)).isoformat(),
    }


async def _create_group(
    app_client: AsyncClient, headers: dict, client_id: int, lines: list[dict]
) -> dict:
    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups",
        json={
            "order_number": f"445-{uuid.uuid4().hex[:4]}",
            "start_date": (_TODAY - timedelta(days=10)).isoformat(),
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
    email = f"mddup-fin-{suffix}@example.com"
    password = f"T3st_{suffix}!PassX"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name=f"MdDup Fin {suffix}",
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


async def _import(app_client: AsyncClient, headers: dict, payload: bytes) -> dict:
    resp = await app_client.post(
        "/api/md-consumption/imports",
        files={
            "file": (
                "raport.xlsx",
                payload,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={"period_month": _PERIOD},
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


async def test_two_md_rows_for_one_person_are_summed(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """15 + 5 = 20 odjętych MD, nie 5 z ostatniego wiersza."""
    client_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_md_line(contracts[0], 50)]
    )
    finance = await _finance_headers(app_client)

    detail = await _import(
        app_client, finance, _sheet([(names[0], 15), (names[0], 5)])
    )
    assert detail["rows_applied"] == 2, detail

    body = await _group(app_client, app_auth_headers, client_id, group["id"])
    assert body["lines"][0]["md_remaining"] == pytest.approx(30.0)


async def test_reimport_of_duplicated_rows_stays_idempotent(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Sumowanie nie może zamienić idempotencji `(linia, miesiąc)` w dodawanie."""
    client_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_md_line(contracts[0], 50)]
    )
    finance = await _finance_headers(app_client)
    payload = _sheet([(names[0], 15), (names[0], 5)])

    await _import(app_client, finance, payload)
    await _import(app_client, finance, payload)

    body = await _group(app_client, app_auth_headers, client_id, group["id"])
    assert body["lines"][0]["md_remaining"] == pytest.approx(30.0)


async def test_manual_assignment_adds_to_the_row_already_applied(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Rozstrzygnięcie drugiego wiersza nie może skasować MD pierwszego.

    Zapis idzie po kluczu (linia, miesiąc) i NADPISUJE, więc wysłanie samego
    ``row.md_reported`` kasowałoby MD wiersza rozstrzygniętego wcześniej.
    """
    client_id, contracts, names = await _seed_client_with_contracts(
        2, same_name=True
    )
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        [_md_line(contracts[0], 50), _md_line(contracts[1], 50)],
    )
    finance = await _finance_headers(app_client)

    detail = await _import(
        app_client, finance, _sheet([(names[0], 15), (names[0], 5)])
    )
    assert detail["rows_ambiguous"] == 2, detail

    target = group["lines"][0]["id"]
    for row in detail["rows"]:
        resp = await app_client.post(
            f"/api/md-consumption/imports/{detail['id']}/rows/{row['id']}/assign",
            json={"order_id": target},
            headers=finance,
        )
        assert resp.status_code == 200, resp.text

    body = await _group(app_client, app_auth_headers, client_id, group["id"])
    line = next(line for line in body["lines"] if line["id"] == target)
    assert line["md_remaining"] == pytest.approx(30.0)
