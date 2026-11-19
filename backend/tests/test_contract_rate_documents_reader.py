"""Czytnik stawki z dokumentu kontraktu (bez modelu i bez bazy)."""

from __future__ import annotations

import json

from app.services.contract_rate_documents import reader


def _reply(**over):
    base = {
        "kind": "annex",
        "agreement_number": "1/2026",
        "document_date": "2026-10-01",
        "changes_rate": True,
        "rate_steps": [
            {
                "rate": "124,50",
                "currency": "pln",
                "unit": "hour",
                "from": "2026-11-01",
                "to": None,
            }
        ],
        "effective_from": "2026-11-01",
        "other_rates": [{"rate": 180, "unit": "hour", "label": "nadgodziny"}],
        "quote": "124,50 zł netto za roboczogodzinę",
    }
    base.update(over)
    return "```json\n" + json.dumps(base, ensure_ascii=False) + "\n```"


def test_parse_reply_cleans_fields():
    result = reader.parse_reply(_reply(), "text")
    assert result.status == "read" and result.mode == "text"
    step = result.fields["rate_steps"][0]
    assert step == {
        "rate": 124.5,
        "currency": "PLN",
        "unit": "hour",
        "from": "2026-11-01",
        "to": None,
        "condition": None,
    }
    assert result.fields["other_rates"][0]["label"] == "nadgodziny"


def test_parse_reply_drops_bad_steps_and_unknown_kind():
    result = reader.parse_reply(
        _reply(
            kind="faktura",
            rate_steps=[{"rate": -5, "unit": "hour"}, {"rate": 100, "unit": "week"}],
        )
    )
    assert result.fields["kind"] == "other"
    assert result.fields["rate_steps"] == []
    assert result.fields["changes_rate"] is False


def test_parse_reply_garbage_is_failed():
    assert reader.parse_reply("nie wiem").status == "failed"
    assert reader.parse_reply("{to nie json}").status == "failed"
    assert reader.parse_reply("[1, 2]").status == "failed"


def test_invalid_dates_become_none():
    result = reader.parse_reply(
        _reply(document_date="01.10.2026", effective_from="jutro")
    )
    assert (
        result.fields["document_date"] is None
        and result.fields["effective_from"] is None
    )


def test_mime_for_known_and_unknown_files():
    assert reader.mime_for("Aneks.PDF", None) == "application/pdf"
    assert reader.mime_for("skan.jpg", "application/octet-stream") == "image/jpeg"
    assert reader.mime_for("umowa.docx", "application/vnd.openxmlformats") is None


def test_image_goes_to_model_as_image(monkeypatch):
    blocks, mode = reader.build_content("skan.png", b"\x89PNG", "image/png")
    assert mode == "image" and blocks[0]["type"] == "image"


def test_pdf_with_text_is_sent_as_text(monkeypatch):
    monkeypatch.setattr(
        reader, "pdf_pages_text", lambda content: ["§ 6 stawka 124 zł " * 10]
    )
    blocks, mode = reader.build_content("aneks.pdf", b"%PDF", "application/pdf")
    assert mode == "text" and blocks[0]["type"] == "text" and "§ 6" in blocks[0]["text"]


def test_scanned_pdf_is_sent_as_document(monkeypatch):
    monkeypatch.setattr(reader, "pdf_pages_text", lambda content: ["", " "])
    blocks, mode = reader.build_content("skan.pdf", b"%PDF", "application/pdf")
    assert mode == "pdf" and blocks[0]["type"] == "document"


async def test_unsupported_or_huge_file_is_skipped():
    assert (
        await reader.read_document(b"x", "application/msword", "a.doc")
    ).status == "skipped"
    big = b"0" * (reader.MAX_BYTES + 1)
    assert (
        await reader.read_document(big, "application/pdf", "a.pdf")
    ).status == "skipped"
