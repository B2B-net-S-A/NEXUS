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
from app.services.cv_generator_b2b.text_extractor import (
    CVTextExtractionError,
    extract_text_from_file,
)
from app.services.cv_text_extractor import sniff_extension_bytes

MAX_UPLOAD_BYTES = _MAX_UPLOAD_BYTES
_CHAMPION_UNREADABLE = (
    "Profil Championa: nie można odczytać pliku DOCX. Wgraj poprawny dokument."
)


class DocxExpansionLimit(ValueError):
    """The archive would inflate past the host limit — a size problem, not damage."""


def _docx_container(data: bytes) -> None:
    with ZipFile(BytesIO(data)) as archive:
        # Protect the host before python-docx inflates an uploaded archive.
        if sum(info.file_size for info in archive.infolist()) > MAX_UPLOAD_BYTES * 4:
            raise DocxExpansionLimit("DOCX expansion limit")
        if "word/document.xml" not in archive.namelist():
            raise ValueError("DOCX document missing")


def validate_cv_file(cv_bytes: bytes, cv_filename: str) -> None:
    _validate_upload(cv_bytes, cv_filename, allowed_ext=_ALLOWED_CV_EXT, label="CV")
    try:
        # Runda 6 audytu: format z bajtów — PDF nazwany `.docx` to PDF.
        kind = sniff_extension_bytes(cv_bytes) or Path(cv_filename).suffix.lower()
        if kind == ".docx":
            _docx_container(cv_bytes)
            if not extract_text_from_file(cv_bytes, cv_filename).strip():
                raise ValueError("Empty DOCX")
        else:
            import pdfplumber

            with pdfplumber.open(BytesIO(cv_bytes)) as pdf:
                if not any(page.chars or page.images for page in pdf.pages):
                    raise ValueError("Empty PDF")
    except Exception as error:
        raise StandaloneGenerationError(
            "invalid_input",
            "CV: nie można odczytać dokumentu lub plik jest pusty. Wgraj poprawny PDF/DOCX; PDF nie może być zabezpieczony hasłem.",
        ) from error


def validate_upload_inputs(payload: UploadGenerationInput) -> None:
    validate_cv_file(payload.cv_bytes, payload.cv_filename)
    champion = None
    if payload.champion_bytes is not None:
        filename = payload.champion_filename or ""
        _validate_upload(
            payload.champion_bytes,
            filename,
            allowed_ext=_ALLOWED_CHAMPION_EXT,
            label="Profil Championa",
        )
        # The reason goes to the recruiter as it is. Until 09.2026 every failure
        # here — including a (since removed) length limit — was reported as an
        # unreadable DOCX, so people re-exported healthy files instead of
        # fixing the actual problem.
        try:
            _docx_container(payload.champion_bytes)
        except DocxExpansionLimit as error:
            raise StandaloneGenerationError(
                "invalid_input",
                "Profil Championa: plik po rozpakowaniu przekracza dopuszczalny "
                "rozmiar. Usuń z dokumentu obrazy lub osadzone pliki.",
            ) from error
        except Exception as error:
            raise StandaloneGenerationError(
                "invalid_input", _CHAMPION_UNREADABLE
            ) from error
        try:
            champion = parse_champion_from_docx_bytes(payload.champion_bytes, filename)
        except CVTextExtractionError as error:
            raise StandaloneGenerationError(
                "invalid_input", f"Profil Championa: {error}"
            ) from error
        except Exception as error:
            raise StandaloneGenerationError(
                "invalid_input", _CHAMPION_UNREADABLE
            ) from error

    required = bool(payload.client_rule and payload.client_rule.require_champion)
    # Manual MUST/NICE fields only fed interactive-CV tiles; they are not a
    # Champion. A reviewed preview profile counts as one.
    has_profile = payload.champion_profile is not None
    if required and not has_profile and (champion is None or champion.is_empty()):
        raise StandaloneGenerationError(
            "invalid_input",
            "Ten klient wymaga Profilu Championa, ale nie rozpoznano jego treści. Wgraj poprawny profil.",
        )
