"""Suma godzin z prośby o akceptację, którą klient zaakceptował w wątku. Bez bazy.

Próba IX–X 2026. Część osób nie ma pliku godzin za miesiąc. Jedynym dowodem jest
wątek: prośba o akceptację z jedną sumą („prośba o akcept TS za 10-2026 176h”,
„Proszę o akceptację czasu za wrzesień dla … - 176h.”) i odpowiedź klienta
„akceptuję”. Prośbę pisze nasza koordynatorka albo sam konsultant ze skrzynki
u klienta, a mail z akceptacją przychodzi na rozliczenia@ wprost albo przekazany.

Bierzemy najnowszą wiadomość klienta (``senders``, bez samego konsultanta) ze
słowem akceptacji albo odmowy. Odmowa daje brak wyniku. Liczba pochodzi z tej
wiadomości, a bez niej z wiadomości, na którą klient odpisał (następnej w wątku).
Starszych wiadomości nie bierzemy, bo mają nieaktualne liczby. Wynik jest tylko
wtedy, gdy:

* prośba ma jedną sumę: jedną liczbę godzin albo jedną liczbę MD (dwie różne
  liczby, godziny i MD naraz = brak);
* prośba dotyczy tej osoby: napisał ją sam konsultant kontraktu albo imię
  i nazwisko osoby stoi w prośbie lub w temacie wątku;
* miesiąc z prośby jest jeden (daty sprzed roku, np. z klauzuli RODO w stopce,
  pomijamy). Zgodność z rozliczanym miesiącem sprawdza ``declared.evaluate``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from app.services.client_settlements import mail_text
from app.services.client_settlements.declared import month_in, short_lines
from app.services.client_settlements.rcp_checks import name_tokens

#: Nazwa dowodu na karcie rozliczenia.
SOURCE = "Prośba o akceptację godzin zaakceptowana przez klienta"
#: Miesiące w prośbie dalej niż o tyle od rozliczanego to nie okres pracy (stopka).
_NEAR_MONTHS = 12
_SUBJECT_LINE = re.compile(r"^\s*(?:temat|subject)\s*:\s*(.+)$", re.IGNORECASE)


@dataclass(frozen=True)
class Request:
    hours: Optional[Decimal]
    md: Optional[Decimal]
    #: ``RRRR-MM`` z prośby, bez niego z tematu wątku; ``None`` = brak.
    month: Optional[str]
    #: Adres nadawcy wiadomości z akceptacją.
    acceptor: str
    #: Adres nadawcy prośby (``acceptor``, gdy liczba stoi w samej akceptacji).
    requester: str
    #: Pierwsza linia odpowiedzi klienta, do pokazania w kontrolach.
    quote: str


def _own(text: str) -> str:
    return "\n".join(
        line
        for line in short_lines(text).splitlines()
        if not mail_text._HEADER_LINE.match(line)
    )


def _subjects(subject: str, text: str) -> str:
    lines = [subject] + [
        found.group(1)
        for line in text.splitlines()
        if (found := _SUBJECT_LINE.match(line))
    ]
    return "\n".join(lines)


def _address(sender: str) -> str:
    """„Imię Nazwisko <adres<mailto:adres>>” → „adres”."""

    found = mail_text._ADDRESS.search(sender)
    return found.group(0).lower() if found else sender


def _apart(one: str, other: str) -> int:
    a, b = (int(x[:4]) * 12 + int(x[5:7]) for x in (one, other))
    return abs(a - b)


def _quote(own: str, *, skip_subject: bool) -> str:
    """Pierwsza linia treści wiadomości bez powitania (pierwsza wiadomość wątku
    zaczyna się od tematu)."""

    greeting = re.compile(r"^(dzie[nń] dobry|witam|hej|cze[sś][cć])\W*$", re.I)
    lines = [line.strip() for line in own.splitlines()[int(skip_subject) :]]
    return next((x for x in lines if x and not greeting.match(x)), "")[:160]


def _rejected(text: str) -> bool:
    # Wzór odmowy jak przy odpowiedzi na paczkę KCP; import tutaj, bo
    # ``client_acceptance`` importuje ``service``.
    from app.services.client_settlements.client_acceptance import _REJECT

    return bool(_REJECT.search(text))


def _amount(found: mail_text.Acceptance) -> Optional[tuple[str, Decimal]]:
    """Jedna suma wiadomości: (``h`` albo ``md``, liczba); inaczej ``None``."""

    hours, md = set(found.hours), set(found.md)
    if len(hours) + len(md) != 1:
        return None
    return ("h", next(iter(hours))) if hours else ("md", next(iter(md)))


def _period(found: mail_text.Acceptance, subjects: str, month: str) -> Optional[str]:
    """Jeden miesiąc z prośby (bez dat sprzed roku), bez niego z tematu."""

    near = {m for m in found.months if _apart(m, month) <= _NEAR_MONTHS}
    if len(near) > 1:
        return None
    return next(iter(near), None) or month_in(subjects)


def _for_person(
    requester: str,
    text: str,
    subjects: str,
    *,
    person_name: str,
    senders: mail_text.Senders,
) -> bool:
    if senders.is_consultant(requester):
        return True
    person = name_tokens(person_name)
    return bool(person) and (
        person <= name_tokens(text) or person <= name_tokens(subjects)
    )


def _in_thread(
    mail: mail_text.Mail,
    *,
    month: str,
    person_name: str,
    senders: mail_text.Senders,
) -> Optional[Request]:
    messages = [
        (sender or "", text, _own(text)) for sender, text in mail_text._messages(mail)
    ]
    for at, (sender, _raw, own) in enumerate(messages):
        if not senders.accepts_from(sender):
            continue
        if _rejected(own):
            return None
        if not mail_text._APPROVED.search(own):
            continue
        # Liczba w samej akceptacji, a bez niej w wiadomości, na którą klient odpisał.
        for requester, raw, body in messages[at : at + 2]:
            found = mail_text.read_acceptance(body, month)
            if not (found.hours or found.md):
                continue
            amount = _amount(found)
            subjects = _subjects(mail.subject, raw)
            if amount is None or not _for_person(
                requester, body, subjects, person_name=person_name, senders=senders
            ):
                return None
            # Nowsza wiadomość z inną liczbą (korekta po akceptacji) = niejednoznaczne.
            for _newer, _text, text in messages[:at]:
                later = mail_text.read_acceptance(text, month)
                if (later.hours or later.md) and _amount(later) != amount:
                    return None
            unit, value = amount
            return Request(
                hours=value if unit == "h" else None,
                md=value if unit == "md" else None,
                month=_period(found, subjects, month),
                acceptor=_address(sender),
                requester=_address(requester),
                quote=_quote(own, skip_subject=at == 0),
            )
        return None
    return None


def find(
    mail: mail_text.Mail,
    *,
    month: str,
    person_name: str,
    senders: mail_text.Senders,
) -> Optional[Request]:
    """Zaakceptowana przez klienta prośba z jedną sumą w mailu albo w mailu
    do niego załączonym; ``None`` = brak albo niejednoznaczna."""

    for one in mail_text.thread(mail):
        found = _in_thread(one, month=month, person_name=person_name, senders=senders)
        if found is not None:
            return found
    return None


@dataclass(frozen=True)
class Unaccepted:
    """Prośba z jedną sumą, na którą klient odpisał bez akceptacji i bez odmowy."""

    hours: Optional[Decimal]
    md: Optional[Decimal]
    month: str
    #: Adres osoby klienta, która odpisała (do niej idzie prośba o „akceptuję”).
    replier: str
    requester: str
    quote: str


def _unaccepted_in_thread(
    mail: mail_text.Mail,
    *,
    month: str,
    person_name: str,
    senders: mail_text.Senders,
) -> Optional[Unaccepted]:
    messages = [
        (sender or "", text, _own(text)) for sender, text in mail_text._messages(mail)
    ]
    for at, (sender, _raw, own) in enumerate(messages):
        if not senders.accepts_from(sender):
            continue
        # Rozstrzyga najnowsza wiadomość klienta: akceptację czyta ``find``,
        # odmowa to nie brak odpowiedzi.
        if _rejected(own) or mail_text._APPROVED.search(own):
            return None
        if at + 1 >= len(messages):
            return None
        requester, raw, body = messages[at + 1]
        found = mail_text.read_acceptance(body, month)
        amount = _amount(found) if (found.hours or found.md) else None
        subjects = _subjects(mail.subject, raw)
        if amount is None or not _for_person(
            requester, body, subjects, person_name=person_name, senders=senders
        ):
            return None
        if _period(found, subjects, month) != month:
            return None
        unit, value = amount
        return Unaccepted(
            hours=value if unit == "h" else None,
            md=value if unit == "md" else None,
            month=month,
            replier=_address(sender),
            requester=_address(requester),
            quote=_quote(own, skip_subject=at == 0),
        )
    return None


def find_unaccepted(
    mail: mail_text.Mail,
    *,
    month: str,
    person_name: str,
    senders: mail_text.Senders,
) -> Optional[Unaccepted]:
    """Prośba o akceptację za ``month`` z jedną sumą dla tej osoby, na którą
    najnowsza odpowiedź klienta nie jest ani akceptacją, ani odmową.

    Decyzja Artura z 25.11.2026 (BIK, IX 2026: „Prosimy o przesyłanie również
    faktury w formie PDF”): odpowiedź bez sprzeciwu NIE jest akceptacją, ale
    rozliczenie nie może stać bez drogi — akceptujący dostaje prośbę o wyraźne
    „akceptuję” (``client_settlements/feedback``)."""

    for one in mail_text.thread(mail):
        found = _unaccepted_in_thread(
            one, month=month, person_name=person_name, senders=senders
        )
        if found is not None:
            return found
    return None
