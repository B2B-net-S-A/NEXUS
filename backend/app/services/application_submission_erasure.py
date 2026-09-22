"""Usuwanie zgłoszeń z formularza aplikacyjnego razem z kandydatem (art. 17).

Audyt 22.09.2026 r2 (CAND-02). `application_submissions.matched_candidate_id`
ma ``ON DELETE SET NULL``, więc przed tą zmianą usunięcie profilu zostawiało
zgłoszenia z CV (bajty w bazie albo obiekt w storage), telefonem, LinkedInem
i treścią wiadomości. Zgody zgłoszeń (``candidate_consents``) kaskadują
z wiersza zgłoszenia — liczymy je przed usunięciem do dowodu wykonania.

Pliki NIE są kasowane tutaj: klucze wracają do wołającego, który wpisuje je
do trwałego rejestru kasowań w tej samej transakcji. Klucz, na który wskazuje
jeszcze CV lub dokument INNEGO kandydata (rozstrzygnięcie „create” zakłada
nowy profil na tym samym obiekcie), zostaje w storage.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application_submission import ApplicationSubmission
from app.models.candidate import Candidate
from app.models.candidate_consent import CandidateConsent
from app.models.candidate_document import CandidateDocument


async def erase_candidate_submissions(
    db: AsyncSession, *, candidate_id: int, email: Optional[str]
) -> dict[str, Any]:
    """Kasuje zgłoszenia osoby; zwraca liczniki i klucze plików do rejestru."""
    match = ApplicationSubmission.matched_candidate_id == candidate_id
    normalized = (email or "").strip().lower()
    where = (
        or_(match, func.lower(ApplicationSubmission.submitted_email) == normalized)
        if normalized
        else match
    )
    rows = (
        await db.execute(
            select(ApplicationSubmission.id, ApplicationSubmission.cv_object_key)
            .where(where)
            .with_for_update()
        )
    ).all()
    if not rows:
        return {
            "application_submissions_deleted": 0,
            "application_consents_deleted": 0,
            "storage_keys": [],
        }
    ids = [row.id for row in rows]
    keys = {row.cv_object_key for row in rows if row.cv_object_key}
    if keys:
        shared_docs = await db.scalars(
            select(CandidateDocument.storage_key).where(
                CandidateDocument.storage_key.in_(keys),
                CandidateDocument.candidate_id != candidate_id,
            )
        )
        shared_cvs = await db.scalars(
            select(Candidate.cv_storage_key).where(
                Candidate.cv_storage_key.in_(keys),
                Candidate.id != candidate_id,
            )
        )
        keys -= set(shared_docs.all()) | set(shared_cvs.all())

    consents = (
        await db.execute(
            delete(CandidateConsent).where(
                CandidateConsent.application_submission_id.in_(ids)
            )
        )
    ).rowcount or 0
    deleted = (
        await db.execute(
            delete(ApplicationSubmission).where(ApplicationSubmission.id.in_(ids))
        )
    ).rowcount or 0
    return {
        "application_submissions_deleted": deleted,
        "application_consents_deleted": consents,
        "storage_keys": sorted(keys),
    }
