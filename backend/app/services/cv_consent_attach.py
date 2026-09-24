"""Dołączenie (i wymiana) zrzutu zgody RODO PO generacji CV (generator v3).

Do 23.09.2026 zrzut zgody (wymóg PKO BP) dało się podać wyłącznie przed
generacją; brak zgody oznaczał albo odmowę generacji, albo — pod centralnymi
regułami — CV, które nigdy nie stawało się gotowe do wysyłki. Teraz generacja
przechodzi, pobranie blokuje ``cv_consent_gate``, a zgodę dołącza się tutaj:

* dotyczy CAŁEGO pakietu (wersja główna + druga wersja językowa) — obie
  wersje idą do tego samego banku z tym samym zrzutem;
* 409, gdy którakolwiek wersja jeszcze się generuje — render z obrazem
  wyścigowałby z workerem, który zapisuje ten sam wiersz;
* zrzut można WYMIENIĆ (zły obraz, nowa zgoda) — ślad ``cv_consent_replaced``;
* każdy gotowy dokument dostaje NOWY DOCX z obrazem (bieżący renderer —
  zapisane w ``artifact_provenance``), klucz w ``render_payload`` i bajty;
* kopie zasobów w szkicach (edytor generatora, CV etapu) dostają nowy obraz,
  bo z nich renderuje się DOCX przy zatwierdzeniu;
* wersja już ZATWIERDZONA jest zatwierdzana ponownie z tym samym HTML-em
  i nowym obrazem, wyłącznie gdy treść jest bajt w bajt ta sama co
  w zatwierdzonej wersji — BEZ wywołania AI (zapis poprzedniej kontroli
  treści, ``review_override``). Zmieniony HTML czeka na człowieka.
"""

from __future__ import annotations

import copy
import hashlib
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.models.activity import Activity
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.cv_document_version import CvDocumentVersion
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.cv_generated_draft import CvGeneratedDraft
from app.services.cv_consent_gate import consent_attached, consent_required


def render_with_consent(
    payload: dict[str, Any], *, template_bytes: Optional[bytes]
) -> tuple[bytes, bytes]:
    """DOCX z payloadu z doczytanym obrazem zgody; ``(docx, obraz)``.

    Jedna implementacja z generacją (`api.cv_generator_b2b._render_with_consent`,
    wołana też przez `_finalize_success`). Synchroniczne — przez
    ``run_in_threadpool``.
    """
    from app.api.cv_generator_b2b import _render_with_consent

    return _render_with_consent(payload, template_bytes=template_bytes)


def binding_context(primary: CvGeneratedDocument) -> dict:
    """Kontekst pokwitowania zgody dołączanej do gotowego CV.

    Klient, etap i numer projektu idą z polityki zamrożonej na wierszu
    głównym pakietu — tych samych wartości, które sprawdza gotowość pakietu
    (`cv_packages.assess`), więc dołączona zgoda przechodzi ją bez rozjazdu.
    """
    from app.services.cv_generator_b2b import consent_binding
    from app.services.cv_packages import project_number

    policy = primary.central_policy or {}
    return {
        **consent_binding.subject(generated_id=primary.id, client_id=primary.client_id),
        "project_ref": project_number(policy.get("project_ref")),
        "recruitment_stage_id": policy.get("stage_id"),
    }


def _verify_image(image: bytes) -> None:
    from PIL import Image

    try:
        with Image.open(BytesIO(image)) as picture:
            picture.verify()
    except Exception as exc:  # noqa: BLE001 — PIL rzuca różne typy
        raise HTTPException(
            422,
            "Nie udało się odczytać zrzutu zgody — wgraj go ponownie jako PNG, "
            "JPEG albo WEBP.",
        ) from exc


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


async def _package(db, generated: CvGeneratedDocument):
    from app.services.cv_packages import members

    return await members(db, generated, lock=True)


async def attach(
    db, generated: CvGeneratedDocument, *, token: str, user_id: int
) -> dict:
    """Dołącz / wymień zgodę w całym pakiecie. Bez commitu — robi wołający."""
    from app.services import object_storage
    from app.services.cv_generator_b2b import consent_binding

    job, primary, rows = await _package(db, generated)
    if not consent_required(primary):
        raise HTTPException(
            409, "To CV nie wymaga zrzutu zgody — polityka klienta go nie przewiduje."
        )
    if any(row.status == "processing" for row in rows) or (
        job is not None and job.status in ("queued", "running")
    ):
        raise HTTPException(
            409,
            "Generacja CV nadal trwa. Dołącz zgodę, gdy obie wersje będą gotowe.",
        )
    ready = [row for row in rows if row.status == "ready" and row.render_payload]
    if not ready:
        raise HTTPException(
            409, "To CV nie jest gotowe — nie ma do czego dołączyć zgody."
        )
    try:
        receipt = consent_binding.verify(token, user_id, binding_context(primary))
    except ValueError:
        raise HTTPException(
            422,
            "Zrzut zgody nie jest przypisany do tego CV albo wygasł. Wgraj go "
            "ponownie.",
        ) from None
    try:
        image = await run_in_threadpool(
            object_storage.download_cv, receipt["storage_key"]
        )
    except Exception as exc:  # noqa: BLE001 — magazyn chwilowo niedostępny
        raise HTTPException(
            503,
            "Nie udało się pobrać zrzutu zgody z magazynu. Spróbuj ponownie za chwilę.",
        ) from exc
    if not image:
        raise HTTPException(422, "Zrzut zgody jest pusty — wgraj go ponownie.")
    _verify_image(image)

    replaced = any(consent_attached(row) for row in ready)
    now = datetime.now(timezone.utc)
    consent_record = {
        "storage_key": receipt["storage_key"],
        "binding": receipt["binding"],
    }
    reapproved: list[int] = []
    for row in ready:
        previous_docx_sha = row.docx_sha256
        payload = copy.deepcopy(row.render_payload)
        payload["consent_screenshot"] = {**consent_record, "_bytes": image}
        try:
            docx, _image = await run_in_threadpool(
                render_with_consent, payload, template_bytes=row.template_content
            )
        except Exception as exc:  # noqa: BLE001 — python-docx/PIL
            raise HTTPException(
                422,
                "Nie udało się wstawić zrzutu zgody do CV. Sprawdź obraz i spróbuj "
                "ponownie.",
            ) from exc
        docx_sha = _sha(docx)
        stored = {**row.render_payload, "consent_screenshot": dict(consent_record)}
        provenance = dict(stored.get("artifact_provenance") or {})
        provenance["generated_docx_sha256"] = docx_sha
        provenance["consent_sha256"] = _sha(image)
        provenance["consent_attached_after_generation"] = {
            "at": now.isoformat(),
            "by": user_id,
            "replaced": replaced,
            "previous_docx_sha256": previous_docx_sha,
            # DOCX powstał BIEŻĄCYM rendererem, nie tym z chwili generacji.
            "rerendered_with_current_renderer": True,
        }
        stored["artifact_provenance"] = provenance
        row.render_payload = stored
        row.consent_content = image
        row.docx_content = docx
        row.docx_sha256 = docx_sha
        row_versions = await _refresh_generated_drafts(
            db,
            row,
            image=image,
            user_id=user_id,
            previous_docx_sha=previous_docx_sha,
        )
        row_versions += await _refresh_stage_drafts(
            db, row, image=image, user_id=user_id
        )
        reapproved.extend(row_versions)
        db.add(
            Activity(
                entity_type="cv_generated_document",
                entity_id=row.id,
                action="cv_consent_replaced" if replaced else "cv_consent_attached",
                user_id=user_id,
                details={
                    "package_id": primary.id,
                    "language": row.language,
                    "docx_sha256": docx_sha,
                    "previous_docx_sha256": previous_docx_sha,
                    "reapproved_version_ids": row_versions,
                },
            )
        )
    await db.flush()
    return {
        "package_id": primary.id,
        "replaced": replaced,
        "document_ids": [row.id for row in ready],
        "reapproved_version_ids": reapproved,
    }


def _with_consent_digest(metadata: Optional[dict], image: bytes) -> dict:
    return {**(metadata or {}), "consent_sha256": _sha(image)}


def _reapproval_review(previous: Optional[dict]) -> dict:
    review = dict((previous or {}).get("content_review") or {})
    review["consent_reapproval"] = True
    return review


async def _latest_owned_version(db, row) -> Optional[CvDocumentVersion]:
    return await db.scalar(
        select(CvDocumentVersion)
        .where(
            CvDocumentVersion.generated_owner_id == row.id,
            CvDocumentVersion.candidate_stage_cv_id.is_(None),
        )
        .order_by(CvDocumentVersion.version.desc())
        .limit(1)
    )


async def _refresh_generated_drafts(
    db, row, *, image: bytes, user_id: int, previous_docx_sha: Optional[str]
) -> list[int]:
    """Szkic edytora generatora + ponowne zatwierdzenie jego wersji."""
    from app.services.cv_approved_docx import render_approved_docx

    draft = await db.scalar(
        select(CvGeneratedDraft)
        .where(CvGeneratedDraft.generated_document_id == row.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if draft is not None:
        draft.branded_consent_content = image
        draft.branded_render_metadata = _with_consent_digest(
            draft.branded_render_metadata, image
        )
    latest = await _latest_owned_version(db, row)
    if latest is None or not latest.template_content:
        return []
    if draft is not None and (
        draft.branded_status != "finalized"
        or _sha(draft.branded_draft_html.encode()) != latest.content_sha256
    ):
        # Szkic w trakcie edycji albo treść różna od zatwierdzonej — nowe
        # zatwierdzenie należy do człowieka (z kontrolą treści).
        return []
    if latest.docx_sha256 and latest.docx_sha256 == previous_docx_sha:
        # Wersja zatwierdzona bez edycji niesie DOCX generatora — następca
        # dostaje nowy DOCX generatora z obrazem.
        docx = row.docx_content
    else:
        docx = await run_in_threadpool(
            render_approved_docx,
            latest.content_html,
            latest.template_content,
            consent=image,
            language=latest.language or "pl",
        )
    metadata = _with_consent_digest(latest.render_metadata, image)
    metadata["content_review"] = _reapproval_review(latest.render_metadata)
    version = CvDocumentVersion(
        generated_owner_id=row.id,
        generated_document_id=row.id,
        candidate_stage_cv_id=None,
        version=latest.version + 1,
        content_html=latest.content_html,
        content_sha256=latest.content_sha256,
        template_content=latest.template_content,
        consent_content=image,
        docx_content=docx,
        docx_sha256=_sha(docx),
        docx_filename=latest.docx_filename,
        render_metadata=metadata,
        language=latest.language,
        template=latest.template,
        candidate_first_name=latest.candidate_first_name,
        job_title=latest.job_title,
        approved_at=datetime.now(timezone.utc),
        approved_by=user_id,
    )
    db.add(version)
    await db.flush()
    if draft is not None:
        draft.branded_version = version.version
        draft.branded_render_metadata = metadata
        draft.edit_revision += 1
    return [version.id]


async def _refresh_stage_drafts(db, row, *, image: bytes, user_id: int) -> list[int]:
    """Kopie w CV etapów + ponowne zatwierdzenie niezmienionej treści."""
    from app.services.candidate_stage_cv_service import finalize_stage_cv
    from app.services.cv_document_versions import freeze_approved_version

    stage_cvs = (
        await db.scalars(
            select(CandidateStageCV)
            .where(CandidateStageCV.generated_document_id == row.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).all()
    reapproved: list[int] = []
    for csv in stage_cvs:
        csv.branded_consent_content = image
        csv.branded_render_metadata = _with_consent_digest(
            csv.branded_render_metadata, image
        )
        if csv.branded_status != "finalized":
            continue
        approved = await freeze_approved_version(db, csv)
        if (
            _sha((csv.branded_draft_html or "").encode()) != approved.content_sha256
            or not (csv.branded_draft_html or "").strip()
        ):
            continue
        previous_review = _reapproval_review(approved.render_metadata)
        csv.branded_version += 1
        csv.branded_status = "draft"
        version, _filename, _size = await finalize_stage_cv(
            db,
            csv,
            csv.branded_draft_html,
            user_id,
            review_override=previous_review,
            activity_details={"reason": "consent_attached"},
        )
        reapproved.append(version.id)
    return reapproved


__all__ = ["attach", "binding_context", "render_with_consent"]
