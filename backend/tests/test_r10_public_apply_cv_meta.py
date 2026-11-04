"""Runda 10: publiczny formularz CV (R10-N10-6, R10-N10-7)."""

from __future__ import annotations

import asyncio
import io
import logging

from starlette.datastructures import Headers, UploadFile

from app.api import public_share
from app.services import public_apply


def _upload(filename: str, content_type: str) -> UploadFile:
    return UploadFile(
        io.BytesIO(b"x"),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


def test_cv_extraction_failure_does_not_log_the_cv_filename(
    tmp_path, monkeypatch, caplog
):
    """`.rtf` z MIME `application/msword` przechodzi walidację, a wyjątek
    ekstraktora niesie nazwę pliku (zwykle imię i nazwisko)."""
    monkeypatch.setattr(public_share.settings, "UPLOAD_DIR", str(tmp_path))
    upload = _upload("Anna_Nowak_CV.rtf", "application/msword")
    public_share._validate_cv_file(upload, b"{\\rtf1 test}")

    with caplog.at_level(logging.WARNING, logger=public_share.logger.name):
        asyncio.run(public_share._persist_cv(7, upload, b"{\\rtf1 test}"))

    assert caplog.records, "ekstrakcja .rtf powinna zostawić ostrzeżenie"
    assert all("Anna_Nowak" not in r.getMessage() for r in caplog.records)


def test_long_declared_content_type_is_normalized_before_the_database():
    upload = _upload("cv.pdf", "application/pdf" + "x" * 150)
    assert public_apply.cv_content_type(upload) == "application/pdf"


def test_whitelisted_content_type_with_parameters_is_kept():
    upload = _upload("cv.pdf", "Application/PDF; charset=binary")
    assert public_apply.cv_content_type(upload) == "application/pdf"


def test_unknown_content_type_falls_back_to_the_extension():
    assert (
        public_apply.cv_content_type(_upload("cv.docx", "x" * 300))
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert (
        public_apply.cv_content_type(_upload("cv.rtf", "x" * 300))
        == "application/octet-stream"
    )
    for upload in (_upload("cv.docx", "x" * 300), _upload("cv.rtf", "y" * 300)):
        assert len(public_apply.cv_content_type(upload)) <= 100


def test_duplicate_branch_filename_fits_the_column_and_drops_directories():
    long_name = "Ż" * 400 + ".pdf"
    name = public_apply.cv_display_filename(_upload(long_name, "application/pdf"))
    assert name.endswith(".pdf")
    assert len(name) <= 500
    assert len(name.encode("utf-8")) <= public_share._STORED_NAME_MAX_BYTES

    assert (
        public_apply.cv_display_filename(_upload("..\\..\\x\\cv.pdf", "a")) == "cv.pdf"
    )
    assert public_apply.cv_display_filename(_upload("", "a")) == "cv.pdf"
