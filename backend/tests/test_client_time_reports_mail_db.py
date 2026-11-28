"""Raport T4T z maila (Nordea, 23.11.2026): arkusz wchodzi jako wersja raportu
miesiąca, ten sam plik drugi raz to duplikat, a bez jednego klienta z regułą T4T
plik zostaje zwykłym dokumentem. Na końcu cała droga przez oba czytniki wsparcie@
dla maila przekierowanego ze skrzynki koordynatorki (28.11.2026). Osoby, adresy
(poza adresem funkcyjnym Cost Control), numery i godziny fikcyjne."""

from __future__ import annotations

import base64
import io
from datetime import date, datetime

import openpyxl
import pytest
from sqlalchemy import func, select

from app.core.config import Settings, settings
from app.core.database import AsyncSessionLocal
from app.models.client_settlement import ClientSettlementRuleSet
from app.models.client_time_report import ClientTimeReport
from app.models.consultant_portal import CpDocument
from app.services import support_mail_route
from app.services.client_settlements import t4t_mail, time_reports
from app.services.consultant_portal import mailbox as settlements_mailbox
from tests.test_admin_cases_mail_ingest import (  # noqa: F401  (fixture'y)
    FakeMailbox as CasesMailbox,
    _cases_for,
    _run,
    cases_on,
    mailbox_on,
    shared_support_mailbox,
)
from tests.test_client_audit_2026_09_24 import _client
from tests.test_client_time_reports_db import (
    HEADER,
    MONTH,
    NIDS,
    _drop,
    _person,
    _rows,
    _view,
    _xlsx,
)

pytestmark = pytest.mark.asyncio

FILE = "#microsoft.graph.fileAttachment"


def _files(content: bytes) -> list[dict]:
    return [
        {
            "@odata.type": FILE,
            "name": "B2B_net_SA_T4T_September_01.10.2026.xlsx",
            "isInline": False,
            "contentBytes": base64.b64encode(content).decode("ascii"),
        },
        {
            "@odata.type": FILE,
            "name": "image001.png",
            "isInline": True,
            "contentBytes": "",
        },
    ]


async def _ingest(files: list[dict]) -> t4t_mail.T4tMailResult:
    async with AsyncSessionLocal() as db:
        result = await t4t_mail.ingest(db, files, received_on=date(2026, 10, 1))
        await db.commit()
    return result


async def test_raport_z_maila_to_wersja_raportu_a_powtorka_to_duplikat(monkeypatch):
    client_id = await _client()
    jan = await _person(client_id, "Jan", "Mailowy")
    try:

        async def only_this(db, month):
            assert month == MONTH
            return [client_id]

        monkeypatch.setattr(time_reports, "enabled_clients", only_this)
        content = _xlsx(_rows("M000101", "Jan Mailowy"))
        first = await _ingest(_files(content))
        assert first.consumed == {0} and first.versions == 1 and first.duplicates == 0
        again = await _ingest(_files(content))
        assert again.consumed == {0} and again.versions == 0 and again.duplicates == 1
        view = await _view(client_id)
        assert [v["version_no"] for v in view["versions"]] == [1]
        assert view["versions"][0]["hours_approved"] == "176.00"
    finally:
        await _drop(client_id, [jan])


async def test_bez_jednego_klienta_z_regula_plik_zostaje_dokumentem(monkeypatch):
    async def nobody(db, month):
        return []

    monkeypatch.setattr(time_reports, "enabled_clients", nobody)
    content = _xlsx(_rows("M000102", "Ewa Mailowa"))
    result = await _ingest(_files(content))
    assert result.consumed == set() and result.versions == 0


async def test_arkusz_spoza_t4t_nie_jest_raportem(monkeypatch):
    async def boom(db, month):
        raise AssertionError("zwykły arkusz nie pyta o klienta")

    monkeypatch.setattr(time_reports, "enabled_clients", boom)
    workbook = openpyxl.Workbook()
    workbook.active.append(["Data", "Godziny", "Opis"])
    workbook.active.append(["2026-09-01", 8, "praca"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    result = await _ingest(_files(buffer.getvalue()))
    assert result.consumed == set()


# ── Redirect ze skrzynki koordynatorki na wsparcie@ (28.11.2026) ─────────────
#
# Cost Control odpowiada na mail koordynatorki „Lista kontraktorów - <miesiąc>”, a reguła
# Exchange w jej skrzynce robi Redirect na wsparcie@. Redirect zostawia oryginalne
# nagłówki: From = Cost Control, To = koordynatorka, DW = ludzie z Nordei. W To/DW nie
# ma adresu rozliczeń, w temacie nie ma „T4T”, więc mail rozpoznaje tylko nadawca
# (``CONSULTANT_PORTAL_TIME_REPORT_SENDERS``). Do 28.11 nie przyszedł żaden żywy mail.

COST_CONTROL = "costcontrol.psnoc@nordea.com"
COORDINATOR = "koordynatorka.rozliczen@firma.example"
NOVEMBER = "2026-11"
REDIRECT_SUBJECT = "RE: Lista kontraktorów - listopad 2026"
REDIRECT_FILE = "B2B_net_SA_T4T_November_30.11.2026.xlsx"
# Tygodnie T4T w listopadzie 2026: 11.11 święto, ostatni tydzień jeszcze bez akceptacji.
NOVEMBER_WEEKS = [(2, 8, 40, 2), (9, 15, 32, 2), (16, 22, 40, 2), (23, 29, 40, 1)]


def _november_xlsx(number: str, name: str) -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"
    sheet.append(HEADER)
    for start, end, hours, status in NOVEMBER_WEEKS:
        day = datetime(2026, 11, start)
        sheet.append(
            [NIDS, name, number, day, datetime(2026, 11, end), day, hours, status]
        )
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _redirect_files(content: bytes) -> list[dict]:
    return [
        {
            "@odata.type": FILE,
            "name": REDIRECT_FILE,
            "contentType": (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
            "size": len(content),
            "isInline": False,
            "contentBytes": base64.b64encode(content).decode("ascii"),
        },
        # Logo ze stopki Cost Control.
        {
            "@odata.type": FILE,
            "name": "image001.png",
            "contentType": "image/png",
            "size": 0,
            "isInline": True,
            "contentBytes": "",
        },
    ]


class _SettlementsFake:
    """wsparcie@ widziana przez czytnik rozliczeń, w kształcie odpowiedzi Graph."""

    def __init__(self, messages: list[dict], files: dict[str, list[dict]]) -> None:
        self.messages = messages
        self.files = files

    async def list_messages(self, since):
        return self.messages

    async def attachments(self, message_id):
        return self.files.get(message_id, [])

    async def mime(self, message_id):
        return None


@pytest.fixture
def redirect_mailbox(shared_support_mailbox, monkeypatch):  # noqa: F811
    """Oba czytniki na jednej wsparcie@, nadawcy raportów godzin jak w ``config.py``."""

    monkeypatch.setattr(settings, "ADMIN_CASES_M365_MAILBOX", shared_support_mailbox)
    monkeypatch.setattr(
        settings,
        "CONSULTANT_PORTAL_TIME_REPORT_SENDERS",
        Settings.model_fields["CONSULTANT_PORTAL_TIME_REPORT_SENDERS"].default,
    )
    return shared_support_mailbox


def _redirected(cases: CasesMailbox, content: bytes) -> dict:
    """Mail po Redirect, z polami z ``$select`` czytnika rozliczeń."""

    message = cases.add(
        subject=REDIRECT_SUBJECT,
        hours_ago=1,
        sender=COST_CONTROL,
        to=[COORDINATOR],
        cc=["kierownik.zespolu@nordea.com"],
        attachments=_redirect_files(content),
    )
    fields = settlements_mailbox._MESSAGE_SELECT.split(",")
    return {key: message[key] for key in fields}


async def _reports(client_id: int) -> list[tuple]:
    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(ClientTimeReport)
            .where(ClientTimeReport.client_id == client_id)
            .order_by(ClientTimeReport.version_no)
        )
        return [
            (
                r.period_month,
                r.version_no,
                r.file_name,
                r.rows_count,
                r.people_count,
                str(r.hours_approved),
            )
            for r in rows
        ]


async def _documents_of(message_ids: list[str]) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(func.count())
            .select_from(CpDocument)
            .where(CpDocument.graph_message_id.in_(message_ids))
        )


async def _read_settlements(messages: list[dict], files: dict) -> dict:
    async with AsyncSessionLocal() as db:
        result = await settlements_mailbox.run_once(
            db, mailbox=_SettlementsFake(messages, files)
        )
        await db.commit()
    return result


async def test_redirect_od_koordynatorki_to_wersja_raportu_a_nie_sprawa(
    redirect_mailbox, monkeypatch
):
    client_id = await _client()
    async with AsyncSessionLocal() as db:
        db.add(
            ClientSettlementRuleSet(
                client_id=client_id,
                effective_from=NOVEMBER,
                rules={"report.time_for_teams": {"level": "warn", "params": {}}},
            )
        )
        await db.commit()
    real_enabled = time_reports.enabled_clients

    async def ours_by_rule(db, month):
        # Klient znaleziony po regule; inni klienci z regułą w bazie testów się nie liczą.
        assert month == NOVEMBER
        assert client_id in await real_enabled(db, month)
        return [client_id]

    monkeypatch.setattr(time_reports, "enabled_clients", ours_by_rule)
    content = _november_xlsx("M000301", "Jan Przekierowany")
    cases = CasesMailbox()
    first = _redirected(cases, content)
    # Cost Control wysyła ten sam plik jeszcze raz (nowa wiadomość, ten sam arkusz).
    again = _redirected(cases, content)
    try:
        route = support_mail_route.settlements_addresses()
        assert not support_mail_route.recipients(first) & route
        assert support_mail_route.is_settlements_mail(first, route)

        # Czytnik spraw oddaje oba maile rozliczeniom: żadnej sprawy.
        outcome = await _run(cases)
        assert outcome["status"] == "ok"
        assert outcome.get("routed_settlements") == 2
        assert await _cases_for(cases) == {}

        # Czytnik rozliczeń: pierwszy mail = wersja 1 raportu za listopad.
        result = await _read_settlements([first], cases.attachments)
        assert result["status"] == "ok"
        assert (result["created"], result["skipped"]) == (1, 0)
        assert await _reports(client_id) == [
            (NOVEMBER, 1, REDIRECT_FILE, 4, 1, "112.00")
        ]

        # Drugi taki sam mail: duplikat bez nowej wersji.
        result = await _read_settlements([again], cases.attachments)
        assert result["status"] == "ok"
        assert (result["created"], result["skipped"]) == (0, 1)
        assert [r[1] for r in await _reports(client_id)] == [1]
        # Arkusz wczytany jako raport nie jest dokumentem konsultanta.
        assert await _documents_of([first["id"], again["id"]]) == 0
    finally:
        await _drop(client_id, [])
