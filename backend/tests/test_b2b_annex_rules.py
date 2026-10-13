"""Rejestr aneksów — reguły czyste (bez bazy).

Data wejścia aneksu w życie i jego stan są liczone RAZ, na serwerze: rejestr
aneksów, etykieta w „Umowach bieżących” i zakładka „Aneksy” kontraktu muszą
mówić to samo, co ``effects.apply`` zapisuje w aneksie kontraktu.
"""

from datetime import date

from app.services.b2b_documents.annex_summary import annex_change
from app.services.b2b_documents.effects import (
    ANNEX_STATES,
    annex_effective_date,
    annex_state,
)

DOC_DATE = date(2026, 10, 10)


# ── data wejścia w życie ─────────────────────────────────────────────────────


def test_rate_annex_takes_the_earliest_step_of_this_contracts_client():
    values = {
        "effective_date": "2026-11-01",
        "rate_items": [
            {"rate": 150, "from": "2027-01-01", "client_id": 7},
            {"rate": 140, "from": "2026-12-01", "client_id": 9},
        ],
    }
    # Krok innego klienta nie zmienia tego kontraktu — nie on wyznacza datę.
    assert annex_effective_date(
        "annex_rate_change", values, DOC_DATE, contract_client_id=7
    ) == date(2027, 1, 1)
    # Bez kontraktu (aneks jeszcze niepowiązany): najwcześniejszy krok.
    assert annex_effective_date("annex_rate_change", values, DOC_DATE) == date(
        2026, 12, 1
    )


def test_rate_step_without_its_own_date_starts_with_the_annex():
    values = {
        "effective_date": "2026-11-01",
        "rate_items": [{"rate": 150}, {"rate": 160, "from": "2027-01-01"}],
    }
    assert annex_effective_date(
        "annex_rate_change", values, DOC_DATE, contract_client_id=7
    ) == date(2026, 11, 1)


def test_rate_annex_without_a_step_for_this_client_keeps_the_earliest_step():
    values = {
        "effective_date": "2026-11-01",
        "rate_items": [{"rate": 150, "from": "2026-12-01", "client_id": 9}],
    }
    assert annex_effective_date(
        "annex_rate_change", values, DOC_DATE, contract_client_id=7
    ) == date(2026, 12, 1)


def test_rate_annex_from_before_the_annex_generator_has_one_rate():
    values = {"new_rate": "150", "effective_date": "2026-11-01"}
    assert annex_effective_date("annex_rate_change", values, DOC_DATE) == date(
        2026, 11, 1
    )
    assert annex_effective_date("annex_rate_change", {"new_rate": "150"}, DOC_DATE) == (
        DOC_DATE
    )


def test_start_date_annex_takes_the_new_start_date():
    # Pole „Data wejścia zmian w życie” formularza nie trafia do kontraktu —
    # aneks kontraktu dostaje nową datę rozpoczęcia.
    values = {"effective_date": "2026-10-15", "new_start_date": "2026-11-16"}
    assert annex_effective_date("annex_start_date", values, DOC_DATE) == date(
        2026, 11, 16
    )


def test_other_annexes_take_the_effective_date_then_the_document_date():
    for key in ("annex_party_data", "annex_subcontractor", "annex_mandate"):
        assert annex_effective_date(
            key, {"effective_date": "2026-11-01"}, DOC_DATE
        ) == date(2026, 11, 1)
        assert annex_effective_date(key, {}, DOC_DATE) == DOC_DATE
    assert annex_effective_date("annex_start_date", {}, DOC_DATE) == DOC_DATE


# ── stan ─────────────────────────────────────────────────────────────────────


def test_state_names_are_the_four_from_the_register():
    assert ANNEX_STATES == ("waiting", "signed_pending", "in_force", "cancelled")


def test_unsigned_annex_waits_for_signature():
    assert (
        annex_state(
            status="issued",
            signature_status="unsigned",
            effective=date(2026, 11, 1),
            today=date(2026, 12, 1),
        )
        == "waiting"
    )


def test_signed_annex_is_pending_until_its_effective_day():
    signed = {"status": "signed", "signature_status": "signed_both"}
    day = date(2026, 11, 16)
    assert annex_state(**signed, effective=day, today=date(2026, 11, 15)) == (
        "signed_pending"
    )
    # W dniu wejścia w życie aneks już obowiązuje.
    assert annex_state(**signed, effective=day, today=day) == "in_force"
    assert annex_state(**signed, effective=None, today=day) == "in_force"


# ── skrót zmiany na liście ───────────────────────────────────────────────────


def test_rate_change_shows_amounts_only_to_people_who_see_rates():
    values = {
        "rate_items": [{"rate": "150", "from": "2026-11-01", "client_id": 7}],
        "effective_date": "2026-11-01",
    }
    hidden = annex_change("annex_rate_change", values, rates_visible=False)
    assert hidden == {"kind": "rate", "hidden": True}

    shown = annex_change(
        "annex_rate_change",
        values,
        rates_visible=True,
        rates_before=[{"rate": 140.0, "from": None, "to": None}],
    )
    assert shown["hidden"] is False
    assert shown["currency"] == "PLN"
    assert [item["rate"] for item in shown["items"]] == [150.0]
    assert [item["rate"] for item in shown["before"]] == [140.0]


def test_rate_change_from_before_the_annex_generator_has_one_item():
    shown = annex_change("annex_rate_change", {"new_rate": "165"}, rates_visible=True)
    assert [item["rate"] for item in shown["items"]] == [165.0]
    assert shown["before"] == []


def test_other_annexes_summarise_what_the_document_says():
    assert annex_change(
        "annex_start_date",
        {"current_start_date": "2026-11-02", "new_start_date": "2026-11-16"},
        rates_visible=False,
    ) == {"kind": "start_date", "before": "2026-11-02", "after": "2026-11-16"}
    assert annex_change(
        "annex_party_data",
        {"new_legal_name": " ZAJĄC IT ", "new_nip": "521-390-00-11"},
        rates_visible=False,
    ) == {"kind": "party", "legal_name": "ZAJĄC IT", "nip": "5213900011"}
    assert annex_change(
        "annex_subcontractor", {"delegate_name": "Paweł Sowa"}, rates_visible=False
    ) == {"kind": "delegate", "name": "Paweł Sowa"}
    mandate = annex_change(
        "annex_mandate",
        {"period_from": "2026-10-01", "change_rate": True, "rate_gross": "80"},
        rates_visible=False,
    )
    # Aneks zlecenia mówi tylko, że stawka się zmienia — bez kwoty.
    assert mandate == {
        "kind": "mandate",
        "period_from": "2026-10-01",
        "period_to": None,
        "rate_changed": True,
    }
    assert annex_change("termination_agreement", {}, rates_visible=True) is None


def test_cancelled_annex_stays_cancelled_whatever_the_signature_says():
    assert (
        annex_state(
            status="cancelled",
            signature_status="signed_both",
            effective=date(2026, 11, 1),
            today=date(2026, 12, 1),
        )
        == "cancelled"
    )
