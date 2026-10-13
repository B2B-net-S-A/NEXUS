"""Version snapshots created while holding the stage-CV row lock."""

import hashlib
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select, update

from app.models.candidate import Candidate
from app.models.cv_document_version import CvDocumentVersion
from app.models.cv_share_token import CVShareToken
from app.models.job import Job
from app.models.user import User


def public_first_name(name, template, language):
    """Imię pokazywane klientowi pod linkiem — przy szablonie blind zamaskowane.

    Runda 9 (R9-N3-1): wersja CV etapu w szablonie blind zapisywała prawdziwe
    imię kandydata, a publiczny link `/cv/{token}` je zwracał. Lustro maskowania
    `public_view._mask_blind` i widoku `/cv/i/`.
    """
    if template == "blind":
        return "Candidate" if language == "en" else "Kandydat"
    return name


def check_revision(csv, expected: int) -> None:
    if expected != (csv.edit_revision or 0):
        raise HTTPException(
            409,
            "CV zostało zmienione w innej sesji. Zachowaj swoje poprawki i wczytaj aktualną wersję.",
        )


async def freeze_approved_version(
    db, csv, *, docx_content=None, docx_filename=None, render_metadata=None
):
    """Also pins legacy tokens before creating a new draft. No token is revoked."""
    if csv.branded_status != "finalized":
        raise HTTPException(409, "Najpierw zatwierdź bieżącą wersję CV.")
    version = await db.scalar(
        select(CvDocumentVersion).where(
            CvDocumentVersion.candidate_stage_cv_id == csv.id,
            CvDocumentVersion.version == csv.branded_version,
        )
    )
    if version is None:
        candidate = await db.get(Candidate, csv.candidate_id)
        job = await db.get(Job, csv.job_id)
        html = csv.branded_draft_html or ""
        version = CvDocumentVersion(
            candidate_stage_cv_id=csv.id,
            version=csv.branded_version,
            generated_document_id=csv.generated_document_id,
            content_html=html,
            template_content=csv.branded_template_content,
            consent_content=csv.branded_consent_content,
            docx_content=docx_content,
            docx_sha256=hashlib.sha256(docx_content).hexdigest()
            if docx_content
            else None,
            docx_filename=docx_filename,
            render_metadata=render_metadata,
            content_sha256=hashlib.sha256(html.encode()).hexdigest(),
            template=csv.branded_template,
            language=csv.branded_language,
            candidate_first_name=public_first_name(
                candidate.name if candidate else None,
                csv.branded_template,
                csv.branded_language,
            ),
            job_title=job.title if job else None,
            snapshot_path=csv.branded_snapshot_path,
            snapshot_filename=csv.branded_snapshot_filename,
            snapshot_size_bytes=csv.branded_snapshot_size_bytes,
            approved_at=csv.branded_finalized_at or datetime.now(timezone.utc),
            approved_by=csv.branded_finalized_by,
        )
        db.add(version)
        await db.flush()
    await db.execute(
        update(CVShareToken)
        .where(
            CVShareToken.candidate_stage_cv_id == csv.id,
            CVShareToken.document_version_id.is_(None),
        )
        .values(document_version_id=version.id)
    )
    return version


# ── Historia wersji w edytorze CV (tylko odczyt) ─────────────────────────────


def _history_language(value):
    """Kontrakt historii zna dwa języki; wiersz bez języka to polskie CV."""
    return "en" if value == "en" else "pl"


def _approved_without_row(csv, versions) -> bool:
    """Etap pokazuje zatwierdzone CV, którego nikt jeszcze nie zamroził.

    Wiersz wersji powstaje przy zatwierdzeniu od migracji 0287 (bez
    uzupełnienia wstecz); starsze zatwierdzone CV dostaje go dopiero przy
    nowym szkicu albo linku (`freeze_approved_version`). Odczyt historii
    niczego nie zapisuje, więc bierze taką wersję z wiersza etapu.
    """
    return csv.branded_status == "finalized" and csv.branded_version not in versions


def version_summaries(csv, rows, unfrozen_approver=None):
    """Zatwierdzone wersje CV etapu, od najnowszej. Bez bazy.

    ``rows``: ``(version, approved_at, approver_name, language, has_docx)``.
    „Bieżąca” jest wersja, którą etap pokazuje teraz jako zatwierdzoną:
    zatwierdzony etap i jego numer. Otwarty szkic nosi już następny numer,
    więc żadna wersja nie jest wtedy bieżąca.
    """
    approved = csv.branded_status == "finalized"
    listed = [
        {
            "version": version,
            "approved_at": approved_at,
            "approved_by_name": (name or "").strip() or None,
            "language": _history_language(language),
            "docx_available": bool(has_docx),
            "is_current": approved and version == csv.branded_version,
        }
        for version, approved_at, name, language, has_docx in rows
    ]
    if _approved_without_row(csv, {item["version"] for item in listed}):
        listed.append(
            {
                "version": csv.branded_version,
                "approved_at": csv.branded_finalized_at,
                "approved_by_name": (unfrozen_approver or "").strip() or None,
                "language": _history_language(csv.branded_language),
                # Plik Word leży w wierszu wersji, a tego jeszcze nie ma.
                "docx_available": False,
                "is_current": True,
            }
        )
    return sorted(listed, key=lambda item: item["version"], reverse=True)


async def stage_versions(db, csv):
    """Lista historii wersji CV etapu. Czyta same metadane, bez treści i plików."""
    rows = (
        await db.execute(
            select(
                CvDocumentVersion.version,
                CvDocumentVersion.approved_at,
                User.name,
                CvDocumentVersion.language,
                CvDocumentVersion.docx_content.is_not(None),
            )
            .outerjoin(User, User.id == CvDocumentVersion.approved_by)
            .where(CvDocumentVersion.candidate_stage_cv_id == csv.id)
            .order_by(CvDocumentVersion.version.desc())
        )
    ).all()
    approver = None
    if csv.branded_finalized_by and _approved_without_row(
        csv, {row[0] for row in rows}
    ):
        approver = await db.scalar(
            select(User.name).where(User.id == csv.branded_finalized_by)
        )
    return version_summaries(csv, rows, approver)


async def stage_version_content(db, csv, version_number):
    """Treść jednej zatwierdzonej wersji CV etapu albo ``None``, gdy jej nie ma."""
    row = (
        await db.execute(
            select(
                CvDocumentVersion.content_html,
                CvDocumentVersion.language,
                CvDocumentVersion.approved_at,
            ).where(
                CvDocumentVersion.candidate_stage_cv_id == csv.id,
                CvDocumentVersion.version == version_number,
            )
        )
    ).first()
    if row is not None:
        html, language, approved_at = row
    elif csv.branded_status == "finalized" and version_number == csv.branded_version:
        # Zatwierdzone CV bez wiersza wersji — patrz `_approved_without_row`.
        html = csv.branded_draft_html or ""
        language, approved_at = csv.branded_language, csv.branded_finalized_at
    else:
        return None
    return {
        "version": version_number,
        "content_html": html,
        "language": _history_language(language),
        "approved_at": approved_at,
    }
