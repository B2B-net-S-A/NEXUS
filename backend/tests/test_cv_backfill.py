"""Unit tests for the Traffit "? ?" name-backfill.

Covers:
  * `name_from_filename` — conservative filename → (first, last) heuristic.
  * The `_apply_cv_enrichment` placeholder fix — Traffit's "?" is treated as
    blank so a CV parse can overwrite it (it previously only knew "Nieznane").
  * `enrich_candidate_from_cv_bytes` — CV-content name wins; filename is a
    fallback; Traffit custom fields survive enrichment.
  * Kwota `cv_name_backfill` — model funkcji dociera do kroku Claude'a,
    operacja powstaje tylko przed płatnym krokiem, odmowa kwoty zatrzymuje bieg.
"""

from __future__ import annotations

import inspect
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.ai_feature import AIFeatureKey
from app.models.candidate import Candidate
from app.services import cv_backfill, cv_parser
from app.services.ai_models import model_for
from app.services.ai_quota import AIQuotaExceeded
from app.services.cv_backfill import enrich_candidate_from_cv_bytes, name_from_filename
from app.services.cv_enrichment import _apply_cv_enrichment

# Sygnatura PRAWDZIWEGO `parse_cv`, pobrana przed jakimkolwiek monkeypatchem.
# Do 09.2026 zaślepki przyjmowały `model=`, którego prawdziwa funkcja nie znała —
# produkcja rzucała `TypeError` (łapany jako „parse is best-effort"), a testy
# przechodziły na zielono.
_PARSE_CV_SIGNATURE = inspect.signature(cv_parser.parse_cv)


def _fake_parse_cv(result: dict | None):
    """Zaślepka `parse_cv`, która odrzuca wywołania niezgodne z prawdziwą sygnaturą."""

    async def fake(*args, **kwargs):
        _PARSE_CV_SIGNATURE.bind(*args, **kwargs)
        fake.calls.append(kwargs)
        return dict(result) if result is not None else None

    fake.calls = []
    return fake


def _recording_gate(entered: list, *, refuse: AIQuotaExceeded | None = None):
    """Zamiennik `ai_feature` bez bazy: zapisuje wejścia, opcjonalnie odmawia."""

    @asynccontextmanager
    async def gate(_db, feature, **_kwargs):
        entered.append(feature)
        if refuse is not None:
            raise refuse
        yield None

    return gate


@pytest.fixture(autouse=True)
def _claude_step_unavailable_by_default(monkeypatch):
    """Testy nie zależą od klucza API w środowisku uruchomienia."""
    monkeypatch.setattr(cv_backfill.settings, "ANTHROPIC_API_KEY", None)
    # F10 = GPT-6 Luna (22.09.2026): krok modelu pyta o klucz DOSTAWCY.
    monkeypatch.setattr(cv_backfill.settings, "OPENAI_API_KEY", "")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def _ph_candidate(**kw) -> Candidate:
    """A nameless Traffit-style candidate (name='?'), nothing else filled."""
    return Candidate(
        id=kw.get("id", 1),
        name=kw.get("name", "?"),
        lastname=kw.get("lastname", "?"),
        email=kw.get("email"),
        phone=kw.get("phone"),
        cv_filename=kw.get("cv_filename"),
        cv_extracted_data=kw.get("cv_extracted_data", {}),
        experience=[],
    )


# ── name_from_filename ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("Blaczek_Gabriel_resume.pdf", ("Blaczek", "Gabriel")),
        ("Adam Haluszczynski CV.docx", ("Adam", "Haluszczynski")),
        ("Aleksandra Waszelewska-cv (1).pdf", ("Aleksandra", "Waszelewska")),
        ("Zinoviya Oleksiy CV EN.docx", ("Zinoviya", "Oleksiy")),
        ("VugarSuleymanov_CV.docx", ("Vugar", "Suleymanov")),
        ("jan-kowalski.pdf", ("Jan", "Kowalski")),
        # Ambiguous / no usable name — must not guess.
        ("CV_fin.pdf", (None, None)),
        ("resume.pdf", (None, None)),
        ("Kowalski.pdf", (None, None)),
        ("", (None, None)),
        (None, (None, None)),
    ],
)
def test_name_from_filename(filename, expected):
    assert name_from_filename(filename) == expected


# ── placeholder fix: "?" is blank ───────────────────────────────────────────


def test_question_mark_name_is_overwritten_by_parse():
    c = _ph_candidate(name="?", lastname="?", email=None)
    parsed = {
        "first_name": "Anna",
        "last_name": "Nowak",
        "email": "anna.nowak@example.com",
        "phone": "+48 600 100 200",
    }
    _apply_cv_enrichment(c, parsed)
    assert c.name == "Anna"
    assert c.lastname == "Nowak"
    assert c.email == "anna.nowak@example.com"
    assert c.phone == "+48 600 100 200"


def test_real_name_is_never_overwritten():
    c = _ph_candidate(name="Jan", lastname="Kowalski")
    _apply_cv_enrichment(c, {"first_name": "Other", "last_name": "Person"})
    assert c.name == "Jan"
    assert c.lastname == "Kowalski"


def test_traffit_custom_fields_survive_enrichment():
    c = _ph_candidate(
        name="?",
        cv_extracted_data={"traffit__Position": "Senior Dev", "traffit_id": "555"},
    )
    _apply_cv_enrichment(c, {"first_name": "Ola", "last_name": "Wis", "skills": []})
    assert c.cv_extracted_data["traffit__Position"] == "Senior Dev"
    assert c.cv_extracted_data["traffit_id"] == "555"
    assert c.cv_extracted_data["first_name"] == "Ola"


# ── enrich_candidate_from_cv_bytes ──────────────────────────────────────────


async def test_enrich_prefers_cv_content_over_filename(monkeypatch):
    c = _ph_candidate(name="?", lastname="?", cv_filename="VugarSuleymanov_CV.docx")

    async def fake_extract(_bytes, _name):
        return "Marek Zielinski\nPython developer\nmarek@z.pl"

    fake_parse = _fake_parse_cv(
        {"first_name": "Marek", "last_name": "Zielinski", "email": "marek@z.pl"}
    )

    monkeypatch.setattr(cv_backfill, "_extract_text_from_bytes", fake_extract)
    monkeypatch.setattr("app.services.cv_parser.parse_cv", fake_parse)

    res = await enrich_candidate_from_cv_bytes(None, c, b"PK..", c.cv_filename)

    assert c.name == "Marek" and c.lastname == "Zielinski"
    assert c.email == "marek@z.pl"
    assert res["name_source"] == "cv"
    assert res["resolved"] is True


async def test_enrich_falls_back_to_filename_when_cv_has_no_name(monkeypatch):
    c = _ph_candidate(name="?", lastname="?", cv_filename="Adam Haluszczynski CV.docx")

    async def fake_extract(_bytes, _name):
        return "Some CV text without a clear header name"

    fake_parse = _fake_parse_cv({"first_name": None, "last_name": None, "skills": []})

    monkeypatch.setattr(cv_backfill, "_extract_text_from_bytes", fake_extract)
    monkeypatch.setattr("app.services.cv_parser.parse_cv", fake_parse)

    res = await enrich_candidate_from_cv_bytes(None, c, b"PK..", c.cv_filename)

    assert c.name == "Adam" and c.lastname == "Haluszczynski"
    assert res["name_source"] == "filename"
    assert res["resolved"] is True


async def test_enrich_unresolved_when_no_text_and_unhelpful_filename(monkeypatch):
    c = _ph_candidate(name="?", lastname="?", cv_filename="CV_fin.pdf")

    async def fake_extract(_bytes, _name):
        return ""  # extraction yielded nothing

    monkeypatch.setattr(cv_backfill, "_extract_text_from_bytes", fake_extract)

    res = await enrich_candidate_from_cv_bytes(None, c, b"PK..", c.cv_filename)

    assert c.name == "?"  # still unresolved — never guessed garbage
    assert res["resolved"] is False


# ── email-collision guard (duplicate Traffit rows) ──────────────────────────


class _FakeDB:
    """Minimal stand-in: scalar() returns 1 to simulate an existing email."""

    def __init__(self, clash: bool):
        self._clash = clash

    async def scalar(self, *_a, **_k):
        return 1 if self._clash else None


async def test_enrich_drops_colliding_email_but_keeps_name(monkeypatch):
    c = _ph_candidate(name="?", lastname="?", cv_filename="Dup_CV.docx")

    async def fake_extract(_b, _n):
        return "cv text"

    fake_parse = _fake_parse_cv(
        {
            "first_name": "Wojciech",
            "last_name": "Krzysiek",
            "email": "w.krzysiek@example.com",
            "phone": "+48 600 000 111",
        }
    )

    monkeypatch.setattr(cv_backfill, "_extract_text_from_bytes", fake_extract)
    monkeypatch.setattr("app.services.cv_parser.parse_cv", fake_parse)

    res = await enrich_candidate_from_cv_bytes(
        _FakeDB(clash=True), c, b"x", c.cv_filename
    )

    assert c.name == "Wojciech" and c.lastname == "Krzysiek"  # name still filled
    assert c.email is None  # colliding email dropped
    assert c.phone == "+48 600 000 111"  # phone still filled
    assert res["email_collision"] is True
    assert res["resolved"] is True


async def test_enrich_keeps_unique_email(monkeypatch):
    c = _ph_candidate(name="?", lastname="?", cv_filename="Ula_Nowak_CV.pdf")

    async def fake_extract(_b, _n):
        return "cv text"

    fake_parse = _fake_parse_cv(
        {"first_name": "Ula", "last_name": "Nowak", "email": "ula@example.com"}
    )

    monkeypatch.setattr(cv_backfill, "_extract_text_from_bytes", fake_extract)
    monkeypatch.setattr("app.services.cv_parser.parse_cv", fake_parse)

    res = await enrich_candidate_from_cv_bytes(
        _FakeDB(clash=False), c, b"x", c.cv_filename
    )

    assert c.email == "ula@example.com"
    assert res["email_collision"] is False


# ── kwota i model `cv_name_backfill` ────────────────────────────────────────


def test_parse_cv_accepts_the_model_the_name_backfill_passes():
    """Prawdziwa sygnatura przyjmuje wywołanie z `cv_backfill` (do 09.2026: TypeError)."""
    _PARSE_CV_SIGNATURE.bind(
        "cv text", prefer_llm=True, model=model_for(AIFeatureKey.cv_name_backfill)
    )


def _claude_step_available(monkeypatch):
    monkeypatch.setattr(cv_backfill.settings, "ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(cv_backfill.settings, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(cv_backfill.settings, "CV_ENRICHMENT_ENABLED", True)


async def test_name_backfill_reaches_claude_with_its_own_model_under_its_quota(
    monkeypatch,
):
    _claude_step_available(monkeypatch)
    c = _ph_candidate(name="?", lastname="?", cv_filename="CV_fin.pdf")
    seen_models: list = []

    async def fake_claude(cv_text, *, model=None, template=cv_parser.CV_ENRICHMENT):
        seen_models.append(model)
        return {"first_name": "Halina", "last_name": "Kwiatkowska"}

    async def fake_extract(_b, _n):
        return "Halina Kwiatkowska\nTester manualny"

    entered: list = []
    monkeypatch.setattr(cv_backfill, "_extract_text_from_bytes", fake_extract)
    monkeypatch.setattr(cv_parser, "_parse_with_claude", fake_claude)
    monkeypatch.setattr(cv_backfill, "ai_feature", _recording_gate(entered))

    res = await enrich_candidate_from_cv_bytes(
        _FakeDB(clash=False), c, b"PK..", c.cv_filename
    )

    assert seen_models == [model_for(AIFeatureKey.cv_name_backfill)]
    assert entered == [AIFeatureKey.cv_name_backfill]
    assert (c.name, c.lastname) == ("Halina", "Kwiatkowska")
    assert res["name_source"] == "cv"


async def test_no_quota_operation_for_a_candidate_without_cv_text(monkeypatch):
    _claude_step_available(monkeypatch)
    c = _ph_candidate(name="?", lastname="?", cv_filename="Adam Haluszczynski CV.docx")

    async def fake_extract(_b, _n):
        return "   "

    entered: list = []
    monkeypatch.setattr(cv_backfill, "_extract_text_from_bytes", fake_extract)
    monkeypatch.setattr(cv_backfill, "ai_feature", _recording_gate(entered))

    res = await enrich_candidate_from_cv_bytes(
        _FakeDB(clash=False), c, b"PK..", c.cv_filename
    )

    assert entered == []
    assert res["name_source"] == "filename"


async def test_no_quota_operation_when_the_llm_is_not_preferred(monkeypatch):
    _claude_step_available(monkeypatch)
    c = _ph_candidate(name="?", lastname="?", cv_filename="Ula_Nowak_CV.pdf")
    fake_parse = _fake_parse_cv({"first_name": "Ula", "last_name": "Nowak"})

    async def fake_extract(_b, _n):
        return "Ula Nowak"

    entered: list = []
    monkeypatch.setattr(cv_backfill, "_extract_text_from_bytes", fake_extract)
    monkeypatch.setattr("app.services.cv_parser.parse_cv", fake_parse)
    monkeypatch.setattr(cv_backfill, "ai_feature", _recording_gate(entered))

    await enrich_candidate_from_cv_bytes(
        _FakeDB(clash=False), c, b"PK..", c.cv_filename, prefer_llm=False
    )

    assert entered == []
    assert fake_parse.calls[0]["prefer_llm"] is False


async def test_quota_refusal_is_raised_instead_of_a_filename_guess(monkeypatch):
    _claude_step_available(monkeypatch)
    c = _ph_candidate(name="?", lastname="?", cv_filename="Adam Haluszczynski CV.docx")

    async def fake_extract(_b, _n):
        return "Adam Haluszczynski"

    refusal = AIQuotaExceeded(
        AIFeatureKey.cv_name_backfill, "Miesięczny limit wyczerpany"
    )
    monkeypatch.setattr(cv_backfill, "_extract_text_from_bytes", fake_extract)
    monkeypatch.setattr(cv_backfill, "ai_feature", _recording_gate([], refuse=refusal))

    with pytest.raises(AIQuotaExceeded):
        await enrich_candidate_from_cv_bytes(
            _FakeDB(clash=False), c, b"PK..", c.cv_filename
        )
    assert (c.name, c.lastname) == ("?", "?")


async def test_backfill_run_stops_on_quota_refusal(monkeypatch):
    _claude_step_available(monkeypatch)
    first = _ph_candidate(id=1, name="?", lastname="?", cv_filename="Jan_Kowalski.pdf")
    first.cv_file_content = b"PK.."
    first.cv_storage_key = None

    async def fake_extract(_b, _n):
        return "Jan Kowalski"

    refusal = AIQuotaExceeded(
        AIFeatureKey.cv_name_backfill, "Miesięczny limit wyczerpany"
    )
    monkeypatch.setattr(cv_backfill, "_extract_text_from_bytes", fake_extract)
    monkeypatch.setattr(cv_backfill, "ai_feature", _recording_gate([], refuse=refusal))

    db = SimpleNamespace(
        execute=AsyncMock(return_value=[SimpleNamespace(id=1), SimpleNamespace(id=2)]),
        scalar=AsyncMock(return_value=first),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )

    stats = await cv_backfill.backfill_missing_names(db)

    assert stats["stopped_reason"].startswith("quota:")
    assert stats["processed"] == 0
    assert db.scalar.await_count == 1  # drugi kandydat nie jest już nawet wczytany
    db.commit.assert_not_awaited()
    assert (first.name, first.lastname) == ("?", "?")


# ── ten sam plik CV nie idzie do modelu drugi raz ───────────────────────────


def _model_stamp(cv_bytes: bytes, *, extractor: str | None = "claude:cv_enrichment:v4"):
    """`cv_highlights` w kształcie zapisywanym przez `_apply_cv_enrichment`."""
    import hashlib

    return {
        "source_hash": hashlib.sha256(cv_bytes).hexdigest(),
        "extractor_version": extractor,
    }


async def test_cv_already_read_by_the_model_is_not_read_again(monkeypatch):
    _claude_step_available(monkeypatch)
    cv = b"PK.. ten sam plik"
    c = _ph_candidate(
        cv_filename="CV_fin.pdf", cv_extracted_data={"cv_highlights": _model_stamp(cv)}
    )

    async def must_not_extract(_b, _n):
        raise AssertionError("tekst CV czytany ponownie")

    entered: list = []
    monkeypatch.setattr(cv_backfill, "_extract_text_from_bytes", must_not_extract)
    monkeypatch.setattr(cv_backfill, "ai_feature", _recording_gate(entered))

    for prefer_llm in (True, False):
        res = await enrich_candidate_from_cv_bytes(
            _FakeDB(clash=False), c, cv, c.cv_filename, prefer_llm=prefer_llm
        )
        assert res["skipped_reason"] == "cv_already_read_by_model"

    assert entered == []
    assert (c.name, c.lastname) == ("?", "?")
    assert c.cv_extracted_data == {"cv_highlights": _model_stamp(cv)}


@pytest.mark.parametrize(
    "stamp",
    [
        pytest.param(lambda cv: _model_stamp(b"PK.. inny plik"), id="nowe-cv"),
        # Stan wierszy po błędzie z 09.2026: skrót zapisany, model nie czytał.
        pytest.param(lambda cv: _model_stamp(cv, extractor=None), id="bez-modelu"),
        pytest.param(lambda cv: _model_stamp(cv, extractor="regex"), id="regex"),
        pytest.param(lambda cv: {"extractor_version": "claude:x:v1"}, id="bez-skrotu"),
    ],
)
async def test_model_reads_a_cv_it_has_not_read_yet(monkeypatch, stamp):
    _claude_step_available(monkeypatch)
    cv = b"PK.. ten sam plik"
    c = _ph_candidate(
        cv_filename="CV_fin.pdf", cv_extracted_data={"cv_highlights": stamp(cv)}
    )

    async def fake_claude(cv_text, *, model=None, template=cv_parser.CV_ENRICHMENT):
        return {"first_name": "Halina", "last_name": "Kwiatkowska"}

    async def fake_extract(_b, _n):
        return "Halina Kwiatkowska\nTester manualny"

    entered: list = []
    monkeypatch.setattr(cv_backfill, "_extract_text_from_bytes", fake_extract)
    monkeypatch.setattr(cv_parser, "_parse_with_claude", fake_claude)
    monkeypatch.setattr(cv_backfill, "ai_feature", _recording_gate(entered))

    res = await enrich_candidate_from_cv_bytes(
        _FakeDB(clash=False), c, cv, c.cv_filename
    )

    assert entered == [AIFeatureKey.cv_name_backfill]
    assert res["skipped_reason"] is None
    assert (c.name, c.lastname) == ("Halina", "Kwiatkowska")


def test_non_dict_extracted_data_does_not_break_the_read_check():
    c = _ph_candidate(cv_extracted_data=["stary", "kształt"])
    assert cv_backfill._model_already_read(c, "abc") is False
