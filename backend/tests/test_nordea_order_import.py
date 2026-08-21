from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.nordea_order_import import NordeaImportError, parse_nordea_csv


def _csv(*rows: str) -> bytes:
    header = (
        "Numer zamówienia;Kontraktor;Line manager;Start date;End date;"
        "Stawka  przychodowa;Stawka z umowy ramowej"
    )
    return ("\ufeff" + "\n".join([header, *rows])).encode("utf-8")


def test_parser_converts_decimal_commas_and_keeps_two_orders_for_one_person():
    parsed = parse_nordea_csv(
        _csv(
            "279411;Paweł Włodarczyk;Manager;25.02.2026;23.08.2026;185;178",
            "285838;Paweł Włodarczyk;Manager;24.08.2026;23.02.2027;195,8;56,4",
        )
    )
    assert [row.order_number for row in parsed] == ["279411", "285838"]
    assert parsed[1].revenue_rate == Decimal("195.8")
    assert parsed[1].framework_rate == Decimal("56.40")
    assert parsed[1].row_number == 3


def test_parser_rejects_end_before_start_with_row_number():
    with pytest.raises(NordeaImportError, match="Wiersz 2"):
        parse_nordea_csv(_csv("123;Jan Kowalski;Manager;01.09.2026;31.08.2026;150;120"))


def test_parser_rejects_wrong_structure_instead_of_guessing():
    with pytest.raises(NordeaImportError, match="nagłówków"):
        parse_nordea_csv(b"foo;bar\n1;2")
