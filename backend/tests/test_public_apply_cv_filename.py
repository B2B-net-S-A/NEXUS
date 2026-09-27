"""R8-N4-8: długa nazwa pliku CV nie wywraca zgłoszenia (ENAMETOOLONG → 500)."""

from __future__ import annotations

import io

import pytest
from starlette.datastructures import Headers, UploadFile

from app.api import public_share


def test_fit_filename_keeps_extension_and_byte_limit():
    long_name = "ą" * 130 + ".pdf"  # 264 bajty
    fitted = public_share._fit_filename(long_name)
    assert fitted.endswith(".pdf")
    assert len(fitted.encode("utf-8")) <= 180
    assert public_share._fit_filename("cv.pdf") == "cv.pdf"


@pytest.mark.asyncio
async def test_persist_cv_accepts_a_very_long_polish_name(tmp_path, monkeypatch):
    monkeypatch.setattr(public_share.settings, "UPLOAD_DIR", str(tmp_path))
    upload = UploadFile(
        io.BytesIO(b"%PDF-1.4"),
        filename="ą" * 130 + ".pdf",
        headers=Headers({"content-type": "application/pdf"}),
    )
    stored, _text = await public_share._persist_cv(7, upload, b"%PDF-1.4")
    assert stored.endswith(".pdf")
    assert (tmp_path / f"candidate_7_{stored}").exists()
