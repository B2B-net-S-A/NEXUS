"""Ostrzeżenia osoby od systemu (27.10.2026) — bez bazy.

Analiza 133 odrzuceń z 23–27.10: osoby 15–25% nad budżetem szły dalej tak
rzadko jak te ponad 25% (12% wobec 15%), więc próg twardy spada do 15%.
Osoba, która według profilu przyjmie mniej dni w biurze, niż chce klient,
chce wyłącznie zdalnie albo mieszka w innym mieście przy pracy z biurem,
szła dalej o połowę rzadziej (18% wobec 36%) — system dodaje ją za resztą
i zapisuje w migawce, co wiedział, a karta mówi to rekruterowi.
"""

from decimal import Decimal
from types import SimpleNamespace

from app.services import new_column_autofill as autofill
from app.services.location_utils import location_tokens
from app.services.process_entry_meta import autofill_badge

_GDYNIA = frozenset(location_tokens("Gdynia"))


def _person(**kw):
    base = {
        "max_onsite_days_per_week": None,
        "accepts_more_office_days": None,
        "preferences": None,
        "location": None,
        "city": None,
        "cv_extracted_data": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def test_hard_budget_cut_is_15_percent():
    tier = autofill._rate_tier
    assert tier(Decimal("115"), "PLN", consents=False, budget_hourly=100) == 1
    assert tier(Decimal("116"), "PLN", consents=False, budget_hourly=100) is None


def test_budget_caution_names_the_percent_over():
    assert autofill.budget_caution(Decimal("112"), "PLN", budget_hourly=95) == {
        "key": "budget",
        "over_pct": 18,
        "rate": 112.0,
        "budget": 95.0,
    }
    assert autofill.budget_caution(Decimal("95"), "PLN", budget_hourly=95) is None
    assert autofill.budget_caution(None, None, budget_hourly=95) is None
    assert autofill.budget_caution(Decimal("130"), "EUR", budget_hourly=95) is None


def test_fewer_office_days_than_the_client_wants():
    person = _person(max_onsite_days_per_week=1)
    assert autofill.office_cautions(
        person, office_days=3, office_tokens=_GDYNIA, office_label="Gdynia"
    ) == [{"key": "office_days", "candidate_days": 1, "required_days": 3}]


def test_consent_to_more_office_days_is_no_caution():
    person = _person(max_onsite_days_per_week=1, accepts_more_office_days=True)
    assert (
        autofill.office_cautions(
            person, office_days=3, office_tokens=_GDYNIA, office_label="Gdynia"
        )
        == []
    )


def test_remote_only_profile():
    person = _person(preferences={"remote_modes": ["remote"]})
    assert autofill.office_cautions(
        person, office_days=2, office_tokens=_GDYNIA, office_label="Gdynia"
    ) == [{"key": "remote_only", "required_days": 2}]


def test_other_city_with_office_days():
    person = _person(city="Kraków")
    assert autofill.office_cautions(
        person, office_days=3, office_tokens=_GDYNIA, office_label="Gdynia"
    ) == [
        {"key": "office_city", "city": "Kraków", "office": "Gdynia", "required_days": 3}
    ]


def test_unknown_or_remote_job_is_no_caution():
    assert (
        autofill.office_cautions(
            _person(), office_days=3, office_tokens=_GDYNIA, office_label="Gdynia"
        )
        == []
    )
    assert (
        autofill.office_cautions(
            _person(city="Kraków", max_onsite_days_per_week=0),
            office_days=0,
            office_tokens=_GDYNIA,
            office_label="Gdynia",
        )
        == []
    )


def _meta(cautions):
    return {
        "kind": "autofill",
        "score": 71.3,
        "matched_must": ["Java"],
        "missing_must": [],
        "rate_from_hourly": 112.0,
        "availability_date": None,
        "cautions": cautions,
    }


def test_badge_turns_cautions_into_labels():
    badge = autofill_badge(
        _meta(
            [
                {"key": "budget", "over_pct": 18, "rate": 112.0, "budget": 95.0},
                {"key": "office_days", "candidate_days": 1, "required_days": 2},
                {"key": "remote_only", "required_days": 3},
                {
                    "key": "office_city",
                    "city": "Kraków",
                    "office": "Warszawa",
                    "required_days": 2,
                },
            ]
        ),
        waiting_days=None,
    )
    assert badge["cautions"] == [
        {
            "key": "budget",
            "label": "+18% budżetu",
            "title": "„Stawka od” 112 zł/h, budżet 95 zł/h.",
        },
        {
            "key": "office_days",
            "label": "Biuro: 1 z 2 dni",
            "title": "Według profilu przyjmie 1 dzień w biurze w tygodniu, klient chce 2 dni.",
        },
        {
            "key": "remote_only",
            "label": "Tylko zdalnie",
            "title": "Według profilu albo notatek chce pracować wyłącznie zdalnie, klient chce 3 dni w biurze w tygodniu.",
        },
        {
            "key": "office_city",
            "label": "Inne miasto: Kraków",
            "title": "Mieszka: Kraków. Biuro klienta: Warszawa, 2 dni w tygodniu.",
        },
    ]


def test_badge_skips_unknown_or_broken_cautions():
    badge = autofill_badge(
        _meta([{"key": "nowy"}, "zle", {"key": "budget", "over_pct": "x"}]),
        waiting_days=None,
    )
    assert badge["cautions"] == []
    assert autofill_badge(_meta(None), waiting_days=None)["cautions"] == []
