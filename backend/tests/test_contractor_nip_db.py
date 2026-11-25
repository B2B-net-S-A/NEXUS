"""NIP kontraktora z faktur KSeF zapisuje się sam — na bazie (decyzja Artura z 25.11.2026).

Faktura, która byłaby podpowiedzią „NIP kontraktora”, zapisuje NIP osobie sama,
gdy historia faktur tego NIP-u (zakupy w KSeF albo nasza faktura „Benefit”)
wskazuje tylko tę osobę; reszta czeka na Finanse jak dotąd. Przebieg wstecz
zapisuje tylko ``candidates.nip``. Osoby, NIP-y, numery i kwoty fikcyjne.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today, local_now
from app.models.app_setting import AppSetting
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.candidate import Candidate
from app.models.client_sales_invoice import ClientSalesInvoice
from app.models.client_settlement import ClientContractorInvoice
from app.models.contract import ContractStatus
from app.models.hr_approval import ApprovalDocument
from app.services.client_settlements import contractor_invoices as ci
from app.services.client_settlements import contractor_nip as cn
from app.services.hr.approvals import cost_invoices
from tests.test_client_audit_2026_09_24 import _client, _contract
from tests.test_client_settlements_consultant_db import _module, _restore
from tests.test_client_settlements_contractor_invoices_db import (
    ACTOR,
    _cleanup,
    _consider,
    _invoice,
    _item,
    _months,
    _nip,
    _person,
    _settlement,
    _tag,
)

pytestmark = pytest.mark.asyncio


class _Docs:
    """Faktury z historii (zakupy w ``approval_documents``, „Benefit”) do sprzątnięcia."""

    def __init__(self) -> None:
        self.purchases: list[str] = []
        self.benefits: list[str] = []

    async def purchase(
        self, nip: str, name: str, issue: date, *, kind: str = "Vat"
    ) -> None:
        item = _item(nip, name, "9000.00", issue)
        item["invoiceType"] = kind
        async with AsyncSessionLocal() as db:
            await cost_invoices.store(
                db, item, ksef_number=item["ksefNumber"], now=local_now(), match=False
            )
            await db.commit()
        self.purchases.append(item["ksefNumber"])

    async def benefit(self, nip: str, buyer: str, issue: date) -> None:
        ksef = f"9990000001-{issue:%Y%m%d}-{uuid.uuid4().hex[:12].upper()}-AB"
        async with AsyncSessionLocal() as db:
            db.add(
                ClientSalesInvoice(
                    ksef_number=ksef,
                    xml_sha256=hashlib.sha256(ksef.encode()).hexdigest(),
                    buyer_nip=nip,
                    buyer_name=buyer,
                    invoice_number=f"{random.randint(1, 999)}/{issue:%m/%Y}/Benefit",
                    issue_date=issue,
                    currency="PLN",
                    net_amount=Decimal("100.00"),
                    gross_amount=Decimal("123.00"),
                    items=[],
                    order_refs=[],
                    match_status="unmatched",
                )
            )
            await db.commit()
        self.benefits.append(ksef)

    async def drop(self) -> None:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(ApprovalDocument).where(
                    ApprovalDocument.ksef_number.in_(self.purchases)
                )
            )
            await db.execute(
                delete(ClientSalesInvoice).where(
                    ClientSalesInvoice.ksef_number.in_(self.benefits)
                )
            )
            await db.commit()


async def _nip_of(candidate_id: int) -> str | None:
    async with AsyncSessionLocal() as db:
        return (await db.get(Candidate, candidate_id)).nip


def _earlier(issue: date) -> date:
    """Dzień z miesiąca sprzed dwóch miesięcy (``issue`` to 3. dzień miesiąca)."""

    return issue - timedelta(days=40)


async def test_druga_faktura_w_innym_miesiacu_zapisuje_nip_sama() -> None:
    client_id = await _client()
    _, _, issue = _months()
    first, last = f"Iza{_tag()}", f"Wzorcowa{_tag()}"
    contract_id, candidate_id = await _person(client_id, first=first, last=last)
    nip, docs = _nip(), _Docs()
    try:
        await docs.purchase(nip, f"{first} {last} IT", _earlier(issue))
        item = _item(nip, f"{last.upper()} {first.upper()}", "8640.00", issue)
        assert await _consider(item) == ci.CONFIRMED
        saved = await _invoice(item["ksefNumber"])
        assert (saved.nip_state, saved.decided_by) == (ci.CONFIRMED, None)
        assert saved.decided_at is not None and saved.contract_id == contract_id
        assert await _nip_of(candidate_id) == nip

        # Od teraz NIP wiąże faktury sam, bez nazwy osoby.
        later = _item(nip, "Zupełnie inna nazwa", "100.00", issue + timedelta(days=30))
        assert await _consider(later) == ci.KNOWN
    finally:
        await docs.drop()
        await _cleanup(client_id, [candidate_id])


async def test_jedna_faktura_albo_ten_sam_miesiac_zostaje_podpowiedzia() -> None:
    client_id = await _client()
    _, _, issue = _months()
    first, last = f"Ola{_tag()}", f"Pierwsza{_tag()}"
    contract_id, candidate_id = await _person(client_id, first=first, last=last)
    nip, docs = _nip(), _Docs()
    try:
        assert await _consider(_item(nip, f"{first} {last}", "500.00", issue)) == (
            ci.SUGGESTED
        )
        # Druga faktura z tego samego miesiąca i korekta z innego to nie dowód.
        await docs.purchase(nip, f"{first} {last}", _earlier(issue), kind="Kor")
        same_month = _item(nip, f"{first} {last}", "500.00", issue + timedelta(days=1))
        assert await _consider(same_month) == ci.SUGGESTED
        assert await _nip_of(candidate_id) is None
    finally:
        await docs.drop()
        await _cleanup(client_id, [candidate_id])


async def test_faktura_benefit_na_ten_nip_wystarcza_przy_pierwszym_zakupie() -> None:
    client_id = await _client()
    _, _, issue = _months()
    first, last = f"Ewa{_tag()}", f"Benefitowa{_tag()}"
    contract_id, candidate_id = await _person(client_id, first=first, last=last)
    nip, docs = _nip(), _Docs()
    try:
        await docs.benefit(nip, f"Usługi IT {first} {last}", issue - timedelta(days=8))
        item = _item(nip, f"{first} {last}", "7000.00", issue)
        assert await _consider(item) == ci.CONFIRMED
        assert await _nip_of(candidate_id) == nip
    finally:
        await docs.drop()
        await _cleanup(client_id, [candidate_id])


async def test_imiennicy_zostaja_podpowiedzia_mimo_historii() -> None:
    client_id = await _client()
    month, _, issue = _months()
    first, last = f"Piotr{_tag()}", f"Dwojak{_tag()}"
    first_id, cand_a = await _person(client_id, first=first, last=last)
    second_id, cand_b = await _person(client_id, first=first, last=last)
    nip, docs = _nip(), _Docs()
    try:
        await _settlement(client_id, second_id, month, "2000.00")
        await docs.purchase(nip, f"{first} {last}", _earlier(issue))
        hit = _item(nip, f"{first} {last}", "2000.00", issue)
        assert await _consider(hit) == ci.SUGGESTED
        assert (await _invoice(hit["ksefNumber"])).contract_id == second_id
        assert await _nip_of(cand_a) is None and await _nip_of(cand_b) is None
    finally:
        await docs.drop()
        await _cleanup(client_id, [cand_a, cand_b])


async def test_nip_innego_kandydata_albo_umowy_innej_osoby_zostaje_podpowiedzia() -> (
    None
):
    client_id = await _client()
    _, _, issue = _months()
    first, last = f"Jan{_tag()}", f"Zajety{_tag()}"
    contract_id, candidate_id = await _person(client_id, first=first, last=last)
    taken, partner, docs = _nip(), _nip(), _Docs()
    async with AsyncSessionLocal() as db:
        other = Candidate(name=f"Inny{_tag()}", lastname=f"Kandydat{_tag()}", nip=taken)
        former = Candidate(name=f"Dawny{_tag()}", lastname=f"Partner{_tag()}")
        db.add_all([other, former])
        await db.commit()
        other_id, former_id = other.id, former.id
    # Umowa z generatora B2B osoby, której kontrakt dawno się skończył.
    former_contract = await _contract(
        client_id,
        former_id,
        status=ContractStatus.ended,
        start_date=business_today() - timedelta(days=500),
        end_date=business_today() - timedelta(days=200),
    )
    seq = random.randint(10_000_000, 99_999_999)
    async with AsyncSessionLocal() as db:
        generated = B2BGeneratedContract(
            year=2031,
            seq=seq,
            contract_number=f"{seq}/2031",
            partner_name="Osoba Testowa",
            partner_nip=partner,
            candidate_id=former_id,
            contract_id=former_contract,
            language="pl",
            signature_status="unsigned",
            contract_status="in_progress",
        )
        db.add(generated)
        await db.commit()
        generated_id = generated.id
    try:
        for nip in (taken, partner):
            await docs.purchase(nip, f"{first} {last}", _earlier(issue))
            item = _item(nip, f"{first} {last}", "900.00", issue)
            assert await _consider(item) == ci.SUGGESTED
        assert await _nip_of(candidate_id) is None
    finally:
        await docs.drop()
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(B2BGeneratedContract).where(
                    B2BGeneratedContract.id == generated_id
                )
            )
            await db.commit()
        await _cleanup(client_id, [candidate_id, other_id, former_id])


async def test_osoba_z_innym_nip_em_nic_nie_dostaje() -> None:
    client_id = await _client()
    _, _, issue = _months()
    first, last = f"Ala{_tag()}", f"Zapisana{_tag()}"
    own = _nip()
    contract_id, candidate_id = await _person(
        client_id, first=first, last=last, nip=own
    )
    nip, docs = _nip(), _Docs()
    try:
        await docs.purchase(nip, f"{first} {last}", _earlier(issue))
        await docs.purchase(nip, f"{first} {last}", issue)
        item = _item(nip, f"{first} {last}", "900.00", issue + timedelta(days=1))
        assert await _consider(item) is None
        async with AsyncSessionLocal() as db:
            plan = await cn.plan(db, business_today())
        assert plan.decisions[nip] == (candidate_id, cn.HAS_NIP)
        assert candidate_id not in plan.confirm
        assert await _nip_of(candidate_id) == own
    finally:
        await docs.drop()
        await _cleanup(client_id, [candidate_id])


async def test_odrzucona_para_nie_wraca_ani_w_przebiegu_wstecz() -> None:
    client_id = await _client()
    _, _, issue = _months()
    first, last = f"Iwo{_tag()}", f"Odrzucony{_tag()}"
    contract_id, candidate_id = await _person(client_id, first=first, last=last)
    nip, docs = _nip(), _Docs()
    try:
        item = _item(nip, f"{first} {last}", "500.00", issue)
        assert await _consider(item) == ci.SUGGESTED
        async with AsyncSessionLocal() as db:
            saved = await _invoice(item["ksefNumber"])
            await ci.reject_nip(db, saved.id, ACTOR, local_now())
            await db.commit()
        await docs.purchase(nip, f"{first} {last}", _earlier(issue))
        again = _item(nip, f"{first} {last}", "500.00", issue + timedelta(days=31))
        assert await _consider(again) is None
        async with AsyncSessionLocal() as db:
            plan = await cn.plan(db, business_today())
        assert plan.decisions[nip] == (candidate_id, cn.REJECTED)
        assert await _nip_of(candidate_id) is None
    finally:
        await docs.drop()
        await _cleanup(client_id, [candidate_id])


async def test_fundacja_bez_osoby_w_nazwie_i_inkubator_z_nazwiskiem() -> None:
    client_id = await _client()
    _, _, issue = _months()
    first, last = f"Kuba{_tag()}", f"Inkubowany{_tag()}"
    contract_id, candidate_id = await _person(client_id, first=first, last=last)
    foundation = f"Fundacja Przykładowy Start {_tag()}"
    plain, shared, docs = _nip(), _nip(), _Docs()
    try:
        # Sama fundacja: to nie kontraktor.
        await docs.purchase(plain, foundation, _earlier(issue))
        assert await _consider(_item(plain, foundation, "900.00", issue)) is None

        # Inkubator: ten sam NIP wystawia też bez osoby w nazwie (za innych).
        await docs.purchase(shared, foundation, _earlier(issue))
        await docs.purchase(
            shared, f"{foundation} {first} {last}", _earlier(issue) - timedelta(days=31)
        )
        item = _item(shared, f"{foundation} {first} {last}", "900.00", issue)
        assert await _consider(item) == ci.SUGGESTED
        assert await _nip_of(candidate_id) is None
        async with AsyncSessionLocal() as db:
            plan = await cn.plan(db, business_today())
        assert plan.decisions[plain] == (None, cn.NO_PERSON)
        assert plan.decisions[shared] == (None, cn.UNNAMED)
    finally:
        await docs.drop()
        await _cleanup(client_id, [candidate_id])


async def test_przebieg_wstecz_na_sucho_liczy_a_potem_zapisuje_tylko_nip(
    monkeypatch,
) -> None:
    now, today = local_now(), business_today()
    async with AsyncSessionLocal() as db:
        before = await cn.backfill(db, today=today, now=now, dry_run=True)
    client_id = await _client()
    _, _, issue = _months()
    people: dict[str, tuple[int, int, str, str]] = {}
    for key in ("proven", "benefit", "single", "twin_a", "twin_b"):
        first, last = f"Osoba{_tag()}", f"Wsteczna{_tag()}"
        if key == "twin_b":
            first, last = people["twin_a"][2], people["twin_a"][3]
        contract_id, candidate_id = await _person(client_id, first=first, last=last)
        people[key] = (contract_id, candidate_id, first, last)
    nips = {key: _nip() for key in ("proven", "benefit", "single", "twin", "plain")}
    docs = _Docs()

    def name(key: str) -> str:
        return f"{people[key][2]} {people[key][3]}"

    try:
        # Podpowiedź sprzed historii: przebieg wstecz ją zatwierdzi.
        pending = _item(nips["proven"], name("proven"), "800.00", issue)
        assert await _consider(pending) == ci.SUGGESTED
        await docs.purchase(nips["proven"], name("proven"), _earlier(issue))
        await docs.purchase(nips["benefit"], name("benefit"), issue)
        await docs.benefit(nips["benefit"], f"Firma {name('benefit')}", issue)
        await docs.purchase(nips["single"], name("single"), issue)
        await docs.purchase(nips["twin"], name("twin_a"), _earlier(issue))
        await docs.purchase(nips["twin"], name("twin_a"), issue)
        await docs.purchase(nips["plain"], f"Fundacja Wsteczna {_tag()}", issue)
        await docs.purchase(
            nips["plain"], f"Fundacja Wsteczna {_tag()}", _earlier(issue)
        )

        async with AsyncSessionLocal() as db:
            dry = await cn.backfill(db, today=today, now=now, dry_run=True)
        delta = {k: dry.get(k, 0) - before.get(k, 0) for k in set(dry) | set(before)}
        assert {k: v for k, v in delta.items() if v} == {
            "nips": 5,
            "candidates": 2,
            "proven": 2,
            "with_benefit": 1,
            "single_month": 1,
            "several_people": 1,
            "no_person": 1,
        }
        assert await _nip_of(people["proven"][1]) is None  # na sucho bez zapisu

        # Zapis tylko dla osób z tego testu (baza testów jest wspólna).
        mine = {candidate_id for _, candidate_id, _, _ in people.values()}
        real_plan = cn.plan

        async def only_mine(db: Any, today: date) -> cn.Plan:
            result = await real_plan(db, today)
            result.confirm = {c: n for c, n in result.confirm.items() if c in mine}
            return result

        monkeypatch.setattr(cn, "plan", only_mine)
        async with AsyncSessionLocal() as db:
            done = await cn.backfill(db, today=today, now=now)
            await db.commit()
        assert (done["written"], done["failed"]) == (2, 0)
        assert sorted(done["candidate_ids"]) == sorted(
            [people["proven"][1], people["benefit"][1]]
        )
        assert await _nip_of(people["proven"][1]) == nips["proven"]
        assert await _nip_of(people["benefit"][1]) == nips["benefit"]
        for key in ("single", "twin_a", "twin_b"):
            assert await _nip_of(people[key][1]) is None
        confirmed = await _invoice(pending["ksefNumber"])
        assert (confirmed.nip_state, confirmed.decided_by) == (ci.CONFIRMED, None)
        # Bez wierszy faktur z historii.
        async with AsyncSessionLocal() as db:
            rows = await db.scalars(
                select(ClientContractorInvoice.ksef_number).where(
                    ClientContractorInvoice.seller_nip.in_(list(nips.values()))
                )
            )
            assert list(rows) == [pending["ksefNumber"]]
    finally:
        await docs.drop()
        await _cleanup(client_id, [c for _, c, _, _ in people.values()])


async def test_przebieg_wstecz_raz_po_wdrozeniu(monkeypatch) -> None:
    key = f"contractor_nip_backfill_test_{_tag()}"
    calls: list[str] = []

    async def counted(db: Any, *, today: date, now: Any) -> dict[str, Any]:
        calls.append(today.isoformat())
        return {"nips": 0, "candidates": 0, "written": 0, "candidate_ids": []}

    monkeypatch.setattr(cn, "BACKFILL_KEY", key)
    monkeypatch.setattr(cn, "backfill", counted)
    previous = await _module(False)
    try:
        async with AsyncSessionLocal() as db:
            assert await cn.backfill_once(db) is None  # moduł wyłączony: czeka
        await _module(True)
        async with AsyncSessionLocal() as db:
            summary = await cn.backfill_once(db)
        assert summary is not None and summary["candidates"] == 0
        async with AsyncSessionLocal() as db:
            marker = await db.get(AppSetting, key)
            assert marker is not None and marker.value["executed_at"]
            assert await cn.backfill_once(db) is None
        assert len(calls) == 1
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AppSetting).where(AppSetting.key == key))
            await db.commit()
        await _restore(previous)
