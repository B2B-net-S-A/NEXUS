"""Unit tests for the Traffit "? ?" name-backfill.

Covers:
  * `name_from_filename` — conservative filename → (first, last) heuristic.
  * The `_apply_cv_enrichment` placeholder fix — Traffit's "?" is treated as
    blank so a CV parse can overwrite it (it previously only knew "Nieznane").
  * `enrich_candidate_from_cv_bytes` — CV-content name wins; filename is a
    fallback; Traffit custom fields survive enrichment.
"""

from __future__ import annotations

import pytest

from app.models.candidate import Candidate
from app.services import cv_backfill
from app.services.cv_backfill import enrich_candidate_from_cv_bytes, name_from_filename
from app.services.cv_enrichment import _apply_cv_enrichment


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

    async def fake_parse(_text, *, prefer_llm=True, model=None):
        return {"first_name": "Marek", "last_name": "Zielinski", "email": "marek@z.pl"}

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

    async def fake_parse(_text, *, prefer_llm=True, model=None):
        return {"first_name": None, "last_name": None, "skills": []}

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

    async def fake_parse(_t, *, prefer_llm=True, model=None):
        return {
            "first_name": "Wojciech",
            "last_name": "Krzysiek",
            "email": "w.krzysiek@example.com",
            "phone": "+48 600 000 111",
        }

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

    async def fake_parse(_t, *, prefer_llm=True, model=None):
        return {"first_name": "Ula", "last_name": "Nowak", "email": "ula@example.com"}

    monkeypatch.setattr(cv_backfill, "_extract_text_from_bytes", fake_extract)
    monkeypatch.setattr("app.services.cv_parser.parse_cv", fake_parse)

    res = await enrich_candidate_from_cv_bytes(
        _FakeDB(clash=False), c, b"x", c.cv_filename
    )

    assert c.email == "ula@example.com"
    assert res["email_collision"] is False
