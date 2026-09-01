"""Dealbreaker-switche — kontrakty „nieznany przechodzi" i twardego sufitu.

Każda asercja o przechodzeniu nieznanych jest tu ŻELAZNA: filtr stażu przy
pokryciu 1,2% zredukował kiedyś lejek 11 091 → 45. Sufit budżetu jest TWARDY
i bez marginesu z decyzji produktowej 19.08 — pomiar z 18.08 (0% marginesu
ukrywa 44% realnie dowiezionych, bo stawki negocjuje się w dół) został przy
tej decyzji świadomie zaakceptowany; NIE przywracaj marginesu bez decyzji
właściciela produktu.
"""

from types import SimpleNamespace

from app.services.dealbreaker_filters import (
    apply_dealbreakers,
    budget_excludes,
    remote_only_refuses_office,
    resolve_job_budget_hourly,
)
from app.services.location_utils import candidate_location_tokens


def _cand(**kw):
    base = dict(
        expected_rate_hourly=None,
        expected_rate_currency=None,
        cv_extracted_data=None,
        location=None,
        city=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _notes(**prefs_kw):
    prefs = {
        "other": None,
        "locations": [],
        "remote_only": None,
        "sectors_avoid": [],
        "sectors_prefer": [],
    }
    prefs.update(prefs_kw)
    return {"_notes_insights": {"preferences": prefs}}


# ── budżet ───────────────────────────────────────────────────────────────────


def test_unknown_rate_always_passes():
    assert budget_excludes(_cand(), 100.0) is False
    # Niekanoniczna waluta = „nie wiemy", nie „za drogo".
    eur = _cand(expected_rate_hourly=500, expected_rate_currency="EUR")
    assert budget_excludes(eur, 100.0) is False


def test_hard_cap_is_strict_and_equal_passes():
    """Wpisana stawka = twardy sufit: powyżej ukryty, RÓWNY przechodzi."""
    over = _cand(expected_rate_hourly=101, expected_rate_currency="PLN")
    assert budget_excludes(over, 100.0) is True
    equal = _cand(expected_rate_hourly=100, expected_rate_currency="PLN")
    assert budget_excludes(equal, 100.0) is False
    under = _cand(expected_rate_hourly=99, expected_rate_currency="PLN")
    assert budget_excludes(under, 100.0) is False


def test_no_margin_is_ever_applied():
    """130 przy budżecie 100 jest UKRYTY — dawny margines +30% nie wraca."""
    cand = _cand(expected_rate_hourly=130, expected_rate_currency="PLN")
    assert budget_excludes(cand, 100.0) is True


def test_resolve_budget_prefers_explicit_field(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "CHAMPION_MATCH_SIGNALS_ENABLED", True, raising=False)
    job = SimpleNamespace(rate_budget_hourly=140, champion_profile={"rate_value": 999})
    assert resolve_job_budget_hourly(job) == 140.0
    fallback = SimpleNamespace(
        rate_budget_hourly=None, champion_profile={"rate_value": 120}
    )
    assert resolve_job_budget_hourly(fallback) == 120.0


def test_budget_filter_is_automatic_by_default():
    """Sama obecność budżetu aktywuje sufit — bez osobnego uzbrajania."""
    over = _cand(expected_rate_hourly=200, expected_rate_currency="PLN")
    res = apply_dealbreakers([over], budget_hourly=100.0)
    assert res.kept == [] and res.hidden_over_budget == 1


def test_apply_without_budget_is_noop():
    """Brak znanego budżetu oferty nie ukrywa nikogo (brak danych ≠ powód)."""
    cand = _cand(expected_rate_hourly=999, expected_rate_currency="PLN")
    res = apply_dealbreakers([cand], budget_hourly=None)
    assert res.kept == [cand] and res.hidden_over_budget == 0


def test_explicit_opt_out_shows_over_budget():
    """Konsument może jawnie wyłączyć sufit (widok „pokaż wszystkich")."""
    over = _cand(expected_rate_hourly=999, expected_rate_currency="PLN")
    res = apply_dealbreakers([over], exclude_over_budget=False, budget_hourly=100.0)
    assert res.kept == [over]


# ── biuro (remote_only z notatek) ────────────────────────────────────────────


def test_remote_only_true_excludes_false_and_none_pass():
    assert remote_only_refuses_office(_cand(cv_extracted_data=_notes(remote_only=True)))
    assert not remote_only_refuses_office(
        _cand(cv_extracted_data=_notes(remote_only=False))
    )
    assert not remote_only_refuses_office(_cand(cv_extracted_data=_notes()))
    assert not remote_only_refuses_office(_cand())  # brak notatek
    # cv_extracted_data bywa LISTĄ na prodzie — nie może się wywrócić.
    assert not remote_only_refuses_office(_cand(cv_extracted_data=["legacy"]))


def test_apply_counts_and_order_are_deterministic():
    over = _cand(
        expected_rate_hourly=200,
        expected_rate_currency="PLN",
        cv_extracted_data=_notes(remote_only=True),  # łapie OBA powody
    )
    remote = _cand(cv_extracted_data=_notes(remote_only=True))
    ok = _cand(expected_rate_hourly=90, expected_rate_currency="PLN")
    res = apply_dealbreakers(
        [over, remote, ok],
        budget_hourly=100.0,
        exclude_remote_only=True,
    )
    assert res.kept == [ok]
    # Budżet liczony PRZED biurem — kandydat z oboma powodami nie migruje.
    assert res.hidden_over_budget == 1
    assert res.hidden_remote_only == 1
    assert res.hidden_meta() == {"over_budget": 1, "remote_only": 1}


# ── źródła lokalizacji ───────────────────────────────────────────────────────


def test_location_sources_cv_notes_all():
    cand = _cand(
        city="Kraków",
        location="Kraków, małopolskie",
        cv_extracted_data={
            "_notes_insights": {
                "preferences": {"locations": ["Poznań"], "remote_only": None},
                "relocation": {"willing": True, "targets": ["Wrocław"]},
            }
        },
    )
    cv = candidate_location_tokens(cand, "cv")
    notes = candidate_location_tokens(cand, "notes")
    both = candidate_location_tokens(cand, "all")
    assert "kraków" in cv and "poznań" not in cv
    assert {"poznań", "wrocław"} <= notes and "kraków" not in notes
    assert {"kraków", "poznań", "wrocław"} <= both


def test_relocation_unwilling_targets_are_not_locations():
    cand = _cand(
        cv_extracted_data={
            "_notes_insights": {
                "preferences": {"locations": []},
                "relocation": {"willing": False, "targets": ["Berlin"]},
            }
        }
    )
    assert "berlin" not in candidate_location_tokens(cand, "notes")


def test_location_sources_survive_list_shaped_extracted_data():
    cand = _cand(city="Łódź", cv_extracted_data=["legacy", "list"])
    assert "łódź" in candidate_location_tokens(cand, "all")
    assert candidate_location_tokens(cand, "notes") == set()


# ── kontrakt API radaru: budżet aktywuje się sam, margines nie istnieje ──────


def test_radar_budget_presence_is_the_whole_contract():
    from app.api.talent_radar import TalentRadarSearchRequest

    req = TalentRadarSearchRequest(client_id=1, text="x", budget_hourly_max=150)
    assert req.budget_hourly_max == 150.0
    # Decyzja 19.08: bez marginesu i bez osobnego przełącznika — pola nie
    # mogą wrócić do modelu cichym refaktorem.
    assert "budget_margin_pct" not in TalentRadarSearchRequest.model_fields
    assert "exclude_over_budget" not in TalentRadarSearchRequest.model_fields
