"""Zaproszenie na prep: tytuł i treść, które widzi kandydat (0370).

Zespół od lat wysyłał z Outlooka zaproszenia „Przygotowanie do spotkania
z <klient> - <kandydat>” ze stałą treścią. Do 02.10.2026 NEXUS wysyłał
„Prep 1: <kandydat> — <stanowisko>”, a wiadomość i informację o nagrywaniu
sklejał w jeden akapit (zwykły tekst w treści HTML). Zgłoszenie Delivery
Leada: tytuł i treść jak dotąd, bez półpauz, a informacja o administratorze
danych niżej, jako adnotacja.

Jedno źródło treści: okno „Zaplanuj prep” pokazuje podgląd z tego samego
szablonu (``NOTE_FIELD`` i ``ORGANIZER_FIELD`` podstawia przeglądarka).

W treści nie ma terminu samego prepu — niesie go zaproszenie, a wpisany
tekstem zostałby nieaktualny po przełożeniu spotkania.

Od 26.10.2026 (decyzje D1–D3) pod podpisem stoi sekcja „O roli” z opisem
z Profilu Championa (``services/prep_role.py``), w Prepie 1 i 2, a w treści
zdanie, że opis jest niżej.

Od 24.11.2026 (F3, decyzja Artura) przed Prepem 1 może być Przygotowanie
rekrutera (``prep_no`` 0). Kandydat dostaje wtedy spotkania numerowane po
kolei — „(spotkanie 1)”, „(spotkanie 2)”, „(spotkanie 3)” — bo dwa zaproszenia
o tym samym tytule wyglądałyby na pomyłkę. Bez Przygotowania tytuły są jak
dotąd: Prep 1 bez numeru, Prep 2 „(spotkanie 2)”. Numer liczy się przy
zakładaniu spotkania (``meeting_number``).
"""

from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from app.core.config import settings

# Treść informacji o nagrywaniu. Wersja robocza do akceptacji prawnej —
# zmiana treści = nowa wersja (jak zgoda na stronie kariery).
NOTICE_VERSION = "2026-09-23"
NOTICE_TEXT = (
    "Ta rozmowa jest nagrywana i transkrybowana w Microsoft Teams wyłącznie "
    "po to, żeby dobrze przygotować Cię do rozmowy z klientem. Administratorem "
    "danych jest B2B.NET S.A. Transkrypt zostaje wewnątrz B2B.NET i nie trafia "
    "do klienta. Jeśli nie chcesz nagrania, powiedz o tym na początku rozmowy."
)

# Pola podglądu w oknie „Zaplanuj prep” (podstawia je przeglądarka).
NOTE_FIELD = "{note}"
ORGANIZER_FIELD = "{organizer}"
ROLE_FIELD = "{role}"
ROLE_HINT_FIELD = "{role_hint}"

ROLE_HINT = (
    "Przed spotkaniem przejrzyj, proszę, opis roli poniżej. Porozmawiamy o tym, "
    "jak Twoje doświadczenie odpowiada tym wymaganiom."
)

MAX_TITLE = 255


def when_label(value: datetime) -> str:
    """„05.10.2026, godz. 14:00” w strefie firmy."""
    aware = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    local = aware.astimezone(ZoneInfo(settings.BUSINESS_TZ))
    return f"{local:%d.%m.%Y}, godz. {local:%H:%M}"


def _client_phrase(client_name: Optional[str]) -> str:
    name = " ".join((client_name or "").split())
    return f"Klientem {name}" if name else "Klientem"


_ORDINALS = {1: "pierwsze", 2: "drugie", 3: "trzecie"}


def meeting_number(prep_no: int, has_preparation: bool) -> Optional[int]:
    """Które to spotkanie przygotowujące dla kandydata (``None`` = bez numeru).

    Przygotowanie (0) jest zawsze pierwsze. Bez Przygotowania w rundzie
    zostaje dawna numeracja: Prep 1 bez numeru, Prep 2 drugi.
    """
    if prep_no == 0:
        return 1
    if prep_no == 1:
        return 2 if has_preparation else None
    return 3 if has_preparation else 2


def _default_number(prep_no: int) -> Optional[int]:
    return meeting_number(prep_no, has_preparation=False)


def title(
    prep_no: int,
    candidate_name: str,
    client_name: Optional[str],
    *,
    number: Optional[int] = None,
) -> str:
    """Tytuł zaproszenia — ten sam w Outlooku organizatora, kandydata i w NEXUSIE.

    ``number`` — numer spotkania z ``meeting_number``; brak = numeracja sprzed
    Przygotowania (Prep 2 „(spotkanie 2)”).
    """
    who = " ".join((candidate_name or "").split()) or "Kandydat"
    no = number if number is not None else _default_number(prep_no)
    suffix = f" (spotkanie {no})" if no else ""
    head = f"Przygotowanie do spotkania z {_client_phrase(client_name)}"
    tail = f" - {who}{suffix}"
    return head[: MAX_TITLE - len(tail)] + tail


def interview_line(interview_start: datetime) -> str:
    """Zdanie o terminie rozmowy u klienta (tylko gdy prep jest przed nią)."""
    return f"Termin rozmowy z Klientem: {when_label(interview_start)}"


def text(
    *,
    prep_no: int,
    client_name: Optional[str],
    job_title: Optional[str],
    interview_start: Optional[datetime],
    note: Optional[str],
    organizer_name: str,
    role_hint: Optional[str] = None,
    number: Optional[int] = None,
) -> str:
    """Wiadomość do kandydata: akapity rozdzielone pustą linią, bez adnotacji.

    ``role_hint`` — zdanie o opisie roli pod podpisem (:data:`ROLE_HINT`), tylko
    gdy opis idzie w zaproszeniu. ``number`` jak w :func:`title`.
    """
    no = number if number is not None else _default_number(prep_no)
    meeting = (
        f"{_ORDINALS[no]} spotkanie przygotowujące"
        if no in _ORDINALS
        else "spotkanie przygotowujące"
    )
    lead = f"Zapraszam na {meeting} do rozmowy z {_client_phrase(client_name)}"
    role = " ".join((job_title or "").split())
    if role:
        lead += f" na stanowisko {role}"
    paragraphs = ["Dzień dobry,", f"{lead}."]
    if interview_start is not None:
        paragraphs.append(interview_line(interview_start))
    if role_hint:
        paragraphs.append(role_hint)
    extra = (note or "").replace("\r\n", "\n").strip()
    if extra:
        paragraphs.append(extra)
    paragraphs.append("W razie pytań pozostaję do dyspozycji.")
    paragraphs.append(f"Pozdrawiam\n{organizer_name}")
    return "\n\n".join(paragraphs)


def role_section(role_title: Optional[str], description: Optional[str]) -> str:
    """„O roli: <stanowisko>” + opis; pusty opis = brak sekcji."""
    body = (description or "").replace("\r\n", "\n").strip()
    if not body:
        return ""
    role = " ".join((role_title or "").split())
    return f"{'O roli: ' + role if role else 'O roli'}\n\n{body}"


def _paragraphs_html(text_: str) -> str:
    return "".join(
        "<p>" + "<br>".join(html.escape(line) for line in part.split("\n")) + "</p>"
        for part in text_.split("\n\n")
        if part.strip()
    )


def as_html(body: str, role: str = "") -> str:
    """Treść zaproszenia dla Outlooka: akapity, sekcja „O roli” i adnotacja
    o nagrywaniu, każde pod kreską."""
    rendered = _paragraphs_html(body)
    if role:
        heading, _, rest = role.partition("\n\n")
        rendered += (
            f"<hr><p><strong>{html.escape(heading)}</strong></p>"
            + _paragraphs_html(rest)
        )
    return f"{rendered}<hr><p><em>{html.escape(NOTICE_TEXT)}</em></p>"


def as_plain(body: str, role: str = "") -> str:
    """Ta sama treść jako zwykły tekst — opis wydarzenia w NEXUSIE."""
    middle = f"\n\n{role}" if role else ""
    return f"{body}{middle}\n\n{NOTICE_TEXT}"
