"""Runda 9 (FILES) — testy bez bazy: nazwy plików i strażnik archiwów XLSX."""

from __future__ import annotations

import io
import os
import zipfile

import pytest

_LONG_PL = "Curriculum_Vitae_" + "Żółćgęśląjaźń_" * 20 + "Kowalski.pdf"


def test_long_polish_cv_name_fits_the_disk_name_limit(tmp_path):
    """R9-N7-3: `candidate_<id>_<nazwa>` z ~250 polskimi znakami = ENAMETOOLONG."""
    from app.api.candidates import _sanitize_upload_filename

    name = _sanitize_upload_filename(_LONG_PL, fallback="upload.pdf")
    assert name.endswith(".pdf")
    assert len(name.encode("utf-8")) <= 180
    path = tmp_path / f"candidate_1234567_{name}"
    path.write_bytes(b"%PDF-1.4")  # przed poprawką: OSError [Errno 63/36]
    assert path.read_bytes() == b"%PDF-1.4"
    assert _sanitize_upload_filename("../../x/cv.pdf", fallback="u.pdf") == "cv.pdf"
    assert _sanitize_upload_filename("", fallback="u.pdf") == "u.pdf"


def test_filename_column_fit_keeps_the_extension():
    """R9-N7-4: kolumny `filename` mają 255 znaków."""
    from app.core.upload_filename import fit_filename_column

    fitted = fit_filename_column("a" * 400 + ".pdf")
    assert len(fitted) == 255 and fitted.endswith(".pdf")
    assert fit_filename_column("krótki.pdf") == "krótki.pdf"
    assert len(fit_filename_column("x" * 300)) == 255


def test_group_pdf_copy_on_contract_is_a_pdf_file_name():
    """R9-N7-10: kopia na kontrakcie miała nazwę `OIT/0189/2026` bez `.pdf`."""
    from app.api.client_order_groups import _order_copy_filename

    assert _order_copy_filename("OIT/0189/2026/ITVM") == "OIT_0189_2026_ITVM.pdf"
    assert _order_copy_filename("445") == "445.pdf"


def _xlsx_bomb() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        # 11 MB XML w kilkunastu kilobajtach — ponad limit części XML.
        zf.writestr("xl/sharedStrings.xml", " " * (11 * 1024 * 1024))
    return buf.getvalue()


def test_finance_workbook_bomb_is_rejected_before_openpyxl(monkeypatch):
    """R9-N7-13: arkusz Finansów bez strażnika „bomby ZIP”."""
    import openpyxl

    from app.services.finance_import import FinanceWorkbookError, parse_finance_workbook

    calls: list[bool] = []
    monkeypatch.setattr(openpyxl, "load_workbook", lambda *a, **k: calls.append(True))
    with pytest.raises(FinanceWorkbookError):
        parse_finance_workbook(_xlsx_bomb())
    assert calls == [], "openpyxl dostał archiwum, które rozwija się ponad limit"


def test_md_sheet_bomb_is_rejected_before_openpyxl(monkeypatch):
    from app.services import md_import_parser

    calls: list[bool] = []
    monkeypatch.setattr(
        md_import_parser, "load_workbook", lambda *a, **k: calls.append(True)
    )
    with pytest.raises(md_import_parser.MdSheetFormatError):
        md_import_parser.parse_md_sheet(_xlsx_bomb())
    assert calls == [], "openpyxl dostał archiwum, które rozwija się ponad limit"


def test_storage_log_lines_carry_no_exception_message():
    """R9-N7-8: komunikat wyjątku magazynu (URL z kluczem = nazwisko) nie idzie
    do logu ani do komunikatu dla użytkownika."""
    backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def src(rel: str) -> str:
        with open(os.path.join(backend, rel), encoding="utf-8") as fh:
            return fh.read()

    cv_source = src("app/services/cv_source.py")
    assert "logger.exception" not in cv_source
    standalone = src("app/services/cv_generator_b2b/standalone_service.py")
    assert "Object Storage: {err}" not in standalone
    assert '"[submission] CV fetch failed submission=%s: %s", submission.id, e' not in src(
        "app/api/application_submissions.py"
    )
    assert '"[apply] inert CV object-store upload failed: %s", e)' not in src(
        "app/api/public_share.py"
    )
