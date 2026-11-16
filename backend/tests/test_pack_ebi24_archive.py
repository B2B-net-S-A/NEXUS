"""Paczki archiwum eBI24 mieszczą się w limicie ciała żądania (bez bazy).

16.11.2026 paczki z domyślnym ``--max-mb 60`` dostawały 413 od
``BodySizeLimitMiddleware`` (``MAX_REQUEST_BODY_MB`` = 30), zanim import
cokolwiek przeczytał.
"""

from __future__ import annotations

from app.core.config import settings
from app.services.finance_ledger import archive
from scripts import pack_ebi24_archive as pack

MB = 1024 * 1024


def test_default_package_fits_request_body_limit() -> None:
    # Margines na nagłówki multipart i metadane.json (ok. 1 MB na 4 000 wierszy).
    assert (pack.DEFAULT_MAX_MB + 3) * MB <= settings.MAX_REQUEST_BODY_MB * MB


def test_default_package_fits_import_limits() -> None:
    assert pack.DEFAULT_MAX_MB * MB < archive.MAX_PACKAGE_BYTES
    assert pack.DEFAULT_MAX_FILES < archive.MAX_ENTRIES
