"""Mail rozliczeń NN z liczbą MD: akceptacja odbioru pracy klienta. Bez bazy.

Nationale-Nederlanden wysyła z działu rozliczeń kontraktorów mail „Rozliczenie
pracownika <osoba> za okres 09-2026” z treścią „szczegóły zaakceptowanego
odbioru pracy”, polami „Imię i nazwisko”, „Okres pracy: 09-2026” i tabelą
„Numer zamówienia · Nazwa CK · Opis wykonywanej pracy · Ilość MD · Kwota netto
· Kwota brutto”. W tekście maila każda komórka to osobna linia, więc MD to
liczba tuż nad parą kwot „… PLN”. Kilka wierszy tabeli sumujemy; czytamy
tylko pierwszą tabelę, bo przekazany dalej mail cytuje ją ponownie.

Przekazany dalej z Outlooka mail bywa tekstem z wierszem tabeli w jednej linii
(próba IV–V 2026): „00000001 ALFA - Moduł Prace dewelopera 20 19,200.00 PLN
23,616.00 PLN” — wtedy MD to liczba tuż przed parą kwot w tej samej linii.

To akceptacja klienta z MD wprost, bez przeliczania godzin. Mail spoza wzoru
daje ``None``.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Optional

from app.services.client_settlements import mail_text
from app.services.client_settlements.declared import (
    Declared,
    month_in,
    short_lines,
)

SOURCE = "Akceptacja NN"
_MARK = re.compile(r"zaakceptowanego\s+odbioru\s+pracy", re.I)
_PERSON = re.compile(r"^imię\s+i\s+nazwisko\s*:\s*(.+)$", re.I)
_PERIOD = re.compile(r"^okres\s+pracy\s*:\s*(.+)$", re.I)
_TABLE_END = re.compile(r"^kwota\s+netto\s+do\s+zafakturowania", re.I)
_MD = re.compile(r"^\d+(?:[.,]\d+)?$")
_PLN = re.compile(r"^(\d[\d,.\xa0 ]*?)\s*(?:PLN|zł)$", re.I)
_AMOUNT = r"\d{1,3}(?:[ \xa0.,]\d{3})*[.,]\d{2}"
#: Wiersz tabeli w jednej linii: „… 20 19,200.00 PLN 23,616.00 PLN”.
_ROW = re.compile(
    r"(?:^|\s)(\d{1,2}(?:[.,]\d{1,3})?)\s+(" + _AMOUNT + r")\s*(?:PLN|zł)\s+"
    r"(" + _AMOUNT + r")\s*(?:PLN|zł)\s*$",
    re.I,
)
# Po pierwszej tabeli: nagłówek przekazanego maila albo ponowny początek treści.
_NEXT_MAIL = re.compile(
    r"^(?:from|od|sent|wysłano|subject|temat)\s*:|zaakceptowanego\s+odbioru", re.I
)


def _amount(text: str) -> Optional[Decimal]:
    """„21,120.00” i „21 120,00” → 21120.00."""

    cleaned = text.replace("\xa0", "").replace(" ", "")
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(",", "")
    try:
        return Decimal(cleaned.replace(",", "."))
    except ArithmeticError:
        return None


def parse_text(text: str) -> Optional[Declared]:
    if not _MARK.search(text):
        return None
    raw = [line for line in short_lines(text).splitlines() if line.strip()]
    quoted = [line.lstrip().startswith(">") for line in raw]
    lines = [line.lstrip("> \t").strip() for line in raw]
    person: Optional[str] = None
    month: Optional[str] = None
    md = Decimal("0")
    net = Decimal("0")
    rows = 0
    for index, line in enumerate(lines):
        if person is None and (found := _PERSON.match(line)):
            person = found.group(1).strip()
        if month is None and (found := _PERIOD.match(line)):
            month = month_in(found.group(1))
        if rows and (
            _TABLE_END.match(line) or quoted[index] or _NEXT_MAIL.search(line)
        ):
            # Czytamy tylko pierwszą tabelę: dalej jest jej cytat albo kopia.
            break
        if (
            0 < index < len(lines) - 1
            and _MD.match(lines[index - 1])
            and (found := _PLN.match(line))
            and _PLN.match(lines[index + 1])
        ):
            md += _amount(lines[index - 1]) or Decimal("0")
            net += _amount(found.group(1)) or Decimal("0")
            rows += 1
        elif found := _ROW.search(line):
            md += _amount(found.group(1)) or Decimal("0")
            net += _amount(found.group(2)) or Decimal("0")
            rows += 1
    return Declared(
        source=SOURCE,
        consultant=person,
        month=month,
        md=md if rows else None,
        amount=net if rows else None,
    )


def parse(content: bytes, mime: str) -> Optional[Declared]:
    mail = mail_text.read(content, mime)
    return parse_text(mail.body) if mail is not None else None
