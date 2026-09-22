"""SIG-01..05 — finalizacja podpisu tylko przy pozytywnym wyniku, właściwym
pliku i właściwych stronach.

Ścieżki odmowy są sprawdzane na lekkim zastępniku sprawy (jak w
``test_signature_link_revocation``): każda odmowa zapada, zanim finalizacja
dotknie bazy, więc ``db`` to ``AsyncMock``, który nie może zostać użyty.
Ścieżka sukcesu z prawdziwą bazą jest w ``test_contract_lifecycle_invariant``.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.models.document_signature import SignatureStatus
from app.services.signing import sender as signing_sender
from app.services.signing.provider import ValidationReport
from app.services.signing.validation import ValidationService

BACKEND = Path(__file__).resolve().parents[1]
SOURCE = b"%PDF-1.7 umowa-zrodlowa"
SIGNED = SOURCE + b"\n% przyrostowy podpis PAdES"


class _Provider:
    def __init__(self, report: ValidationReport) -> None:
        self._report = report

    async def validate(self, pdf: bytes) -> ValidationReport:
        return self._report


def _sig(signature_type: str = "QES", *, with_source: bool = True):
    sig = SimpleNamespace(
        id=7,
        status=SignatureStatus.sent,
        provider="upload_validate",
        signature_type=signature_type,
        contract_id=1,
        validation_report=None,
        signer_first_name="Łukasz",
        signer_last_name="Żółć",
        sender_user_id=1,
    )
    if with_source:
        signing_sender.record_source_pdf(sig, SOURCE)
    return sig


def _passed(*signers: str, indication: str = "TOTAL_PASSED", is_qes: bool = True):
    return ValidationReport(
        is_qes=is_qes,
        indication=indication,
        signature_count=len(signers),
        signers=list(signers),
        signature_results=[{"signer": s, "indication": indication} for s in signers],
    )


async def _finalize(monkeypatch, sig, report, pdf=SIGNED):
    monkeypatch.setattr(settings, "DSS_VALIDATION_URL", "http://dss.internal")
    monkeypatch.setattr(signing_sender, "get_provider", lambda _n: _Provider(report))
    db = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await signing_sender.finalize_signed_pdf(db, sig, pdf, moved_by=1)
    db.flush.assert_not_called()
    db.add.assert_not_called()
    assert sig.status is SignatureStatus.sent, "odmowa zmieniła stan sprawy"
    return exc.value


# ── SIG-01: tylko jawnie pozytywny wynik KAŻDEGO podpisu ────────────────────


async def test_qes_total_failed_is_never_completed(monkeypatch):
    report = _passed("Lukasz Zolc", indication="TOTAL_FAILED")
    err = await _finalize(monkeypatch, _sig(), report)
    assert err.status_code == 422
    assert "TOTAL_FAILED" in err.detail


async def test_ades_indeterminate_is_never_completed(monkeypatch):
    report = _passed("Lukasz Zolc", indication="INDETERMINATE", is_qes=False)
    err = await _finalize(monkeypatch, _sig("AdES"), report)
    assert err.status_code == 422


async def test_one_failed_signature_blocks_completion(monkeypatch):
    report = ValidationReport(
        is_qes=True,
        indication="TOTAL_PASSED",
        signature_count=2,
        signature_results=[
            {"signer": "Lukasz Zolc", "indication": "TOTAL_PASSED"},
            {"signer": "Anna Firma", "indication": "TOTAL_FAILED"},
        ],
    )
    err = await _finalize(monkeypatch, _sig(), report)
    assert err.status_code == 422


async def test_validator_unavailable_is_never_completed(monkeypatch):
    report = ValidationReport(
        is_qes=False, indication="INDETERMINATE", sub_indication="VALIDATOR_UNAVAILABLE"
    )
    err = await _finalize(monkeypatch, _sig("AdES"), report)
    assert err.status_code == 422


def test_result_count_must_match_signature_count():
    report = ValidationReport(
        is_qes=True,
        signature_count=2,
        signature_results=[{"signer": "A B", "indication": "TOTAL_PASSED"}],
    )
    assert report.all_signatures_passed is False


def test_dss_mapping_keeps_every_signature_verdict():
    report = ValidationService._map_dss_report(
        {
            "simpleReport": {
                "signatureOrTimestamp": [
                    {
                        "signedBy": "Jan Kowalski",
                        "indication": "TOTAL_PASSED",
                        "signatureLevel": "QESig",
                    },
                    {"signedBy": "Anna Firma", "indication": "TOTAL_FAILED"},
                    {"type": "TIMESTAMP", "indication": "TOTAL_PASSED"},
                ]
            }
        }
    )
    assert report.signature_count == 2
    assert [r["indication"] for r in report.signature_results] == [
        "TOTAL_PASSED",
        "TOTAL_FAILED",
    ]
    assert report.all_signatures_passed is False


# ── SIG-02: plik = wysłana umowa, podpisali właściwi ludzie ─────────────────


async def test_legacy_signature_without_source_fingerprint_needs_review(monkeypatch):
    err = await _finalize(monkeypatch, _sig(with_source=False), _passed("Łukasz Żółć"))
    assert err.status_code == 409
    assert "Podpisany plik nie pasuje do wysłanej umowy" in err.detail


async def test_signed_file_of_another_contract_is_refused(monkeypatch):
    other = b"%PDF-1.7 zupelnie-inna-umowa" + b"\n% podpis"
    err = await _finalize(monkeypatch, _sig(), _passed("Łukasz Żółć"), pdf=other)
    assert err.status_code == 409
    assert "wymaga ręcznej weryfikacji" in err.detail


async def test_unsigned_copy_of_source_is_refused(monkeypatch):
    # Dokładnie ten sam plik co źródło (bez dopisanego podpisu) nie jest
    # przyrostowym podpisem — nie może przejść porównania prefiksu.
    err = await _finalize(monkeypatch, _sig(), _passed("Łukasz Żółć"), pdf=SOURCE)
    assert err.status_code == 409


async def test_signature_by_someone_else_is_refused(monkeypatch):
    err = await _finalize(monkeypatch, _sig(), _passed("Different Signer"))
    assert err.status_code == 409
    assert "Łukasz Żółć" in err.detail


async def test_extra_signer_outside_company_list_is_refused(monkeypatch):
    monkeypatch.setattr(settings, "SIGNING_COMPANY_SIGNER_NAMES", "Anna Prezes")
    err = await _finalize(
        monkeypatch, _sig(), _passed("Common Name: Lukasz Zolc", "Obcy Człowiek")
    )
    assert err.status_code == 409


async def test_unreadable_signer_is_refused(monkeypatch):
    err = await _finalize(
        monkeypatch, _sig(), _passed("Lukasz Zolc", "<nieznany sygnatariusz>")
    )
    assert err.status_code == 409


def test_record_source_pdf_dedups_and_keeps_new_object():
    sig = SimpleNamespace(validation_report=None)
    signing_sender.record_source_pdf(sig, SOURCE)
    first = sig.validation_report
    signing_sender.record_source_pdf(sig, SOURCE)
    assert (
        sig.validation_report[signing_sender.SOURCE_PDFS_KEY]
        == first[signing_sender.SOURCE_PDFS_KEY]
    )
    signing_sender.record_source_pdf(sig, SOURCE + b"x")
    assert len(sig.validation_report[signing_sender.SOURCE_PDFS_KEY]) == 2
    assert sig.validation_report is not first


# ── SIG-03: obie strony = dwie RÓŻNE tożsamości z pozytywnym wynikiem ───────


def test_same_person_twice_is_not_both_parties():
    report = _passed("Jan Kowalski", "CN=Jan Kowalski, C=PL")
    assert report.signature_count == 2
    assert report.both_parties_signed is False


def test_two_distinct_positive_signers_are_both_parties():
    report = _passed(
        "Common Name: Jan Kowalski, Country: PL", "Common Name: Anna Prezes"
    )
    assert report.both_parties_signed is True


def test_unknown_signers_do_not_count_as_parties():
    report = _passed("<nieznany sygnatariusz>", "<nieznany sygnatariusz>")
    assert report.both_parties_signed is False


def test_failed_second_signature_does_not_make_both_parties():
    report = ValidationReport(
        is_qes=True,
        signature_count=2,
        signature_results=[
            {"signer": "Jan Kowalski", "indication": "TOTAL_PASSED"},
            {"signer": "Anna Prezes", "indication": "INDETERMINATE"},
        ],
    )
    assert report.both_parties_signed is False


# ── SIG-04 / SIG-05 ─────────────────────────────────────────────────────────


def test_upload_signed_endpoint_is_gone():
    from app.main import app

    paths = {getattr(r, "path", "") for r in app.routes}
    assert not any(p.endswith("/upload-signed") for p in paths)


def test_finalize_does_not_claim_pipeline_move():
    text = (BACKEND / "app/services/signing/sender.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    func = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "finalize_signed_pdf"
    )
    src = ast.get_source_segment(text, func) or ""
    assert "przeszedł na etap" not in src
    assert "przenieś kandydata na etap" in src
    assert '"pipeline_moved": False' in src
