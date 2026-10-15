"""Zdarzenia API v1 (0448): listener ORM, kanał ``GET /events`` i webhooki.

Dwie warstwy:

* bez bazy — budowa zdarzeń z obiektów flusha, listener na SQLite (ten sam
  ``after_flush`` i SAVEPOINT co na Postgresie: zmiana biznesowa przeżywa brak
  poczekalni), ochrona SSRF, podpis, odstępy ponowień, wysyłka przez
  ``httpx.MockTransport`` (połączenie na sprawdzony adres IP, SNI dla hosta);
* Postgres (CI) — widoczność kanału po scope'ach, webhooki tylko własnego
  konta, sekret pokazany raz (paragon bez sekretu), dostarczenie z kursorem,
  seria porażek i włączenie udaną próbą, odczyt admina.

Dane zmyślone (repo publiczne). Adresy webhooków: domeny ``.example``
z podmienionym DNS — testy nie wychodzą do sieci.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
from sqlalchemy import Enum as SAEnum
from sqlalchemy import Integer, String, create_engine, event, select, text
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
)
from sqlalchemy.orm.attributes import set_committed_value

from app.models.application_screening import ApplicationScreening
from app.models.application_submission import ApplicationSubmission
from app.models.candidate import Candidate
from app.models.contract import Contract, ContractStatus
from app.models.integration_event import IntegrationEvent, IntegrationWebhook
from app.models.invoice import InvoiceStatus
from app.models.job import Job, JobStatus
from app.models.note import Note
from app.models.order_change_event import OrderChangeEvent
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.recruitment_process import RecruitmentProcess
from app.services import integration_events as ie
from app.services import integration_webhooks as wh

PUBLIC_V4 = "93.184.215.14"
PUBLIC_V6 = "2606:2800:21f:cb07:6820:80da:af6b:8b2c"


# ═════════════════════════════════════════════════════════════════════════════
# Bez bazy
# ═════════════════════════════════════════════════════════════════════════════


class TestCatalog:
    def test_every_type_maps_to_a_real_scope(self) -> None:
        from app.models.service_account import ServiceScope

        known = {scope.value for scope in ServiceScope}
        assert set(ie.EVENT_TYPES.values()) <= known
        assert ie.TEST_EVENT_TYPE not in ie.EVENT_TYPES

    def test_visible_types_follow_scopes(self) -> None:
        assert set(ie.visible_types({"recruitments:read"})) == {
            "card.moved",
            "recruitment.created",
            "recruitment.closed",
            "recruitment.reopened",
        }
        assert ie.visible_types({"events:read", "webhooks:manage"}) == []
        assert set(ie.visible_types({"invoices:read", "md:read"})) == {
            "invoice.created",
            "invoice.updated",
            "md_import.created",
        }


def _persistent_like(obj: Any, **committed: Any) -> Any:
    """Obiekt z „wczytanymi” wartościami — kolejne ustawienie daje historię."""
    for key, value in committed.items():
        set_committed_value(obj, key, value)
    return obj


class TestCollectFlushEvents:
    def test_created_rows_carry_ids_only(self) -> None:
        objects = [
            Candidate(id=11, name="Ala", lastname="Zmyślona", email="a@example.com"),
            CandidateStage(
                id=31, candidate_id=11, job_id=21, stage=PipelineStage.verified
            ),
            Note(id=41, content="Treść z danymi osobowymi", candidate_id=11, job_id=21),
            Job(id=21, title="Rekrutacja testowa"),
            OrderChangeEvent(
                id=51, order_id=61, contract_id=71, client_id=81, field="end_date"
            ),
        ]
        rows = ie.collect_flush_events(objects, [])
        by_type = {row["type"]: row for row in rows}
        assert by_type["candidate.created"]["refs"] == {"candidate_id": 11}
        assert by_type["candidate.created"]["scope"] == "candidates:read"
        assert by_type["card.moved"]["refs"] == {
            "candidate_id": 11,
            "job_id": 21,
            "stage": "verified",
            "stage_entry_id": 31,
        }
        assert by_type["note.created"]["refs"] == {
            "note_id": 41,
            "candidate_id": 11,
            "job_id": 21,
            "contract_id": None,
        }
        assert by_type["recruitment.created"]["refs"] == {"job_id": 21}
        assert by_type["order.changed"]["refs"]["order_id"] == 61
        assert by_type["order.changed"]["scope"] == "orders:read"
        # Żadnych treści, nazwisk ani adresów — same identyfikatory.
        dumped = json.dumps(rows)
        assert "Zmyślona" not in dumped and "Treść" not in dumped
        assert "example.com" not in dumped

    def test_job_close_and_reopen(self) -> None:
        job = _persistent_like(Job(), id=5, status=JobStatus.published)
        job.status = JobStatus.closed
        assert [r["type"] for r in ie.collect_flush_events([], [job])] == [
            "recruitment.closed"
        ]
        reopened = _persistent_like(Job(), id=5, status=JobStatus.closed)
        reopened.status = JobStatus.published
        assert [r["type"] for r in ie.collect_flush_events([], [reopened])] == [
            "recruitment.reopened"
        ]

    def test_same_value_or_other_column_is_not_an_event(self) -> None:
        job = _persistent_like(Job(), id=5, status=JobStatus.closed, title="A")
        job.status = JobStatus.closed
        job.title = "B"
        assert ie.collect_flush_events([], [job]) == []

    def test_unknown_previous_status_closes_but_never_reopens(self) -> None:
        closing = _persistent_like(Job(), id=6)
        closing.status = JobStatus.closed
        assert [r["type"] for r in ie.collect_flush_events([], [closing])] == [
            "recruitment.closed"
        ]
        opening = _persistent_like(Job(), id=7)
        opening.status = JobStatus.published
        assert ie.collect_flush_events([], [opening]) == []

    def test_contract_status_change_has_previous_status(self) -> None:
        contract = _persistent_like(Contract(), id=9, status=ContractStatus.active)
        contract.status = ContractStatus.ended
        (row,) = ie.collect_flush_events([], [contract])
        assert row["type"] == "contract.status_changed"
        assert row["refs"] == {
            "contract_id": 9,
            "status": "ended",
            "previous_status": "active",
        }

    def test_one_broken_object_does_not_drop_the_rest(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        original = ie._created_events

        def flaky(obj: Any, table: str) -> list:
            if table == "notes":
                raise RuntimeError("zepsute")
            return original(obj, table)

        monkeypatch.setattr(ie, "_created_events", flaky)
        with caplog.at_level(logging.ERROR, logger=ie.__name__):
            rows = ie.collect_flush_events(
                [Note(id=1, content="x"), Candidate(id=2, name="A", lastname="B")], []
            )
        assert [r["type"] for r in rows] == ["candidate.created"]
        assert "notes" in caplog.text and "RuntimeError" in caplog.text


def _process(entry_source=None, **values) -> RecruitmentProcess:
    base = {
        "id": 90,
        "candidate_id": 11,
        "job_id": 21,
        "legacy_current_candidate_stage_id": 31,
        "entry_source": entry_source,
    }
    return _persistent_like(RecruitmentProcess(), **{**base, **values})


def _types(rows: list[dict]) -> list[str]:
    return [row["type"] for row in rows]


class TestApplicationReceived:
    """Dwie drogi zgłoszenia z linku (korekta koordynatora 15.10.2026)."""

    def test_new_email_process_stamped_after_insert(self) -> None:
        # ``transition_process``: etap i proces już zapisane, źródło wejścia
        # stemplowane UPDATE-em w kolejnym flushu.
        process = _process()
        process.entry_source = "application"
        stage = CandidateStage(
            id=32, candidate_id=11, job_id=21, stage=PipelineStage.new
        )
        rows = ie.collect_flush_events([stage], [process])
        assert _types(rows) == ["card.moved", "application.received"]
        (app_row,) = [r for r in rows if r["type"] == "application.received"]
        assert app_row["scope"] == "applications:read"
        assert app_row["refs"] == {
            "application_id": None,
            "candidate_id": 11,
            "job_id": 21,
            "stage_id": 31,
        }

    def test_process_inserted_with_application_source(self) -> None:
        process = RecruitmentProcess(
            id=91,
            candidate_id=12,
            job_id=22,
            legacy_current_candidate_stage_id=33,
            entry_source="application",
        )
        (row,) = ie.collect_flush_events([process], [])
        assert row["type"] == "application.received"
        assert row["refs"]["candidate_id"] == 12

    def test_other_entry_sources_are_not_applications(self) -> None:
        for source in ("added_manual", "auto_match", "reassign"):
            process = _process()
            process.entry_source = source
            assert ie.collect_flush_events([], [process]) == []
        unchanged = _process(entry_source="application", candidate_id=13)
        unchanged.job_id = 23  # inna kolumna, źródło bez zmian
        assert ie.collect_flush_events([], [unchanged]) == []

    def test_known_email_submission_carries_the_event(self) -> None:
        submission = ApplicationSubmission(id=7, job_id=21, matched_candidate_id=11)
        (row,) = ie.collect_flush_events([submission], [])
        assert row["refs"] == {
            "application_id": 7,
            "candidate_id": 11,
            "job_id": 21,
            "stage_id": None,
        }

    def test_one_apply_with_both_rows_gives_one_event(self) -> None:
        submission = ApplicationSubmission(id=8, job_id=21, matched_candidate_id=11)
        process = _process()
        process.entry_source = "application"
        rows = ie.collect_flush_events([submission], [process])
        assert _types(rows) == ["application.received"]
        assert rows[0]["refs"]["application_id"] == 8

    def test_submission_flushed_earlier_still_suppresses(self) -> None:
        # Zgłoszenie zapisane wcześniejszym flushem (albo rozpatrywane, wciąż
        # bez dopasowanej osoby) leży w mapie tożsamości sesji.
        process = _process()
        process.entry_source = "application"
        for matched in (11, None):
            loaded = _persistent_like(
                ApplicationSubmission(), id=9, job_id=21, matched_candidate_id=matched
            )
            assert (
                ie.collect_flush_events([], [process], session_objects=[loaded]) == []
            )
        other_job = _persistent_like(
            ApplicationSubmission(), id=10, job_id=99, matched_candidate_id=11
        )
        assert _types(
            ie.collect_flush_events([], [process], session_objects=[other_job])
        ) == ["application.received"]

    def test_ai_screening_of_known_email_does_not_repeat_the_event(self) -> None:
        process = _process()
        process.entry_source = "application"
        known = _persistent_like(
            ApplicationScreening(), id=1, candidate_id=11, job_id=21, submission_id=7
        )
        assert ie.collect_flush_events([], [process], session_objects=[known]) == []
        new_email = _persistent_like(
            ApplicationScreening(), id=2, candidate_id=11, job_id=21, submission_id=None
        )
        assert _types(
            ie.collect_flush_events([], [process], session_objects=[new_email])
        ) == ["application.received"]

    def test_same_pair_twice_in_one_flush_is_one_event(self) -> None:
        first = _process()
        first.entry_source = "application"
        second = _process(id=92)
        second.entry_source = "application"
        assert _types(ie.collect_flush_events([], [first, second])) == [
            "application.received"
        ]


# ── Listener na prawdziwym flushu (SQLite) ──────────────────────────────────


class _Base(DeclarativeBase):
    pass


class _Candidate(_Base):
    __tablename__ = "candidates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), default="x")


class _Job(_Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[JobStatus] = mapped_column(
        SAEnum(JobStatus), default=JobStatus.published
    )


class _Invoice(_Base):
    __tablename__ = "invoices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_id: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[InvoiceStatus] = mapped_column(
        SAEnum(InvoiceStatus), default=InvoiceStatus.issued
    )
    notes: Mapped[str] = mapped_column(String(50), default="")


class _Process(_Base):
    __tablename__ = "recruitment_processes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(Integer, default=1)
    job_id: Mapped[int] = mapped_column(Integer, default=1)
    legacy_current_candidate_stage_id: Mapped[int] = mapped_column(Integer, default=5)
    entry_source: Mapped[str] = mapped_column(String(24), nullable=True)


_OUTBOX_DDL = (
    "CREATE TABLE integration_event_outbox (id INTEGER PRIMARY KEY, "
    "type TEXT NOT NULL, scope TEXT NOT NULL, refs TEXT NOT NULL DEFAULT '{}', "
    "occurred_at TEXT DEFAULT CURRENT_TIMESTAMP)"
)


def _sqlite(with_outbox: bool = True):
    engine = create_engine("sqlite://")

    # Przepis SQLAlchemy na prawdziwe SAVEPOINT-y w pysqlite.
    @event.listens_for(engine, "connect")
    def _connect(dbapi_connection, _record) -> None:
        dbapi_connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def _begin(conn) -> None:
        conn.exec_driver_sql("BEGIN")

    _Base.metadata.create_all(engine)
    if with_outbox:
        with engine.begin() as conn:
            conn.exec_driver_sql(_OUTBOX_DDL)
    return engine


def _outbox(engine) -> list[tuple[str, dict]]:
    with engine.connect() as conn:
        rows = conn.exec_driver_sql(
            "SELECT type, refs FROM integration_event_outbox ORDER BY id"
        ).fetchall()
    return [(row[0], json.loads(row[1])) for row in rows]


class TestListenerOnFlush:
    def test_events_are_written_in_the_same_transaction(self) -> None:
        engine = _sqlite()
        with Session(engine, expire_on_commit=False) as session:
            session.add_all([_Candidate(), _Job()])
            session.commit()
            job = session.get(_Job, 1)
            job.status = JobStatus.closed
            session.commit()
            job.status = JobStatus.published
            session.commit()
        assert _outbox(engine) == [
            ("candidate.created", {"candidate_id": 1}),
            ("recruitment.created", {"job_id": 1}),
            ("recruitment.closed", {"job_id": 1}),
            ("recruitment.reopened", {"job_id": 1}),
        ]

    def test_application_stamp_in_a_later_flush(self) -> None:
        engine = _sqlite()
        with Session(engine, expire_on_commit=False) as session:
            process = _Process()
            session.add(process)
            session.flush()
            process.entry_source = "application"
            session.flush()
            session.commit()
        assert _outbox(engine) == [
            (
                "application.received",
                {
                    "application_id": None,
                    "candidate_id": 1,
                    "job_id": 1,
                    "stage_id": 5,
                },
            )
        ]

    def test_rollback_takes_the_event_with_it(self) -> None:
        engine = _sqlite()
        with Session(engine) as session:
            session.add(_Candidate())
            session.flush()
            session.rollback()
        assert _outbox(engine) == []

    def test_invoice_update_only_on_real_change(self) -> None:
        engine = _sqlite()
        with Session(engine, expire_on_commit=False) as session:
            invoice = _Invoice()
            session.add(invoice)
            session.commit()
            invoice.status = InvoiceStatus.issued  # ta sama wartość
            session.commit()
            invoice.status = InvoiceStatus.paid
            session.commit()
        assert [t for t, _ in _outbox(engine)] == ["invoice.created", "invoice.updated"]
        assert _outbox(engine)[1][1] == {
            "invoice_id": 1,
            "contract_id": 1,
            "status": "paid",
        }

    def test_missing_outbox_never_breaks_the_business_write(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        engine = _sqlite(with_outbox=False)
        with caplog.at_level(logging.ERROR, logger=ie.__name__):
            with Session(engine) as session:
                session.add(_Candidate(name="zostaje"))
                session.commit()
                # Sesja zdrowa po wycofanym savepoincie — kolejny zapis też wchodzi.
                session.add(_Candidate(name="drugi"))
                session.commit()
        with engine.connect() as conn:
            names = conn.exec_driver_sql(
                "SELECT name FROM candidates ORDER BY id"
            ).fetchall()
        assert [n for (n,) in names] == ["zostaje", "drugi"]
        assert "zdarzenia pominięte" in caplog.text

    def test_unwatched_tables_cost_nothing(self) -> None:
        engine = _sqlite()

        statements: list[str] = []

        @event.listens_for(engine, "before_cursor_execute")
        def _count(_c, _cur, statement, *_a, **_k) -> None:
            statements.append(statement)

        class _Other(_Base):
            __tablename__ = "integration_test_other"
            id: Mapped[int] = mapped_column(Integer, primary_key=True)

        _Other.__table__.create(engine)
        statements.clear()
        with Session(engine) as session:
            session.add(_Other())
            session.commit()
        assert not any("SAVEPOINT" in s or "integration_event" in s for s in statements)


# ── Adres webhooka i SSRF ───────────────────────────────────────────────────


class TestWebhookUrl:
    @pytest.mark.parametrize(
        "url,code",
        [
            ("http://hooks.example/x", "webhook_url_not_https"),
            ("ftp://hooks.example/x", "webhook_url_not_https"),
            ("https://user:pass@hooks.example/x", "invalid_webhook_url"),
            ("https://hooks.example:8443/x", "webhook_url_port"),
            ("https://hooks.example/x#frag", "invalid_webhook_url"),
            ("https:///x", "invalid_webhook_url"),
            ("https://hooks example/x", "invalid_webhook_url"),
            ("", "invalid_webhook_url"),
            ("https://a.example/" + "x" * 2100, "invalid_webhook_url"),
        ],
    )
    def test_static_rejections(self, url: str, code: str) -> None:
        with pytest.raises(wh.WebhookUrlError) as exc:
            wh.parse_webhook_url(url)
        assert exc.value.code == code

    def test_normalized_target(self) -> None:
        target = wh.parse_webhook_url("HTTPS://Hooks.Example:443/in?token=abc")
        assert target.url == "https://hooks.example/in?token=abc"
        assert (target.host, target.port, target.is_ip_literal) == (
            "hooks.example",
            443,
            False,
        )
        assert wh.parse_webhook_url("https://zażółć.example/").host.startswith("xn--")

    @pytest.mark.parametrize(
        "ip",
        [
            "127.0.0.1",
            "10.1.2.3",
            "172.16.0.5",
            "192.168.1.1",
            "169.254.169.254",
            "100.64.0.1",
            "0.0.0.0",
            "224.0.0.1",
            "255.255.255.255",
            "::1",
            "fe80::1",
            "fc00::1",
            "::ffff:127.0.0.1",
            "::ffff:10.0.0.1",
            "2002:7f00:1::1",
            "64:ff9b::7f00:1",
            "64:ff9b::a00:1",
            "fec0::1",
            "2001:0:4136:e378:8000:63bf:3fff:fdd2",
            "not-an-ip",
        ],
    )
    def test_non_public_addresses(self, ip: str) -> None:
        assert wh.is_public_address(ip) is False

    @pytest.mark.parametrize(
        "ip", [PUBLIC_V4, "8.8.8.8", PUBLIC_V6, "64:ff9b::808:808"]
    )
    def test_public_addresses(self, ip: str) -> None:
        assert wh.is_public_address(ip) is True

    async def test_any_private_answer_blocks_the_host(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake(host: str, port: int) -> list[str]:
            return [PUBLIC_V4, "10.0.0.7"]

        monkeypatch.setattr(wh, "_resolve", fake)
        with pytest.raises(wh.WebhookUrlError) as exc:
            await wh.validate_webhook_url("https://rebind.example/hook")
        assert exc.value.code == "webhook_url_not_public"

    async def test_literal_private_ip_is_blocked_without_dns(self) -> None:
        with pytest.raises(wh.WebhookUrlError) as exc:
            await wh.validate_webhook_url("https://127.0.0.1/hook")
        assert exc.value.code == "webhook_url_not_public"

    async def test_dns_failure_is_a_clear_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake(host: str, port: int) -> list[str]:
            raise OSError("nxdomain")

        monkeypatch.setattr(wh, "_resolve", fake)
        with pytest.raises(wh.WebhookUrlError) as exc:
            await wh.validate_webhook_url("https://missing.example/")
        assert exc.value.code == "webhook_url_unresolvable"

    async def test_ipv4_goes_first(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake(host: str, port: int) -> list[str]:
            return [PUBLIC_V6, PUBLIC_V4]

        monkeypatch.setattr(wh, "_resolve", fake)
        target = wh.parse_webhook_url("https://dual.example/")
        assert await wh.resolve_public_addresses(target) == [PUBLIC_V4, PUBLIC_V6]

    def test_display_url_hides_query(self) -> None:
        assert (
            wh.display_url("https://hooks.example/catch/1?token=secret")
            == "https://hooks.example/catch/1?…"
        )
        assert wh.display_url("https://hooks.example/in") == "https://hooks.example/in"


# ── Podpis, treść, odstępy ──────────────────────────────────────────────────


class TestSignatureAndBackoff:
    def test_signature_is_hmac_sha256_of_raw_body(self) -> None:
        body = wh.build_body(3, [{"id": 1}], datetime(2041, 1, 1, tzinfo=timezone.utc))
        expected = hmac.new(b"whsec_x", body, hashlib.sha256).hexdigest()
        assert wh.sign("whsec_x", body) == f"sha256={expected}"
        assert json.loads(body) == {
            "webhook_id": 3,
            "sent_at": "2041-01-01T00:00:00+00:00",
            "events": [{"id": 1}],
        }

    def test_secret_shape_and_encryption_roundtrip(self) -> None:
        secret = wh.new_secret()
        assert secret.startswith("whsec_") and len(secret) > 40
        ciphertext = wh.encrypt_secret(secret)
        assert secret not in ciphertext
        assert wh.decrypt_secret(ciphertext) == secret

    def test_backoff_grows_and_caps(self) -> None:
        assert [wh.backoff_seconds(n) for n in (1, 2, 3, 4)] == [30, 60, 120, 240]
        assert wh.backoff_seconds(8) == 3600
        assert wh.backoff_seconds(50) == 3600
        total = sum(
            wh.backoff_seconds(n) for n in range(1, wh.MAX_CONSECUTIVE_FAILURES)
        )
        assert 8 * 3600 < total < 24 * 3600


# ── Wysyłka (MockTransport, bez sieci) ──────────────────────────────────────


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=False
    )


@pytest.fixture
def public_dns(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    asked: list[str] = []

    async def fake(host: str, port: int) -> list[str]:
        asked.append(host)
        return [PUBLIC_V4]

    monkeypatch.setattr(wh, "_resolve", fake)
    return asked


class TestPostSigned:
    async def test_pins_validated_ip_and_signs(self, public_dns: list[str]) -> None:
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["host"] = request.url.host
            seen["host_header"] = request.headers["host"]
            seen["sni"] = request.extensions.get("sni_hostname")
            seen["signature"] = request.headers[wh.SIGNATURE_HEADER]
            seen["event_id"] = request.headers[wh.EVENT_ID_HEADER]
            seen["body"] = request.content
            return httpx.Response(204)

        body = wh.build_body(1, [{"id": 7}], datetime.now(timezone.utc))
        async with _mock_client(handler) as client:
            result = await wh.post_signed(
                client,
                url="https://hooks.example/in?k=1",
                secret="whsec_abc",
                webhook_id=1,
                last_event_id=7,
                body=body,
            )
        assert result == wh.DeliveryResult(True, 204, None)
        assert seen["host"] == PUBLIC_V4
        assert seen["host_header"] == "hooks.example"
        assert seen["sni"] == "hooks.example"
        assert seen["event_id"] == "7"
        assert seen["body"] == body
        assert seen["signature"] == wh.sign("whsec_abc", body)
        assert public_dns == ["hooks.example"]

    @pytest.mark.parametrize(
        "status,error",
        [(302, "redirect_not_followed"), (500, "http_500"), (410, "http_410")],
    )
    async def test_non_2xx_is_a_failure(
        self, public_dns: list[str], status: int, error: str
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status, headers={"location": "http://127.0.0.1/"})

        async with _mock_client(handler) as client:
            result = await wh.post_signed(
                client,
                url="https://hooks.example/",
                secret="s",
                webhook_id=1,
                last_event_id=1,
                body=b"{}",
            )
        assert result == wh.DeliveryResult(False, status, error)

    async def test_timeout_and_network_errors(self, public_dns: list[str]) -> None:
        def slow(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("wolno", request=request)

        def refused(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("odmowa", request=request)

        for handler, error in ((slow, "timeout"), (refused, "network:ConnectError")):
            async with _mock_client(handler) as client:
                result = await wh.post_signed(
                    client,
                    url="https://hooks.example/",
                    secret="s",
                    webhook_id=1,
                    last_event_id=1,
                    body=b"{}",
                )
            assert result == wh.DeliveryResult(False, None, error)

    async def test_rebinding_to_private_at_send_time_is_blocked(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def rebound(host: str, port: int) -> list[str]:
            return ["169.254.169.254"]

        monkeypatch.setattr(wh, "_resolve", rebound)
        called = []

        def handler(request: httpx.Request) -> httpx.Response:
            called.append(request)
            return httpx.Response(200)

        async with _mock_client(handler) as client:
            result = await wh.post_signed(
                client,
                url="https://hooks.example/",
                secret="s",
                webhook_id=1,
                last_event_id=1,
                body=b"{}",
            )
        assert result == wh.DeliveryResult(False, None, "webhook_url_not_public")
        assert called == []


# ═════════════════════════════════════════════════════════════════════════════
# Postgres (CI)
# ═════════════════════════════════════════════════════════════════════════════

V1 = "/api/integrations/v1"


def _h(api_key: str, idem: str | None = None) -> dict:
    out = {"X-API-Key": api_key}
    if idem is not None:
        out["Idempotency-Key"] = idem
    return out


async def _key(app_client, headers: dict, scopes: list[str]) -> tuple[dict, str]:
    from tests.test_service_accounts import _account_with_key

    account, api_key, _ = await _account_with_key(app_client, headers, scopes)
    return account, api_key


async def _publish_all(db) -> int:
    """Cała poczekalnia do kanału — w CI leżą w niej zdarzenia całego przebiegu."""
    total = 0
    while True:
        moved = await ie.publish_pending(db)
        total += moved
        if moved == 0:
            return total


async def _seed_events(rows: list[tuple[str, dict]]) -> list[int]:
    """Zdarzenia wprost do kanału (z pominięciem poczekalni)."""
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        objects = [
            IntegrationEvent(
                type=event_type,
                scope=ie.EVENT_TYPES[event_type],
                refs=refs,
                occurred_at=datetime.now(timezone.utc),
            )
            for event_type, refs in rows
        ]
        db.add_all(objects)
        await db.commit()
        return [obj.id for obj in objects]


async def _create_webhook(
    app_client, api_key: str, url: str = "https://hooks.example/in", **extra
) -> tuple[Any, str]:
    resp = await app_client.post(
        f"{V1}/webhooks",
        headers=_h(api_key, str(uuid.uuid4())),
        json={"url": url, **extra},
    )
    return resp, url


_FEED_SCOPES = ["events:read", "webhooks:manage"]


@pytest.mark.asyncio
class TestFeed:
    async def test_listener_event_reaches_feed_only_with_scope(
        self, app_client, app_auth_headers: dict
    ) -> None:
        from app.core.database import AsyncSessionLocal

        _, sees = await _key(
            app_client, app_auth_headers, ["events:read", "candidates:read"]
        )
        _, blind = await _key(
            app_client, app_auth_headers, ["events:read", "recruitments:read"]
        )
        async with AsyncSessionLocal() as db:
            start = await ie.current_cursor(db)
            u = uuid.uuid4().hex[:8]
            cand = Candidate(
                name="Ola", lastname=f"Zdarzenie-{u}", email=f"ev-{u}@example.com"
            )
            db.add(cand)
            await db.commit()
            outbox = (
                await db.execute(
                    text(
                        "SELECT count(*) FROM integration_event_outbox "
                        "WHERE type = 'candidate.created' "
                        "AND (refs->>'candidate_id')::int = :cid"
                    ),
                    {"cid": cand.id},
                )
            ).scalar()
            assert outbox == 1
            await _publish_all(db)

        resp = await app_client.get(
            f"{V1}/events", params={"after": start, "limit": 500}, headers=_h(sees)
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        mine = [e for e in body["items"] if e["refs"].get("candidate_id") == cand.id]
        assert [e["type"] for e in mine] == ["candidate.created"]
        assert body["next_after"] >= mine[0]["id"]

        resp = await app_client.get(
            f"{V1}/events", params={"after": start, "limit": 500}, headers=_h(blind)
        )
        assert resp.status_code == 200, resp.text
        assert all(e["type"] != "candidate.created" for e in resp.json()["items"])
        # Kursor przeskakuje zdarzenia niewidoczne dla klucza.
        assert resp.json()["next_after"] >= mine[0]["id"]

    async def test_types_filter_paging_and_unknown_type(
        self, app_client, app_auth_headers: dict
    ) -> None:
        _, api_key = await _key(
            app_client, app_auth_headers, ["events:read", "recruitments:read"]
        )
        from app.core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            start = await ie.current_cursor(db)
        marker = int(uuid.uuid4().int % 1_000_000_000)
        ids = await _seed_events(
            [
                ("recruitment.created", {"job_id": marker}),
                ("card.moved", {"job_id": marker, "candidate_id": 1}),
                ("recruitment.closed", {"job_id": marker}),
            ]
        )
        resp = await app_client.get(
            f"{V1}/events",
            params={"after": start, "types": "recruitment.created,recruitment.closed"},
            headers=_h(api_key),
        )
        assert resp.status_code == 200, resp.text
        got = [
            e["id"] for e in resp.json()["items"] if e["refs"].get("job_id") == marker
        ]
        assert got == [ids[0], ids[2]]

        page = await app_client.get(
            f"{V1}/events",
            params={"after": ids[0] - 1, "limit": 1},
            headers=_h(api_key),
        )
        assert page.json()["has_more"] is True
        assert page.json()["next_after"] == page.json()["items"][0]["id"]

        bad = await app_client.get(
            f"{V1}/events", params={"types": "candidate.deleted"}, headers=_h(api_key)
        )
        assert bad.status_code == 422, bad.text
        assert bad.json()["error"]["code"] == "unknown_event_type"

    async def test_scopes_guard_the_routes(
        self, app_client, app_auth_headers: dict
    ) -> None:
        _, no_events = await _key(app_client, app_auth_headers, ["candidates:read"])
        assert (
            await app_client.get(f"{V1}/events", headers=_h(no_events))
        ).status_code == 403
        assert (
            await app_client.get(f"{V1}/webhooks", headers=_h(no_events))
        ).status_code == 403
        user_jwt = await app_client.get(f"{V1}/events", headers=app_auth_headers)
        assert user_jwt.status_code == 401


@pytest.mark.asyncio
class TestWebhookRoutes:
    async def test_secret_is_shown_once_and_never_stored_plain(
        self, app_client, app_auth_headers: dict, public_dns: list[str]
    ) -> None:
        from app.core.database import AsyncSessionLocal
        from app.models.integration_write_receipt import IntegrationWriteReceipt

        account, api_key = await _key(app_client, app_auth_headers, _FEED_SCOPES)
        idem = str(uuid.uuid4())
        payload = {"url": "https://hooks.example/in?token=t1"}
        first = await app_client.post(
            f"{V1}/webhooks", headers=_h(api_key, idem), json=payload
        )
        assert first.status_code == 201, first.text
        secret = first.json()["secret"]
        assert secret.startswith("whsec_")
        assert first.json()["secret_redacted"] is False

        replay = await app_client.post(
            f"{V1}/webhooks", headers=_h(api_key, idem), json=payload
        )
        assert replay.status_code == 201
        assert replay.headers.get("Idempotent-Replayed") == "true"
        assert replay.json()["secret"] is None
        assert replay.json()["secret_redacted"] is True
        assert replay.json()["webhook"]["id"] == first.json()["webhook"]["id"]

        listed = await app_client.get(f"{V1}/webhooks", headers=_h(api_key))
        assert secret not in listed.text

        async with AsyncSessionLocal() as db:
            receipts = (
                await db.scalars(
                    select(IntegrationWriteReceipt.response_json).where(
                        IntegrationWriteReceipt.service_account_id == account["id"]
                    )
                )
            ).all()
            hook = await db.get(IntegrationWebhook, first.json()["webhook"]["id"])
        assert receipts and all(secret not in json.dumps(r) for r in receipts)
        assert secret not in hook.secret_ct
        assert wh.decrypt_secret(hook.secret_ct) == secret

    async def test_other_accounts_webhooks_are_404(
        self, app_client, app_auth_headers: dict, public_dns: list[str]
    ) -> None:
        _, owner = await _key(app_client, app_auth_headers, _FEED_SCOPES)
        _, other = await _key(app_client, app_auth_headers, _FEED_SCOPES)
        created, _ = await _create_webhook(app_client, owner)
        assert created.status_code == 201, created.text
        hook_id = created.json()["webhook"]["id"]

        assert hook_id not in [
            h["id"]
            for h in (await app_client.get(f"{V1}/webhooks", headers=_h(other))).json()
        ]
        for method, path in (
            ("DELETE", f"/webhooks/{hook_id}"),
            ("POST", f"/webhooks/{hook_id}/test"),
        ):
            resp = await app_client.request(
                method, f"{V1}{path}", headers=_h(other, str(uuid.uuid4()))
            )
            assert resp.status_code == 404, resp.text

        test = await app_client.post(
            f"{V1}/webhooks/{hook_id}/test", headers=_h(owner, str(uuid.uuid4()))
        )
        assert test.status_code == 202, test.text
        listed = (await app_client.get(f"{V1}/webhooks", headers=_h(owner))).json()
        assert [h["test_pending"] for h in listed if h["id"] == hook_id] == [True]

        deleted = await app_client.delete(
            f"{V1}/webhooks/{hook_id}", headers=_h(owner, str(uuid.uuid4()))
        )
        assert deleted.status_code == 200, deleted.text
        assert (await app_client.get(f"{V1}/webhooks", headers=_h(owner))).json() == []

    async def test_registration_rules(
        self, app_client, app_auth_headers: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def private(host: str, port: int) -> list[str]:
            return ["10.0.0.5"] if host == "internal.example" else [PUBLIC_V4]

        monkeypatch.setattr(wh, "_resolve", private)
        _, manage_only = await _key(app_client, app_auth_headers, ["webhooks:manage"])
        resp, _ = await _create_webhook(app_client, manage_only)
        assert resp.status_code == 403
        assert resp.json()["error"]["details"]["missing"] == ["events:read"]

        _, api_key = await _key(
            app_client, app_auth_headers, _FEED_SCOPES + ["orders:read"]
        )
        for url, code in (
            ("http://hooks.example/in", "webhook_url_not_https"),
            ("https://internal.example/in", "webhook_url_not_public"),
            ("https://127.0.0.1/in", "webhook_url_not_public"),
        ):
            resp, _ = await _create_webhook(app_client, api_key, url)
            assert resp.status_code == 422, resp.text
            assert resp.json()["error"]["code"] == code

        resp, _ = await _create_webhook(app_client, api_key, event_types=["card.moved"])
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "event_type_not_visible"
        resp, _ = await _create_webhook(app_client, api_key, event_types=["nope"])
        assert resp.json()["error"]["code"] == "unknown_event_type"

        for _ in range(wh.MAX_WEBHOOKS_PER_ACCOUNT):
            ok, _ = await _create_webhook(
                app_client, api_key, event_types=["order.changed"]
            )
            assert ok.status_code == 201, ok.text
        over, _ = await _create_webhook(app_client, api_key)
        assert over.status_code == 409
        assert over.json()["error"]["code"] == "webhook_limit"

    async def test_admin_sees_webhooks_without_query(
        self, app_client, app_auth_headers: dict, public_dns: list[str]
    ) -> None:
        account, api_key = await _key(app_client, app_auth_headers, _FEED_SCOPES)
        created, _ = await _create_webhook(
            app_client, api_key, "https://hooks.example/catch/9?token=zzz"
        )
        assert created.status_code == 201
        resp = await app_client.get(
            f"/api/settings/service-accounts/{account['id']}/webhooks",
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        (row,) = resp.json()
        assert row["url"] == "https://hooks.example/catch/9?…"
        assert "secret" not in row and "secret_ct" not in row
        assert created.json()["secret"] not in resp.text
        missing = await app_client.get(
            "/api/settings/service-accounts/999999999/webhooks",
            headers=app_auth_headers,
        )
        assert missing.status_code == 404
        no_admin = await app_client.get(
            f"/api/settings/service-accounts/{account['id']}/webhooks",
            headers=_h(api_key),
        )
        assert no_admin.status_code == 401


@pytest.mark.asyncio
class TestDelivery:
    async def _hook(
        self, app_client, app_auth_headers, scopes, **extra
    ) -> tuple[dict, str, int, str]:
        account, api_key = await _key(
            app_client, app_auth_headers, _FEED_SCOPES + scopes
        )
        created, _ = await _create_webhook(app_client, api_key, **extra)
        assert created.status_code == 201, created.text
        body = created.json()
        return account, api_key, body["webhook"]["id"], body["secret"]

    async def test_delivers_visible_events_with_signature_and_advances(
        self, app_client, app_auth_headers: dict, public_dns: list[str]
    ) -> None:
        from app.core.database import AsyncSessionLocal

        _, _, hook_id, secret = await self._hook(
            app_client, app_auth_headers, ["md:read"]
        )
        marker = int(uuid.uuid4().int % 1_000_000_000)
        ids = await _seed_events(
            [
                (
                    "md_import.created",
                    {"md_import_id": marker, "period_month": "2041-01"},
                ),
                ("candidate.created", {"candidate_id": marker}),
            ]
        )
        received: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers[wh.SIGNATURE_HEADER] == wh.sign(
                secret, request.content
            )
            received.append(json.loads(request.content))
            return httpx.Response(200)

        async with _mock_client(handler) as client, AsyncSessionLocal() as db:
            outcome = await wh.deliver_webhook(db, client, hook_id)
        assert outcome == "delivered"
        events = [e for body in received for e in body["events"]]
        assert [e["id"] for e in events if e["refs"].get("md_import_id") == marker] == [
            ids[0]
        ]
        # Bez candidates:read zdarzenie kandydata nie wychodzi.
        assert all(e["type"] != "candidate.created" for e in events)

        async with AsyncSessionLocal() as db:
            hook = await db.get(IntegrationWebhook, hook_id)
            assert hook.last_event_id >= ids[1]
            assert (hook.failure_count, hook.last_status, hook.lease_until) == (
                0,
                200,
                None,
            )

        received.clear()
        async with _mock_client(handler) as client, AsyncSessionLocal() as db:
            assert await wh.deliver_webhook(db, client, hook_id) == "idle"
        assert received == []

    async def test_hidden_client_recruitments_do_not_exist_in_feed_or_webhooks(
        self, app_client, app_auth_headers: dict, public_dns: list[str]
    ) -> None:
        """Jak ``GET /recruitments/{id}`` (404): zdarzenia rekrutacji klienta
        ukrytego albo usuniętego nie wychodzą ani kanałem, ani webhookiem."""
        from app.core.database import AsyncSessionLocal
        from app.models.client import Client

        tag = uuid.uuid4().hex[:8]
        async with AsyncSessionLocal() as db:
            listed = Client(name=f"V1 Zdarzenia klient {tag}")
            hidden = Client(name=f"V1 Zdarzenia ukryty {tag}", hidden=True)
            gone = Client(
                name=f"V1 Zdarzenia usunięty {tag}",
                deleted_at=datetime.now(timezone.utc),
            )
            db.add_all([listed, hidden, gone])
            await db.flush()
            jobs = [
                Job(
                    title=f"Zdarzenia {tag} {n}",
                    client_id=c.id,
                    status=JobStatus.published,
                )
                for n, c in enumerate([listed, hidden, gone])
            ]
            db.add_all(jobs)
            await db.commit()
            visible_id, hidden_id, gone_id = (job.id for job in jobs)

        account, api_key, hook_id, _ = await self._hook(
            app_client, app_auth_headers, ["recruitments:read"]
        )
        async with AsyncSessionLocal() as db:
            start = await ie.current_cursor(db)
        await _seed_events(
            [
                ("recruitment.created", {"job_id": job_id})
                for job_id in (visible_id, hidden_id, gone_id)
            ]
        )

        resp = await app_client.get(
            f"{V1}/events",
            params={"after": start, "limit": 500, "types": "recruitment.created"},
            headers=_h(api_key),
        )
        assert resp.status_code == 200, resp.text
        seen = {e["refs"]["job_id"] for e in resp.json()["items"]}
        assert visible_id in seen
        assert not seen & {hidden_id, gone_id}

        received: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            received.append(json.loads(request.content))
            return httpx.Response(200)

        async with AsyncSessionLocal() as db:
            hook = await db.get(IntegrationWebhook, hook_id)
            hook.last_event_id = start
            await db.commit()
        async with _mock_client(handler) as client, AsyncSessionLocal() as db:
            assert await wh.deliver_webhook(db, client, hook_id) == "delivered"
        delivered = {
            e["refs"].get("job_id") for body in received for e in body["events"]
        }
        assert visible_id in delivered
        assert not delivered & {hidden_id, gone_id}

    async def test_failures_back_off_disable_and_test_reenables(
        self, app_client, app_auth_headers: dict, public_dns: list[str]
    ) -> None:
        from app.core.database import AsyncSessionLocal

        _, api_key, hook_id, _ = await self._hook(
            app_client, app_auth_headers, ["md:read"]
        )
        await _seed_events(
            [("md_import.created", {"md_import_id": 1, "period_month": "2041-02"})]
        )

        def down(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503)

        now = datetime.now(timezone.utc)
        async with _mock_client(down) as client, AsyncSessionLocal() as db:
            assert await wh.deliver_webhook(db, client, hook_id, now=now) == "failed"
            hook = await db.get(IntegrationWebhook, hook_id, populate_existing=True)
            cursor = hook.last_event_id
            assert (hook.failure_count, hook.last_error) == (1, "http_503")
            assert hook.next_attempt_at == now + timedelta(seconds=30)
            # W odstępie nic nie wychodzi.
            assert await wh.deliver_webhook(db, client, hook_id, now=now) == "skipped"

            hook.failure_count = wh.MAX_CONSECUTIVE_FAILURES - 1
            hook.next_attempt_at = None
            await db.commit()
            assert await wh.deliver_webhook(db, client, hook_id) == "failed"
            hook = await db.get(IntegrationWebhook, hook_id, populate_existing=True)
            assert hook.is_active is False and hook.disabled_reason
            assert hook.last_event_id == cursor  # porażka nie przesuwa kursora

        resp = await app_client.post(
            f"{V1}/webhooks/{hook_id}/test", headers=_h(api_key, str(uuid.uuid4()))
        )
        assert resp.status_code == 202, resp.text
        seen: list[dict] = []

        def up(request: httpx.Request) -> httpx.Response:
            seen.append(json.loads(request.content))
            return httpx.Response(204)

        async with _mock_client(up) as client, AsyncSessionLocal() as db:
            assert await wh.deliver_webhook(db, client, hook_id) == "delivered"
            hook = await db.get(IntegrationWebhook, hook_id, populate_existing=True)
        assert seen[0]["events"][0]["type"] == ie.TEST_EVENT_TYPE
        assert seen[0]["events"][0]["id"] == 0
        assert hook.is_active is True and hook.failure_count == 0
        assert hook.test_requested_at is None

    async def test_inactive_account_gets_nothing(
        self, app_client, app_auth_headers: dict, public_dns: list[str]
    ) -> None:
        from app.core.database import AsyncSessionLocal

        account, _, hook_id, _ = await self._hook(
            app_client, app_auth_headers, ["md:read"]
        )
        await _seed_events(
            [("md_import.created", {"md_import_id": 2, "period_month": "2041-03"})]
        )
        resp = await app_client.patch(
            f"/api/settings/service-accounts/{account['id']}",
            headers=app_auth_headers,
            json={"is_active": False},
        )
        assert resp.status_code == 200, resp.text
        calls: list = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200)

        async with _mock_client(handler) as client, AsyncSessionLocal() as db:
            assert await wh.deliver_webhook(db, client, hook_id) == "skipped"
        assert calls == []


@pytest.mark.asyncio
async def test_publish_keeps_cursor_order_and_retention_cuts_old(app_client) -> None:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "INSERT INTO integration_event_outbox (type, scope, refs) VALUES "
                "('md_import.created', 'md:read', '{\"md_import_id\": 1}'::jsonb), "
                "('md_import.created', 'md:read', '{\"md_import_id\": 2}'::jsonb)"
            )
        )
        await db.commit()
        before = await ie.current_cursor(db)
        assert await _publish_all(db) >= 2
        after = await ie.current_cursor(db)
        assert after >= before + 2
        left = (
            await db.execute(text("SELECT count(*) FROM integration_event_outbox"))
        ).scalar()
        assert left == 0

        old_id = (await _seed_events([("md_import.created", {"md_import_id": 3})]))[0]
        await db.execute(
            text(
                "UPDATE integration_events SET published_at = now() - interval '40 days' "
                "WHERE id <= :id"
            ),
            {"id": old_id - 1},
        )
        await db.commit()
        await ie.purge_expired(db)
        remaining_min = (
            await db.execute(text("SELECT min(id) FROM integration_events"))
        ).scalar()
        assert remaining_min == old_id


@pytest.mark.asyncio
async def test_failed_outbox_insert_does_not_poison_the_postgres_transaction(
    app_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Na Postgresie błąd INSERT-u przerywa CAŁĄ transakcję — bez SAVEPOINT-u
    commit kandydata padłby na ``InFailedSqlTransaction``."""
    from sqlalchemy import BigInteger, Column, MetaData, Table
    from sqlalchemy.dialects.postgresql import JSONB

    from app.core.database import AsyncSessionLocal

    missing = Table(
        "integration_event_outbox_missing",
        MetaData(),
        Column("id", BigInteger, primary_key=True),
        Column("type", String(64)),
        Column("scope", String(64)),
        Column("refs", JSONB),
    )

    class _Missing:
        __table__ = missing

    monkeypatch.setattr(ie, "IntegrationEventOutbox", _Missing)
    u = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Ola", lastname=f"Savepoint-{u}", email=f"sp-{u}@example.com"
        )
        db.add(cand)
        await db.commit()
        found = await db.scalar(select(Candidate.id).where(Candidate.id == cand.id))
    assert found == cand.id
