"""Informacja zwrotna o wadach rozliczenia na bazie: na sucho, bez powtórek dnia,
przypomnienie po N dniach roboczych, koniec po poprawce, rozliczenie bez wady
bez komunikatu, dzwonek opiekuna, mail do konsultanta i trasy. Dane fikcyjne.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.client import Client
from app.models.client_settlement import ClientSettlement, ClientSettlementRuleSet
from app.models.client_settlement_feedback import ClientSettlementFeedback
from app.models.contract import Contract
from app.models.notification import Notification, NotificationType
from app.models.user import UserRole
from app.services.care.announcement_mail import MailOutcome
from app.services.client_settlements import feedback
from app.services.client_settlements.feedback import Settings
from app.services.consultant_portal import portal_mail
from app.services.person_workdays import business_days
from tests.care_announcements_seed import (
    _get_setting,
    _set_setting,
    headers,
    make_client,
    make_consultant,
    make_user,
)

pytestmark = pytest.mark.asyncio

ADDRESS = "rozliczenia@example.com"
MONTH = "2026-10"
DRY = Settings(mode="dry_run", external="all")
SIGNED_PDF = [
    {
        "title": "RCP",
        "checks": [
            {
                "rule": "proof.signed_pdf",
                "state": "fail",
                "title": "PDF bez podpisu elektronicznego",
                "detail": None,
            }
        ],
    }
]
CLEAN = [{"title": "RCP", "checks": [{"state": "ok", "title": "Podpis ważny"}]}]


def _workday(after: date, count: int) -> date:
    """``count``-ty dzień roboczy po ``after``."""

    return business_days(after + timedelta(days=1), after + timedelta(days=30))[
        count - 1
    ]


@dataclass
class FakeMailer:
    sent: list[dict] = field(default_factory=list)

    async def send(
        self, *, to: str, subject: str, text: str, cc: Optional[str] = None
    ) -> MailOutcome:
        self.sent.append({"to": to, "subject": subject, "text": text, "cc": cc})
        return MailOutcome("accepted")


@pytest.fixture
def mailer(monkeypatch) -> FakeMailer:
    from app.core.config import settings

    fake = FakeMailer()
    monkeypatch.setattr(portal_mail, "default_mailer", lambda: fake)
    monkeypatch.setattr(settings, "CONSULTANT_PORTAL_SETTLEMENTS_ADDRESSES", ADDRESS)
    return fake


@pytest_asyncio.fixture
async def module_on():
    module = await _get_setting("client_settlements")
    switch = await _get_setting(feedback.SETTING_KEY)
    await _set_setting("client_settlements", {"enabled": True})
    yield
    await _set_setting("client_settlements", module)
    await _set_setting(feedback.SETTING_KEY, switch)


@dataclass
class World:
    client_id: int
    #: Rozliczenie z wadą (PDF bez podpisu).
    faulty: int
    faulty_email: str
    #: Rozliczenie bez uwag.
    clean: int
    owner_id: int
    owner_email: str


async def _world() -> World:
    owner = await make_user(UserRole.delivery_lead, name="Opiekun")
    client_id = await make_client()
    email = f"konsultant-wada-{client_id}@example.com"
    faulty, _ = await make_consultant(
        client_id, contract_email=email, owner_id=owner.id
    )
    clean, _ = await make_consultant(
        client_id,
        contract_email=f"konsultant-ok-{client_id}@example.com",
        owner_id=owner.id,
    )
    async with AsyncSessionLocal() as db:
        db.add(
            ClientSettlementRuleSet(
                client_id=client_id, effective_from="2020-01", rules={}
            )
        )
        for contract_id, status, checks in (
            (faulty, "warnings", SIGNED_PDF),
            (clean, "ok", CLEAN),
        ):
            db.add(
                ClientSettlement(
                    contract_id=contract_id,
                    client_id=client_id,
                    period_month=MONTH,
                    status=status,
                    checks=checks,
                )
            )
        await db.commit()
    return World(client_id, faulty, email, clean, owner.id, owner.email)


async def _cleanup(world: World) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(Notification).where(
                Notification.notification_type == NotificationType.settlement_feedback,
                Notification.user_id == world.owner_id,
            )
        )
        await db.execute(
            delete(ClientSettlementFeedback).where(
                ClientSettlementFeedback.client_id == world.client_id
            )
        )
        await db.execute(
            delete(ClientSettlement).where(
                ClientSettlement.client_id == world.client_id
            )
        )
        await db.execute(
            delete(ClientSettlementRuleSet).where(
                ClientSettlementRuleSet.client_id == world.client_id
            )
        )
        await db.execute(delete(Contract).where(Contract.client_id == world.client_id))
        await db.execute(delete(Client).where(Client.id == world.client_id))
        await db.commit()


async def _rows(contract_id: int) -> list[ClientSettlementFeedback]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(ClientSettlementFeedback)
                    .where(ClientSettlementFeedback.contract_id == contract_id)
                    .order_by(ClientSettlementFeedback.id)
                )
            ).all()
        )


async def _run(today: date, settings: Settings, world: World) -> dict:
    async with AsyncSessionLocal() as db:
        return await feedback.run(
            db, today, months=[MONTH], settings=settings, client_ids={world.client_id}
        )


async def _bells(world: World) -> list[Notification]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(Notification).where(
                        Notification.user_id == world.owner_id,
                        Notification.notification_type
                        == NotificationType.settlement_feedback,
                    )
                )
            ).all()
        )


async def test_na_sucho_zapis_komu_co_kiedy_i_nic_bez_wady(mailer, module_on) -> None:
    world = await _world()
    today = business_today()
    try:
        result = await _run(today, DRY, world)
        assert result["months"][MONTH]["new"] == 1
        assert result["months"][MONTH]["messages"] == 1
        (row,) = await _rows(world.faulty)
        assert (row.code, row.audience, row.send_count) == (
            "proof.signed_pdf",
            "consultant",
            1,
        )
        (entry,) = row.sends
        assert entry["outcome"] == "dry_run"
        assert (entry["to"], entry["address"], entry["cc"]) == (
            "consultant",
            world.faulty_email,
            world.owner_email,
        )
        assert entry["on"] == today.isoformat()
        assert "kwalifikowanym podpisem" in entry["text"]
        # Bez wady: ani wiersza, ani komunikatu. Na sucho: nic nie wychodzi.
        assert await _rows(world.clean) == []
        assert mailer.sent == [] and await _bells(world) == []
    finally:
        await _cleanup(world)


async def test_bez_powtorki_dnia_przypomnienie_po_n_dniach_i_koniec_po_poprawce(
    mailer, module_on
) -> None:
    world = await _world()
    start = business_today()
    try:
        await _run(start, DRY, world)
        await _run(start, DRY, world)
        assert (await _rows(world.faulty))[0].send_count == 1
        await _run(_workday(start, 2), DRY, world)
        assert (await _rows(world.faulty))[0].send_count == 1
        third = _workday(start, 3)
        await _run(third, DRY, world)
        (row,) = await _rows(world.faulty)
        assert row.send_count == 2 and row.last_sent_on == third

        # Konsultant przysłał podpisany PDF: rozliczenie bez uwag.
        async with AsyncSessionLocal() as db:
            s = await db.scalar(
                select(ClientSettlement).where(
                    ClientSettlement.contract_id == world.faulty
                )
            )
            s.status, s.checks = "ok", CLEAN
            await db.commit()
        fixed = _workday(third, 1)
        result = await _run(fixed, DRY, world)
        assert result["months"][MONTH]["resolved"] == 1
        later = _workday(fixed, 10)
        await _run(later, DRY, world)
        (row,) = await _rows(world.faulty)
        assert row.resolved_on == fixed and row.send_count == 2
    finally:
        await _cleanup(world)


async def test_wylaczone_nic_nie_robi(mailer, module_on) -> None:
    world = await _world()
    try:
        assert await _run(business_today(), Settings(), world) == {"status": "disabled"}
        assert await _rows(world.faulty) == []
    finally:
        await _cleanup(world)


async def test_bez_wysylki_poza_firme_dzwonek_opiekuna_zamiast_maila(
    mailer, module_on
) -> None:
    world = await _world()
    try:
        await _run(business_today(), Settings(mode="on", external="off"), world)
        assert mailer.sent == []
        (bell,) = await _bells(world)
        assert "Przekaż konsultantowi: PDF z RCP bez podpisu" in bell.message
        assert bell.link == f"/contracts/{world.faulty}"
        (row,) = await _rows(world.faulty)
        assert row.sends[-1]["to"] == "owner"
        assert row.sends[-1]["why"] == "external_off"
        assert row.sends[-1]["outcome"] == "sent"
    finally:
        await _cleanup(world)


async def test_wysylka_do_wszystkich_mail_do_konsultanta_z_opiekunem_w_kopii(
    mailer, module_on
) -> None:
    world = await _world()
    start = business_today()
    try:
        on = Settings(mode="on", external="all")
        await _run(start, on, world)
        (mail,) = mailer.sent
        assert (mail["to"], mail["cc"]) == (world.faulty_email, world.owner_email)
        assert mail["subject"].startswith("Rozliczenie za październik 2026")
        await _run(_workday(start, 3), on, world)
        assert mailer.sent[-1]["subject"].startswith("Przypomnienie: ")
        assert await _bells(world) == []
    finally:
        await _cleanup(world)


async def test_adres_z_kartoteki_gdy_kontrakt_bez_adresu(mailer, module_on) -> None:
    world = await _world()
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("UPDATE contracts SET candidate_email = NULL WHERE id = :id"),
            {"id": world.faulty},
        )
        card = await db.scalar(
            text(
                "SELECT c.email FROM candidates c JOIN contracts k "
                "ON k.candidate_id = c.id WHERE k.id = :id"
            ),
            {"id": world.faulty},
        )
        await db.commit()
    try:
        await _run(business_today(), Settings(mode="on", external="all"), world)
        (mail,) = mailer.sent
        assert mail["to"] == card
    finally:
        await _cleanup(world)


async def test_klient_z_raportem_t4t_bez_brakow_rcp_i_bez_wady_zdjecia(
    mailer, module_on
) -> None:
    from app.models.consultant_portal import CpDocument
    from app.services.client_settlements import reminders

    world = await _world()
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "UPDATE client_settlement_rule_sets SET rules = "
                '\'{"report.time_for_teams": {"level": "warn"}}\'::jsonb '
                "WHERE client_id = :id"
            ),
            {"id": world.client_id},
        )
        document = CpDocument(
            contract_id=world.faulty,
            kind="report",
            period_year=2026,
            period_month=10,
            channel="mailbox",
            file_path="feedback-test/zdjecie.jpg",
            mime="image/jpeg",
            size_bytes=10,
            sha256="0" * 64,
        )
        db.add(document)
        await db.flush()
        s = await db.scalar(
            select(ClientSettlement).where(ClientSettlement.contract_id == world.faulty)
        )
        s.status, s.checks, s.report_document_id = "checking", [], document.id
        await db.commit()
    try:
        await _run(business_today(), DRY, world)
        assert await _rows(world.faulty) == []
        async with AsyncSessionLocal() as db:
            missing = await reminders.missing_reports(
                db, MONTH, client_id=world.client_id
            )
        assert missing == []
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                text(
                    "UPDATE client_settlements SET report_document_id = NULL "
                    "WHERE client_id = :id"
                ),
                {"id": world.client_id},
            )
            await db.execute(
                delete(CpDocument).where(CpDocument.contract_id == world.faulty)
            )
            await db.commit()
        await _cleanup(world)


async def test_api_ustawienia_tylko_admin_i_podglad_finansow(
    app_client, mailer, module_on
) -> None:
    world = await _world()
    admin = await make_user(UserRole.admin, name="Admin")
    finance = await make_user(UserRole.finance, name="Finanse")
    base = "/api/finance/settlements/reminders"
    try:
        start = await app_client.get(f"{base}/settings", headers=headers(finance))
        assert start.status_code == 200, start.text
        refused = await app_client.put(
            f"{base}/settings",
            json={"feedback": {"mode": "dry_run"}},
            headers=headers(finance),
        )
        assert refused.status_code == 403
        saved = await app_client.put(
            f"{base}/settings",
            json={"feedback": {"mode": "dry_run", "every_days": 2}},
            headers=headers(admin),
        )
        assert saved.status_code == 200, saved.text
        assert saved.json() == {
            "feedback": {"mode": "dry_run", "external": "off", "every_days": 2}
        }
        bad = await app_client.put(
            f"{base}/settings",
            json={"feedback": {"external": "everyone"}},
            headers=headers(admin),
        )
        assert bad.status_code == 422
        empty = await app_client.put(
            f"{base}/settings", json={}, headers=headers(admin)
        )
        assert empty.status_code == 422

        await _run(business_today(), DRY, world)
        view = await app_client.get(
            f"{base}/feedback",
            params={"month": MONTH, "client_id": world.client_id},
            headers=headers(finance),
        )
        assert view.status_code == 200, view.text
        body = view.json()
        assert body["settings"]["mode"] == "dry_run"
        assert body["summary"]["defects"] == 1 and body["summary"]["messages"] == 1
        assert body["rows"][0]["code"] == "proof.signed_pdf"
    finally:
        await _cleanup(world)
        async with AsyncSessionLocal() as db:
            await db.execute(
                text("DELETE FROM users WHERE id IN (:a, :f)"),
                {"a": admin.id, "f": finance.id},
            )
            await db.commit()


# ── Kosmetyka przy dobrym MD: informacja raz, bez przypomnień (25.11.2026) ──

ROWS_NOTE = [
    {
        "title": "Pola i sumy",
        "checks": [
            {
                "state": "none",
                "title": "Wiersze opisu prac nie sumują się do SUMA",
                "detail": "Wiersze: 44 MD, SUMA: 22 MD. SUMA zgadza się z godzinami dni.",
                "notice": "note.rows_sum",
            }
        ],
    }
]


async def _set(world: World, status: str, checks: list) -> None:
    async with AsyncSessionLocal() as db:
        s = await db.scalar(
            select(ClientSettlement).where(ClientSettlement.contract_id == world.faulty)
        )
        s.status, s.checks = status, checks
        await db.commit()


@pytest.mark.parametrize("status", ["ok", "accepted"])
async def test_informacja_bez_poprawki_raz_przy_bez_uwag_bez_przypomnien(
    mailer, module_on, status
) -> None:
    world = await _world()
    await _set(world, status, ROWS_NOTE)
    start = business_today()
    try:
        first = await _run(start, DRY, world)
        assert (first["months"][MONTH]["new"], first["months"][MONTH]["messages"]) == (
            1,
            1,
        )
        (row,) = await _rows(world.faulty)
        assert (row.code, row.audience, row.send_count) == (
            "note.rows_sum",
            "consultant",
            1,
        )
        # Nic więcej nie czeka: wiersz zamknięty w dniu komunikatu.
        assert row.resolved_on == start
        (entry,) = row.sends
        assert entry["outcome"] == "dry_run" and entry["codes"] == ["note.rows_sum"]
        assert "Na przyszłość:" in entry["text"]
        assert "Tego raportu nie trzeba poprawiać" in entry["text"]

        await _run(start, DRY, world)
        later = await _run(_workday(start, 3), DRY, world)
        assert later["months"][MONTH]["messages"] == 0
        assert later["months"][MONTH]["reopened"] == 0
        (row,) = await _rows(world.faulty)
        assert row.send_count == 1 and row.resolved_on == start
        assert await _rows(world.clean) == []
        assert mailer.sent == [] and await _bells(world) == []
    finally:
        await _cleanup(world)


async def test_wada_i_informacja_w_jednym_mailu_przypomnienie_tylko_o_wadzie(
    mailer, module_on
) -> None:
    world = await _world()
    await _set(world, "warnings", [*SIGNED_PDF, *ROWS_NOTE])
    start = business_today()
    on = Settings(mode="on", external="all")
    try:
        await _run(start, on, world)
        (mail,) = mailer.sent
        assert "Co zrobić:" in mail["text"] and "Na przyszłość:" in mail["text"]
        third = _workday(start, 3)
        await _run(third, on, world)
        reminder = mailer.sent[-1]
        assert reminder["subject"].startswith("Przypomnienie: ")
        assert "Na przyszłość:" not in reminder["text"]
        rows = {row.code: row for row in await _rows(world.faulty)}
        assert rows["proof.signed_pdf"].send_count == 2
        assert rows["note.rows_sum"].send_count == 1
        assert rows["note.rows_sum"].resolved_on == start
    finally:
        await _cleanup(world)


async def test_brak_raportu_zostaje_przypomnieniom_a_wada_rozliczeniu(
    mailer, module_on
) -> None:
    """Przypomnienie „Brak RCP” dotyczy kontraktu bez rozliczenia, a informacja
    zwrotna tylko rozliczeń: o tym samym nie piszą obie."""

    from app.services.client_settlements import reminders

    world = await _world()
    await _set(world, "ok", ROWS_NOTE)
    since = (business_today() - date(2026, 10, 1)).days + 30
    missing_id, _ = await make_consultant(
        world.client_id,
        contract_email=f"konsultant-brak-{world.client_id}@example.com",
        owner_id=world.owner_id,
        started_days_ago=since,
    )
    try:
        await _run(business_today(), DRY, world)
        async with AsyncSessionLocal() as db:
            missing = await reminders.missing_reports(
                db, MONTH, client_id=world.client_id
            )
        assert [m.contract_id for m in missing] == [missing_id]
        assert await _rows(missing_id) == []
        assert [row.code for row in await _rows(world.faulty)] == ["note.rows_sum"]
    finally:
        await _cleanup(world)
