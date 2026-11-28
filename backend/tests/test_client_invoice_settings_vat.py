"""Stawka VAT szkicu przy nadpisaniu u klienta z dwoma nabywcami (28.11.2026).

Ekran ustawień zapisuje klientowi stawkę domyślną 23 przy dodaniu; drugi nabywca
z UE (spółka zagraniczna klienta) musi mimo to dostać „np II”. Dane zmyślone.
"""

from app.services.client_invoicing import issue_settings


def _settings(vat_rate=None):
    data = issue_settings.normalize({})
    if vat_rate is not None:
        data["clients"]["7"] = {"vat_rate": vat_rate}
    return data


def test_domestic_override_does_not_apply_to_eu_buyer():
    data = _settings("23")
    assert issue_settings.client_vat(data, 7, eu_buyer=False) == "23"
    assert issue_settings.client_vat(data, 7, eu_buyer=True) == "np II"


def test_foreign_override_still_applies_to_eu_buyer():
    data = _settings("np I")
    assert issue_settings.client_vat(data, 7, eu_buyer=True) == "np I"


def test_reverse_charge_override_does_not_apply_to_domestic_buyer():
    data = _settings("np II")
    assert issue_settings.client_vat(data, 7, eu_buyer=True) == "np II"
    assert issue_settings.client_vat(data, 7, eu_buyer=False) == data["default_vat"]


def test_without_override_defaults_stay():
    data = _settings()
    assert issue_settings.client_vat(data, 7, eu_buyer=True) == "np II"
    assert issue_settings.client_vat(data, 7, eu_buyer=False) == data["default_vat"]
