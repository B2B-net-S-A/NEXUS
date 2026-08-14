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


def test_legacy_doc_is_skipped_before_download(monkeypatch):
    """The image ships neither libreoffice nor antiword, so `.doc` always fails.

    Classifying it up front saves thousands of pointless S3 GETs — and, more
    usefully, turns "77% success" into a number that says whether the remainder
    is fixable.
    """
    called = []
    monkeypatch.setattr(svc, "download_cv", lambda key: called.append(key) or b"x")

    result = extract_one("cv/2026/01/abc", "stary.doc")

    assert result.outcome == "legacy_doc"
    assert called == [], "must not download a file we cannot read"


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

    assert "ORDER BY candidates.id" in by_id
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
            svc._EXTRACTION_MARKER_KEY: {"outcome": "empty", "chars": 0}
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
