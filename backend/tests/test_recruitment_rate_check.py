"""Reguła porównania stawki z rekrutacji ze stawką w zamówieniu i umowie (D7).

Czyste funkcje, bez bazy. Przypadki są wspólne z lustrem we froncie
(``frontend/src/lib/__fixtures__/recruitment-rate-check-cases.json``) —
zmiana reguły bez zmiany pliku przypadków wywraca oba zestawy testów.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.services import recruitment_rate_check as check

_CASES = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "frontend/src/lib/__fixtures__/recruitment-rate-check-cases.json"
    ).read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", _CASES["compare"], ids=lambda c: c["name"])
def test_compare_matches_the_shared_cases(case):
    ref, act = case["reference"], case["actual"]
    assert (
        check.compare(
            ref["value"],
            ref["unit"],
            ref["currency"],
            act["value"],
            act["unit"],
            act["currency"],
        )
        == case["expected"]
    )


@pytest.mark.parametrize("case", _CASES["hourly"])
def test_hourly_matches_the_shared_cases(case):
    got = check.hourly_pln(case["value"], case["unit"], case["currency"])
    expected = case["expected"]
    assert got == (Decimal(expected) if expected is not None else None)


@pytest.mark.parametrize("case", _CASES["format"])
def test_format_matches_the_shared_cases(case):
    assert check.format_rate(case["value"], case["unit"]) == case["expected"]


def test_compare_ref_without_reference_is_not_comparable():
    assert check.compare_ref(None, "165", "hour") == check.NOT_COMPARABLE


def test_rateunit_enum_values_are_understood():
    from app.models.contract import RateUnit

    ref = check.RateRef(value=Decimal("165"), unit=RateUnit.hourly)
    assert check.compare_ref(ref, "1320", RateUnit.daily) == check.EQUAL
