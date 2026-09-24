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
from app.core.scheduling import business_today

pytestmark = pytest.mark.asyncio


#: Miesiąc importu musi zachodzić na okres linii — inaczej `md_lines_settling_in_month`
#: nie zwraca nic i test „przechodzi" z zerem zmian.
def _period():
    return business_today().strftime("%Y-%m")


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
                start_date=business_today() - timedelta(days=30),
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
        "start_date": (business_today() - timedelta(days=10)).isoformat(),
    }


async def _create_group(
    app_client: AsyncClient, headers: dict, client_id: int, lines: list[dict]
) -> dict:
    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups",
        json={
            "order_number": f"445-{uuid.uuid4().hex[:4]}",
            "start_date": (business_today() - timedelta(days=10)).isoformat(),
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


async def _import(
    app_client: AsyncClient, headers: dict, payload: bytes, period: str | None = None
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
        data={"period_month": period or _period()},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _next_month_first():
    """Pierwszy dzień przyszłego miesiąca — start kontynuacji w testach podziału.

    Audyt 24.09.2026 (W4): nadwyżka przechodzi wyłącznie na następcę, który
    ROZLICZA miesiąc raportu. Testy, w których kontynuacja ma czekać
    (niezmaterializowana), zaczynają ją pierwszego dnia przyszłego miesiąca
    i importują TEN miesiąc — okres poprzednika go obejmuje, kontynuacji też.
    """
    today = business_today()
    return (date(today.year, today.month, 1) + timedelta(days=32)).replace(day=1)


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

    detail = await _import(app_client, finance, _sheet([(names[0], 15), (names[0], 5)]))
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
    client_id, contracts, names = await _seed_client_with_contracts(2, same_name=True)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        [_md_line(contracts[0], 50), _md_line(contracts[1], 50)],
    )
    finance = await _finance_headers(app_client)

    detail = await _import(app_client, finance, _sheet([(names[0], 15), (names[0], 5)]))
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


# ── Podział zużycia między zamówieniem bieżącym a kontynuacją ───────────────
#
# Konsultant nie przestaje pracować w dniu, w którym kończy się budżet MD.
# Raport przychodzi jedną liczbą za cały miesiąc, więc nadwyżka ponad budżet
# należy do zamówienia-następcy — zostawiona na bieżącym pokazywałaby
# przekroczenie na zamówieniu, które klient już zamknął, a nowe stałoby puste.


async def _extend(
    app_client: AsyncClient,
    headers: dict,
    client_id: int,
    group_id: int,
    *,
    start,
    lines: list[dict],
) -> dict:
    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group_id}/extend",
        json={
            "order_number": f"NEXT-{uuid.uuid4().hex[:4]}",
            "start_date": start.isoformat(),
            "lines": lines,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _events(app_client: AsyncClient, headers: dict, client_id: int, gid: int):
    resp = await app_client.get(
        f"/api/clients/{client_id}/order-groups/{gid}/events", headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["events"]


async def _line_of(app_client: AsyncClient, headers: dict, client_id: int, gid: int):
    listing = await app_client.get(
        f"/api/clients/{client_id}/order-groups", headers=headers
    )
    assert listing.status_code == 200, listing.text
    everything = []
    for group in listing.json()["groups"]:
        everything.append(group)
        everything.extend(group.get("future_orders") or [])
    group = next(g for g in everything if g["id"] == gid)
    return group["lines"][0]


async def test_md_beyond_the_budget_flows_onto_the_continuation(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """20 MD budżetu, 30 MD w raporcie → 20 tu, 10 na kontynuacji.

    Kontynuacja startuje w PRZESZŁOŚCI i mimo to czekała: zamówienie MD kończy
    budżet, nie kalendarz. Dopiero wyzerowanie budżetu przez ten import
    przepuszcza ją przez materializator — dokładnie sekwencja ze zgłoszenia.
    """
    client_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_md_line(contracts[0], 20)]
    )
    successor_start = business_today() - timedelta(days=5)
    successor = await _extend(
        app_client,
        app_auth_headers,
        client_id,
        group["id"],
        start=successor_start,
        lines=[
            dict(
                _md_line(contracts[0], 50),
                start_date=successor_start.isoformat(),
            )
        ],
    )
    assert successor["status"] == "scheduled", "kontynuacja ruszyła mimo budżetu MD"

    finance = await _finance_headers(app_client)
    detail = await _import(app_client, finance, _sheet([(names[0], 30)]))
    assert detail["rows_applied"] == 1, detail

    current_line = await _line_of(app_client, app_auth_headers, client_id, group["id"])
    next_line = await _line_of(app_client, app_auth_headers, client_id, successor["id"])
    assert current_line["md_remaining"] == pytest.approx(0.0)
    assert current_line["is_active"] is False
    assert next_line["md_remaining"] == pytest.approx(40.0)
    assert next_line["is_active"] is True, "kontynuacja nie przejęła zamówienia"

    ours = [
        e
        for e in await _events(app_client, app_auth_headers, client_id, group["id"])
        if e["event_type"] == "transfer_md"
    ]
    theirs = [
        e
        for e in await _events(app_client, app_auth_headers, client_id, successor["id"])
        if e["event_type"] == "transfer_md"
    ]
    assert len(ours) == 1 and len(theirs) == 1, "podział ma ślad po OBU stronach"
    assert successor["order_number"] in ours[0]["description"]
    assert group["order_number"] in theirs[0]["description"]
    # Odsyłacz jedzie POZA `payload`, bo ten znika rolom bez VIEW_FINANCE.
    assert ours[0]["related_group_id"] == successor["id"]
    assert ours[0]["related_order_number"] == successor["order_number"]
    assert theirs[0]["related_group_id"] == group["id"]
    assert theirs[0]["related_order_number"] == group["order_number"]
    assert ours[0]["payload"]["md_transferred"] == "10.000000"


async def test_reimporting_the_split_month_does_not_move_md_twice(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Podział musi być idempotentny tak samo jak sam ``md_remaining``.

    Pojemność linii liczona Z UWZGLĘDNIENIEM bieżącego miesiąca widziałaby
    własny, poprzedni zapis jako zużycie i przy każdym powtórzeniu importu
    przesuwała na następcę kolejne MD.
    """
    client_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_md_line(contracts[0], 20)]
    )
    successor_start = _next_month_first()
    period = successor_start.strftime("%Y-%m")
    successor = await _extend(
        app_client,
        app_auth_headers,
        client_id,
        group["id"],
        start=successor_start,
        lines=[
            dict(
                _md_line(contracts[0], 50),
                start_date=successor_start.isoformat(),
            )
        ],
    )
    finance = await _finance_headers(app_client)
    payload = _sheet([(names[0], 30)])

    await _import(app_client, finance, payload, period)
    await _import(app_client, finance, payload, period)

    next_line = await _line_of(app_client, app_auth_headers, client_id, successor["id"])
    assert next_line["md_remaining"] == pytest.approx(40.0)


async def test_reimport_after_materialization_does_not_double_count(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Audyt 22.09 r2 (FIN-MD-01): po materializacji następca jest ``active``,
    więc powtórka importu dopasowywała wiersz do NASTĘPCY i zapisywała na nim
    pełne 30 MD — a 20 MD poprzednika za ten sam miesiąc zostawało (MD liczone
    dwa razy, następcy zostawało 20 zamiast 40)."""
    client_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_md_line(contracts[0], 20)]
    )
    successor_start = business_today() - timedelta(days=5)
    successor = await _extend(
        app_client,
        app_auth_headers,
        client_id,
        group["id"],
        start=successor_start,
        lines=[
            dict(
                _md_line(contracts[0], 50),
                start_date=successor_start.isoformat(),
            )
        ],
    )
    finance = await _finance_headers(app_client)
    payload = _sheet([(names[0], 30)])

    first = await _import(app_client, finance, payload)
    assert first["rows_applied"] == 1, first
    assert (await _line_of(app_client, app_auth_headers, client_id, successor["id"]))[
        "is_active"
    ] is True, "kontynuacja powinna się zmaterializować"

    second = await _import(app_client, finance, payload)
    assert second["rows_applied"] == 1, second

    current_line = await _line_of(app_client, app_auth_headers, client_id, group["id"])
    next_line = await _line_of(app_client, app_auth_headers, client_id, successor["id"])
    assert current_line["md_remaining"] == pytest.approx(0.0)
    assert next_line["md_remaining"] == pytest.approx(40.0)


async def test_raising_the_budget_takes_the_md_back_from_the_continuation(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Po podniesieniu budżetu nadwyżki nie ma — stary wiersz musi zejść do zera.

    Zostawienie go policzyłoby te same MD na obu zamówieniach naraz, a linia
    następcy nie ma jak tego pokazać: jej pozostałość po prostu byłaby zaniżona.
    """
    client_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_md_line(contracts[0], 20)]
    )
    successor_start = _next_month_first()
    period = successor_start.strftime("%Y-%m")
    successor = await _extend(
        app_client,
        app_auth_headers,
        client_id,
        group["id"],
        start=successor_start,
        lines=[
            dict(
                _md_line(contracts[0], 50),
                start_date=successor_start.isoformat(),
            )
        ],
    )
    finance = await _finance_headers(app_client)
    payload = _sheet([(names[0], 30)])
    await _import(app_client, finance, payload, period)
    assert (await _line_of(app_client, app_auth_headers, client_id, successor["id"]))[
        "md_remaining"
    ] == pytest.approx(40.0)

    raised = await app_client.patch(
        f"/api/clients/{client_id}/order-groups/{group['id']}"
        f"/lines/{group['lines'][0]['id']}",
        json={"input_mode": "md", "input_value": 50, "rate_revenue": 1200},
        headers=app_auth_headers,
    )
    assert raised.status_code == 200, raised.text
    await _import(app_client, finance, payload, period)

    current_line = await _line_of(app_client, app_auth_headers, client_id, group["id"])
    next_line = await _line_of(app_client, app_auth_headers, client_id, successor["id"])
    assert current_line["md_remaining"] == pytest.approx(20.0)
    assert next_line["md_remaining"] == pytest.approx(50.0)


async def test_overflow_stays_put_when_there_is_no_continuation(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Następcy nie wymyślamy — przekroczenie zostaje widoczne na linii."""
    client_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_md_line(contracts[0], 20)]
    )
    finance = await _finance_headers(app_client)
    await _import(app_client, finance, _sheet([(names[0], 30)]))

    line = await _line_of(app_client, app_auth_headers, client_id, group["id"])
    assert line["md_remaining"] == pytest.approx(-10.0)
    events = await _events(app_client, app_auth_headers, client_id, group["id"])
    assert not [e for e in events if e["event_type"] == "transfer_md"]


async def test_manual_assignment_splits_the_same_way_as_the_batch_import(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Ręczne rozstrzygnięcie idzie tą samą ścieżką co import wsadowy.

    Druga ścieżka jest łatwa do przeoczenia: gdyby ominęła podział, wynik
    zależałby od tego, czy arkusz był jednoznaczny — czyli od danych, a nie
    od reguły.
    """
    client_id, contracts, names = await _seed_client_with_contracts(2, same_name=True)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        [_md_line(contracts[0], 20), _md_line(contracts[1], 50)],
    )
    successor_start = _next_month_first()
    period = successor_start.strftime("%Y-%m")
    successor = await _extend(
        app_client,
        app_auth_headers,
        client_id,
        group["id"],
        start=successor_start,
        lines=[
            dict(
                _md_line(contracts[0], 50),
                start_date=successor_start.isoformat(),
            )
        ],
    )
    finance = await _finance_headers(app_client)
    detail = await _import(app_client, finance, _sheet([(names[0], 30)]), period)
    assert detail["rows_ambiguous"] == 1, detail

    target = next(
        line for line in group["lines"] if line["md_total"] == pytest.approx(20.0)
    )
    resp = await app_client.post(
        f"/api/md-consumption/imports/{detail['id']}/rows/{detail['rows'][0]['id']}"
        "/assign",
        json={"order_id": target["id"]},
        headers=finance,
    )
    assert resp.status_code == 200, resp.text

    next_line = await _line_of(app_client, app_auth_headers, client_id, successor["id"])
    assert next_line["md_remaining"] == pytest.approx(40.0)


async def test_import_entry_names_the_order_and_the_counter(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Wpis „Import MD" musi powiedzieć, z KTÓREJ puli zeszły te MD.

    Ten sam konsultant bywa obsadzony na kolejnych zamówieniach klienta, więc
    sam miesiąc i liczba MD nie wystarczają do rozliczenia faktury.
    """
    client_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_md_line(contracts[0], 50)]
    )
    finance = await _finance_headers(app_client)
    await _import(app_client, finance, _sheet([(names[0], 20)]))

    entry = next(
        e
        for e in await _events(app_client, app_auth_headers, client_id, group["id"])
        if e["event_type"] == "import_md"
    )
    assert group["order_number"] in entry["description"]
    assert "wykorzystano 20 / pozostało 30 MD" in entry["description"]
    # Miesiąc słownie, nie „2026-07" — wpis czyta człowiek.
    assert _period() not in entry["description"]


# ── Audyt 22.09 r2 (FIN-MD-07) ──────────────────────────────────────────────


async def test_assigning_an_old_row_does_not_overwrite_a_newer_or_manual_entry(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Przypisanie wiersza starszej paczki nadpisywało wpis ręczny / nowszy."""
    client_id, contracts, names = await _seed_client_with_contracts(2, same_name=True)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        [_md_line(contracts[0], 50), _md_line(contracts[1], 50)],
    )
    finance = await _finance_headers(app_client)
    old = await _import(app_client, finance, _sheet([(names[0], 15)]))
    assert old["rows_ambiguous"] == 1, old
    target = group["lines"][0]["id"]

    manual = await app_client.put(
        f"/api/clients/{client_id}/order-groups/{group['id']}"
        f"/lines/{target}/consumptions/{_period()}",
        json={"md_reported": 7, "status": "accepted"},
        headers=app_auth_headers,
    )
    assert manual.status_code == 200, manual.text

    resp = await app_client.post(
        f"/api/md-consumption/imports/{old['id']}/rows/{old['rows'][0]['id']}/assign",
        json={"order_id": target},
        headers=finance,
    )
    assert resp.status_code == 409, resp.text
    assert "ręczne rozliczenie" in resp.text

    body = await _group(app_client, app_auth_headers, client_id, group["id"])
    line = next(line for line in body["lines"] if line["id"] == target)
    assert line["md_remaining"] == pytest.approx(43.0)
