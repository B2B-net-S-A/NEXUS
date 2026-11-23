"""Rodzaj pliku z poczty rozliczeń: „faktura” sprawdzona treścią (próba IX–X 2026).

RCP BNP przysłane z tematem „faktura …”, jako „2026-09.pdf” albo w mailu
„FV i podpisane rozliczenie godzinowe” trafiało do faktur, więc rozliczenie nie
powstawało (9 przypadków). PDF rozpoznany jako RCP to raport; prawdziwa faktura
zostaje fakturą.
"""

from __future__ import annotations

from app.services.client_settlements import rcp_bnp
from app.services.consultant_portal.mailbox import kind_of_file


def test_pdf_named_as_invoice_but_rcp_inside_is_a_report(monkeypatch) -> None:
    seen = []

    def fake_parse(content: bytes, mime: str):
        seen.append(mime)
        return object()

    monkeypatch.setattr(rcp_bnp, "parse", fake_parse)
    assert kind_of_file("faktura 09/2026", "2026-09.pdf", b"%PDF-1.7 ...") == "report"
    assert seen == ["application/pdf"]


def test_real_invoice_pdf_stays_an_invoice(monkeypatch) -> None:
    monkeypatch.setattr(rcp_bnp, "parse", lambda content, mime: None)
    assert (
        kind_of_file("FV 1/10/2026", "FV_1_10_2026.pdf", b"%PDF-1.4 ...") == "invoice"
    )


def test_report_by_name_is_not_parsed(monkeypatch) -> None:
    def boom(content: bytes, mime: str):
        raise AssertionError("raport z nazwy nie wymaga odczytu treści")

    monkeypatch.setattr(rcp_bnp, "parse", boom)
    assert kind_of_file("TS wrzesień", "Timesheet_09.pdf", b"%PDF-1.7") == "report"


def test_non_pdf_invoice_is_not_parsed(monkeypatch) -> None:
    monkeypatch.setattr(rcp_bnp, "parse", lambda content, mime: object())
    assert kind_of_file("faktura", "faktura.xml", b"<xml/>") == "invoice"
