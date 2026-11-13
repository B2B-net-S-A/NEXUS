"""Księga NEXUSA (K1, 0699) — trasy z bazą.

Przełącznik modułu (wyłączony = 404, admin widzi), bufor i zatwierdzenie
z kolejnymi pozycjami dziennika (tylko „Księgowi” i admin), trwałość
zatwierdzonych zapisów (serwis i wyzwalacz w bazie), storno czerwone raz
i nie dla storna, zamknięcie okresu przy pustym buforze i ponowne otwarcie
przez admina z powodem, dokumenty płacowe niewidoczne bez Płac (lista, karta,
zatwierdzenie, karta konta zbiorczo), obroty i salda z analityką słownika,
plan kont (konto nadrzędne, reguła E2 blokuje wyłączenie), lata i tryb roku,
lista „Księgowi”. Osoby, konta i kwoty fikcyjne; rok obrotowy losowy z
przyszłości, żeby nie zderzyć się z innymi testami na wspólnej bazie.
"""

from __future__ import annotations

import random
import uuid
from datetime import date, datetime, timezone

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError

from app.api import ledger as ledger_api
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token
from app.models.app_setting import AppSetting
from app.models.finance_ledger import FinanceCounterparty
from app.models.finance_posting import FinanceAccount, FinancePostingRule
from app.models.ledger import (
    LedgerDocument,
    LedgerEvent,
    LedgerLine,
    LedgerPeriod,
    LedgerYear,
)
from app.models.user import User, UserRole
from app.services.ledger import documents as ledger_documents
from app.services.ledger import settings as ledger_settings
from app.services.ledger import years as ledger_years
from app.services.ledger.documents import DocumentSpec
from app.services.ledger.engine import LineIn
from app.services.ledger_schema import PURGE_SETTING
from tests._permission_grants import grant_permissions

ACC = "/api/accounting"


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _user(db, role: str) -> User:
    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"ksiega-{marker}@example.com",
        name=f"Osoba Testowa {marker}",
        role=UserRole(role),
        roles=[role],
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _set_ledger(value) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, ledger_settings.SETTING_KEY)
        if value is None:
            if row is not None:
                await db.delete(row)
        elif row is None:
            db.add(AppSetting(key=ledger_settings.SETTING_KEY, value=value))
        else:
            row.value = value
        await db.commit()


async def _purge_years(year_numbers: list[int]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(text(f"SET LOCAL {PURGE_SETTING} = 'on'"))
        year_ids = list(
            await db.scalars(
                select(LedgerYear.id).where(LedgerYear.year.in_(year_numbers))
            )
        )
        if year_ids:
            doc_ids = list(
                await db.scalars(
                    select(LedgerDocument.id).where(
                        LedgerDocument.year_id.in_(year_ids)
                    )
                )
            )
            period_ids = list(
                await db.scalars(
                    select(LedgerPeriod.id).where(LedgerPeriod.year_id.in_(year_ids))
                )
            )
            await db.execute(
                delete(LedgerEvent).where(
                    (LedgerEvent.document_id.in_(doc_ids or [0]))
                    | (LedgerEvent.period_id.in_(period_ids or [0]))
                )
            )
            await db.execute(
                update(LedgerDocument)
                .where(LedgerDocument.id.in_(doc_ids or [0]))
                .values(reversed_by_id=None)
            )
            await db.execute(
                delete(LedgerLine).where(LedgerLine.document_id.in_(doc_ids or [0]))
            )
            await db.execute(
                delete(LedgerDocument).where(
                    LedgerDocument.id.in_(doc_ids or [0]),
                    LedgerDocument.reverses_id.is_not(None),
                )
            )
            await db.execute(
                delete(LedgerDocument).where(LedgerDocument.id.in_(doc_ids or [0]))
            )
            await db.execute(
                delete(LedgerPeriod).where(LedgerPeriod.year_id.in_(year_ids))
            )
            await db.execute(delete(LedgerYear).where(LedgerYear.id.in_(year_ids)))
        await db.commit()


@pytest_asyncio.fixture
async def client():
    app = FastAPI()
    app.include_router(ledger_api.router, prefix=ACC)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as c:
        yield c


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
        module_only = await _user(db, "recruiter")
        recruiter = await _user(db, "recruiter")
        counterparty = FinanceCounterparty(
            name="Kontrahent Testowy",
            symfonia_partner_id=f"TEST-{uuid.uuid4().hex[:12]}",
        )
        db.add(counterparty)
        accounts = {
            "cash": (f"{prefix}-131", "Rachunek bieżący", "other", None),
            "suppliers": (
                f"{prefix}-201",
                "Rozrachunki z dostawcami",
                "settlement",
                "counterparty",
            ),
            "vat": (f"{prefix}-221", "VAT naliczony", "vat", None),
            "cost": (f"{prefix}-402", "Usługi obce", "cost", None),
            "wages": (f"{prefix}-404", "Wynagrodzenia", "cost", None),
            "payroll": (
                f"{prefix}-231",
                "Rozrachunki z tytułu wynagrodzeń",
                "settlement",
                None,
            ),
        }
        for number, name, kind, dictionary in accounts.values():
            db.add(
                FinanceAccount(
                    number=number, name=name, kind=kind, dictionary=dictionary
                )
            )
        await db.commit()
        await ledger_years.ensure_year(db, year, actor_id=admin.id)
        await db.commit()
    await grant_permissions(module_only.id, "finance_module")
    await grant_permissions(accountant.id, "payroll")
    await _set_ledger({"modules": {"ledger": True}, "accountants": [accountant.id]})
    yield {
        "year": year,
        "admin": admin,
        "accountant": accountant,
        "finance": finance,
        "module_only": module_only,
        "recruiter": recruiter,
        "counterparty": counterparty,
        "acc": {key: value[0] for key, value in accounts.items()},
    }
    await _purge_years([year, year - 1])
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(FinancePostingRule).where(
                FinancePostingRule.cost_account.like(f"{prefix}-%")
            )
        )
        await db.execute(
            delete(FinanceAccount).where(FinanceAccount.number.like(f"{prefix}-%"))
        )
        await db.execute(
            delete(FinanceCounterparty).where(FinanceCounterparty.id == counterparty.id)
        )
        await db.execute(
            delete(User).where(
                User.id.in_(
                    [admin.id, accountant.id, finance.id, module_only.id, recruiter.id]
                )
            )
        )
        await db.commit()
    await _set_ledger(previous)


def _doc(world, *, month: int = 3, amount: str = "1230.00", **extra) -> dict:
    acc = world["acc"]
    body = {
        "doc_type": "PK",
        "op_date": date(world["year"], month, 10).isoformat(),
        "description": "Faktura testowa",
        "lines": [
            {"side": "debit", "account": acc["cost"], "amount": "1000.00"},
            {"side": "debit", "account": acc["vat"], "amount": "230.00"},
            {
                "side": "credit",
                "account": f"{acc['suppliers']}-1042",
                "amount": amount,
                "counterparty_id": world["counterparty"].id,
            },
        ],
    }
    body.update(extra)
    return body


async def _create(client, world, user_key: str = "finance", **kwargs) -> dict:
    response = await client.post(
        f"{ACC}/documents",
        json=_doc(world, **kwargs),
        headers=_headers(world[user_key]),
    )
    assert response.status_code == 201, response.text
    return response.json()


# ── Moduł i konfiguracja ─────────────────────────────────────────────────────


async def test_module_off_hides_ledger_but_admin_sees(client, world):
    await _set_ledger(
        {"modules": {"ledger": False}, "accountants": [world["accountant"].id]}
    )
    finance = _headers(world["finance"])
    config = await client.get(f"{ACC}/config", headers=finance)
    assert config.status_code == 200
    assert config.json()["open"] is False
    listing = await client.get(
        f"{ACC}/documents", params={"year": world["year"]}, headers=finance
    )
    assert listing.status_code == 404
    admin = await client.get(
        f"{ACC}/documents",
        params={"year": world["year"]},
        headers=_headers(world["admin"]),
    )
    assert admin.status_code == 200


async def test_recruiter_without_finance_module_is_refused(client, world):
    response = await client.get(f"{ACC}/config", headers=_headers(world["recruiter"]))
    assert response.status_code == 403


async def test_modules_without_screens_cannot_be_enabled(client, world):
    admin = _headers(world["admin"])
    refused = await client.put(
        f"{ACC}/config/modules",
        json={"module": "payroll", "enabled": True},
        headers=admin,
    )
    assert refused.status_code == 409
    not_admin = await client.put(
        f"{ACC}/config/modules",
        json={"module": "ledger", "enabled": True},
        headers=_headers(world["accountant"]),
    )
    assert not_admin.status_code == 403


async def test_accountants_list_needs_admin_and_finance_module(client, world):
    admin = _headers(world["admin"])
    refused = await client.put(
        f"{ACC}/config/accountants",
        json={"user_ids": [world["recruiter"].id]},
        headers=admin,
    )
    assert refused.status_code == 422
    assert "Modułu Finanse" in refused.json()["detail"]
    saved = await client.put(
        f"{ACC}/config/accountants",
        json={"user_ids": [world["accountant"].id, world["module_only"].id]},
        headers=admin,
    )
    assert saved.status_code == 200
    assert saved.json()["accountants"] == sorted(
        [world["accountant"].id, world["module_only"].id]
    )
    by_accountant = await client.put(
        f"{ACC}/config/accountants",
        json={"user_ids": []},
        headers=_headers(world["accountant"]),
    )
    assert by_accountant.status_code == 403


# ── Bufor, zatwierdzenie, trwałość ───────────────────────────────────────────


async def test_draft_then_approval_numbers_journal_in_order(client, world):
    first = await _create(client, world, month=3)
    second = await _create(client, world, month=2)
    assert first["status"] == "draft" and first["journal_no"] is None
    assert first["number"] == f"PK 1/03/{world['year']}"
    refused = await client.post(
        f"{ACC}/documents/approve",
        json={"ids": [first["id"], second["id"]]},
        headers=_headers(world["finance"]),
    )
    assert refused.status_code == 403
    approved = await client.post(
        f"{ACC}/documents/approve",
        json={"ids": [first["id"], second["id"]]},
        headers=_headers(world["accountant"]),
    )
    assert approved.status_code == 200, approved.text
    # Kolejność w dzienniku: data operacji (luty przed marcem).
    numbers = {item["id"]: item["journal_no"] for item in approved.json()["approved"]}
    assert numbers == {second["id"]: 1, first["id"]: 2}
    card = await client.get(
        f"{ACC}/documents/{first['id']}", headers=_headers(world["finance"])
    )
    body = card.json()
    assert body["status"] == "approved"
    assert [event["action"] for event in body["events"]] == ["create", "approve"]
    assert body["lines"][2]["account_name"].endswith("· analityka")


async def test_approved_document_is_permanent(client, world):
    doc = await _create(client, world)
    await client.post(
        f"{ACC}/documents/approve",
        json={"ids": [doc["id"]]},
        headers=_headers(world["accountant"]),
    )
    finance = _headers(world["finance"])
    patched = await client.patch(
        f"{ACC}/documents/{doc['id']}", json=_doc(world), headers=finance
    )
    assert patched.status_code == 409
    deleted = await client.delete(f"{ACC}/documents/{doc['id']}", headers=finance)
    assert deleted.status_code == 409
    async with AsyncSessionLocal() as db:
        with pytest.raises(DBAPIError) as exc:
            await db.execute(
                update(LedgerDocument)
                .where(LedgerDocument.id == doc["id"])
                .values(debit_total=1, credit_total=1)
            )
        assert "stornem" in str(exc.value)
        await db.rollback()
        with pytest.raises(DBAPIError):
            await db.execute(
                update(LedgerLine)
                .where(LedgerLine.document_id == doc["id"])
                .values(amount=5)
            )
        await db.rollback()


async def test_draft_can_be_edited_and_deleted(client, world):
    doc = await _create(client, world)
    finance = _headers(world["finance"])
    changed = await client.patch(
        f"{ACC}/documents/{doc['id']}",
        json=_doc(world, month=4, description="Poprawiony opis"),
        headers=finance,
    )
    assert changed.status_code == 200
    assert changed.json()["op_date"] == date(world["year"], 4, 10).isoformat()
    assert changed.json()["description"] == "Poprawiony opis"
    deleted = await client.delete(f"{ACC}/documents/{doc['id']}", headers=finance)
    assert deleted.status_code == 204
    missing = await client.get(f"{ACC}/documents/{doc['id']}", headers=finance)
    assert missing.status_code == 404
    async with AsyncSessionLocal() as db:
        trail = list(
            await db.scalars(
                select(LedgerEvent.action).where(
                    LedgerEvent.detail["number"].astext == doc["number"],
                    LedgerEvent.action == "delete",
                )
            )
        )
    assert trail == ["delete"]


async def test_unbalanced_or_unknown_account_is_refused(client, world):
    finance = _headers(world["finance"])
    unbalanced = await client.post(
        f"{ACC}/documents", json=_doc(world, amount="1229.99"), headers=finance
    )
    assert unbalanced.status_code == 422
    assert "różni się od sumy Ma" in unbalanced.json()["detail"]
    body = _doc(world)
    body["lines"][0]["account"] = f"{world['acc']['cost']}-77"
    unknown = await client.post(f"{ACC}/documents", json=body, headers=finance)
    assert unknown.status_code == 422
    assert "słownik analityki" in unknown.json()["detail"]
    no_year = await client.post(
        f"{ACC}/documents",
        json={**_doc(world), "op_date": date(world["year"] - 1, 5, 1).isoformat()},
        headers=finance,
    )
    assert no_year.status_code == 409
    assert "Nie ma roku obrotowego" in no_year.json()["detail"]


# ── Storno ───────────────────────────────────────────────────────────────────


async def test_red_storno_once_and_never_of_storno(client, world):
    doc = await _create(client, world)
    accountant = _headers(world["accountant"])
    await client.post(
        f"{ACC}/documents/approve", json={"ids": [doc["id"]]}, headers=accountant
    )
    reversed_ = await client.post(
        f"{ACC}/documents/{doc['id']}/reverse",
        json={
            "op_date": date(world["year"], 5, 2).isoformat(),
            "reason": "Błędna kwota",
        },
        headers=accountant,
    )
    assert reversed_.status_code == 200, reversed_.text
    storno = reversed_.json()
    assert storno["doc_type"] == "ST"
    assert storno["status"] == "approved"
    assert storno["reverses_id"] == doc["id"]
    assert [line["amount"] for line in storno["lines"]] == [-100_000, -23_000, -123_000]
    again = await client.post(
        f"{ACC}/documents/{doc['id']}/reverse",
        json={"reason": "jeszcze raz"},
        headers=accountant,
    )
    assert again.status_code == 409
    of_storno = await client.post(
        f"{ACC}/documents/{storno['id']}/reverse",
        json={
            "op_date": date(world["year"], 5, 2).isoformat(),
            "reason": "storno storna",
        },
        headers=accountant,
    )
    assert of_storno.status_code == 409
    finance = await client.post(
        f"{ACC}/documents/{doc['id']}/reverse",
        json={"reason": "bez prawa"},
        headers=_headers(world["finance"]),
    )
    assert finance.status_code == 403
    balance = await client.get(
        f"{ACC}/trial-balance",
        params={"year": world["year"], "level": "analytic"},
        headers=accountant,
    )
    rows = {row["account"]: row for row in balance.json()["items"]}
    assert rows[world["acc"]["cost"]]["ytd_wn"] == 0
    assert rows[world["acc"]["cost"]]["saldo_wn"] == 0


# ── Okresy ───────────────────────────────────────────────────────────────────


async def test_period_close_needs_empty_buffer_and_blocks_posting(client, world):
    year = world["year"]
    draft = await _create(client, world, month=6)
    accountant = _headers(world["accountant"])
    config = await client.get(f"{ACC}/config", headers=accountant)
    periods = {
        period["month"]: period
        for item in config.json()["years"]
        if item["year"] == year
        for period in item["periods"]
    }
    june = periods[6]["id"]
    blocked = await client.post(f"{ACC}/periods/{june}/close", headers=accountant)
    assert blocked.status_code == 409
    assert "W buforze" in blocked.json()["detail"]
    await client.delete(f"{ACC}/documents/{draft['id']}", headers=accountant)
    by_finance = await client.post(
        f"{ACC}/periods/{june}/close", headers=_headers(world["finance"])
    )
    assert by_finance.status_code == 403
    closed = await client.post(f"{ACC}/periods/{june}/close", headers=accountant)
    assert closed.status_code == 200
    posting = await client.post(
        f"{ACC}/documents",
        json=_doc(world, month=6),
        headers=_headers(world["finance"]),
    )
    assert posting.status_code == 409
    assert "zamknięty" in posting.json()["detail"]
    reopen_by_accountant = await client.post(
        f"{ACC}/periods/{june}/reopen", json={"reason": "korekta"}, headers=accountant
    )
    assert reopen_by_accountant.status_code == 403
    admin = _headers(world["admin"])
    no_reason = await client.post(
        f"{ACC}/periods/{june}/reopen", json={"reason": "  "}, headers=admin
    )
    assert no_reason.status_code == 422
    reopened = await client.post(
        f"{ACC}/periods/{june}/reopen",
        json={"reason": "Korekta faktury z czerwca"},
        headers=admin,
    )
    assert reopened.status_code == 200
    async with AsyncSessionLocal() as db:
        actions = list(
            await db.scalars(
                select(LedgerEvent.action)
                .where(LedgerEvent.period_id == june)
                .order_by(LedgerEvent.id)
            )
        )
    assert actions == ["close", "reopen"]


# ── Dokumenty płacowe (D2) ───────────────────────────────────────────────────


async def test_payroll_document_hidden_without_payroll(client, world):
    acc = world["acc"]
    async with AsyncSessionLocal() as db:
        doc = await ledger_documents.create_draft(
            db,
            DocumentSpec(
                doc_type="LP",
                op_date=date(world["year"], 7, 31),
                doc_date=date(world["year"], 7, 31),
                number="LP 07",
                lines=[
                    LineIn(side="debit", account=acc["wages"], amount=900_000),
                    LineIn(side="credit", account=acc["payroll"], amount=900_000),
                ],
                sensitivity="payroll",
                source_type="test_payroll",
                source_id=uuid.uuid4().hex,
            ),
            actor_id=world["accountant"].id,
        )
        await db.commit()
        doc_id = doc.id
    only = _headers(world["module_only"])
    listing = await client.get(
        f"{ACC}/documents", params={"year": world["year"]}, headers=only
    )
    assert doc_id not in [item["id"] for item in listing.json()["items"]]
    assert listing.json()["counts"].get("LP") is None
    assert (
        await client.get(f"{ACC}/documents/{doc_id}", headers=only)
    ).status_code == 404
    accountant = _headers(world["accountant"])
    seen = await client.get(f"{ACC}/documents/{doc_id}", headers=accountant)
    assert seen.status_code == 200
    await _set_ledger(
        {
            "modules": {"ledger": True},
            "accountants": [world["accountant"].id, world["module_only"].id],
        }
    )
    refused = await client.post(
        f"{ACC}/documents/approve", json={"ids": [doc_id]}, headers=only
    )
    assert refused.status_code == 404
    approved = await client.post(
        f"{ACC}/documents/approve", json={"ids": [doc_id]}, headers=accountant
    )
    assert approved.status_code == 200
    card = await client.get(
        f"{ACC}/accounts/card",
        params={"account": acc["wages"], "year": world["year"]},
        headers=only,
    )
    assert card.status_code == 200
    assert card.json()["items"] == []
    assert card.json()["payroll_rows"] == [
        {
            "month": 7,
            "wn": 900_000,
            "ma": 0,
            "lines": 1,
            "label": "Dokumenty płacowe — szczegóły widzą Płace i administrator",
        }
    ]
    assert card.json()["closing"] == 900_000
    full = await client.get(
        f"{ACC}/accounts/card",
        params={"account": acc["wages"], "year": world["year"]},
        headers=accountant,
    )
    assert [item["number"] for item in full.json()["items"]] == ["LP 07"]


# ── Obroty i salda ───────────────────────────────────────────────────────────


async def test_trial_balance_groups_dictionary_analytics(client, world):
    acc = world["acc"]
    first = await _create(client, world, month=3)
    body = _doc(world, month=3)
    body["lines"][2]["account"] = f"{acc['suppliers']}-2001"
    second = (
        await client.post(
            f"{ACC}/documents", json=body, headers=_headers(world["finance"])
        )
    ).json()
    accountant = _headers(world["accountant"])
    await client.post(
        f"{ACC}/documents/approve",
        json={"ids": [first["id"], second["id"]]},
        headers=accountant,
    )
    synthetic = await client.get(
        f"{ACC}/trial-balance",
        params={"year": world["year"], "month_from": 3, "month_to": 3},
        headers=accountant,
    )
    data = synthetic.json()
    rows = {row["account"]: row for row in data["items"]}
    assert rows[acc["suppliers"]]["ma"] == 246_000
    assert rows[acc["suppliers"]]["analytics"] == 2
    assert rows[acc["suppliers"]]["saldo_ma"] == 246_000
    assert data["balanced"] is True
    analytic = await client.get(
        f"{ACC}/trial-balance",
        params={"year": world["year"], "level": "analytic"},
        headers=accountant,
    )
    accounts = {row["account"] for row in analytic.json()["items"]}
    assert {f"{acc['suppliers']}-1042", f"{acc['suppliers']}-2001"} <= accounts
    april = await client.get(
        f"{ACC}/trial-balance",
        params={"year": world["year"], "month_from": 4, "month_to": 4},
        headers=accountant,
    )
    april_rows = {row["account"]: row for row in april.json()["items"]}
    assert april_rows[acc["suppliers"]]["ma"] == 0
    assert april_rows[acc["suppliers"]]["saldo_ma"] == 246_000


# ── Plan kont, lata ──────────────────────────────────────────────────────────


async def test_chart_parent_and_rule_guard(client, world):
    acc = world["acc"]
    finance = _headers(world["finance"])
    bad_parent = await client.post(
        f"{ACC}/chart",
        json={
            "number": f"{acc['cost']}9",
            "name": "Zły rodzic",
            "parent_number": acc["cost"],
        },
        headers=finance,
    )
    assert bad_parent.status_code == 422
    created = await client.post(
        f"{ACC}/chart",
        json={
            "number": f"{acc['cost']}-1",
            "name": "Usługi obce — biuro",
            "kind": "cost",
            "parent_number": acc["cost"],
            "account_type": "result",
        },
        headers=finance,
    )
    assert created.status_code == 201, created.text
    rows = {row["number"]: row for row in created.json()["items"]}
    assert rows[acc["cost"]]["has_children"] is True
    assert rows[acc["cost"]]["postable"] is False
    assert rows[f"{acc['cost']}-1"]["account_type_label"] == "wynikowe"
    async with AsyncSessionLocal() as db:
        db.add(
            FinancePostingRule(
                category="office",
                counterparty_id=world["counterparty"].id,
                cost_account=f"{acc['cost']}-1",
                vat_account=acc["vat"],
                deduction="full",
                register="purchase",
                doc_type="FVZ",
                service_label="Biuro",
                description_template="{usługa}",
                active=False,
            )
        )
        await db.commit()
    account_id = rows[f"{acc['cost']}-1"]["id"]
    # Reguła wyłączona nie blokuje; aktywna już tak.
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(FinancePostingRule)
            .where(FinancePostingRule.cost_account == f"{acc['cost']}-1")
            .values(active=True)
        )
        await db.commit()
    blocked = await client.patch(
        f"{ACC}/chart/{account_id}", json={"active": False}, headers=finance
    )
    assert blocked.status_code == 409
    renamed = await client.patch(
        f"{ACC}/chart/{account_id}", json={"name": "Biuro i media"}, headers=finance
    )
    assert renamed.status_code == 200


async def test_year_creation_and_mode_rights(client, world):
    target = world["year"] - 1
    refused = await client.post(
        f"{ACC}/years", json={"year": target}, headers=_headers(world["finance"])
    )
    assert refused.status_code == 403
    accountant = _headers(world["accountant"])
    nexus_mode = await client.post(
        f"{ACC}/years", json={"year": target, "mode": "nexus"}, headers=accountant
    )
    assert nexus_mode.status_code == 403
    created = await client.post(
        f"{ACC}/years", json={"year": target}, headers=accountant
    )
    assert created.status_code == 201
    year_row = next(item for item in created.json()["items"] if item["year"] == target)
    assert len(year_row["periods"]) == 12
    assert year_row["mode"] == "symfonia"
    duplicate = await client.post(
        f"{ACC}/years", json={"year": target}, headers=accountant
    )
    assert duplicate.status_code == 409
    mode_by_accountant = await client.patch(
        f"{ACC}/years/{year_row['id']}", json={"mode": "parallel"}, headers=accountant
    )
    assert mode_by_accountant.status_code == 403
    mode = await client.patch(
        f"{ACC}/years/{year_row['id']}",
        json={"mode": "parallel"},
        headers=_headers(world["admin"]),
    )
    assert mode.status_code == 200
    assert (
        next(item for item in mode.json()["items"] if item["year"] == target)["mode"]
        == "parallel"
    )


async def test_listing_filters_and_search(client, world):
    first = await _create(client, world, month=8, description="Najem biura sierpień")
    await _create(client, world, month=9)
    finance = _headers(world["finance"])
    august = await client.get(
        f"{ACC}/documents", params={"year": world["year"], "month": 8}, headers=finance
    )
    assert [item["id"] for item in august.json()["items"]] == [first["id"]]
    found = await client.get(
        f"{ACC}/documents",
        params={"year": world["year"], "q": "najem"},
        headers=finance,
    )
    assert [item["id"] for item in found.json()["items"]] == [first["id"]]
    drafts = await client.get(
        f"{ACC}/documents",
        params={"year": world["year"], "status": "draft"},
        headers=finance,
    )
    assert drafts.json()["drafts"] == 2
    assert drafts.json()["counts"] == {"PK": 2}
    empty_year = await client.get(
        f"{ACC}/documents", params={"year": 2021}, headers=finance
    )
    assert empty_year.status_code == 200
    assert empty_year.json()["year"] in (None, 2021)


async def test_service_refuses_second_document_for_same_source(world):
    acc = world["acc"]
    source = uuid.uuid4().hex

    def spec() -> DocumentSpec:
        return DocumentSpec(
            doc_type="FVZ",
            op_date=date(world["year"], 10, 5),
            doc_date=date(world["year"], 10, 5),
            number="FV/1/10",
            lines=[
                LineIn(side="debit", account=acc["cost"], amount=100),
                LineIn(side="credit", account=acc["cash"], amount=100),
            ],
            source_type="finance_cost_entry",
            source_id=source,
        )

    async with AsyncSessionLocal() as db:
        await ledger_documents.create_draft(db, spec(), actor_id=None)
        await db.commit()
        with pytest.raises(Exception) as exc:
            await ledger_documents.create_draft(db, spec(), actor_id=None)
        assert "ma już dokument" in str(exc.value)
        await db.rollback()


def test_now_is_timezone_aware():
    assert ledger_api._now().tzinfo == timezone.utc
    assert isinstance(ledger_api._now(), datetime)
