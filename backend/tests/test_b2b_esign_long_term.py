"""E6 (23.11.2026): dane do długiej weryfikacji (PAdES-LT) w umowie po podpisie
obu stron.

Testowe CA na „liście zaufanych” z responderem OCSP i listą CRL na 127.0.0.1
(``tests/_qualified_ca.py``): walidator i dopisanie DSS pobierają je tym samym
backendem pyHanko co na produkcji, z adresów w certyfikatach.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from io import BytesIO

import pytest
from cryptography.hazmat.primitives.serialization import Encoding
from pyhanko.sign.validation.errors import NoDSSFoundError

from app.core.config import settings as app_config
from app.services.b2b_esign import long_term
from app.services.b2b_esign.qualified import QualifiedValidator
from app.services.b2b_esign.verdict import Fingerprint, builds_on, judge
from tests._qualified_ca import start_ca
from tests._signed_pdf import blank_pdf, sign
from tests.test_b2b_esign import (  # noqa: F401 — fikstura esign_env
    _partner,
    _seed_in_progress,
    _send,
    _token,
    esign_env,
)

CONTRACTOR = "Jan Kowalski"
COMPANY = "Anna Nowak"


@pytest.fixture
async def signed_twice():
    """PDF podpisany przez kontraktora (OCSP) i reprezentanta (CRL)."""
    ca, runner = await start_ca()
    at = datetime.now(timezone.utc) - timedelta(minutes=30)
    data = await sign(
        blank_pdf(),
        CONTRACTOR,
        at,
        field="Podpis1",
        signer=ca.signer(CONTRACTOR, via="ocsp"),
    )
    data = await sign(
        data, COMPANY, at, field="Podpis2", signer=ca.signer(COMPANY, via="crl")
    )
    validator = QualifiedValidator()
    validator._registry = ca.registry()
    try:
        yield ca, validator, data
    finally:
        await runner.cleanup()


async def _accepted(validator: QualifiedValidator, data: bytes) -> bool:
    verdict = judge(
        await validator.validate(data),
        authoritative=validator.authoritative,
        required_signers=[CONTRACTOR],
        any_of_signers=[COMPANY],
    )
    return verdict.accepted


def _dss(data: bytes):
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.validation.dss import DocumentSecurityStore

    return DocumentSecurityStore.read_dss(PdfFileReader(BytesIO(data), strict=False))


@pytest.mark.asyncio
async def test_both_signatures_get_their_revocation_data_in_one_update(
    signed_twice, monkeypatch
):
    ca, validator, data = signed_twice
    monkeypatch.setattr(app_config, "B2B_ESIGN_ADD_LTV", True)
    # Kontrola: plik testowy przechodzi walidację jak umowa podpisana
    # kwalifikowanie przez obie strony.
    report = await validator.validate(data)
    assert [r["level"] for r in report.signature_results] == ["QESig", "QESig"]
    assert await _accepted(validator, data)
    hits_before = (ca.ocsp_hits, ca.crl_hits)
    with pytest.raises(NoDSSFoundError):
        _dss(data)  # przed: brak DSS

    result = await long_term.with_long_term_data(
        data,
        validator=validator,
        still_accepted=lambda candidate: _accepted(validator, candidate),
    )

    assert result != data
    # Pobrane od nowa z adresów w certyfikatach (OCSP i CRL).
    assert ca.ocsp_hits > hits_before[0] and ca.crl_hits > hits_before[1]
    assert builds_on(result, Fingerprint.of(data))
    dss = _dss(result)
    assert len(dss.ocsps) == 1  # kontraktor ma w certyfikacie adres OCSP
    assert len(dss.crls) == 1  # reprezentant ma adres listy CRL
    stored = {cert.dump() for cert in dss.load_certs()}
    assert ca.asn1_cert.dump() in stored
    assert {c.public_bytes(Encoding.DER) for c in ca.issued.values()} <= stored
    assert len(dss.vri_entries) == 2  # wpis VRI dla każdego podpisu
    # Jedna aktualizacja przyrostowa (bez nowego podpisu) i oba podpisy całe.
    assert result.count(b"%%EOF") == data.count(b"%%EOF") + 1
    after = await validator.validate(result)
    assert after.signature_count == 2
    assert [r["indication"] for r in after.signature_results] == [
        "TOTAL_PASSED",
        "TOTAL_PASSED",
    ]
    assert [r["level"] for r in after.signature_results] == ["QESig", "QESig"]


@pytest.mark.asyncio
async def test_failed_fetch_keeps_the_signed_file_and_logs_without_names(
    signed_twice, monkeypatch, caplog
):
    ca, validator, data = signed_twice
    monkeypatch.setattr(app_config, "B2B_ESIGN_ADD_LTV", True)
    ca.down = True
    checked: list[bytes] = []

    async def _still_accepted(candidate: bytes) -> bool:
        checked.append(candidate)
        return True

    with caplog.at_level(logging.INFO, logger="app.services.b2b_esign.long_term"):
        result = await long_term.with_long_term_data(
            data, validator=validator, still_accepted=_still_accepted
        )

    assert result is data
    assert ca.ocsp_hits >= 1  # próbował pobrać z adresu w certyfikacie
    assert checked == []
    warnings = [
        r.getMessage()
        for r in caplog.records
        if r.name == long_term.logger.name and r.levelno == logging.WARNING
    ]
    assert len(warnings) == 1, warnings
    assert "bez danych do długiej weryfikacji" in warnings[0]
    assert all(CONTRACTOR not in m and COMPANY not in m for m in warnings)


@pytest.mark.asyncio
async def test_result_that_fails_validation_is_dropped(signed_twice, monkeypatch):
    _ca, validator, data = signed_twice
    monkeypatch.setattr(app_config, "B2B_ESIGN_ADD_LTV", True)

    async def _rejects(_candidate: bytes) -> bool:
        return False

    result = await long_term.with_long_term_data(
        data, validator=validator, still_accepted=_rejects
    )
    assert result is data


@pytest.mark.asyncio
async def test_timeout_keeps_the_signed_file(signed_twice, monkeypatch):
    import asyncio

    _ca, validator, data = signed_twice
    monkeypatch.setattr(app_config, "B2B_ESIGN_ADD_LTV", True)
    monkeypatch.setattr(long_term, "TIMEOUT_S", 0.05)

    async def _slow(_candidate: bytes) -> bool:
        await asyncio.sleep(1)
        return True

    result = await long_term.with_long_term_data(
        data, validator=validator, still_accepted=_slow
    )
    assert result is data


@pytest.mark.asyncio
async def test_switch_off_changes_nothing_and_fetches_nothing(
    signed_twice, monkeypatch
):
    ca, validator, data = signed_twice
    monkeypatch.setattr(app_config, "B2B_ESIGN_ADD_LTV", False)

    async def _never(_candidate: bytes) -> bool:
        raise AssertionError("bez przełącznika nic nie sprawdzamy")

    result = await long_term.with_long_term_data(
        data, validator=validator, still_accepted=_never
    )
    assert result is data
    assert (ca.ocsp_hits, ca.crl_hits) == (0, 0)


def test_switch_defaults_to_off():
    from app.core.config import Settings

    assert Settings.model_fields["B2B_ESIGN_ADD_LTV"].default is False


@pytest.mark.asyncio
async def test_dss_sidecar_validator_is_left_alone(monkeypatch):
    """Z walidatorem EU DSS nie ma listy zaufanych w procesie: bez LT."""
    from app.services.signing.validation import ValidationService

    monkeypatch.setattr(app_config, "B2B_ESIGN_ADD_LTV", True)

    async def _never(_candidate: bytes) -> bool:
        raise AssertionError

    data = blank_pdf()
    result = await long_term.with_long_term_data(
        data, validator=ValidationService(), still_accepted=_never
    )
    assert result is data


@pytest.mark.asyncio
async def test_final_contract_file_is_the_lt_one_everywhere(
    app_client,
    app_auth_headers,
    esign_env,  # noqa: F811
    monkeypatch,
):
    """Przebieg na bazie: kontraktor i reprezentant wgrywają pliki podpisane
    certyfikatami testowego CA, a walidator to ``QualifiedValidator``.
    Plik końcowy wniosku ma DSS, a Dokumenty kontraktu, kopia kontraktora
    i pobranie podpisanej umowy dostają ten sam plik."""
    from sqlalchemy import select

    from app.api import b2b_esign
    from app.core.database import AsyncSessionLocal
    from app.models.b2b_generated_contract import B2BGeneratedContract
    from app.models.b2b_signing_request import B2BSigningRequest
    from app.models.contract_document import ContractDocument
    from app.models.user import User
    from app.services import storage_service
    from app.services.b2b_esign import mail as esign_mail
    from app.services.b2b_esign import settings as esign_settings

    ca, runner = await start_ca()
    try:
        validator = QualifiedValidator()
        validator._registry = ca.registry()
        source = blank_pdf()

        async def _pdf(_docx: bytes) -> bytes:
            return source

        mails: list[dict] = []

        async def _send_from(db, **kwargs):
            mails.append(kwargs)
            return True, None

        monkeypatch.setattr(b2b_esign, "pdf_from_docx", _pdf)
        monkeypatch.setattr(b2b_esign, "_validator", lambda: validator)
        monkeypatch.setattr(esign_mail, "send_from", _send_from)
        monkeypatch.setattr(app_config, "B2B_ESIGN_ADD_LTV", True)

        admin_id = esign_env["admin_id"]
        async with AsyncSessionLocal() as db:
            # Reprezentant z prawem oznaczania podpisu: plik trafia do Dokumentów.
            await esign_settings.save(
                db,
                esign_settings.EsignSettings(
                    mode="all", company_signer_ids=(admin_id,)
                ),
                actor_id=admin_id,
            )
            await db.commit()
            admin_name = (await db.get(User, admin_id)).name
        scenario = await _seed_in_progress(created_by=admin_id)
        partner = await _partner(scenario["generated_id"])
        sent = await _send(
            app_client, app_auth_headers, scenario["generated_id"], admin_id
        )
        assert sent.status_code == 200, sent.text
        request_id = sent.json()["request"]["id"]
        token = _token(sent.json()["sign_url"])

        at = datetime.now(timezone.utc) - timedelta(minutes=5)
        contractor_pdf = await sign(
            source, partner, at, field="Podpis1", signer=ca.signer(partner, via="ocsp")
        )
        signed = await app_client.post(
            f"/api/public/b2b-sign/{token}",
            files={"file": ("u.pdf", contractor_pdf, "application/pdf")},
        )
        assert signed.status_code == 200, signed.text
        uploaded = await sign(
            contractor_pdf,
            admin_name,
            at,
            field="Podpis2",
            signer=ca.signer(admin_name, via="crl"),
        )
        done = await app_client.post(
            f"/api/b2b-generator/esign/{request_id}/company-sign",
            files={"file": ("u.pdf", uploaded, "application/pdf")},
            headers=app_auth_headers,
        )
        assert done.status_code == 200, done.text
        assert done.json()["status"] == "completed"

        async with AsyncSessionLocal() as db:
            request = await db.get(B2BSigningRequest, request_id)
            final = storage_service.read_b2b_signing_pdf(request.final_pdf_path)
            assert request.validation["long_term"]["size_before"] == len(uploaded)
            row = await db.get(B2BGeneratedContract, scenario["generated_id"])
            assert row.signature_status == "signed_both"
            document = await db.scalar(
                select(ContractDocument).where(
                    ContractDocument.id == row.signed_document_id
                )
            )
        assert final != uploaded and builds_on(final, Fingerprint.of(uploaded))
        assert len(_dss(final).vri_entries) == 2
        assert await _accepted_as(validator, final, partner, admin_name)
        # Jeden plik końcowy wszędzie.
        assert document.content_sha256 == Fingerprint.of(final).sha256
        [attachment] = mails[-1]["attachments"]
        assert attachment.data == final
        copy = await app_client.get(f"/api/public/b2b-sign/{token}/signed-pdf")
        assert copy.content == final
        own = await app_client.get(
            f"/api/b2b-generator/esign/{request_id}/signed-pdf",
            headers=app_auth_headers,
        )
        assert own.content == final
    finally:
        await runner.cleanup()


async def _accepted_as(
    validator: QualifiedValidator, data: bytes, contractor: str, company: str
) -> bool:
    verdict = judge(
        await validator.validate(data),
        authoritative=True,
        required_signers=[contractor],
        any_of_signers=[company],
    )
    return verdict.accepted


async def _sign_with_timestamp(data: bytes, signer, timestamper, field: str) -> bytes:
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign.signers import pdf_signer

    writer = IncrementalPdfFileWriter(BytesIO(data), strict=False)
    out = BytesIO()
    await pdf_signer.PdfSigner(
        pdf_signer.PdfSignatureMetadata(field_name=field),
        signer=signer,
        timestamper=timestamper,
    ).async_sign_pdf(writer, output=out)
    return out.getvalue()


@pytest.mark.asyncio
async def test_signature_timestamp_of_pades_t_gets_its_revocation_data_too(
    monkeypatch,
):
    """KIR i inni dają PAdES-T: znacznik czasu podpisu ma własny certyfikat
    TSA, więc DSS dostaje też jego OCSP."""
    ca, runner = await start_ca()
    try:
        timestamper = ca.timestamper()
        data = await _sign_with_timestamp(
            blank_pdf(), ca.signer(CONTRACTOR, via="ocsp"), timestamper, "Podpis1"
        )
        data = await _sign_with_timestamp(
            data, ca.signer(COMPANY, via="crl"), timestamper, "Podpis2"
        )
        validator = QualifiedValidator()
        validator._registry = ca.registry()
        monkeypatch.setattr(app_config, "B2B_ESIGN_ADD_LTV", True)
        assert await _accepted(validator, data)

        result = await long_term.with_long_term_data(
            data,
            validator=validator,
            still_accepted=lambda candidate: _accepted(validator, candidate),
        )

        assert builds_on(result, Fingerprint.of(data))
        dss = _dss(result)
        stored = {cert.dump() for cert in dss.load_certs()}
        assert timestamper.tsa_cert.dump() in stored
        # Kontraktor i TSA mają adres OCSP; reprezentant listę CRL.
        assert len(dss.ocsps) >= 2
        assert len(dss.crls) == 1
        assert await _accepted(validator, result)
    finally:
        await runner.cleanup()
