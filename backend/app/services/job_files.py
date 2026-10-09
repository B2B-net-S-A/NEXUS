"""Pliki rekrutacji: reguły przyjęcia, zapis, przepięcie z formularza, sieroty (0427).

Delivery Lead dokłada pliki na ``/jobs/new`` (request klienta z kroku 1 zapisuje
się sam, kolejne dodaje ręcznie), a zespół widzi je w menu „⋯” rekrutacji.
Rekrutacja powstaje dopiero przy „Utwórz i przekaż”, więc do tego czasu plik
należy do niedokończonego formularza autora; ``attach_intake_files`` przepina
go na rekrutację w transakcji tworzenia.

Pliki leżą na dysku (``storage_service.save_job_file``), wiersz niesie nazwę,
typ i rozmiar. Typ dokumentu przy pobraniu bierzemy z ROZSZERZENIA, nie
z nagłówka przeglądarki — plik podpisany jako ``text/html`` nie może się
otworzyć w karcie na adresie API.

Nazwy plików to dane klienta — do logów idzie wyłącznie identyfikator.
"""

from __future__ import annotations

import io
import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import UploadFile
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.upload_filename import fit_filename_column
from app.models.job_file import JobFile
from app.models.user import User
from app.services import storage_service
from app.services.job_file_schema import SOURCE_REQUEST, SOURCE_UPLOAD, SOURCES

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_FILES = 20
ORPHAN_BATCH = 200

# Rozszerzenie → typ, z którym plik wraca przy pobraniu.
CONTENT_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".eml": "message/rfc822",
    ".msg": "application/vnd.ms-outlook",
}

ALLOWED_TEXT = (
    "PDF, Word, Excel, PowerPoint, TXT, CSV, PNG, JPG albo wiadomość (EML, MSG)"
)
MSG_TYPE = f"Tego typu pliku nie da się dodać. Dozwolone: {ALLOWED_TEXT}."
MSG_EMPTY = "Plik jest pusty."
MSG_TOO_BIG = f"Plik jest za duży — najwyżej {MAX_FILE_BYTES // (1024 * 1024)} MB."
MSG_TOO_MANY = f"Rekrutacja może mieć najwyżej {MAX_FILES} plików. Usuń któryś, żeby dodać kolejny."
MSG_SOURCE = "Nieznane źródło pliku."


@dataclass(frozen=True)
class JobFileRefused(Exception):
    """Odmowa przyjęcia pliku: kod HTTP i zdanie dla użytkownika."""

    status: int
    message: str

    def __str__(self) -> str:  # pragma: no cover — tylko do logów
        return self.message


def checked_name(filename: Optional[str]) -> tuple[str, str]:
    """(nazwa do pokazania, typ dokumentu) albo ``JobFileRefused`` 415."""
    name = os.path.basename((filename or "").replace("\\", "/"))
    # Znaki sterujące (NUL, CR, LF…) nie są nazwą: Postgres odrzuca NUL,
    # a reszta trafiłaby do nagłówka pobrania.
    name = "".join(ch for ch in name if ch.isprintable()).strip()
    extension = os.path.splitext(name)[1].lower()
    content_type = CONTENT_TYPES.get(extension)
    if not name or content_type is None:
        raise JobFileRefused(415, MSG_TYPE)
    return fit_filename_column(name), content_type


async def read_bounded(upload: UploadFile) -> bytes:
    """Treść pliku, nigdy więcej niż limit + 1 bajt w pamięci."""
    data = await upload.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise JobFileRefused(413, MSG_TOO_BIG)
    if not data:
        raise JobFileRefused(422, MSG_EMPTY)
    return data


def _owner_clause(*, job_id: Optional[int], form_id: Optional[int]):
    if (job_id is None) == (form_id is None):
        raise ValueError("job_files: podaj dokładnie jedno — rekrutację albo formularz")
    if job_id is not None:
        return JobFile.job_id == job_id
    return JobFile.intake_form_id == form_id


async def _lock_owner(
    db: AsyncSession, *, job_id: Optional[int], form_id: Optional[int]
) -> None:
    """Blokada doradcza na właściciela plików — limit liczony bez wyścigu."""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:scope), :owner)"),
        {
            "scope": "job_files:job" if job_id is not None else "job_files:form",
            "owner": job_id if job_id is not None else form_id,
        },
    )


async def add_file(
    db: AsyncSession,
    *,
    upload: UploadFile,
    user_id: int,
    source: str = SOURCE_UPLOAD,
    job_id: Optional[int] = None,
    form_id: Optional[int] = None,
) -> JobFile:
    """Przyjmij plik i zapisz wiersz (bez commita). Odmowa = ``JobFileRefused``."""
    if source not in SOURCES:
        raise JobFileRefused(422, MSG_SOURCE)
    name, content_type = checked_name(upload.filename)
    data = await read_bounded(upload)
    await _lock_owner(db, job_id=job_id, form_id=form_id)
    count = await db.scalar(
        select(func.count(JobFile.id)).where(
            _owner_clause(job_id=job_id, form_id=form_id)
        )
    )
    if int(count or 0) >= MAX_FILES:
        raise JobFileRefused(409, MSG_TOO_MANY)
    relative_path, size = storage_service.save_job_file(name, io.BytesIO(data))
    row = JobFile(
        job_id=job_id,
        intake_form_id=form_id,
        source=source,
        filename=name,
        file_path=relative_path,
        content_type=content_type,
        size_bytes=size,
        uploaded_by=user_id,
    )
    db.add(row)
    try:
        await db.flush()
    except Exception:
        # Wiersz się nie zapisał — plik na dysku byłby sierotą bez rejestru.
        storage_service.delete_job_file(relative_path)
        raise
    return row


async def list_files(
    db: AsyncSession, *, job_id: Optional[int] = None, form_id: Optional[int] = None
) -> list[dict[str, Any]]:
    """Pliki rekrutacji albo formularza: najpierw request klienta, potem po kolei."""
    rows = (
        await db.execute(
            select(JobFile, User.name)
            .outerjoin(User, User.id == JobFile.uploaded_by)
            .where(_owner_clause(job_id=job_id, form_id=form_id))
            .order_by(
                (JobFile.source != SOURCE_REQUEST), JobFile.created_at, JobFile.id
            )
        )
    ).all()
    return [serialize(row, uploader_name) for row, uploader_name in rows]


def serialize(row: JobFile, uploader_name: Optional[str] = None) -> dict[str, Any]:
    return {
        "id": row.id,
        "filename": row.filename,
        "content_type": row.content_type,
        "size_bytes": row.size_bytes,
        "source": row.source,
        "uploaded_by": row.uploaded_by,
        "uploaded_by_name": (uploader_name or "").strip() or None,
        "created_at": row.created_at,
    }


async def get_file(
    db: AsyncSession,
    file_id: int,
    *,
    job_id: Optional[int] = None,
    form_id: Optional[int] = None,
) -> Optional[JobFile]:
    return await db.scalar(
        select(JobFile).where(
            JobFile.id == file_id, _owner_clause(job_id=job_id, form_id=form_id)
        )
    )


async def attach_intake_files(
    db: AsyncSession, *, job_id: int, form_id: Optional[int], user_id: int
) -> int:
    """Pliki niedokończonego formularza przechodzą na nowo założoną rekrutację.

    Wołać w transakcji tworzenia, PRZED usunięciem formularza (klucz obcy
    ustawiłby ``intake_form_id`` na NULL i plik zostałby sierotą). Cudzy
    formularz niczego nie oddaje — tak jak jego usunięcie jest wtedy no-opem.
    """
    if form_id is None:
        return 0
    result = await db.execute(
        text(
            "UPDATE job_files SET job_id = :job, intake_form_id = NULL, "
            "updated_at = now() "
            "WHERE intake_form_id = :form AND intake_form_id IN ("
            "SELECT id FROM job_intake_forms WHERE id = :form AND user_id = :uid)"
        ),
        {"job": job_id, "form": form_id, "uid": user_id},
    )
    return int(result.rowcount or 0)


async def file_paths_of_job(db: AsyncSession, job_id: int) -> list[str]:
    """Ścieżki plików rekrutacji — do skasowania z dysku PO usunięciu rekrutacji."""
    return list(
        (
            await db.scalars(select(JobFile.file_path).where(JobFile.job_id == job_id))
        ).all()
    )


def delete_stored(paths: list[str]) -> None:
    for path in paths:
        storage_service.delete_job_file(path)


async def sweep_orphans(db: AsyncSession) -> int:
    """Usuń wiersze bez rekrutacji i bez formularza razem z plikami.

    Tak wygląda plik formularza, który autor usunął albo który zniknął po
    30 dniach retencji (klucz obcy ustawia ``intake_form_id`` na NULL). Wiersz
    znika pierwszy i dopiero po commicie plik — nieudana transakcja nie
    zostawia rejestru bez pliku. Sam commituje.
    """
    rows = (
        await db.execute(
            delete(JobFile)
            .where(
                JobFile.id.in_(
                    select(JobFile.id)
                    .where(JobFile.job_id.is_(None), JobFile.intake_form_id.is_(None))
                    .order_by(JobFile.id)
                    .limit(ORPHAN_BATCH)
                )
            )
            .returning(JobFile.file_path)
        )
    ).all()
    await db.commit()
    delete_stored([path for (path,) in rows])
    if rows:
        logger.info("job_files: usunięto %d osieroconych plików", len(rows))
    return len(rows)
