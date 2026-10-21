"""Podpis umowy B2B w NEXUSIE (0497) — reguły przyjęcia pliku i przebieg.

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
    migration = (root / "alembic/versions/0497_b2b_signing_requests.py").read_text()
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


async def _send(app_client, headers, generated_id: int, signer_id: int):
    return await app_client.post(
        f"/api/b2b-generator/generated/{generated_id}/esign/send",
        json={
            "contractor_email": "anna@example.com",
            "company_signer_id": signer_id,
            "days": 14,
        },
        headers=headers,
    )


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
    from tests.test_b2b_signature_automation import _seed_bound_scenario

    scenario = await _seed_bound_scenario(created_by=esign_env["admin_id"])
    partner = await _partner(scenario["generated_id"])
    sent = await _send(
        app_client, app_auth_headers, scenario["generated_id"], esign_env["signer_id"]
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["request"]["contractor_name"] == partner
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
    assert stranger.status_code == 403, stranger.text

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
    from tests.test_b2b_signature_automation import _seed_bound_scenario

    scenario = await _seed_bound_scenario(created_by=esign_env["admin_id"])
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
    from tests.test_b2b_signature_automation import _seed_bound_scenario

    scenario = await _seed_bound_scenario(created_by=esign_env["admin_id"])
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
    from tests.test_b2b_signature_automation import _seed_bound_scenario

    bogus = await app_client.post(
        "/api/public/b2b-sign/nie-ma-takiego-linku",
        files={"file": ("u.pdf", SOURCE + b"% podpis\n", "application/pdf")},
    )
    assert bogus.status_code == 404, bogus.text

    scenario = await _seed_bound_scenario(created_by=esign_env["admin_id"])
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
