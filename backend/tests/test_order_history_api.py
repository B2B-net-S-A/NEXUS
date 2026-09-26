"""Historia zamówienia, okno „Zużycie MD" i „Importy MD" — API (ticket 7, 25.09.2026).

* ``GET …/order-groups/{g}/history`` — jeden wpis na import, seria edycji
  jednej osoby w 15 minut = jeden wpis, bez pojedynczych zejść MD i pól
  technicznych; zdublowany zapis systemowy raz;
* edycja linii zapisuje realne zmiany „przed → po", a zapis identycznych
  wartości nie zostawia wpisu;
* techniczne zmiany pól linii są w Timeline kontraktu, z polskimi nazwami;
* ``GET …/consumptions`` niesie saldo po miesiącu, źródło, numer z importu
  i korekty pod miesiącem;
* ``GET /api/clients/{id}/md-imports[/{import_id}]`` pokazuje wyłącznie
  wiersze tego klienta.

Nazwiska, numery i liczby są zmyślone (repo jest publiczne).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.core.scheduling import business_today
from tests.test_multi_consultant_orders import (
    _enable_for,
    _line_payload,
    _seed_client_with_contracts,
)

pytestmark = pytest.mark.asyncio


async def _create_md_group(
    app_client: AsyncClient, headers: dict, client_id: int, lines: list[dict]
) -> dict:
    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups",
        json={
            "order_number": f"45000{uuid.uuid4().int % 100000:05d}",
            "start_date": (business_today() - timedelta(days=10)).isoformat(),
            "order_type": "md",
            "md_budget_mode": "per_person",
            "lines": lines,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _history(app_client: AsyncClient, headers: dict, client_id: int, group_id: int):
    resp = await app_client.get(
        f"/api/clients/{client_id}/order-groups/{group_id}/history", headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _record(group_id: int, **kwargs) -> None:
    from app.core.database import AsyncSessionLocal
    from app.services.client_order_lines import record_event

    async with AsyncSessionLocal() as db:
        record_event(db, group_id=group_id, **kwargs)
        await db.commit()


async def test_line_edit_records_before_and_after_and_skips_unchanged_values(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_for(monkeypatch, client_id)
    group = await _create_md_group(
        app_client, app_auth_headers, client_id, [_line_payload(contracts[0])]
    )
    line = group["lines"][0]
    url = f"/api/clients/{client_id}/order-groups/{group['id']}/lines/{line['id']}"

    changed = await app_client.patch(
        url, json={"rate_cost": 1100}, headers=app_auth_headers
    )
    assert changed.status_code == 200, changed.text
    # Formularz odsyła komplet pól — zapis tych samych wartości to nie zmiana.
    same = await app_client.patch(
        url, json={"rate_cost": 1100, "end_date": None}, headers=app_auth_headers
    )
    assert same.status_code == 200, same.text

    events = await app_client.get(
        f"/api/clients/{client_id}/order-groups/{group['id']}/events",
        headers=app_auth_headers,
    )
    edits = [e for e in events.json()["events"] if e["event_type"] == "edycja_reczna"]
    assert len(edits) == 1, "zapis bez zmian zostawił wpis w dzienniku"
    assert edits[0]["payload"]["diff"] == {
        "stawka kosztowa": ["1 000 zł/MD", "1 100 zł/MD"]
    }
    assert "stawka kosztowa" in edits[0]["payload"]["changed"]

    history = await _history(app_client, app_auth_headers, client_id, group["id"])
    entry = next(e for e in history["entries"] if e["category"] == "edits")
    assert entry["changes"] == [
        {"label": "stawka kosztowa", "before": "1 000 zł/MD", "after": "1 100 zł/MD"}
    ]
    assert entry["balance_after"] == 50
    assert entry["person_name"] in history["people"]


async def test_history_groups_imports_and_edit_series_and_hides_noise(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    client_id, contracts, _ = await _seed_client_with_contracts(2)
    _enable_for(monkeypatch, client_id)
    group = await _create_md_group(
        app_client,
        app_auth_headers,
        client_id,
        [_line_payload(contracts[0]), _line_payload(contracts[1])],
    )
    gid = group["id"]
    first, second = (line["id"] for line in group["lines"])

    for order_id, md in ((first, "10"), (second, "15")):
        await _record(
            gid,
            order_id=order_id,
            event_type="import_md",
            description=f"Za sierpień zużyto {md} MD",
            payload={
                "import_id": 991_000 + gid,
                "period_month": "2026-08",
                "md_applied": md,
                "md_remaining": "40",
            },
        )
    # Pojedyncze ręczne zejście — ma zostać w oknie „Zużycie MD", nie tutaj.
    await _record(
        gid,
        order_id=first,
        event_type="edycja_reczna",
        description="zejście MD",
        payload={
            "changed": ["zejście MD"],
            "period_month": "2026-08",
            "md_reported": "9",
            "previous": "10",
            "md_remaining": "41",
        },
    )
    # Techniczna zmiana pola — tylko Timeline kontraktu.
    await _record(
        gid,
        order_id=second,
        event_type="edycja_reczna",
        description="zmieniono: rate_candidate_currency",
        payload={"changed": ["rate_candidate_currency"], "md_remaining": "35"},
    )

    history = await _history(app_client, app_auth_headers, client_id, gid)
    imports = [e for e in history["entries"] if e["event_type"] == "import_md"]
    assert len(imports) == 1
    assert imports[0]["summary"] == "Import MD za sierpień 2026 – 2 osoby, 25 MD"
    assert imports[0]["import_id"] == 991_000 + gid
    assert not [e for e in history["entries"] if e["category"] == "edits"]
    for entry in history["entries"]:
        assert "rate_candidate_currency" not in entry["summary"]

    card = await app_client.get(
        f"/api/clients/{client_id}/order-groups", headers=app_auth_headers
    )
    listed = next(g for g in card.json()["groups"] if g["id"] == gid)
    assert listed["event_count"] == len(history["entries"])


async def test_identical_system_event_in_one_transaction_is_written_once(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from sqlalchemy import func, select

    from app.core.database import AsyncSessionLocal
    from app.models.client_order_group import ClientOrderGroupEvent
    from app.services.client_order_lines import record_event

    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_for(monkeypatch, client_id)
    group = await _create_md_group(
        app_client, app_auth_headers, client_id, [_line_payload(contracts[0])]
    )
    payload = {"reason": "md_exhausted", "automatic": True, "lines": 1}
    async with AsyncSessionLocal() as db:
        a = record_event(
            db,
            group_id=group["id"],
            event_type="zakonczenie",
            description="Zakończono zamówienie",
            payload=payload,
        )
        b = record_event(
            db,
            group_id=group["id"],
            event_type="zakonczenie",
            description="Zakończono zamówienie",
            payload=dict(payload),
        )
        assert a is b
        await db.commit()
        count = await db.scalar(
            select(func.count(ClientOrderGroupEvent.id)).where(
                ClientOrderGroupEvent.group_id == group["id"],
                ClientOrderGroupEvent.event_type == "zakonczenie",
            )
        )
    assert count == 1


async def test_technical_field_changes_are_in_the_contract_timeline_in_polish(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_for(monkeypatch, client_id)
    group = await _create_md_group(
        app_client, app_auth_headers, client_id, [_line_payload(contracts[0])]
    )
    line = group["lines"][0]
    await _record(
        group["id"],
        order_id=line["id"],
        event_type="edycja_reczna",
        description="zmiana waluty",
        payload={
            "changed": ["waluta stawki kosztowej"],
            "diff": {},
            "technical": {"waluta stawki kosztowej": ["PLN", "EUR"]},
            "md_remaining": "50",
        },
    )

    history = await _history(app_client, app_auth_headers, client_id, group["id"])
    assert not [e for e in history["entries"] if e["category"] == "edits"]

    resp = await app_client.get(
        f"/api/contracts/{contracts[0]}/activities", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    entry = next(a for a in resp.json() if a["action"] == "order_line_fields_changed")
    assert entry["details"]["fields"] == ["waluta stawki kosztowej"]
    assert entry["details"]["changes"] == ["waluta stawki kosztowej: PLN → EUR"]
    assert entry["details"]["order_number"] == group["order_number"]


async def test_consumption_window_has_balance_source_and_corrections(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_for(monkeypatch, client_id)
    group = await _create_md_group(
        app_client, app_auth_headers, client_id, [_line_payload(contracts[0])]
    )
    line = group["lines"][0]
    base = f"/api/clients/{client_id}/order-groups/{group['id']}/lines/{line['id']}/consumptions"
    for month, md in (("2026-06", 20), ("2026-07", 25), ("2026-07", 40)):
        resp = await app_client.put(
            f"{base}/{month}", json={"md_reported": md}, headers=app_auth_headers
        )
        assert resp.status_code == 200, resp.text

    body = (await app_client.get(base, headers=app_auth_headers)).json()
    assert body["order_number"] == group["order_number"]
    assert body["md_budget"] == 50
    assert body["md_used"] == 60
    assert body["md_remaining"] == -10
    june, july = body["rows"]
    assert (june["period_month"], june["balance_after"]) == ("2026-06", 30)
    assert (july["period_month"], july["balance_after"]) == ("2026-07", -10)
    assert july["source_kind"] == "manual"
    assert [(c["from_md"], c["to_md"]) for c in july["corrections"]] == [
        (None, 25),
        (25, 40),
    ]

    groups = await app_client.get(
        f"/api/clients/{client_id}/order-groups", headers=app_auth_headers
    )
    read = next(
        ln
        for g in groups.json()["groups"]
        if g["id"] == group["id"]
        for ln in g["lines"]
    )
    assert read["consumption_recent"] == [
        {"period_month": "2026-06", "md": 20},
        {"period_month": "2026-07", "md": 40},
    ]
    assert "negative_balance" in read["consumption_flags"]


async def test_client_md_imports_show_only_this_clients_rows(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.core.database import AsyncSessionLocal
    from app.models.md_consumption import MdConsumptionImport, MdConsumptionImportRow

    client_a, contracts_a, _ = await _seed_client_with_contracts(1)
    client_b, contracts_b, _ = await _seed_client_with_contracts(1)
    _enable_for(monkeypatch, client_a, client_b)
    group_a = await _create_md_group(
        app_client, app_auth_headers, client_a, [_line_payload(contracts_a[0])]
    )
    group_b = await _create_md_group(
        app_client, app_auth_headers, client_b, [_line_payload(contracts_b[0])]
    )
    line_a = group_a["lines"][0]["id"]
    line_b = group_b["lines"][0]["id"]
    other_client_name = f"Obca-{uuid.uuid4().hex[:6]}"

    async with AsyncSessionLocal() as db:
        batch = MdConsumptionImport(period_month="2026-08", filename="zuzycie.xlsx")
        db.add(batch)
        await db.flush()
        db.add_all(
            [
                MdConsumptionImportRow(
                    import_id=batch.id,
                    row_number=2,
                    consultant_name="Osoba A",
                    md_reported=Decimal("10"),
                    status="applied",
                    matched_order_id=line_a,
                    order_number_hint=group_a["order_number"],
                ),
                MdConsumptionImportRow(
                    import_id=batch.id,
                    row_number=3,
                    consultant_name="Osoba A",
                    md_reported=Decimal("19"),
                    status="applied",
                    matched_order_id=line_a,
                    order_number_hint="4599999999",
                ),
                MdConsumptionImportRow(
                    import_id=batch.id,
                    row_number=4,
                    consultant_name=other_client_name,
                    md_reported=Decimal("7"),
                    status="applied",
                    matched_order_id=line_b,
                ),
                # Faktura zaksięgowana u klienta B z numerem klienta A w „Uwagach"
                # — nadal wiersz B (przegląd 25.09.2026: wyciek kwot).
                MdConsumptionImportRow(
                    import_id=batch.id,
                    row_number=5,
                    consultant_name=other_client_name,
                    md_reported=Decimal("0"),
                    status="cost_only",
                    cost_status="applied",
                    matched_group_id=group_b["id"],
                    order_number_hint=group_a["order_number"],
                    invoice_amount=Decimal("50000"),
                ),
                # Numer, w którym numer A tylko SIĘ ZAWIERA, to inny numer.
                MdConsumptionImportRow(
                    import_id=batch.id,
                    row_number=6,
                    consultant_name=other_client_name,
                    md_reported=Decimal("3"),
                    status="unmatched",
                    order_number_hint=group_a["order_number"] + "1",
                ),
            ]
        )
        other = MdConsumptionImport(period_month="2026-07", filename="inny.xlsx")
        db.add(other)
        await db.flush()
        db.add(
            MdConsumptionImportRow(
                import_id=other.id,
                row_number=2,
                consultant_name=other_client_name,
                md_reported=Decimal("5"),
                status="applied",
                matched_order_id=line_b,
            )
        )
        await db.commit()
        batch_id, other_id = batch.id, other.id

    listing = await app_client.get(
        f"/api/clients/{client_a}/md-imports", headers=app_auth_headers
    )
    assert listing.status_code == 200, listing.text
    ids = [i["id"] for i in listing.json()["imports"]]
    assert batch_id in ids and other_id not in ids
    summary = next(i for i in listing.json()["imports"] if i["id"] == batch_id)
    assert (summary["rows_total"], summary["rows_booked"]) == (2, 2)

    detail = await app_client.get(
        f"/api/clients/{client_a}/md-imports/{batch_id}", headers=app_auth_headers
    )
    assert detail.status_code == 200, detail.text
    rows = detail.json()["rows"]
    assert [r["row_number"] for r in rows] == [2, 3]
    assert other_client_name not in detail.text
    assert [r["number_mismatch"] for r in rows] == [False, True]
    assert all(r["target_order_number"] == group_a["order_number"] for r in rows)
    assert all(r["state"] == "booked" for r in rows)

    missing = await app_client.get(
        f"/api/clients/{client_a}/md-imports/{other_id}", headers=app_auth_headers
    )
    assert missing.status_code == 404

    # Okno zużycia osoby A: numer z importu i ostrzeżenie o obcym numerze.
    await app_client.put(
        f"/api/clients/{client_a}/order-groups/{group_a['id']}/lines/{line_a}"
        "/consumptions/2026-08",
        json={"md_reported": 29},
        headers=app_auth_headers,
    )
    window = await app_client.get(
        f"/api/clients/{client_a}/order-groups/{group_a['id']}/lines/{line_a}/consumptions",
        headers=app_auth_headers,
    )
    body = window.json()
    (row,) = body["rows"]
    assert [r["order_number_hint"] for r in row["import_rows"]] == [
        group_a["order_number"],
        "4599999999",
    ]
    assert row["source_kind"] == "manual_correction"
    assert [(w["order_number"], w["md"]) for w in body["foreign_import_warnings"]] == [
        ("4599999999", 19)
    ]


async def test_client_md_imports_unbooked_row_needs_binding_number_and_own_person(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Runda 7 (R7-N4-2): wiersz niezaksięgowany jest wierszem klienta A tylko
    przy numerze A, który wiąże, i osobie z linią u A. Osoba innego klienta
    z tym samym numerem w „Uwagach" nie wychodzi (nazwisko i kwota faktury)."""
    from app.core.database import AsyncSessionLocal
    from app.models.md_consumption import MdConsumptionImport, MdConsumptionImportRow

    client_a, contracts_a, names_a = await _seed_client_with_contracts(1)
    client_b, contracts_b, names_b = await _seed_client_with_contracts(1)
    _enable_for(monkeypatch, client_a, client_b)
    group_a = await _create_md_group(
        app_client, app_auth_headers, client_a, [_line_payload(contracts_a[0])]
    )
    await _create_md_group(
        app_client, app_auth_headers, client_b, [_line_payload(contracts_b[0])]
    )

    async with AsyncSessionLocal() as db:
        batch = MdConsumptionImport(period_month="2026-08", filename="zuzycie.xlsx")
        db.add(batch)
        await db.flush()
        db.add_all(
            [
                MdConsumptionImportRow(
                    import_id=batch.id,
                    row_number=2,
                    consultant_name=names_a[0],
                    md_reported=Decimal("4"),
                    status="unmatched",
                    order_number_hint=group_a["order_number"],
                ),
                MdConsumptionImportRow(
                    import_id=batch.id,
                    row_number=3,
                    consultant_name=names_b[0],
                    md_reported=Decimal("0"),
                    status="cost_only",
                    cost_status="unmatched_consultant",
                    order_number_hint=group_a["order_number"],
                    invoice_amount=Decimal("41000"),
                ),
            ]
        )
        await db.commit()
        batch_id = batch.id

    detail = await app_client.get(
        f"/api/clients/{client_a}/md-imports/{batch_id}", headers=app_auth_headers
    )
    assert detail.status_code == 200, detail.text
    assert [r["row_number"] for r in detail.json()["rows"]] == [2]
    assert names_b[0] not in detail.text

    other = await app_client.get(
        f"/api/clients/{client_b}/md-imports/{batch_id}", headers=app_auth_headers
    )
    assert other.status_code == 404
