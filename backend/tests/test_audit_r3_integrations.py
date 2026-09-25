"""Audyt 25.09.2026, runda 3 — obszar D: powiadomienia, M365, Jarvis, poczta.

R3-2 callback M365 podpinał skrzynkę innej osoby, R3-3 mail o etapie omijał
wyciszenia i sekcje, R3-4 karta debriefu Jarvisa opisywała osobę podaną przez
model, R3-6 mail odrzucenia mógł wyjść dwa razy, R3-7 prywatne spotkania
z Outlooka były widoczne w NEXUSIE z treścią. Poczta zamówień: konflikt
spójności spoza dziennika nie może udawać „wpisu równoległego biegu”,
odrzucony wpis „Nieudane” nie jest oryginałem dla duplikatu.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from app.api import microsoft365
from app.models.user import User, UserRole
from app.services.m365.provider import TokenBundle

# ── R3-2: callback M365 przyjmuje wyłącznie skrzynkę właściciela konta ───────


def _nexus_user(email: str = "anna.nowak@b2bnetwork.pl", **extra) -> User:
    return User(
        id=41,
        email=email,
        name="Anna Nowak",
        role=UserRole.recruiter,
        roles=[UserRole.recruiter.value],
        is_active=True,
        profile_completed=True,
        authorization_version=1,
        **extra,
    )


def _bundle(upn: str) -> TokenBundle:
    return TokenBundle(
        access_token="access",
        refresh_token="refresh",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        scopes=["Mail.Read"],
        tenant_id="tenant",
        mailbox_upn=upn,
    )


async def _run_callback(monkeypatch, user: User, bundle: TokenBundle | Exception):
    db = AsyncMock()
    db.add = MagicMock()
    db.get.return_value = user
    db.scalar.return_value = None
    monkeypatch.setattr(
        microsoft365.m365_oauth,
        "verify_state",
        MagicMock(return_value=(user.id, "pkce-verifier")),
    )
    exchange = (
        AsyncMock(side_effect=bundle)
        if isinstance(bundle, Exception)
        else AsyncMock(return_value=bundle)
    )
    monkeypatch.setattr(microsoft365.m365_oauth, "exchange_code", exchange)
    cipher = MagicMock()
    cipher.encrypt.side_effect = lambda value: f"ct:{value}"
    monkeypatch.setattr(microsoft365, "get_token_cipher", lambda: cipher)
    spawned: list[str] = []

    def _fake_spawn(coro, name):
        coro.close()
        spawned.append(name)

    monkeypatch.setattr(microsoft365, "_spawn", _fake_spawn)
    response = await microsoft365.callback.__wrapped__(
        request=MagicMock(),
        code="authorization-code",
        state="signed-state",
        error=None,
        error_description=None,
        db=db,
    )
    return response, db, spawned


@pytest.mark.asyncio
async def test_callback_rejects_mailbox_of_another_person(monkeypatch) -> None:
    user = _nexus_user()
    response, db, spawned = await _run_callback(
        monkeypatch, user, _bundle("jan.kowalski@b2bnetwork.pl")
    )

    location = response.headers["location"]
    assert response.status_code == 302
    assert "status=error" in location
    assert "innej+osoby" in location
    assert "anna.nowak%40b2bnetwork.pl" in location
    db.add.assert_not_called()
    db.commit.assert_not_awaited()
    assert spawned == []


@pytest.mark.asyncio
async def test_callback_rejects_bundle_without_mailbox_address(monkeypatch) -> None:
    response, db, _ = await _run_callback(monkeypatch, _nexus_user(), _bundle(""))
    assert "status=error" in response.headers["location"]
    db.add.assert_not_called()
    db.commit.assert_not_awaited()


@pytest.mark.parametrize(
    ("user_kwargs", "upn"),
    [
        ({}, "Anna.Nowak@B2BNetwork.pl"),
        # Konto sprzed SSO z innym adresem w `email` — SSO zapamiętało UPN.
        (
            {
                "email": "a.nowak@b2bnetwork.pl",
                "microsoft_upn": "anna.nowak@b2bnetwork.pl",
            },
            "anna.nowak@b2bnetwork.pl",
        ),
    ],
)
@pytest.mark.asyncio
async def test_callback_accepts_own_mailbox(monkeypatch, user_kwargs, upn) -> None:
    user = _nexus_user(**user_kwargs)
    response, db, spawned = await _run_callback(monkeypatch, user, _bundle(upn))
    assert "status=success" in response.headers["location"]
    db.add.assert_called_once()
    db.commit.assert_awaited()
    assert len(spawned) == 2


@pytest.mark.asyncio
async def test_callback_token_exchange_error_does_not_leak_exception(
    monkeypatch,
) -> None:
    response, db, _ = await _run_callback(
        monkeypatch,
        _nexus_user(),
        RuntimeError("Token response missing access_token: {'secret': 'x'}"),
    )
    location = response.headers["location"]
    assert "status=error" in location
    assert "secret" not in location
    assert "RuntimeError" not in location
    db.add.assert_not_called()


# ── R3-3: mail o etapie przechodzi bramkę odbiorcy ───────────────────────────


@pytest.mark.parametrize("eligible", [False, True])
@pytest.mark.asyncio
async def test_stage_email_respects_recipient_gate(monkeypatch, eligible) -> None:
    from app.services import stage_notification_emitter as emitter
    from app.services.stage_notification_resolver import ResolvedRecipient

    monkeypatch.setattr(
        emitter,
        "resolve_recipients",
        AsyncMock(
            return_value=[
                ResolvedRecipient(user_id=7, notify_inapp=False, notify_email=True)
            ]
        ),
    )
    policy = MagicMock()
    policy.allows.return_value = True
    monkeypatch.setattr(emitter, "load_policy", AsyncMock(return_value=policy))
    gate = AsyncMock(return_value=eligible)
    monkeypatch.setattr(emitter, "notification_recipient_has_access", gate)
    monkeypatch.setattr(
        emitter,
        "_user_by_id",
        AsyncMock(return_value=SimpleNamespace(id=7, email="r@x.pl", name="R")),
    )
    monkeypatch.setattr(emitter, "_client_name", AsyncMock(return_value=None))
    sent = AsyncMock()
    monkeypatch.setattr(emitter, "run_in_threadpool", sent)

    await emitter.notify_stage_change(
        AsyncMock(),
        new_stage=SimpleNamespace(id=5, moved_at=datetime.now(timezone.utc)),
        previous_stage=None,
        job=SimpleNamespace(id=3, title="Java", client_id=None),
        candidate=SimpleNamespace(id=9, name="Jan", lastname="Nowak"),
        mover=None,
        stage_display_name="CV wysłane",
    )

    gate.assert_awaited_once()
    assert gate.await_args.args[1] == 7
    assert gate.await_args.kwargs["link"] == "/candidates/9"
    assert sent.await_count == (1 if eligible else 0)


# ── R3-4: Jarvis — karta debriefu i nazwy z odczytu, nie z modelu ────────────


class _FakeTransport:
    def __init__(self, routes):
        self.routes = routes
        self.calls: list[str] = []

    async def call(self, spec):
        from app.services.jarvis.transport import ToolResponse

        self.calls.append(spec.path)
        status, data = self.routes.get(spec.path, (404, None))
        return ToolResponse(status=status, data=data)


def _debrief_args(**extra):
    return {
        "event_id": 11,
        "outcome": "good",
        "offer_acceptance": "likely",
        **extra,
    }


_EVENT_ROUTES = {
    "/api/interview-cycle/events/11": (200, {"id": 11, "candidate_id": 7, "job_id": 3}),
    "/api/candidates/7/quick-view": (
        200,
        {"candidate": {"id": 7, "name": "Ewa", "lastname": "Lis"}},
    ),
    "/api/jobs/3": (200, {"id": 3, "title": "Java Dev", "client_name": "Bank"}),
}


@pytest.mark.asyncio
async def test_debrief_rejects_candidate_other_than_event() -> None:
    from app.services.jarvis.agent import ProposalRejected, prepare_proposal
    from app.services.jarvis.tools import TOOLS_BY_NAME

    tool = TOOLS_BY_NAME["save_interview_debrief"]
    with pytest.raises(ProposalRejected, match="innego kandydata"):
        await prepare_proposal(
            _FakeTransport(_EVENT_ROUTES), tool, _debrief_args(candidate_id=99)
        )


@pytest.mark.asyncio
async def test_debrief_card_names_people_from_the_event() -> None:
    from app.services.jarvis.agent import prepare_proposal
    from app.services.jarvis.tools import TOOLS_BY_NAME

    tool = TOOLS_BY_NAME["save_interview_debrief"]
    args, preview = await prepare_proposal(
        _FakeTransport(_EVENT_ROUTES), tool, _debrief_args()
    )
    assert args["candidate_id"] == 7
    assert args["job_id"] == 3
    assert "Ewa Lis" in preview["text"]
    assert "Java Dev / Bank" in preview["text"]
    # Zapis nadal idzie wyłącznie po wydarzeniu.
    assert tool.build(args).path == "/api/interview-cycle/events/11/debrief"


@pytest.mark.asyncio
async def test_debrief_on_unknown_event_is_rejected() -> None:
    from app.services.jarvis.agent import ProposalRejected, prepare_proposal
    from app.services.jarvis.tools import TOOLS_BY_NAME

    with pytest.raises(ProposalRejected):
        await prepare_proposal(
            _FakeTransport({}),
            TOOLS_BY_NAME["save_interview_debrief"],
            _debrief_args(),
        )


@pytest.mark.asyncio
async def test_pool_and_alert_cards_use_names_read_from_api() -> None:
    from app.services.jarvis.agent import prepare_proposal, sanitize_args
    from app.services.jarvis.tools import TOOLS_BY_NAME

    pool_tool = TOOLS_BY_NAME["add_to_talent_pool"]
    assert "pool_name" not in pool_tool.input_schema["properties"]
    routes = {
        "/api/talent-pools": (200, [{"id": 4, "name": "Java Senior"}]),
        "/api/candidates/7/quick-view": _EVENT_ROUTES["/api/candidates/7/quick-view"],
        "/api/dl-alerts/cards": (
            200,
            {"cards": [{"id": 12, "title": "Kończy się zamówienie Bank"}]},
        ),
    }
    args = sanitize_args(
        pool_tool, {"pool_id": 4, "candidate_id": 7, "pool_name": "Pula CEO"}
    )
    _, preview = await prepare_proposal(_FakeTransport(routes), pool_tool, args)
    assert "Java Senior" in preview["text"]
    assert "Pula CEO" not in preview["text"]

    alert_tool = TOOLS_BY_NAME["mark_client_alert_handled"]
    assert "title" not in alert_tool.input_schema["properties"]
    args = sanitize_args(alert_tool, {"alert_id": 12, "title": "Zmyślona sprawa"})
    _, preview = await prepare_proposal(_FakeTransport(routes), alert_tool, args)
    assert "Kończy się zamówienie Bank" in preview["text"]
    assert "Zmyślona" not in preview["text"]


# ── R3-6: rezerwacja maila odrzucenia commitowana przed Graphem ──────────────


@pytest.mark.asyncio
async def test_rejection_dispatch_commits_reservation_and_leases_row(
    monkeypatch,
) -> None:
    import asyncio

    from app.models.recruitment_pipeline import PipelineStage
    from app.models.rejection_email import RejectionEmailStatus
    from app.services import rejection_email_scheduler as scheduler
    from app.services.m365 import sender as m365_sender

    row = SimpleNamespace(
        id=77,
        status=RejectionEmailStatus.pending,
        recruiter_id=5,
        candidate_id=9,
        job_id=3,
        to_email="kandydat@example.com",
        subject="Dziękujemy",
        body_html="<p>x</p>",
        scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    db = AsyncMock()
    db.add = MagicMock()
    db.scalar.side_effect = [row, PipelineStage.rejected, SimpleNamespace(id=1)]
    owner = SimpleNamespace(id=5)
    monkeypatch.setattr(scheduler, "eligible_m365_owner", AsyncMock(return_value=owner))
    monkeypatch.setattr(scheduler, "_can_send_rejection_email", lambda _u: True)
    seen: dict = {}

    async def _send_new(*_args, **kwargs):
        seen.update(kwargs)
        seen["lease"] = row.scheduled_at
        # Proces ubity po wysyłce (deploy) — rezerwacja musi już być zapisana.
        raise asyncio.CancelledError

    monkeypatch.setattr(m365_sender, "send_new", _send_new)
    before = datetime.now(timezone.utc)
    with pytest.raises(asyncio.CancelledError):
        await scheduler.dispatch(db, row.id)

    assert seen["commit_reservation"] is True
    assert seen["client_request_id"] == "scheduled-rejection:77"
    assert seen["lease"] >= before + timedelta(minutes=scheduler.SEND_LEASE_MINUTES - 1)
    assert row.status == RejectionEmailStatus.pending


# ── R3-7: prywatne spotkania z Outlooka i iCal bez treści ────────────────────


def _graph_event(sensitivity: str = "private", change_key: str = "ck1") -> dict:
    return {
        "id": "graph-ev-1",
        "changeKey": change_key,
        "subject": "Wizyta u lekarza",
        "body": {"content": "Gabinet 12, dr Kowalski"},
        "start": {"dateTime": "2026-10-01T10:00:00Z"},
        "end": {"dateTime": "2026-10-01T11:00:00Z"},
        "location": {"displayName": "Przychodnia"},
        "attendees": [{"emailAddress": {"address": "kandydat@example.com"}}],
        "sensitivity": sensitivity,
    }


def test_event_select_asks_for_sensitivity() -> None:
    from app.services.m365.sync import EVENT_SELECT

    assert "sensitivity" in EVENT_SELECT.split(",")


class _UrlGraph:
    def __init__(self):
        self.calls: list[tuple[str, dict | None]] = []

    async def paginate(self, url, params=None):
        self.calls.append((url, params))
        yield {"value": [], "@odata.deltaLink": "https://graph/new-delta"}


@pytest.mark.parametrize("already_reset", [False, True])
@pytest.mark.asyncio
async def test_old_events_cursor_is_replaced_once_to_read_sensitivity(
    already_reset, monkeypatch
) -> None:
    from app.services.m365 import sync as sync_mod

    # Przebieg po starszych prywatnych spotkaniach ma własne testy (runda 4).
    monkeypatch.setattr(sync_mod, "_scrub_old_private_events", AsyncMock())

    conn = SimpleNamespace(id=5, delta_token_events="https://graph/old-delta")
    db = AsyncMock()
    db.get.return_value = (
        SimpleNamespace(value={"connection_ids": [5]}) if already_reset else None
    )
    graph = _UrlGraph()
    await sync_mod._sync_events(
        db, graph, conn, sync_mod.SyncResult(connection_id=conn.id)
    )

    url, params = graph.calls[0]
    if already_reset:
        assert url == "https://graph/old-delta"
        db.execute.assert_not_awaited()
    else:
        assert url == "/me/calendarView/delta"
        assert "sensitivity" in params["$select"]
        db.execute.assert_awaited_once()  # znacznik „odczytano ponownie”
    assert conn.delta_token_events == "https://graph/new-delta"


@pytest.mark.parametrize("sensitivity", ["private", "Confidential"])
@pytest.mark.asyncio
async def test_private_outlook_event_is_imported_without_content(sensitivity) -> None:
    from app.services.m365.sync import _upsert_event

    db = AsyncMock()
    db.add = MagicMock()
    db.scalar.return_value = None
    assert await _upsert_event(
        db, SimpleNamespace(user_id=5), _graph_event(sensitivity)
    )

    row = db.add.call_args.args[0]
    assert row.title == "Spotkanie prywatne"
    assert row.description is None
    assert row.location is None
    assert row.attendees == []
    assert row.teams_link is None
    assert row.candidate_id is None
    # Jedyne zapytanie to odczyt istniejącego wiersza — bez szukania kandydata.
    assert db.scalar.await_count == 1


@pytest.mark.asyncio
async def test_existing_private_row_is_scrubbed_even_with_same_change_key() -> None:
    from app.models.calendar_event import EventType
    from app.services.m365.sync import _upsert_event

    existing = SimpleNamespace(
        title="Wizyta u lekarza",
        description="Gabinet 12",
        location="Przychodnia",
        attendees=[{"address": "kandydat@example.com"}],
        teams_link=None,
        online_meeting_url=None,
        m365_change_key="ck1",
        event_type=EventType.meeting,
        candidate_id=None,
    )
    db = AsyncMock()
    db.scalar.return_value = existing
    assert await _upsert_event(db, SimpleNamespace(user_id=5), _graph_event())
    assert existing.title == "Spotkanie prywatne"
    assert existing.description is None
    assert existing.location is None
    assert existing.attendees == []

    # Już wyczyszczony wiersz z tym samym changeKey — bez zapisu.
    assert not await _upsert_event(db, SimpleNamespace(user_id=5), _graph_event())


@pytest.mark.asyncio
async def test_normal_outlook_event_keeps_content() -> None:
    from app.services.m365.sync import _upsert_event

    db = AsyncMock()
    db.add = MagicMock()
    db.scalar.side_effect = [None, None]
    assert await _upsert_event(
        db, SimpleNamespace(user_id=5), _graph_event(sensitivity="normal")
    )
    row = db.add.call_args.args[0]
    assert row.title == "Wizyta u lekarza"
    assert row.attendees == [{"address": "kandydat@example.com", "name": None}]


@pytest.mark.asyncio
async def test_private_ical_event_is_imported_without_content(monkeypatch) -> None:
    from app.services import ical_import

    start = (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y%m%dT%H%M%SZ")
    feed = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//t//t//\r\n"
        "BEGIN:VEVENT\r\nUID:priv-1\r\n"
        f"DTSTART:{start}\r\nSUMMARY:Terapia\r\nDESCRIPTION:Notatki\r\n"
        "LOCATION:Gabinet\r\nCLASS:PRIVATE\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    ).encode()
    monkeypatch.setattr(ical_import, "_fetch_ical_safely", AsyncMock(return_value=feed))
    db = AsyncMock()
    db.add = MagicMock()
    db.scalar.return_value = None
    await ical_import.import_ical_url(db, "https://cal.example.com/x.ics", creator_id=5)
    row = db.add.call_args.args[0]
    assert row.title == "Spotkanie prywatne"
    assert row.description is None
    assert row.location is None


# ── Poczta zamówień ──────────────────────────────────────────────────────────


def _integrity(
    constraint: str | None, message: str = "duplicate key"
) -> IntegrityError:
    orig = SimpleNamespace(constraint_name=constraint)
    err = IntegrityError("INSERT", {}, Exception(message))
    err.orig = orig
    return err


def test_only_journal_unique_conflict_counts_as_parallel_run() -> None:
    from app.services.order_mail_ingest import _is_journal_unique_conflict

    assert _is_journal_unique_conflict(
        _integrity("uq_order_mail_documents_message_attachment")
    )
    assert not _is_journal_unique_conflict(_integrity("ck_client_orders_md_coherence"))
    assert _is_journal_unique_conflict(
        _integrity(None, 'violates "uq_order_mail_documents_message_no_attachment"')
    )
    assert not _is_journal_unique_conflict(_integrity(None, "fk violation"))


@pytest.mark.asyncio
async def test_add_journal_row_reraises_foreign_integrity_error() -> None:
    from app.services.order_mail_ingest import _add_journal_row

    class _Nested:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            raise _integrity("fk_order_mail_documents_client_id")

    db = MagicMock()
    db.begin_nested.return_value = _Nested()
    db.commit = AsyncMock()
    with pytest.raises(IntegrityError):
        await _add_journal_row(db, MagicMock())
    db.commit.assert_not_awaited()


def test_first_with_sha_excludes_dismissed_unprocessed_rows() -> None:
    from app.services.order_mail_ingest import dismissed_unprocessed_clause

    sql = str(
        dismissed_unprocessed_clause().compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "dismissed_from" in sql
    assert "jsonb_typeof" in sql
    assert "'failed'" in sql


@pytest.mark.asyncio
async def test_dismiss_stamps_the_previous_outcome(monkeypatch) -> None:
    from app.api import order_mail_queue as queue
    from app.models.order_mail import OUTCOME_DISMISSED, OUTCOME_FAILED

    doc = SimpleNamespace(
        id=3,
        outcome=OUTCOME_FAILED,
        document_meta={"failed_retry": {"attempts": 3}},
        reviewed_by_user_id=None,
        reviewed_at=None,
    )
    monkeypatch.setattr(queue, "_load_visible", AsyncMock(return_value=doc))
    monkeypatch.setattr(queue, "_require_apply_rights", AsyncMock())
    monkeypatch.setattr(queue, "_close_review_cards", AsyncMock())
    monkeypatch.setattr(queue, "_serialize", AsyncMock(return_value={"id": 3}))
    await queue.dismiss_queue_item(3, SimpleNamespace(id=8), AsyncMock())
    assert doc.outcome == OUTCOME_DISMISSED
    assert doc.document_meta == {
        "failed_retry": {"attempts": 3},
        "dismissed_from": OUTCOME_FAILED,
    }


# ── Z bazą (CI) ──────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db_session():
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        yield session


@pytest.mark.asyncio
async def test_dismissed_failed_row_is_not_the_original_of_a_resent_pdf(db_session):
    from app.models.order_mail import (
        OUTCOME_DISMISSED,
        OUTCOME_FAILED,
        OUTCOME_NEEDS_REVIEW,
    )
    from app.services import order_mail_ingest as svc

    def _row(outcome: str, **extra):
        mid = uuid.uuid4().hex[:10]
        row = svc._base_row(
            None,
            {
                "id": f"graph-{mid}",
                "internetMessageId": f"<{mid}@r3.example>",
                "subject": "Zamówienie",
                "from": {"emailAddress": {"address": "orders@bank-r3.example"}},
                "receivedDateTime": "2031-03-03T08:00:00Z",
            },
        )
        row.attachment_sha256 = sha
        row.outcome = outcome
        for key, value in extra.items():
            setattr(row, key, value)
        return row

    sha = uuid.uuid4().hex + uuid.uuid4().hex
    # Odrzucony po rundzie 3 (stempel) i przed nią (kształt wpisu nieudanego).
    stamped = _row(OUTCOME_DISMISSED, document_meta={"dismissed_from": OUTCOME_FAILED})
    legacy = _row(OUTCOME_DISMISSED, error="Błąd przetwarzania: OSError")
    db_session.add_all([stamped, legacy])
    await db_session.commit()
    assert await svc._first_with_sha(db_session, sha) is None

    # Odrzucony po odczycie (był w „Do weryfikacji”) nadal jest oryginałem.
    reviewed = _row(
        OUTCOME_DISMISSED,
        extraction={"order_number": "X"},
        document_meta={"dismissed_from": OUTCOME_NEEDS_REVIEW},
    )
    db_session.add(reviewed)
    await db_session.commit()
    assert (await svc._first_with_sha(db_session, sha)).id == reviewed.id
