"""Rabat roczny od obrotu klienta (``client_invoicing/rebate.py``) — bez bazy.

Decyzje Artura 16.11.2026: rabat jako pozycja na każdej fakturze po stawce
progu obrotu SPRZED miesiąca faktury, wyższa stawka tylko od nadwyżki, za
miesiąc przekroczenia korekta różnicy od części ponad próg, próg w innej
walucie po kursie NBP z każdej faktury. Kwoty fikcyjne.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.client_invoicing import issue_settings, rebate

TIERED = {
    "threshold_currency": "EUR",
    "periods": [
        {"from_year": 2024, "tiers": [{"up_to": None, "rate": 2.5}]},
        {
            "from_year": 2026,
            "tiers": [{"up_to": None, "rate": 3}, {"up_to": 1000, "rate": 2.5}],
        },
    ],
    "exclude_words": ["Podróż", " refaktura "],
}
DAY = date(2026, 10, 30)
RATES = {DAY: {"PLN": Decimal("1"), "EUR": Decimal("4.0000")}}


def _terms() -> rebate.Terms:
    terms = rebate.parse_terms(TIERED)
    assert terms is not None
    return terms


def _entry(net: str, month: int = 10, currency: str = "PLN") -> rebate.Entry:
    return rebate.Entry(currency, Decimal(net), DAY, month)


# ── Warunki jako dane ───────────────────────────────────────────────────────


def test_terms_are_sorted_and_round_trip_to_json():
    terms = _terms()
    tiers = rebate.tiers_for(terms, 2026)
    assert [t.up_to for t in tiers] == [Decimal(1000), None]
    assert terms.exclude_words == ("podróż", "refaktura")
    again = rebate.parse_terms(rebate.to_json(terms))
    assert again == terms
    assert rebate.to_json(terms)["periods"][1]["tiers"] == [
        {"up_to": 1000, "rate": 2.5},
        {"up_to": None, "rate": 3},
    ]


def test_no_terms_means_no_rebate():
    assert rebate.parse_terms(None) is None
    assert rebate.parse_terms({}) is None


def test_period_applies_from_its_year_for_the_whole_year():
    terms = _terms()
    assert rebate.tiers_for(terms, 2023) is None
    assert [t.rate for t in rebate.tiers_for(terms, 2025)] == [Decimal("2.5")]
    # Aneks z marca 2026 zmienia progi dla całego 2026 (rozliczenie roczne).
    assert len(rebate.tiers_for(terms, 2026)) == 2
    assert len(rebate.tiers_for(terms, 2030)) == 2


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({**TIERED, "threshold_currency": "GBP"}, "waluta progu"),
        ({**TIERED, "periods": []}, "okresów"),
        (
            {**TIERED, "periods": [{"from_year": 2026, "tiers": []}]},
            "od 1 do 6 progów",
        ),
        (
            {
                **TIERED,
                "periods": [
                    {
                        "from_year": 2026,
                        "tiers": [
                            {"up_to": None, "rate": 2},
                            {"up_to": None, "rate": 3},
                        ],
                    }
                ],
            },
            "dokładnie jeden próg bez górnej granicy",
        ),
        (
            {
                **TIERED,
                "periods": [
                    {
                        "from_year": 2026,
                        "tiers": [
                            {"up_to": 1000, "rate": 2},
                            {"up_to": 1000, "rate": 3},
                        ],
                    }
                ],
            },
            "dokładnie jeden próg bez górnej granicy",
        ),
        (
            {
                **TIERED,
                "periods": [
                    {
                        "from_year": 2026,
                        "tiers": [
                            {"up_to": 1000, "rate": 2},
                            {"up_to": 1000, "rate": 2.5},
                            {"up_to": None, "rate": 3},
                        ],
                    }
                ],
            },
            "tą samą granicą",
        ),
        (
            {
                **TIERED,
                "periods": [
                    {"from_year": 2026, "tiers": [{"up_to": None, "rate": 101}]}
                ],
            },
            "od 0 do 100%",
        ),
        (
            {
                **TIERED,
                "periods": [
                    {
                        "from_year": 2026,
                        "tiers": [{"up_to": -5, "rate": 2}, {"up_to": None, "rate": 3}],
                    }
                ],
            },
            "dodatnia",
        ),
        (
            {
                **TIERED,
                "periods": [
                    {"from_year": 2026, "tiers": [{"up_to": None, "rate": True}]}
                ],
            },
            "podaj liczbę",
        ),
        (
            {
                **TIERED,
                "periods": [
                    {"from_year": 2026, "tiers": [{"up_to": None, "rate": 2}]},
                    {"from_year": 2026, "tiers": [{"up_to": None, "rate": 3}]},
                ],
            },
            "tego samego roku",
        ),
        (
            {
                **TIERED,
                "periods": [
                    {"from_year": "2026", "tiers": [{"up_to": None, "rate": 2}]}
                ],
            },
            "rok początku",
        ),
        ({**TIERED, "exclude_words": ["x"]}, "słowo wyłączające"),
        ("2.5%", "złe dane"),
    ],
)
def test_bad_terms_are_refused(raw, message):
    with pytest.raises(rebate.RebateTermsError, match=message):
        rebate.parse_terms(raw)


def test_settings_save_refuses_bad_terms_but_load_survives_them():
    bad = {"clients": {"11": {"rebate": {**TIERED, "threshold_currency": "GBP"}}}}
    with pytest.raises(issue_settings.IssueSettingsError, match="klient 11"):
        issue_settings._check_rebates(bad)  # noqa: SLF001
    # Odczyt złych danych z bazy nie zatrzymuje wystawiania: rabat odpada.
    loaded = issue_settings.normalize(bad)
    assert "rebate" not in loaded["clients"].get("11", {})
    assert issue_settings.client_rebate(loaded, 11) is None

    good = issue_settings.normalize({"clients": {"11": {"rebate": TIERED}}})
    assert issue_settings.client_rebate(good, 11) == _terms()
    assert issue_settings.client_rebate(good, 12) is None
    assert issue_settings.client_rebate(good, None) is None


# ── Stawka z obrotu sprzed miesiąca, nadwyżka, korekta ─────────────────────


def _tiers():
    return rebate.tiers_for(_terms(), 2026)


def test_threshold_is_inclusive():
    tiers = _tiers()
    assert rebate.tier_for(Decimal("1000.00"), tiers).rate == Decimal("2.5")
    assert rebate.tier_for(Decimal("1000.01"), tiers).rate == Decimal(3)
    assert rebate.tier_for(Decimal("-50"), tiers).rate == Decimal("2.5")


def test_due_counts_higher_rate_only_on_the_excess():
    tiers = _tiers()
    assert rebate.due(Decimal(1000), tiers) == Decimal("25.0")
    # 1 000 × 2,5% + 200 × 3% — nie 1 200 × 3%.
    assert rebate.due(Decimal(1200), tiers) == Decimal("31.0")
    assert rebate.due(Decimal(0), tiers) == Decimal(0)


def test_month_after_crossing_gets_3_percent_and_crossing_month_a_correction():
    # 4,00 PLN/EUR: wrzesień 3 200 PLN = 800 EUR, październik 1 600 PLN = 400 EUR.
    status = rebate.summarize(
        2026, _terms(), [_entry("3200.00", 9), _entry("1600.00", 10)], RATES
    )
    assert status.turnover == Decimal("1200.00")
    assert status.rate_for(9).rate == Decimal("2.5")
    # Październik przekroczył próg (800 → 1 200 EUR), ale faktury za październik
    # idą jeszcze po 2,5%; 3% dopiero od listopada.
    assert status.rate_for(10).rate == Decimal("2.5")
    assert status.rate_for(11).rate == Decimal(3)
    assert status.next_tier(10).rate == Decimal(3)
    assert status.next_tier(11) is None
    (correction,) = status.corrections
    assert correction.month == 10
    assert correction.rate_diff == Decimal("0.5")
    assert correction.excess == Decimal("200.00")
    # 0,5% od części października ponad próg: 200 EUR z 400 EUR → połowa z 1 600 PLN.
    assert correction.amounts == (("PLN", Decimal("4.00")),)
    assert status.due == Decimal("31.0")


def test_no_correction_below_threshold_and_months_after_are_billed_right():
    below = rebate.summarize(2026, _terms(), [_entry("3996.00", 9)], RATES)
    assert below.corrections == ()
    assert below.to_next() == Decimal("1.00")
    # Listopad w całości ponad progiem i fakturowany po 3% — bez korekty.
    after = rebate.summarize(
        2026,
        _terms(),
        [_entry("3200.00", 9), _entry("1600.00", 10), _entry("4000.00", 11)],
        RATES,
    )
    assert [c.month for c in after.corrections] == [10]
    assert after.to_next() is None


def test_flat_rate_before_the_amendment_year():
    status = rebate.summarize(2025, _terms(), [_entry("400000.00", 3)], RATES)
    assert status.rate_for(12).rate == Decimal("2.5")
    assert status.corrections == ()


def test_service_net_drops_rebate_and_travel_lines():
    words = ("podróż",)
    items = [
        {"name": "Usługi informatyczne — październik", "net": "1000.00"},
        {"name": "Refaktura: podróż służbowa", "net": "300.00"},
        {
            "name": "Rabat od obrotu rocznego 2,5% (umowa ramowa, rok 2026)",
            "net": "-25.00",
        },
    ]
    net, touched = rebate.service_net(Decimal("1275.00"), items, words)
    assert net == Decimal("1000.00") and touched is True
    # Korekta: liczy się różnica stanów po i przed.
    correction = [
        {"name": "Usługi", "net": "900.00"},
        {"name": "Rabat od obrotu rocznego 2,5%", "net": "-22.50"},
        {"name": "Usługi", "net": "1000.00", "before_correction": True},
        {
            "name": "Rabat od obrotu rocznego 2,5%",
            "net": "-25.00",
            "before_correction": True,
        },
    ]
    net, touched = rebate.service_net(Decimal("-97.50"), correction, words)
    assert net == Decimal("-100.00") and touched is False


def test_rebate_lines_one_per_vat_rate_without_travel():
    lines = [
        {"name": "Usługi A", "quantity": "160", "unit_price": "100", "vat_rate": "23"},
        {"name": "Usługi B", "quantity": "10", "unit_price": "50", "vat_rate": "np II"},
        {"name": "Podróż", "quantity": "1", "unit_price": "999", "vat_rate": "23"},
        {
            "name": "Rabat od obrotu rocznego 3% (stary)",
            "quantity": "1",
            "unit_price": "-1",
            "vat_rate": "23",
        },
    ]
    tier = rebate.Tier(None, Decimal("2.5"))
    out = rebate.rebate_lines(lines, tier, 2026, ("podróż",))
    assert [(line["vat_rate"], line["unit_price"]) for line in out] == [
        ("23", "-400.00"),
        ("np II", "-12.50"),
    ]
    assert all(rebate.is_rebate_line(line) for line in out)
    assert out[0]["name"] == "Rabat od obrotu rocznego 2,5% (umowa ramowa, rok 2026)"
    assert rebate.rebate_lines(lines, rebate.Tier(None, Decimal(0)), 2026, ()) == []


def test_corrections_reduce_turnover():
    status = rebate.summarize(
        2026, _terms(), [_entry("4000.00", 9), _entry("-4400.00", 10)], RATES
    )
    assert status.turnover == Decimal("-100.00")
    assert status.due == Decimal(0)
    assert status.rate_for(11).rate == Decimal("2.5")


def test_invoice_in_threshold_currency_counts_directly_and_missing_rate_is_flagged():
    status = rebate.summarize(
        2026,
        _terms(),
        [
            _entry("600.00", 9, "EUR"),
            rebate.Entry("PLN", Decimal("4000.00"), date(2026, 3, 2), 3),
        ],
        RATES,
    )
    assert status.turnover == Decimal("600.00")
    assert status.missing_fx == 1


def test_rate_boundary_is_the_day_before_sale():
    assert rebate.rate_boundary(date(2026, 10, 31), date(2026, 11, 3)) == DAY
    assert rebate.rate_boundary(None, date(2026, 10, 31)) == DAY


def test_payload_for_invoice_month():
    status = rebate.summarize(
        2026, _terms(), [_entry("3200.00", 9), _entry("1600.00", 10)], RATES
    )
    data = rebate.payload(status, month=10, on_invoice=Decimal("40.00"), currency="PLN")
    assert data["rate"] == "2.5" and data["next_rate"] == "3"
    assert data["turnover_before"] == "800.00"
    assert data["on_invoice"] == "40.00"
    assert data["corrections"] == [
        {
            "month": 10,
            "rate_diff": "0.5",
            "excess": "200.00",
            "amounts": [{"currency": "PLN", "amount": "4.00"}],
        }
    ]
    assert data["tiers"] == [
        {"up_to": "1000.00", "rate": "2.5"},
        {"up_to": None, "rate": "3"},
    ]
