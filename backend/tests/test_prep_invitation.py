"""Zaproszenie na prep: tytuł i treść, które widzi kandydat.

Zgłoszenie Delivery Leada 02.10.2026: tytuł „Prep 1: … — …” nie nadaje się
dla kandydata, treść ma być standardowa (jak w dotychczasowych zaproszeniach
z Outlooka), bez półpauz, a informacja o administratorze danych niżej, jako
adnotacja. Do tej daty dopisek i informacja o nagrywaniu sklejały się w jeden
akapit, bo zwykły tekst z pustą linią trafiał do treści HTML.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.services import prep_invitation
from app.services.m365.html_sanitize import sanitize_html

INTERVIEW = datetime(2031, 10, 6, 12, 0, tzinfo=timezone.utc)  # 14:00 w Warszawie


def _text(**overrides) -> str:
    args = dict(
        prep_no=1,
        client_name="Bank Przykładowy",
        job_title="Senior Java Developer",
        interview_start=INTERVIEW,
        note=None,
        organizer_name="Kasia Lead",
    )
    args.update(overrides)
    return prep_invitation.text(**args)


def test_title_follows_the_team_convention_without_dashes() -> None:
    title = prep_invitation.title(1, "Jan Testowy", "Bank Przykładowy")
    assert (
        title == "Przygotowanie do spotkania z Klientem Bank Przykładowy - Jan Testowy"
    )
    second = prep_invitation.title(2, "Jan Testowy", "Bank Przykładowy")
    assert second.endswith("- Jan Testowy (spotkanie 2)")
    for value in (title, second):
        assert "—" not in value and "–" not in value
        assert "Prep" not in value


def test_title_without_client_and_with_a_very_long_client_name() -> None:
    assert (
        prep_invitation.title(1, "Jan Testowy", None)
        == "Przygotowanie do spotkania z Klientem - Jan Testowy"
    )
    long = prep_invitation.title(2, "Jan Testowy", "K" * 400)
    assert len(long) <= prep_invitation.MAX_TITLE
    assert long.endswith(" - Jan Testowy (spotkanie 2)")


def test_body_is_the_standard_invitation_in_paragraphs() -> None:
    paragraphs = _text(note="Proszę o kamerę.").split("\n\n")
    assert paragraphs == [
        "Dzień dobry,",
        "Zapraszam na spotkanie przygotowujące do rozmowy z Klientem Bank "
        "Przykładowy na stanowisko Senior Java Developer.",
        "Termin rozmowy z Klientem: 06.10.2031, godz. 14:00",
        "Proszę o kamerę.",
        "W razie pytań pozostaję do dyspozycji.",
        "Pozdrawiam\nKasia Lead",
    ]
    assert "—" not in _text() and "–" not in _text()
    assert "drugie spotkanie przygotowujące" in _text(prep_no=2)


def test_body_skips_what_is_unknown() -> None:
    bare = _text(client_name=None, job_title=None, interview_start=None)
    assert "Zapraszam na spotkanie przygotowujące do rozmowy z Klientem." in bare
    assert "Termin rozmowy" not in bare
    assert "stanowisko" not in bare
    # Termin samego prepu niesie zaproszenie — w treści zostałby nieaktualny
    # po przełożeniu spotkania.
    assert "Termin spotkania przygotowującego" not in _text()


def test_html_keeps_paragraphs_and_puts_the_notice_below_as_an_annotation() -> None:
    body = _text(note="Wiersz 1\nWiersz 2 <script>alert(1)</script>")
    html = sanitize_html(prep_invitation.as_html(body))
    main, _, annotation = html.partition("<hr>")
    # Każdy akapit osobno — do 02.10.2026 wszystko było jednym ciągiem tekstu.
    assert main.count("<p>") == 6
    assert "<p>Dzień dobry,</p>" in main
    assert "<p>Pozdrawiam<br>Kasia Lead</p>" in main
    assert "Wiersz 1<br>Wiersz 2" in main
    assert "<script>" not in html
    # Informacja o nagrywaniu i administratorze danych: pod kreską, kursywą.
    assert "Administratorem danych" not in main
    assert annotation.startswith("<p><em>") and "Administratorem danych" in annotation
    assert "nagrywana i transkrybowana" in annotation


def test_plain_version_for_nexus_carries_the_same_content() -> None:
    plain = prep_invitation.as_plain(_text())
    assert plain.startswith("Dzień dobry,\n\nZapraszam")
    assert plain.endswith(prep_invitation.NOTICE_TEXT)


def test_preview_fields_survive_as_placeholders() -> None:
    """Okno „Zaplanuj prep” dostaje treść z polami do podstawienia."""
    body = _text(
        note=prep_invitation.NOTE_FIELD, organizer_name=prep_invitation.ORGANIZER_FIELD
    )
    assert "\n\n{note}\n\n" in body
    assert body.endswith("Pozdrawiam\n{organizer}")
    assert prep_invitation.interview_line(INTERVIEW) in body
