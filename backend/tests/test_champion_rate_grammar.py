"""The spellings of a PLN-per-hour rate recruiters actually write.

`pln_hourly_bounds` decides whether a document's rate text can be a budget at
all. The first grammar (11.09) accepted one fixed phrase, so "140 zł netto/h"
or "Stawka: 140 zł/h" — texts sitting next to a 140 PLN/h budget in profiles
of the 08.2026 import — read as "not PLN per hour", and the next reconcile,
import or template copy wiped the budget. The grammar is now token-based: the
currency, the per-hour unit and the net qualifiers in any order. Other
currencies, day/MD/month rates, gross figures and monthly "k PLN" shapes are
still rejected.
"""

import itertools
import re

import pytest

from app.services.champion_intake import (
    document_rate,
    pln_hourly_bounds,
    prepare_profile,
)

ACCEPTED = [
    # One value — currency and unit in any order and spelling.
    ("140 zł/h", (140.0, 140.0)),
    ("140zł/h", (140.0, 140.0)),
    ("140 PLN/h", (140.0, 140.0)),
    ("140 PLN / h", (140.0, 140.0)),
    ("PLN 140/h", (140.0, 140.0)),
    ("140 zł/godz.", (140.0, 140.0)),
    ("140 PLN/godzinę", (140.0, 140.0)),
    ("140 zł za godzinę", (140.0, 140.0)),
    ("140 zł na godzinę", (140.0, 140.0)),
    ("140 złotych netto za godzinę", (140.0, 140.0)),
    ("140 PLN per hour", (140.0, 140.0)),
    ("140 zł/1h", (140.0, 140.0)),
    # Net qualifiers anywhere around the currency and the unit.
    ("140 zł netto/h", (140.0, 140.0)),
    ("140 PLN netto/h", (140.0, 140.0)),
    ("140 zł/h netto", (140.0, 140.0)),
    ("140 zł/h + VAT", (140.0, 140.0)),
    ("140 PLN/h netto + VAT", (140.0, 140.0)),
    ("140 zł/h (netto, B2B)", (140.0, 140.0)),
    ("140 PLN/h B2B", (140.0, 140.0)),
    ("140 zł/h na B2B", (140.0, 140.0)),
    ("140 zł/h bez VAT", (140.0, 140.0)),
    # Number formats.
    ("140,50 zł/h", (140.5, 140.5)),
    ("140.00 PLN/h", (140.0, 140.0)),
    # Not a realistic hourly rate — but read as 1400, not as 1 or 400.
    ("1 400 zł/h", (1400.0, 1400.0)),
    ("1\u00a0400 zł/h", (1400.0, 1400.0)),  # a no-break space from Word
    # A label in front.
    ("Stawka: 140 zł/h", (140.0, 140.0)),
    ("Maks. stawka kandydata: 140 zł/h", (140.0, 140.0)),
    # Approximately one value.
    ("ok. 140 zł/h", (140.0, 140.0)),
    ("około 140 zł/h", (140.0, 140.0)),
    ("~140 zł/h", (140.0, 140.0)),
    # An upper bound.
    ("do 140 zł netto/h", (0.0, 140.0)),
    ("do 140 PLN/h", (0.0, 140.0)),
    ("do 140 PLN/h netto", (0.0, 140.0)),
    ("max. 140 zł/godz. + VAT", (0.0, 140.0)),
    ("maks. 140 PLN/h", (0.0, 140.0)),
    ("maksymalnie 140 zł/h", (0.0, 140.0)),
    ("up to 140 PLN/h", (0.0, 140.0)),
    ("Stawka maksymalna: do 140 zł/h netto", (0.0, 140.0)),
    # A range.
    ("120-140 zł/h", (120.0, 140.0)),
    ("120–140 zł/h", (120.0, 140.0)),
    ("120 - 140 zł/h netto", (120.0, 140.0)),
    ("120-140 zł netto/h", (120.0, 140.0)),
    ("120 – 140 PLN/h + VAT", (120.0, 140.0)),
    ("120/140 zł/h", (120.0, 140.0)),
    ("od 120 do 140 zł/h", (120.0, 140.0)),
    ("120 zł/h – 140 zł/h", (120.0, 140.0)),
    ("PLN 120-140/h", (120.0, 140.0)),
    ("Budżet: 120-140 PLN/h", (120.0, 140.0)),
]

REJECTED = [
    # Another currency.
    "45 EUR/h",
    "45 €/h",
    "40 USD/h",
    "120–140 EUR/h",
    # Another unit: day, MD, month.
    "1200 PLN/MD",
    "180 PLN/MD netto",
    "1200 zł/dzień",
    "20 000 PLN/mies.",
    "20 000 PLN miesięcznie",
    # "k PLN" monthly shapes.
    "20k PLN",
    "20k PLN/h",
    "25 k PLN/mies.",
    # Gross: another number than the net budget.
    "140 zł/h brutto",
    "120–140 zł/h brutto",
    # A missing currency or unit.
    "120–140 zł",
    "140 zł",
    "140/h",
    "140",
    "",
    # Words left over — the text does not vouch for one PLN/h budget.
    "130 zł/h lub 1000 zł/MD",
    "140 zł/h, 1100 zł/MD",
    "140 PLN/h (ok. 35 EUR/h)",
    "stawka do negocjacji",
    "od 120 zł/h",
    "140 zł/h + 23% VAT",
    "zlecenie 140/h",
]


@pytest.mark.parametrize("text,bounds", ACCEPTED)
def test_recruiter_spellings_of_a_pln_per_hour_rate(text, bounds) -> None:
    assert pln_hourly_bounds(text) == bounds


@pytest.mark.parametrize("text", REJECTED)
def test_texts_that_cannot_vouch_for_a_pln_per_hour_budget(text) -> None:
    assert pln_hourly_bounds(text) is None


def test_the_tables_are_big_enough_to_mean_something() -> None:
    assert len(ACCEPTED) >= 30
    assert len(REJECTED) >= 20


@pytest.mark.parametrize("text,bounds", ACCEPTED)
def test_the_budget_is_the_upper_bound(text, bounds) -> None:
    low, high = bounds
    assert document_rate(text) == (high, low < high)


# ── Nothing the base (05590855) accepted is lost ─────────────────────────────


def _base_rate(value):
    """`rate` + `number` at 05590855 — the only rate reader the base had."""
    text = re.sub(r"\s*(?:PLN|zł)\s*/\s*(?:h|godz\.?)\s*$", "", str(value), flags=re.I)
    text = str(text).strip().replace(",", ".")
    if not re.fullmatch(r"\d+(?:\.\d+)?", text):
        return None
    number = float(text)
    return number if 0 < number <= 2000 else None


def _base_corpus():
    numbers = ["140", "140.5", "140,5", "99", "2000", "1", "0", "2001"]
    currencies = ["PLN", "pln", "Pln", "zł", "ZŁ", "Zł"]
    before = ["", " ", "  "]
    slashes = ["/", " / ", "/ ", " /"]
    units = ["h", "H", "godz", "godz.", "GODZ."]
    after = ["", " "]
    for parts in itertools.product(numbers, before, currencies, slashes, units, after):
        number, gap, currency, slash, unit, tail = parts
        yield f"{number}{gap}{currency}{slash}{unit}{tail}"
    yield from numbers


def test_every_spelling_the_base_accepted_is_still_accepted() -> None:
    accepted = 0
    for text in _base_corpus():
        expected = _base_rate(text)
        if expected is None:
            continue
        accepted += 1
        assert document_rate(text) == (expected, False), text
        cp = prepare_profile({"basics": {"rate_value": None, "rate_raw": text}})
        assert cp["basics"]["rate_value"] == expected, text
        assert "basics.rate_value" not in cp["intake"]["unresolved"], text
        if not text.strip().replace(",", "").replace(".", "").isdigit():
            # With a currency and unit, the new grammar reads it on its own too.
            assert pln_hourly_bounds(text) == (expected, expected), text
    assert accepted > 1000
