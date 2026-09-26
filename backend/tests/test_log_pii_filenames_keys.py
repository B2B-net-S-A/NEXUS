"""Nazwy plików CV, klucze magazynu i nazwiska kandydatów nie trafiają do logów
(runda 6 audytu, W3 i W6).

Klucz CV w magazynie ma kształt ``cv/RRRR/MM/<uuid>-<oryginalna_nazwa_pliku>``,
a nazwa pliku CV to zwykle „Jan_Kowalski_CV.pdf” — czyli imię i nazwisko.
Logi backendu idą do Loki/Coolify, więc log niesie wyłącznie część
identyfikującą obiekt (prefiks + uuid) albo rozszerzenie i długość nazwy.

Druga połowa pliku to strażnik źródeł: każde wywołanie ``logger.*`` w
``backend/app``, które przekazuje nazwę pliku, klucz magazynu albo nazwisko
wprost (bez ``safe_storage_key``/``safe_filename``), wywraca CI.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest

from app.core.log_safety import safe_filename, safe_storage_key

_APP = Path(__file__).resolve().parents[1] / "app"
_UUID = "0123456789abcdef0123456789abcdef"


def test_safe_storage_key_keeps_prefix_and_uuid_only():
    out = safe_storage_key(f"cv/2026/05/{_UUID}-Jan_Kowalski_CV.pdf")
    assert out.startswith(f"cv/2026/05/{_UUID}")
    assert "Kowalski" not in out
    assert "Jan" not in out


@pytest.mark.parametrize(
    "key",
    [
        "stage-cv/12/" + "a" * 64,  # sam skrót — bez nazwy pliku, zostaje
        "purged/77",
    ],
)
def test_safe_storage_key_keeps_keys_without_names(key):
    assert safe_storage_key(key) == key


def test_safe_storage_key_hashes_unknown_last_segment():
    out = safe_storage_key("legacy/Anna Nowak CV.docx")
    assert "Nowak" not in out
    assert out.startswith("legacy/")


def test_safe_storage_key_handles_empty():
    assert safe_storage_key(None) == "-"
    assert safe_storage_key("") == "-"


def test_safe_filename_reports_extension_and_length_only():
    out = safe_filename("Jan_Kowalski_CV.pdf")
    assert "Kowalski" not in out and "Jan" not in out
    assert ".pdf" in out
    assert safe_filename(None) == "-"


def test_upload_cv_log_has_no_file_name(monkeypatch, caplog):
    from app.services import object_storage

    class _Client:
        def put_object(self, **_kw):
            return {}

    monkeypatch.setattr(object_storage, "_client", lambda: _Client())
    monkeypatch.setattr(object_storage, "_bucket_name", lambda: "bucket")

    with caplog.at_level(logging.INFO, logger=object_storage.logger.name):
        key = object_storage.upload_cv(b"x", "Jan_Kowalski_CV.pdf")

    assert "Kowalski" in key  # sam klucz się nie zmienia — zmienia się log
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "Kowalski" not in logged
    assert "uploaded 1 bytes" in logged


def test_cv_text_backfill_download_failure_log_has_no_file_name(monkeypatch, caplog):
    from app.services import cv_text_backfill

    def boom(_key):
        raise RuntimeError("storage down")

    monkeypatch.setattr(cv_text_backfill, "download_cv", boom)
    with caplog.at_level(logging.WARNING, logger=cv_text_backfill.logger.name):
        res = cv_text_backfill.extract_one(
            f"cv/2026/05/{_UUID}-Anna_Nowak_CV.pdf", "Anna_Nowak_CV.pdf"
        )

    assert res.outcome == "download_failed"
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "Nowak" not in logged
    assert _UUID in logged


async def test_order_parser_unparsed_json_log_has_no_raw_model_output(
    monkeypatch, caplog
):
    """Surowy JSON modelu niesie nazwisko konsultanta i stawkę — log ma kształt."""
    from app.services import order_pdf_parser

    raw = '{"consultant_name": "Jan Kowalski", "rate_client": 1340'  # ucięty

    class _Block:
        text = raw

    class _Msg:
        content = [_Block()]
        stop_reason = "max_tokens"

    monkeypatch.setattr(order_pdf_parser, "call_claude", lambda *a, **k: _Msg())
    monkeypatch.setattr(order_pdf_parser, "api_key_configured", lambda _m: True)
    monkeypatch.setattr(order_pdf_parser.settings, "ORDER_EXTRACTION_ENABLED", True)

    with caplog.at_level(logging.WARNING, logger=order_pdf_parser.logger.name):
        result = await order_pdf_parser._call_extraction(
            "Zamówienie nr 1",
            consultant_name=None,
            consultant_given_names=None,
            all_rows=True,
        )

    assert result is None
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "JSON parse failed" in logged
    assert "Kowalski" not in logged
    assert "1340" not in logged


def test_storage_service_logs_have_no_file_name(monkeypatch, tmp_path, caplog):
    """R7-V5-2: magazyn dokumentów loguje ścieżkę `<8hex>-<oryginalna nazwa>`."""
    import io

    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(storage_service, "BRANDED_CVS_DIR", tmp_path / "branded_cvs")
    with caplog.at_level(logging.INFO, logger=storage_service.logger.name):
        rel, _size = storage_service.save_branded_cv(
            1, "CV_Jan_Kowalski_v1.html", io.BytesIO(b"x")
        )
        storage_service.delete_branded_cv(rel)
        storage_service.delete_branded_cv(rel)  # już usunięty — ostrzeżenie

    assert "Kowalski" in rel  # sama ścieżka się nie zmienia — zmienia się log
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "Saved branded CV" in logged and "Deleted branded CV" in logged
    assert "Kowalski" not in logged


# ── strażnik źródeł ─────────────────────────────────────────────────────────

# Nazwy argumentów niosących dane osoby albo nazwę pliku CV.
_SENSITIVE_NAMES = {
    "storage_key",
    "cv_storage_key",
    "filename",
    "file_name",
    "file_path",
    "old_filename",
    "candidate_name",
    "lastname",
    "full_name",
    "partner_name",
    "consultant_name",
    # Runda 7 (R7-V5-2): ścieżki magazynu dokumentów (`<8hex>-<oryginalna nazwa>`)
    # i nazwy załączników z maila zamówień.
    "rel",
    "relative_path",
    "storage_path",
    "final_path",
    "attachment_name",
    "key",
}
_SAFE_WRAPPERS = {"safe_storage_key", "safe_filename"}
# Świadome wyjątki: pliki Championa to opis roli („Profil_Championa_Java.docx”),
# nie dokument osoby.
_EXEMPT = {
    "services/champion_profile_ingest.py",
    "services/cv_generator_b2b/champion_builder.py",
}
# Świadome wyjątki dla pary (plik, nazwa): `key` w tych plikach to klucz
# rejestru klauzul klienta (firma, np. „cardif”), nie klucz magazynu ani osoba.
_EXEMPT_NAMES = {
    ("api/b2b_contract_generator.py", "key"),
    ("services/b2b_contract_generator/docx_renderer.py", "key"),
}
_LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}


def _leaf_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.BoolOp):  # `filename or file_path`
        for value in node.values:
            name = _leaf_name(value)
            if name in _SENSITIVE_NAMES:
                return name
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value in {"name", "lastname", "full_name"}
    ):
        return "person_name"
    return None


def _logged_values(call: ast.Call) -> list[ast.AST]:
    """Argumenty formatowania ORAZ wartości wstawione f-stringiem w komunikat.

    Runda 7 (R7-V5-2): do rundy 6 strażnik patrzył tylko na `args[1:]`, więc
    `logger.info(f"... {rel}")` przechodził bez sprawdzenia.
    """
    values: list[ast.AST] = list(call.args[1:])
    if call.args and isinstance(call.args[0], ast.JoinedStr):
        values.extend(
            part.value
            for part in call.args[0].values
            if isinstance(part, ast.FormattedValue)
        )
    return values


def test_no_logger_call_passes_file_names_keys_or_person_names_raw():
    offenders: list[str] = []
    for path in sorted(_APP.rglob("*.py")):
        rel = path.relative_to(_APP).as_posix()
        if rel in _EXEMPT:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _LOG_METHODS
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in {"logger", "log", "_logger"}
            ):
                continue
            for arg in _logged_values(node):
                name = _leaf_name(arg)
                if (rel, name) in _EXEMPT_NAMES:
                    continue
                if name in _SENSITIVE_NAMES or name == "person_name":
                    offenders.append(f"{rel}:{node.lineno} ({name})")
    assert not offenders, (
        "logger.* z nazwą pliku / kluczem magazynu / nazwiskiem wprost — owiń w "
        "safe_storage_key/safe_filename albo loguj ID:\n" + "\n".join(offenders)
    )
