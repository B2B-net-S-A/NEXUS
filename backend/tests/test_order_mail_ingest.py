"""Pobieranie zamówień z maila: sloty, watermark, rozpoznanie, dedup, dziennik.

Graph jest podstawiony — żadnej sieci. PDF-y nie są prawdziwe: tekst dokumentu
podstawiamy w ``extract_order_text``, bo interesuje nas przepływ (dedup po SHA,
drabina wyników, idempotencja), a nie ekstrakcja (ta ma własne testy).
Lata w danych: 2031+ (wolny zakres bazy testowej).
"""

import random
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.m365 import M365Connection
from app.models.order_mail import (
    OUTCOME_DUPLICATE,
    OUTCOME_IGNORED_NO_PDF,
    OUTCOME_IGNORED_SENDER,
    OUTCOME_NEEDS_REVIEW,
    OUTCOME_UNRECOGNIZED,
    OrderMailDocument,
)
from app.services import order_mail_ingest as svc
from app.services.order_client_identity import ClientIdentification, ClientRegistry
from app.services.order_document_text import OrderDocumentText
from app.services.order_pdf_parser import ConsultantOrderRow, OrderExtraction
from app.tasks.order_mail_ingest import due_interval

WAW = ZoneInfo("Europe/Warsaw")
RUN = uuid.uuid4().hex[:8]  # baza testowa jest współdzielona i nie jest czyszczona


def _synthetic_nip() -> str:
    """Losowy NIP z poprawną sumą kontrolną — unikalny per przebieg."""
    weights = (6, 5, 7, 2, 3, 4, 5, 6, 7)
    while True:
        body = [random.randint(0, 9) for _ in range(9)]
        control = sum(d * w for d, w in zip(body, weights)) % 11
        if control != 10:
            return "".join(map(str, body)) + str(control)


@pytest_asyncio.fixture
async def db_session():
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        yield session


# ── Odstęp między biegami ───────────────────────────────────────────────────


class TestDueInterval:
    hour = timedelta(minutes=60)

    def test_first_run_is_immediate(self):
        assert due_interval(datetime(2031, 3, 3, 10, 0, tzinfo=WAW), None, self.hour)

    def test_waits_a_full_interval_after_the_last_finish(self):
        last = datetime(2031, 3, 3, 8, 4, tzinfo=WAW)
        assert not due_interval(
            datetime(2031, 3, 3, 8, 30, tzinfo=WAW), last, self.hour
        )
        assert not due_interval(datetime(2031, 3, 3, 9, 3, tzinfo=WAW), last, self.hour)
        assert due_interval(datetime(2031, 3, 3, 9, 4, tzinfo=WAW), last, self.hour)

    def test_manual_run_pushes_the_clock(self):
        """Bieg ręczny o 08:50 znaczy, że planowy nie odpala o 09:04, tylko o 09:50."""
        manual_finished = datetime(2031, 3, 3, 8, 50, tzinfo=WAW)
        assert not due_interval(
            datetime(2031, 3, 3, 9, 4, tzinfo=WAW), manual_finished, self.hour
        )
        assert due_interval(
            datetime(2031, 3, 3, 9, 50, tzinfo=WAW), manual_finished, self.hour
        )

    def test_interrupted_run_leaves_no_finish_and_is_due_at_once(self):
        """Restart w trakcie biegu: koniec niezapisany → po starcie od razu."""
        assert due_interval(datetime(2031, 3, 3, 9, 0, tzinfo=WAW), None, self.hour)

    def test_long_outage_is_due_once_not_many_times(self):
        last = datetime(2031, 3, 1, 15, 3, tzinfo=WAW)
        assert due_interval(datetime(2031, 3, 3, 7, 0, tzinfo=WAW), last, self.hour)

    def test_interval_floor_and_default(self, monkeypatch):
        monkeypatch.setattr(svc.settings, "ORDER_MAIL_POLL_INTERVAL_MINUTES", 0)
        assert svc.poll_interval_minutes() == 5
        monkeypatch.setattr(svc.settings, "ORDER_MAIL_POLL_INTERVAL_MINUTES", 60)
        assert svc.poll_interval_minutes() == 60


# ── Projekcja stanu (kolejka + admin) ────────────────────────────────────────


class TestSyncSnapshot:
    def test_no_state_yet(self):
        snap = svc.sync_snapshot(None, running=False)
        assert snap["last_completed"] is None
        assert snap["interrupted"] is False
        assert snap["interval_minutes"] == svc.poll_interval_minutes()

    def test_running_without_lock_is_interrupted_and_keeps_previous_result(self):
        """Wiersz „running" po restarcie: poprzedni wynik zostaje, bieg = przerwany."""
        state = {
            "last_run_started_at": datetime(2031, 3, 3, 9, 6, tzinfo=timezone.utc),
            "last_run_finished_at": datetime(2031, 3, 3, 6, 2, tzinfo=timezone.utc),
            "last_status": "running",
            "last_error": None,
            "last_seen_received_at": None,
            "stats": {
                "reason": "scheduled",
                "started_at": "2031-03-03T06:02:00+00:00",
                "finished_at": "2031-03-03T06:02:41+00:00",
                "status": "ok",
                "error": None,
                "messages": 1,
                "new_messages": 0,
                "needs_review": 0,
                "errors": [],
            },
        }
        snap = svc.sync_snapshot(state, running=False)
        assert snap["interrupted"] is True
        assert snap["started_at"] == "2031-03-03T09:06:00+00:00"
        assert snap["last_completed"]["finished_at"] == "2031-03-03T06:02:41+00:00"
        assert snap["last_completed"]["status"] == "ok"
        assert snap["last_completed"]["reason"] == "scheduled"
        live = svc.sync_snapshot(state, running=True)
        assert live["interrupted"] is False and live["running"] is True

    def test_legacy_stats_without_record_are_attributed_only_when_finished(self):
        legacy = {"messages": 3, "needs_review": 1, "errors": []}
        base = {
            "last_run_started_at": datetime(2031, 3, 3, 8, 0, tzinfo=timezone.utc),
            "last_run_finished_at": datetime(2031, 3, 3, 8, 1, tzinfo=timezone.utc),
            "last_error": "x",
            "stats": legacy,
        }
        done = svc.sync_snapshot({**base, "last_status": "partial"}, running=False)
        assert done["last_completed"]["status"] == "partial"
        assert done["last_completed"]["error"] == "x"
        assert done["last_completed"]["needs_review"] == 1
        assert done["last_completed"]["finished_at"] == "2031-03-03T08:01:00+00:00"
        # Start nadpisany przez nowy bieg — liczników nie da się przypisać.
        mid = svc.sync_snapshot({**base, "last_status": "running"}, running=True)
        assert mid["last_completed"] is None


def test_watermark_never_moves_backwards():
    older = datetime(2031, 3, 1, tzinfo=timezone.utc)
    newer = datetime(2031, 3, 2, tzinfo=timezone.utc)
    assert svc._latest(older, newer) == newer
    assert svc._latest(newer, older) == newer
    assert svc._latest(None, older) == older
    assert svc._latest(None, None) is None
    naive = datetime(2031, 3, 3)
    assert svc._latest(naive, older) == naive.replace(tzinfo=timezone.utc)


# ── Watermark ────────────────────────────────────────────────────────────────


def test_compute_since_uses_lookback_then_overlap(monkeypatch):
    monkeypatch.setattr(svc.settings, "ORDER_MAIL_INITIAL_LOOKBACK_DAYS", 7)
    monkeypatch.setattr(svc.settings, "ORDER_MAIL_OVERLAP_HOURS", 2)
    now = datetime(2031, 3, 3, 12, 0, tzinfo=timezone.utc)
    assert svc.compute_since(None, now) == now - timedelta(days=7)
    seen = datetime(2031, 3, 2, 9, 0, tzinfo=timezone.utc)
    assert svc.compute_since({"last_seen_received_at": seen}, now) == seen - timedelta(
        hours=2
    )


# ── Rozpoznanie → client_id ─────────────────────────────────────────────────


def test_resolve_client_id_from_registry_hit_and_from_policy_env(monkeypatch):
    by_nip = ClientIdentification(client_key="4242", method="registry_id")
    assert svc.resolve_client_id(by_nip) == (4242, None)
    monkeypatch.setenv("CARDIF_ORDER_EXTRACTION_CLIENT_IDS", "77")
    by_marker = ClientIdentification(client_key="cardif", method="marker")
    assert svc.resolve_client_id(by_marker) == (77, "cardif")
    monkeypatch.setenv("CARDIF_ORDER_EXTRACTION_CLIENT_IDS", "77,78")
    assert svc.resolve_client_id(by_marker) == (None, "cardif")
    assert svc.resolve_client_id(
        ClientIdentification(client_key=None, method=None)
    ) == (None, None)


def test_sender_allowlist(monkeypatch):
    monkeypatch.setattr(svc.settings, "ORDER_MAIL_SENDER_ALLOWLIST", "")
    assert svc.sender_allowed("anything.example") is True
    monkeypatch.setattr(
        svc.settings, "ORDER_MAIL_SENDER_ALLOWLIST", "bik.pl, nordea.com"
    )
    assert svc.sender_allowed("BIK.pl") is True
    assert svc.sender_allowed("spam.example") is False
    assert svc.sender_allowed(None) is False


def test_extraction_to_json_serializes_decimals_and_rows():
    ex = OrderExtraction(
        title="1",
        rate_client=Decimal("900.50"),
        consultant_rows=[
            ConsultantOrderRow(consultant_name="A B", rate_client=Decimal("1"))
        ],
    )
    out = svc.extraction_to_json(ex)
    assert out["rate_client"] == "900.50"
    assert out["consultant_rows"][0]["rate_client"] == "1"


# ── Przebieg z podstawionym Graphem (baza) ───────────────────────────────────


class _FakeGraph:
    def __init__(self, messages, attachments):
        self.messages = messages
        self.attachments = attachments

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def paginate(self, url, params=None):
        yield {"value": self.messages}

    async def get(self, url, params=None):
        msg_id = url.split("/messages/")[1].split("/")[0]
        return {"value": self.attachments.get(msg_id, [])}


def _msg(
    mid,
    *,
    sender="orders@bank-a.example",
    subject="Zamówienie",
    received="2031-03-03T08:00:00Z",
):
    return {
        "id": f"graph-{mid}",
        "internetMessageId": f"<{mid}-{RUN}@example>",
        "subject": subject,
        "from": {"emailAddress": {"address": sender}},
        "receivedDateTime": received,
        "hasAttachments": True,
    }


def _pdf(name, payload: bytes):
    import base64

    return {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": name,
        "contentType": "application/pdf",
        "contentBytes": base64.b64encode(payload).decode(),
    }


@pytest_asyncio.fixture
async def orders_connection(db_session):
    from app.models.user import User, UserRole

    u = User(
        email=f"order-mail-bot-{RUN}@example.test",
        name="Bot",
        role=UserRole.admin,
        password_hash="x",
    )
    db_session.add(u)
    await db_session.flush()
    conn = M365Connection(
        user_id=u.id,
        tenant_id="t",
        mailbox_upn=f"zamowienia-{RUN}@example.test",
        access_token_ct="x",
        refresh_token_ct="y",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        scopes_granted=[],
        is_active=True,
        purpose="personal",
    )
    db_session.add(conn)
    await db_session.commit()
    return conn


@pytest.mark.asyncio
async def test_ingest_end_to_end_with_fake_graph(
    db_session, orders_connection, monkeypatch, tmp_path
):
    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(storage_service, "ORDER_MAIL_DIR", tmp_path / "order_mail")
    monkeypatch.setattr(svc.settings, "ORDER_MAIL_UPN", orders_connection.mailbox_upn)
    monkeypatch.setattr(svc.settings, "ORDER_MAIL_SENDER_ALLOWLIST", "")
    monkeypatch.setattr(svc.settings, "ORDER_MAIL_INGEST_ENABLED", True)

    # Klient rozpoznawany po NIP (syntetyczny, poprawna suma kontrolna) — z bazy.
    from app.models.client import Client

    nip = _synthetic_nip()
    client = Client(name=f"Bank A Testowy {RUN} S.A.", nip=nip)
    db_session.add(client)
    await db_session.commit()

    pdf_a = f"%PDF-1.4 order A {RUN}".encode()
    pdf_b = f"%PDF-1.4 order B unknown {RUN}".encode()
    messages = [
        _msg("m1"),
        _msg("m2", sender="x@spam.example", received="2031-03-03T09:00:00Z"),
        _msg("m3", received="2031-03-03T10:00:00Z"),  # bez PDF-a
        _msg("m4", received="2031-03-03T11:00:00Z"),  # ten sam PDF co m1 → duplikat
        _msg("m5", received="2031-03-03T12:00:00Z"),  # nieznany klient
    ]
    attachments = {
        "graph-m1": [_pdf("zam_a.pdf", pdf_a)],
        "graph-m2": [_pdf("zam_spam.pdf", f"%PDF spam {RUN}".encode())],
        "graph-m3": [
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": "x.docx",
                "contentType": "application/octet-stream",
                "contentBytes": "AA==",
            }
        ],
        "graph-m4": [_pdf("zam_a_again.pdf", pdf_a)],
        "graph-m5": [_pdf("zam_b.pdf", pdf_b)],
    }
    fake = _FakeGraph(messages, attachments)
    monkeypatch.setattr(svc, "GraphClient", lambda conn, db: fake)

    texts = {
        pdf_a: f"Zamówienie nr 7/2031\nBank A Testowy S.A. NIP {nip}\nJan Testowy 2031-04-01 2031-06-30",
        pdf_b: "Zamówienie nr 9/2031\nNieznany Podmiot NIP 5260001246",
        f"%PDF spam {RUN}".encode(): "spam",
    }
    monkeypatch.setattr(
        svc,
        "extract_order_text",
        lambda path, filename: OrderDocumentText(
            text=texts[open(path, "rb").read()],
            page_count=1,
            ocr_used=False,
            ocr_capped=False,
            reextracted_with=None,
            letter_spacing_ratio=0.05,
        ),
    )

    async def fake_parse(text, *, all_rows=False, **kw):
        return OrderExtraction(
            title="7/2031",
            start_date="2031-04-01",
            end_date="2031-06-30",
            consultant_rows=[
                ConsultantOrderRow(consultant_name="Jan Testowy", uncertain=False)
            ],
            uncertain=False,
            source="claude",
        )

    monkeypatch.setattr(svc, "parse_order_document", fake_parse)

    # allowlist ON dla drugiego przebiegu (m2 ma być ignorowany po nadawcy)
    monkeypatch.setattr(svc.settings, "ORDER_MAIL_SENDER_ALLOWLIST", "bank-a.example")

    stats = await svc.run_order_mail_ingest(reason="test")
    assert stats.errors == []
    assert (stats.messages, stats.attachments) == (5, 3)
    assert (stats.needs_review, stats.unrecognized, stats.duplicates) == (1, 1, 1)
    assert (stats.ignored_no_pdf, stats.ignored_sender) == (1, 1)
    # Każda z pięciu wiadomości zostawiła wpis w dzienniku → pięć NOWYCH.
    assert stats.new_messages == 5 and stats.auto_applied == 0
    assert stats.reason == "test"

    rows = (
        (
            await db_session.execute(
                select(OrderMailDocument)
                .where(OrderMailDocument.internet_message_id.like(f"%-{RUN}@example>"))
                .order_by(OrderMailDocument.id)
            )
        )
        .scalars()
        .all()
    )
    by_msg = {r.internet_message_id: r for r in rows}
    a = by_msg[f"<m1-{RUN}@example>"]
    assert a.outcome == OUTCOME_NEEDS_REVIEW and a.client_id == client.id
    assert a.identification_method == "registry_id"
    assert (
        a.extraction["title"] == "7/2031"
        and a.extraction["consultant_rows"][0]["consultant_name"] == "Jan Testowy"
    )
    assert a.storage_path and (tmp_path / a.storage_path).exists()
    assert by_msg[f"<m2-{RUN}@example>"].outcome == OUTCOME_IGNORED_SENDER
    assert by_msg[f"<m3-{RUN}@example>"].outcome == OUTCOME_IGNORED_NO_PDF
    dup = by_msg[f"<m4-{RUN}@example>"]
    assert (
        dup.outcome == OUTCOME_DUPLICATE
        and dup.duplicate_of_id == a.id
        and dup.client_id == client.id
    )
    assert by_msg[f"<m5-{RUN}@example>"].outcome == OUTCOME_UNRECOGNIZED

    # Połączenie dostało purpose=orders (self-healing po UPN).
    await db_session.refresh(orders_connection)
    assert orders_connection.purpose == "orders"

    # Idempotencja: drugi bieg nad tymi samymi wiadomościami nic nie dokłada.
    again = await svc.run_order_mail_ingest(reason="test-again")
    assert again.skipped_existing == 3 or again.skipped_existing >= 1
    assert again.messages == 5 and again.new_messages == 0
    total = len(
        (
            await db_session.execute(
                select(OrderMailDocument).where(
                    OrderMailDocument.internet_message_id.like(f"%-{RUN}@example>")
                )
            )
        )
        .scalars()
        .all()
    )
    assert total == len(rows)

    state = await svc.read_state(db_session)
    assert state["last_status"] == "ok"
    assert state["last_seen_received_at"] is not None
    assert state["stats"]["messages"] == 5
    # Rekord ostatniego ZAKOŃCZONEGO biegu — to z niego czyta przycisk
    # „Pobierz zamówienia z maila" i pasek „ostatnie sprawdzenie".
    record = state["stats"]
    assert record["reason"] == "test-again" and record["status"] == "ok"
    assert record["finished_at"] >= record["started_at"]
    snap = svc.sync_snapshot(state, running=False)
    assert snap["interrupted"] is False
    assert snap["last_completed"]["new_messages"] == 0
    assert snap["last_completed"]["messages"] == 5
    assert snap["last_completed"]["reason"] == "test-again"


@pytest.mark.asyncio
async def test_document_marked_gross_rate_is_converted_and_consultant_matched(
    db_session, monkeypatch, tmp_path
):
    """Zgłoszenie Erste: klient rozpoznany po NIP, ale bez env polityki brutto.

    Rodzaj stawki czytamy z DOKUMENTU: „PLN BRUTTO" → ÷ 1,23, mimo braku
    polityki klientowej. Konsultant z dokumentu jest dopasowany do rostera
    klienta (nazwisko z diakrytykami).
    """
    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(storage_service, "ORDER_MAIL_DIR", tmp_path / "order_mail")
    # Erste NIE jest w env polityki — mirror zgłoszenia (polityka nieaktywna).
    monkeypatch.delenv("ERSTE_GROSS_RATE_CLIENT_IDS", raising=False)

    nip = _synthetic_nip()
    client = Client(name=f"Erste Testowy {RUN} S.A.", nip=nip)
    db_session.add(client)
    await db_session.flush()
    cand = Candidate(
        name="Marcin", lastname="Żółtaniecki", email=f"mz-{RUN}@example.test"
    )
    db_session.add(cand)
    await db_session.flush()
    db_session.add(
        Contract(
            candidate_id=cand.id,
            client_id=client.id,
            status=ContractStatus.active,
            start_date=date(2031, 1, 1),
            end_date=date(2031, 12, 31),
            rate_candidate=Decimal("900"),
            rate_client=Decimal("1160"),
            rate_unit=RateUnit.daily,
        )
    )
    await db_session.commit()

    doc_text = (
        f"Zlecenie K/2031/194208/JP/828/31ERSTE8\n"
        f"Erste Bank Polska S.A. NIP {nip}\n"
        "Dane kontraktora Marcin Żółtaniecki Zlecenie od 2031-04-01 "
        "Zlecenie do 2031-06-30\n"
        "Wartość zlecenia 23,00 dni roboczych x 1 426,80 PLN BRUTTO = "
        "32 816,40 PLN BRUTTO"
    )
    monkeypatch.setattr(
        svc,
        "extract_order_text",
        lambda path, filename: OrderDocumentText(
            text=doc_text,
            page_count=1,
            ocr_used=False,
            ocr_capped=False,
            reextracted_with=None,
            letter_spacing_ratio=0.05,
        ),
    )

    async def fake_parse(text, *, all_rows=False, **kw):
        # Model czyta kwotę BRUTTO z dokumentu, tak jak w PDF-ie.
        return OrderExtraction(
            title="K/2031/194208/JP/828/31ERSTE8",
            start_date="2031-04-01",
            end_date="2031-06-30",
            rate_client=Decimal("1426.80"),
            rate_unit="day",
            consultant_rows=[
                ConsultantOrderRow(
                    consultant_name="Marcin Żółtaniecki",
                    rate_client=Decimal("1426.80"),
                    rate_unit="day",
                    uncertain=False,
                )
            ],
            uncertain=False,
            source="claude",
        )

    monkeypatch.setattr(svc, "parse_order_document", fake_parse)

    registry = await svc.build_registry_from_db(db_session)
    row = OrderMailDocument(
        internet_message_id=f"<erste-gross-{RUN}@example>",
        received_at=datetime.now(timezone.utc),
        sender_email="orders@erste.example",
        attachment_name="zam.pdf",
    )
    await svc.process_pdf_bytes(db_session, row, b"%PDF-1.4 erste", registry=registry)

    assert row.client_id == client.id
    assert row.identification_method == "registry_id"
    # Bug 1: stawka brutto z dokumentu przeliczona na netto (÷ 1,23).
    assert row.extraction["rate_client"] == "1160.00"
    assert row.extraction["rate_client_gross"] == "1426.80"
    assert row.extraction["consultant_rows"][0]["rate_client"] == "1160.00"
    assert row.extraction["consultant_rows"][0]["rate_client_gross"] == "1426.80"
    # Bug 2: konsultant z dokumentu dopasowany do rostera klienta.
    resolved = row.proposal["resolved"][0]
    assert resolved["candidate_id"] == cand.id
    assert resolved["match_kind"] in ("exact", "rescued")


@pytest.mark.asyncio
async def test_notify_failure_rolls_back_session_and_is_recorded(
    db_session, monkeypatch, tmp_path
):
    """Padnięte powiadomienie DL (błąd SQL w trakcie) nie może zatruć sesji.

    Bez rollbacku każde kolejne zapytanie — także zapis końca biegu — kończy
    się PendingRollbackError i stan zostaje na „running" bez końca (tak
    wyglądał bieg 2026-09-03 09:06 na prodzie: dokument w kolejce, stan
    nigdy niezamknięty).
    """
    from sqlalchemy import text as sql_text

    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(storage_service, "ORDER_MAIL_DIR", tmp_path / "order_mail")
    monkeypatch.setattr(svc.settings, "ORDER_MAIL_SENDER_ALLOWLIST", "")

    async def fake_process(db, row, payload, *, registry):
        row.outcome = OUTCOME_NEEDS_REVIEW
        row.client_id = 1
        row.extraction = {"title": "7/2031", "consultant_rows": []}
        return row

    async def failing_notify(db, row):
        await db.execute(sql_text("SELECT * FROM order_mail_table_that_does_not_exist"))

    monkeypatch.setattr(svc, "process_pdf_bytes", fake_process)
    monkeypatch.setattr(svc, "notify_review", failing_notify)

    tag = uuid.uuid4().hex[:8]
    fake = _FakeGraph([], {"graph-nf": [_pdf("nf.pdf", f"%PDF nf {tag}".encode())]})
    stats = svc.IngestStats()
    added = await svc._process_message(
        db_session,
        fake,
        None,
        _msg("nf"),
        stats,
        registry=ClientRegistry(by_registry_id={}),
    )
    assert added is True and stats.needs_review == 1
    assert stats.errors and stats.errors[0].startswith("notify doc ")
    # Sesja nadaje się do dalszej pracy — bez rollbacku ten SELECT rzuca.
    assert (await db_session.execute(sql_text("SELECT 1"))).scalar() == 1


@pytest.mark.asyncio
async def test_ingest_without_connection_records_error(db_session, monkeypatch):
    monkeypatch.setattr(svc.settings, "ORDER_MAIL_UPN", "nobody@example.test")
    stats = await svc.run_order_mail_ingest(reason="test")
    assert "no_connection" in stats.errors
    state = await svc.read_state(db_session)
    assert state["last_status"] == "error"


# ── Tryb app-only (client_credentials, skrzynka współdzielona) ──────────────


def test_mailbox_prefix_follows_auth_mode(monkeypatch):
    """`/me` tylko dla tokenu użytkownika; app-only adresuje skrzynkę po UPN."""
    monkeypatch.setattr(svc.settings, "ORDER_MAIL_UPN", "nexus-zamowienia@example.test")
    monkeypatch.setattr(svc.settings, "ORDER_MAIL_AUTH_MODE", "delegated")
    assert svc.mailbox_prefix() == "/me"
    monkeypatch.setattr(svc.settings, "ORDER_MAIL_AUTH_MODE", "APP")
    assert svc.auth_mode() == "app"
    assert svc.mailbox_prefix() == "/users/nexus-zamowienia@example.test"
    monkeypatch.setattr(svc.settings, "ORDER_MAIL_AUTH_MODE", "garbage")
    assert svc.auth_mode() == "delegated"


class _RecordingGraph(_FakeGraph):
    def __init__(self, messages, attachments):
        super().__init__(messages, attachments)
        self.urls: list[str] = []

    async def paginate(self, url, params=None):
        self.urls.append(url)
        async for page in super().paginate(url, params=params):
            yield page

    async def get(self, url, params=None):
        self.urls.append(url)
        return await super().get(url, params=params)


@pytest.mark.asyncio
async def test_app_mode_reads_users_path_without_connection(
    db_session, monkeypatch, tmp_path
):
    """App-only: zero wierszy M365Connection, ścieżki `/users/{upn}`, connection_id NULL."""
    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(storage_service, "ORDER_MAIL_DIR", tmp_path / "order_mail")
    upn = f"nexus-zamowienia-{RUN}@example.test"
    monkeypatch.setattr(svc.settings, "ORDER_MAIL_UPN", upn)
    monkeypatch.setattr(svc.settings, "ORDER_MAIL_AUTH_MODE", "app")
    monkeypatch.setattr(svc.settings, "ORDER_MAIL_SENDER_ALLOWLIST", "")
    monkeypatch.setattr(svc, "app_only_credentials_configured", lambda: True)

    # Wiadomość bez PDF-a: przechodzi przez listę i załączniki, nie dotyka parsera.
    mid = f"app-{RUN}"
    fake = _RecordingGraph(
        [_msg(mid)],
        {
            f"graph-{mid}": [
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": "notatka.txt",
                    "contentType": "text/plain",
                    "contentBytes": "AA==",
                }
            ]
        },
    )
    monkeypatch.setattr(svc, "AppGraphClient", lambda: fake)

    async def _boom(conn, db):  # delegated NIE może zostać dotknięte w trybie app
        raise AssertionError("GraphClient(conn, db) called in app mode")

    monkeypatch.setattr(svc, "GraphClient", _boom)

    stats = await svc.run_order_mail_ingest(reason="test")

    assert "no_connection" not in stats.errors
    assert "app_only_misconfigured" not in stats.errors
    assert stats.ignored_no_pdf == 1
    assert fake.urls[0] == f"/users/{upn}/mailFolders/Inbox/messages"
    assert fake.urls[1] == f"/users/{upn}/messages/graph-{mid}/attachments"

    from sqlalchemy import select

    from app.models.order_mail import OrderMailDocument

    row = await db_session.scalar(
        select(OrderMailDocument).where(
            OrderMailDocument.internet_message_id == f"<{mid}-{RUN}@example>"
        )
    )
    assert row is not None
    assert row.connection_id is None
    assert row.outcome == "ignored_no_pdf"


@pytest.mark.asyncio
async def test_app_mode_without_credentials_records_error(db_session, monkeypatch):
    """Brak poświadczeń client_credentials = jawny błąd stanu, nie cicha pustka."""
    monkeypatch.setattr(svc.settings, "ORDER_MAIL_UPN", "nexus-zamowienia@example.test")
    monkeypatch.setattr(svc.settings, "ORDER_MAIL_AUTH_MODE", "app")
    monkeypatch.setattr(svc, "app_only_credentials_configured", lambda: False)
    stats = await svc.run_order_mail_ingest(reason="test")
    assert "app_only_misconfigured" in stats.errors
    state = await svc.read_state(db_session)
    assert state["last_status"] == "error"
    assert "app-only reader misconfigured" in (state["last_error"] or "")


@pytest.mark.asyncio
async def test_app_graph_client_token_lifecycle(monkeypatch):
    """Wejście bierze token; 401-owe odświeżenie wymusza nowy; brak tokenu = wyjątek."""
    from app.services.m365 import app_graph_client as agc

    calls: list[bool] = []

    def fake_acquire(*, force_refresh=False):
        calls.append(force_refresh)
        return f"tok-{len(calls)}"

    monkeypatch.setattr(agc, "acquire_app_token", fake_acquire)
    async with agc.AppGraphClient() as gc:
        assert gc._access_token == "tok-1"
        await gc._authorize()  # no-op: nie ma właściciela do sprawdzenia
        await gc._refresh_and_persist()
        assert gc._access_token == "tok-2"
    assert calls == [False, True]

    monkeypatch.setattr(agc, "acquire_app_token", lambda *, force_refresh=False: None)
    with pytest.raises(agc.AppOnlyTokenUnavailable):
        async with agc.AppGraphClient():
            pass


def test_msal_client_credentials_refresh_contract():
    """Kontrakt MSAL, na którym stoi `acquire_app_token(force_refresh=True)`.

    Review #1343 zakładał odwrotnie: że `remove_tokens_for_client` nie istnieje,
    a `acquire_token_for_client(force_refresh=True)` działa. W msal 1.37 jest
    dokładnie na odwrót — ten test wywali się przy zmianie biblioteki, zanim
    zrobi to produkcja po pierwszym 401. Hermetyczny: konstruktor MSAL robi
    OIDC discovery po sieci, więc dostaje podstawiony klient HTTP.
    """
    import json

    import msal

    class _Resp:
        status_code = 200
        headers: dict = {}

        def __init__(self, payload):
            self.text = json.dumps(payload)

        def json(self):
            return json.loads(self.text)

        def raise_for_status(self):
            return None

    class _Http:
        def get(self, url, **kwargs):
            base = "https://login.microsoftonline.com/tenant-test"
            return _Resp(
                {
                    "authorization_endpoint": f"{base}/oauth2/v2.0/authorize",
                    "token_endpoint": f"{base}/oauth2/v2.0/token",
                    "issuer": f"{base}/v2.0",
                }
            )

        def post(self, url, **kwargs):  # nigdy nie powinno dojść do sieci
            raise AssertionError("unexpected network call")

    app = msal.ConfidentialClientApplication(
        client_id="nexus-test-client",  # nie GUID: reguła gitleaks fireflies-api-key
        authority="https://login.microsoftonline.com/tenant-test",
        client_credential="x",
        http_client=_Http(),
        instance_discovery=False,
    )
    assert callable(getattr(app, "remove_tokens_for_client", None))
    app.remove_tokens_for_client()  # pusty cache — no-op, nie wyjątek
    with pytest.raises(ValueError):
        app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"], force_refresh=True
        )


@pytest.mark.asyncio
async def test_roster_includes_old_contract_and_refreshes_only_its_client(db_session):
    from app.services.order_mail_resolver import load_roster, resolve_rows

    client = Client(name=f"Roster PFRON {RUN}")
    other = Client(name=f"Other roster {RUN}")
    db_session.add_all([client, other])
    await db_session.flush()
    person = Candidate(
        name="Konrad", lastname="Korcz", email=f"roster-{uuid.uuid4().hex}@example.test"
    )
    outsider = Candidate(
        name="Konrad",
        lastname="Korcz",
        email=f"outsider-{uuid.uuid4().hex}@example.test",
    )
    db_session.add_all([person, outsider])
    await db_session.flush()
    db_session.add_all(
        [
            Contract(
                candidate_id=person.id,
                client_id=client.id,
                status=ContractStatus.ended,
                start_date=date(2020, 1, 1),
                end_date=date(2020, 12, 31),
            ),
            Contract(
                candidate_id=outsider.id,
                client_id=other.id,
                status=ContractStatus.active,
                start_date=date(2031, 1, 1),
            ),
        ]
    )
    await db_session.flush()
    roster = await load_roster(db_session, client.id)
    assert [p.candidate_id for p in roster] == [person.id]
    resolved = resolve_rows(
        [ConsultantOrderRow(consultant_name="Konrada Korcza")], roster
    )
    assert resolved[0].candidate_id == person.id
    assert resolved[0].contract_id is not None
    assert not resolved[0].has_single_live_contract
    # The next read must include an assignment made since the previous read.
    db_session.add(
        Contract(
            candidate_id=outsider.id,
            client_id=client.id,
            status=ContractStatus.draft,
            start_date=date(2031, 1, 1),
        )
    )
    await db_session.flush()
    refreshed = await load_roster(db_session, client.id)
    assert {p.candidate_id for p in refreshed} == {person.id, outsider.id}
    await db_session.rollback()
