"""Pracuj.pl mailem do opiekuna (27.10.2026) — czyste reguły, bez bazy.

Stawka, skład maila z treści zakładki Pracuj.pl, cisza przypomnień po
wysyłce (dni robocze z kalendarza firmy) i opiekun w stałych częściach.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.services.job_ad import fixed_blocks, pracuj_mail, reminders

CARETAKER = fixed_blocks.PracujCaretaker(name="Nicola", email="ogloszenia@pracuj.pl")

RENDERED = {
    "title": "PAM/CyberArk Developer (k/m/x)",
    "pracuj": {
        "params": ["kontrakt B2B"],
        "fields": [
            {"key": "title", "label": "Tytuł stanowiska", "kind": "text",
             "text": "PAM/CyberArk Developer (k/m/x)", "items": []},
            {"key": "about", "label": "O projekcie", "kind": "text",
             "text": "Onboarding aplikacji do PAM.\n\nZespół <6> osób & więcej.",
             "items": []},
            {"key": "responsibilities", "label": "Twój zakres obowiązków",
             "kind": "list", "text": "a\nb", "items": ["konektory CyberArk", "wsparcie PAM"]},
            {"key": "nice_to_have", "label": "Mile widziane", "kind": "list",
             "text": "", "items": []},
            {"key": "process", "label": "Etapy rekrutacji", "kind": "ordered",
             "text": "", "items": ["Rozmowa z rekruterem", "Rozmowa z klientem"]},
        ],
    },
}  # fmt: skip

FACTS = [
    {"key": "requirements", "label": "Wymagania", "value": "1 krytyczne"},
    {"key": "city", "label": "Miasto", "value": "Gdańsk"},
    {"key": "workplace", "label": "Tryb", "value": "hybrydowo, 2 dni w biurze"},
    {"key": "contract", "label": "Współpraca", "value": "B2B"},
    {"key": "language", "label": "Język", "value": "angielski B2"},
]


# ── Stawka ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("rate_from", "rate_to", "text"),
    [
        (110, 125, "110–125 zł/h netto (B2B)"),
        (110, None, "od 110 zł/h netto (B2B)"),
        (None, 190, "do 190 zł/h netto (B2B)"),
        (150, 150, "150 zł/h netto (B2B)"),
    ],
)
def test_rate_is_written_once_in_one_shape(rate_from, rate_to, text) -> None:
    assert pracuj_mail.rate_text(rate_from, rate_to) == text


@pytest.mark.parametrize(
    ("rate_from", "rate_to", "message"),
    [
        (None, None, "Wpisz stawkę"),
        (190, 170, "nie może być niższa"),
        (50, 200, "ponad trzy razy"),
        (0, 100, "mieścić się"),
        (100, 9000, "mieścić się"),
    ],
)
def test_rate_refusals_say_what_to_fix(rate_from, rate_to, message) -> None:
    with pytest.raises(pracuj_mail.RateInvalid, match=message):
        pracuj_mail.rate_text(rate_from, rate_to)


# ── Skład maila ──────────────────────────────────────────────────────────────


def test_mail_greets_the_caretaker_and_carries_facts_rate_and_sections() -> None:
    mail = pracuj_mail.compose(
        RENDERED, FACTS, caretaker=CARETAKER, rate="110–125 zł/h netto (B2B)"
    )
    assert (
        mail.subject == "Prośba o publikację ogłoszenia: PAM/CyberArk Developer (k/m/x)"
    )
    lines = mail.body_text.split("\n")
    assert lines[0] == "Dzień dobry Nicola,"
    assert "PAM/CyberArk Developer (k/m/x)" in lines
    # Fakty w stałej kolejności, bez „Wymagania” (sama liczba pozycji).
    start = lines.index("Tryb: hybrydowo, 2 dni w biurze")
    assert lines[start : start + 5] == [
        "Tryb: hybrydowo, 2 dni w biurze",
        "Miasto: Gdańsk",
        "Współpraca: B2B",
        "Język: angielski B2",
        "Stawka: 110–125 zł/h netto (B2B)",
    ]
    assert not any(line.startswith("Wymagania") for line in lines)
    # Tytuł nie powtarza się jako sekcja, pusta sekcja wypada.
    assert "Tytuł stanowiska" not in lines and "Mile widziane" not in lines
    assert "• konektory CyberArk" in lines
    assert "2. Rozmowa z klientem" in lines
    assert lines[-1] == "Po publikacji proszę o link do ogłoszenia."
    # Stawka jest w mailu dokładnie raz.
    assert mail.body_text.count("zł/h") == 1


def test_mail_html_escapes_every_text() -> None:
    mail = pracuj_mail.compose(RENDERED, FACTS, caretaker=CARETAKER, rate="110 zł/h")
    assert "Zespół &lt;6&gt; osób &amp; więcej." in mail.body_html
    assert "<6>" not in mail.body_html
    assert "<ol><li>Rozmowa z rekruterem</li>" in mail.body_html


def test_without_a_name_the_mail_says_just_good_morning() -> None:
    mail = pracuj_mail.compose(
        RENDERED, FACTS, caretaker=fixed_blocks.PracujCaretaker(), rate="110 zł/h"
    )
    assert mail.body_text.startswith("Dzień dobry,\n")


# ── Cisza przypomnień po wysyłce ─────────────────────────────────────────────


def _sent(day: int, month: int = 10, hour: int = 10) -> datetime:
    return datetime(2026, month, day, hour, tzinfo=timezone.utc)


def test_caretaker_has_the_day_of_sending_and_three_business_days() -> None:
    sent = _sent(27)  # wtorek
    assert pracuj_mail.is_waiting(sent, date(2026, 10, 27))
    assert pracuj_mail.is_waiting(sent, date(2026, 10, 30))  # piątek = 3. dzień
    assert pracuj_mail.is_waiting(sent, date(2026, 11, 1))  # niedziela
    assert not pracuj_mail.is_waiting(sent, date(2026, 11, 2))  # poniedziałek


def test_holidays_do_not_count_as_business_days() -> None:
    sent = _sent(9, month=11)  # poniedziałek; 11.11 to święto
    assert pracuj_mail.is_waiting(sent, date(2026, 11, 12))
    assert pracuj_mail.is_waiting(sent, date(2026, 11, 13))
    assert not pracuj_mail.is_waiting(sent, date(2026, 11, 16))


def test_late_evening_utc_counts_in_the_company_calendar() -> None:
    # 23:30 UTC we wtorek to już środa w Warszawie.
    sent = datetime(2026, 10, 27, 23, 30, tzinfo=timezone.utc)
    assert pracuj_mail.is_waiting(sent, date(2026, 11, 2))
    assert not pracuj_mail.is_waiting(sent, date(2026, 11, 3))


# ── Stan kanału w przypomnieniach ────────────────────────────────────────────


def test_requested_pracuj_is_not_missing_and_says_so_in_the_mail() -> None:
    at = _sent(27)
    channels = reminders.channel_states(
        career_live=None,
        portals_live={},
        skips={},
        recruiter_ids=(2,),
        leads=(1,),
        requested={"pracuj": at},
    )
    status = reminders.JobAdStatus(
        job_id=1,
        title="PAM",
        client=None,
        opened_at=at,
        leads=(1,),
        delivery_lead_id=1,
        recruiter_ids=(2,),
        has_ad=True,
        channels=channels,
    )
    pracuj = status.channel("pracuj")
    assert pracuj.state == "requested" and pracuj.since == at and not pracuj.owners
    assert [c.channel for c in status.missing] == ["kariera", "jjit"]
    fact = reminders.channel_fact(status, pracuj, viewer=1, today=date(2026, 10, 28))
    assert fact == "✉ wysłane do opiekuna 27.10 · czeka na publikację"


def test_live_and_skipped_win_over_requested() -> None:
    at = _sent(27)
    channels = reminders.channel_states(
        career_live=None,
        portals_live={"pracuj": at},
        skips={"jjit": ("Klient nie chce", 1, at)},
        recruiter_ids=(),
        leads=(1,),
        requested={"pracuj": at, "jjit": at},
    )
    states = {c.channel: c.state for c in channels}
    assert states == {"kariera": "missing", "pracuj": "live", "jjit": "skipped"}


# ── Opiekun w stałych częściach ─────────────────────────────────────────────


def test_caretaker_defaults_to_the_pracuj_ads_mailbox() -> None:
    blocks = fixed_blocks.parse_blocks(None)
    assert blocks.pracuj_caretaker == fixed_blocks.PracujCaretaker(
        name="", email="ogloszenia@pracuj.pl"
    )


def test_broken_caretaker_in_the_database_falls_back_to_the_default() -> None:
    blocks = fixed_blocks.parse_blocks(
        {"pracuj_caretaker": {"name": "Nicola", "email": "nie adres"}}
    )
    assert blocks.pracuj_caretaker == fixed_blocks.PracujCaretaker()


@pytest.mark.parametrize(
    "email",
    [
        "",
        "a@b",
        "Nicola <ogloszenia@pracuj.pl>",
        "a@pracuj.pl, b@pracuj.pl",
        "a b@x.pl",
    ],
)
def test_caretaker_needs_exactly_one_plain_address(email) -> None:
    with pytest.raises(ValueError, match="adres e-mail"):
        fixed_blocks.validate_caretaker({"name": "Nicola", "email": email})


def test_caretaker_name_is_one_line() -> None:
    caretaker = fixed_blocks.validate_caretaker(
        {"name": "  Nicola\nZ  ", "email": " ogloszenia@pracuj.pl "}
    )
    assert caretaker == fixed_blocks.PracujCaretaker("Nicola Z", "ogloszenia@pracuj.pl")


def test_saving_blocks_without_the_caretaker_keeps_the_saved_one() -> None:
    saved = fixed_blocks.PracujCaretaker("Nicola", "opiekun@pracuj.pl")
    value = fixed_blocks.DEFAULTS.as_dict()
    del value["pracuj_caretaker"]
    blocks = fixed_blocks.validate_blocks(value, keep_caretaker=saved)
    assert blocks.pracuj_caretaker == saved
