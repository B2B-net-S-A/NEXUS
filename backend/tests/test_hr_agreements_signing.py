"""Umowy z ludźmi (etap 5, E5) — podpis i przepisanie do kartoteki.

Autenti to fałszywy klient (``FakeAutenti``), e-teczka — zaślepka
``attach_document`` (moduł dokumentów osoby dopisuje E4). Sprawdzamy:
wysyłkę tylko na klik i z zamrożonymi polami, błąd Autenti bez treści
odpowiedzi, stan z ``GET`` procesu (podpisana / odrzucona / wycofana / po
terminie), przepisanie po podpisie w jednej transakcji i bez dublowania przy
powtórce, nieudane przepisanie (zamknięty miesiąc płac) z „Przepisz ponownie”,
podpis ręczny ze skanem (razem albo nic), aneks zmieniający tylko stawkę,
znacznik dla Symfonii i pętlę z rezerwacją przebiegu. Dane fikcyjne.
"""

from __future__ import annotations

import hashlib
import shutil
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select

from app.core.config import settings as app_settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.hr_agreement import HrAgreement
from app.models.hr_document import HrDocument
from app.models.hr_ops import HrAuditEvent, HrJobRun
from app.models.hr_payroll import EmployeeRate, PayrollPeriod
from app.models.hr_profile import EmployeeProfile
from app.models.notification import Notification, NotificationType
from app.services import cv_pdf_preview
from app.services.hr import agreements_effects, agreements_signing
from app.services.hr import agreements_document as document
from app.services.hr.agreements import SETTINGS_KEY
from app.services.hr.agreements_errors import AgreementError
from tests.hr_agreements_seed import (
    PREFIX,
    SCAN_PDF,
    SIGNED_PDF,
    agreements_on_fixture,  # noqa: F401  (fixture „agreements_on”)
    autenti_fixture,  # noqa: F401  (fixture „autenti”)
    autenti_error,
    first_of_next_month,
    make_template,
)
from tests.hr_settlements_seed import headers, set_setting


#: Prawdziwa zamiana DOCX → PDF i prawdziwa e-teczka (zasiew podmienia je na zaślepki).
REAL_PDF_FROM_DOCX = cv_pdf_preview.pdf_from_docx
REAL_ATTACH = agreements_effects.attach_document


@pytest.fixture(scope="module", autouse=True)
def agreements_routes():
    from app.api import hr_agreements
    from app.main import app

    before = list(app.router.routes)
    added = False
    if f"{PREFIX}/settings" not in {getattr(route, "path", "") for route in before}:
        app.include_router(hr_agreements.router, prefix=PREFIX, tags=["hr"])
        added = True
    yield
    if added:
        app.router.routes[:] = before


@pytest.fixture
def bells(monkeypatch):
    """Typ ``hr_agreement_update`` dopina koordynator — do tego czasu sprawdzamy
    odbiorców i treść na istniejącym typie osobistym."""

    monkeypatch.setattr(
        agreements_signing, "_update_type", lambda: NotificationType.hr_lifecycle_task
    )


async def _draft(app_client, team, *, person=None, kind="zlecenie", **values) -> dict:
    template_id = await make_template(kind)
    body = {
        "template_id": template_id,
        "hourly_rate": "32.00",
        "currency": "PLN",
        "start_date": first_of_next_month().isoformat(),
        "hours_confirmation": True,
        **values,
    }
    person = person or team.mandate
    created = await app_client.post(
        f"{PREFIX}/people/{person.id}", json=body, headers=headers(team.hr)
    )
    assert created.status_code == 201, created.text
    return created.json()


async def _agreement(agreement_id: int) -> HrAgreement:
    async with AsyncSessionLocal() as db:
        return await db.get(HrAgreement, agreement_id)


async def _rates(user_id: int) -> list[EmployeeRate]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(EmployeeRate)
                    .where(EmployeeRate.user_id == user_id)
                    .order_by(EmployeeRate.effective_from)
                )
            ).all()
        )


async def _profile(user_id: int) -> EmployeeProfile:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(EmployeeProfile).where(EmployeeProfile.user_id == user_id)
        )


async def _sync(agreement_id: int, client) -> str:
    async with AsyncSessionLocal() as db:
        agreement = await db.scalar(
            select(HrAgreement).where(HrAgreement.id == agreement_id).with_for_update()
        )
        outcome = await agreements_signing.sync_process(db, agreement, client)
        await db.commit()
        return outcome


async def _close_month(day: date) -> int:
    async with AsyncSessionLocal() as db:
        period = PayrollPeriod(
            year=day.year,
            month=day.month,
            status="closed",
            close_count=1,
            closed_at=datetime.now(timezone.utc),
        )
        db.add(period)
        await db.commit()
        return period.id


async def _reopen(period_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(PayrollPeriod).where(PayrollPeriod.id == period_id))
        await db.commit()


async def _actions(agreement_id: int) -> list[str]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(HrAuditEvent.action)
                    .where(
                        HrAuditEvent.entity_type == "hr_agreement",
                        HrAuditEvent.entity_id == str(agreement_id),
                    )
                    .order_by(HrAuditEvent.id)
                )
            ).all()
        )


# ── Wysyłka ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_without_autenti_is_503_and_manual_path_stays(
    app_client, agreements_on, monkeypatch
) -> None:
    team = agreements_on
    monkeypatch.setattr(app_settings, "AUTENTI_ENABLED", False)
    draft = await _draft(app_client, team)
    assert draft["actions"]["send"] is False and draft["actions"]["mark_signed"] is True
    refused = await app_client.post(
        f"{PREFIX}/{draft['id']}/send", headers=headers(team.hr)
    )
    assert refused.status_code == 503 and "ręcznie" in refused.json()["detail"]


@pytest.mark.asyncio
async def test_send_freezes_fields_and_calls_autenti_once(
    app_client, agreements_on, autenti
) -> None:
    team = agreements_on
    draft = await _draft(app_client, team)
    # Płace nie wysyłają — tylko klik Kadr.
    refused = await app_client.post(
        f"{PREFIX}/{draft['id']}/send", headers=headers(team.payroll)
    )
    assert refused.status_code == 403
    sent = await app_client.post(
        f"{PREFIX}/{draft['id']}/send", headers=headers(team.hr)
    )
    assert sent.status_code == 200, sent.text
    assert (
        sent.json()["status"] == "sent" and sent.json()["actions"]["withdraw"] is True
    )
    assert autenti.names() == ["create", "upload", "send"]
    payload = autenti.calls[0][1]["payload"]
    signer = payload["signers"][0]
    assert signer["email"] == team.mandate.email
    assert signer["lastName"] == team.mandate.name.split()[-1]
    assert autenti.calls[0][1]["key"] == f"hr-agreement-{draft['id']}-1"
    assert autenti.calls[1][1]["filename"].startswith("Umowa_zlecenia_Celina_Testowa")
    row = await _agreement(draft["id"])
    assert row.autenti_process_id and row.sent_sha256 and row.sent_by == team.hr.id
    assert row.document_fields["rate"] == "32,00"
    assert row.document_fields["person_name"] == team.mandate.name
    # Druga wysyłka tej samej umowy — 409, Autenti bez nowego procesu.
    again = await app_client.post(
        f"{PREFIX}/{draft['id']}/send", headers=headers(team.hr)
    )
    assert again.status_code == 409 and autenti.created == 1


@pytest.mark.asyncio
async def test_send_failure_keeps_draft_with_reason_and_counts_attempt(
    app_client, agreements_on, autenti
) -> None:
    team = agreements_on
    draft = await _draft(app_client, team)
    autenti.fail["upload"] = autenti_error(500)
    failed = await app_client.post(
        f"{PREFIX}/{draft['id']}/send", headers=headers(team.hr)
    )
    assert failed.status_code == 502
    assert "HTTP 500" in failed.json()["detail"]
    assert "odpowiedź z danymi" not in failed.text
    row = await _agreement(draft["id"])
    assert row.status == "draft" and row.send_attempts == 1
    assert row.autenti_process_id is None and "HTTP 500" in (row.last_error or "")
    autenti.fail.clear()
    sent = await app_client.post(
        f"{PREFIX}/{draft['id']}/send", headers=headers(team.hr)
    )
    assert sent.status_code == 200
    assert autenti.calls[-3][1]["key"] == f"hr-agreement-{draft['id']}-2"


# ── Podpis w Autenti ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_signed_in_autenti_applies_once_to_profile_rate_and_documents(
    app_client, agreements_on, autenti, bells
) -> None:
    team = agreements_on
    # Ola z B2B przechodzi na zlecenie.
    switch = await _draft(app_client, team, person=team.b2b, kind="zlecenie")
    agreement_id = switch["id"]
    await app_client.post(f"{PREFIX}/{agreement_id}/send", headers=headers(team.hr))
    autenti.status = "IN_PROGRESS"
    assert await _sync(agreement_id, autenti) == "unchanged"
    autenti.status = "COMPLETED"
    assert await _sync(agreement_id, autenti) == "signed"
    row = await _agreement(agreement_id)
    assert row.status == "signed" and row.applied_at is not None
    assert row.signed_on == business_today() and row.document_id == 9001
    assert row.symfonia_pending is True
    # Kartoteka: z B2B na zlecenie, z potwierdzaniem godzin.
    profile = await _profile(team.b2b.id)
    assert profile.employment_type == "zlecenie" and profile.timesheet_required is True
    rates = await _rates(team.b2b.id)
    assert [(r.effective_from, r.hourly_rate) for r in rates] == [
        (first_of_next_month(), Decimal("32.00"))
    ]
    (call,) = team.attached.calls
    assert call["content"] == SIGNED_PDF and call["mime"] == "application/pdf"
    assert call["source"] == "agreement" and call["source_ref"] == str(agreement_id)
    assert call["kind"] == "contract" and call["valid_until"] is None
    # Powtórka (webhook, pętla) niczego nie dubluje.
    assert await _sync(agreement_id, autenti) == "unchanged"
    async with AsyncSessionLocal() as db:
        assert await agreements_signing.on_autenti_process(db, row.autenti_process_id)
    assert len(await _rates(team.b2b.id)) == 1 and len(team.attached.calls) == 1
    async with AsyncSessionLocal() as db:
        bell = await db.scalar(
            select(Notification).where(
                Notification.user_id == team.hr.id,
                Notification.notification_type == NotificationType.hr_lifecycle_task,
            )
        )
    assert bell is not None and "podpisana" in bell.title
    assert "32,00" not in bell.title + bell.message


@pytest.mark.asyncio
async def test_closed_payroll_month_leaves_signed_with_reason_then_retry_applies(
    app_client, agreements_on, autenti
) -> None:
    team = agreements_on
    draft = await _draft(app_client, team)
    await app_client.post(f"{PREFIX}/{draft['id']}/send", headers=headers(team.hr))
    period_id = await _close_month(first_of_next_month())
    try:
        autenti.status = "COMPLETED"
        assert await _sync(draft["id"], autenti) == "apply_failed"
        row = await _agreement(draft["id"])
        assert row.status == "signed" and row.applied_at is None and row.apply_error
        assert row.document_id is None and team.attached.calls == []
        assert await _rates(team.mandate.id) == []
        assert "agreement_apply_failed" in await _actions(draft["id"])
        listing = await app_client.get(
            f"{PREFIX}/{draft['id']}", headers=headers(team.hr)
        )
        assert listing.json()["actions"]["apply"] is True
    finally:
        await _reopen(period_id)
    retried = await app_client.post(
        f"{PREFIX}/{draft['id']}/apply", headers=headers(team.hr)
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["applied_at"] and retried.json()["apply_error"] is None
    assert len(await _rates(team.mandate.id)) == 1 and len(team.attached.calls) == 1
    again = await app_client.post(
        f"{PREFIX}/{draft['id']}/apply", headers=headers(team.hr)
    )
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_failed_document_attach_rolls_back_rate_and_profile(
    app_client, agreements_on, autenti
) -> None:
    team = agreements_on
    draft = await _draft(app_client, team, person=team.b2b)
    await app_client.post(f"{PREFIX}/{draft['id']}/send", headers=headers(team.hr))
    team.attached.fail = RuntimeError("e-teczka niedostępna")
    autenti.status = "COMPLETED"
    assert await _sync(draft["id"], autenti) == "apply_failed"
    row = await _agreement(draft["id"])
    assert row.status == "signed" and row.applied_at is None
    # Punkt zapisu cofnął stawkę i formę razem z nieudanym dokumentem.
    assert await _rates(team.b2b.id) == []
    assert (await _profile(team.b2b.id)).employment_type == "b2b"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("remote", "status", "outcome"),
    [
        ("DOCUMENT_PROCESS_REJECTED", "rejected", "rejected"),
        ("DOCUMENT_PROCESS_EXPIRED", "draft", "expired"),
        ("DOCUMENT_PROCESS_WITHDRAWN", "draft", "withdrawn"),
    ],
)
async def test_rejected_expired_withdrawn_in_autenti(
    app_client, agreements_on, autenti, remote, status, outcome
) -> None:
    team = agreements_on
    draft = await _draft(app_client, team)
    await app_client.post(f"{PREFIX}/{draft['id']}/send", headers=headers(team.hr))
    autenti.status = remote
    assert await _sync(draft["id"], autenti) == outcome
    row = await _agreement(draft["id"])
    assert row.status == status
    if status == "draft":
        assert row.autenti_process_id is None and row.last_error
        assert row.document_fields is None
    assert await _rates(team.mandate.id) == [] and team.attached.calls == []


@pytest.mark.asyncio
async def test_download_failure_keeps_sent_and_retries(
    app_client, agreements_on, autenti
) -> None:
    team = agreements_on
    draft = await _draft(app_client, team)
    await app_client.post(f"{PREFIX}/{draft['id']}/send", headers=headers(team.hr))
    autenti.status = "COMPLETED"
    autenti.fail["download"] = autenti_error(503)
    assert await _sync(draft["id"], autenti) == "download_failed"
    row = await _agreement(draft["id"])
    assert row.status == "sent" and "ponowi" in (row.last_error or "")
    autenti.fail.clear()
    assert await _sync(draft["id"], autenti) == "signed"


@pytest.mark.asyncio
async def test_withdraw_back_to_draft_and_cancel_sent(
    app_client, agreements_on, autenti
) -> None:
    team = agreements_on
    draft = await _draft(app_client, team)
    await app_client.post(f"{PREFIX}/{draft['id']}/send", headers=headers(team.hr))
    withdrawn = await app_client.post(
        f"{PREFIX}/{draft['id']}/withdraw", headers=headers(team.hr)
    )
    assert withdrawn.status_code == 200 and withdrawn.json()["status"] == "draft"
    assert autenti.names()[-1] == "withdraw"
    await app_client.post(f"{PREFIX}/{draft['id']}/send", headers=headers(team.hr))
    no_reason = await app_client.post(
        f"{PREFIX}/{draft['id']}/cancel",
        json={"reason": "  "},
        headers=headers(team.hr),
    )
    assert no_reason.status_code == 422
    cancelled = await app_client.post(
        f"{PREFIX}/{draft['id']}/cancel",
        json={"reason": "Osoba zrezygnowała przed podpisem."},
        headers=headers(team.hr),
    )
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert autenti.names().count("withdraw") == 2
    # Anulowana umowa nie blokuje nowej.
    await _draft(app_client, team)


@pytest.mark.asyncio
async def test_signed_agreement_lands_in_real_person_documents_once(
    app_client, agreements_on, autenti, monkeypatch
) -> None:
    """Prawdziwe ``documents.attach_generated`` (E4): rodzaj, źródło, ważność, plik."""

    team = agreements_on
    monkeypatch.setattr(agreements_effects, "attach_document", REAL_ATTACH)
    end = first_of_next_month(13) - timedelta(days=1)
    draft = await _draft(app_client, team, end_date=end.isoformat())
    await app_client.post(f"{PREFIX}/{draft['id']}/send", headers=headers(team.hr))
    autenti.status = "COMPLETED"
    assert await _sync(draft["id"], autenti) == "signed"
    row = await _agreement(draft["id"])
    async with AsyncSessionLocal() as db:
        document = await db.get(HrDocument, row.document_id)
    assert document is not None and document.user_id == team.mandate.id
    assert (document.kind, document.source, document.source_ref) == (
        "contract",
        "agreement",
        str(draft["id"]),
    )
    assert document.valid_until == end and document.mime == "application/pdf"
    assert document.sha256 == hashlib.sha256(SIGNED_PDF).hexdigest()
    assert document.visible_to_person and document.visible_to_payroll
    # Ponowne wołanie e-teczki dla tej samej umowy oddaje ten sam dokument.
    async with AsyncSessionLocal() as db:
        again = await REAL_ATTACH(
            db,
            await db.get(HrAgreement, draft["id"]),
            content=SIGNED_PDF,
            mime="application/pdf",
            actor_id=team.hr.id,
        )
        assert again == row.document_id
        count = await db.scalar(
            select(func.count())
            .select_from(HrDocument)
            .where(
                HrDocument.source == "agreement",
                HrDocument.source_ref == str(draft["id"]),
            )
        )
    assert count == 1


@pytest.mark.asyncio
async def test_document_refused_by_person_documents_is_apply_error(
    app_client, agreements_on, autenti, monkeypatch
) -> None:
    """Odmowa e-teczki (treść nie jest PDF-em) = umowa podpisana z powodem, bez stawki."""

    team = agreements_on
    monkeypatch.setattr(agreements_effects, "attach_document", REAL_ATTACH)
    draft = await _draft(app_client, team)
    await app_client.post(f"{PREFIX}/{draft['id']}/send", headers=headers(team.hr))
    autenti.status = "COMPLETED"
    autenti.signed = b"to nie jest PDF"
    assert await _sync(draft["id"], autenti) == "apply_failed"
    row = await _agreement(draft["id"])
    assert row.status == "signed" and row.applied_at is None
    assert row.apply_error and row.document_id is None
    assert await _rates(team.mandate.id) == []


@pytest.mark.asyncio
async def test_cancel_sent_when_autenti_switched_off_does_not_get_stuck(
    app_client, agreements_on, autenti, monkeypatch
) -> None:
    """Autenti wyłączone po wysyłce: anulowanie przechodzi, ślad mówi, że bez wycofania."""

    team = agreements_on
    draft = await _draft(app_client, team)
    await app_client.post(f"{PREFIX}/{draft['id']}/send", headers=headers(team.hr))
    monkeypatch.setattr(app_settings, "AUTENTI_ENABLED", False)
    withdraw = await app_client.post(
        f"{PREFIX}/{draft['id']}/withdraw", headers=headers(team.hr)
    )
    assert withdraw.status_code == 503
    cancelled = await app_client.post(
        f"{PREFIX}/{draft['id']}/cancel",
        json={"reason": "Umowa zastąpiona papierową."},
        headers=headers(team.hr),
    )
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert "withdraw" not in autenti.names()
    async with AsyncSessionLocal() as db:
        details = await db.scalar(
            select(HrAuditEvent.details).where(
                HrAuditEvent.entity_id == str(draft["id"]),
                HrAuditEvent.action == "agreement_cancelled",
            )
        )
    assert details["withdrawn_in_autenti"] is False


# ── Podpis ręczny ─────────────────────────────────────────────────────────────


def _scan(content: bytes = SCAN_PDF, **values) -> dict:
    data = {
        "signed_on": business_today().isoformat(),
        "reason": "Podpis na papierze w biurze.",
    }
    data.update(values)
    return {"files": {"file": ("skan.pdf", content, "application/pdf")}, "data": data}


@pytest.mark.asyncio
async def test_manual_signature_with_scan_applies_in_one_transaction(
    app_client, agreements_on, monkeypatch
) -> None:
    team = agreements_on
    monkeypatch.setattr(app_settings, "AUTENTI_ENABLED", False)
    end = first_of_next_month(7) - timedelta(days=1)
    draft = await _draft(app_client, team, end_date=end.isoformat())
    url = f"{PREFIX}/{draft['id']}/mark-signed"
    not_scan = await app_client.post(
        url, headers=headers(team.hr), **_scan(b"MZ\x90\x00")
    )
    assert not_scan.status_code == 422
    future = await app_client.post(
        url,
        headers=headers(team.hr),
        **_scan(signed_on=(business_today() + timedelta(days=1)).isoformat()),
    )
    assert future.status_code == 422
    refused = await app_client.post(url, headers=headers(team.payroll), **_scan())
    assert refused.status_code == 403
    signed = await app_client.post(url, headers=headers(team.hr), **_scan())
    assert signed.status_code == 200, signed.text
    body = signed.json()
    assert body["status"] == "signed" and body["signing_channel"] == "manual"
    assert (
        body["applied_at"] and body["manual_reason"] == "Podpis na papierze w biurze."
    )
    (call,) = team.attached.calls
    assert call["content"] == SCAN_PDF and call["actor_id"] == team.hr.id
    # Umowa na czas określony: „ważny do” dokumentu w e-teczce = koniec umowy.
    assert call["valid_until"] == end
    assert "agreement_signed_manually" in await _actions(draft["id"])
    assert len(await _rates(team.mandate.id)) == 1


@pytest.mark.asyncio
async def test_manual_signature_refused_by_effects_changes_nothing(
    app_client, agreements_on
) -> None:
    team = agreements_on
    draft = await _draft(app_client, team)
    period_id = await _close_month(first_of_next_month())
    try:
        refused = await app_client.post(
            f"{PREFIX}/{draft['id']}/mark-signed", headers=headers(team.hr), **_scan()
        )
        assert refused.status_code == 409, refused.text
    finally:
        await _reopen(period_id)
    row = await _agreement(draft["id"])
    assert (
        row.status == "draft" and row.signed_at is None and row.document_fields is None
    )
    assert team.attached.calls == [] and await _rates(team.mandate.id) == []


@pytest.mark.asyncio
async def test_manual_signature_of_sent_agreement_needs_withdraw(
    app_client, agreements_on, autenti
) -> None:
    team = agreements_on
    draft = await _draft(app_client, team)
    await app_client.post(f"{PREFIX}/{draft['id']}/send", headers=headers(team.hr))
    refused = await app_client.post(
        f"{PREFIX}/{draft['id']}/mark-signed", headers=headers(team.hr), **_scan()
    )
    assert refused.status_code == 409 and "wycofaj" in refused.json()["detail"]


# ── Aneks ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_annex_changes_rate_from_date_and_keeps_form(
    app_client, agreements_on
) -> None:
    team = agreements_on
    base = await _draft(app_client, team)
    signed = await app_client.post(
        f"{PREFIX}/{base['id']}/mark-signed", headers=headers(team.hr), **_scan()
    )
    assert signed.status_code == 200, signed.text
    async with AsyncSessionLocal() as db:
        profile = await db.scalar(
            select(EmployeeProfile).where(EmployeeProfile.user_id == team.mandate.id)
        )
        profile.timesheet_required = False
        await db.commit()
    later = first_of_next_month(3)
    annex = await _draft(
        app_client,
        team,
        kind="annex",
        base_agreement_id=base["id"],
        hourly_rate="34.00",
        start_date=later.isoformat(),
    )
    assert annex["kind"] == "annex" and annex["base_agreement_id"] == base["id"]
    done = await app_client.post(
        f"{PREFIX}/{annex['id']}/mark-signed", headers=headers(team.hr), **_scan()
    )
    assert done.status_code == 200, done.text
    rates = await _rates(team.mandate.id)
    assert [(r.effective_from, r.hourly_rate) for r in rates] == [
        (first_of_next_month(), Decimal("32.00")),
        (later, Decimal("34.00")),
    ]
    assert rates[0].effective_to == later - timedelta(days=1)
    # Aneks nie rusza formy ani potwierdzania godzin.
    assert (await _profile(team.mandate.id)).timesheet_required is False
    assert team.attached.calls[-1]["kind"] == "annex"
    filled = await app_client.get(
        f"{PREFIX}/{annex['id']}/docx", headers=headers(team.hr)
    )
    assert filled.status_code == 200


@pytest.mark.asyncio
async def test_annex_base_must_be_signed_agreement_of_same_person(
    app_client, agreements_on
) -> None:
    team = agreements_on
    other = await _draft(app_client, team, person=team.b2b)
    template_id = await make_template("annex")
    refused = await app_client.post(
        f"{PREFIX}/people/{team.mandate.id}",
        json={
            "template_id": template_id,
            "base_agreement_id": other["id"],
            "hourly_rate": "34.00",
            "start_date": first_of_next_month().isoformat(),
        },
        headers=headers(team.hr),
    )
    assert refused.status_code == 422 and "tej samej osoby" in refused.json()["detail"]


# ── Symfonia ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_symfonia_pending_for_mandate_not_for_b2b_and_export_mark(
    app_client, agreements_on
) -> None:
    team = agreements_on
    mandate = await _draft(app_client, team)
    b2b = await _draft(
        app_client, team, person=team.b2b, kind="b2b", hours_confirmation=True
    )
    for agreement in (mandate, b2b):
        signed = await app_client.post(
            f"{PREFIX}/{agreement['id']}/mark-signed",
            headers=headers(team.hr),
            **_scan(),
        )
        assert signed.status_code == 200, signed.text
    async with AsyncSessionLocal() as db:
        pending = await agreements_effects.pending_for_symfonia(db)
        assert [row["agreement_id"] for row in pending] == [mandate["id"]]
        assert "załóż umowę w Symfonii" in pending[0]["todo"]
        assert "32,00" not in pending[0]["todo"]
        assert (
            await agreements_effects.mark_symfonia_exported(
                db, [mandate["id"], b2b["id"]], actor_id=team.payroll.id
            )
            == 1
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        assert await agreements_effects.pending_for_symfonia(db) == []
    row = await _agreement(mandate["id"])
    assert row.symfonia_pending is False and row.symfonia_exported_at is not None


# ── Pętla i webhook ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_once_disabled_claims_slot_and_signs(
    app_client, agreements_on, autenti, monkeypatch
) -> None:
    team = agreements_on
    draft = await _draft(app_client, team)
    await app_client.post(f"{PREFIX}/{draft['id']}/send", headers=headers(team.hr))
    autenti.status = "COMPLETED"
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(HrJobRun).where(HrJobRun.kind == agreements_signing.JOB_KIND)
        )
        await db.commit()
    await set_setting(SETTINGS_KEY, {"enabled": False})
    async with AsyncSessionLocal() as db:
        assert (await agreements_signing.run_once(db))["reason"] == "module_off"
    await set_setting(SETTINGS_KEY, {"enabled": True})
    monkeypatch.setattr(app_settings, "AUTENTI_ENABLED", False)
    async with AsyncSessionLocal() as db:
        assert (await agreements_signing.run_once(db))["reason"] == "autenti_off"
    monkeypatch.setattr(app_settings, "AUTENTI_ENABLED", True)
    async with AsyncSessionLocal() as db:
        result = await agreements_signing.run_once(db)
    assert result["status"] == "ok" and result.get("signed") == 1, result
    async with AsyncSessionLocal() as db:
        assert (await agreements_signing.run_once(db))["reason"] == "already_ran"
        runs = await db.scalar(
            select(func.count())
            .select_from(HrJobRun)
            .where(HrJobRun.kind == agreements_signing.JOB_KIND)
        )
    assert runs == 1
    assert (await _agreement(draft["id"])).status == "signed"
    async with AsyncSessionLocal() as db:
        assert await agreements_signing.on_autenti_process(db, "proc-not-ours") is False


@pytest.mark.asyncio
async def test_missing_notification_type_does_not_break_signing(
    app_client, agreements_on, autenti, monkeypatch
) -> None:
    team = agreements_on
    monkeypatch.setattr(agreements_signing, "_update_type", lambda: None)
    draft = await _draft(app_client, team)
    await app_client.post(f"{PREFIX}/{draft['id']}/send", headers=headers(team.hr))
    autenti.status = "DOCUMENT_PROCESS_REJECTED"
    assert await _sync(draft["id"], autenti) == "rejected"


# ── PDF przez LibreOffice ─────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.skipif(shutil.which("soffice") is None, reason="bez LibreOffice")
async def test_real_pdf_from_uploaded_template(
    app_client, agreements_on, monkeypatch
) -> None:
    team = agreements_on
    draft = await _draft(app_client, team)
    monkeypatch.setattr(cv_pdf_preview, "pdf_from_docx", REAL_PDF_FROM_DOCX)
    async with AsyncSessionLocal() as db:
        row = await db.get(HrAgreement, draft["id"])
        pdf = await document.render_pdf(db, row)
    assert pdf.startswith(b"%PDF") and len(pdf) > 1000


def test_scan_mime_by_header_not_by_name() -> None:
    assert agreements_signing.scan_mime(b"%PDF-1.4 x") == "application/pdf"
    assert agreements_signing.scan_mime(b"\xff\xd8\xff\xe0 x") == "image/jpeg"
    assert agreements_signing.scan_mime(b"\x89PNG\r\n\x1a\n x") == "image/png"
    for bad in (b"", b"PK\x03\x04 docx", b"GIF89a"):
        with pytest.raises(AgreementError):
            agreements_signing.scan_mime(bad)
