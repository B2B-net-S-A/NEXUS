"""Readiness of new central-policy packages; historical documents stay untouched."""

from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
import re

from fastapi import HTTPException
from PIL import Image
from sqlalchemy import select, or_
from sqlalchemy.exc import DBAPIError

from app.models.cv_generation_job import CvGenerationJob
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.cv_document_version import CvDocumentVersion
from app.models.cv_generated_draft import CvGeneratedDraft
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.note import Note
from app.models.job import Job
from app.services.cv_source_cleanup import is_purged_key
from app.services.cv_generated_approval import approved_version_for_generation


def digest(value):
    return sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def project_number(value):
    return re.sub(r"^(?:ZOB[\s_-]*)+", "", (value or "").strip(), flags=re.I).strip()


async def members(db, generated, *, lock=False):
    query = select(CvGenerationJob).where(
        or_(
            CvGenerationJob.generated_id == generated.id,
            CvGenerationJob.second_generated_id == generated.id,
        )
    )
    job = await db.scalar(
        query.with_for_update().execution_options(populate_existing=True)
        if lock
        else query
    )
    ids = [job.generated_id, job.second_generated_id] if job else [generated.id]
    query = (
        select(CvGeneratedDocument)
        .where(CvGeneratedDocument.id.in_([i for i in ids if i]))
        .order_by(CvGeneratedDocument.id)
    )
    rows = list(
        (
            await db.scalars(
                query.with_for_update().execution_options(populate_existing=True)
                if lock
                else query
            )
        ).all()
    )
    primary = next(
        row for row in rows if row.id == (job.generated_id if job else generated.id)
    )
    return job, primary, rows


async def assess(db, generated, *, note_id=None, lock=False):
    job, primary, rows = await members(db, generated, lock=lock)
    policy = primary.central_policy
    if not policy:
        return {"managed": False}, None
    review = primary.package_review or {}
    if note_id is None:
        note_id = review.get("note_id")
    reasons, documents, fingerprints, versions = [], [], {}, {}
    for row in rows:
        version = await db.scalar(
            select(CvDocumentVersion)
            .where(CvDocumentVersion.generated_document_id == row.id)
            .order_by(CvDocumentVersion.id.desc())
            .limit(1)
        )
        documents.append(
            {
                "id": row.id,
                "language": row.language,
                "status": row.status,
                "filename": row.filename,
                "approved_version_id": version.id if version else None,
            }
        )
        if row.status != "ready" or version is None:
            reasons.append(f"{row.language.upper()}: brak zatwierdzonego dokumentu.")
            continue
        version = await approved_version_for_generation(db, row, version.id)
        owner_query = (
            select(CvGeneratedDraft).where(
                CvGeneratedDraft.generated_document_id == row.id
            )
            if version.generated_owner_id
            else select(CandidateStageCV).where(
                CandidateStageCV.id == version.candidate_stage_cv_id
            )
        )
        try:
            owner = await db.scalar(
                owner_query.with_for_update(nowait=True).execution_options(
                    populate_existing=True
                )
                if lock
                else owner_query
            )
        except DBAPIError as exc:
            code = getattr(exc.orig, "sqlstate", None) or getattr(
                exc.orig, "pgcode", None
            )
            if code != "55P03":
                raise
            raise HTTPException(
                409, "CV jest właśnie edytowane. Odśwież pakiet i ponów potwierdzenie."
            ) from exc
        if owner is not None and (
            owner.branded_status != "finalized"
            or sha256((owner.branded_draft_html or "").encode()).hexdigest()
            != version.content_sha256
        ):
            reasons.append(
                f"{row.language.upper()}: dokument zmieniono po zatwierdzeniu."
            )
        if version.language != row.language:
            reasons.append(
                f"{row.language.upper()}: niezgodny język zatwierdzonej wersji."
            )
        if policy.get("requires_rodo_consent_block"):
            binding = (
                (row.render_payload or {}).get("consent_screenshot", {}).get("binding")
            )
            try:
                if not binding or not version.consent_content:
                    raise ValueError
                subject = binding.get("subject") or {}
                if (
                    subject.get("client_id") != row.client_id
                    or subject.get("recruitment_stage_id") != policy.get("stage_id")
                    or subject.get("project_ref")
                    != project_number(policy.get("project_ref"))
                ):
                    raise ValueError
                with Image.open(BytesIO(version.consent_content)) as image:
                    image.verify()
            except (ValueError, OSError, SyntaxError):
                reasons.append("Brak poprawnego, powiązanego załącznika zgody.")
        versions[row.language] = version.id
        fingerprints[str(row.id)] = {
            "version_id": version.id,
            "html": version.content_sha256,
            "docx": version.docx_sha256,
            "edit_revision": owner.edit_revision if owner else None,
        }
    required = policy["required_languages"]
    available = [row.language for row in rows if row.status == "ready"]
    for language in required:
        if language not in available:
            reasons.append(f"Brak wygenerowanej wersji {language.upper()}.")
    if policy.get("require_position") and not (primary.position or "").strip():
        reasons.append("Brak stanowiska do nazwy CV.")
    if policy.get("require_project_ref") and not policy.get("project_ref", "").strip():
        reasons.append("Brak numeru projektu / zapytania.")
    if policy.get("requires_rodo_consent_block"):
        recruitment = await db.get(Job, primary.job_id) if primary.job_id else None
        reference = getattr(recruitment, "reference_number", None)
        if not reference or project_number(reference) != project_number(
            policy.get("project_ref")
        ):
            reasons.append(
                "Numer zapytania musi być zgodny z numerem rekrutacji PKO BP."
            )
    note_state = None
    if note_id:
        query = select(Note).where(Note.id == note_id)
        note = await db.scalar(query.with_for_update() if lock else query)
        superseded = await db.scalar(
            select(Note.id).where(Note.supersedes_note_id == note_id).limit(1)
        )
        if (
            note is None
            or not primary.candidate_id
            or not primary.job_id
            or note.candidate_id != primary.candidate_id
            or note.job_id != primary.job_id
            or note.source_deleted_at
            or superseded
            or not note.content.strip()
        ):
            reasons.append(
                "Wybierz aktualną notatkę rekomendacyjną tego kandydata w tej rekrutacji."
            )
        else:
            note_state = {
                "id": note.id,
                "updated_at": str(note.updated_at),
                "hash": sha256(note.content.encode()).hexdigest(),
            }
    elif policy.get("require_recommendation_note"):
        reasons.append("Nie wskazano notatki rekomendacyjnej dla tej rekrutacji.")
    fingerprint = digest(
        {"documents": fingerprints, "policy": policy, "note": note_state}
    )
    confirmed = (
        review.get("fingerprint") == fingerprint
        and review.get("sources_checked") is True
    )
    if not confirmed:
        reasons.append("Potwierdź sprawdzenie aktualnych CV i notatki względem źródeł.")
    state = {
        "fingerprint": fingerprint,
        "managed": True,
        "package_id": primary.id,
        "effective_policy": policy,
        "required_languages": required,
        "available_languages": available,
        "documents": documents,
        "note_id": note_id,
        "ready": not reasons,
        "reasons": list(dict.fromkeys(reasons)),
        "sources_checked": confirmed,
        "generic": primary.content_mode != "tailored",
        "can_retry": bool(
            job
            and job.status not in ("queued", "running")
            and job.prepared_source_facts
            and not is_purged_key(job.input_storage_key)
            and set(required) - set(available)
        ),
        "generation_status": job.status if job else primary.status,
    }
    return state, {
        "primary": primary,
        "fingerprint": fingerprint,
        "note": note_state,
        "versions": versions,
        "policy": policy,
    }


async def confirm(
    db, generated, *, note_id, sources_checked, user_id, expected_fingerprint
):
    state, data = await assess(db, generated, note_id=note_id, lock=True)
    if not data:
        raise HTTPException(
            409, "Dokument historyczny nie wymaga nowego potwierdzenia pakietu."
        )
    if expected_fingerprint != data["fingerprint"]:
        raise HTTPException(
            409,
            "Pakiet lub notatka zmieniły się. Odśwież podgląd i sprawdź je ponownie.",
        )
    missing = [r for r in state["reasons"] if not r.startswith("Potwierdź sprawdzenie")]
    if missing or not sources_checked:
        raise HTTPException(
            409,
            {
                "message": "Pakiet nie jest gotowy.",
                "reasons": missing or ["Potwierdź sprawdzenie CV względem źródeł."],
            },
        )
    data["primary"].package_review = {
        "fingerprint": data["fingerprint"],
        "note_id": note_id,
        "note_version": data["note"],
        "policy": data["policy"],
        "document_versions": data["versions"],
        "sources_checked": True,
        "reviewed_by": user_id,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.flush()
    return (await assess(db, generated))[0]


async def require_ready(db, generated, selected_version_id):
    if not getattr(generated, "central_policy", None):
        return None
    state, data = await assess(db, generated, lock=True)
    if not state["ready"] or selected_version_id not in data["versions"].values():
        raise HTTPException(
            409,
            {
                "message": "Pakiet CV nie jest gotowy do udostępnienia.",
                "reasons": state["reasons"]
                or ["Wybrana wersja nie należy do zatwierdzonego pakietu."],
            },
        )
    return data["versions"]


async def public_documents(db, package_versions):
    """Only versions frozen into this token; no current drafts, notes or policy internals."""
    if not package_versions:
        return {}
    documents = []
    for language, version_id in package_versions.items():
        version = await db.get(CvDocumentVersion, version_id)
        if (
            version is None
            or version.language != language
            or not version.docx_content
            or sha256(version.docx_content).hexdigest() != version.docx_sha256
            or sha256(version.content_html.encode()).hexdigest()
            != version.content_sha256
        ):
            raise HTTPException(409, "Nie można potwierdzić integralności pakietu CV.")
        from app.services.html_sanitizer import sanitize_cv_html

        documents.append(
            {
                "language": language,
                "filename": version.docx_filename,
                "cv_html": sanitize_cv_html(version.content_html),
            }
        )
    return {"package_documents": documents}
