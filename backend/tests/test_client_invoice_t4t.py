"""„Do faktury” z raportu T4T bez bazy: akceptacja managera po angielsku, termin
faktury (art. 106i), pozycja z godzin, godziny z wystawionej faktury. Dane fikcyjne."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.services.client_settlements import client_invoice, mail_text, t4t_invoice
from app.services.client_settlements.acceptance_mail import MailMessage

MONTH = "2026-09"
DOMAINS = ("klient.example",)
MANAGER = [MailMessage("pm@klient.example", date(2026, 10, 12))]
OURS = [MailMessage("koordynatorka@b2b.example", date(2026, 10, 9))]


def _mail(body: str, subject: str = "RE: Time for Teams") -> mail_text.Mail:
    return mail_text.Mail(subject=subject, body=body)


def _rules(**params: str) -> dict:
    return {t4t_invoice.RULE_KEY: {"level": "warn", "params": params}}


def test_akceptacja_managera_z_godzinami_za_miesiac() -> None:
    verdict = t4t_invoice.judge_mail(
        _mail("Approved.\n\nPlease approve the 102 hours for September 2026."),
        MANAGER,
        month=MONTH,
        domains=DOMAINS,
    )
    assert verdict.ok and verdict.hours == Decimal("102")
    assert verdict.note == "Akceptacja mailowa managera: 102 h za wrzesień 2026."


def test_sama_nasza_prosba_nie_jest_akceptacja() -> None:
    verdict = t4t_invoice.judge_mail(
        _mail("Please approve the 102 hours for September 2026."),
        OURS,
        month=MONTH,
        domains=DOMAINS,
    )
    assert not verdict.ok and verdict.hours is None


def test_akceptacja_za_inny_miesiac_albo_bez_jednej_liczby() -> None:
    other = t4t_invoice.judge_mail(
        _mail("Approved. 160 hours for October 2026."),
        MANAGER,
        month=MONTH,
        domains=DOMAINS,
    )
    assert not other.ok and "nie za wrzesień 2026" in other.note
    two = t4t_invoice.judge_mail(
        _mail("Approved: 120 hours in September 2026, plus 32 hours moved."),
        MANAGER,
        month=MONTH,
        domains=DOMAINS,
    )
    assert not two.ok and "32 h, 120 h" in two.note
    none = t4t_invoice.judge_mail(
        _mail("Thanks, I will check September 2026 next week."),
        MANAGER,
        month=MONTH,
        domains=DOMAINS,
    )
    assert not none.ok and none.note == "W mailu nie ma akceptacji managera."


def test_angielski_odczyt_tylko_na_zadanie() -> None:
    text = "Please approve the 192 hours for September 2026. Approved."
    assert mail_text.read_acceptance(text, MONTH).hours == ()
    found = mail_text.read_acceptance(text, MONTH, english=True)
    assert found.hours == (Decimal("192"),)
    assert MONTH in found.months
    # „may” bez roku to czasownik, nie maj.
    verb = mail_text.read_acceptance("You may approve 8 hours.", MONTH, english=True)
    assert "2026-05" not in verb.months


def test_termin_faktury_15_dnia_i_ostrzezenie() -> None:
    assert t4t_invoice.deadline("2026-10") == date(2026, 11, 15)
    assert t4t_invoice.deadline("2026-12") == date(2027, 1, 15)
    rules = _rules(warn_days="5")
    assert t4t_invoice.deadline_warning(MONTH, date(2026, 10, 9), rules, ["X"]) is None
    warn = t4t_invoice.deadline_warning(MONTH, date(2026, 10, 10), rules, ["Y", "x"])
    assert warn == {
        "date": "2026-10-15",
        "days_left": 5,
        "overdue": False,
        "missing": 2,
        "people": ["x", "Y"],
    }
    late = t4t_invoice.deadline_warning(MONTH, date(2026, 10, 17), rules, ["X"])
    assert late["overdue"] is True and late["days_left"] == -2
    # Wszyscy mają zatwierdzone godziny albo brak dnia: bez ostrzeżenia.
    assert t4t_invoice.deadline_warning(MONTH, date(2026, 10, 14), rules, []) is None
    assert t4t_invoice.deadline_warning(MONTH, None, rules, ["X"]) is None


def test_parametr_dni_ostrzezenia() -> None:
    assert t4t_invoice.warn_days(_rules()) == t4t_invoice.DEFAULT_WARN_DAYS
    assert t4t_invoice.warn_days(_rules(warn_days="abc")) == 5
    assert t4t_invoice.warn_days(_rules(warn_days="-3")) == 0
    assert t4t_invoice.warn_days(_rules(warn_days="90")) == t4t_invoice.MAX_WARN_DAYS
    assert t4t_invoice.warn_days(_rules(warn_days=" 10 ")) == 10


def _order(unit: str, rate: str, currency: str = "PLN", md: str | None = None):
    return SimpleNamespace(
        rate_unit=SimpleNamespace(value=unit),
        rate_client=Decimal(rate),
        rate_client_currency=currency,
        md_rate_revenue=None if md is None else Decimal(md),
        md_rate_cost=None,
        rate_candidate=None,
    )


def test_pozycja_godzinowa_i_dzienna() -> None:
    (hourly,) = client_invoice.t4t_positions(
        Decimal("126.5"), _order("hourly", "150"), name="Usługi"
    )
    assert (hourly.unit, hourly.quantity, hourly.unit_price, hourly.net) == (
        "godz.",
        Decimal("126.5"),
        Decimal("150.00"),
        Decimal("18975.00"),
    )
    (daily,) = client_invoice.t4t_positions(
        Decimal("172"), _order("daily", "1200"), name="Usługi"
    )
    assert (daily.unit, daily.quantity, daily.net) == (
        "MD",
        Decimal("21.500"),
        Decimal("25800.00"),
    )
    (no_order,) = client_invoice.t4t_positions(Decimal("8"), None, name="Usługi")
    assert no_order.unit_price is None and no_order.net == Decimal("0.00")


def _invoice(*items: dict) -> SimpleNamespace:
    return SimpleNamespace(items=list(items))


def test_godziny_z_wystawionej_faktury_i_nazwa_pozycji() -> None:
    base = {
        "name": "NIDS:2020-000001, IT, ID:M000001",
        "unit": "godz.",
        "quantity": "176",
    }
    travel = {"name": "NIDS:2020-000001, IT, PKP", "unit": "szt.", "quantity": "1"}
    correction = {"name": base["name"], "unit": "godz.", "quantity": "-32"}
    assert client_invoice.invoiced_hours([_invoice(base, travel)]) == Decimal("176")
    assert client_invoice.invoiced_hours(
        [_invoice(base), _invoice(correction)]
    ) == Decimal("144")
    assert client_invoice.invoiced_hours([_invoice(travel)]) is None
    assert client_invoice.invoiced_hours([]) is None
    # Faktura za koszty podróży nie daje nazwy pozycji godzinowej.
    assert client_invoice.hours_item_name([travel]) is None
    assert client_invoice.hours_item_name([travel, base]) == base["name"]
