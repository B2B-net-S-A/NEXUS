"""Mail koordynatora z godzinami zaakceptowanymi przez klienta → MD osoby. Bez bazy.

Decyzja Artura z 23.11.2026. Centrum e-Zdrowia za X 2026 nie przysłało
podpisanego protokołu umowy CeZ/242. Koordynatorka rozliczeń wysłała na rozliczenia@
zestawienie „Zaakceptowane godziny przez cez: Umowa nr … - Październik 2026”
(wcześniej „AKCEPTACJA GODZIN CEZ WRZESIEŃ”), a Finanse wystawiły z niego fakturę
(6 z 6 osób, 952 h, równe fakturze). Taki mail jest dowodem godzin osób z listy.

Wzór: znacznik „zaakceptowane godziny” albo „akceptacja godzin” w temacie albo
pierwszej linii treści, potem wiersz na osobę „Imię Nazwisko: 176 h” („…:176h”,
punktor „*” bywa w osobnej linii). „czekamy”, „BRAK CZEKAMY” albo liczba w innej
jednostce = osoba bez godzin (bez MD). Czytamy tylko treść nad stopką
(„Pozdrawiam”) i nad cytatem wcześniejszej wersji („Od:”, „From:”), bo cytat ma
nieaktualne liczby. Miesiąc z tematu; bez roku — okres dokumentu z poczty.

Wynik ma kształt protokołu zbiorczego, więc kontrole i MD liczy
``protocol_collective.evaluate`` (MD = godziny / ``fields.md_hours``).
"""

from __future__ import annotations

import re
from typing import Optional

from app.services.client_settlements import mail_text
from app.services.client_settlements.declared import month_in, number, short_lines
from app.services.client_settlements.protocol_collective import (
    _NAME,
    _NUM,
    Protocol,
    ProtocolPerson,
)

SOURCE = "Godziny zaakceptowane przez klienta (mail koordynatora)"
_MARK = re.compile(r"zaakceptowane\s+godziny|akceptacja\s+godzin", re.I)
_BULLET = r"(?:[*•·-][ \t]*)?"
_ROW = re.compile(rf"^[ \t]*{_BULLET}({_NAME})[ \t]*:[ \t]*({_NUM})[ \t]*h\b", re.I)
_END = re.compile(
    r"^[ \t]*(?:pozdrawiam|z\s+powa[zż]aniem|od:|from:|wys[lł]ane:|sent:|-{2,}|_{5,}|>)",
    re.I,
)


def parse_text(subject: str, body: str) -> Optional[Protocol]:
    """Zestawienie godzin z tematu i treści albo ``None`` dla innego maila."""

    lines = short_lines(body).splitlines()
    head = next((line for line in lines if line.strip()), "")
    if not (_MARK.search(subject) or _MARK.search(head)):
        return None
    people: list[ProtocolPerson] = []
    for line in lines:
        if _END.match(line):
            break
        found = _ROW.match(line)
        hours = number(found.group(2)) if found else None
        if found and hours is not None and hours > 0:
            people.append(ProtocolPerson(found.group(1).strip(), hours))
    if not people:
        return None
    return Protocol(SOURCE, month_in(subject), tuple(people))


def parse(content: bytes, mime: str) -> Optional[Protocol]:
    if mime not in mail_text.MAIL_MIMES:
        return None
    mail = mail_text.read(content, mime)
    return parse_text(mail.subject, mail.body) if mail is not None else None
