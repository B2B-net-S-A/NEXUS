"""Katalog reguł: wartości domyślne, nadpisania z bazy, walidacja zapisu."""

from __future__ import annotations

import pytest

from app.services.client_settlements import rules_catalog as catalog


def test_klient_bez_regul_ma_wszystko_wylaczone():
    rules = catalog.effective(None)
    assert set(rules) == set(catalog.RULES)
    assert {r["level"] for r in rules.values()} == {"off"}


def test_nadpisanie_poziomu_i_parametru_reszta_z_katalogu():
    rules = catalog.effective(
        {"extra.multiplier": {"level": "block", "params": {"pct": "120", "obcy": "x"}}}
    )
    assert rules["extra.multiplier"] == {"level": "block", "params": {"pct": "120"}}
    assert rules["fields.md_hours"]["level"] == catalog.RULES["fields.md_hours"].level


def test_wycofany_klucz_i_zly_poziom_nie_psuja_odczytu():
    rules = catalog.effective(
        {"stara.regula": {"level": "block"}, "proof.month": {"level": "zawsze"}}
    )
    assert "stara.regula" not in rules
    assert rules["proof.month"]["level"] == catalog.RULES["proof.month"].level


def test_zapis_odrzuca_nieznany_klucz_poziom_i_za_dlugi_parametr():
    with pytest.raises(catalog.RulesError):
        catalog.clean_for_save([{"key": "nie.ma", "level": "off"}])
    with pytest.raises(catalog.RulesError):
        catalog.clean_for_save([{"key": "proof.month", "level": "zawsze"}])
    with pytest.raises(catalog.RulesError):
        catalog.clean_for_save(
            [
                {
                    "key": "proof.signed_pdf",
                    "level": "block",
                    "params": {"issuer": "x" * 300},
                }
            ]
        )


def test_zapis_przycina_i_bierze_tylko_znane_parametry():
    out = catalog.clean_for_save(
        [
            {
                "key": "proof.signed_pdf",
                "level": "block",
                "params": {"issuer": "  Bank  ", "inny": "x"},
            }
        ]
    )
    assert out == {"proof.signed_pdf": {"level": "block", "params": {"issuer": "Bank"}}}


def test_ekran_ma_wszystkie_sekcje_i_pola():
    screen = catalog.as_screen(catalog.effective(None))
    assert [s["key"] for s in screen] == [s.key for s in catalog.SECTIONS]
    onboarding = next(
        r for s in screen for r in s["rules"] if r["key"] == "order.onboarding_md"
    )
    assert [f["key"] for f in onboarding["param_fields"]] == ["md", "item"]


E6_RULES = {
    "proof.accept_has_hours",
    "fields.md_month_limit",
    "travel.extra_costs_confirm",
    "pay.after_client_signature",
    "pay.mail_accept_fallback",
    "pay.per_person",
    "cl.extra_costs_on_invoice",
    "cl.client_document",
    "cl.after_signed_document",
    "cl.send_to",
}


def test_reguly_z_odpowiedzi_rozliczen_czekaja_na_e6():
    """Odpowiedzi z 12.11 (E0.3): reguły da się ustawić, silnik ich nie sprawdza."""

    assert E6_RULES <= set(catalog.RULES)
    assert {catalog.RULES[k].stage for k in E6_RULES} == {"E6"}
    payment = next(s for s in catalog.SECTIONS if s.key == "payment")
    assert {r.key for r in payment.rules} == {
        "pay.after_client_signature",
        "pay.mail_accept_fallback",
        "pay.per_person",
    }


def test_koszty_dodatkowe_nie_blokuja_same_a_adres_wysylki_jest_pusty():
    assert catalog.RULES["travel.extra_costs_confirm"].level != "block"
    assert catalog.RULES["cl.send_to"].params == {"email": ""}
    rules = catalog.effective({})
    assert rules["travel.extra_costs_confirm"]["level"] != "block"
