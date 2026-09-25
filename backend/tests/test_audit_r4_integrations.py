"""Audyt 25.09.2026, runda 4 — obszar D: poczta zamówień i M365.

R4-25 klauzula „odrzucony nieudany” dawała NULL dla wpisów odrzuconych przed
rundą 3 (bez stempla ``dismissed_from``, z odczytem), więc ``~klauzula``
wyrzucała prawdziwy oryginał i ponownie przysłany PDF był czytany od nowa.
R4-26 ochrona prywatnego spotkania zależała od typu wydarzenia, który da się
zmienić w NEXUSIE. R4-27 prywatne spotkania starsze niż okno pełnego odczytu
zostawały z treścią.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.dialects import postgresql

# ── R4-25: klauzula „odrzucony nieudany” nigdy nie daje NULL ──────────────────


def _sqlite_engine():
    """SQLite z ``->>`` i emulacją ``jsonb_typeof`` — logika trójwartościowa
    jest ta sama co w Postgresie, więc NULL w klauzuli wychodzi tu tak samo."""
    engine = create_engine("sqlite://")

    def _jsonb_typeof(value):
        if value is None:
            return None
        parsed = json.loads(value)
        if parsed is None:
            return "null"
        if isinstance(parsed, bool):
            return "boolean"
        if isinstance(parsed, (int, float)):
            return "number"
        if isinstance(parsed, str):
            return "string"
        return "array" if isinstance(parsed, list) else "object"

    @event.listens_for(engine, "connect")
    def _register(dbapi_conn, _record):
        dbapi_conn.create_function("jsonb_typeof", 1, _jsonb_typeof)

    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE order_mail_documents (id INTEGER PRIMARY KEY, "
                "outcome TEXT NOT NULL, document_meta TEXT, extraction TEXT, "
                "error TEXT)"
            )
        )
    return engine


def _classify(rows: list[dict]) -> dict[int, object]:
    """Id → wartość klauzuli (True / False / None = NULL) dla każdego wiersza."""
    from app.models.order_mail import OrderMailDocument
    from app.services.order_mail_ingest import dismissed_unprocessed_clause

    engine = _sqlite_engine()
    with engine.begin() as conn:
        for row in rows:
            conn.execute(
                text(
                    "INSERT INTO order_mail_documents "
                    "(id, outcome, document_meta, extraction, error) "
                    "VALUES (:id, :outcome, :meta, :extraction, :error)"
                ),
                {
                    "id": row["id"],
                    "outcome": row["outcome"],
                    "meta": (json.dumps(row["meta"]) if "meta" in row else None),
                    "extraction": (
                        json.dumps(row["extraction"]) if "extraction" in row else None
                    ),
                    "error": row.get("error"),
                },
            )
        result = conn.execute(
            select(
                OrderMailDocument.id,
                dismissed_unprocessed_clause().label("clause"),
            ).select_from(OrderMailDocument.__table__)
        )
        values = {row.id: row.clause for row in result}
        excluded = {
            row.id
            for row in conn.execute(
                select(OrderMailDocument.id)
                .select_from(OrderMailDocument.__table__)
                .where(~dismissed_unprocessed_clause())
            )
        }
    return {
        key: (None if value is None else bool(value)) for key, value in values.items()
    } | {"kept": excluded}


def test_dismissed_before_round_three_with_extraction_is_not_null() -> None:
    from app.models.order_mail import (
        OUTCOME_APPLIED,
        OUTCOME_DISMISSED,
        OUTCOME_FAILED,
        OUTCOME_NEEDS_REVIEW,
    )

    got = _classify(
        [
            # Odrzucony przed rundą 3 po odczycie: bez stempla, z extraction.
            {"id": 1, "outcome": OUTCOME_DISMISSED, "extraction": {"n": "X"}},
            # j.w., z błędem (odczyt był, a potem coś padło) — nadal oryginał.
            {
                "id": 2,
                "outcome": OUTCOME_DISMISSED,
                "extraction": {"n": "X"},
                "error": "Błąd",
                "meta": {"pages": 1},
            },
            # Odrzucony przed rundą 3 nieudany: bez odczytu, z błędem.
            {"id": 3, "outcome": OUTCOME_DISMISSED, "error": "Błąd"},
            # j.w., odczyt zapisany jako JSON null.
            {"id": 4, "outcome": OUTCOME_DISMISSED, "extraction": None, "error": "B"},
            # Po rundzie 3: stempel.
            {
                "id": 5,
                "outcome": OUTCOME_DISMISSED,
                "meta": {"dismissed_from": OUTCOME_FAILED},
            },
            {
                "id": 6,
                "outcome": OUTCOME_DISMISSED,
                "meta": {"dismissed_from": OUTCOME_NEEDS_REVIEW},
                "extraction": {"n": "X"},
            },
            # Nie odrzucony — nigdy.
            {"id": 7, "outcome": OUTCOME_APPLIED, "extraction": {"n": "X"}},
        ]
    )
    assert got[1] is False
    assert got[2] is False
    assert got[3] is True
    assert got[4] is True
    assert got[5] is True
    assert got[6] is False
    assert got[7] is False
    # Żaden wiersz nie daje NULL — `~klauzula` nie wyrzuca po cichu oryginałów.
    assert got["kept"] == {1, 2, 6, 7}


def test_dismissed_clause_never_compares_a_bare_stamp() -> None:
    """Porównanie z samym ``->>`` daje NULL, gdy stempla nie ma — musi być
    osłonięte ``coalesce`` (tak renderuje się to w Postgresie)."""
    from app.services.order_mail_ingest import dismissed_unprocessed_clause

    sql = str(
        dismissed_unprocessed_clause().compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "coalesce((order_mail_documents.document_meta ->> 'dismissed_from')" in sql
    assert "(order_mail_documents.document_meta ->> 'dismissed_from') = " not in sql


@pytest_asyncio.fixture
async def db_session():
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        yield session


@pytest.mark.asyncio
async def test_legacy_dismissed_read_row_stays_the_original(db_session):
    from app.models.order_mail import OUTCOME_DISMISSED
    from app.services import order_mail_ingest as svc

    sha = uuid.uuid4().hex + uuid.uuid4().hex

    def _row(**extra):
        mid = uuid.uuid4().hex[:10]
        row = svc._base_row(
            None,
            {
                "id": f"graph-{mid}",
                "internetMessageId": f"<{mid}@r4.example>",
                "subject": "Zamówienie",
                "from": {"emailAddress": {"address": "orders@bank-r4.example"}},
                "receivedDateTime": "2031-04-04T08:00:00Z",
            },
        )
        row.attachment_sha256 = sha
        row.outcome = OUTCOME_DISMISSED
        for key, value in extra.items():
            setattr(row, key, value)
        return row

    # Odrzucony nieudany sprzed rundy 3 — nie jest oryginałem.
    failed_legacy = _row(error="Błąd przetwarzania: OSError")
    db_session.add(failed_legacy)
    await db_session.commit()
    assert await svc._first_with_sha(db_session, sha) is None

    # Odrzucony po odczycie sprzed rundy 3 (bez stempla) — nadal oryginał.
    read_legacy = _row(extraction={"order_number": "X"}, document_meta={"pages": 2})
    db_session.add(read_legacy)
    await db_session.commit()
    assert (await svc._first_with_sha(db_session, sha)).id == read_legacy.id


# ── Callback M365: tożsamość Microsoft (`oid`) obok adresu skrzynki ─────────


def _user(**extra):
    from app.models.user import User, UserRole

    base = dict(
        id=41,
        email="anna.nowak@b2bnetwork.pl",
        name="Anna Nowak",
        role=UserRole.recruiter,
        roles=[UserRole.recruiter.value],
        is_active=True,
        profile_completed=True,
        authorization_version=1,
    )
    base.update(extra)
    return User(**base)


# GUID-y budowane w locie: dosłowny UUID łapie reguła gitleaks (fireflies-api-key).
_TENANT = str(uuid.UUID(int=0x11111111222233334444555555555555))
_OTHER_TENANT = str(uuid.UUID(int=0x99999999222233334444555555555555))


@pytest.mark.parametrize(
    ("user_kwargs", "upn", "oid", "tenant", "expected"),
    [
        # Ten sam adres, ale INNA tożsamość Microsoft — UPN nadany ponownie
        # nowej osobie po odejściu poprzedniej. Odmowa.
        ({"azure_oid": "oid-a"}, "anna.nowak@b2bnetwork.pl", "oid-b", _TENANT, False),
        # Konto przypięte do `oid`, adres konta inny niż login (zmiana nazwiska
        # po ostatnim logowaniu) — ta sama osoba, zgoda.
        (
            {"email": "a.kowalska@b2bnetwork.pl", "azure_oid": "OID-A"},
            "anna.nowak@b2bnetwork.pl",
            "oid-a",
            _TENANT,
            True,
        ),
        # Ta sama `oid` z innego tenanta nie wystarcza.
        (
            {"email": "a.kowalska@b2bnetwork.pl", "azure_oid": "oid-a"},
            "anna.nowak@b2bnetwork.pl",
            "oid-a",
            _OTHER_TENANT,
            False,
        ),
        # Bez `oid` na koncie — jak dotąd tylko adres.
        ({}, "anna.nowak@b2bnetwork.pl", "oid-x", _TENANT, True),
        ({}, "jan.kowalski@b2bnetwork.pl", "oid-x", _TENANT, False),
        # Token bez `oid` — konto z `oid` dalej przechodzi po adresie.
        ({"azure_oid": "oid-a"}, "anna.nowak@b2bnetwork.pl", None, _TENANT, True),
    ],
)
def test_mailbox_ownership_uses_the_microsoft_identity(
    monkeypatch, user_kwargs, upn, oid, tenant, expected
) -> None:
    from app.api import microsoft365
    from app.core.config import settings

    monkeypatch.setattr(settings, "M365_TENANT_ID", _TENANT)
    assert (
        microsoft365._mailbox_belongs_to_user(
            upn, _user(**user_kwargs), oid=oid, tenant_id=tenant
        )
        is expected
    )


def test_token_response_carries_the_oid() -> None:
    import base64

    from app.services.m365 import oauth

    claims = {"preferred_username": "anna@x.pl", "oid": "oid-a", "tid": _TENANT}
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    bundle = oauth._parse_token_response(
        {
            "access_token": "a",
            "refresh_token": "r",
            "id_token": f"h.{body}.s",
        }
    )
    assert bundle.oid == "oid-a"
    assert bundle.tenant_id == _TENANT


# ── R4-26: prywatność zależy od POCHODZENIA wydarzenia, nie od typu ──────────


def _graph_event(sensitivity: str = "private", change_key: str = "ck2") -> dict:
    return {
        "id": "graph-ev-r4",
        "changeKey": change_key,
        "subject": "Wizyta u lekarza",
        "body": {"content": "Gabinet 12"},
        "start": {"dateTime": "2026-10-01T10:00:00Z"},
        "end": {"dateTime": "2026-10-01T11:00:00Z"},
        "location": {"displayName": "Przychodnia"},
        "attendees": [{"emailAddress": {"address": "kandydat@example.com"}}],
        "sensitivity": sensitivity,
    }


def _existing_row(**extra):
    from app.models.calendar_event import EventType

    base = dict(
        title="Wizyta u lekarza",
        description="Gabinet 12",
        location="Przychodnia",
        attendees=[{"address": "kandydat@example.com"}],
        teams_link=None,
        online_meeting_url=None,
        m365_change_key="ck1",
        event_type=EventType.meeting,
        candidate_id=None,
        operational_owner_id=None,
    )
    base.update(extra)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_imported_meeting_retyped_in_nexus_is_still_scrubbed() -> None:
    from app.models.calendar_event import EventType
    from app.services.m365.sync import _upsert_event

    # Spotkanie z Outlooka, któremu w NEXUSIE zmieniono typ na rozmowę.
    existing = _existing_row(event_type=EventType.interview)
    db = AsyncMock()
    db.scalar.return_value = existing
    assert await _upsert_event(db, SimpleNamespace(user_id=5), _graph_event())
    assert existing.title == "Spotkanie prywatne"
    assert existing.description is None
    assert existing.location is None
    assert existing.attendees == []


@pytest.mark.parametrize("event_type", ["prep_call", "meeting", "client_interview"])
@pytest.mark.asyncio
async def test_event_created_in_nexus_keeps_its_content(event_type) -> None:
    from app.models.calendar_event import EventType
    from app.services.m365.sync import _upsert_event

    # Prep, spotkanie po rozmowie, blokada rozmowy u klienta — założone
    # w NEXUSIE (mają osobę odpowiedzialną), w Outlooku oznaczone jako prywatne.
    existing = _existing_row(
        event_type=EventType(event_type),
        title="Prep z kandydatem",
        description="Treść NEXUSA",
        operational_owner_id=7,
    )
    db = AsyncMock()
    db.scalar.side_effect = [existing, None]
    await _upsert_event(db, SimpleNamespace(user_id=5), _graph_event())
    # Zwykła aktualizacja z Outlooka, bez zamiany na „Spotkanie prywatne”.
    assert existing.title == "Wizyta u lekarza"
    assert existing.description == "Gabinet 12"


def test_origin_marker_cannot_be_set_from_nexus_edit_nor_by_import() -> None:
    """Pochodzenie = ``operational_owner_id``: ustawiają je wyłącznie ścieżki
    zakładające wydarzenie w NEXUSIE; edycja wydarzenia go nie przyjmuje,
    a import z Outlooka go nie ustawia."""
    import inspect

    from app.api.calendar import CalendarEventUpdate
    from app.services.m365 import sync as sync_mod

    assert "operational_owner_id" not in CalendarEventUpdate.model_fields
    source = inspect.getsource(sync_mod._upsert_event)
    assert "operational_owner_id=" not in source
    assert "operational_owner_id =" not in source


# ── R4-27: prywatne spotkania starsze niż okno pełnego odczytu ──────────────


class _EventsGraph:
    def __init__(self, answers: dict):
        self.answers = answers
        self.urls: list[str] = []

    async def get(self, url, params=None):
        self.urls.append(url)
        answer = self.answers[url.rsplit("/", 1)[-1]]
        if isinstance(answer, Exception):
            raise answer
        return answer


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


def _saved_state(db) -> dict:
    stmt = db.execute.await_args.args[0]
    return stmt.compile(dialect=postgresql.dialect()).params["value"]


@pytest.mark.asyncio
async def test_old_private_meetings_are_scrubbed_by_id() -> None:
    from app.services.m365 import sync as sync_mod
    from app.services.m365.graph_client import GraphRequestError

    private = _existing_row(id=11, external_id="g-private")
    normal = _existing_row(id=12, external_id="g-normal", title="Spotkanie zespołu")
    gone = _existing_row(id=13, external_id="g-gone", title="Stare")
    graph = _EventsGraph(
        {
            "g-private": {"sensitivity": "private"},
            "g-normal": {"sensitivity": "normal"},
            "g-gone": GraphRequestError(404, {}),
        }
    )
    db = AsyncMock()
    db.get.return_value = None  # brak stanu — pierwszy przebieg
    db.scalars.return_value = _Scalars([private, normal, gone])

    await sync_mod._scrub_old_private_events(
        db, graph, SimpleNamespace(id=5, user_id=9)
    )

    assert private.title == "Spotkanie prywatne"
    assert private.description is None and private.attendees == []
    assert normal.title == "Spotkanie zespołu"
    assert normal.description == "Gabinet 12"
    assert gone.title == "Stare"
    assert graph.urls == [
        "/me/events/g-private",
        "/me/events/g-normal",
        "/me/events/g-gone",
    ]
    # Mniej wierszy niż paczka = koniec — stan zapisany jako zakończony.
    assert _saved_state(db) == {"after_id": 13, "done": True}
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_old_private_scrub_stops_on_graph_failure_and_keeps_cursor() -> None:
    from app.services.m365 import sync as sync_mod
    from app.services.m365.graph_client import GraphRequestError

    first = _existing_row(id=21, external_id="g-a")
    second = _existing_row(id=22, external_id="g-b")
    graph = _EventsGraph(
        {"g-a": {"sensitivity": "private"}, "g-b": GraphRequestError(503, {})}
    )
    db = AsyncMock()
    db.get.return_value = None
    db.scalars.return_value = _Scalars([first, second])
    await sync_mod._scrub_old_private_events(
        db, graph, SimpleNamespace(id=5, user_id=9)
    )
    assert first.title == "Spotkanie prywatne"
    assert second.title == "Wizyta u lekarza"
    assert _saved_state(db) == {"after_id": 21, "done": False}


@pytest.mark.asyncio
async def test_old_private_scrub_is_skipped_once_done() -> None:
    from app.services.m365 import sync as sync_mod

    db = AsyncMock()
    db.get.return_value = SimpleNamespace(value={"after_id": 99, "done": True})
    graph = _EventsGraph({})
    await sync_mod._scrub_old_private_events(
        db, graph, SimpleNamespace(id=5, user_id=9)
    )
    db.scalars.assert_not_awaited()
    assert graph.urls == []


def test_old_private_scrub_selects_only_imported_rows_before_the_window() -> None:
    from app.services.m365 import sync as sync_mod

    sql = str(
        sync_mod._old_private_candidates_stmt(user_id=9, after_id=0).compile(
            dialect=postgresql.dialect()
        )
    )
    assert "calendar_events.operational_owner_id IS NULL" in sql
    assert "calendar_events.start_time <" in sql
    assert "calendar_events.external_source =" in sql
    assert "calendar_events.created_by =" in sql


# ── Pełny odczyt po zmianie $select — jeden, nie co bieg ─────────────────────


class _FailingEventGraph:
    def __init__(self, events):
        self.events = events
        self.calls: list[str] = []

    async def paginate(self, url, params=None):
        self.calls.append(url)
        yield {"value": self.events, "@odata.deltaLink": "https://graph/new-delta"}


async def _boom(*_args, **_kwargs):
    raise ValueError("value too long for type character varying(500)")


@pytest.mark.asyncio
async def test_forced_full_read_with_a_broken_normal_event_is_done_once(
    monkeypatch,
) -> None:
    from app.services.m365 import sync as sync_mod

    monkeypatch.setattr(sync_mod, "_upsert_event", _boom)
    conn = SimpleNamespace(id=5, delta_token_events="https://graph/old-delta")
    db = AsyncMock()
    db.get.return_value = None  # reset jeszcze nie zrobiony
    graph = _FailingEventGraph([{"id": "e1", "sensitivity": "normal"}])
    result = sync_mod.SyncResult(connection_id=5)
    await sync_mod._sync_events(db, graph, conn, result)

    assert result.errors == 1
    assert graph.calls == ["/me/calendarView/delta"]
    # Pełny odczyt się zakończył: nowy kursor + znacznik, następny bieg = delta.
    assert conn.delta_token_events == "https://graph/new-delta"
    db.execute.assert_awaited_once()


@pytest.mark.parametrize("sensitivity", ["private", None])
@pytest.mark.asyncio
async def test_forced_full_read_repeats_when_a_private_event_failed(
    monkeypatch, sensitivity
) -> None:
    from app.services.m365 import sync as sync_mod

    monkeypatch.setattr(sync_mod, "_upsert_event", _boom)
    conn = SimpleNamespace(id=5, delta_token_events="https://graph/old-delta")
    db = AsyncMock()
    db.get.return_value = None
    graph = _FailingEventGraph([{"id": "e1", "sensitivity": sensitivity}])
    await sync_mod._sync_events(db, graph, conn, sync_mod.SyncResult(connection_id=5))
    # Prywatne (albo nieznane) wydarzenie mogło zostać z treścią — bez znacznika.
    assert conn.delta_token_events == "https://graph/old-delta"
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_initial_full_read_with_errors_still_does_not_store_cursor(
    monkeypatch,
) -> None:
    from app.services.m365 import sync as sync_mod

    monkeypatch.setattr(sync_mod, "_upsert_event", _boom)
    conn = SimpleNamespace(id=5, delta_token_events=None)
    db = AsyncMock()
    db.get.return_value = None
    graph = _FailingEventGraph([{"id": "e1", "sensitivity": "normal"}])
    await sync_mod._sync_events(db, graph, conn, sync_mod.SyncResult(connection_id=5))
    assert conn.delta_token_events is None
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_old_private_scrub_runs_only_after_the_select_reset(monkeypatch) -> None:
    from app.services.m365 import sync as sync_mod

    scrub = AsyncMock()
    monkeypatch.setattr(sync_mod, "_scrub_old_private_events", scrub)
    for done, expected in ((False, 0), (True, 1)):
        scrub.reset_mock()
        conn = SimpleNamespace(id=5, user_id=9, delta_token_events="https://graph/d")
        db = AsyncMock()
        db.get.return_value = (
            SimpleNamespace(value={"connection_ids": [5]}) if done else None
        )
        graph = _FailingEventGraph([])
        await sync_mod._sync_events(
            db, graph, conn, sync_mod.SyncResult(connection_id=5)
        )
        assert scrub.await_count == expected
