"""Runda 10 (F10): Zamówienia PDF nie podają odwróconego okresu jak poprawnego.

Produkcja: zamówienie OIT/0569/2026/ITVM zapisane przed walidacją okresu
(24.09.2026) ma 01.01.2027–31.12.2026, a lista i nazwa pliku pokazywały ten
okres wprost. Wpis zostaje na liście (plik jest do rozliczenia), ale niesie
``period_invalid`` i nazwę z „okres-do-sprawdzenia” zamiast dat.
"""

from __future__ import annotations

from datetime import date

from app.services.finance_order_pdfs import (
    INVALID_PERIOD_LABEL,
    OrderPdfEntry,
    build_download_name,
    format_period,
    zip_member_name,
)


def _entry(start: date, end: date | None) -> OrderPdfEntry:
    return OrderPdfEntry(
        kind="order",
        id=1,
        client_id=39,
        client_name="Klient Testowy",
        original_name="OIT-0569.pdf",
        file_path="client_orders/1/x.pdf",
        content_type="application/pdf",
        consultant_name="Jan Testowy",
        consultant_lastname="Testowy",
        start=start,
        end=end,
        entry_type="extension",
        status="active",
        order_number="OIT/0569/2026/ITVM",
        uploaded_at=None,
    )


def test_reversed_period_is_flagged_and_not_printed_as_dates():
    entry = _entry(date(2027, 1, 1), date(2026, 12, 31))
    assert entry.period_invalid is True
    assert format_period(entry.start, entry.end) == INVALID_PERIOD_LABEL
    assert entry.download_name == f"OIT-0569_Testowy_{INVALID_PERIOD_LABEL}.pdf"
    assert "31.12.2026" not in entry.download_name
    member = zip_member_name(entry)
    assert member.endswith(f"_{INVALID_PERIOD_LABEL}.pdf")
    assert "01.01.2027-31.12.2026" not in member


def test_valid_periods_keep_their_dates():
    one_day = _entry(date(2026, 10, 1), date(2026, 10, 1))
    assert one_day.period_invalid is False
    open_ended = _entry(date(2026, 10, 1), None)
    assert open_ended.period_invalid is False
    assert build_download_name(
        "a.pdf", "Nowak", date(2026, 10, 1), date(2026, 12, 31)
    ) == ("a_Nowak_01.10.2026-31.12.2026.pdf")
