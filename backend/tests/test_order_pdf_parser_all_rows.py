"""Tryb all-rows parsera zamówień (ścieżka mailowa) — P1b ticketu mailowego.

Kontrakt: ``parse_order_document(text, all_rows=True)`` zwraca KAŻDĄ osobę
z dokumentu jako wiersz z własnym okresem, nie wybiera żadnej i nie zwija
niczego do pól dokumentu. Ucięcie tekstu przed wysłaniem do modelu jest
WIDOCZNE (``document_truncated``), bo w tym trybie ogon tabeli to kolejne
osoby — cichy cap produkowałby poprawnie wyglądającą, niekompletną listę.
"""

from decimal import Decimal

import pytest

from app.services import order_pdf_parser as m
from app.services.llm_prompts import ORDER_EXTRACTION
from app.services.order_pdf_parser import parse_order_document

# ── prompt v5 ────────────────────────────────────────────────────────────────


def test_prompt_is_v5_and_knows_the_all_rows_switch_and_document_vat():
    """Bump wersji jest kluczem cache'u; brak placeholdera = render() rzuca."""
    assert ORDER_EXTRACTION.version == 5
    rendered = ORDER_EXTRACTION.render(
        document_text="x",
        target_consultant="(not provided)",
        list_all_consultants="yes",
    )
    assert "LIST ALL CONSULTANTS" in rendered
    assert "Never divide by VAT yourself" in rendered
    assert "Never infer this from the client identity" in rendered
    # Trzy pułapki z korpusu muszą być w prompcie — to one odróżniają v4 od v3.
    assert "FRAMEWORK vs ORDER NUMBER" in rendered
    assert "POLISH NUMBER FORMATS" in rendered
    assert "REVISION COLUMNS" in rendered
    # Okres per wiersz jest w schemacie wiersza.
    assert '"start_date": "YYYY-MM-DD"|"YYYY-MM"|null' in rendered


def test_prompt_renders_without_all_rows_placeholder_missing():
    with pytest.raises(KeyError):
        ORDER_EXTRACTION.render(document_text="x", target_consultant="(not provided)")


# ── _normalize: daty per wiersz ──────────────────────────────────────────────


def test_normalize_keeps_per_row_period_and_document_period_apart():
    data = {
        "title": "3/07/2026/BL",
        "start_date": "2026-07-01",
        "end_date": "2026-08-31",
        "rate_client": None,
        "rate_unit": None,
        "md_total": None,
        "consultant_rows": [
            {
                "consultant_name": "Baczewski Marcin",
                "start_date": "1.07.2026",
                "end_date": "31.08.2026",
                "rate_client": 1400,
                "rate_unit": "day",
                "md_total": 43,
                "uncertain": False,
                "uncertain_reason": None,
            },
            {
                "consultant_name": "Jęczeń Barbara",
                "start_date": None,
                "end_date": None,
                "rate_client": 900,
                "rate_unit": "day",
                "md_total": 43,
                "uncertain": False,
                "uncertain_reason": None,
            },
        ],
        "_confidence": {"title": 0.99, "start_date": 0.95},
        "uncertain": False,
        "uncertain_reasons": [],
    }
    r = m._normalize(data, source="claude")
    assert r.title == "3/07/2026/BL"
    assert [row.consultant_name for row in r.consultant_rows] == [
        "Baczewski Marcin",
        "Jęczeń Barbara",
    ]
    first, second = r.consultant_rows
    # Format dd.mm.yyyy z tabeli Velobanku jest normalizowany jak daty dokumentu.
    assert (first.start_date, first.end_date) == ("2026-07-01", "2026-08-31")
    assert first.rate_client == Decimal("1400")
    # Brak własnego okresu w wierszu NIE jest dziedziczony w _normalize — o tym
    # decyduje konsument (planer), który zna okres dokumentu.
    assert (second.start_date, second.end_date) == (None, None)


# ── parse_order_document(all_rows=True) ──────────────────────────────────────


@pytest.mark.asyncio
async def test_all_rows_returns_every_person_without_choosing_one(monkeypatch):
    calls: list[str] = []

    async def fake_all_rows(text: str):
        calls.append("all_rows")
        return m.OrderExtraction(
            title="OIT/0189/2026/ITVM",
            start_date="2026-04-01",
            end_date="2026-12-31",
            consultant_rows=[
                m.ConsultantOrderRow(
                    consultant_name="Wiktoria Matyja",
                    rate_client=Decimal("1340"),
                    rate_unit="day",
                    md_total=Decimal("189"),
                    start_date="2026-04-01",
                    end_date="2026-12-31",
                    uncertain=False,
                ),
                m.ConsultantOrderRow(
                    consultant_name="Bartosz Nowak",
                    rate_client=Decimal("1350"),
                    rate_unit="day",
                    md_total=Decimal("189"),
                    start_date="2026-04-01",
                    end_date="2026-12-31",
                    uncertain=False,
                ),
            ],
            uncertain=False,
            source="claude",
        )

    async def must_not_be_called(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("tryb all-rows nie może iść ścieżką targetowaną")

    monkeypatch.setattr(m, "_extract_all_rows_with_claude", fake_all_rows)
    monkeypatch.setattr(m, "_extract_with_claude", must_not_be_called)

    r = await parse_order_document("Zamówienie nr: OIT/0189/2026/ITVM …", all_rows=True)

    assert calls == ["all_rows"]
    assert len(r.consultant_rows) == 2
    # Nic nie zostało zwinięte do pól dokumentu ani wybrane.
    assert r.rate_client is None and r.md_total is None
    assert r.consultant_rate_matched is False
    assert r.source == "claude"


@pytest.mark.asyncio
async def test_all_rows_and_target_are_mutually_exclusive():
    with pytest.raises(ValueError):
        await parse_order_document("x", consultant_name="Jan Kowalski", all_rows=True)


@pytest.mark.asyncio
async def test_all_rows_regex_fallback_has_no_rows_and_says_so(monkeypatch):
    """Bez modelu nie ma wierszy — i `source` mówi to wprost bramce automatu."""

    async def no_model(text: str):
        return None

    monkeypatch.setattr(m, "_extract_all_rows_with_claude", no_model)
    r = await parse_order_document(
        "Zamówienie nr 445/2026\nJan Kowalski 1200 PLN/MD", all_rows=True
    )
    assert r.source == "regex"
    assert r.consultant_rows == []
    assert r.uncertain is True


@pytest.mark.asyncio
async def test_all_rows_marks_silent_truncation(monkeypatch):
    """Tekst ponad _MAX_DOC_CHARS bez osoby docelowej jest ucinany — flaga MUSI wstać."""
    captured: dict[str, object] = {}

    def fake_call_claude(**kwargs):  # noqa: ANN003
        captured["max_tokens"] = kwargs["max_tokens"]
        captured["prompt"] = kwargs["messages"][0]["content"]

        class _Block:
            text = (
                '{"title": "1830/2026", "start_date": "2026-09-01", "end_date": null,'
                ' "rate_client": null, "rate_unit": null, "total_value": null,'
                ' "md_total": null, "consultant_rows": [{"consultant_name":'
                ' "Andrzej Iciek", "start_date": null, "end_date": null,'
                ' "rate_client": 900, "rate_unit": "day", "md_total": 64,'
                ' "uncertain": false, "uncertain_reason": null}], "currency": "PLN",'
                ' "_confidence": {"title": 0.99}, "uncertain": false,'
                ' "uncertain_reasons": []}'
            )

        class _Msg:
            content = [_Block()]

        return _Msg()

    monkeypatch.setattr(m, "call_claude", fake_call_claude)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(m.settings, "ORDER_EXTRACTION_ENABLED", True)

    long_text = "Zamówienie nr 1830/2026\n" + ("x" * (m._MAX_DOC_CHARS + 500))
    r = await parse_order_document(long_text, all_rows=True)

    assert r.document_truncated is True
    assert r.consultant_rows[0].consultant_name == "Andrzej Iciek"
    assert captured["max_tokens"] == m._MAX_ALL_ROWS_TOKENS
    assert "LIST ALL CONSULTANTS (yes|no):\nyes" in str(captured["prompt"])

    short = await parse_order_document(
        "Zamówienie nr 1830/2026\nAndrzej Iciek", all_rows=True
    )
    assert short.document_truncated is False

    # Tryb ZWYKŁY bez osoby docelowej idzie tą samą ścieżką cięcia
    # (text[:_MAX_DOC_CHARS]), więc flaga mówi prawdę także tutaj — nie jest
    # zawężona do all_rows (wątek review #1337). Zawężenie ukryłoby realne
    # cięcie przed każdym przyszłym konsumentem tego trybu.
    plain_long = await parse_order_document(long_text)
    assert plain_long.document_truncated is True
    assert captured["max_tokens"] == m._MAX_TOKENS

    # Tryb celowany nie tnie po cichu — buduje nagłówek + okna osoby, a o
    # niepełnym kontekście mówi `uncertain`. Flaga ma tam zostać opuszczona.
    targeted_long = await parse_order_document(
        long_text + "\nAndrzej Iciek", consultant_name="Andrzej Iciek"
    )
    assert targeted_long.document_truncated is False


@pytest.mark.asyncio
async def test_targeted_mode_is_untouched_by_all_rows_switch(monkeypatch):
    """Istniejąca ścieżka targetowana dostaje `list_all_consultants=no`."""
    captured: dict[str, object] = {}

    def fake_call_claude(**kwargs):  # noqa: ANN003
        captured["prompt"] = kwargs["messages"][0]["content"]
        captured["max_tokens"] = kwargs["max_tokens"]

        class _Block:
            text = (
                '{"title": "445", "start_date": "2026-01-01", "end_date": null,'
                ' "rate_client": null, "rate_unit": null, "total_value": null,'
                ' "md_total": null, "consultant_rows": [{"consultant_name":'
                ' "Jan Kowalski", "start_date": null, "end_date": null,'
                ' "rate_client": 1200, "rate_unit": "day", "md_total": 10,'
                ' "uncertain": false, "uncertain_reason": null}], "currency": "PLN",'
                ' "_confidence": {}, "uncertain": false, "uncertain_reasons": []}'
            )

        class _Msg:
            content = [_Block()]

        return _Msg()

    monkeypatch.setattr(m, "call_claude", fake_call_claude)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(m.settings, "ORDER_EXTRACTION_ENABLED", True)

    r = await parse_order_document(
        "Zamówienie nr 445\nJan Kowalski 1200 PLN/MD 10 MD",
        consultant_name="Jan Kowalski",
        consultant_given_names="Jan",
    )
    assert "LIST ALL CONSULTANTS (yes|no):\nno" in str(captured["prompt"])
    assert captured["max_tokens"] == m._MAX_TARGETED_TOKENS
    assert r.rate_client == Decimal("1200")
    assert r.consultant_rate_matched is True
    assert r.document_truncated is False
