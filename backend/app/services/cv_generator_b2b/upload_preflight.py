"""Host-only upload checks before a generation slot or AI quota is consumed.

PDF image pages remain eligible for the existing OCR worker. This preflight
does not claim that OCR will recognize their content and never runs OCR/AI.
"""

from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from app.services.cv_generator_b2b.standalone_service import (
    UploadGenerationInput,
    StandaloneGenerationError,
    _validate_upload,
    _ALLOWED_CV_EXT,
    _ALLOWED_CHAMPION_EXT,
    _MAX_UPLOAD_BYTES,
)
from app.services.cv_generator_b2b.champion_builder import (
    parse_champion_from_docx_bytes,
)
from app.services.cv_generator_b2b.text_extractor import extract_text_from_file

MAX_UPLOAD_BYTES = _MAX_UPLOAD_BYTES


def _docx_container(data: bytes) -> None:
    with ZipFile(BytesIO(data)) as archive:
        # Protect the host before python-docx inflates an uploaded archive.
        if sum(info.file_size for info in archive.infolist()) > MAX_UPLOAD_BYTES * 4:
            raise ValueError("DOCX expansion limit")
        if "word/document.xml" not in archive.namelist():
            raise ValueError("DOCX document missing")


def validate_upload_inputs(payload: UploadGenerationInput) -> None:
    _validate_upload(
        payload.cv_bytes, payload.cv_filename, allowed_ext=_ALLOWED_CV_EXT, label="CV"
    )
    try:
        if Path(payload.cv_filename).suffix.lower() == ".docx":
            _docx_container(payload.cv_bytes)
            if not extract_text_from_file(
                payload.cv_bytes, payload.cv_filename
            ).strip():
                raise ValueError("Empty DOCX")
        else:
            import pdfplumber

            with pdfplumber.open(BytesIO(payload.cv_bytes)) as pdf:
                if not any(page.chars or page.images for page in pdf.pages):
                    raise ValueError("Empty PDF")
    except Exception as error:
        raise StandaloneGenerationError(
            "invalid_input",
            "CV: nie można odczytać dokumentu lub plik jest pusty. Wgraj poprawny PDF/DOCX; PDF nie może być zabezpieczony hasłem.",
        ) from error

    champion = None
    if payload.champion_bytes is not None:
        filename = payload.champion_filename or ""
        _validate_upload(
            payload.champion_bytes,
            filename,
            allowed_ext=_ALLOWED_CHAMPION_EXT,
            label="Profil Championa",
        )
        try:
            _docx_container(payload.champion_bytes)
            champion = parse_champion_from_docx_bytes(payload.champion_bytes, filename)
        except Exception as error:
            raise StandaloneGenerationError(
                "invalid_input",
                "Profil Championa: nie można odczytać pliku DOCX. Wgraj poprawny dokument.",
            ) from error

    required = bool(payload.client_rule and payload.client_rule.require_champion)
    manual = bool(
        payload.must_requirements.strip() or payload.nice_requirements.strip()
    )
    if required and not manual and (champion is None or champion.is_empty()):
        raise StandaloneGenerationError(
            "invalid_input",
            "Ten klient wymaga Profilu Championa, ale nie rozpoznano jego treści. Uzupełnij MUST-HAVE / NICE-TO-HAVE lub wgraj poprawny profil.",
        )
