"""Rabat roczny od obrotu klienta (``client_invoicing/rebate.py``) — bez bazy.

Decyzje Artura 16.11.2026: stawka progu dotyczy CAŁEGO obrotu roku, progi
z aneksu obowiązują od roku jego wejścia, próg w innej walucie po kursie NBP
z każdej faktury, rozliczenie zbiorczą korektą do 31.01. Kwoty fikcyjne.
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


def _entry(net: str, currency: str = "PLN", *names: str) -> rebate.Entry:
    return rebate.Entry(
        currency, Decimal(net), DAY, tuple({"name": name} for name in names)
    )


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


# ── Próg i stawka od całego obrotu ──────────────────────────────────────────


def test_threshold_is_inclusive_and_rate_covers_whole_turnover():
    tiers = rebate.tiers_for(_terms(), 2026)
    assert rebate.tier_for(Decimal("1000.00"), tiers).rate == Decimal("2.5")
    assert rebate.tier_for(Decimal("1000.01"), tiers).rate == Decimal(3)
    assert rebate.tier_for(Decimal("-50"), tiers).rate == Decimal("2.5")


def test_crossing_the_threshold_moves_whole_year_from_2_5_to_3_percent():
    terms = _terms()
    # 4 000 PLN / 4,00 = 1 000 EUR → jeszcze 2,5%.
    below = rebate.summarize(2026, terms, [_entry("4000.00")], RATES)
    assert below.turnover == Decimal("1000.00")
    assert below.tier.rate == Decimal("2.5")
    assert below.next_tier.rate == Decimal(3)
    assert below.to_next == Decimal("0.00")
    assert [(t.currency, t.rebate) for t in below.totals] == [
        ("PLN", Decimal("100.00"))
    ]

    # Jeszcze 4 PLN → 1 001 EUR: 3% od CAŁEGO obrotu, nie tylko od nadwyżki.
    above = rebate.summarize(2026, terms, [_entry("4000.00"), _entry("4.00")], RATES)
    assert above.tier.rate == Decimal(3)
    assert above.next_tier is None and above.to_next is None
    assert [(t.currency, t.net, t.rebate) for t in above.totals] == [
        ("PLN", Decimal("4004.00"), Decimal("120.12"))
    ]
    assert above.settle_by == date(2027, 1, 31)


def test_flat_rate_before_the_amendment_year():
    status = rebate.summarize(2025, _terms(), [_entry("400000.00")], RATES)
    assert status.tier.rate == Decimal("2.5")
    assert status.totals[0].rebate == Decimal("10000.00")


def test_corrections_reduce_turnover_and_negative_total_gives_no_rebate():
    status = rebate.summarize(
        2026, _terms(), [_entry("4000.00"), _entry("-4400.00")], RATES
    )
    assert status.turnover == Decimal("-100.00")
    assert status.totals[0].rebate == Decimal("0.00")


def test_travel_invoices_are_outside_turnover():
    status = rebate.summarize(
        2026,
        _terms(),
        [
            _entry("4000.00", "PLN", "Usługi informatyczne — październik"),
            _entry("900000.00", "PLN", "Refaktura kosztów podróży", "PODRÓŻ służbowa"),
            # Mieszana faktura (usługa + podróż) zostaje w obrocie.
            _entry("8.00", "PLN", "Usługi informatyczne", "Podróż"),
        ],
        RATES,
    )
    assert status.excluded == 1
    assert status.invoices == 2
    assert status.turnover == Decimal("1002.00")


def test_invoice_in_threshold_currency_counts_directly_and_missing_rate_is_flagged():
    other_day = date(2026, 3, 2)
    status = rebate.summarize(
        2026,
        _terms(),
        [
            _entry("600.00", "EUR"),
            rebate.Entry("PLN", Decimal("4000.00"), other_day),  # brak kursu tego dnia
        ],
        RATES,
    )
    assert status.turnover == Decimal("600.00")
    assert status.missing_fx == 1
    # Rabat w walucie faktury liczy się mimo braku kursu (kurs dotyczy tylko progu).
    assert {t.currency: t.rebate for t in status.totals} == {
        "EUR": Decimal("15.00"),
        "PLN": Decimal("100.00"),
    }


def test_rate_boundary_is_the_day_before_sale():
    assert rebate.rate_boundary(date(2026, 10, 31), date(2026, 11, 3)) == DAY
    assert rebate.rate_boundary(None, date(2026, 10, 31)) == DAY


def test_payload_shows_this_invoice_share():
    status = rebate.summarize(2026, _terms(), [_entry("8000.00")], RATES)
    data = rebate.payload(status, invoice_net=Decimal("1000.00"), currency="PLN")
    assert data["rate"] == "3"
    assert data["this_invoice"] == "30.00"
    assert data["tiers"] == [
        {"up_to": "1000.00", "rate": "2.5"},
        {"up_to": None, "rate": "3"},
    ]
    assert data["settle_by"] == "2027-01-31"
    assert (
        rebate.payload(status, invoice_net=None, currency="PLN")["this_invoice"] is None
    )
