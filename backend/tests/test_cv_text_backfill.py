"""Unit tests for the CV-text recovery service.

The pure classification/pipeline seams are tested here; the storage and OCR
calls are stubbed. What matters is that the run is *safe to repeat* — it must
never replace good text with worse, and it must not re-burn OCR on files that
already proved unreadable.
"""

from __future__ import annotations

import pytest

from app.services import cv_text_backfill as svc
from app.services.cv_text_backfill import (
    BackfillStats,
    ExtractionResult,
    _extension_of,
    _record_marker,
    _terminal_marker,
    extract_one,
    looks_like_junk,
    sanitize,
)
from app.models.candidate import Candidate


def _candidate(**kw) -> Candidate:
    return Candidate(
        id=kw.get("id", 1),
        name="Jan",
        lastname="Kowalski",
        cv_extracted_data=kw.get("cv_extracted_data", {}),
        raw_cv_text=kw.get("raw_cv_text"),
        cv_storage_key=kw.get("cv_storage_key", "cv/1.pdf"),
    )


# ── Classification ──────────────────────────────────────────────────────────


def test_junk_detects_cid_glyph_fallback():
    """pdfplumber emits these for fonts without a Unicode CMap."""
    assert looks_like_junk("(cid:42)(cid:7)(cid:15)" * 40)
    assert not looks_like_junk("Prawdziwe CV z treścią. " * 20)


def test_junk_ignores_short_strings():
    assert not looks_like_junk("(cid:1)")


def test_sanitize_strips_bytes_postgres_rejects():
    assert sanitize("a\x00b\x07c") == "abc"
    assert sanitize("keep\ttabs\nand\nnewlines") == "keep\ttabs\nand\nnewlines"


@pytest.mark.parametrize(
    "filename,key,expected",
    [
        ("cv.docx", "cv/2026/01/x", ".docx"),
        (None, "cv/2026/01/x.pdf", ".pdf"),
        ("stary.doc", "cv/2026/01/x", ".doc"),
        ("bez-rozszerzenia", "tez-bez", ".pdf"),
    ],
)
def test_extension_resolution(filename, key, expected):
    assert _extension_of(filename, key) == expected


_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64
_PDF = b"%PDF-1.4\n%fake"


def test_legacy_doc_is_recognised_by_its_bytes(monkeypatch):
    """The image ships neither libreoffice nor antiword, so real OLE2 Word
    always fails — classified as `legacy_doc` from the BYTES, not the name."""
    monkeypatch.setattr(svc, "download_cv", lambda key: _OLE)

    assert extract_one("cv/2026/01/abc", "stary.doc").outcome == "legacy_doc"
    # A `.docx` name does not rescue binary Word either.
    assert extract_one("cv/2026/01/abc", "cv.docx").outcome == "legacy_doc"


def test_pdf_named_docx_is_read_as_pdf(monkeypatch):
    """Measured on prod 2026-09-22: 3 320 Traffit CVs named `*.docx` are PDFs.

    By name they went to python-docx, failed and got a terminal `empty`.
    """
    from app.services import cv_text_extractor as cte

    monkeypatch.setattr(svc, "download_cv", lambda key: _PDF)
    monkeypatch.setattr(cte, "_extract_pdf", lambda _p: "Senior QA Engineer, Selenium")
    monkeypatch.setattr(
        cte, "_extract_docx", lambda _p: pytest.fail("PDF bytes sent to python-docx")
    )

    result = extract_one("cv/2026/01/abc", "Tester_Jan Kowalski.docx")

    assert result.outcome == "extracted"
    assert "Senior QA Engineer" in result.text


def test_pre_sniff_empty_marker_gets_exactly_one_more_attempt():
    stale = _candidate(
        cv_extracted_data={"_cv_text_extraction": {"outcome": "empty", "chars": 0}}
    )
    assert _terminal_marker(stale) is None, "recorded before format sniffing"

    fresh = _candidate(cv_extracted_data={})
    _record_marker(fresh, "empty", 0)
    assert _terminal_marker(fresh) == "empty", "the new marker is final again"

    junk = _candidate(
        cv_extracted_data={"_cv_text_extraction": {"outcome": "junk", "chars": 0}}
    )
    assert _terminal_marker(junk) == "junk", "junk did not depend on the name"


def test_pre_sniff_markers_are_reopened_in_sql():
    from sqlalchemy.dialects import postgresql

    sql = str(
        svc._pending_candidates_stmt(10).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "sniffed" in sql


def test_download_failure_is_retryable_not_terminal(monkeypatch):
    def _boom(_key):
        raise RuntimeError("S3 timeout")

    monkeypatch.setattr(svc, "download_cv", _boom)

    result = extract_one("cv/2026/01/abc", "cv.pdf")

    assert result.outcome == "download_failed"
    assert result.outcome not in svc._TERMINAL_OUTCOMES, (
        "a transient storage error must not permanently exclude the candidate"
    )


# ── Attempt marker ──────────────────────────────────────────────────────────


def test_terminal_marker_skips_only_hopeless_outcomes():
    hopeless = _candidate(cv_extracted_data={})
    _record_marker(hopeless, "legacy_doc", 0)
    assert _terminal_marker(hopeless) == "legacy_doc"

    retryable = _candidate(cv_extracted_data={})
    _record_marker(retryable, "download_failed", 0)
    assert _terminal_marker(retryable) is None, (
        "a retryable outcome must not be treated as final"
    )


def test_marker_preserves_other_extracted_data():
    c = _candidate(
        cv_extracted_data={"traffit_Position": "Dev", "_manual_override_city": True}
    )

    _record_marker(c, "extracted", 4200)

    assert c.cv_extracted_data["traffit_Position"] == "Dev"
    assert c.cv_extracted_data["_manual_override_city"] is True
    assert c.cv_extracted_data["_cv_text_extraction"]["chars"] == 4200


# ── Stats shape ─────────────────────────────────────────────────────────────


def test_stats_report_a_taxonomy_not_a_single_rate():
    """ "77,5% extracted" cannot tell you whether the rest is fixable."""
    stats = BackfillStats()
    stats.legacy_doc = 3
    stats.junk = 2
    stats.candidate_ids_written = [7, 9]

    payload = stats.as_dict()

    assert payload["written"] == 2
    for bucket in ("legacy_doc", "junk", "empty", "download_failed", "error"):
        assert bucket in payload


def test_extraction_result_defaults_to_empty_text():
    assert ExtractionResult("junk").text == ""


def test_random_sample_changes_ordering_not_scope():
    """`--limit` over id order misrepresents the backlog; this is the escape hatch.

    Measured 2026-08-10: the first 30 rows by id yielded 6.7% extracted and 50%
    legacy `.doc`; a 200-row random sample of the same backlog yielded 75% and
    0.5% `.doc`. The id-ordered read would have argued for putting LibreOffice in
    the image to rescue 133 people.
    """
    by_id = str(svc._pending_candidates_stmt(30))
    random_ = str(svc._pending_candidates_stmt(30, random_sample=True))

    # Runda 6 audytu: najpierw wiersze bez znacznika, potem po id.
    assert "candidates.id ASC" in by_id
    assert "random()" in random_
    # Same population either way — only the draw order differs.
    for clause in ("cv_storage_key IS NOT NULL", "LIMIT"):
        assert clause in by_id and clause in random_


def test_no_improvement_is_terminal_and_separately_counted():
    """Two distinct failures the first cut of this module conflated.

    (a) It incremented `stats.empty` for "file had text, ours was worse" — the
        exact conflation the taxonomy exists to prevent, and it would have made
        the reported `empty=48` unreadable.
    (b) It wrote a `no_improvement` marker that `_terminal_marker` did not
        recognise, so those rows re-entered the scope on every run and burned an
        S3 GET plus OCR each time, forever.
    """
    assert "no_improvement" in svc._TERMINAL_OUTCOMES

    c = _candidate(cv_extracted_data={})
    _record_marker(c, "no_improvement", 150)
    assert _terminal_marker(c) == "no_improvement"

    assert "no_improvement" in BackfillStats().as_dict()
    assert BackfillStats().no_improvement == 0


def test_unconfigured_storage_is_distinguishable_from_nothing_to_do():
    """`scanned == 0` is also what a finished backlog looks like."""
    assert BackfillStats().storage_available is True
    broken = BackfillStats()
    broken.storage_available = False
    assert broken.as_dict()["storage_available"] is False


def test_terminal_rows_are_excluded_in_sql_not_just_in_the_loop():
    """Skipping in Python left the tranche re-reading its own failures forever.

    A row that can never yield text still matches the predicate, so
    `ORDER BY id LIMIT N` kept handing back the same failures and each successive
    tranche spent more of its budget re-fetching them. Measured on the first
    production run: 2 494 of 2 500 rows scanned were already-marked skips — the
    tranche did about 0.2% useful work.
    """
    # Compile with literal binds: the marker key travels as a bound parameter,
    # so a plain str() of the statement shows `:param_1` and would pass this
    # assertion even with the filter removed.
    sql = str(
        svc._pending_candidates_stmt(3000).compile(
            compile_kwargs={"literal_binds": True}
        )
    )
    assert "_cv_text_extraction" in sql, (
        "scope no longer filters on the extraction marker — tranches will stall "
        "on rows that can never succeed"
    )
    assert "legacy_doc" in sql, "terminal outcomes are not part of the predicate"
    # The retryable outcomes must NOT be excluded, or a transient S3 blip would
    # permanently drop the candidate.
    for retryable in ("download_failed", "error"):
        assert retryable not in svc._TERMINAL_OUTCOMES


def test_retry_outcomes_reopens_only_the_named_terminal_classes():
    """Wybrane klasy terminalne wracają do scope'u; reszta zostaje wykluczona.

    Pomiar 2026-08-14: losowy pilotaż wierszy `empty` odzyskał 37,5% CV —
    klasa przestała być terminalna po bumpach ekstraktorów, ale znaczniki
    z 10.08 trwale blokowały ponowną próbę. Bez tego mechanizmu jedyną drogą
    byłoby ręczne kasowanie znaczników w SQL.
    """

    from sqlalchemy.dialects import postgresql

    from app.services.cv_text_backfill import _pending_candidates_stmt

    def _sql(**kwargs) -> str:
        return str(
            _pending_candidates_stmt(None, **kwargs).compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )

    default_sql = _sql()
    assert "'empty'" in default_sql, "domyślnie empty jest wykluczone"
    assert "'legacy_doc'" in default_sql

    retry_sql = _sql(retry_outcomes=frozenset({"empty", "junk"}))
    assert "'empty'" not in retry_sql, "retry zdejmuje empty z listy wykluczeń"
    assert "'junk'" not in retry_sql
    assert "'legacy_doc'" in retry_sql, "niewymienione klasy zostają wykluczone"


def test_retry_outcomes_open_the_loop_guard_not_just_sql():
    """Test PĘTLI, nie kompilacji SQL — łapie no-op z review #1156.

    Pierwsza wersja flagi otwierała tylko predykat SQL; `_terminal_marker`
    w pętli sprawdzał pełny zbiór terminalny i wyrzucał każdy wpuszczony
    wiersz jako `skipped_terminal`. Bieg wyglądał jak „nie ma nic do
    zrobienia" — zero ekstrakcji, zero błędów, zielony exit code. Oba
    strażniki (SQL + pętla) MUSZĄ dostawać ten sam `retry_outcomes`.
    """

    from types import SimpleNamespace

    from app.services import cv_text_backfill as svc

    candidate = SimpleNamespace(
        cv_extracted_data={
            # `sniffed`: znacznik po rozpoznawaniu formatu po bajtach — bez
            # flagi `empty` dostaje jedną ponowną próbę niezależnie od retry.
            svc._EXTRACTION_MARKER_KEY: {
                "outcome": "empty",
                "chars": 0,
                "sniffed": True,
            }
        },
    )

    assert svc._terminal_marker(candidate) == "empty", (
        "bez retry wiersz jest terminalny"
    )
    assert (
        svc._terminal_marker(candidate, retry_outcomes=frozenset({"empty"})) is None
    ), "retry zdejmuje terminalność TAKŻE w pętli, nie tylko w SQL"
    assert (
        svc._terminal_marker(candidate, retry_outcomes=frozenset({"junk"})) == "empty"
    ), "retry innej klasy nie otwiera tej"

    import inspect

    loop_src = inspect.getsource(svc.run_backfill)
    assert "_terminal_marker(candidate, retry_outcomes=retry_outcomes)" in loop_src, (
        "pętla run_backfill musi przekazywać retry_outcomes do strażnika — "
        "inaczej SQL wpuszcza wiersze, a pętla je po cichu wyrzuca"
    )


# ── Runda 6 audytu (T6-4): przejściowe wyniki nie blokują kolejki ───────────


def _sql(stmt) -> str:
    from sqlalchemy.dialects import postgresql

    return str(
        stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )


@pytest.mark.parametrize("outcome", ["download_failed", "no_file", "error"])
def test_transient_outcome_is_deferred_with_growing_backoff(outcome):
    """Do 26.09.2026 `download_failed`/`no_file`/`error` wracały co noc na
    czoło `ORDER BY id LIMIT 1000`, a nowe CV nie mieściły się w budżecie."""
    from datetime import datetime, timezone

    c = _candidate(cv_extracted_data={})
    _record_marker(c, outcome, 0)
    first = c.cv_extracted_data["_cv_text_extraction"]
    assert first["attempts"] == 1
    assert first["storage_key"] == "cv/1.pdf"
    after_1 = datetime.fromisoformat(first["retry_after"])
    assert after_1 > datetime.now(timezone.utc)

    _record_marker(c, outcome, 0)
    second = c.cv_extracted_data["_cv_text_extraction"]
    assert second["attempts"] == 2
    assert datetime.fromisoformat(second["retry_after"]) > after_1
    # Nadal nieterminalny — po odroczeniu dostaje kolejną próbę.
    assert _terminal_marker(c) is None


def test_attempts_restart_for_a_new_cv_file():
    c = _candidate(cv_extracted_data={})
    _record_marker(c, "download_failed", 0)
    _record_marker(c, "download_failed", 0)
    c.cv_storage_key = "cv/2.pdf"
    _record_marker(c, "download_failed", 0)
    assert c.cv_extracted_data["_cv_text_extraction"]["attempts"] == 1


def test_pending_scope_respects_deferral_and_puts_new_cvs_first():
    sql = _sql(svc._pending_candidates_stmt(1000))
    assert "retry_after" in sql, "odroczenie ponowień nie jest częścią zakresu"
    order_by = sql.split("ORDER BY", 1)[1]
    # Wiersze bez znacznika (nowe CV) przed ponowieniami.
    assert "IS NOT NULL" in order_by
    assert order_by.index("IS NOT NULL") < order_by.index("candidates.id")


def test_glued_scope_respects_deferral():
    assert "retry_after" in _sql(svc._glued_candidates_stmt(1000))


def test_terminal_verdict_does_not_stick_to_a_replaced_file():
    c = _candidate(cv_extracted_data={})
    _record_marker(c, "empty", 0)
    assert _terminal_marker(c) == "empty"
    c.cv_storage_key = "cv/nowy.pdf"
    assert _terminal_marker(c) is None, "nowy plik nie dziedziczy wyroku starego"
    assert "storage_key" in _sql(svc._pending_candidates_stmt(10))


def test_cv_text_phase_stats_survive_the_watermark_summary():
    """`_CvTextPhaseResult.as_dict` miało klucze, których `_summarize` nie
    przepuszczał — faza wyglądała w `/sync/status` jak pusta."""
    from datetime import datetime, timezone

    from app.tasks.traffit_sync import _CvTextPhaseResult, _summarize

    stats = BackfillStats()
    stats.scanned = 10
    stats.extracted = 4
    stats.download_failed = 2
    summary = stats.as_dict()
    summary["glued"] = BackfillStats().as_dict()
    now = datetime.now(timezone.utc)
    out = _summarize(_CvTextPhaseResult(summary, now, now).as_dict())
    assert out["scanned"] == 10
    assert out["extracted"] == 4
    assert out["download_failed"] == 2
    assert out["written"] == 0
    assert "glued" in out
