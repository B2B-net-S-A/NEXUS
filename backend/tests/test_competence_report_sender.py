"""Pętla raportów kompetencji (``tasks/competence_report_sender.py``) i ``send_report``.

Pętla commituje (rezerwacja przed wysyłką), więc testy zapisują fikcyjne osoby
naprawdę i sprzątają je na końcu. Wszystkie raporty mają daty z 2000 roku,
a przebieg dostaje ``now`` z tego roku: pętla bierze tylko wiersze utworzone
przed ``now``, więc nie rusza raportów z innych testów. Nadawca maila
(``send_email``), polityka z Ustawień i stawki rynku są podmienione.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select

from app.core import tasks as bg_tasks
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.competence_report import CompetenceReport
from app.models.user import User, UserRole
from app.services import competence_report_engine as engine
from app.services import market_rates
from app.services.competence_report_schema import ReportConditions
from app.tasks import competence_report_sender as sender

T0 = datetime(2000, 1, 3, 8, 0, tzinfo=timezone.utc)
DUE = T0 + timedelta(hours=23)
CONDITIONS = ReportConditions(
    rate=150, modes=("hybrid",), office_days_max=2, office_cities=("Kraków",)
).model_dump(mode="json")


class _Policy:
    def __init__(self, enabled: bool = True, cutoff: datetime = T0 - timedelta(days=1)):
        self.enabled, self.cutoff = enabled, cutoff

    def kind_enabled(self, kind):
        return self.enabled

    def allows(self, kind, event_at):
        return self.enabled and event_at is not None and event_at >= self.cutoff


@pytest.fixture
def mail(monkeypatch):
    """Nadawca, polityka i rynek podmienione; zwraca listę wysłanych maili."""
    sent: list[SimpleNamespace] = []
    state = SimpleNamespace(ok=True, policy=_Policy(), sent=sent)

    def fake_send(
        to,
        subject,
        text_body,
        html_body=None,
        reply_to=None,
        sender_upn=None,
        list_unsubscribe=None,
    ):
        sent.append(
            SimpleNamespace(
                to=to,
                subject=subject,
                html=html_body,
                reply_to=reply_to,
                sender=sender_upn,
                unsubscribe=list_unsubscribe,
            )
        )
        return state.ok

    async def fake_policy(db):
        return state.policy

    async def no_rate(db, *, role, years, city):
        return None

    from app.core.config import settings

    monkeypatch.setattr("app.services.email.send_email", fake_send)
    monkeypatch.setattr(
        "app.services.notification_delivery.is_delivery_allowed_sync",
        lambda kind, at: True,
    )
    monkeypatch.setattr("app.services.notification_delivery.load_policy", fake_policy)
    monkeypatch.setattr(
        "app.services.candidate_terms_queue.candidate_sender_ready", lambda: True
    )
    monkeypatch.setattr(
        settings, "CANDIDATE_MAIL_SENDER_UPN", "kariera-test@example.com"
    )
    monkeypatch.setattr(settings, "M365_APP_MAIL_ENABLED", False)
    monkeypatch.delenv("COMPETENCE_REPORT_TEST_RECIPIENTS", raising=False)
    monkeypatch.setattr(market_rates, "market_rate_for", no_rate)
    return state


@pytest.fixture
async def people():
    """Fabryka fikcyjnych kandydatów z raportem; sprząta po teście."""
    import app.models  # noqa: F401

    made: list[int] = []
    users: list[int] = []

    async def make(
        *, parsed=True, status="waiting_cv", snapshot=False, owner=False, **fields
    ):
        async with AsyncSessionLocal() as db:
            candidate = Candidate(
                name="Testowa",
                lastname="Petla",
                email=f"petla-{uuid.uuid4().hex[:12]}@example.com",
                cv_parsed_at=T0 if parsed else None,
            )
            db.add(candidate)
            owner_id = None
            if owner:
                user = User(
                    email=f"opiekun-petli-{uuid.uuid4().hex[:8]}@example.com",
                    password_hash="not-a-real-hash",
                    name="Opiekun Petli",
                    role=UserRole.recruiter,
                )
                db.add(user)
                await db.flush()
                owner_id = user.id
                users.append(user.id)
            await db.flush()
            report = CompetenceReport(
                candidate_id=candidate.id,
                email=candidate.email,
                status=status,
                conditions=CONDITIONS,
                created_at=T0,
                send_due_at=DUE,
                owner_user_id=owner_id,
                **fields,
            )
            if snapshot:
                report.snapshot = engine.fallback_snapshot(report).model_dump(
                    mode="json"
                )
            db.add(report)
            await db.commit()
            made.append(candidate.id)
            return report.id

    yield make

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(Activity).where(
                Activity.entity_type == "candidate", Activity.entity_id.in_(made)
            )
        )
        await db.execute(delete(Candidate).where(Candidate.id.in_(made)))
        await db.execute(delete(User).where(User.id.in_(users)))
        await db.commit()


async def _row(report_id: int) -> CompetenceReport:
    async with AsyncSessionLocal() as db:
        return await db.get(CompetenceReport, report_id)


async def _tick(now: datetime) -> dict:
    async with AsyncSessionLocal() as db:
        return await sender.process_due(db, now=now)


async def test_odczytane_cv_daje_gotowy_raport_ale_nie_przed_terminem(mail, people):
    report_id = await people()

    await _tick(T0 + timedelta(hours=1))

    row = await _row(report_id)
    assert row.status == "ready"
    assert row.ready_at == T0 + timedelta(hours=1)
    assert row.snapshot["conditions"]["rate"] == 150
    assert mail.sent == []


async def test_po_terminie_wysyla_z_tokenem_i_wpisem(mail, people):
    report_id = await people(owner=True)
    await _tick(T0 + timedelta(hours=1))

    await _tick(DUE)

    row = await _row(report_id)
    assert row.status == "sent" and row.sent_at == DUE and row.sent_by_user_id is None
    assert row.token_hash and row.token_expires_at > DUE
    [message] = mail.sent
    assert message.to == row.email
    assert message.sender == "kariera-test@example.com"
    assert message.reply_to.startswith("opiekun-petli-")
    assert message.unsubscribe and "/opt-out" in message.unsubscribe
    assert message.subject.startswith("Twój raport kompetencji")
    async with AsyncSessionLocal() as db:
        entry = await db.scalar(
            select(Activity).where(
                Activity.entity_id == row.candidate_id,
                Activity.action == engine.ACTIVITY_ACTION,
            )
        )
    assert entry.details["summary"] == "raport kompetencji wysłany"
    # drugi przebieg niczego nie wysyła drugi raz
    await _tick(DUE + timedelta(minutes=5))
    assert len(mail.sent) == 1


async def test_wstrzymany_nie_wychodzi(mail, people):
    report_id = await people(status="ready", snapshot=True, held_at=T0)

    await _tick(DUE + timedelta(hours=1))

    assert (await _row(report_id)).status == "ready"
    assert mail.sent == []


async def test_wypisany_nie_dostaje_raportu(mail, people):
    report_id = await people(status="ready", snapshot=True)
    async with AsyncSessionLocal() as db:
        row = await db.get(CompetenceReport, report_id)
        # wypis z wcześniejszego raportu tej samej osoby
        db.add(
            CompetenceReport(
                candidate_id=row.candidate_id,
                email=row.email,
                status="sent",
                conditions=CONDITIONS,
                created_at=T0 - timedelta(days=30),
                send_due_at=T0 - timedelta(days=29),
                opted_out_at=T0 - timedelta(days=20),
            )
        )
        await db.commit()

    await _tick(DUE)

    assert (await _row(report_id)).status == "opted_out"
    assert mail.sent == []


async def test_lista_probna_blokuje_inne_adresy(mail, people, monkeypatch):
    monkeypatch.setenv(
        "COMPETENCE_REPORT_TEST_RECIPIENTS", "zespol-testowy@example.com"
    )
    report_id = await people(status="ready", snapshot=True)

    await _tick(DUE)

    row = await _row(report_id)
    assert (row.status, row.last_error) == ("skipped", "recipient_not_allowed")
    assert mail.sent == []


async def test_wylaczony_rodzaj_maila_nic_nie_wysyla(mail, people):
    mail.policy = _Policy(enabled=False)
    report_id = await people(status="ready", snapshot=True)

    await _tick(DUE)

    assert (await _row(report_id)).status == "ready"
    assert mail.sent == []


async def test_raport_sprzed_wlaczenia_maila_odpada(mail, people):
    mail.policy = _Policy(cutoff=T0 + timedelta(hours=2))
    report_id = await people(status="ready", snapshot=True)

    await _tick(DUE)

    row = await _row(report_id)
    assert (row.status, row.last_error) == ("skipped", "before_enabled")
    assert mail.sent == []


async def test_nieudana_wysylka_liczy_proby_a_po_piatej_failed(mail, people):
    mail.ok = False
    retry_id = await people(status="ready", snapshot=True)
    last_id = await people(status="ready", snapshot=True, attempts=4)

    await _tick(DUE)

    retry, last = await _row(retry_id), await _row(last_id)
    assert (retry.status, retry.attempts) == ("ready", 1)
    assert retry.sent_at is None and retry.token_hash is None
    assert retry.last_error and "@" not in retry.last_error
    assert (last.status, last.attempts) == ("failed", 5)


async def test_ponowny_odczyt_cv_raz_po_30_minutach(mail, people, monkeypatch):
    calls: list[int] = []

    async def fake_parse(candidate_id, *args, **kwargs):
        calls.append(candidate_id)

    monkeypatch.setattr("app.api.public_share._invite_post_apply_task", fake_parse)
    report_id = await people(parsed=False)

    await _tick(T0 + timedelta(minutes=20))
    await asyncio.gather(*list(bg_tasks._bg_tasks))
    assert calls == []

    await _tick(T0 + timedelta(minutes=31))
    await asyncio.gather(*list(bg_tasks._bg_tasks))
    await _tick(T0 + timedelta(minutes=40))
    await asyncio.gather(*list(bg_tasks._bg_tasks))

    row = await _row(report_id)
    assert calls == [row.candidate_id]
    assert (row.status, row.attempts) == ("waiting_cv", 1)


async def test_po_20_h_bez_odczytu_raport_limited(mail, people, monkeypatch):
    async def fake_parse(candidate_id, *args, **kwargs):
        return None

    monkeypatch.setattr("app.api.public_share._invite_post_apply_task", fake_parse)
    report_id = await people(parsed=False, attempts=1)

    await _tick(T0 + timedelta(hours=19))
    assert (await _row(report_id)).status == "waiting_cv"

    await _tick(T0 + timedelta(hours=20, minutes=1))

    row = await _row(report_id)
    assert row.status == "ready" and row.attempts == 0
    assert row.snapshot["variant"] == "limited"


async def test_wyslij_teraz_przed_terminem(mail, people):
    report_id = await people(status="ready", snapshot=True, held_at=T0)
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"rekruter-{uuid.uuid4().hex[:8]}@example.com",
            password_hash="not-a-real-hash",
            name="Rekruter Testowy",
            role=UserRole.recruiter,
        )
        db.add(user)
        await db.commit()
        try:
            report = await db.get(CompetenceReport, report_id)
            await engine.send_report_now(db, report, user)
            row = await _row(report_id)
            assert row.status == "sent" and row.sent_by_user_id == user.id
            assert len(mail.sent) == 1
            with pytest.raises(engine.ReportNotSendable) as err:
                await engine.send_report_now(db, report, user)
            assert err.value.reason == "not_ready"
        finally:
            await db.execute(
                delete(Activity).where(
                    Activity.entity_type == "candidate",
                    Activity.entity_id == row.candidate_id,
                )
            )
            await db.execute(delete(User).where(User.id == user.id))
            await db.commit()
