"""Konta modułów w Ustawieniach Księgowości muszą przyjmować zapisy — reguły bez bazy.

Po imporcie pełnego planu kont z Symfonii domyślne konta (200, 229, 231, 401,
761) mają analitykę pod sobą, a 080 może nie istnieć — moduł odrzuciłby dekret
dopiero przy pracy. Zapis w Ustawieniach sprawdza to od razu, a ``/config``
pokazuje zapisane konta, które przestały być księgowalne. Konta fikcyjne.
"""

from __future__ import annotations

from app.services.ledger import engine
from app.services.ledger import settings as ledger_settings

PLAN = engine.plan_from_rows(
    [
        ("130", "Rachunki bankowe", "other", True, None),
        ("130-1", "Rachunek bieżący", "other", True, None),
        ("200", "Rozrachunki z odbiorcami", "settlement", True, None),
        ("200-1", "Odbiorcy krajowi", "settlement", True, "counterparty"),
        ("200-2", "Odbiorcy zagraniczni", "settlement", True, "counterparty"),
        ("202-1", "Dostawcy zagraniczni", "settlement", True, "counterparty"),
        ("221", "VAT naliczony", "vat", True, None),
        ("222", "VAT należny", "vat", True, None),
        ("225", "Rozrachunki z US", "other", True, None),
        ("229", "Rozrachunki z ZUS", "other", True, None),
        ("229-1", "ZUS — ubezpieczenia", "other", True, None),
        ("229-1-1", "ZUS — społeczne", "other", True, None),
        ("229-1-2", "ZUS — zdrowotne", "other", True, None),
        ("229-2", "ZUS — fundusze", "other", True, None),
        ("231", "Rozrachunki z tytułu wynagrodzeń", "other", True, None),
        ("231-10", "Wynagrodzenia — zarząd", "other", True, None),
        ("231-9", "Wynagrodzenia — zespół", "other", True, None),
        ("234", "Pozostałe rozrachunki", "other", True, "mpk"),
        ("401", "Amortyzacja", "cost", True, None),
        ("401-1", "Amortyzacja — wyłączone", "cost", False, None),
        ("490", "Rozliczenie kosztów", "other", True, None),
        ("761", "Pozostałe koszty operacyjne", "other", False, None),
    ]
)


def test_synthetic_account_is_refused_with_first_postable_analytic():
    problem = ledger_settings.account_problem("229", PLAN)
    assert problem == "konto 229 ma konta analityczne — wybierz np. 229-1-1."


def test_hint_sorts_analytics_by_number_not_text():
    problem = ledger_settings.account_problem("231", PLAN)
    assert "np. 231-9." in problem


def test_synthetic_account_with_only_inactive_analytics_has_no_example():
    problem = ledger_settings.account_problem("401", PLAN)
    assert problem == "konto 401 ma konta analityczne — wybierz konto analityczne."


def test_dictionary_account_is_refused_for_single_account_field():
    problem = ledger_settings.account_problem("234", PLAN)
    assert "prowadzi analitykę (MPK)" in problem


def test_missing_and_disabled_accounts_are_refused():
    assert ledger_settings.account_problem("080", PLAN) == (
        "konta 080 nie ma w planie kont."
    )
    assert ledger_settings.account_problem("761", PLAN) == (
        "konto 761 jest wyłączone w planie kont."
    )


def test_postable_accounts_pass():
    for number in ("229-1-1", "130-1", "490", "222"):
        assert ledger_settings.account_problem(number, PLAN) is None
    # Analityka słownika (konto jednego kontrahenta) też przyjmuje zapisy.
    assert ledger_settings.account_problem("200-1-77", PLAN) is None


def test_counterparty_field_needs_counterparty_dictionary():
    problem = ledger_settings.account_problem("200", PLAN, counterparty=True)
    assert problem is not None
    assert "200-ID kontrahenta" in problem and "np. 200-1" in problem
    assert ledger_settings.account_problem("200-1", PLAN, counterparty=True) is None


def test_counterparty_field_without_candidate_asks_for_dictionary():
    problem = ledger_settings.account_problem("490", PLAN, counterparty=True)
    assert "słownik analityki „kontrahenci”" in problem
    assert ledger_settings.account_problem("999", PLAN, counterparty=True) == (
        "konta 999 nie ma w planie kont."
    )


def test_counterparty_field_refuses_other_dictionary():
    problem = ledger_settings.account_problem("234", PLAN, counterparty=True)
    assert "nie prowadzi słownika kontrahentów" in problem


def test_problems_list_defaults_after_full_plan_import():
    """Domyślne konta modułów na pełnym planie: lista mówi, co przestawić."""

    settings = ledger_settings.normalize(None)
    found = {
        (item["group"], item["field"]): item
        for item in ledger_settings.account_problems(settings, PLAN)
    }
    assert set(found) == {
        ("sales", "receivable_account"),
        ("payroll", "settlement_account"),
        ("payroll", "zus_account"),
        ("assets", "intake_account"),
        ("assets", "disposal_account"),
        ("bank", "zus_account"),
    } | {
        ("assets", f"cost_map.{source}")
        for source, _ in ledger_settings.DEFAULT_COST_MAP
    }
    # Domyślna mapa umorzeń wskazuje 400-x, których w tym planie nie ma.
    mapped = found[("assets", "cost_map.070-3")]
    assert (mapped["account"], mapped["label"]) == (
        "400-4",
        "Amortyzacja dla umorzenia 070-3",
    )
    # Konto dla umorzeń spoza mapy jest domyślnie puste — nie jest problemem.
    assert ("assets", "cost_account") not in found
    receivable = found[("sales", "receivable_account")]
    assert receivable["account"] == "200"
    assert receivable["group_label"] == "Ustawienia → Konta faktur sprzedaży"
    assert "np. 200-1" in receivable["problem"]
    # Puste pola (konto przychodów bez wartości) nie są problemem tej listy.
    assert ("sales", "revenue_account") not in found


def test_problems_list_is_empty_when_accounts_are_postable():
    settings = ledger_settings.normalize(
        {
            "sales": {"receivable_account": "200-1", "vat_account": "222"},
            "payroll": {"settlement_account": "231-9", "zus_account": "229-2"},
            "assets": {
                "cost_account": "490",
                "intake_account": "130-1",
                "disposal_account": "490",
                "cost_map": [["229", "490"]],
            },
            "bank": {
                "zus_account": "229-1-2",
                "pit_account": "225",
                "accounts": [{"number": "1" * 26, "account": "130-1"}],
            },
            "vat": {"foreign_account": "202-1"},
        }
    )
    assert ledger_settings.account_problems(settings, PLAN) == []


def test_problems_list_covers_company_bank_accounts():
    settings = ledger_settings.normalize(
        {
            "sales": {"receivable_account": "200-1"},
            "payroll": {"settlement_account": "231-9", "zus_account": "229-2"},
            "assets": {
                "cost_account": "490",
                "intake_account": "130-1",
                "disposal_account": "490",
                "cost_map": [],
            },
            "bank": {
                "zus_account": "229-2",
                "accounts": [{"number": "1" * 26, "account": "130", "name": "Główny"}],
            },
        }
    )
    problems = ledger_settings.account_problems(settings, PLAN)
    assert [(item["field"], item["label"], item["account"]) for item in problems] == [
        ("accounts.1", "Rachunek Główny", "130")
    ]


def test_saved_cost_map_replaces_default_and_bad_pairs_are_dropped():
    settings = ledger_settings.normalize(
        {"assets": {"cost_map": [["070-3", "400-4"], ["07*0", "400"], "070", []]}}
    )
    assert settings.assets.cost_map == (("070-3", "400-4"),)
    assert ledger_settings.normalize(None).assets.cost_map == (
        ledger_settings.DEFAULT_COST_MAP
    )
    assert ledger_settings.to_json(settings)["assets"]["cost_map"] == [
        ["070-3", "400-4"]
    ]


def test_cost_for_takes_longest_matching_depreciation_account():
    accounts = ledger_settings.AssetsAccounts(
        cost_map=(("070", "400-6"), ("070-3", "400-4"), ("075", "400-1"))
    )
    assert accounts.cost_for("070-3") == "400-4"
    assert accounts.cost_for("070-3-1") == "400-4"
    assert accounts.cost_for("070-5") == "400-6"
    assert accounts.cost_for("075-3") == "400-1"
    # 0750 to inne konto niż 075 — porównujemy segmenty numeru, nie tekst.
    assert accounts.cost_for("0750") is None
    fallback = ledger_settings.AssetsAccounts(cost_account="409-1", cost_map=())
    assert fallback.cost_for("070-3") == "409-1"


def test_revenue_account_may_stay_empty_but_not_others():
    assert "revenue_account" in ledger_settings.SALES_OPTIONAL
    assert ledger_settings.normalize({"sales": {"revenue_account": ""}}).sales == (
        ledger_settings.SalesAccounts(revenue_account="")
    )
