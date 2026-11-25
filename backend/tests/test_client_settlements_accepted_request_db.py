"""MD z prośby o akceptację zaakceptowanej przez klienta, z bazą.

Dane fikcyjne (osoba z ``_candidate``, domena ``klient.example``). Układ jak
w próbie IX–X 2026: jedynym dokumentem miesiąca osoby jest odpowiedź klienta
„Akceptuję” na naszą prośbę „… - 176h”, bez pliku godzin.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from email.message import EmailMessage
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects.postgresql import insert

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today, local_now
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.client_settlement import ClientSettlement, ClientSettlementRuleSet
from app.models.contract import Contract
from app.services import storage_service
from app.services.client_settlements import accepted_request, mail_text, service
from app.services.consultant_portal import documents
from tests.test_client_audit_2026_09_24 import _candidate, _client, _contract

pytestmark = pytest.mark.asyncio

DOMAIN = "klient.example"


def _month() -> str:
    previous = business_today().replace(day=1) - timedelta(days=1)
    return f"{previous:%Y-%m}"


def _reply(person: str, month: str, reply: str) -> bytes:
    year, mon = (int(x) for x in month.split("-"))
    label = mail_text.MONTHS_NOMINATIVE[mon - 1]
    message = EmailMessage()
    message["Subject"] = f"RE: Akceptacja {label} {year} - {person}"
    message["From"] = f"Kierownik Klienta <kierownik@{DOMAIN}>"
    message["To"] = "rozliczenia@firma-testowa.example"
    message.set_content(
        f"{reply}\n\nKierownik Klienta\n\n"
        "From: rozliczenia@firma-testowa.example <rozliczenia@firma-testowa.example>\n"
        f"Subject: Akceptacja {label} {year} - {person}\n\n"
        f"Proszę o akceptację czasu za {label} dla {person} - 176h.\n"
    )
    return message.as_bytes()


async def _world() -> SimpleNamespace:
    month = _month()
    client_id = await _client()
    contract_id = await _contract(client_id, await _candidate())
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        candidate = await db.get(Candidate, contract.candidate_id)
        db.add(
            ClientSettlementRuleSet(
                client_id=client_id,
                effective_from="2020-01",
                rules={
                    "proof.accept_has_hours": {"level": "warn", "params": {}},
                    "proof.excel_with_mail": {
                        "level": "off",
                        "params": {"domain": DOMAIN},
                    },
                },
            )
        )
        await db.execute(
            insert(AppSetting)
            .values(key="client_settlements", value={"enabled": True})
            .on_conflict_do_update(
                index_elements=[AppSetting.key], set_={"value": {"enabled": True}}
            )
        )
        await db.commit()
    return SimpleNamespace(
        client_id=client_id,
        contract_id=contract_id,
        person=f"{candidate.name} {candidate.lastname}",
        month=month,
    )


async def _cleanup(client_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            ClientSettlement.__table__.delete().where(
                ClientSettlement.client_id == client_id
            )
        )
        await db.execute(
            ClientSettlementRuleSet.__table__.delete().where(
                ClientSettlementRuleSet.client_id == client_id
            )
        )
        await db.commit()
    from tests.test_client_audit_2026_09_24 import _cleanup as base_cleanup

    await base_cleanup(client_id)


async def _store(w: SimpleNamespace, content: bytes) -> ClientSettlement:
    year, mon = (int(x) for x in w.month.split("-"))
    async with AsyncSessionLocal() as db:
        await documents.store(
            db,
            contract_id=w.contract_id,
            kind="report",
            year=year,
            month=mon,
            content=content,
            file_name="RE Akceptacja.eml",
            channel="mailbox",
            now=local_now(),
            sender_email=f"kierownik@{DOMAIN}",
        )
        await db.commit()
        s = await service._settlement(db, w.contract_id, w.month)
        assert s is not None
        return s


def _titles(s: ClientSettlement) -> dict[str, str]:
    return {
        c["title"]: c["state"]
        for g in s.checks or []
        if isinstance(g, dict) and g.get("checks")
        for c in g["checks"]
    }


async def test_zaakceptowana_prosba_daje_md_i_zrodlo_w_kontrolach(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    w = await _world()
    try:
        s = await _store(w, _reply(w.person, w.month, "Akceptuję"))
        assert s.md_regular == Decimal("22.000")
        assert s.md_source == "rcp"
        groups = [g.get("title") for g in s.checks if isinstance(g, dict)]
        assert accepted_request.SOURCE in groups
        titles = _titles(s)
        assert titles["Klient zaakceptował prośbę: 176 h"] == "ok"
        assert titles[f"Akceptacja: 176 h za {mail_text.month_label(w.month)}"] == "ok"
    finally:
        await _cleanup(w.client_id)


async def test_odpowiedz_bez_akceptacji_nie_daje_md(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    w = await _world()
    try:
        s = await _store(
            w, _reply(w.person, w.month, "Prosimy o przesyłanie również faktury w PDF.")
        )
        assert s.md_regular is None
        assert accepted_request.SOURCE not in [
            g.get("title") for g in s.checks or [] if isinstance(g, dict)
        ]
        # Decyzja Artura 25.11.2026: bez MD, ale z uwagą i adresem odpowiadającego.
        (check,) = [
            c
            for g in s.checks or []
            if isinstance(g, dict)
            for c in g.get("checks") or []
            if c.get("rule") == service.REQUEST_REPLY
        ]
        assert check["acceptors"] == [f"kierownik@{DOMAIN}"]
    finally:
        await _cleanup(w.client_id)
