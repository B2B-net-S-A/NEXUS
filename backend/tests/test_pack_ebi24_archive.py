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


# ── Przyrost przed wyłączeniem eBI24 (procedura: docs/claude/finanse-insights/
# archiwum-ebi24-przyrost-i-kopia.md) ────────────────────────────────────────

OLD = "a" * 24
NEW = "b" * 24
NEW_NO_FILE = "c" * 24


def _export(tmp_path, with_files: tuple[str, ...]):
    import json

    root = tmp_path / "eksport"
    (root / "archiwum" / "dokumenty" / "2026").mkdir(parents=True)
    rows = [
        {"_id": source_id, "_bucketNumber": number, "_schemaName": "COST_INVOICE"}
        for number, source_id in enumerate((OLD, NEW, NEW_NO_FILE), start=1)
    ]
    (root / "archiwum" / "metadane-000000.json").write_text(json.dumps(rows))
    for number, source_id in enumerate((OLD, NEW, NEW_NO_FILE), start=1):
        if source_id in with_files:
            path = (
                root
                / "archiwum"
                / "dokumenty"
                / "2026"
                / f"{number:06d}-{source_id}.pdf"
            )
            path.write_bytes(b"%PDF-" + source_id.encode())
    known = tmp_path / "w-nexusie.txt"
    known.write_text(f"source_id\n{OLD}\n")
    return root, known


def test_new_ids_skip_documents_already_in_nexus(tmp_path) -> None:
    root, known = _export(tmp_path, with_files=())

    assert pack.new_ids(root, pack.read_known(known)) == [NEW, NEW_NO_FILE]


def test_increment_packs_only_new_documents_and_counts_missing(
    tmp_path, capsys
) -> None:
    import json
    import zipfile

    root, known = _export(tmp_path, with_files=(OLD, NEW))

    packages = pack.pack(root, tmp_path / "paczki", 25, known=pack.read_known(known))

    assert len(packages) == 1
    with zipfile.ZipFile(packages[0]) as archive_zip:
        rows = json.loads(archive_zip.read("metadane.json"))
        names = archive_zip.namelist()
    assert [row["_id"] for row in rows] == [NEW]
    assert f"pliki/{NEW}.pdf" in names and f"pliki/{OLD}.pdf" not in names
    out = capsys.readouterr().out
    assert "już w NEXUSIE: 1" in out
    assert "bez pliku: 1" in out


def test_read_known_rejects_file_without_ids(tmp_path) -> None:
    import pytest

    empty = tmp_path / "pusty.txt"
    empty.write_text("source_id\n")

    with pytest.raises(SystemExit):
        pack.read_known(empty)
