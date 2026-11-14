"""Środki trwałe (K6, 0703) — trasy z bazą.

Przełączniki (wyłączony moduł = 404, admin widzi), ewidencję zmieniają tylko
„Księgowi” i admin; OT z nowym środkiem i AM miesiąca w buforze przez
„Nalicz amortyzację” (idempotentnie), zatwierdzony AM blokuje parametry
planu, środek przyjęty wstecz i MT z datą w zamkniętym miesiącu; likwidacja
z odpisem za swój miesiąc i zapisem Wn 070 + 761 / Ma 010; kolejność
usuwania dokumentów środka; import ewidencji z Symfonii (podgląd, zapis,
duplikaty); konta modułu ustawia admin. Konta z losowym prefiksem, rok
obrotowy losowy z przyszłości, kwoty fikcyjne.
"""

from __future__ import annotations

import random
import uuid
from datetime import date

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, or_, select

from app.api import ledger as ledger_api
from app.api import ledger_assets as ledger_assets_api
from app.core.database import AsyncSessionLocal
from app.models.app_setting import AppSetting
from app.models.finance_posting import FinanceAccount
from app.models.ledger import LedgerDocument, LedgerLine, LedgerYear
from app.models.ledger_assets import LedgerAsset
from app.models.user import User
from app.services.ledger import settings as ledger_settings
from app.services.ledger import years as ledger_years
from tests.test_ledger_db import _headers, _purge_years, _set_ledger, _user

ACC = "/api/accounting"


@pytest_asyncio.fixture
async def client():
    app = FastAPI()
    app.include_router(ledger_api.router, prefix=ACC)
    app.include_router(ledger_assets_api.router, prefix=ACC)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as c:
        yield c


ACCOUNTS = {
    "fixed": ("010", "Środki trwałe", "other"),
    "intangible": ("020", "Wartości niematerialne i prawne", "other"),
    "dep_fixed": ("070", "Umorzenie środków trwałych", "other"),
    "dep_intangible": ("071", "Umorzenie WNiP", "other"),
    "intake": ("080", "Środki trwałe w budowie", "other"),
    "cost": ("401", "Amortyzacja", "cost"),
    "disposal": ("761", "Pozostałe koszty operacyjne", "other"),
    "settlement": ("490", "Rozliczenie kosztów", "other"),
    "client": ("501", "Koszty klientów", "cost"),
    "front": ("502", "Koszty Front office", "cost"),
    "back": ("503", "Koszty Back office", "cost"),
    "overhead": ("550", "Koszty ogólne", "cost"),
    "team": ("504", "Koszty zespołu", "cost"),
}


def _ledger_value(world, *, assets_open: bool = True, allocation: bool = True):
    acc = world["acc"]
    value = {
        "modules": {"ledger": True, "assets": assets_open},
        "accountants": [world["accountant"].id],
        "assets": {
            "cost_account": acc["cost"],
            "intake_account": acc["intake"],
            "disposal_account": acc["disposal"],
        },
    }
    if allocation:
        value["allocation"] = {
            "settlement_account": acc["settlement"],
            "client_account": acc["client"],
            "front_office_account": acc["front"],
            "back_office_account": acc["back"],
            "overhead_account": acc["overhead"],
            "team_account": acc["team"],
        }
    return value


@pytest_asyncio.fixture
async def world():
    prefix = f"T{random.randint(10_000, 99_999)}"
    async with AsyncSessionLocal() as db:
        year = random.randint(2050, 2099)
        while await db.scalar(select(LedgerYear.id).where(LedgerYear.year == year)):
            year = random.randint(2050, 2099)
        previous = await db.scalar(
            select(AppSetting.value).where(
                AppSetting.key == ledger_settings.SETTING_KEY
            )
        )
        admin = await _user(db, "admin")
        accountant = await _user(db, "finance")
        finance = await _user(db, "finance")
        recruiter = await _user(db, "recruiter")
        for number, name, kind in ACCOUNTS.values():
            db.add(FinanceAccount(number=f"{prefix}-{number}", name=name, kind=kind))
        await db.commit()
        await ledger_years.ensure_year(db, year, actor_id=admin.id)
        await db.commit()
    data = {
        "year": year,
        "prefix": prefix,
        "admin": admin,
        "accountant": accountant,
        "finance": finance,
        "recruiter": recruiter,
        "acc": {key: f"{prefix}-{value[0]}" for key, value in ACCOUNTS.items()},
    }
    await _set_ledger(_ledger_value(data))
    yield data
    users = [admin.id, accountant.id, finance.id, recruiter.id]
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(LedgerAsset).where(
                or_(
                    LedgerAsset.created_by.in_(users),
                    LedgerAsset.inventory_number.like(f"{prefix}/%"),
                )
            )
        )
        await db.commit()
    await _purge_years([year, year - 1])
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(FinanceAccount).where(FinanceAccount.number.like(f"{prefix}-%"))
        )
        await db.execute(delete(User).where(User.id.in_(users)))
        await db.commit()
    await _set_ledger(previous)


def _asset_body(world, **extra) -> dict:
    acc = world["acc"]
    body = {
        "name": "Stacje robocze projektowe",
        "kind": "fixed",
        "kst": "491",
        "accepted_on": date(world["year"], 1, 10).isoformat(),
        "initial_value": "24000.00",
        "asset_account": acc["fixed"],
        "depreciation_account": acc["dep_fixed"],
        "mpk": "OG",
        "balance_method": "linear",
        "balance_rate": "25",
        "tax_method": "linear",
        "tax_rate": "30",
    }
    body.update(extra)
    return body


async def _create(client, world, user: str = "accountant", **extra) -> dict:
    response = await client.post(
        f"{ACC}/assets", json=_asset_body(world, **extra), headers=_headers(world[user])
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _sync(client, world, month: int, user: str = "finance") -> dict:
    response = await client.post(
        f"{ACC}/assets/sync",
        json={"year": world["year"], "month": month},
        headers=_headers(world[user]),
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _doc(source_type: str, source_id: str) -> LedgerDocument | None:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(LedgerDocument).where(
                LedgerDocument.source_type == source_type,
                LedgerDocument.source_id == source_id,
                LedgerDocument.reversed_by_id.is_(None),
            )
        )


async def _lines(doc_id: int) -> list[tuple[str, str, int, str | None]]:
    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(LedgerLine)
            .where(LedgerLine.document_id == doc_id)
            .order_by(LedgerLine.line_no)
        )
        return [(row.side, row.account, row.amount, row.mpk) for row in rows]


async def _approve(client, world, doc_id: int) -> None:
    response = await client.post(
        f"{ACC}/documents/approve",
        json={"ids": [doc_id]},
        headers=_headers(world["accountant"]),
    )
    assert response.status_code == 200, response.text
    assert response.json()["approved"], response.text


def _month(world, month: int) -> str:
    return f"{world['year']}-{month:02d}"


# ── Moduł i uprawnienia ──────────────────────────────────────────────────────


async def test_module_off_hides_assets_but_admin_sees(client, world):
    await _set_ledger(_ledger_value(world, assets_open=False))
    query = {"year": world["year"], "month": 3}
    hidden = await client.get(
        f"{ACC}/assets", params=query, headers=_headers(world["finance"])
    )
    assert hidden.status_code == 404
    seen = await client.get(
        f"{ACC}/assets", params=query, headers=_headers(world["admin"])
    )
    assert seen.status_code == 200
    summary = await client.get(
        f"{ACC}/sources", params=query, headers=_headers(world["finance"])
    )
    assert summary.status_code == 200
    assert {item["kind"] for item in summary.json()["items"]}.isdisjoint(
        {"assets", "asset_docs"}
    )
    enabled = await client.put(
        f"{ACC}/config/modules",
        json={"module": "assets", "enabled": True},
        headers=_headers(world["admin"]),
    )
    assert enabled.status_code == 200, enabled.text


async def test_only_accountants_change_the_register(client, world):
    refused = await client.post(
        f"{ACC}/assets", json=_asset_body(world), headers=_headers(world["finance"])
    )
    assert refused.status_code == 403
    query = {"year": world["year"], "month": 1}
    assert (
        await client.get(
            f"{ACC}/assets", params=query, headers=_headers(world["finance"])
        )
    ).status_code == 200
    assert (
        await client.get(
            f"{ACC}/assets", params=query, headers=_headers(world["recruiter"])
        )
    ).status_code == 403
    imported = await client.post(
        f"{ACC}/assets/import",
        params={"year": world["year"], "month": 1},
        files={
            "file": ("st.csv", b"Nazwa;Data przyjecia;Wartosc poczatkowa\n", "text/csv")
        },
        headers=_headers(world["finance"]),
    )
    assert imported.status_code == 403


# ── OT, AM, zatwierdzona przeszłość ──────────────────────────────────────────


async def test_intake_and_month_depreciation_reach_the_buffer_once(client, world):
    acc, year = world["acc"], world["year"]
    created = await _create(client, world)
    assert created["inventory_number"] == f"ST/{year}/001"

    january = await _sync(client, world, 1)
    assert january["operations"]["created"] == 1
    assert january["depreciation"]["skipped"] == 1  # odpisy od lutego
    async with AsyncSessionLocal() as db:
        asset = await db.get(LedgerAsset, created["id"])
        assert asset is not None
    intake = await _doc("asset_operation", str(await _intake_id(created["id"])))
    assert intake is not None and intake.number == f"OT 1/{year}"
    assert await _lines(intake.id) == [
        ("debit", acc["fixed"], 2_400_000, None),
        ("credit", acc["intake"], 2_400_000, None),
    ]

    february = await _sync(client, world, 2)
    assert february["depreciation"]["created"] == 1
    am = await _doc("assets_month", _month(world, 2))
    assert am is not None and am.doc_type == "AM"
    assert await _lines(am.id) == [
        ("debit", acc["cost"], 50_000, "OG"),
        ("credit", acc["dep_fixed"], 50_000, None),
        ("debit", acc["overhead"], 50_000, "OG"),
        ("credit", acc["settlement"], 50_000, None),
    ]
    again = await _sync(client, world, 2)
    assert (
        again["depreciation"]["unchanged"] == 1
        and again["depreciation"]["created"] == 0
    )

    listing = await client.get(
        f"{ACC}/assets",
        params={"year": year, "month": 2},
        headers=_headers(world["finance"]),
    )
    body = listing.json()
    assert body["stats"]["month_amount"] == 50_000
    assert body["stats"]["count"] == 1 and body["stats"]["net"] == 2_350_000
    assert body["am"]["status"] == "draft"
    assert body["items"][0]["net"] == 2_350_000 and body["can_manage"] is False


async def _intake_id(asset_id: int) -> int:
    from app.models.ledger_assets import LedgerAssetOperation

    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(LedgerAssetOperation.id).where(
                LedgerAssetOperation.asset_id == asset_id,
                LedgerAssetOperation.op_type == "OT",
            )
        )


async def test_approved_depreciation_locks_the_past(client, world):
    year = world["year"]
    first = await _create(client, world)
    await _sync(client, world, 2)
    am = await _doc("assets_month", _month(world, 2))
    await _approve(client, world, am.id)
    am = await _doc("assets_month", _month(world, 2))
    assert am.status == "approved" and am.journal_no
    headers = _headers(world["accountant"])

    locked = await client.patch(
        f"{ACC}/assets/{first['id']}", json={"balance_rate": "20"}, headers=headers
    )
    assert locked.status_code == 409 and "amortyzacja" in locked.json()["detail"]
    renamed = await client.patch(
        f"{ACC}/assets/{first['id']}",
        json={"name": "Stacje robocze (3 szt.)"},
        headers=headers,
    )
    assert renamed.status_code == 200, renamed.text

    backdated = await client.post(
        f"{ACC}/assets",
        json=_asset_body(world, accepted_on=date(year, 1, 5).isoformat(), kst="803"),
        headers=headers,
    )
    assert backdated.status_code == 409
    assert "zapis nr" in backdated.json()["detail"]
    second = await _create(client, world, accepted_on=date(year, 2, 10).isoformat())

    early_move = await client.post(
        f"{ACC}/assets/{first['id']}/operations",
        json={
            "op_type": "MT",
            "op_date": date(year, 2, 15).isoformat(),
            "mpk_to": "FO",
        },
        headers=headers,
    )
    assert early_move.status_code == 409
    move = await client.post(
        f"{ACC}/assets/{first['id']}/operations",
        json={"op_type": "MT", "op_date": date(year, 3, 1).isoformat(), "mpk_to": "FO"},
        headers=headers,
    )
    assert move.status_code == 201, move.text

    march = await _sync(client, world, 3)
    assert march["depreciation"]["created"] == 1
    acc = world["acc"]
    am_march = await _doc("assets_month", _month(world, 3))
    assert await _lines(am_march.id) == [
        ("debit", acc["cost"], 50_000, "FO"),
        ("debit", acc["cost"], 50_000, "OG"),
        ("credit", acc["dep_fixed"], 100_000, None),
        ("debit", acc["front"], 50_000, "FO"),
        ("debit", acc["overhead"], 50_000, "OG"),
        ("credit", acc["settlement"], 100_000, None),
    ]
    card = await client.get(
        f"{ACC}/assets/{first['id']}",
        params={"year": year, "month": 3},
        headers=_headers(world["finance"]),
    )
    assert card.status_code == 200, card.text
    plan = {row["month"]: row for row in card.json()["balance_plan"]}
    assert plan[_month(world, 2)]["state"] == "approved"
    assert plan[_month(world, 2)]["journal_no"] == am.journal_no
    assert plan[_month(world, 3)]["state"] == "draft"
    assert card.json()["locked"] and card.json()["mpk"] == "FO"
    assert card.json()["tax_plan"][0]["amount"] == 60_000  # 30% podatkowo
    assert second["inventory_number"] == f"ST/{year}/002"


async def test_liquidation_posts_write_off_and_ends_depreciation(client, world):
    acc, year = world["acc"], world["year"]
    created = await _create(client, world)
    headers = _headers(world["accountant"])
    response = await client.post(
        f"{ACC}/assets/{created['id']}/operations",
        json={
            "op_type": "LT",
            "op_date": date(year, 4, 20).isoformat(),
            "note": "Zepsute",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    april = await _sync(client, world, 4)
    assert april["operations"]["created"] == 1
    write_off = await _doc("asset_operation", str(response.json()["id"]))
    # Odpisy 02–04 po 500 zł = 1 500 zł; netto 22 500 zł.
    assert await _lines(write_off.id) == [
        ("debit", acc["dep_fixed"], 150_000, None),
        ("debit", acc["disposal"], 2_250_000, None),
        ("credit", acc["fixed"], 2_400_000, None),
    ]
    assert (await _doc("assets_month", _month(world, 4))) is not None
    may = await _sync(client, world, 5)
    assert may["depreciation"]["skipped"] == 1
    again = await client.post(
        f"{ACC}/assets/{created['id']}/operations",
        json={
            "op_type": "UL",
            "op_date": date(year, 5, 2).isoformat(),
            "amount": "100.00",
        },
        headers=headers,
    )
    assert again.status_code == 409

    undone = await client.delete(
        f"{ACC}/assets/operations/{response.json()['id']}", headers=headers
    )
    assert undone.status_code == 204, undone.text
    async with AsyncSessionLocal() as db:
        asset = await db.get(LedgerAsset, created["id"])
        assert asset.status == "in_use" and asset.disposed_on is None
    assert await _doc("asset_operation", str(response.json()["id"])) is None


async def test_only_the_last_document_is_deleted(client, world):
    year = world["year"]
    created = await _create(client, world)
    headers = _headers(world["accountant"])
    improvement = await client.post(
        f"{ACC}/assets/{created['id']}/operations",
        json={
            "op_type": "UL",
            "op_date": date(year, 2, 3).isoformat(),
            "amount": "6000.00",
        },
        headers=headers,
    )
    assert improvement.status_code == 201, improvement.text
    move = await client.post(
        f"{ACC}/assets/{created['id']}/operations",
        json={
            "op_type": "MT",
            "op_date": date(year, 2, 20).isoformat(),
            "mpk_to": "BO",
        },
        headers=headers,
    )
    assert move.status_code == 201
    earlier = await client.post(
        f"{ACC}/assets/{created['id']}/operations",
        json={
            "op_type": "UL",
            "op_date": date(year, 2, 1).isoformat(),
            "amount": "10.00",
        },
        headers=headers,
    )
    assert earlier.status_code == 422
    blocked = await client.delete(
        f"{ACC}/assets/operations/{improvement.json()['id']}", headers=headers
    )
    assert blocked.status_code == 409
    intake = await client.delete(
        f"{ACC}/assets/operations/{await _intake_id(created['id'])}", headers=headers
    )
    assert intake.status_code == 409
    assert (
        await client.delete(
            f"{ACC}/assets/operations/{move.json()['id']}", headers=headers
        )
    ).status_code == 204
    assert (
        await client.delete(
            f"{ACC}/assets/operations/{improvement.json()['id']}", headers=headers
        )
    ).status_code == 204
    assert (
        await client.delete(f"{ACC}/assets/{created['id']}", headers=headers)
    ).status_code == 204


async def test_depreciation_waits_for_split_accounts(client, world):
    await _set_ledger(_ledger_value(world, allocation=False))
    await _create(client, world)
    summary = await client.get(
        f"{ACC}/sources",
        params={"year": world["year"], "month": 2},
        headers=_headers(world["finance"]),
    )
    item = next(i for i in summary.json()["items"] if i["kind"] == "assets")
    assert item["problems_total"] == 1
    assert "„5”" in item["problems"][0]["problems"][0]


# ── Import z Symfonii ŚT ─────────────────────────────────────────────────────


def _register_csv(world, *, extra_row: str = "") -> bytes:
    acc, prefix = world["acc"], world["prefix"]
    year = world["year"]
    rows = [
        "Numer inwentarzowy;Nazwa;Rodzaj;KŚT;Data przyjęcia;Wartość początkowa;"
        "Umorzenie bilansowe;Umorzenie podatkowe;Metoda;Stawka bilansowa;"
        "Stawka podatkowa;Konto;Konto umorzenia;MPK",
        f"{prefix}/1;Samochód osobowy;ŚT;741;16.09.{year - 2};142 000,00;59 166,75;"
        f"59 166,75;liniowa;20;20;{acc['fixed']};{acc['dep_fixed']};FO",
        f"{prefix}/2;Licencja systemu;WNiP;;15.01.{year - 2};28 000,00;28 000,00;"
        f"28 000,00;liniowa;50;50;{acc['intangible']};{acc['dep_intangible']};OG",
    ]
    if extra_row:
        rows.append(extra_row)
    return ("\n".join(rows) + "\n").encode("utf-8")


async def _import(client, world, content: bytes, *, save: bool, month: int = 10):
    return await client.post(
        f"{ACC}/assets/import",
        params={"year": world["year"] - 1, "month": month, "save": str(save).lower()},
        files={"file": ("ewidencja.csv", content, "text/csv")},
        headers=_headers(world["accountant"]),
    )


async def test_import_previews_then_saves_register_with_opening(client, world):
    acc, prefix, year = world["acc"], world["prefix"], world["year"]
    bad = await _import(
        client,
        world,
        _register_csv(
            world,
            extra_row=f"{prefix}/3;Meble;ŚT;803;01.02.{year - 1};5 000,00;0;0;"
            f"liniowa;20;20;{prefix}-999;{acc['dep_fixed']};OG",
        ),
        save=False,
    )
    assert bad.status_code == 200, bad.text
    assert bad.json()["errors_total"] == 1
    assert bad.json()["missing_accounts"] == [f"{prefix}-999"]
    refused = await _import(
        client,
        world,
        _register_csv(
            world,
            extra_row=f"{prefix}/3;Meble;ŚT;803;01.02.{year - 1};5 000,00;0;0;"
            f"liniowa;20;20;{prefix}-999;{acc['dep_fixed']};OG",
        ),
        save=True,
    )
    assert refused.status_code == 422

    preview = await _import(client, world, _register_csv(world), save=False)
    body = preview.json()
    assert body["valid"] == 2 and body["errors_total"] == 0 and body["created"] == 0
    assert body["totals"]["initial"] == 17_000_000
    saved = await _import(client, world, _register_csv(world), save=True)
    assert saved.status_code == 200, saved.text
    assert saved.json()["created"] == 2
    duplicate = await _import(client, world, _register_csv(world), save=False)
    assert duplicate.json()["errors_total"] == 2

    async with AsyncSessionLocal() as db:
        car = await db.scalar(
            select(LedgerAsset).where(LedgerAsset.inventory_number == f"{prefix}/1")
        )
        licence = await db.scalar(
            select(LedgerAsset).where(LedgerAsset.inventory_number == f"{prefix}/2")
        )
    assert car.opening_month == date(year - 1, 10, 1)
    assert car.opening_balance == 5_916_675 and car.mpk == "FO"
    assert licence.kind == "intangible" and licence.kst is None

    # Stan na 10.(rok−1): odpis samochodu od listopada, licencja umorzona.
    async with AsyncSessionLocal() as db:
        await ledger_years.ensure_year(db, year - 1, actor_id=world["admin"].id)
        await db.commit()
    response = await client.post(
        f"{ACC}/assets/sync",
        json={"year": year - 1, "month": 11},
        headers=_headers(world["finance"]),
    )
    assert response.status_code == 200, response.text
    am = await _doc("assets_month", f"{year - 1}-11")
    assert await _lines(am.id) == [
        ("debit", acc["cost"], 236_667, "FO"),
        ("credit", acc["dep_fixed"], 236_667, None),
        ("debit", acc["front"], 236_667, "FO"),
        ("credit", acc["settlement"], 236_667, None),
    ]
    # Środek ze stanem nie ma OT w księdze — dokumenty miesiąca stanu są w Symfonii.
    assert response.json()["operations"]["created"] == 0


async def test_assets_accounts_are_set_by_admin_from_the_plan(client, world):
    acc = world["acc"]
    body = {
        "cost_account": acc["cost"],
        "intake_account": acc["intake"],
        "disposal_account": acc["disposal"],
    }
    refused = await client.put(
        f"{ACC}/assets/settings", json=body, headers=_headers(world["accountant"])
    )
    assert refused.status_code == 403
    missing = await client.put(
        f"{ACC}/assets/settings",
        json={**body, "disposal_account": f"{world['prefix']}-998"},
        headers=_headers(world["admin"]),
    )
    assert missing.status_code == 422
    saved = await client.put(
        f"{ACC}/assets/settings", json=body, headers=_headers(world["admin"])
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["cost_account"] == acc["cost"]


async def test_new_asset_needs_valid_mpk_kst_and_rate(client, world):
    headers = _headers(world["accountant"])
    for extra, fragment in (
        ({"mpk": "ZARZAD"}, "MPK"),
        ({"kst": ""}, "KŚT"),
        ({"balance_rate": "0"}, "stawki"),
        ({"kind": "intangible", "tax_method": "degressive", "kst": None}, "WNiP"),
        ({"asset_account": f"{world['prefix']}-997"}, "Konto środka"),
    ):
        response = await client.post(
            f"{ACC}/assets", json=_asset_body(world, **extra), headers=headers
        )
        assert response.status_code == 422, (extra, response.text)
        assert fragment in response.json()["detail"], response.text
    unique = uuid.uuid4().hex[:6]
    first = await _create(client, world, inventory_number=f"{world['prefix']}/{unique}")
    clash = await client.post(
        f"{ACC}/assets",
        json=_asset_body(world, inventory_number=first["inventory_number"]),
        headers=headers,
    )
    assert clash.status_code == 409


async def test_editing_dates_keeps_documents_after_acceptance_and_opening(
    client, world
):
    # Przegląd K6: PATCH daty przyjęcia albo miesiąca stanu omijał kontrolę dat
    # dokumentów — LT lądował w księdze przed OT, a UL w okresie stanu z Symfonii.
    year, prefix = world["year"], world["prefix"]
    headers = _headers(world["accountant"])
    created = await _create(client, world)
    liquidation = await client.post(
        f"{ACC}/assets/{created['id']}/operations",
        json={"op_type": "LT", "op_date": date(year, 1, 20).isoformat()},
        headers=headers,
    )
    assert liquidation.status_code == 201, liquidation.text
    moved = await client.patch(
        f"{ACC}/assets/{created['id']}",
        json={"accepted_on": date(year, 3, 1).isoformat()},
        headers=headers,
    )
    assert moved.status_code == 422, moved.text
    assert "LT 1/" in moved.json()["detail"]

    opened = await _create(
        client,
        world,
        inventory_number=f"{prefix}/o1",
        accepted_on=date(year - 1, 5, 1).isoformat(),
        opening={"month": date(year, 10, 1).isoformat(), "balance": "1000.00"},
    )
    improvement = await client.post(
        f"{ACC}/assets/{opened['id']}/operations",
        json={
            "op_type": "UL",
            "op_date": date(year, 11, 5).isoformat(),
            "amount": "100.00",
        },
        headers=headers,
    )
    assert improvement.status_code == 201, improvement.text
    shifted = await client.patch(
        f"{ACC}/assets/{opened['id']}",
        json={
            "opening": {"month": date(year, 12, 1).isoformat(), "balance": "1000.00"}
        },
        headers=headers,
    )
    assert shifted.status_code == 422, shifted.text


async def test_description_edit_keeps_depreciation_drafts(client, world):
    headers = _headers(world["accountant"])
    created = await _create(client, world)
    await _sync(client, world, 2)
    assert await _doc("assets_month", _month(world, 2)) is not None
    renamed = await client.patch(
        f"{ACC}/assets/{created['id']}",
        json={"name": "Stacje robocze (3 szt.)", "note": "Pokój 3"},
        headers=headers,
    )
    assert renamed.status_code == 200, renamed.text
    # Opis środka nie zmienia AM — szkic zostaje w buforze.
    assert await _doc("assets_month", _month(world, 2)) is not None
    replanned = await client.patch(
        f"{ACC}/assets/{created['id']}", json={"balance_rate": "20"}, headers=headers
    )
    assert replanned.status_code == 200, replanned.text
    assert await _doc("assets_month", _month(world, 2)) is None
