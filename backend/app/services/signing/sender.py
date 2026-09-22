"""Send a B2B contract for in-house QES signature (provider-agnostic).

Two-step flow mirroring the Autenti sender, but provider-neutral and KIR-free
for the upload-and-validate pas:

1. :func:`prepare_send` — validates contract/candidate/content, creates a
   ``document_signatures`` row in ``status=draft``.
2. :func:`prepare_and_send` — wraps it: mints a single-use
   :class:`SignatureLink`, flips ``draft → sent``, notifies the recruiter, and
   returns the public ``/sign/{token}`` URL synchronously so it can be shared.

The consultant opens the link, downloads the contract PDF, signs it with their
own qualified tool, and uploads the signed PAdES — which the public endpoint
validates (pyHanko + EU DSS). No KIR dependency for this pas.

Plan: ``docs/in-house-qes-signature-plan.md`` §3, §7.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.contract import Contract, ContractStatus
from app.models.contract_document import ContractDocument, ContractDocumentType
from app.models.document_signature import DocumentSignature, SignatureStatus
from app.models.notification import NotificationType
from app.models.signature_link import SignatureLink
from app.models.user import User
from app.schemas.document_signature import SignForSignatureRequest
from app.services import storage_service
from app.services.notification_triggers import emit as emit_notification
from app.services.signing.pdf_renderer import render_contract_pdf
from app.services.signing.provider import (
    ValidationReport,
    normalize_person_text,
    signer_identity,
)
from app.services.signing.registry import get_provider

logger = logging.getLogger(__name__)

# Etykiety etapów podpisu — WYŁĄCZNIE do wpisu audytowego `pipeline_stage`
# w `finalize_signed_pdf`.
# Automatyczny ruch kandydata przy wysyłce i podpisie ZDJĘTY 17.09.2026
# (decyzja właściciela: umowę podpisujemy offline, etap zmienia człowiek na
# tablicy). Kolumny „Umowa wysłana" / „Umowa podpisana" zostają w szablonie
# jako ręczne.
STAGE_SIGNED = "Umowa podpisana"
STAGE_HIRED = "Zatrudniony"

# Klucz w ``document_signatures.validation_report`` z odciskami PDF-ów, które
# wyszły do podpisującego (SIG-02). Lista, bo PDF jest renderowany przy każdym
# pobraniu — każda wydana wersja jest zapisana i każda może wrócić podpisana.
SOURCE_PDFS_KEY = "source_pdfs"
_MAX_SOURCE_PDFS = 20

SOURCE_MISMATCH_MESSAGE = (
    "Podpisany plik nie pasuje do wysłanej umowy — wymaga ręcznej weryfikacji."
)


def _require_enabled() -> None:
    if not settings.SIGNING_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="In-house signing is disabled (SIGNING_ENABLED=false)",
        )


def _validate_signer(candidate: Candidate) -> tuple[str, str, str, Optional[str]]:
    """Denormalized signer snapshot from the candidate, or 422 with hint."""
    email = (candidate.email or "").strip()
    first = (candidate.name or "").strip()
    last = (candidate.lastname or "").strip()
    missing = []
    if not email:
        missing.append("candidate.email")
    if not first:
        missing.append("candidate.name")
    if not last:
        missing.append("candidate.lastname")
    if missing:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Candidate is missing signer fields",
                "missing": missing,
            },
        )
    phone = (candidate.phone or "").strip() or None
    return email, first, last, phone


async def prepare_send(
    db: AsyncSession,
    *,
    contract_id: int,
    payload: SignForSignatureRequest,
    sender_user: User,
) -> DocumentSignature:
    """Validate + persist a new ``document_signatures`` row (status=draft)."""
    _require_enabled()

    contract = await db.scalar(
        select(Contract)
        .where(Contract.id == contract_id)
        .options(selectinload(Contract.candidate))
    )
    if contract is None:
        raise HTTPException(status_code=404, detail="Contract not found")
    if contract.status not in (
        ContractStatus.draft,
        ContractStatus.active,
        ContractStatus.ending,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Umowa ma status={contract.status.value}; do podpisu można "
                "wysłać umowę `draft`, `active` lub `ending` (nie `ended`)."
            ),
        )
    if contract.candidate is None:
        raise HTTPException(
            status_code=422, detail="Contract has no candidate attached"
        )

    signer_email, first_name, last_name, signer_phone = _validate_signer(
        contract.candidate
    )

    snapshot = await db.scalar(
        select(ContractDocument)
        .where(
            ContractDocument.contract_id == contract.id,
            ContractDocument.doc_type == "contract",
        )
        .order_by(ContractDocument.created_at.desc())
        .limit(1)
    )
    # Signable content: prefer a finalized snapshot (immutable reviewed HTML),
    # else fall back to the contract's rendered draft HTML (produced by the
    # B2B generator's /generate bridge — prod contracts have no snapshots).
    if snapshot is None and not (contract.draft_content_html or "").strip():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Umowa nie ma treści do podpisu — wygeneruj ją w Generatorze "
                "Umów B2B (lub sfinalizuj draft), a potem wyślij do podpisu."
            ),
        )

    expires_days = payload.expires_in_days or settings.SIGNING_LINK_EXPIRY_DAYS
    expires_at = datetime.now(timezone.utc) + timedelta(days=expires_days)

    sig = DocumentSignature(
        contract_id=contract.id,
        contract_document_id=snapshot.id if snapshot else None,
        provider=payload.provider,
        signature_type=payload.signature_type,
        status=SignatureStatus.draft,
        sender_user_id=sender_user.id,
        signer_email=signer_email,
        signer_first_name=first_name,
        signer_last_name=last_name,
        signer_phone=signer_phone,
        expires_at=expires_at,
    )
    db.add(sig)
    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract.id,
            action="signature_initiated",
            user_id=sender_user.id,
            external_source="signing",
            details={
                "provider": payload.provider,
                "signature_type": payload.signature_type,
                "signer_email": signer_email,
            },
        )
    )
    await db.commit()
    await db.refresh(sig)
    return sig


def render_unsigned_pdf(sig: DocumentSignature) -> bytes:
    """Render the contract snapshot HTML → unsigned PDF (sync; to_thread it).

    Reused by the public ``GET /sign/{token}/pdf`` endpoint so the consultant
    can download exactly the document they're about to sign.
    """
    html: Optional[str] = None
    if sig.contract_document_id and sig.contract_document is not None:
        abs_path = storage_service.get_contract_document_path(
            sig.contract_document.file_path
        )
        html = abs_path.read_bytes().decode("utf-8", errors="replace")
    elif sig.contract is not None and sig.contract.draft_content_html:
        html = sig.contract.draft_content_html
    if not html:
        raise RuntimeError(
            f"No signable content for signature {sig.id} "
            "(no snapshot and empty draft_content_html)"
        )
    return render_contract_pdf(html, title=f"Umowa #{sig.contract_id}")


def record_source_pdf(sig: DocumentSignature, pdf_bytes: bytes) -> None:
    """Zapamiętaj odcisk (SHA-256 + długość) PDF-u wydanego do podpisu (SIG-02).

    Wołane tam, gdzie PDF opuszcza system (publiczne ``/sign/{token}/pdf``).
    Finalizacja przyjmuje wyłącznie plik, który ZACZYNA SIĘ dokładnie tymi
    bajtami — podpis PAdES jest przyrostowym dopisaniem do oryginału. Nie
    commituje (robi to wołający).
    """
    digest = hashlib.sha256(pdf_bytes).hexdigest()
    report = dict(sig.validation_report or {})
    sources = [
        dict(item)
        for item in report.get(SOURCE_PDFS_KEY) or []
        if isinstance(item, dict)
    ]
    if any(
        item.get("sha256") == digest and item.get("length") == len(pdf_bytes)
        for item in sources
    ):
        return
    sources.append(
        {
            "sha256": digest,
            "length": len(pdf_bytes),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    report[SOURCE_PDFS_KEY] = sources[-_MAX_SOURCE_PDFS:]
    # Nowy obiekt — JSONB bez MutableDict nie widzi zmian w miejscu.
    sig.validation_report = report


def _recorded_sources(sig: DocumentSignature) -> list[dict[str, Any]]:
    return [
        item
        for item in (sig.validation_report or {}).get(SOURCE_PDFS_KEY) or []
        if isinstance(item, dict)
        and isinstance(item.get("sha256"), str)
        and isinstance(item.get("length"), int)
    ]


def _source_mismatch(reason: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=f"{SOURCE_MISMATCH_MESSAGE} {reason}",
    )


def _assert_matches_source(sig: DocumentSignature, pdf_bytes: bytes) -> None:
    """Podpisany PDF musi zaczynać się bajtami PDF-u wydanego do podpisu."""
    sources = _recorded_sources(sig)
    if not sources:
        # Sprawa sprzed zapisu odcisków (albo PDF nigdy nie został pobrany
        # z linku) — nie mamy z czym porównać, więc nie zamykamy automatycznie.
        raise _source_mismatch(
            "Brak zapisanego odcisku wysłanego dokumentu, więc nie da się "
            "potwierdzić, że podpisano tę umowę."
        )
    for item in sources:
        length = item["length"]
        if len(pdf_bytes) <= length:
            continue
        if hashlib.sha256(pdf_bytes[:length]).hexdigest() == item["sha256"]:
            return
    raise _source_mismatch(
        "Treść pliku różni się od dokumentu, który wysłaliśmy do podpisu."
    )


def _name_tokens(value: str | None) -> set[str]:
    return set(normalize_person_text(value).split())


def _company_signer_tokens() -> list[set[str]]:
    return [
        tokens
        for tokens in (
            _name_tokens(name)
            for name in (settings.SIGNING_COMPANY_SIGNER_NAMES or "").split(",")
        )
        if tokens
    ]


def _expected_signers_check(
    sig: DocumentSignature, report: ValidationReport
) -> list[str]:
    """Sprawdź strony podpisu; zwraca tożsamości spoza kandydata (SIG-02).

    Kandydat musi podpisać. Każdy inny podpis musi mieć czytelną tożsamość,
    a jeśli skonfigurowano sygnatariuszy firmy — należeć do jednego z nich.
    """
    if any(not signer_identity(r.get("signer")) for r in report.signature_results):
        raise _source_mismatch("Nie da się odczytać, kto złożył jeden z podpisów.")
    candidate_tokens = _name_tokens(
        f"{sig.signer_first_name or ''} {sig.signer_last_name or ''}"
    )
    identities = report.positive_signer_identities
    candidate_ids = [
        ident
        for ident in identities
        if candidate_tokens and candidate_tokens <= set(ident.split())
    ]
    if not candidate_ids:
        raise _source_mismatch(
            f"Wśród podpisów nie ma podpisu {sig.signer_first_name} "
            f"{sig.signer_last_name}."
        )
    others = [ident for ident in identities if ident not in candidate_ids]
    company = _company_signer_tokens()
    if company:
        for ident in others:
            ident_tokens = set(ident.split())
            if not any(tokens <= ident_tokens for tokens in company):
                raise _source_mismatch("Umowę podpisała osoba spoza stron umowy.")
    return others


def mint_signature_link(
    db: AsyncSession, sig: DocumentSignature, *, party: str = "consultant"
) -> tuple[SignatureLink, str]:
    """Create a single-use signing link tied to ``sig``.

    Returns ``(link, raw_token)``. The raw token goes into the ``/sign/{token}``
    URL and is never stored: the row keeps only its SHA-256 (v2 hash-at-rest),
    with a non-secret ``v2$`` revoke key in the PK.
    """
    import hashlib

    purpose = "upload_signed" if sig.provider == "upload_validate" else "qes_signing"
    raw_token = secrets.token_urlsafe(36)
    link = SignatureLink(
        token=f"v2${secrets.token_hex(16)}",
        token_sha256=hashlib.sha256(raw_token.encode()).hexdigest(),
        signature_id=sig.id,
        party=party,
        purpose=purpose,
        created_by=sig.sender_user_id,
        expires_at=sig.expires_at
        or (
            datetime.now(timezone.utc)
            + timedelta(days=settings.SIGNING_LINK_EXPIRY_DAYS)
        ),
    )
    db.add(link)
    return link, raw_token


async def prepare_and_send(
    db: AsyncSession,
    *,
    contract_id: int,
    payload: SignForSignatureRequest,
    sender_user: User,
) -> tuple[DocumentSignature, str]:
    """Validate, create the signature, mint the link, return the shareable URL.

    Synchronous so the recruiter gets the ``/sign/{token}`` link back
    immediately. Flips ``draft → sent`` and notifies the recruiter in-app.
    """
    sig = await prepare_send(
        db, contract_id=contract_id, payload=payload, sender_user=sender_user
    )
    _link, raw_token = mint_signature_link(db, sig)
    sig.status = SignatureStatus.sent
    sig.sent_at = datetime.now(timezone.utc)

    base = settings.PUBLIC_BASE_URL.rstrip("/")
    sign_url = f"{base}/sign/{raw_token}"

    db.add(
        Activity(
            entity_type="contract",
            entity_id=sig.contract_id,
            action="signature_sent",
            user_id=sig.sender_user_id,
            external_source="signing",
            details={"provider": sig.provider},
        )
    )
    try:
        await emit_notification(
            db,
            user_id=sig.sender_user_id,
            title="Link do podpisu gotowy",
            message=(
                f"Umowa kontraktu #{sig.contract_id} dla "
                f"{sig.signer_first_name} {sig.signer_last_name}. "
                f"Wyślij konsultantowi link do podpisu: {sign_url}"
            ),
            ntype=NotificationType.signature_sent,
            related_entity_type="document_signature",
            related_entity_id=sig.id,
            link=f"/candidates?contract={sig.contract_id}",
        )
    except Exception:  # noqa: BLE001
        logger.exception("prepare_and_send: notification emit failed sig=%d", sig.id)

    await db.commit()
    await db.refresh(sig)
    logger.info("prepare_and_send: link minted sig=%d", sig.id)
    return sig, sign_url


async def finalize_signed_pdf(
    db: AsyncSession,
    sig: DocumentSignature,
    pdf_bytes: bytes,
    *,
    moved_by: int,
) -> dict[str, Any]:
    """Validate a signed PAdES, attach it, complete the signature, advance pipeline.

    Wołane przez publiczne ``/sign/{token}/submit``. Kolejność bramek:
    status sprawy → podpis obecny → QES (autorytatywny DSS) → KAŻDY podpis
    z jawnie pozytywnym wynikiem (SIG-01) → plik zaczyna się bajtami PDF-u
    wydanego do podpisu i podpisali właściwi ludzie (SIG-02). Każda odmowa
    zostawia sprawę bez zmian (wołający nie commituje po 4xx), więc da się
    ponowić. Nie przesuwa kandydata w pipeline (od 17.09.2026). Does NOT commit.
    """
    # Fail-closed on status (M5-P0.2). A withdrawn/expired/rejected — or already
    # completed — signature must never be finalized, even if a still-live token
    # survived (belt-and-braces with link revocation on withdraw). Only an
    # in-flight signature (sent / in_progress) may be completed. Guards BOTH
    # callers (dawniej także usunięte /upload-signed).
    if sig.status not in (SignatureStatus.sent, SignatureStatus.in_progress):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Podpis w statusie {sig.status.value} nie może zostać sfinalizowany"
            ),
        )

    provider = get_provider(sig.provider)
    report = await provider.validate(pdf_bytes)

    if report.indication == "NO_SIGNATURE":
        raise HTTPException(
            status_code=422, detail="Plik nie zawiera podpisu elektronicznego"
        )

    # Fail-closed for QES lanes (M5-P0.x): a qualified document may only be
    # completed on an AUTHORITATIVE, positive DSS verdict. Previously the QES
    # gate was skipped whenever ``DSS_VALIDATION_URL`` was unset — so with no
    # validator configured, a non-qualified (or indeterminate) signature would
    # silently complete on the non-authoritative pyHanko fallback. Now: no
    # validator, or a timed-out / INDETERMINATE result, refuses completion and
    # leaves the signature state unchanged (the caller does not commit on 4xx).
    requires_qes = (sig.signature_type or "").upper() == "QES"
    if requires_qes:
        if not settings.DSS_VALIDATION_URL:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Brak autorytatywnej walidacji QES — DSS_VALIDATION_URL nie "
                    "jest skonfigurowany, więc podpisu nie można potwierdzić jako "
                    "kwalifikowanego. Dokument nie został sfinalizowany."
                ),
            )
        indication = (report.indication or "").upper()
        authoritative_qes = report.is_qes and not indication.startswith("INDETERMINATE")
        if not authoritative_qes:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Walidacja QES nierozstrzygnięta lub negatywna (werdykt: "
                    f"{report.indication or 'nieokreślony'}). Podpis nie jest "
                    "kwalifikowany lub nie ma autorytatywnego potwierdzenia — "
                    "dokument nie został sfinalizowany."
                ),
            )

    # SIG-01: zamknąć sprawę wolno WYŁĄCZNIE przy jawnie pozytywnym wyniku
    # KAŻDEGO podpisu. TOTAL_FAILED, INDETERMINATE i brak walidatora (wynik
    # bez ocen podpisów) zostawiają sprawę do ponowienia.
    if not report.all_signatures_passed:
        verdicts = ", ".join(
            str(r.get("indication") or "brak wyniku") for r in report.signature_results
        ) or (report.indication or "brak wyniku")
        raise HTTPException(
            status_code=422,
            detail=(
                "Nie wszystkie podpisy mają pozytywny wynik weryfikacji "
                f"(wyniki: {verdicts}). Dokument nie został sfinalizowany — "
                "spróbuj ponownie albo przekaż plik do ręcznej weryfikacji."
            ),
        )

    # SIG-02: plik musi być TĄ umową (przyrostowy PAdES zaczyna się bajtami
    # wysłanego PDF-u) i podpisaną przez właściwe strony.
    _assert_matches_source(sig, pdf_bytes)
    other_signers = _expected_signers_check(sig, report)

    # Obie strony (SIG-03): co najmniej dwie RÓŻNE tożsamości z pozytywnym
    # wynikiem, w tym kandydat i ktoś inny. `suggested_stage` to wyłącznie
    # podpowiedź — od 17.09.2026 podpis NIE przesuwa kandydata w pipeline.
    both_signed = report.both_parties_signed and bool(other_signers)
    suggested_stage = STAGE_HIRED if both_signed else STAGE_SIGNED

    rel_path, size = storage_service.save_contract_document(
        sig.contract_id, f"signed_umowa_{sig.contract_id}.pdf", BytesIO(pdf_bytes)
    )
    signed_doc = ContractDocument(
        contract_id=sig.contract_id,
        filename=f"signed_umowa_{sig.contract_id}.pdf",
        file_path=rel_path,
        content_type="application/pdf",
        size_bytes=size,
        doc_type=ContractDocumentType.contract,
    )
    db.add(signed_doc)
    await db.flush()

    now = datetime.now(timezone.utc)
    sig.signed_document_id = signed_doc.id
    db_report = report.as_db_report()
    db_report[SOURCE_PDFS_KEY] = _recorded_sources(sig)
    sig.validation_report = db_report
    sig.signature_level = report.signature_level
    sig.status = SignatureStatus.completed
    sig.completed_at = now

    db.add(
        Activity(
            entity_type="contract",
            entity_id=sig.contract_id,
            action="signature_signed",
            user_id=sig.sender_user_id,
            external_source="signing",
            details={
                "is_qes": report.is_qes,
                "signature_level": report.signature_level,
                "signed_by": report.signed_by,
                "signature_count": report.signature_count,
                "both_parties_signed": both_signed,
                "suggested_pipeline_stage": suggested_stage,
                "pipeline_moved": False,
            },
        )
    )

    try:
        title = (
            "Umowa podpisana przez obie strony" if both_signed else "Umowa podpisana"
        )
        if both_signed:
            # SIG-05: podpis nie zmienia etapu — mówimy, co zrobić, zamiast
            # twierdzić, że kandydat już jest na „Zatrudniony".
            message = (
                f"Umowa kontraktu #{sig.contract_id} dla "
                f"{sig.signer_first_name} {sig.signer_last_name}: umowa "
                "podpisana przez obie strony — przenieś kandydata na etap "
                "Zatrudniony ręcznie."
            )
        else:
            message = (
                f"Umowa kontraktu #{sig.contract_id} dla "
                f"{sig.signer_first_name} {sig.signer_last_name} została podpisana."
            )
        await emit_notification(
            db,
            user_id=sig.sender_user_id,
            title=title,
            message=message,
            ntype=NotificationType.signature_signed,
            related_entity_type="document_signature",
            related_entity_id=sig.id,
            link=f"/candidates?contract={sig.contract_id}",
        )
    except Exception:  # noqa: BLE001
        logger.exception("finalize_signed_pdf: notification emit failed sig=%d", sig.id)

    return {
        "status": "ok",
        "is_qes": report.is_qes,
        "signature_level": report.signature_level,
        "signed_by": report.signed_by,
        "indication": report.indication,
        "dss_verified": bool(settings.DSS_VALIDATION_URL),
        "signature_count": report.signature_count,
        "signers": report.signers,
        "both_parties_signed": both_signed,
        "suggested_pipeline_stage": suggested_stage,
        "pipeline_moved": False,
    }
