"""Pobieranie zamówień z maila: sloty, watermark, rozpoznanie, dedup, dziennik.

Graph jest podstawiony — żadnej sieci. PDF-y nie są prawdziwe: tekst dokumentu
podstawiamy w ``extract_order_text``, bo interesuje nas przepływ (dedup po SHA,
drabina wyników, idempotencja), a nie ekstrakcja (ta ma własne testy).
Lata w danych: 2031+ (wolny zakres bazy testowej).
"""

import random
import uuid
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from sqlalchemy import select

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
from app.services.order_client_identity import ClientIdentification
from app.services.order_document_text import OrderDocumentText
from app.services.order_pdf_parser import ConsultantOrderRow, OrderExtraction
from app.tasks.order_mail_ingest import due_slot, parse_slots

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


# ── Sloty ────────────────────────────────────────────────────────────────────


class TestDueSlot:
    slots = [time(8, 0), time(15, 0)]

    def test_first_run_is_immediate(self):
        assert (
            due_slot(datetime(2031, 3, 3, 10, 0, tzinfo=WAW), None, self.slots) is True
        )

    def test_runs_once_per_slot_not_every_check(self):
        last = datetime(2031, 3, 3, 8, 4, tzinfo=WAW)  # bieg z 08:00 skończył się 08:04
        assert (
            due_slot(datetime(2031, 3, 3, 8, 30, tzinfo=WAW), last, self.slots) is False
        )
        assert (
            due_slot(datetime(2031, 3, 3, 14, 59, tzinfo=WAW), last, self.slots)
            is False
        )
        assert (
            due_slot(datetime(2031, 3, 3, 15, 1, tzinfo=WAW), last, self.slots) is True
        )

    def test_no_third_run_in_the_evening(self):
        """Dwa markery z min_gap≈10h odpalałyby o 18:00; sloty — nie."""
        last = datetime(2031, 3, 3, 15, 3, tzinfo=WAW)
        assert (
            due_slot(datetime(2031, 3, 3, 18, 0, tzinfo=WAW), last, self.slots) is False
        )
        assert (
            due_slot(datetime(2031, 3, 3, 23, 59, tzinfo=WAW), last, self.slots)
            is False
        )

    def test_restart_at_0759_does_not_lose_0800(self):
        last = datetime(2031, 3, 3, 15, 3, tzinfo=WAW)
        assert (
            due_slot(datetime(2031, 3, 4, 8, 0, tzinfo=WAW), last, self.slots) is True
        )

    def test_overrunning_run_does_not_double_fire(self):
        # bieg zaczął 07:58, skończył 08:20 → slot 08:00 leży PRZED last → nie
        last = datetime(2031, 3, 4, 8, 20, tzinfo=WAW)
        assert (
            due_slot(datetime(2031, 3, 4, 8, 25, tzinfo=WAW), last, self.slots) is False
        )

    def test_missed_yesterday_slot_after_long_outage(self):
        last = datetime(2031, 3, 1, 15, 3, tzinfo=WAW)
        assert (
            due_slot(datetime(2031, 3, 3, 7, 0, tzinfo=WAW), last, self.slots) is True
        )

    def test_parse_slots_tolerates_junk(self):
        assert parse_slots("08:00, 15:00,bad, 15:00") == [time(8, 0), time(15, 0)]
        assert parse_slots("") == []


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
    again = await svc.run_order_mail_ingest(reason="test")
    assert again.skipped_existing == 3 or again.skipped_existing >= 1
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
    zrobi to produkcja po pierwszym 401.
    """
    import msal

    app = msal.ConfidentialClientApplication(
        client_id="00000000-0000-0000-0000-000000000000",
        authority="https://login.microsoftonline.com/11111111-1111-1111-1111-111111111111",
        client_credential="not-a-real-secret",
    )
    assert callable(getattr(app, "remove_tokens_for_client", None))
    app.remove_tokens_for_client()  # pusty cache — no-op, nie wyjątek
    with pytest.raises(ValueError):
        app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"], force_refresh=True
        )
