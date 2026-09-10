"""Approve the exact verified generation without inventing a recruitment stage."""

import copy
import hashlib
import logging
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import select
from app.models.cv_document_version import CvDocumentVersion
from app.services.cv_approval_provenance import capture_editor_origin
from app.services.cv_generator_b2b.public_view import build_public_payload
from app.services.cv_generator_b2b.html_export import render_interactive_html
from app.services.html_sanitizer import sanitize_cv_html

logger = logging.getLogger(__name__)


def _render_missing_docx(generated, template: bytes, consent: bytes | None) -> bytes:
    """Odtwórz DOCX CV sprzed zapisu pliku — z tych samych zasobów co wersja.

    Kolumny ``docx_content``/``docx_sha256`` doszły w #1444 (migracja 0292) bez
    backfillu, więc KAŻDE CV wygenerowane wcześniej ma w nich NULL. Bez tego
    kroku żadnego z nich nie dało się zatwierdzić, a więc i udostępnić
    klientowi. Render jest deterministyczny i idzie tą samą drogą co pobranie
    (``rerender_docx_from_payload``): anonimizacja blind z ``blind_cv``
    w payloadzie, szablon i zrzut zgody — dokładnie te bajty, które zamrozi
    zatwierdzana wersja (``generated_assets``), a nie drugi odczyt z magazynu.
    """
    payload = copy.deepcopy(generated.render_payload)
    # Wiersz oznaczony jako anonimowy, którego payload nie niesie anonimizacji,
    # dałby plik z nazwiskiem i firmami — i ten sam tekst w zatwierdzanej
    # wersji. Odmawiamy zamiast zamrozić dokument do wysłania klientowi.
    if getattr(generated, "blind", False) and payload.get("blind_cv") is not True:
        raise HTTPException(
            409,
            "To CV anonimowe nie ma zapisanej anonimizacji. Wygeneruj CV ponownie.",
        )
    screenshot = payload.get("consent_screenshot")
    if isinstance(screenshot, dict) and consent:
        screenshot["_bytes"] = consent
    from app.services.cv_generator_b2b.standalone_service import (
        rerender_docx_from_payload,
    )

    try:
        return rerender_docx_from_payload(
            payload,
            require_consent=bool(screenshot),
            template_bytes=template,
        )
    except Exception as exc:  # noqa: BLE001 — python-docx/PIL raise various types
        logger.exception("[cv_b2b] Render of legacy CV %s failed", generated.id)
        raise HTTPException(
            409,
            "Nie udało się odtworzyć dokumentu z zapisanych danych. "
            "Wygeneruj CV ponownie.",
        ) from exc


async def approve_unchanged_generation(db, generated, user_id):
    """Caller holds the authorized generation row lock; retries reuse approval.

    CV sprzed zapisu pliku DOCX (#1444) dostaje plik odtworzony z
    ``render_payload`` i zapisany na wierszu pod tą samą blokadą — dalej
    obowiązują te same kontrole co przy nowym CV.
    """
    if generated.status != "ready" or not generated.render_payload:
        raise HTTPException(409, "CV nie jest gotowe do zatwierdzenia.")
    # Oba pola puste = wiersz sprzed zapisu DOCX, do odtworzenia niżej. Każdy
    # inny stan (plik bez skrótu, skrót bez pliku, rozjazd) to utrata
    # integralności — tego nie wolno zakryć ponownym renderem.
    missing_docx = generated.docx_content is None and generated.docx_sha256 is None
    if not missing_docx and (
        not generated.docx_content
        or hashlib.sha256(generated.docx_content).hexdigest() != generated.docx_sha256
    ):
        raise HTTPException(
            409, "Brak poprawnego zapisanego dokumentu. Wygeneruj CV ponownie."
        )
    public = build_public_payload(generated.render_payload)
    html = sanitize_cv_html(render_interactive_html(public, [], document_only=True))
    metadata = capture_editor_origin(html, generated.render_payload)
    from app.services.cv_generator_b2b.source_facts import source_evidence_enforced

    # With source-evidence enforcement off (the default), approving an
    # unchanged generation does not require an AI review — the pre-#1444
    # flow had no approval gate at all. Re-enabled together with the flag.
    if not metadata["generation_review_available"] and source_evidence_enforced():
        raise HTTPException(
            409,
            "Brak potwierdzonej kontroli treści tej generacji. Wygeneruj CV ponownie.",
        )
    existing = await db.scalar(
        select(CvDocumentVersion).where(
            CvDocumentVersion.generated_owner_id == generated.id,
            CvDocumentVersion.version == 1,
        )
    )
    if existing is not None:
        return existing
    from app.models.cv_generated_draft import CvGeneratedDraft

    if await db.scalar(
        select(CvGeneratedDraft.id).where(
            CvGeneratedDraft.generated_document_id == generated.id
        )
    ):
        raise HTTPException(
            409, "To CV ma zapisany szkic. Zatwierdź jego treść w edytorze."
        )
    from starlette.concurrency import run_in_threadpool
    from app.services.cv_document_assets import generated_assets, CvAssetsError

    try:
        template, consent, assets = await run_in_threadpool(generated_assets, generated)
    except CvAssetsError as exc:
        raise HTTPException(422, str(exc)) from exc
    expected_template = (generated.render_payload.get("artifact_provenance") or {}).get(
        "template_sha256"
    )
    if expected_template and expected_template != assets["template_sha256"]:
        raise HTTPException(
            409, "Szablon tej generacji nie jest już dostępny. Wygeneruj CV ponownie."
        )
    if missing_docx:
        docx = await run_in_threadpool(
            _render_missing_docx, generated, template, consent
        )
        generated.docx_content = docx
        generated.docx_sha256 = hashlib.sha256(docx).hexdigest()
        metadata["docx_rendered_at_approval"] = True
    metadata.update(assets)
    version = CvDocumentVersion(
        generated_owner_id=generated.id,
        generated_document_id=generated.id,
        candidate_stage_cv_id=None,
        version=1,
        content_html=html,
        content_sha256=hashlib.sha256(html.encode()).hexdigest(),
        template_content=template,
        consent_content=consent,
        docx_content=generated.docx_content,
        docx_sha256=generated.docx_sha256,
        docx_filename=generated.filename,
        render_metadata={
            **metadata,
            "editorial_provenance": generated.render_payload.get(
                "editorial_provenance"
            ),
            "artifact_provenance": generated.render_payload.get("artifact_provenance"),
        },
        language=public["language"],
        candidate_first_name=public["candidate_name"],
        job_title=public["position"],
        template="blind" if public["blind"] else "standard",
        approved_at=datetime.now(timezone.utc),
        approved_by=user_id,
    )
    db.add(version)
    await db.flush()
    return version
