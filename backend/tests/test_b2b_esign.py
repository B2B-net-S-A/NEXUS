"""Podpis umowy B2B w NEXUSIE (0499) — reguły przyjęcia pliku i przebieg.

Czyste reguły (bez bazy) pilnują wad toru z czerwca z audytu 21.10.2026:
kwalifikowany KAŻDY podpis, brak walidatora = odmowa, obie strony po nazwisku.
Przebieg na bazie podmienia walidator (``_validator``) i zamianę Worda na PDF —
DSS i LibreOffice nie stoją w CI.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from app.services.b2b_esign import settings as esign_settings
from app.services.b2b_esign.verdict import (
    Fingerprint,
    builds_on,
    judge,
    name_matches,
)
from app.services.signing.provider import ValidationReport
from app.services.signing.validation import ValidationService

SOURCE = b"%PDF-1.7\n% umowa do podpisu\n%%EOF\n"


def _report(*sigs: tuple[str, str, str]) -> ValidationReport:
    return ValidationReport(
        is_qes=True,
        signature_count=len(sigs),
        signature_results=[
            {"signer": signer, "indication": indication, "level": level}
            for signer, indication, level in sigs
        ],
    )


# ── czyste reguły ────────────────────────────────────────────────────────────


def test_signed_file_must_extend_the_issued_bytes():
    issued = Fingerprint.of(SOURCE)
    assert builds_on(SOURCE + b"% podpis\n", issued)
    assert not builds_on(SOURCE, issued)  # nic nie dołożono
    assert not builds_on(SOURCE.replace(b"umowa", b"UMOWA") + b"% podpis", issued)


def test_the_same_file_without_a_signature_says_there_is_no_new_signature():
    """Olaf 26.10.2026: wgrał pobrany plik bez podpisu i dostał „To nie jest
    ten sam dokument” — a to JEST ten sam dokument, tylko bez podpisu."""
    from app.services.b2b_esign.verdict import (
        MSG_CHANGED,
        MSG_NOT_SIGNED,
        upload_problem,
    )

    issued = Fingerprint.of(SOURCE)
    assert upload_problem(SOURCE, issued) == MSG_NOT_SIGNED
    assert upload_problem(SOURCE + b"% podpis\n", issued) is None
    assert upload_problem(SOURCE.replace(b"umowa", b"UMOWA"), issued) == MSG_CHANGED
    assert upload_problem(SOURCE[:-10], issued) == MSG_CHANGED


def test_name_from_the_certificate_may_carry_a_middle_name_and_any_order():
    assert name_matches("Jan Kowalski", "CN=Kowalski Jan Piotr, C=PL")
    assert name_matches("Łukasz Żółć", "Common Name: Lukasz Zolc, Country: PL")
    assert not name_matches("Jan Kowalski", "CN=Jan Nowak")
    assert not name_matches("", "CN=Jan Kowalski")


def test_no_authoritative_validator_means_no():
    verdict = judge(
        _report(("Jan Kowalski", "TOTAL_PASSED", "QESig")),
        authoritative=False,
        required_signers=["Jan Kowalski"],
    )
    assert verdict.code == "no_validator"


def test_every_signature_must_be_qualified_not_only_the_first():
    verdict = judge(
        _report(
            ("Jan Kowalski", "TOTAL_PASSED", "QESig"),
            ("Olaf Firma", "TOTAL_PASSED", "AdESig"),
        ),
        authoritative=True,
        required_signers=["Jan Kowalski", "Olaf Firma"],
    )
    assert verdict.code == "not_qualified"


def test_failed_signature_blocks_even_beside_a_good_one():
    verdict = judge(
        _report(
            ("Jan Kowalski", "TOTAL_PASSED", "QESig"),
            ("Ktoś Inny", "TOTAL_FAILED", "QESig"),
        ),
        authoritative=True,
        required_signers=["Jan Kowalski"],
    )
    assert verdict.code == "invalid"


def test_the_named_contractor_has_to_sign():
    verdict = judge(
        _report(("Jan Nowak", "TOTAL_PASSED", "QESig")),
        authoritative=True,
        required_signers=["Jan Kowalski"],
    )
    assert verdict.code == "missing_signer"
    assert "Jan Kowalski" in (verdict.message or "")


def test_both_parties_signed_with_qualified_signatures_is_accepted():
    verdict = judge(
        _report(
            ("CN=Jan Kowalski", "TOTAL_PASSED", "QESig"),
            ("CN=Olaf Firma", "TOTAL_PASSED", "QESig"),
        ),
        authoritative=True,
        required_signers=["Jan Kowalski", "Olaf Firma"],
    )
    assert verdict.accepted


def test_dss_mapping_keeps_the_level_of_every_signature():
    report = ValidationService._map_dss_report(
        {
            "simpleReport": {
                "signatureOrTimestamp": [
                    {
                        "signedBy": "A",
                        "indication": "TOTAL_PASSED",
                        "signatureLevel": "QESig",
                    },
                    {
                        "signedBy": "B",
                        "indication": "TOTAL_PASSED",
                        "signatureLevel": "AdESig",
                    },
                ]
            }
        }
    )
    assert [r["level"] for r in report.signature_results] == ["QESig", "AdESig"]


def test_settings_default_to_off_and_pilot_is_per_account():
    assert esign_settings.parse(None).mode == "off"
    assert esign_settings.parse({"mode": "everyone"}).mode == "off"
    pilot = esign_settings.parse({"mode": "pilot", "pilot_user_ids": [7, "x", -1]})
    assert pilot.pilot_user_ids == frozenset({7})

    class _U:
        def __init__(self, uid: int) -> None:
            self.id = uid

    assert pilot.can_send(_U(7)) and not pilot.can_send(_U(8))  # type: ignore[arg-type]


def test_entrypoint_mirrors_the_signing_table():
    root = Path(__file__).resolve().parents[1]
    entrypoint = (root / "entrypoint.sh").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS b2b_signing_requests" in entrypoint
    assert "uq_b2b_signing_requests_open_per_row" in entrypoint
    migration = (root / "alembic/versions/0499_b2b_signing_requests.py").read_text()
    assert re.search(r'down_revision = "0496_b2b_generated_signed_file"', migration)


# ── przebieg na bazie ────────────────────────────────────────────────────────


class _FakeValidator:
    """Walidator z gotowym raportem — DSS nie stoi w CI."""

    report: ValidationReport = _report()
    authoritative = True
    on_validate: Any = None

    async def validate(self, signed_pdf: bytes) -> ValidationReport:
        if _FakeValidator.on_validate is not None:
            await _FakeValidator.on_validate()
        return _FakeValidator.report


@pytest.fixture
async def esign_env(monkeypatch, app_client: AsyncClient):
    from app.api import b2b_esign
    from app.core.database import AsyncSessionLocal
    from tests.test_b2b_signature_automation import (
        _current_admin_id,
        _headers_for_role,
    )
    from app.models.user import UserRole

    async def _docx(db, row):
        return b"docx"

    async def _pdf(docx: bytes) -> bytes:
        return SOURCE

    monkeypatch.setattr(b2b_esign, "_render_generated_row_docx", _docx)
    monkeypatch.setattr(b2b_esign, "pdf_from_docx", _pdf)
    monkeypatch.setattr(b2b_esign, "_validator", lambda: _FakeValidator())
    _FakeValidator.on_validate = None

    admin_id = await _current_admin_id(app_client)
    signer_headers = await _headers_for_role(app_client, UserRole.delivery_lead)
    signer_id = int(signer_headers["X-Test-User-Id"])
    async with AsyncSessionLocal() as db:
        await esign_settings.save(
            db,
            esign_settings.EsignSettings(mode="all", company_signer_ids=(signer_id,)),
            actor_id=admin_id,
        )
        await db.commit()
    yield {
        "admin_id": admin_id,
        "signer_headers": signer_headers,
        "signer_id": signer_id,
    }
    async with AsyncSessionLocal() as db:
        await esign_settings.save(db, esign_settings.EsignSettings(), actor_id=admin_id)
        await db.commit()


async def _send(app_client, headers, generated_id: int, signer_id: int, days: int = 14):
    return await app_client.post(
        f"/api/b2b-generator/generated/{generated_id}/esign/send",
        json={
            "contractor_email": "anna@example.com",
            "company_signer_id": signer_id,
            "days": days,
        },
        headers=headers,
    )


async def _seed_in_progress(*, created_by: int) -> dict[str, Any]:
    """Wiersz jak po „Pobierz DOCX”: niepodpisany, „W trakcie” (``/render``)."""
    from app.core.database import AsyncSessionLocal
    from app.models.b2b_generated_contract import B2BGeneratedContract
    from tests.test_b2b_signature_automation import _seed_bound_scenario

    scenario = await _seed_bound_scenario(created_by=created_by)
    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, scenario["generated_id"])
        assert row is not None
        row.contract_status = "in_progress"
        await db.commit()
    return scenario


def _token(sign_url: str) -> str:
    return sign_url.rsplit("/", 1)[-1]


async def _partner(generated_id: int) -> str:
    """Kto podpisuje za kontraktora — osoba z umowy, nie z formularza wysyłki."""
    from app.core.database import AsyncSessionLocal
    from app.models.b2b_generated_contract import B2BGeneratedContract

    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, generated_id)
        assert row is not None and row.partner_name
        return row.partner_name


@pytest.mark.asyncio
async def test_contractor_then_company_sign_and_the_request_completes(
    app_client: AsyncClient, app_auth_headers: dict[str, str], esign_env
):

    scenario = await _seed_in_progress(created_by=esign_env["admin_id"])
    partner = await _partner(scenario["generated_id"])
    sent = await _send(
        app_client, app_auth_headers, scenario["generated_id"], esign_env["signer_id"]
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["request"]["contractor_name"] == partner
    # Konto testowe nie ma połączonej skrzynki M365 — link do skopiowania.
    assert sent.json()["mail_sent"] is False
    assert "skrzynka" in (sent.json()["mail_problem"] or "")
    defaults = await app_client.get(
        f"/api/b2b-generator/generated/{scenario['generated_id']}/esign/defaults",
        headers=app_auth_headers,
    )
    assert defaults.status_code == 200, defaults.text
    assert defaults.json()["contractor_name"] == partner
    assert defaults.json()["mailbox_connected"] is False
    token = _token(sent.json()["sign_url"])
    again = await _send(
        app_client, app_auth_headers, scenario["generated_id"], esign_env["signer_id"]
    )
    assert again.status_code == 409, again.text

    view = await app_client.get(f"/api/public/b2b-sign/{token}")
    assert view.status_code == 200 and view.json()["status"] == "waiting"
    pdf = await app_client.get(f"/api/public/b2b-sign/{token}/pdf")
    assert pdf.content == SOURCE

    _FakeValidator.report = _report((f"CN={partner}", "TOTAL_PASSED", "QESig"))
    changed = await app_client.post(
        f"/api/public/b2b-sign/{token}",
        files={
            "file": ("u.pdf", b"%PDF-1.7\n% inna tresc\n% podpis", "application/pdf")
        },
    )
    assert changed.status_code == 422, changed.text
    contractor_pdf = SOURCE + b"% podpis kontraktora\n"
    signed = await app_client.post(
        f"/api/public/b2b-sign/{token}",
        files={"file": ("u.pdf", contractor_pdf, "application/pdf")},
    )
    assert signed.status_code == 200, signed.text
    assert signed.json()["status"] == "signed_by_you"

    request_id = sent.json()["request"]["id"]
    stranger = await app_client.post(
        f"/api/b2b-generator/esign/{request_id}/company-sign",
        files={"file": ("u.pdf", contractor_pdf + b"% firma\n", "application/pdf")},
        headers=app_auth_headers,
    )
    # Obcy nie dowiaduje się, że wniosek istnieje (przegląd bezpieczeństwa).
    assert stranger.status_code == 404, stranger.text

    signer = esign_env["signer_headers"]
    mine = await app_client.get("/api/b2b-generator/esign/mine", headers=signer)
    assert [r["id"] for r in mine.json()] == [request_id]
    own_pdf = await app_client.get(
        f"/api/b2b-generator/esign/{request_id}/pdf", headers=signer
    )
    assert own_pdf.content == contractor_pdf

    from app.core.database import AsyncSessionLocal
    from app.models.user import User

    async with AsyncSessionLocal() as db:
        signer_name = (await db.get(User, esign_env["signer_id"])).name
    final_pdf = contractor_pdf + b"% podpis firmy\n"
    _FakeValidator.report = _report(
        (f"CN={partner}", "TOTAL_PASSED", "QESig"),
        (f"CN={signer_name}", "TOTAL_PASSED", "AdESig"),
    )
    not_qualified = await app_client.post(
        f"/api/b2b-generator/esign/{request_id}/company-sign",
        files={"file": ("u.pdf", final_pdf, "application/pdf")},
        headers=signer,
    )
    assert not_qualified.status_code == 422, not_qualified.text
    _FakeValidator.report = _report(
        (f"CN={partner}", "TOTAL_PASSED", "QESig"),
        (f"CN={signer_name}", "TOTAL_PASSED", "QESig"),
    )
    done = await app_client.post(
        f"/api/b2b-generator/esign/{request_id}/company-sign",
        files={"file": ("u.pdf", final_pdf, "application/pdf")},
        headers=signer,
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "completed"
    closed_link = await app_client.get(f"/api/public/b2b-sign/{token}")
    assert closed_link.status_code == 404


@pytest.mark.asyncio
async def test_withdraw_closes_the_link_and_wins_over_a_running_validation(
    app_client: AsyncClient, app_auth_headers: dict[str, str], esign_env
):

    scenario = await _seed_in_progress(created_by=esign_env["admin_id"])
    partner = await _partner(scenario["generated_id"])
    sent = await _send(
        app_client, app_auth_headers, scenario["generated_id"], esign_env["signer_id"]
    )
    assert sent.status_code == 200, sent.text
    token = _token(sent.json()["sign_url"])
    request_id = sent.json()["request"]["id"]

    async def _withdraw_meanwhile() -> None:
        response = await app_client.post(
            f"/api/b2b-generator/esign/{request_id}/withdraw",
            json={"reason": "Przechodzimy na drogę zwykłą"},
            headers=app_auth_headers,
        )
        assert response.status_code == 200, response.text

    _FakeValidator.report = _report((f"CN={partner}", "TOTAL_PASSED", "QESig"))
    _FakeValidator.on_validate = _withdraw_meanwhile
    late = await app_client.post(
        f"/api/public/b2b-sign/{token}",
        files={"file": ("u.pdf", SOURCE + b"% podpis\n", "application/pdf")},
    )
    _FakeValidator.on_validate = None
    assert late.status_code in (404, 409), late.text
    assert (await app_client.get(f"/api/public/b2b-sign/{token}")).status_code == 404

    resent = await _send(
        app_client, app_auth_headers, scenario["generated_id"], esign_env["signer_id"]
    )
    assert resent.status_code == 200, resent.text


@pytest.mark.asyncio
async def test_sending_needs_the_switch_and_a_listed_company_signer(
    app_client: AsyncClient, app_auth_headers: dict[str, str], esign_env
):
    from app.core.database import AsyncSessionLocal

    scenario = await _seed_in_progress(created_by=esign_env["admin_id"])
    wrong_signer = await _send(
        app_client, app_auth_headers, scenario["generated_id"], esign_env["admin_id"]
    )
    assert wrong_signer.status_code == 422, wrong_signer.text

    async with AsyncSessionLocal() as db:
        await esign_settings.save(
            db, esign_settings.EsignSettings(mode="off"), actor_id=esign_env["admin_id"]
        )
        await db.commit()
    off = await _send(
        app_client, app_auth_headers, scenario["generated_id"], esign_env["signer_id"]
    )
    assert off.status_code == 403, off.text


def test_token_is_stored_only_as_a_hash():
    from app.services.b2b_esign.service import new_token, token_hash

    token, digest = new_token()
    assert digest == hashlib.sha256(token.encode()).hexdigest() == token_hash(token)
    assert token not in digest


@pytest.mark.asyncio
async def test_bogus_link_is_refused_before_the_file_and_failures_are_capped(
    app_client: AsyncClient, app_auth_headers: dict[str, str], esign_env
):
    """Przegląd bezpieczeństwa 21.10.2026: fałszywy link nie przyjmuje pliku,
    a jeden link nie uruchamia walidacji w nieskończoność."""
    from app.services.b2b_esign import service

    bogus = await app_client.post(
        "/api/public/b2b-sign/nie-ma-takiego-linku",
        files={"file": ("u.pdf", SOURCE + b"% podpis\n", "application/pdf")},
    )
    assert bogus.status_code == 404, bogus.text

    scenario = await _seed_in_progress(created_by=esign_env["admin_id"])
    sent = await _send(
        app_client, app_auth_headers, scenario["generated_id"], esign_env["signer_id"]
    )
    token = _token(sent.json()["sign_url"])
    _FakeValidator.report = _report(("CN=Ktoś Obcy", "TOTAL_PASSED", "QESig"))
    for _ in range(service.MAX_FAILED_ATTEMPTS):
        wrong = await app_client.post(
            f"/api/public/b2b-sign/{token}",
            files={"file": ("u.pdf", SOURCE + b"% podpis\n", "application/pdf")},
        )
        assert wrong.status_code == 422, wrong.text
    capped = await app_client.post(
        f"/api/public/b2b-sign/{token}",
        files={"file": ("u.pdf", SOURCE + b"% podpis\n", "application/pdf")},
    )
    assert capped.status_code == 429, capped.text


# ── walidator pyHanko z listą UE (bez sieci) ────────────────────────────────


def test_only_a_qualified_esign_certificate_on_a_qscd_is_qesig():
    from types import SimpleNamespace

    from pyhanko.sign.validation.qualified.q_status import (
        QcPrivateKeyManagementType as Key,
    )
    from pyhanko.sign.validation.qualified.tsp import QcCertType

    from app.services.b2b_esign.qualified import level_of

    def q(qualified: bool, qc_type: QcCertType, key: Key):
        return SimpleNamespace(
            status=SimpleNamespace(
                qualified=qualified, qc_type=qc_type, qc_key_security=key
            )
        )

    assert level_of(q(True, QcCertType.QC_ESIGN, Key.QSCD)) == "QESig"
    # SimplySign, mSzafir: klucz na zdalnym QSCD zarządzanym przez dostawcę.
    assert level_of(q(True, QcCertType.QC_ESIGN, Key.QSCD_DELEGATED)) == "QESig"
    assert level_of(q(True, QcCertType.QC_ESIGN, Key.UNKNOWN)) == "AdESig"
    # Pieczęć firmy nie zastępuje podpisu osoby.
    assert level_of(q(True, QcCertType.QC_ESEAL, Key.QSCD)) == "AdESig"
    assert level_of(q(False, QcCertType.QC_ESIGN, Key.QSCD)) == "AdESig"
    assert level_of(None) == "AdESig"


@pytest.mark.asyncio
async def test_without_the_eu_list_the_validator_is_not_authoritative(monkeypatch):
    from app.services.b2b_esign import qualified

    async def _down():
        raise OSError("ec.europa.eu nie odpowiada")

    monkeypatch.setattr(qualified, "_registry", None)
    monkeypatch.setattr(qualified, "_fetch_registry", _down)
    validator = qualified.QualifiedValidator()
    report = await validator.validate(SOURCE + b"% podpis\n")
    assert validator.authoritative is False
    assert report.sub_indication == "EU_TRUSTED_LIST_UNAVAILABLE"
    verdict = judge(
        report, authoritative=validator.authoritative, required_signers=["Jan Kowalski"]
    )
    assert verdict.code == "no_validator"


@pytest.mark.asyncio
async def test_failed_refresh_keeps_the_last_good_eu_list(monkeypatch):
    from app.services.b2b_esign import qualified

    sentinel = object()
    calls: list[str] = []

    async def _ok():
        calls.append("ok")
        return sentinel

    async def _down():
        calls.append("down")
        raise OSError("timeout")

    monkeypatch.setattr(qualified, "_registry", None)
    monkeypatch.setattr(qualified, "_loaded_at", 0.0)
    monkeypatch.setattr(qualified, "_fetch_registry", _ok)
    assert await qualified.trusted_registry(now=1000.0) is sentinel
    # Świeża lista — bez ponownego pobrania.
    assert await qualified.trusted_registry(now=1000.0 + 3600) is sentinel
    monkeypatch.setattr(qualified, "_fetch_registry", _down)
    stale = 1000.0 + qualified.REFRESH_HOURS * 3600 + 1
    assert await qualified.trusted_registry(now=stale) is sentinel
    assert calls == ["ok", "down"]


# ── po podpisie obu stron (PR 5) ─────────────────────────────────────────────


async def _sign_both(
    app_client,
    sender_headers,
    signer_headers,
    generated_id,
    signer_id,
    contractor_days_ago: int = 0,
):
    from datetime import timedelta

    from app.core.database import AsyncSessionLocal
    from app.models.b2b_signing_request import B2BSigningRequest
    from app.models.user import User

    partner = await _partner(generated_id)
    sent = await _send(app_client, sender_headers, generated_id, signer_id)
    assert sent.status_code == 200, sent.text
    token = _token(sent.json()["sign_url"])
    request_id = sent.json()["request"]["id"]
    _FakeValidator.report = _report((f"CN={partner}", "TOTAL_PASSED", "QESig"))
    contractor_pdf = SOURCE + b"% podpis kontraktora\n"
    signed = await app_client.post(
        f"/api/public/b2b-sign/{token}",
        files={"file": ("u.pdf", contractor_pdf, "application/pdf")},
    )
    assert signed.status_code == 200, signed.text
    async with AsyncSessionLocal() as db:
        signer_name = (await db.get(User, signer_id)).name
        if contractor_days_ago:
            request = await db.get(B2BSigningRequest, request_id)
            request.contractor_signed_at -= timedelta(days=contractor_days_ago)
            await db.commit()
    _FakeValidator.report = _report(
        (f"CN={partner}", "TOTAL_PASSED", "QESig"),
        (f"CN={signer_name}", "TOTAL_PASSED", "QESig"),
    )
    done = await app_client.post(
        f"/api/b2b-generator/esign/{request_id}/company-sign",
        files={"file": ("u.pdf", contractor_pdf + b"% firma\n", "application/pdf")},
        headers=signer_headers,
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "completed"
    return request_id


async def _notices(user_id: int, request_id: int) -> list[str]:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.notification import Notification

    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(Notification.title).where(
                Notification.user_id == user_id,
                Notification.related_entity_type == "b2b_signing_request",
                Notification.related_entity_id == request_id,
            )
        )
        return list(rows.all())


@pytest.mark.asyncio
async def test_both_signatures_run_the_signed_automation_with_the_file(
    app_client: AsyncClient, app_auth_headers: dict[str, str], esign_env
):
    """Reprezentant z prawem oznaczania podpisu: kontrakt, zamówienie,
    „Zatrudniony” i podpisany PDF w Dokumentach — jak „Oznacz jako podpisaną”."""
    from app.core.database import AsyncSessionLocal
    from app.models.b2b_generated_contract import B2BGeneratedContract

    admin_id = esign_env["admin_id"]
    async with AsyncSessionLocal() as db:
        await esign_settings.save(
            db,
            esign_settings.EsignSettings(mode="all", company_signer_ids=(admin_id,)),
            actor_id=admin_id,
        )
        await db.commit()
    scenario = await _seed_in_progress(created_by=admin_id)
    request_id = await _sign_both(
        app_client,
        app_auth_headers,
        app_auth_headers,
        scenario["generated_id"],
        admin_id,
    )
    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, scenario["generated_id"])
        assert row is not None
        assert row.signature_status == "signed_both"
        assert row.signature_source == "validated_upload"
        assert row.contract_id is not None and row.signed_document_id is not None
    titles = await _notices(admin_id, request_id)
    assert any("podpisana przez obie strony" in t for t in titles), titles


@pytest.mark.asyncio
async def test_signing_day_is_the_contractor_day_not_the_company_day(
    app_client: AsyncClient, app_auth_headers: dict[str, str], esign_env
):
    """Kontraktor podpisał dwa dni przed reprezentantem firmy — „Data
    podpisania” w eksporcie „Placementy” to dzień podpisu kontraktora (0514)."""
    from datetime import datetime, timedelta, timezone

    from app.core.database import AsyncSessionLocal
    from app.core.scheduling import business_date, business_today
    from app.models.b2b_generated_contract import B2BGeneratedContract
    from app.models.b2b_signing_request import B2BSigningRequest

    admin_id = esign_env["admin_id"]
    async with AsyncSessionLocal() as db:
        await esign_settings.save(
            db,
            esign_settings.EsignSettings(mode="all", company_signer_ids=(admin_id,)),
            actor_id=admin_id,
        )
        await db.commit()
    scenario = await _seed_in_progress(created_by=admin_id)
    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, scenario["generated_id"])
        row.created_at = datetime.now(timezone.utc) - timedelta(days=10)
        await db.commit()
    request_id = await _sign_both(
        app_client,
        app_auth_headers,
        app_auth_headers,
        scenario["generated_id"],
        admin_id,
        contractor_days_ago=2,
    )
    async with AsyncSessionLocal() as db:
        request = await db.get(B2BSigningRequest, request_id)
        row = await db.get(B2BGeneratedContract, scenario["generated_id"])
        assert row is not None and row.signature_status == "signed_both"
        assert row.signed_on == business_date(request.contractor_signed_at)
        assert row.signed_on < business_today()


@pytest.mark.asyncio
async def test_without_the_confirm_permission_the_sender_is_asked_to_finish(
    app_client: AsyncClient, app_auth_headers: dict[str, str], esign_env
):
    """Reprezentant bez zakresu klienta: podpis zostaje, kontrakt nie powstaje,
    nadawca dostaje dzwonek „oznacz ją w rejestrze” i może pobrać plik."""
    from app.core.database import AsyncSessionLocal
    from app.models.b2b_generated_contract import B2BGeneratedContract

    scenario = await _seed_in_progress(created_by=esign_env["admin_id"])
    request_id = await _sign_both(
        app_client,
        app_auth_headers,
        esign_env["signer_headers"],
        scenario["generated_id"],
        esign_env["signer_id"],
    )
    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, scenario["generated_id"])
        assert row is not None and row.signature_status == "unsigned"
    titles = await _notices(esign_env["admin_id"], request_id)
    assert any("oznacz ją w rejestrze" in t for t in titles), titles
    pdf = await app_client.get(
        f"/api/b2b-generator/esign/{request_id}/signed-pdf", headers=app_auth_headers
    )
    assert pdf.status_code == 200 and pdf.content.endswith(b"% firma\n")
    # Audyt 22.10, F45: rejestr pokazuje nadawcy „Pobierz podpisaną umowę”.
    item = await _register_item(app_client, app_auth_headers, scenario["generated_id"])
    assert item["can_download_signed_esign"] is True


# ── nazwa pliku i termin przypomnienia (prośby Sandry i Klaudii, 26.10.2026) ──


def test_messages_for_the_contractor_have_no_em_dash():
    """Klaudia, 26.10.2026: strona dla konsultanta bez myślników „—”."""
    from app.services.b2b_esign import service, verdict

    contractor_messages = [
        service.MSG_LINK,
        service.MSG_ALREADY_SIGNED,
        service.MSG_CLOSED,
        service.MSG_RACE,
        service.MSG_TOO_BIG,
        service.MSG_TOO_MANY_ATTEMPTS,
        verdict.MSG_NOT_PDF,
        verdict.MSG_CHANGED,
        verdict.MSG_NOT_SIGNED,
    ]
    assert [m for m in contractor_messages if "—" in m] == []


def test_contract_file_name_is_number_then_surname_first_without_diacritics():
    from app.services.b2b_contract_filename import contract_file_name

    assert (
        contract_file_name("1555/2026", "Jan Kowalski", ext="pdf")
        == "Umowa B2B 1555-2026 Kowalski Jan.pdf"
    )
    assert (
        contract_file_name(
            "1555/2026", "Maria Anna Nowak-Kowalska", suffix="podpisana", ext="pdf"
        )
        == "Umowa B2B 1555-2026 Nowak-Kowalska Maria Anna podpisana.pdf"
    )
    # „ł” nie rozkłada się w NFKD — bez osobnej zamiany znikało z nazwy.
    assert (
        contract_file_name("1555/2026", "  Łucja   Żółć ", ext="docx")
        == "Umowa B2B 1555-2026 Zolc Lucja.docx"
    )
    # Cudzysłów i ukośnik z danych nie psują nagłówka Content-Disposition.
    assert (
        contract_file_name("15/2026", 'Jan "Kot" Kos/ki', ext="pdf")
        == "Umowa B2B 15-2026 Kos ki Jan Kot.pdf"
    )
    assert contract_file_name(None, None, ext="pdf") == "Umowa B2B.pdf"


def test_contractor_reminder_comes_a_day_before_the_deadline():
    from datetime import datetime, timedelta, timezone

    from app.tasks.b2b_esign_sweeper import contractor_reminder_at

    sent = datetime(2026, 10, 26, 10, 0, tzinfo=timezone.utc)
    for days, before in (
        (3, timedelta(days=1)),
        (5, timedelta(days=1)),
        (7, timedelta(days=1)),
    ):
        expires = sent + timedelta(days=days)
        assert contractor_reminder_at(sent, expires) == expires - before
    # Przy jednym dniu „dzień przed końcem” to chwila wysyłki — połowa terminu.
    one_day = sent + timedelta(days=1)
    assert contractor_reminder_at(sent, one_day) == sent + timedelta(hours=12)


# ── wygasanie i przypomnienia (PR 4b) ────────────────────────────────────────


@pytest.mark.asyncio
async def test_sweeper_reminds_a_day_before_the_deadline_once_then_expires_the_link(
    app_client: AsyncClient, app_auth_headers: dict[str, str], esign_env
):
    from datetime import datetime, timedelta, timezone

    from app.core.database import AsyncSessionLocal
    from app.models.b2b_signing_request import B2BSigningRequest
    from app.tasks import b2b_esign_sweeper

    scenario = await _seed_in_progress(created_by=esign_env["admin_id"])
    sent = await _send(
        app_client,
        app_auth_headers,
        scenario["generated_id"],
        esign_env["signer_id"],
        days=3,
    )
    request_id = sent.json()["request"]["id"]
    token = _token(sent.json()["sign_url"])
    now = datetime.now(timezone.utc)

    assert await b2b_esign_sweeper._handle(request_id, now + timedelta(days=1)) is None
    assert (
        await b2b_esign_sweeper._handle(request_id, now + timedelta(days=2, minutes=1))
        == "reminded"
    )
    # Jedno przypomnienie na termin — kolejny przegląd przed końcem nic nie wysyła.
    assert (
        await b2b_esign_sweeper._handle(request_id, now + timedelta(days=2, hours=12))
        is None
    )
    async with AsyncSessionLocal() as db:
        request = await db.get(B2BSigningRequest, request_id)
        assert request is not None and request.last_reminder_at is not None
    titles = await _notices(esign_env["admin_id"], request_id)
    assert any("czeka na podpis kontraktora" in t for t in titles), titles

    assert (
        await b2b_esign_sweeper._handle(request_id, now + timedelta(days=3, minutes=1))
        == "expired"
    )
    async with AsyncSessionLocal() as db:
        request = await db.get(B2BSigningRequest, request_id)
        assert request is not None and request.status == "expired"
    assert (await app_client.get(f"/api/public/b2b-sign/{token}")).status_code == 404
    titles = await _notices(esign_env["admin_id"], request_id)
    assert any("wygasł" in t for t in titles), titles


# ── wniosek w toku a zmiany umowy (code review 21.10.2026) ───────────────────


def test_only_an_exact_qualified_signature_level_counts():
    for level in ("QESeal", "Indeterminate QESig", "QESig?", "AdESig-QC"):
        verdict = judge(
            _report(("CN=Jan Kowalski", "TOTAL_PASSED", level)),
            authoritative=True,
            required_signers=["Jan Kowalski"],
        )
        assert verdict.code == "not_qualified", level


@pytest.mark.asyncio
async def test_open_request_blocks_correction_and_closes_on_manual_paths(
    app_client: AsyncClient, app_auth_headers: dict[str, str], esign_env
):
    """Po wysyłce PDF jest zamrożony: „Popraw” odmawia, a „Oznacz jako
    podpisaną” i „Anulowana” zamykają wniosek — link przestaje działać."""
    from tests.test_b2b_signature_automation import _confirm

    scenario = await _seed_in_progress(created_by=esign_env["admin_id"])
    sent = await _send(
        app_client, app_auth_headers, scenario["generated_id"], esign_env["signer_id"]
    )
    token = _token(sent.json()["sign_url"])
    form = await app_client.get(
        f"/api/b2b-generator/generated/{scenario['generated_id']}/form",
        headers=app_auth_headers,
    )
    assert form.status_code == 409, form.text
    assert "zwykłą drogę" in form.json()["detail"]

    confirmed = await _confirm(app_client, app_auth_headers, scenario["generated_id"])
    assert confirmed.status_code == 200, confirmed.text
    assert (await app_client.get(f"/api/public/b2b-sign/{token}")).status_code == 404

    other = await _seed_in_progress(created_by=esign_env["admin_id"])
    sent = await _send(
        app_client, app_auth_headers, other["generated_id"], esign_env["signer_id"]
    )
    token = _token(sent.json()["sign_url"])
    cancelled = await app_client.patch(
        f"/api/b2b-generator/generated/{other['generated_id']}",
        json={"contract_status": "cancelled"},
        headers=app_auth_headers,
    )
    assert cancelled.status_code == 200, cancelled.text
    assert (await app_client.get(f"/api/public/b2b-sign/{token}")).status_code == 404


@pytest.mark.asyncio
async def test_unexpected_confirm_failure_still_tells_the_sender(
    app_client: AsyncClient, app_auth_headers: dict[str, str], esign_env, monkeypatch
):
    """Błąd automatyki inny niż HTTP nie daje 500 po zapisanym podpisie —
    nadawca dostaje „oznacz ją w rejestrze”."""
    from app.api import b2b_esign
    from app.core.database import AsyncSessionLocal

    async def _boom(**kwargs):
        raise RuntimeError("employment automation returned no ClientOrder")

    monkeypatch.setattr(b2b_esign, "confirm_generated_contract_fully_signed", _boom)
    admin_id = esign_env["admin_id"]
    async with AsyncSessionLocal() as db:
        await esign_settings.save(
            db,
            esign_settings.EsignSettings(mode="all", company_signer_ids=(admin_id,)),
            actor_id=admin_id,
        )
        await db.commit()
    scenario = await _seed_in_progress(created_by=admin_id)
    request_id = await _sign_both(
        app_client,
        app_auth_headers,
        app_auth_headers,
        scenario["generated_id"],
        admin_id,
    )
    titles = await _notices(admin_id, request_id)
    assert any("oznacz ją w rejestrze" in t for t in titles), titles


# ── etap 1b: reszta systemu wie, że umowa jest w podpisie (22.10.2026) ───────


def test_signature_bells_reach_the_recruiter_who_sent_the_contract():
    """Dzwonki podpisu stoją za sekcją Generatora (Sourcing), nie Delivery —
    rekruter bez Delivery dostaje informację o swojej umowie."""
    from app.models.notification import NotificationType
    from app.services.notification_access import NOTIFICATION_SECTION_BY_TYPE
    from app.services.section_permissions import ProductSection

    for ntype in (
        NotificationType.signature_sent,
        NotificationType.signature_signed,
        NotificationType.signature_failed,
    ):
        assert NOTIFICATION_SECTION_BY_TYPE[ntype] == ProductSection.sourcing


@pytest.mark.asyncio
async def test_open_request_blocks_manual_confirm_requests_and_manual_hire(
    app_client: AsyncClient, app_auth_headers: dict[str, str], esign_env
):
    scenario = await _seed_in_progress(created_by=esign_env["admin_id"])
    sent = await _send(
        app_client, app_auth_headers, scenario["generated_id"], esign_env["signer_id"]
    )
    assert sent.status_code == 200, sent.text

    asked = await app_client.post(
        f"/api/b2b-generator/generated/{scenario['generated_id']}/signature-request",
        headers=app_auth_headers,
    )
    assert asked.status_code == 409, asked.text
    assert "zwykłą drogę" in asked.json()["detail"]

    moved = await app_client.post(
        "/api/pipeline/move",
        json={
            "candidate_id": scenario["candidate_id"],
            "job_id": scenario["job_id"],
            "stage": "hired",
            "hired_signed_via": "b2b_offline",
        },
        headers=app_auth_headers,
    )
    assert moved.status_code == 409, moved.text
    assert moved.json()["detail"]["code"] == "ESIGN_IN_PROGRESS"


def test_history_lists_the_sending_signatures_and_how_it_ended():
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace

    from app.services.b2b_esign.history import esign_history

    t0 = datetime(2026, 10, 21, 13, 0, tzinfo=timezone.utc)
    base = dict(
        sent_by=7,
        last_reminder_at=None,
        contractor_signed_at=None,
        completed_at=None,
        closed_at=None,
        closed_by=None,
        close_reason=None,
        company_signer_id=9,
    )
    withdrawn = SimpleNamespace(
        id=1,
        status="withdrawn",
        sent_at=t0,
        **{
            **base,
            "closed_at": t0 + timedelta(hours=1),
            "closed_by": 7,
            "close_reason": "Przejście na drogę zwykłą",
        },
    )
    completed = SimpleNamespace(
        id=2,
        status="completed",
        sent_at=t0 + timedelta(days=1),
        **{
            **base,
            "last_reminder_at": t0 + timedelta(days=4),
            "contractor_signed_at": t0 + timedelta(days=5),
            "completed_at": t0 + timedelta(days=6),
        },
    )
    expired = SimpleNamespace(
        id=3,
        status="expired",
        sent_at=t0 + timedelta(days=7),
        **{**base, "closed_at": t0 + timedelta(days=21)},
    )

    entries = esign_history([completed, expired, withdrawn])

    assert [e.label for e in entries] == [
        "Wysłana do podpisu w NEXUSIE",
        "Wysyłka wycofana — Przejście na drogę zwykłą",
        "Wysłana do podpisu w NEXUSIE",
        "Przypomnienie do kontraktora",
        "Kontraktor podpisał — podpis kwalifikowany sprawdzony",
        "Podpis za B2B Network — umowa podpisana przez obie strony",
        "Wysłana do podpisu w NEXUSIE",
        "Link do podpisu wygasł",
    ]
    assert entries[5].user_id == 9
    assert len({e.key for e in entries}) == len(entries)


@pytest.mark.asyncio
async def test_card_history_and_signer_list_know_the_contract_is_in_signing(
    app_client: AsyncClient, app_auth_headers: dict[str, str], esign_env
):
    from app.core.database import AsyncSessionLocal
    from app.services.agreement_status import agreement_status_for_pairs

    scenario = await _seed_in_progress(created_by=esign_env["admin_id"])
    generated_id = scenario["generated_id"]
    partner = await _partner(generated_id)
    sent = await _send(
        app_client, app_auth_headers, generated_id, esign_env["signer_id"]
    )
    assert sent.status_code == 200, sent.text

    async with AsyncSessionLocal() as db:
        cards = await agreement_status_for_pairs(
            db, job_id=scenario["job_id"], candidate_ids=[scenario["candidate_id"]]
        )
    esign = cards[scenario["candidate_id"]]["esign"]
    assert esign["status"] == "sent" and esign["expires_at"]

    _FakeValidator.report = _report((f"CN={partner}", "TOTAL_PASSED", "QESig"))
    signed = await app_client.post(
        f"/api/public/b2b-sign/{_token(sent.json()['sign_url'])}",
        files={"file": ("u.pdf", SOURCE + b"% podpis\n", "application/pdf")},
    )
    assert signed.status_code == 200, signed.text

    mine = await app_client.get(
        "/api/b2b-generator/esign/mine", headers=esign_env["signer_headers"]
    )
    assert mine.status_code == 200, mine.text
    waiting = [r for r in mine.json() if r["generated_contract_id"] == generated_id]
    assert waiting and waiting[0]["contract_number"]

    history = await app_client.get(
        f"/api/b2b-generator/generated/{generated_id}/status-history",
        headers=app_auth_headers,
    )
    assert history.status_code == 200, history.text
    esign_labels = [e["label"] for e in history.json() if e["kind"] == "esign"]
    assert esign_labels == [
        "Wysłana do podpisu w NEXUSIE",
        "Kontraktor podpisał — podpis kwalifikowany sprawdzony",
    ]


def test_reminder_after_the_contractor_signed_goes_to_the_company_signer():
    """Audyt 22.10, F48: po podpisie kontraktora zamiatacz ponagla reprezentanta
    firmy — historia nie może pisać „Przypomnienie do kontraktora”."""
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace

    from app.services.b2b_esign.history import esign_history

    t0 = datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc)
    waiting = SimpleNamespace(
        id=4,
        status="contractor_signed",
        sent_at=t0 - timedelta(days=2),
        sent_by=7,
        last_reminder_at=t0 + timedelta(days=3),
        contractor_signed_at=t0,
        completed_at=None,
        closed_at=None,
        closed_by=None,
        close_reason=None,
        company_signer_id=9,
    )

    labels = [e.label for e in esign_history([waiting])]

    assert labels == [
        "Wysłana do podpisu w NEXUSIE",
        "Kontraktor podpisał — podpis kwalifikowany sprawdzony",
        "Przypomnienie do podpisu za B2B Network",
    ]


@pytest.mark.asyncio
async def test_sweeper_skips_a_request_closed_after_the_due_list(monkeypatch):
    """Audyt 22.10, F106: wniosek wycofany albo podpisany między listą a blokadą
    nie dostaje przypomnienia — bez dzwonka i bez maila do kontraktora."""
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace

    from app.tasks import b2b_esign_sweeper

    now = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)
    calls: list[str] = []

    for status in ("withdrawn", "completed", "expired"):
        request = SimpleNamespace(
            id=12,
            status=status,
            generated_contract_id=5,
            sent_at=now - timedelta(days=4),
            expires_at=now + timedelta(days=10),
            contractor_signed_at=None,
            last_reminder_at=None,
            sent_by=7,
            company_signer_id=9,
            contractor_email="anna@example.com",
            contractor_name="Anna",
        )

        class _Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def scalar(self, _stmt, _request=request):
                return _request

            async def get(self, _model, _id):
                return SimpleNamespace(contract_number="B2B/1", candidate_id=3)

            async def commit(self):
                calls.append("commit")

        async def _emit(*_a, **_k):
            calls.append("notify")

        async def _send_from(*_a, **_k):
            calls.append("mail")

        monkeypatch.setattr(b2b_esign_sweeper, "AsyncSessionLocal", _Session)
        monkeypatch.setattr(b2b_esign_sweeper, "emit_notification", _emit)
        monkeypatch.setattr(b2b_esign_sweeper.esign_mail, "send_from", _send_from)

        assert await b2b_esign_sweeper._handle(12, now) is None, status
        assert request.last_reminder_at is None, status
    assert calls == []


async def _register_item(app_client, headers, generated_id: int) -> dict[str, Any]:
    from app.core.database import AsyncSessionLocal
    from app.models.b2b_generated_contract import B2BGeneratedContract

    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, generated_id)
        assert row is not None
        number = row.contract_number
    listed = await app_client.get(
        "/api/b2b-generator/generated", headers=headers, params={"q": number}
    )
    assert listed.status_code == 200, listed.text
    return next(i for i in listed.json() if i["id"] == generated_id)


@pytest.mark.asyncio
async def test_contract_in_nexus_signing_or_signed_there_cannot_be_deleted(
    app_client: AsyncClient, app_auth_headers: dict[str, str], esign_env
):
    """Audyt 22.10, F44: kaskada FK kasowała wniosek razem z podpisem
    kontraktora albo obu stron. Usunąć można dopiero po wycofaniu wysyłki."""
    from app.core.database import AsyncSessionLocal
    from app.models.b2b_generated_contract import B2BGeneratedContract
    from app.models.b2b_signing_request import B2BSigningRequest

    scenario = await _seed_in_progress(created_by=esign_env["admin_id"])
    generated_id = scenario["generated_id"]
    sent = await _send(
        app_client, app_auth_headers, generated_id, esign_env["signer_id"]
    )
    assert sent.status_code == 200, sent.text
    request_id = sent.json()["request"]["id"]

    assert (await _register_item(app_client, app_auth_headers, generated_id))[
        "can_delete"
    ] is False
    deleted = await app_client.delete(
        f"/api/b2b-generator/generated/{generated_id}", headers=app_auth_headers
    )
    assert deleted.status_code == 409, deleted.text
    assert "zwykłą drogę" in deleted.json()["detail"]

    # Obie strony podpisały, ale automatyka nie oznaczyła wiersza.
    async with AsyncSessionLocal() as db:
        request = await db.get(B2BSigningRequest, request_id)
        assert request is not None
        request.status = "completed"
        request.contractor_token_hash = None
        await db.commit()
    assert (await _register_item(app_client, app_auth_headers, generated_id))[
        "can_delete"
    ] is False
    deleted = await app_client.delete(
        f"/api/b2b-generator/generated/{generated_id}", headers=app_auth_headers
    )
    assert deleted.status_code == 409, deleted.text
    async with AsyncSessionLocal() as db:
        assert await db.get(B2BGeneratedContract, generated_id) is not None
        assert await db.get(B2BSigningRequest, request_id) is not None

    # Wycofana wysyłka nie blokuje usunięcia.
    async with AsyncSessionLocal() as db:
        request = await db.get(B2BSigningRequest, request_id)
        assert request is not None
        request.status = "withdrawn"
        await db.commit()
    assert (await _register_item(app_client, app_auth_headers, generated_id))[
        "can_delete"
    ] is True
    deleted = await app_client.delete(
        f"/api/b2b-generator/generated/{generated_id}", headers=app_auth_headers
    )
    assert deleted.status_code == 204, deleted.text


@pytest.mark.asyncio
async def test_withdraw_stays_available_after_the_switch_goes_off(
    app_client: AsyncClient, app_auth_headers: dict[str, str], esign_env
):
    """Audyt 22.10, F46: przełącznik dotyczy wysyłki, nie wycofania — wniosek
    z pilotażu musi dać się przenieść na drogę zwykłą."""
    from app.core.database import AsyncSessionLocal

    scenario = await _seed_in_progress(created_by=esign_env["admin_id"])
    generated_id = scenario["generated_id"]
    sent = await _send(
        app_client, app_auth_headers, generated_id, esign_env["signer_id"]
    )
    assert sent.status_code == 200, sent.text
    async with AsyncSessionLocal() as db:
        await esign_settings.save(
            db, esign_settings.EsignSettings(mode="off"), actor_id=esign_env["admin_id"]
        )
        await db.commit()

    item = await _register_item(app_client, app_auth_headers, generated_id)
    assert item["can_send_esign"] is False
    assert item["can_withdraw_esign"] is True
