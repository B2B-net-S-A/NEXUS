"""Niezależna kontrola AI treści CV (0326) — recenzent i kontrakt doradczy.

Dwie rzeczy, których pilnuje ten plik i których nie pilnuje nic innego:

1. **Recenzentem jest INNY model niż generator.** To cała funkcja: badanie
   z 16.09.2026 zmierzyło, że sędzia LLM faworyzuje własne wyjście, więc CV
   sprawdzane modelem, który je napisał, jest sprawdzane za łagodnie. Gdyby
   ktoś „uprościł" wywołanie do domyślnego modelu generatora, wszystko dalej
   działałoby i nikt by nie zauważył — poza tym, że kontrola przestałaby coś
   znaczyć.
2. **Recenzja nigdy nie zabiera dokumentu.** Trzy awarie generatora w dwa dni
   (09–10.09.2026) miały jeden mechanizm: wywołanie modelu jako WARUNEK
   ścieżki, która wcześniej działała deterministycznie.
"""

import json
import time

import pytest

from app.models.ai_feature import AIFeatureKey
from app.services.ai_models import model_for
from app.services.cv_generator_b2b import factual_verification, final_review
from app.services.cv_generator_b2b import standalone_service as svc
from app.services.cv_generator_b2b.legacy_v7 import pipeline as legacy
from app.services.cv_generator_b2b.provider import (
    CVGeneratorAIError,
    CVGeneratorOverloadedError,
)


_CV_TEXT = (
    "Jan Kowalski\n"
    "Backend Developer\n"
    "01.2015 – 07.2019, Acme Sp. z o.o., Backend Developer\n"
    "Utrzymanie API w Pythonie. Technologie: Python, PostgreSQL.\n"
)


def _ai_json():
    return {
        "name": "Jan Kowalski",
        "first_name": "Jan",
        "position": "Backend Developer",
        "why_points": ["Backend Developer z doświadczeniem w Pythonie"],
        "education": [],
        "skills": [{"label": "Backend", "content": "Python, PostgreSQL"}],
        "certifications": [],
        "languages": [],
        "experience": [
            {
                "dates": "01.2015 – 07.2019",
                "company": "Acme Sp. z o.o.",
                "position": "Backend Developer",
                "responsibilities": ["Utrzymanie API w Pythonie"],
                "technologies": ["Python", "PostgreSQL"],
            }
        ],
    }


@pytest.fixture
def review_on(monkeypatch):
    """Produkcyjne domyślne: legacy + kontrola włączona, bez egzekwowania."""

    monkeypatch.delenv("CV_GENERATION_PIPELINE", raising=False)
    monkeypatch.delenv("CV_SOURCE_EVIDENCE_ENFORCED", raising=False)
    monkeypatch.setenv("CV_FINAL_REVIEW_ENABLED", "true")
    monkeypatch.delenv("CV_FACTUAL_VERIFICATION_MODEL", raising=False)

    seen = {"reviews": []}

    monkeypatch.setattr(legacy, "extract_text_from_file", lambda *a, **k: _CV_TEXT)
    monkeypatch.setattr(
        legacy, "analyze_with_ai", lambda *a, **k: json.dumps(_ai_json())
    )
    monkeypatch.setattr(legacy, "render_cv_to_bytes", lambda *a, **k: b"DOCX")
    return seen


def _verifier(monkeypatch, seen, responder):
    def analyze(user_content, request_id, **kwargs):
        seen["reviews"].append({"request_id": request_id, **kwargs})
        return responder(json.loads(user_content))

    monkeypatch.setattr(factual_verification, "analyze_with_ai", analyze)


def _all_supported(payload):
    return json.dumps(
        {
            "claims": [
                {
                    "path": path,
                    "status": "supported",
                    "evidence": [{"source": "cv", "start_line": 1, "end_line": 4}],
                }
                for path in payload["claims"]
            ]
        }
    )


def _reject(*paths, status="unsupported"):
    def responder(payload):
        return json.dumps(
            {
                "claims": [
                    {
                        "path": path,
                        "status": status if path in paths else "supported",
                        "evidence": []
                        if path in paths
                        else [{"source": "cv", "start_line": 1, "end_line": 4}],
                    }
                    for path in payload["claims"]
                ]
            }
        )

    return responder


def _run():
    return svc._run_generation_pipeline(
        cv_bytes=b"cv",
        cv_filename="cv.pdf",
        champion_dto=None,
        screening_notes_text="Kandydat potwierdził znajomość Pythona.",
        language="pl",
        blind_cv=False,
        request_id="review-test",
        fallback_name="Jan Kowalski",
        started_at=time.time(),
        job_id=1,
        job_title="Backend Developer",
        content_mode="polished",
        client_rule=None,
    )


def test_the_reviewer_is_a_different_model_than_the_generator(review_on, monkeypatch):
    """Sędzia ≠ zawodnik — inaczej cała funkcja nic nie mierzy."""
    _verifier(monkeypatch, review_on, _all_supported)

    _run()

    assert review_on["reviews"], "recenzja w ogóle nie pobiegła"
    for call in review_on["reviews"]:
        assert call["model_override"] == "gpt-5.6-luna"
        assert call["model_override"] != model_for(AIFeatureKey.cv_generator)
        # Przeciążenie u OpenAI nie może zdejmować funkcji, ale fallback musi
        # iść na Sonneta, a nie na fallback generatora (Opus).
        assert list(call["fallback_models"]) == ["claude-sonnet-5"]


def test_the_model_override_is_honoured(review_on, monkeypatch):
    monkeypatch.setenv("CV_FACTUAL_VERIFICATION_MODEL", "deepseek-v4-pro")
    _verifier(monkeypatch, review_on, _all_supported)

    _run()

    assert review_on["reviews"][0]["model_override"] == "deepseek-v4-pro"


def test_a_clean_review_is_stored_and_says_nothing_to_the_recruiter(
    review_on, monkeypatch
):
    _verifier(monkeypatch, review_on, _all_supported)

    result = _run()

    report = result.render_payload["factual_verification"]
    assert report["status"] == "verified"
    assert report["model"] == "gpt-5.6-luna"
    assert not [w for w in result.warnings if "kontrola AI" in w]


def test_findings_reach_the_recruiter_as_warnings_and_never_block(
    review_on, monkeypatch
):
    _verifier(monkeypatch, review_on, _reject("/why_points/0"))

    result = _run()

    report = result.render_payload["factual_verification"]
    assert report["status"] == "advisory"
    assert report["paths"] == ["/why_points/0"]
    assert report["statuses"] == {"/why_points/0": "unsupported"}
    # Dokument POWSTAJE — to jest kontrakt tej funkcji.
    assert result.docx_bytes == b"DOCX"
    warning = next(w for w in result.warnings if w.startswith("BRAK POKRYCIA"))
    assert "podsumowanie" in warning
    assert "brak potwierdzenia" in warning


def test_a_contradiction_reads_differently_than_missing_evidence(
    review_on, monkeypatch
):
    _verifier(
        monkeypatch, review_on, _reject("/experience/0/company", status="contradicted")
    )

    result = _run()

    warning = next(w for w in result.warnings if w.startswith("BRAK POKRYCIA"))
    assert "sprzeczne ze źródłem" in warning
    assert "doświadczenie" in warning


def test_private_notes_are_flagged_softly_not_as_fabrication(review_on, monkeypatch):
    _verifier(monkeypatch, review_on, _reject("/why_points/0", status="private"))

    result = _run()

    warning = next(w for w in result.warnings if w.startswith("WERYFIKUJ"))
    assert "notatek prywatnych" in warning


@pytest.mark.parametrize(
    "boom",
    [
        CVGeneratorOverloadedError("przeciążenie"),
        CVGeneratorAIError("brak klucza"),
        ValueError("defekt recenzenta"),
    ],
)
def test_a_broken_reviewer_cannot_withhold_a_paid_for_cv(review_on, monkeypatch, boom):
    def explode(*args, **kwargs):
        raise boom

    monkeypatch.setattr(factual_verification, "analyze_with_ai", explode)

    result = _run()

    assert result.docx_bytes == b"DOCX"
    report = result.render_payload["factual_verification"]
    assert report["status"] == "unavailable"
    assert len([w for w in result.warnings if w.startswith("WERYFIKUJ")]) == 1


def test_the_flag_off_means_no_call_and_no_report(review_on, monkeypatch):
    monkeypatch.setenv("CV_FINAL_REVIEW_ENABLED", "false")

    def forbidden(*args, **kwargs):
        raise AssertionError("kontrola miała nie biec przy zgaszonej fladze")

    monkeypatch.setattr(factual_verification, "analyze_with_ai", forbidden)

    result = _run()

    assert "factual_verification" not in result.render_payload


def test_findings_from_every_batch_are_reported_not_just_the_first(monkeypatch):
    """Raport doradczy urwany na pierwszej paczce milczy o reszcie CV."""
    calls = {"n": 0}

    def analyze(user_content, request_id, **kwargs):
        calls["n"] += 1
        payload = json.loads(user_content)
        first = next(iter(payload["claims"]))
        return json.dumps(
            {
                "claims": [
                    {
                        "path": path,
                        "status": "unsupported" if path == first else "supported",
                        "evidence": []
                        if path == first
                        else [{"source": "cv", "start_line": 1, "end_line": 1}],
                    }
                    for path in payload["claims"]
                ]
            }
        )

    monkeypatch.setattr(factual_verification, "analyze_with_ai", analyze)
    document = {"why_points": [f"Twierdzenie numer {i}" for i in range(45)]}

    with pytest.raises(factual_verification.FactualVerificationError) as err:
        factual_verification.verify_final_cv(
            document,
            cv_text="źródło\n",
            screening_notes="",
            identity="Jan Kowalski",
            request_id="batches",
        )

    assert calls["n"] == 2, "45 twierdzeń to dwie paczki po 40"
    assert len(err.value.paths) == 2, "po jednym odrzuceniu z KAŻDEJ paczki"


def test_protocol_failures_still_abort_immediately(monkeypatch):
    """Niepoprawnej odpowiedzi nie da się częściowo zaufać."""

    monkeypatch.setattr(
        factual_verification, "analyze_with_ai", lambda *a, **k: "to nie jest JSON"
    )

    with pytest.raises(factual_verification.FactualVerificationError) as err:
        factual_verification.verify_final_cv(
            {"why_points": ["cokolwiek"]},
            cv_text="źródło\n",
            screening_notes="",
            identity="",
            request_id="protocol",
        )

    assert err.value.reason == "invalid_json"


def test_summary_hides_quotes_and_says_nothing_about_rows_from_before(review_on):
    verified = final_review.summarize_review(
        {"status": "verified", "model": "gpt-5.6-luna", "claims": [{"path": "/name"}]}
    )
    assert verified == {
        "status": "verified",
        "findings": 0,
        "model": "gpt-5.6-luna",
        "reason": None,
    }

    advisory = final_review.summarize_review(
        {"status": "advisory", "paths": ["/a", "/b"], "reason": "semantic_rejection"}
    )
    assert advisory["findings"] == 2
    # CV sprzed wdrożenia: brak raportu to brak plakietki, nie „niedostępna".
    assert final_review.summarize_review(None) is None
    assert final_review.summarize_review({"status": "whatever"}) is None


# ── Zatwierdzanie ręcznie edytowanego CV ────────────────────────────────────
#
# Do 0326 edytowane CV NIE przechodziło żadnej kontroli przy wyłączonym
# egzekwowaniu (`evidence_enforcement_off`). Teraz przechodzi doradczą: uwagi
# jadą z zatwierdzoną wersją, ale NIGDY jej nie wstrzymują.


@pytest.fixture
def approval_advisory(monkeypatch):
    """Tryb produkcyjny: kontrola włączona, egzekwowanie wyłączone."""
    monkeypatch.delenv("CV_SOURCE_EVIDENCE_ENFORCED", raising=False)
    monkeypatch.setenv("CV_FINAL_REVIEW_ENABLED", "true")


async def _prepared(monkeypatch, review_module):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    source = SimpleNamespace(
        cv_bytes=b"source",
        cv_filename="cv.docx",
        screening_notes="notatki",
        identity="Jan Kowalski",
        snapshot_sha256="hash",
    )
    monkeypatch.setattr(
        review_module, "load_review_source", AsyncMock(return_value=source)
    )
    monkeypatch.setattr(
        review_module, "extract_text_from_file", Mock(return_value="tekst CV")
    )
    draft = SimpleNamespace(
        id=5, edit_revision=7, generated_document_id=11, branded_render_metadata={}
    )
    return await review_module.prepare_approval_review(
        AsyncMock(), draft, "<p>Twierdzenie</p>"
    )


async def test_edited_cv_is_reviewed_by_the_independent_model(
    approval_advisory, monkeypatch
):
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, Mock

    from app.services import cv_approval_review as review_module

    charged = []

    @asynccontextmanager
    async def quota(db, feature, **kwargs):
        charged.append(feature)
        yield

    monkeypatch.setattr(review_module, "ai_feature", quota)
    monkeypatch.setattr(
        review_module,
        "verify_editor_content",
        Mock(return_value={"version": 3, "prompt_sha256": "p", "model": "gpt-5.6-luna"}),
    )
    prepared = await _prepared(monkeypatch, review_module)

    result = await review_module.execute_approval_review(AsyncMock(), prepared, 17)

    assert charged == [AIFeatureKey.cv_factual_verification], (
        "kontrola edytowanego CV ma płacić ze SWOJEGO kubełka, nie z generatora"
    )
    assert result["status"] == "verified"
    assert result["reviewer_model"] == "gpt-5.6-luna"


async def test_findings_do_not_refuse_the_approval(approval_advisory, monkeypatch):
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, Mock

    from app.services import cv_approval_review as review_module

    @asynccontextmanager
    async def quota(*args, **kwargs):
        yield

    monkeypatch.setattr(review_module, "ai_feature", quota)
    monkeypatch.setattr(
        review_module,
        "verify_editor_content",
        Mock(
            side_effect=factual_verification.FactualVerificationError(
                ["/why_points/0"],
                reason="semantic_rejection",
                statuses={"/why_points/0": "unsupported"},
            )
        ),
    )
    prepared = await _prepared(monkeypatch, review_module)

    result = await review_module.execute_approval_review(AsyncMock(), prepared, 17)

    assert result["status"] == "reviewed"
    assert result["findings"]["count"] == 1
    assert result["findings"]["statuses"] == {"/why_points/0": "unsupported"}


async def test_enforced_mode_still_refuses(monkeypatch):
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, Mock

    import pytest as _pytest
    from fastapi import HTTPException

    from app.services import cv_approval_review as review_module

    monkeypatch.setenv("CV_SOURCE_EVIDENCE_ENFORCED", "true")

    @asynccontextmanager
    async def quota(*args, **kwargs):
        yield

    monkeypatch.setattr(review_module, "ai_feature", quota)
    monkeypatch.setattr(
        review_module,
        "verify_editor_content",
        Mock(side_effect=factual_verification.FactualVerificationError(["/name"])),
    )
    prepared = await _prepared(monkeypatch, review_module)

    with _pytest.raises(HTTPException) as err:
        await review_module.execute_approval_review(AsyncMock(), prepared, 17)
    assert err.value.status_code == 422


async def test_an_unavailable_reviewer_does_not_block_the_approval(
    approval_advisory, monkeypatch
):
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, Mock

    from app.services import cv_approval_review as review_module

    @asynccontextmanager
    async def quota(*args, **kwargs):
        yield

    monkeypatch.setattr(review_module, "ai_feature", quota)
    monkeypatch.setattr(
        review_module,
        "verify_editor_content",
        Mock(side_effect=CVGeneratorAIError("dostawca leży")),
    )
    prepared = await _prepared(monkeypatch, review_module)

    result = await review_module.execute_approval_review(AsyncMock(), prepared, 17)

    assert result["status"] == "unverified"
    assert result["method_detail"] == "review_unavailable"


async def test_a_missing_source_degrades_instead_of_refusing(
    approval_advisory, monkeypatch
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.services import cv_approval_review as review_module
    from app.services.cv_review_sources import ReviewSourceMissing

    monkeypatch.setattr(
        review_module,
        "load_review_source",
        AsyncMock(side_effect=ReviewSourceMissing("brak zapisanych źródeł")),
    )
    draft = SimpleNamespace(
        id=5, edit_revision=7, generated_document_id=11, branded_render_metadata={}
    )

    result = await review_module.prepare_approval_review(
        AsyncMock(), draft, "<p>Treść</p>"
    )

    assert isinstance(result, dict)
    assert result["status"] == "unverified"
    assert result["method"] == "advisory_source_unavailable"
    assert result["reason"] == "source_missing"


def test_review_outcome_reads_findings_off_the_saved_version():
    from app.services.cv_approval_review import review_outcome

    assert review_outcome({"content_review": {"status": "reviewed", "findings": {"count": 3}}}) == (
        "reviewed",
        3,
    )
    assert review_outcome({"content_review": {"status": "verified"}}) == ("verified", None)
    # Wersje sprzed wdrożenia: brak wpisu = brak komunikatu, nie „niedostępna".
    assert review_outcome({}) == (None, None)
    assert review_outcome(None) == (None, None)
