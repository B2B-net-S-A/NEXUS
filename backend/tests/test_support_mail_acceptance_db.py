"""Akceptacja klienta w samej treści maila na jednej skrzynce wsparcie@ (E8).

Próba rozliczeń IX–X 2026: klient (PKO, BIK) odpisuje w wątku z TS bez załącznika,
np. „łączna liczba godzin: 112, październik 2026”. Router oddawał czytnikowi rozliczeń
tylko maile z załącznikiem, więc taka akceptacja zostawała sprawą, a reguła
``proof.accept_has_hours`` nie miała czego sprawdzić. Teraz mail bez załącznika na adres
rozliczeń z domeny klienta z regułą akceptacji mailowej idzie do rozliczeń i ląduje
jako ``.eml`` u osoby z tematu. Domeny, osoby i maile fikcyjne.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client_settlement import ClientSettlementRuleSet
from app.models.consultant_portal import CpDocument
from app.models.contact import Contact
from app.services import storage_service, support_mail_route
from app.services.consultant_portal import mailbox
from tests.consultant_portal_seed import (  # noqa: F401  (fixture'y)
    make_person,
    portal_restored,
    set_portal,
)
from tests.test_admin_cases_mail_ingest import (  # noqa: F401  (fixture'y)
    FakeMailbox as CasesMailbox,
    _cases_for,
    _run,
    cases_on,
    mailbox_on,
    shared_support_mailbox,
)

pytestmark = pytest.mark.asyncio

SETTLEMENTS = "rozliczenia@example.com"


def _domain() -> str:
    return f"bank-{uuid.uuid4().hex[:8]}.example"


async def _rule_set(client_id: int, rules: dict) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            ClientSettlementRuleSet(
                client_id=client_id, effective_from="2026-01", rules=rules
            )
        )
        await db.commit()


async def _drop_rule_sets(client_ids: list[int]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(ClientSettlementRuleSet).where(
                ClientSettlementRuleSet.client_id.in_(client_ids)
            )
        )
        await db.commit()


def _accept_rules(domain: str) -> dict:
    return {
        "proof.accept_has_hours": {"level": "warn", "params": {}},
        "proof.excel_with_mail": {"level": "warn", "params": {"domain": domain}},
    }


def _without_accept_rules(domain: str) -> dict:
    # Domena wpisana, ale obie reguły akceptacji mailowej wyłączone.
    return {
        "proof.accept_has_hours": {"level": "off", "params": {}},
        "proof.excel_with_mail": {"level": "off", "params": {"domain": domain}},
    }


async def test_domains_only_of_clients_with_mail_acceptance_rule() -> None:
    with_rule, without_rule, hours_only = (
        await make_person(),
        await make_person(),
        await make_person(),
    )
    on, off, contact = _domain(), _domain(), _domain()
    await _rule_set(with_rule.client_id, _accept_rules(f"@{on.upper()}"))
    await _rule_set(without_rule.client_id, _without_accept_rules(off))
    # Jak PKO na produkcji: sama ``proof.accept_has_hours``, domena bez wpisu w regule,
    # więc bierzemy domenę z adresów kontaktów klienta.
    await _rule_set(
        hours_only.client_id,
        {"proof.accept_has_hours": {"level": "block", "params": {}}},
    )
    async with AsyncSessionLocal() as db:
        db.add(
            Contact(
                client_id=hours_only.client_id, name="Kontakt", email=f"A@{contact}"
            )
        )
        await db.commit()
    try:
        async with AsyncSessionLocal() as db:
            found = await support_mail_route.acceptance_clients(db)
        assert found.get(on) == frozenset({with_rule.client_id})
        assert found.get(contact) == frozenset({hours_only.client_id})
        assert off not in found
    finally:
        await _drop_rule_sets(
            [with_rule.client_id, without_rule.client_id, hours_only.client_id]
        )
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(Contact).where(Contact.client_id == hours_only.client_id)
            )
            await db.commit()


async def test_cases_reader_leaves_client_acceptance_to_settlements(
    shared_support_mailbox,  # noqa: F811
) -> None:
    with_rule, without_rule = await make_person(), await make_person()
    on, off = _domain(), _domain()
    await _rule_set(with_rule.client_id, _accept_rules(on))
    await _rule_set(without_rule.client_id, _without_accept_rules(off))
    try:
        fake = CasesMailbox()
        acceptance = fake.add(
            subject="RE: Akceptacja godzin październik 2026",
            hours_ago=4,
            sender=f"przelozony@{on}",
            to=[SETTLEMENTS],
        )
        no_rule = fake.add(
            subject="RE: Akceptacja godzin październik 2026",
            hours_ago=3,
            sender=f"przelozony@{off}",
            to=[SETTLEMENTS],
        )
        # Bez adresu rozliczeń w nagłówkach to dalej sprawa, także z domeny klienta.
        not_to_settlements = fake.add(
            subject="Pytanie", hours_ago=2, sender=f"kierownik@{on}", to=["x@ex.com"]
        )

        result = await _run(fake)

        assert result["routed_settlements"] == 1
        cases = await _cases_for(fake)
        assert acceptance["id"] not in cases
        assert no_rule["id"] in cases and not_to_settlements["id"] in cases
    finally:
        await _drop_rule_sets([with_rule.client_id, without_rule.client_id])


# ── Czytnik rozliczeń ───────────────────────────────────────────────────────


class SettlementsMailbox:
    def __init__(self, messages: list[dict], raw: dict[str, bytes]) -> None:
        self.messages = messages
        self.raw = raw

    async def list_messages(self, since):
        return self.messages

    async def attachments(self, message_id):
        return []

    async def mime(self, message_id):
        return self.raw.get(message_id)


def _message(message_id: str, sender: str, subject: str) -> dict:
    return {
        "id": message_id,
        "subject": subject,
        "hasAttachments": False,
        "from": {"emailAddress": {"address": sender}},
        "toRecipients": [{"emailAddress": {"address": SETTLEMENTS}}],
        "receivedDateTime": datetime.now(timezone.utc).isoformat(),
    }


def _eml(sender: str, subject: str) -> bytes:
    return (
        f"From: Przelozony <{sender}>\r\nTo: {SETTLEMENTS}\r\nSubject: {subject}\r\n"
        "MIME-Version: 1.0\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n"
        "Akceptuje. Laczna liczba godzin: 112, pazdziernik 2026.\r\n"
    ).encode()


@pytest_asyncio.fixture
async def settlements_shared(monkeypatch, portal_restored, tmp_path):  # noqa: F811
    from app.core.config import settings

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(
        settings, "CONSULTANT_PORTAL_SETTLEMENTS_MAILBOX", "wsparcie@example.com"
    )
    monkeypatch.setattr(settings, "ADMIN_CASES_M365_MAILBOX", "wsparcie@example.com")
    monkeypatch.setattr(
        settings, "CONSULTANT_PORTAL_SETTLEMENTS_ADDRESSES", SETTLEMENTS
    )
    await set_portal("internal")
    yield


async def _documents(ids: list[str]) -> list[CpDocument]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(CpDocument).where(CpDocument.graph_message_id.in_(ids))
                )
            ).all()
        )


async def _surname(person) -> str:
    async with AsyncSessionLocal() as db:
        return (await db.get(Candidate, person.candidate_id)).lastname


@pytest.mark.usefixtures("settlements_shared")
async def test_settlements_reader_stores_acceptance_body_with_person_from_subject() -> (
    None
):
    with_rule, without_rule = await make_person(), await make_person()
    on, off = _domain(), _domain()
    await _rule_set(with_rule.client_id, _accept_rules(on))
    await _rule_set(without_rule.client_id, _without_accept_rules(off))
    tag = uuid.uuid4().hex[:6]
    accept_id, other_id = f"acc-{tag}", f"off-{tag}"
    # Temat jak u klienta: inicjał imienia i nazwisko (BIK).
    subject = f"RE: Akceptacja godzin październik 2026 - A. {await _surname(with_rule)}"
    other = f"RE: Akceptacja październik 2026 - A. {await _surname(without_rule)}"
    reader = SettlementsMailbox(
        [
            _message(accept_id, f"przelozony@{on}", subject),
            _message(other_id, f"przelozony@{off}", other),
        ],
        {
            accept_id: _eml(f"przelozony@{on}", subject),
            other_id: _eml(f"przelozony@{off}", other),
        },
    )
    try:
        async with AsyncSessionLocal() as db:
            result = await mailbox.run_once(db, mailbox=reader)
            await db.commit()
        assert result["status"] == "ok" and result["created"] == 1
        stored = await _documents([accept_id, other_id])
        assert [
            (d.graph_message_id, d.contract_id, d.kind, d.period_year, d.period_month)
            for d in stored
        ] == [(accept_id, with_rule.contract_id, "report", 2026, 10)]
        assert stored[0].file_name.endswith(".eml")
    finally:
        await _drop_rule_sets([with_rule.client_id, without_rule.client_id])
