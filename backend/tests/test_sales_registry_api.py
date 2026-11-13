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
from sqlalchemy import delete, update

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import local_now
from app.models.app_setting import AppSetting
from app.models.sales import SalesBotResult, SalesCompany
from app.services.sales import registry
from app.services.sales import registry_cards as cards
from app.services.sales.bot_tasks import enrich
from tests.test_sales_companies_api import _headers, _user
from tests.test_sales_signals_api import _company, _run

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
    """Rejestry w pamięci: ``vat[nip]`` → wpis, ``krs[numer]`` → odpowiedź odpisu."""

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


async def _reset_usage() -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(AppSetting).where(AppSetting.key == cards.USAGE_KEY))
        await db.commit()


@pytest.fixture
async def fake(monkeypatch) -> FakeRegistries:
    registries = FakeRegistries()
    monkeypatch.setattr(registry, "BACKOFF_SECONDS", 0)
    monkeypatch.setattr(cards, "new_client", registries.client)
    await _reset_usage()
    return registries


async def _check(ids: list[int], **kwargs: Any) -> cards.Summary:
    async with AsyncSessionLocal() as db:
        return await cards.check_companies(
            db, ids, now=datetime.now(timezone.utc), **kwargs
        )


async def _card(company_id: int) -> SalesCompany:
    async with AsyncSessionLocal() as db:
        return await db.get(SalesCompany, company_id)


async def _history(company_id: int) -> list[dict[str, Any]]:
    return list((await _card(company_id)).custom_fields.get(cards.HISTORY) or [])


def _lines(history: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {line["field"]: line for entry in history for line in entry["lines"]}


@pytest.mark.asyncio
async def test_empty_fields_filled_human_field_kept_and_history_written(fake) -> None:
    nip, krs = _nip(), _krs()
    fake.vat[nip] = _vat_answer(nip, krs)
    fake.krs[krs] = httpx.Response(200, json=_krs_answer(krs, nip))
    company = await _company(
        f"Rejestr {uuid.uuid4().hex[:8]}",
        nip=nip,
        legal_name="Nazwa handlowca",
        custom_fields={"inne": "zostaje"},
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
    custom = card.custom_fields
    assert custom["inne"] == "zostaje"
    assert custom[cards.CHECKED_KEY] == f"{nip}|{krs}"
    assert custom[cards.STATE] == registry.ACTIVE
    assert custom[cards.CHECKED_AT]
    [entry] = custom[cards.HISTORY]
    assert entry["source"] == "krs"
    lines = _lines(custom[cards.HISTORY])
    assert lines["legal_name"]["result"] == cards.KEPT
    assert lines["legal_name"]["before"] == "Nazwa handlowca"
    assert lines["krs"]["result"] == cards.APPLIED
    assert lines["krs"]["url"].endswith(f"/OdpisAktualny/{krs}?rejestr=P&format=json")
    assert "nip" not in lines  # zgodny NIP nie jest zmianą
    assert (summary.checked, summary.applied_fields, summary.kept_fields) == (1, 4, 1)
    assert (summary.mf_queries, summary.krs_queries) == (1, 1)
    async with AsyncSessionLocal() as db:
        used = await cards.usage(db, now=datetime.now(timezone.utc))
    assert used["mf_queries"] == 1


@pytest.mark.asyncio
async def test_field_written_by_enrich_bot_is_updated_from_registry(fake) -> None:
    nip = _nip()
    fake.vat[nip] = _vat_answer(nip, None)
    company = await _company(
        f"Od bota {uuid.uuid4().hex[:8]}", nip=nip, hq_city="Katowice"
    )
    run_id, _ = await _run([company], kind=enrich.KIND, status="received")
    async with AsyncSessionLocal() as db:
        db.add(
            SalesBotResult(
                run_id=run_id,
                kind=enrich.KIND,
                company_id=company,
                status="accepted",
                payload={
                    "fields": {"hq_city": {"value": "Katowice"}},
                    "outcomes": {"hq_city": {"result": enrich.APPLIED}},
                },
                fingerprint=f"test|{uuid.uuid4().hex}",
            )
        )
        await db.commit()

    await _check([company])

    assert (await _card(company)).hq_city == "Bielsko-Biała"
    line = _lines(await _history(company))["hq_city"]
    assert (line["result"], line["before"]) == (cards.APPLIED, "Katowice")


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
    taken = _lines(await _history(company))["nip"]
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
    assert card.custom_fields[cards.STATE] == registry.REMOVED
    [entry] = await _history(company)
    [line] = entry["lines"]
    assert (line["field"], line["result"], line["after"], line["removed_on"]) == (
        "state",
        cards.INACTIVE,
        registry.REMOVED,
        "17.03.2016",
    )
    assert summary.inactive == 1


@pytest.mark.asyncio
async def test_registry_timeout_leaves_card_untouched_and_due(fake) -> None:
    fake.timeout = True
    nip = _nip()
    company = await _company(f"Bez odpowiedzi {uuid.uuid4().hex[:8]}", nip=nip)

    summary = await _check([company])

    assert (summary.checked, summary.errors) == (0, 1)
    card = await _card(company)
    assert cards.CHECKED_AT not in card.custom_fields
    async with AsyncSessionLocal() as db:
        due = await cards.due_company_ids(
            db, now=datetime.now(timezone.utc), limit=10, only=[company]
        )
    assert due == [company]


@pytest.mark.asyncio
async def test_krs_outage_with_vat_answer_still_checks_the_card(fake) -> None:
    nip, krs = _nip(), _krs()
    fake.vat[nip] = _vat_answer(nip, krs)
    fake.krs[krs] = httpx.Response(503)
    company = await _company(f"Bez KRS {uuid.uuid4().hex[:8]}", nip=nip)

    summary = await _check([company])

    # Odpowiedź MF nie przepada: wynik z białej listy, KRS wróci za 30 dni.
    assert (summary.checked, summary.errors) == (1, 0)
    assert summary.cards[company]["krs_unavailable"] is True
    line = _lines(await _history(company))["regon"]
    assert line["url"].startswith("https://wl-api.mf.gov.pl/")
    assert (await _card(company)).krs == krs


@pytest.mark.asyncio
async def test_checked_card_waits_30_days_unless_number_changes(fake) -> None:
    nip = _nip()
    company = await _company(f"Trzydzieści {uuid.uuid4().hex[:8]}", nip=nip)
    await _check([company])
    # NIP-u nie ma w wykazie: stan „brak w rejestrze”, bez wpisu historii.
    card = await _card(company)
    assert card.custom_fields[cards.STATE] == registry.NOT_FOUND
    assert await _history(company) == []
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


@pytest.mark.asyncio
async def test_repeated_check_without_change_adds_no_history(fake) -> None:
    nip = _nip()
    fake.vat[nip] = _vat_answer(nip, None)
    company = await _company(f"Dwa razy {uuid.uuid4().hex[:8]}", nip=nip)
    await _check([company])
    first = await _history(company)
    await _check([company])
    assert await _history(company) == first
    assert _lines(first)["regon"]["result"] == cards.APPLIED


@pytest.mark.asyncio
async def test_history_keeps_last_thirty_entries(fake) -> None:
    nip = _nip()
    fake.vat[nip] = _vat_answer(nip, None)
    old = [
        {"at": "2026-01-01T00:00:00+00:00", "source": "vat", "lines": [{"field": "x"}]}
    ] * cards.HISTORY_KEEP
    company = await _company(
        f"Długa {uuid.uuid4().hex[:8]}",
        nip=nip,
        custom_fields={cards.HISTORY: old},
    )
    await _check([company])
    history = await _history(company)
    assert len(history) == cards.HISTORY_KEEP
    assert history[-1]["lines"][0]["field"] != "x"


@pytest.mark.asyncio
async def test_daily_mf_budget_stops_vat_queries(fake) -> None:
    nip = _nip()
    company = await _company(f"Limit {uuid.uuid4().hex[:8]}", nip=nip)
    summary = await _check([company], mf_budget=0)
    assert fake.calls == []
    assert (summary.errors, summary.mf_queries) == (1, 0)


@pytest.mark.asyncio
async def test_night_step_runs_once_an_hour_and_save_does_not_take_the_hour(
    fake, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "SALES_REGISTRY_ENABLED", True)
    owner = await _user("sales_edit")
    saved = await _company(f"Po bocie {uuid.uuid4().hex[:8]}", nip=_nip())
    company = await _company(
        f"Noc {uuid.uuid4().hex[:8]}", nip=_nip(), owner_user_id=owner.id
    )
    # Sprawdzenie po zapisie (np. po nocnym raporcie bota) nie zabiera godziny nocy.
    await cards.check_after_save([saved])
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
    assert (await _card(company)).custom_fields[cards.CHECKED_AT]


@pytest.mark.asyncio
async def test_night_step_off_without_flag(fake, monkeypatch) -> None:
    monkeypatch.setattr(settings, "SALES_REGISTRY_ENABLED", False)
    async with AsyncSessionLocal() as db:
        night = local_now().replace(hour=2)
        assert (
            await cards.night_step(db, now=datetime.now(timezone.utc), local=night) == 0
        )
    assert fake.calls == []


# ── Ekran: wyzwalacz po zapisie NIP-u i historia karty ───────────────────


@pytest.fixture
def spawned(monkeypatch) -> list[list[int]]:
    calls: list[list[int]] = []

    async def record(company_ids: list[int]) -> None:
        calls.append(company_ids)

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
    assert spawned == [[company]]

    created = await app_client.post(
        COMPANIES,
        json={"name": f"Nowa {uuid.uuid4().hex[:8]}", "krs": _krs()},
        headers=_headers(editor),
    )
    assert created.status_code == 201, created.text
    assert spawned[-1] == [created.json()["id"]]


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


@pytest.mark.asyncio
async def test_card_history_shows_registry_entries(
    app_client, fake, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "SALES_REGISTRY_ENABLED", True)
    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", False)
    krs = _krs()
    fake.removed.add(krs)
    company = await _company(f"Historia {uuid.uuid4().hex[:8]}", krs=krs)
    await _check([company])
    viewer = await _user("sales_view")

    response = await app_client.get(
        f"{COMPANIES}/{company}/bot-history", headers=_headers(viewer)
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["enabled"] is True
    [entry] = body["items"]
    assert entry["bot"] == "Rejestry (KRS)"
    assert entry["lines"][0]["after"] == "firma wykreślona z KRS"
