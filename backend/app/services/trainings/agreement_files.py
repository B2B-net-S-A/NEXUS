"""PDF umowy szkoleniowej do pobrania: szkic do podpisu, wersja trenera, komplet podpisów."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi.responses import FileResponse

from app.core.http_headers import content_disposition
from app.models.training import Training
from app.services import storage_service
from app.services.trainings import agreement
from app.services.trainings.errors import TrainingError

MISSING = "Tej wersji umowy jeszcze nie ma."


def path_for(relative: Optional[str]) -> Path:
    """Plik pod ``STORAGE_ROOT/trainings``, bez wyjścia poza ten katalog."""

    if not relative:
        raise TrainingError(404, MISSING, "no_agreement")
    root = (Path(storage_service.STORAGE_ROOT) / "trainings").resolve()
    path = (Path(storage_service.STORAGE_ROOT) / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise TrainingError(404, MISSING, "no_agreement") from None
    if not path.is_file():
        raise TrainingError(404, MISSING, "no_agreement")
    return path


def response(training: Training, version: str) -> FileResponse:
    relative = {
        "draft": training.agreement_pdf_path,
        "trainer": training.trainer_signed_pdf_path,
        "signed": training.company_signed_pdf_path,
    }[version]
    suffix = {
        "draft": "",
        "trainer": " podpisana przez trenera",
        "signed": " podpisana",
    }[version]
    return FileResponse(
        path_for(relative),
        media_type="application/pdf",
        headers={
            "Content-Disposition": content_disposition(
                agreement.file_name(training, suffix=suffix)
            ),
            "Cache-Control": "private, no-store",
        },
    )
