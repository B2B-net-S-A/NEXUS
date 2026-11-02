"""Kto może zapisać plik kandydata na dysk (decyzja Artura 02.11.2026).

Rekruterzy pobierali CV hurtem do prywatnych baz i czatów: od 23.10 do 02.11
dni z 10 lub więcej osobami to 260 z 381 zapisów, a tylko 1 z nich wróciło do
karty jako wgrane CV. Dlatego osoba z SAMĄ rolą rekrutera ogląda pliki
w NEXUSIE, a oryginał CV pobiera tylko z karty „CV do klienta”, po próbie
z generatorem i z podaniem, co generator zrobił źle. Każda rola dodatkowa
zwalnia z tej zasady. Osoba wrzucająca do Cpro pracuje na plikach, więc też
jest zwolniona.

Bramka patrzy na to, o co prosi klient (``disposition``), a nie na to, co
oddaje nagłówek: ``safe_document_disposition`` zmienia ``inline`` pliku Word na
``attachment``, a podgląd Worda ma działać dalej.
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole

UNRESTRICTED_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.head_of_recruitment,
    UserRole.delivery_lead,
    UserRole.talent_community_manager,
    UserRole.finance,
    UserRole.automation,
)

#: Lustro `previewKind` w `frontend/src/components/v2/files/FilePreviewModal.tsx`.
#: Plik spoza listy nie ma podglądu, więc pobranie jest jedyną drogą do treści.
_PREVIEW_EXTENSIONS = frozenset(
    {".pdf", ".docx", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}
)
_DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)

#: Lustro listy w `frontend/src/lib/cv-download-access.ts`.
FEEDBACK_REASONS: tuple[str, ...] = (
    "why_candidate",
    "requirements_in_roles",
    "lost_experience",
    "invented",
    "years",
    "tone",
    "skills",
    "layout",
    "client_asked",
    "other",
)
FEEDBACK_DETAIL_MAX = 1000

DOWNLOAD_BLOCKED_CODE = "cv_download_blocked"
DOWNLOAD_BLOCKED_MESSAGE = (
    "Pliki kandydata oglądasz w NEXUSIE. Oryginał CV pobierzesz z karty "
    "„CV do klienta”, jeśli generator zrobi złe CV."
)


def is_recruiter_only(user: User) -> bool:
    """Rekruter bez żadnej roli, która zwalnia z ograniczenia."""

    return user.has_role(UserRole.recruiter) and not user.has_any_role(
        *UNRESTRICTED_ROLES
    )


def has_inline_preview(filename: Optional[str], content_type: Optional[str]) -> bool:
    media_type = (content_type or "").split(";", 1)[0].strip().lower()
    if media_type in {"application/pdf", _DOCX_MEDIA_TYPE}:
        return True
    if media_type.startswith("image/"):
        return True
    return os.path.splitext(filename or "")[1].lower() in _PREVIEW_EXTENSIONS


async def _handles_cpro(db: AsyncSession, user_id: int) -> bool:
    from app.models.job import Job
    from app.models.recruitment_pipeline import CandidateStage
    from app.services import cpro_sender

    # Ta sama kolejność co `board_tasks`: osoba na firmę (z zastępcą z urlopu),
    # a kolumny przy rekrutacji i etapie liczą się tylko, gdy nikogo na firmę nie ma.
    state = await cpro_sender.firm_sender(db)
    effective = await cpro_sender.effective_sender(db)
    if user_id in (state.user_id, state.fallback_user_id, effective.user_id):
        return True
    if effective.user_id is not None:
        return False
    return bool(
        await db.scalar(
            select(
                or_(
                    exists().where(Job.cpro_sender_id == user_id),
                    exists().where(CandidateStage.task_assignee_id == user_id),
                )
            )
        )
    )


async def ensure_can_save_file(
    db: AsyncSession,
    user: User,
    *,
    filename: Optional[str],
    content_type: Optional[str],
) -> None:
    """Odmów zapisu na dysk osobie z samą rolą rekrutera.

    Wołaj tylko dla żądania zapisu (``disposition=attachment``), po sprawdzeniu,
    że plik istnieje. Pliku bez podglądu nie blokujemy: inaczej nikt nie
    zobaczyłby jego treści.
    """

    if not is_recruiter_only(user):
        return
    if not has_inline_preview(filename, content_type):
        return
    if await _handles_cpro(db, user.id):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": DOWNLOAD_BLOCKED_CODE,
            "message": DOWNLOAD_BLOCKED_MESSAGE,
        },
    )
