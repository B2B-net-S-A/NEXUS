"""Przypomnienia o brakującym raporcie godzin: czyste reguły (bez bazy).

Harmonogram dni roboczych, kto może dostać mail, kolejność opiekunów i treść.
Dane fikcyjne — repo jest publiczne.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.services.client_settlements import reminders
from app.services.consultant_portal.portal_settings import PortalSettings


def test_trzeci_piaty_i_siodmy_dzien_roboczy_grudnia() -> None:
    # 1.12.2026 to wtorek: 3. dzień = czwartek 3.12, 5. = poniedziałek 7.12.
    assert reminders.step_for(date(2026, 12, 3)) == "day3"
    assert reminders.step_for(date(2026, 12, 7)) == "day5"
    assert reminders.step_for(date(2026, 12, 9)) == "day7"
    assert reminders.step_for(date(2026, 12, 4)) is None
    assert reminders.schedule("2026-11") == {
        "day3": "2026-12-03",
        "day5": "2026-12-07",
        "day7": "2026-12-09",
    }


def test_weekend_i_swieto_nie_sa_dniem_przypomnienia() -> None:
    assert reminders.business_day_number(date(2026, 12, 5)) is None  # sobota
    # Styczeń 2027: 1.01 i 6.01 to święta, więc 3. dzień roboczy to 7.01.
    assert reminders.business_day_number(date(2027, 1, 6)) is None
    assert reminders.step_for(date(2027, 1, 7)) == "day3"
    assert reminders.period_for(date(2027, 1, 7)) == "2026-12"


def _state(state: str, *activated: int) -> PortalSettings:
    return PortalSettings(state=state, activated_contract_ids=frozenset(activated))


@pytest.mark.parametrize("state", ["off", "internal"])
def test_tylko_zespol_i_wylaczony_panel_nie_wysylaja_do_konsultanta(state) -> None:
    reason = reminders.consultant_reason(
        _state(state, 7),
        contract_id=7,
        mode=None,
        email="konsultant@example.com",
        address="rozliczenia@example.com",
    )
    assert reason == reminders.REASON_PORTAL_CLOSED


@pytest.mark.parametrize(
    ("state", "contract_id", "mode", "email", "address", "expected"),
    [
        ("pilot", 8, None, "k@example.com", "r@example.com", reminders.REASON_NO_PANEL),
        ("all", 7, "client_report", "k@example.com", "r@example.com", "client_report"),
        ("pilot", 7, None, "  ", "r@example.com", reminders.REASON_NO_EMAIL),
        ("all", 7, None, "k@example.com", None, reminders.REASON_NO_ADDRESS),
        ("pilot", 7, "consultant", "k@example.com", "r@example.com", "ok"),
        ("all", 7, None, "k@example.com", "r@example.com", "ok"),
    ],
)
def test_kiedy_mail_do_konsultanta_wolno_wyslac(
    state, contract_id, mode, email, address, expected
) -> None:
    reason = reminders.consultant_reason(
        _state(state, 7),
        contract_id=contract_id,
        mode=mode,
        email=email,
        address=address,
    )
    assert reason == expected


def _user(user_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=user_id, name=f"Osoba {user_id}", email=f"o{user_id}@example.com"
    )


def test_opiekun_kontraktu_przed_opiekunem_klienta_przed_dl() -> None:
    users = {uid: _user(uid) for uid in (1, 2, 3)}
    first = reminders.pick_owner(
        contract_owner=1, client_owner=2, client_lead=3, users=users
    )
    assert (first.user_id, first.source) == (1, "contract_care")
    second = reminders.pick_owner(
        contract_owner=None, client_owner=2, client_lead=3, users=users
    )
    assert (second.user_id, second.source) == (2, "client_care")
    third = reminders.pick_owner(
        contract_owner=None, client_owner=None, client_lead=3, users=users
    )
    assert (third.user_id, third.source) == (3, "client_dl")


def test_nieaktywny_opiekun_jest_pomijany_a_bez_nikogo_brak_adresata() -> None:
    # Konto spoza ``users`` (nieaktywne) nie jest adresatem — bierze następny.
    users = {3: _user(3)}
    owner = reminders.pick_owner(
        contract_owner=1, client_owner=2, client_lead=3, users=users
    )
    assert owner.user_id == 3
    assert (
        reminders.pick_owner(
            contract_owner=1, client_owner=None, client_lead=None, users={}
        )
        is None
    )


def test_tresc_maila_mowi_co_przyslac_i_dokad() -> None:
    subject, text = reminders.compose("2026-10", "Bank Przykładowy", "r@example.com")
    assert "październik 2026" in subject
    assert "r@example.com" in text
    assert "akceptacją klienta" in text
    assert "jako plik" in text and "zrzut ekranu" in text
    assert "adresu firmowego" in text
    assert "zł" not in text and "stawk" not in text


def test_dzwonek_opiekuna_skraca_dluga_liste() -> None:
    people = [f"Osoba {i}" for i in range(7)]
    title, message = reminders.bell_text("2026-10", "Bank Przykładowy", people)
    assert title.endswith("(7)")
    assert "Osoba 4" in message and "Osoba 5" not in message
    assert "i 2 innych" in message
    _, one_more = reminders.bell_text("2026-10", "Bank", people[:6])
    assert "i 1 inna osoba" in one_more


def test_adres_rozliczen_z_pierwszego_adresu_listy(monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(
        settings,
        "CONSULTANT_PORTAL_SETTLEMENTS_ADDRESSES",
        " r1@example.com , r2@example.com",
    )
    assert reminders.settlements_address() == "r1@example.com"
    monkeypatch.setattr(settings, "CONSULTANT_PORTAL_SETTLEMENTS_ADDRESSES", "")
    monkeypatch.setattr(settings, "CONSULTANT_PORTAL_SETTLEMENTS_MAILBOX", "")
    assert reminders.settlements_address() is None
