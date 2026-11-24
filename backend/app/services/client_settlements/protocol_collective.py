"""Protokół odbioru zbiorczy klienta z godzinami kilku osób → MD osoby. Bez bazy.

Klienci z zamówień publicznych nie przysyłają miesięcznego RCP osoby, tylko
podpisany protokół odbioru dla całej umowy (próba IX–X 2026, kopia produkcji
z 23.11): Centrum e-Zdrowia — protokół na umowę wykonawczą, PFRON — jeden protokół
na wszystkie zlecenia. PM albo koordynatorka rozliczeń przekazuje go na
rozliczenia@. Faktury Finansów za IX i X mają te same godziny osób co protokoły
(PFRON IX: kwota brutto protokołu = faktura zbiorcza). Bez czytnika protokół stał
jako karta bez osoby, a osoby w „Przebiegu miesiąca” jako „brak raportu”.

Dwa wzory:

* CeZ: „Protokół odbioru · Nr umowy (Wykonawczej) CeZ/…”, okres „w okresie od
  DD.MM.RRRR do DD.MM.RRRR”, w tabeli „Zestawienie” wiersz osoby
  „Imię Nazwisko Suma 176”, pod nią „Suma końcowa 336”. Suma osób różna od
  „Suma końcowa” albo okres przez dwa miesiące = nie wzór (plik czeka na
  człowieka). Protokół jednej osoby bywa bez wiersza „… Suma” (imię i nazwisko
  w komórce rozbite na dwie linie): wtedy osobą jest tekst tabeli, a godzinami
  „Suma końcowa”; osobę z kontraktu musi dać się w nim znaleźć. Tabela
  przestawna („Suma z Godziny”, CeZ/177 za X 2026) ma wiersz osoby z sumą
  dopiero w tabeli szczegółów: bierzemy go, gdy suma osób to „Suma końcowa”.
* Imię w protokole inne niż w kartotece (zdrobnienie albo inne imię): osobę
  wskazuje numer umowy z protokołu, gdy w miesiącu pracuje na niej tylko osoba
  z kontraktu, a protokół ma jedną osobę (``by_agreement``).
* PFRON: „Protokół odbioru na usługi outsourcingu specjalistów IT”, blok na osobę
  „Specjalisty: Imię Nazwisko Rola” i „Liczba Roboczogodzin … : 196,5”. Miesiąca
  w treści nie ma: bierzemy okres dokumentu (z nazwy pliku albo tematu maila,
  nie zgadnięty z daty), inaczej kontrola ``proof.month`` bez MD.

MD = godziny / ``fields.md_hours`` (``declared.evaluate``).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping, Optional

from app.services.client_settlements import declared
from app.services.client_settlements.declared import PDF, number, pdf_text, short_lines
from app.services.client_settlements.rcp_checks import ProofResult, name_tokens

logger = logging.getLogger(__name__)

SOURCE_CEZ = "Protokół odbioru CeZ"
SOURCE_PFRON = "Protokół odbioru PFRON"
_TOLERANCE = Decimal("0.01")
_NUM = r"\d+(?:[.,]\d+)?"
_UPPER = "A-ZĄĆĘŁŃÓŚŹŻ"
# Dwa słowa z wielkiej litery i więcej: „Jan Testowy”, „Anna Inna-Nowak”.
_NAME = rf"[{_UPPER}][^\W\d_][\w'-]*(?:[ \t]+[{_UPPER}][^\W\d_][\w'-]*)+"
_PERSON_SUM = re.compile(rf"^({_NAME})[ \t]+Suma[ \t]+({_NUM})[ \t]*$", re.M)
_TOTAL = re.compile(rf"^Suma końcowa[ \t]+({_NUM})\b", re.M | re.I)
_DATE = r"(\d{1,2})\.(\d{1,2})\.(20\d{2})"
_PERIOD = re.compile(rf"w\s+okresie\*?\s*(?:od\s*)?{_DATE}\s*(?:do\s*)?{_DATE}", re.I)
_SPECIALIST = re.compile(r"^Specjalisty:[ \t]*(.+)$", re.M)
_PFRON_HOURS = re.compile(
    rf"Roboczogodzin.*?rozliczeniowym\s*:\s*({_NUM})", re.I | re.S
)
# „Nr umowy (Wykonawczej) CeZ/177/2026”, w PDF-ie bywa „CeZ / 177 / 2026” albo „CeZ_177_2026”.
_CEZ_CONTRACT = re.compile(
    r"nr\s+umowy[\s\S]{0,40}?\b(cez)\s*[/_]\s*(\d+)\s*[/_]\s*(20\d{2})", re.I
)


@dataclass(frozen=True)
class ProtocolPerson:
    #: Osoba z protokołu: „Imię Nazwisko”, „Imię Nazwisko Rola” (PFRON) albo
    #: tekst tabeli protokołu jednej osoby. Kontrakt pasuje, gdy jego imię
    #: i nazwisko stoją w tym tekście.
    name: str
    hours: Decimal


@dataclass(frozen=True)
class Protocol:
    source: str
    #: ``RRRR-MM`` z treści; ``None`` = z okresu dokumentu (PFRON).
    month: Optional[str]
    people: tuple[ProtocolPerson, ...]
    #: Numer umowy wykonawczej z treści (CeZ: „CeZ/177/2026”); ``None`` = brak w treści.
    contract: Optional[str] = None


def contract_key(number: Optional[str]) -> Optional[str]:
    """Numer umowy CeZ do porównania: „CeZ_177_2026”, „cez / 177 / 2026” → „CEZ/177/2026”."""

    found = re.search(r"\b(cez)\s*[/_]\s*(\d+)\s*[/_]\s*(20\d{2})", number or "", re.I)
    if found is None:
        return None
    return f"CEZ/{int(found.group(2))}/{found.group(3)}"


def _cez_contract(text: str) -> Optional[str]:
    found = _CEZ_CONTRACT.search(text[:3000])
    return contract_key(found.group(0)) if found else None


def _plain(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.replace("ł", "l").replace("Ł", "L"))
    return " ".join(folded.encode("ascii", "ignore").decode().lower().split())


def _cez_month(text: str) -> Optional[str]:
    found = _PERIOD.search(text)
    if found is None:
        return None
    _, start_month, start_year, _, end_month, end_year = found.groups()
    if (start_month, start_year) != (end_month, end_year):
        return None
    month = int(start_month)
    return f"{start_year}-{month:02d}" if 1 <= month <= 12 else None


def _cez(text: str) -> Optional[Protocol]:
    month = _cez_month(text)
    if month is None:
        return None
    # Tabela szczegółów pod „Podsumowaniem” ma sumy dni i własne wiersze „Suma”.
    head = re.split(r"^Podsumowanie projekt", text, maxsplit=1, flags=re.M)[0]
    total_found = _TOTAL.search(head)
    if total_found is None:
        return None
    total = number(total_found.group(1))
    if total is None:
        return None
    sums: dict[frozenset[str], list[Any]] = {}
    for found in _PERSON_SUM.finditer(head):
        hours = number(found.group(2))
        if hours is None:
            return None
        entry = sums.setdefault(
            frozenset(name_tokens(found.group(1))),
            [found.group(1).strip(), Decimal("0")],
        )
        entry[1] += hours
    if not sums:
        table = head[: total_found.start()].rsplit("podpis osoby uprawnionej)", 1)[-1]
        if len(name_tokens(table)) < 2:
            return None
        people = _pivot_people(text[len(head) :], table, total)
        if people is None:
            # Protokół jednej osoby: osoba z tekstu tabeli, godziny z „Suma końcowa”.
            people = (ProtocolPerson(table.strip(), total),)
        return Protocol(SOURCE_CEZ, month, people, _cez_contract(text))
    if abs(sum(hours for _, hours in sums.values()) - total) > _TOLERANCE:
        logger.info("protokół CeZ: suma osób ≠ „Suma końcowa”, bez MD")
        return None
    return Protocol(
        SOURCE_CEZ,
        month,
        tuple(ProtocolPerson(name, hours) for name, hours in sums.values()),
        _cez_contract(text),
    )


def _pivot_people(
    details: str, table: str, total: Decimal
) -> Optional[tuple[ProtocolPerson, ...]]:
    """Osoby zestawienia z tabeli przestawnej („Suma z Godziny”) z wierszy
    „Imię Nazwisko Suma N” tabeli szczegółów pod „Podsumowaniem”.

    W zestawieniu imię i nazwisko jest rozbite w komórce i nie ma wiersza osoby
    z sumą (CeZ/177 za X 2026), a tabela szczegółów go ma. Bierzemy go tylko,
    gdy suma osób to „Suma końcowa” zestawienia, a imię i nazwisko każdej stoją
    w tekście zestawienia; inaczej ``None`` (wiersze spod podsumowania to nie osoby)."""

    people: dict[frozenset[str], list[Any]] = {}
    for found in _PERSON_SUM.finditer(details):
        hours = number(found.group(2))
        tokens = frozenset(name_tokens(found.group(1)))
        if hours is None or not tokens <= name_tokens(table):
            return None
        people.setdefault(tokens, [found.group(1).strip(), Decimal("0")])[1] += hours
    if not people:
        return None
    if abs(sum(hours for _, hours in people.values()) - total) > _TOLERANCE:
        return None
    return tuple(ProtocolPerson(name, hours) for name, hours in people.values())


def _pfron(text: str) -> Optional[Protocol]:
    starts = list(_SPECIALIST.finditer(text))
    people: list[ProtocolPerson] = []
    for index, found in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        hours = _PFRON_HOURS.search(text, found.end(), end)
        value = number(hours.group(1)) if hours else None
        if value is not None and len(name_tokens(found.group(1))) >= 2:
            people.append(ProtocolPerson(found.group(1).strip(), value))
    return Protocol(SOURCE_PFRON, None, tuple(people)) if people else None


def parse_text(text: str) -> Optional[Protocol]:
    """Protokół z tekstu PDF albo ``None`` dla innego dokumentu."""

    text = short_lines(text)
    plain = _plain(text[:3000])
    if "protokol odbioru na uslugi outsourcingu specjalistow" in plain:
        return _pfron(text)
    if (
        plain.startswith("protokol odbioru")
        and "nr umowy" in plain
        and "suma koncowa" in _plain(text)
    ):
        return _cez(text)
    return None


def parse(content: bytes, mime: str) -> Optional[Protocol]:
    if mime != PDF or content[:5] != b"%PDF-":
        return None
    text = pdf_text(content)
    return parse_text(text) if text else None


def person_in(protocol: Protocol, person_name: str) -> Optional[ProtocolPerson]:
    """Jedyna osoba protokołu, w której tekście stoją imię i nazwisko z kontraktu."""

    wanted = name_tokens(person_name)
    if len(wanted) < 2:
        return None
    hits = [p for p in protocol.people if wanted <= name_tokens(p.name)]
    return hits[0] if len(hits) == 1 else None


def by_agreement(
    protocol: Protocol, agreements: frozenset[str]
) -> Optional[ProtocolPerson]:
    """Jedyna osoba protokołu, gdy jego numer umowy jest w ``agreements``.

    CeZ zawiera umowę wykonawczą na osobę, a w protokole bywa inne imię niż
    w kartotece: zdrobnienie albo inne imię (próba IX–X 2026, CeZ/177).
    ``agreements``: numery umów (``contract_key``), na których w miesiącu
    rozliczenia pracuje tylko osoba z kontraktu. Protokół kilku osób = ``None``."""

    if protocol.contract is None or len(protocol.people) != 1:
        return None
    return protocol.people[0] if protocol.contract in agreements else None


def evaluate(
    protocol: Protocol,
    *,
    month: str,
    doc_month: Optional[str],
    person_name: str,
    rules: Mapping[str, Mapping[str, Any]],
    working_days: int,
    other_md: Decimal = Decimal("0"),
    agreements: frozenset[str] = frozenset(),
) -> Optional[ProofResult]:
    """Kontrole i MD osoby; ``None``, gdy osoby w protokole nie ma.

    ``doc_month``: okres dokumentu z nazwy pliku albo tematu maila (nie zgadnięty),
    potrzebny dla protokołu bez miesiąca w treści. ``agreements``: umowy tylko tej
    osoby w miesiącu (``by_agreement``), gdy imię w protokole jest inne."""

    agreement = None
    person = person_in(protocol, person_name)
    if person is None:
        person = by_agreement(protocol, agreements)
        if person is None:
            return None
        agreement = protocol.contract
    return declared.evaluate(
        declared.Declared(
            source=protocol.source,
            consultant=person.name,
            month=protocol.month or doc_month,
            hours=person.hours,
            agreement=agreement,
        ),
        month=month,
        person_name=person_name,
        rules=rules,
        working_days=working_days,
        other_md=other_md,
    )
