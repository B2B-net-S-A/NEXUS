"""Paczka do podpisu: dokumenty bez wymogu kwalifikowanego (0754, 22.11.2026).

Decyzja Artura: kwalifikowany podpis jest wymagany tylko przy umowie, która
przenosi prawa autorskie. NDA, oświadczenia i inne dokumenty kontraktor może
podpisać tym samym podpisem albo zaakceptować kodem z maila. Przebieg na
bazie korzysta z ``esign_env`` z ``test_b2b_esign.py``.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from app.services.b2b_esign import accept_code
from app.services.b2b_esign import documents as esign_docs
from app.services.b2b_esign import mail as esign_mail
from app.services.b2b_esign.history import esign_history
from tests.test_b2b_esign import (  # noqa: F401 — fikstura esign_env
    SOURCE,
    _FakeValidator,
    _partner,
    _report,
    _seed_in_progress,
    _token,
    esign_env,
)
from tests.test_b2b_esign_package import (
    NDA,
    _client_template,
    _send,
    _use_admin_as_company_signer,
)


# ── czyste reguły ────────────────────────────────────────────────────────────


def test_code_has_six_digits_and_its_hash_is_bound_to_the_request():
    code = accept_code.new_code()
    assert re.fullmatch(r"\d{6}", code)
    assert accept_code.code_hash(5, "123456") == accept_code.code_hash(5, "123 456")
    assert accept_code.code_hash(5, "123456") != accept_code.code_hash(6, "123456")
    assert accept_code.code_hash(5, "123456") != accept_code.code_hash(5, "123457")
    # W bazie jest skrót, nie kod.
    assert "123456" not in accept_code.code_hash(5, "123456")


def test_masked_address_shows_where_the_code_goes():
    assert accept_code.mask_email("adrian.b@o2.pl") == "a***@o2.pl"
    assert accept_code.mask_email(None) == ""
    assert accept_code.mask_email("bez-malpy") == ""


def test_code_mail_gives_the_code_and_says_what_it_does_not_cover():
    subject, body = esign_mail.contractor_accept_code_message(
        number="1582/2026", code="731904", valid_minutes=15
    )
    assert subject == "Umowa B2B nr 1582/2026: kod do akceptacji dokumentów"
    assert "731 904" in body
    assert "15 minut" in body
    assert "—" not in body and "—" not in subject


def test_pair_file_name_says_how_the_document_was_signed():
    class _Item:
        title = "NDA klienta"
        signed_via = "email_code"

    assert (
        esign_docs.pair_file_name(_Item())
        == "NDA klienta (zaakceptowane w NEXUSIE).pdf"
    )
    _Item.signed_via = "qualified"
    assert esign_docs.pair_file_name(_Item()) == "NDA klienta (podpis w NEXUSIE).pdf"


def test_contractor_messages_have_no_em_dash():
    for message in (
        accept_code.MSG_NOTHING_TO_ACCEPT,
        accept_code.MSG_RESEND_TOO_SOON,
        accept_code.MSG_CODE_WRONG,
        accept_code.MSG_CODE_EXPIRED,
        accept_code.MSG_NO_CODE,
        accept_code.MSG_NEEDS_QUALIFIED,
        accept_code.MSG_MAIL_FAILED,
        esign_docs.MSG_ANY_NOT_QUALIFIED,
    ):
        assert "—" not in message


def test_history_names_documents_accepted_by_code():
    now = datetime(2026, 11, 22, 10, tzinfo=timezone.utc)

    class _Request:
        id = 7
        sent_at = now
        sent_by = 1
        last_reminder_at = None
        status = "sent"
        completed_at = None
        closed_at = None
        close_reason = None
        company_signer_id = None
        closed_by = None
        contractor_signed_at = None
        events = [{"kind": "document_accepted", "at": now.isoformat(), "title": "NDA"}]

    labels = [e.label for e in esign_history([_Request()])]
    assert "Kontraktor zaakceptował kodem z maila: NDA" in labels


def test_migration_and_entrypoint_add_the_same_columns():
    root = Path(__file__).resolve().parents[1]
    migration = (root / "alembic/versions/0754_b2b_signing_accept_code.py").read_text()
    assert 'down_revision = "0753_cv_layout"' in migration
    assert "ACCEPT_CODE_DDL" in migration
    entrypoint = (root / "entrypoint.sh").read_text(encoding="utf-8")
    assert "_b2b_signing_documents_schema.ACCEPT_CODE_DDL" in entrypoint
    from app.services.b2b_esign.documents_schema import ACCEPT_CODE_DDL

    joined = "\n".join(ACCEPT_CODE_DDL)
    for column in (
        "requirement",
        "signed_via",
        "accept_code_hash",
        "accept_code_expires_at",
    ):
        assert column in joined
    # Stare wiersze zostają przy kwalifikowanym.
    assert "DEFAULT 'qualified'" in joined


# ── przebieg na bazie ────────────────────────────────────────────────────────


def _capture_mails(monkeypatch, *, ok: bool = True) -> list[dict[str, Any]]:
    mails: list[dict[str, Any]] = []

    async def _send_from(db, **kwargs):
        mails.append(kwargs)
        return (True, None) if ok else (False, "brak skrzynki")

    monkeypatch.setattr(esign_mail, "send_from", _send_from)
    return mails


def _code_from(mail: dict[str, Any]) -> str:
    found = re.search(r"(\d{3}) (\d{3})", mail["body_html"])
    assert found, mail["body_html"]
    return found.group(1) + found.group(2)


async def _package(app_client, headers, admin_id: int, **extra) -> dict[str, Any]:
    await _use_admin_as_company_signer(admin_id)
    scenario = await _seed_in_progress(created_by=admin_id)
    nda_id = await _client_template(scenario["client_id"], "NDA klienta", NDA)
    sent = await _send(app_client, headers, scenario["generated_id"], admin_id, **extra)
    assert sent.status_code == 200, sent.text
    [document] = sent.json()["request"]["documents"]
    return {
        **scenario,
        "nda_id": nda_id,
        "request_id": sent.json()["request"]["id"],
        "document": document,
        "token": _token(sent.json()["sign_url"]),
    }


@pytest.mark.asyncio
async def test_contractor_accepts_the_nda_by_code_and_signs_only_the_contract(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    esign_env,  # noqa: F811
    monkeypatch,
):
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.b2b_signing_document import B2BSigningDocument
    from app.models.b2b_signing_request import B2BSigningRequest
    from app.models.start_document import PlacementStartDocument
    from app.services import storage_service

    mails = _capture_mails(monkeypatch)
    pkg = await _package(app_client, app_auth_headers, esign_env["admin_id"])
    token, document = pkg["token"], pkg["document"]
    assert document["requirement"] == "any"

    view = (await app_client.get(f"/api/public/b2b-sign/{token}")).json()
    assert view["documents"][0]["requirement"] == "any"
    assert view["accept_code_email"] == "a***@example.com"

    # Bez kodu nie ma akceptacji.
    no_code = await app_client.post(
        f"/api/public/b2b-sign/{token}/accept",
        json={"code": "000000", "document_ids": [document["id"]]},
    )
    assert no_code.status_code == 422, no_code.text

    mails.clear()
    issued = await app_client.post(f"/api/public/b2b-sign/{token}/accept-code")
    assert issued.status_code == 200, issued.text
    assert issued.json()["accept_code_sent_at"] is not None
    [mail] = mails
    assert mail["to"] == "anna@example.com"
    code = _code_from(mail)

    # Drugi kod dopiero po minucie.
    again = await app_client.post(f"/api/public/b2b-sign/{token}/accept-code")
    assert again.status_code == 429, again.text

    wrong = "000000" if code != "000000" else "111111"
    bad = await app_client.post(
        f"/api/public/b2b-sign/{token}/accept",
        json={"code": wrong, "document_ids": [document["id"]]},
    )
    assert bad.status_code == 422, bad.text
    async with AsyncSessionLocal() as db:
        request = await db.get(B2BSigningRequest, pkg["request_id"])
        failed_after_wrong_code = request.contractor_failed_attempts
    assert failed_after_wrong_code >= 1

    ok = await app_client.post(
        f"/api/public/b2b-sign/{token}/accept",
        json={"code": code, "document_ids": [document["id"]]},
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    # Umowa jeszcze nie podpisana: link czeka, firma nic nie ma.
    assert body["status"] == "waiting"
    assert body["documents"][0]["signed"] is True
    assert body["documents"][0]["signed_via"] == "email_code"
    assert body["accept_code_email"] is None

    # Kod jest jednorazowy.
    reuse = await app_client.post(
        f"/api/public/b2b-sign/{token}/accept",
        json={"code": code, "document_ids": [document["id"]]},
    )
    assert reuse.status_code in (409, 422), reuse.text

    async with AsyncSessionLocal() as db:
        item = await db.get(B2BSigningDocument, document["id"])
        assert item.signed_via == "email_code"
        assert item.signed_sha256 == item.source_sha256
        assert item.validation["method"] == "email_code"
        assert item.validation["email"] == "anna@example.com"
        pair = await db.scalar(
            select(PlacementStartDocument).where(
                PlacementStartDocument.document_id == pkg["nda_id"],
                PlacementStartDocument.candidate_id == pkg["candidate_id"],
                PlacementStartDocument.job_id == pkg["job_id"],
            )
        )
        assert pair is not None and pair.status == "delivered"
        assert pair.file_name == "NDA klienta (zaakceptowane w NEXUSIE).pdf"
        assert storage_service.read_start_document_file(pair.file_path) == NDA
        request = await db.get(B2BSigningRequest, pkg["request_id"])
        assert request.accept_code_hash is None
        assert any(e["kind"] == "document_accepted" for e in request.events)

    # Umowa podpisem kwalifikowanym: teraz komplet idzie do firmy.
    partner = await _partner(pkg["generated_id"])
    _FakeValidator.report = _report((f"CN={partner}", "TOTAL_PASSED", "QESig"))
    signed = await app_client.post(
        f"/api/public/b2b-sign/{token}",
        files={
            "file": ("u.pdf", SOURCE + b"% podpis kontraktora\n", "application/pdf")
        },
    )
    assert signed.status_code == 200, signed.text
    assert signed.json()["status"] == "signed_by_you"


@pytest.mark.asyncio
async def test_document_required_by_the_client_cannot_be_accepted_by_code(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    esign_env,  # noqa: F811
    monkeypatch,
):
    _capture_mails(monkeypatch)
    await _use_admin_as_company_signer(esign_env["admin_id"])
    scenario = await _seed_in_progress(created_by=esign_env["admin_id"])
    nda_id = await _client_template(scenario["client_id"], "NDA klienta", NDA)

    foreign = await _send(
        app_client,
        app_auth_headers,
        scenario["generated_id"],
        esign_env["admin_id"],
        qualified_document_ids=[987654],
    )
    assert foreign.status_code == 422, foreign.text

    sent = await _send(
        app_client,
        app_auth_headers,
        scenario["generated_id"],
        esign_env["admin_id"],
        qualified_document_ids=[nda_id],
    )
    assert sent.status_code == 200, sent.text
    [document] = sent.json()["request"]["documents"]
    assert document["requirement"] == "qualified"
    token = _token(sent.json()["sign_url"])

    view = (await app_client.get(f"/api/public/b2b-sign/{token}")).json()
    assert view["documents"][0]["requirement"] == "qualified"
    assert view["accept_code_email"] is None

    issued = await app_client.post(f"/api/public/b2b-sign/{token}/accept-code")
    assert issued.status_code == 409, issued.text
    refused = await app_client.post(
        f"/api/public/b2b-sign/{token}/accept",
        json={"code": "123456", "document_ids": [document["id"]]},
    )
    assert refused.status_code == 422, refused.text
    assert "kwalifikowanego" in refused.json()["detail"]


@pytest.mark.asyncio
async def test_expired_code_counts_as_a_failed_attempt(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    esign_env,  # noqa: F811
    monkeypatch,
):
    from app.core.database import AsyncSessionLocal
    from app.models.b2b_signing_request import B2BSigningRequest

    mails = _capture_mails(monkeypatch)
    pkg = await _package(app_client, app_auth_headers, esign_env["admin_id"])
    issued = await app_client.post(f"/api/public/b2b-sign/{pkg['token']}/accept-code")
    assert issued.status_code == 200, issued.text
    code = _code_from(mails[-1])
    async with AsyncSessionLocal() as db:
        request = await db.get(B2BSigningRequest, pkg["request_id"])
        request.accept_code_expires_at = datetime.now(timezone.utc) - timedelta(
            minutes=1
        )
        before = request.contractor_failed_attempts
        await db.commit()

    late = await app_client.post(
        f"/api/public/b2b-sign/{pkg['token']}/accept",
        json={"code": code, "document_ids": [pkg["document"]["id"]]},
    )
    assert late.status_code == 422, late.text
    assert late.json()["detail"] == accept_code.MSG_CODE_EXPIRED
    async with AsyncSessionLocal() as db:
        request = await db.get(B2BSigningRequest, pkg["request_id"])
        assert request.contractor_failed_attempts == before + 1


@pytest.mark.asyncio
async def test_code_that_could_not_be_mailed_does_not_work(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    esign_env,  # noqa: F811
    monkeypatch,
):
    from app.core.database import AsyncSessionLocal
    from app.models.b2b_signing_request import B2BSigningRequest

    _capture_mails(monkeypatch, ok=True)
    pkg = await _package(app_client, app_auth_headers, esign_env["admin_id"])
    _capture_mails(monkeypatch, ok=False)
    failed = await app_client.post(f"/api/public/b2b-sign/{pkg['token']}/accept-code")
    assert failed.status_code == 503, failed.text
    assert failed.json()["detail"] == accept_code.MSG_MAIL_FAILED
    async with AsyncSessionLocal() as db:
        request = await db.get(B2BSigningRequest, pkg["request_id"])
        assert request.accept_code_hash is None
        # Kontraktor może od razu poprosić jeszcze raz.
        assert request.accept_code_sent_at is None
