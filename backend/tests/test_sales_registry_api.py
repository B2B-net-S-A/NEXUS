"""Dane firm z rejestrów z bazą: zapis w kartach, historia, dubel numeru, noc i wyzwalacz.

Rejestry odpowiadają nagraniami z ``tests/data/sales_registry`` (fikcyjne firmy), bez sieci.
"""

from __future__ import annotations

import json
import random
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import delete, select, update

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import local_now
from app.models.sales import SalesBotResult, SalesCompany, SalesSignalRun
from app.services.sales import registry
from app.services.sales import registry_cards as cards
from tests.test_sales_companies_api import _headers, _user
from tests.test_sales_signals_api import _company

DATA = Path(__file__).parent / "data" / "sales_registry"
COMPANIES = "/api/sales/companies"
_WEIGHTS = (6, 5, 7, 2, 3, 4, 5, 6, 7)


def _nip() -> str:
    """Losowy NIP z poprawną sumą kontrolną (fikcyjny, unikalny w biegu testów)."""

    while True:
        head = "".join(random.choice("0123456789") for _ in range(9))
        control = sum(int(d) * w for d, w in zip(head, _WEIGHTS)) % 11
        if control != 10:
            return f"{head}{control}"


def _krs() -> str:
    return f"{random.randint(1, 9_999_999_999):010d}"


def _vat_answer(nip: str, krs: str | None, **over: Any) -> dict[str, Any]:
    subject = json.loads((DATA / "vat_batch.json").read_text(encoding="utf-8"))[
        "result"
    ]["entries"][0]["subjects"][0]
    subject = {**subject, "nip": nip, "krs": krs, **over}
    return {"identifier": nip, "subjects": [subject]}


def _krs_answer(krs: str, nip: str, **over: Any) -> dict[str, Any]:
    data = json.loads((DATA / "krs_active.json").read_text(encoding="utf-8"))
    data["odpis"]["naglowekA"]["numerKRS"] = krs
    data["odpis"]["dane"]["dzial1"]["danePodmiotu"]["identyfikatory"]["nip"] = nip
    data["odpis"]["dane"]["dzial1"]["danePodmiotu"].update(over)
    return data


class FakeRegistries:
    """Rejestry w pamięci: ``vat[nip]`` → wpis albo brak, ``krs[numer]`` → odpowiedź."""

    def __init__(self) -> None:
        self.vat: dict[str, dict[str, Any]] = {}
        self.krs: dict[str, httpx.Response] = {}
        self.removed: set[str] = set()
        self.calls: list[str] = []
        self.timeout = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request.url.path)
        if self.timeout:
            raise httpx.ReadTimeout("wolno", request=request)
        path = request.url.path
        if path.startswith("/api/search/nips/"):
            nips = path.rsplit("/", 1)[1].split(",")
            entries = [
                self.vat.get(nip, {"identifier": nip, "subjects": []}) for nip in nips
            ]
            return httpx.Response(200, json={"result": {"entries": entries}})
        number = path.rsplit("/", 1)[1]
        if "OdpisAktualny" in path:
            return self.krs.get(number, httpx.Response(204))
        if number in self.removed:
            body = json.loads((DATA / "krs_full_removed.json").read_text("utf-8"))
            return httpx.Response(200, json=body)
        return httpx.Response(404)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


@pytest.fixture
def fake(monkeypatch) -> FakeRegistries:
    registries = FakeRegistries()
    monkeypatch.setattr(registry, "BACKOFF_SECONDS", 0)
    monkeypatch.setattr(cards, "new_client", registries.client)
    return registries


async def _check(ids: list[int], **kwargs: Any) -> cards.Summary:
    async with AsyncSessionLocal() as db:
        return await cards.check_companies(
            db, ids, now=datetime.now(timezone.utc), **kwargs
        )


async def _card(company_id: int) -> SalesCompany:
    async with AsyncSessionLocal() as db:
        return await db.get(SalesCompany, company_id)


async def _history(company_id: int) -> list[SalesBotResult]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(SalesBotResult)
                    .where(
                        SalesBotResult.kind == cards.KIND,
                        SalesBotResult.company_id == company_id,
                    )
                    .order_by(SalesBotResult.id)
                )
            ).all()
        )


@pytest.mark.asyncio
async def test_empty_fields_filled_human_field_kept_and_history_written(fake) -> None:
    nip, krs = _nip(), _krs()
    fake.vat[nip] = _vat_answer(nip, krs)
    fake.krs[krs] = httpx.Response(200, json=_krs_answer(krs, nip))
    company = await _company(
        f"Rejestr {uuid.uuid4().hex[:8]}", nip=nip, legal_name="Nazwa handlowca"
    )

    summary = await _check([company])

    card = await _card(company)
    assert card.legal_name == "Nazwa handlowca"
    assert (card.regon, card.krs, card.hq_city, card.hq_country) == (
        "111222333",
        krs,
        "Bielsko-Biała",
        "PL",
    )
    [entry] = await _history(company)
    assert entry.status == "accepted"
    payload = entry.payload
    assert payload["actor"] == cards.ACTOR
    assert payload["state"] == registry.ACTIVE
    assert payload["vat_status"] == "active"
    assert payload["outcomes"]["legal_name"] == {
        "result": cards.KEPT,
        "current": "Nazwa handlowca",
    }
    assert payload["outcomes"]["krs"]["result"] == cards.APPLIED
    assert payload["fields"]["krs"]["url"].endswith(
        f"/OdpisAktualny/{krs}?rejestr=P&format=json"
    )
    assert payload["checked_key"] == f"{nip}|{krs}"
    assert (summary.checked, summary.applied_fields, summary.kept_fields) == (1, 4, 1)
    assert (summary.mf_queries, summary.krs_queries) == (1, 1)
    async with AsyncSessionLocal() as db:
        run = await db.get(SalesSignalRun, entry.run_id)
        assert (run.kind, run.status, run.token_hash) == ("registry", "received", None)
        assert run.report["checked"] == 1 and run.report["mf_queries"] == 1


@pytest.mark.asyncio
async def test_nip_from_krs_already_on_other_card_is_history_only(fake) -> None:
    nip, krs = _nip(), _krs()
    fake.krs[krs] = httpx.Response(200, json=_krs_answer(krs, nip))
    other = await _company(f"Druga {uuid.uuid4().hex[:8]}", nip=nip)
    company = await _company(f"Tylko KRS {uuid.uuid4().hex[:8]}", krs=krs)

    await _check([company])

    card = await _card(company)
    assert card.nip is None
    assert card.regon == "111222333"
    [entry] = await _history(company)
    taken = entry.payload["outcomes"]["nip"]
    assert (taken["result"], taken["other_id"]) == (cards.TAKEN, other)
    # Bez NIP-u na karcie MF nie był pytany.
    assert not any(call.startswith("/api/search") for call in fake.calls)


@pytest.mark.asyncio
async def test_removed_company_only_gets_history_and_stays_active(fake) -> None:
    krs = _krs()
    fake.removed.add(krs)
    company = await _company(f"Wykreślona {uuid.uuid4().hex[:8]}", krs=krs)

    summary = await _check([company])

    card = await _card(company)
    assert card.archived_at is None
    assert (card.nip, card.legal_name, card.regon) == (None, None, None)
    [entry] = await _history(company)
    assert entry.payload["state"] == registry.REMOVED
    assert entry.payload["removed_on"] == "17.03.2016"
    assert entry.payload["fields"] == {}
    assert summary.inactive == 1


@pytest.mark.asyncio
async def test_registry_timeout_leaves_card_untouched_and_due(fake) -> None:
    fake.timeout = True
    nip = _nip()
    company = await _company(f"Bez odpowiedzi {uuid.uuid4().hex[:8]}", nip=nip)

    summary = await _check([company])

    assert (summary.checked, summary.errors) == (0, 1)
    assert await _history(company) == []
    async with AsyncSessionLocal() as db:
        run = (
            await db.scalars(
                select(SalesSignalRun)
                .where(SalesSignalRun.kind == cards.KIND)
                .order_by(SalesSignalRun.id.desc())
                .limit(1)
            )
        ).one()
        assert run.status == "failed"
        due = await cards.due_company_ids(
            db, now=datetime.now(timezone.utc), limit=10, only=[company]
        )
    assert due == [company]


@pytest.mark.asyncio
async def test_checked_card_waits_30_days_unless_number_changes(fake) -> None:
    nip = _nip()
    company = await _company(f"Trzydzieści {uuid.uuid4().hex[:8]}", nip=nip)
    await _check([company])
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        assert await cards.due_company_ids(db, now=now, limit=10, only=[company]) == []
        later = now + cards.RESEND_AFTER + timedelta(minutes=1)
        assert await cards.due_company_ids(db, now=later, limit=10, only=[company]) == [
            company
        ]
        await db.execute(
            update(SalesCompany).where(SalesCompany.id == company).values(nip=_nip())
        )
        await db.commit()
        assert await cards.due_company_ids(db, now=now, limit=10, only=[company]) == [
            company
        ]
    # NIP-u nie ma w wykazie: wpis „brak w rejestrze”, karta bez zmian.
    [entry] = await _history(company)
    assert entry.payload["state"] == registry.NOT_FOUND


@pytest.mark.asyncio
async def test_repeated_check_confirms_once_then_only_refreshes(fake) -> None:
    nip = _nip()
    fake.vat[nip] = _vat_answer(nip, None)
    company = await _company(f"Dwa razy {uuid.uuid4().hex[:8]}", nip=nip)
    await _check([company])
    await _check([company])
    first, second = await _history(company)
    await _check([company])
    # Trzecie sprawdzenie z tym samym wynikiem nie dokłada wiersza historii.
    assert [row.id for row in await _history(company)] == [first.id, second.id]
    assert first.payload["outcomes"]["regon"]["result"] == cards.APPLIED
    assert second.payload["outcomes"]["regon"]["result"] == cards.SAME


@pytest.mark.asyncio
async def test_daily_mf_budget_stops_vat_queries(fake) -> None:
    nip = _nip()
    company = await _company(f"Limit {uuid.uuid4().hex[:8]}", nip=nip)
    summary = await _check([company], mf_budget=0)
    assert fake.calls == []
    assert (summary.errors, summary.mf_queries) == (1, 0)


@pytest.mark.asyncio
async def test_night_step_runs_once_an_hour_between_one_and_six(
    fake, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "SALES_REGISTRY_ENABLED", True)
    owner = await _user("sales_edit")
    nip = _nip()
    company = await _company(
        f"Noc {uuid.uuid4().hex[:8]}", nip=nip, owner_user_id=owner.id
    )
    async with AsyncSessionLocal() as db:
        # Inne biegi nocne z tej bazy nie mogą zjeść godziny ani limitu.
        await db.execute(
            delete(SalesSignalRun).where(SalesSignalRun.kind == cards.KIND)
        )
        await db.commit()
    original = cards.due_company_ids

    async def only_ours(db, *, now, limit, only=None):
        # Wspólna baza testów ma inne karty z NIP-em; noc bierze tylko tę.
        return await original(db, now=now, limit=limit, only=[company])

    monkeypatch.setattr(cards, "due_company_ids", only_ours)
    now = datetime.now(timezone.utc)
    night = local_now().replace(hour=2)
    noon = local_now().replace(hour=12)
    async with AsyncSessionLocal() as db:
        assert await cards.night_step(db, now=now, local=noon) == 0
    async with AsyncSessionLocal() as db:
        assert await cards.night_step(db, now=now, local=night) == 1
    async with AsyncSessionLocal() as db:
        assert await cards.night_step(db, now=now, local=night) == 0
    assert len(await _history(company)) == 1


@pytest.mark.asyncio
async def test_night_step_off_without_flag(fake, monkeypatch) -> None:
    monkeypatch.setattr(settings, "SALES_REGISTRY_ENABLED", False)
    async with AsyncSessionLocal() as db:
        night = local_now().replace(hour=2)
        assert (
            await cards.night_step(db, now=datetime.now(timezone.utc), local=night) == 0
        )
    assert fake.calls == []


# ── Wyzwalacz po zapisie NIP-u na ekranie Firmy ──────────────────────────


@pytest.fixture
def spawned(monkeypatch) -> list[tuple[list[int], int | None]]:
    calls: list[tuple[list[int], int | None]] = []

    async def record(company_ids: list[int], *, user_id: int | None = None) -> None:
        calls.append((company_ids, user_id))

    monkeypatch.setattr(cards, "check_after_save", record)
    return calls


@pytest.mark.asyncio
async def test_saving_new_nip_starts_registry_check(
    app_client, spawned, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "SALES_REGISTRY_ENABLED", True)
    editor = await _user("sales_edit")
    company = await _company(f"Ekran {uuid.uuid4().hex[:8]}")

    renamed = await app_client.patch(
        f"{COMPANIES}/{company}", json={"industry": "IT"}, headers=_headers(editor)
    )
    assert renamed.status_code == 200, renamed.text
    assert spawned == []

    saved = await app_client.patch(
        f"{COMPANIES}/{company}", json={"nip": _nip()}, headers=_headers(editor)
    )
    assert saved.status_code == 200, saved.text
    assert spawned == [([company], editor.id)]

    created = await app_client.post(
        COMPANIES,
        json={"name": f"Nowa {uuid.uuid4().hex[:8]}", "krs": _krs()},
        headers=_headers(editor),
    )
    assert created.status_code == 201, created.text
    assert spawned[-1] == ([created.json()["id"]], editor.id)


@pytest.mark.asyncio
async def test_no_registry_check_with_flag_off(
    app_client, spawned, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "SALES_REGISTRY_ENABLED", False)
    editor = await _user("sales_edit")
    company = await _company(f"Wyłączone {uuid.uuid4().hex[:8]}")
    saved = await app_client.patch(
        f"{COMPANIES}/{company}", json={"nip": _nip()}, headers=_headers(editor)
    )
    assert saved.status_code == 200, saved.text
    assert spawned == []
