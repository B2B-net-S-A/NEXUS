"""Kontrola ogłoszenia przed skopiowaniem na portal — deterministyczna.

Model dostaje zakazy w prompcie, ale prompt nie jest gwarancją, a rekruter
może dopisać cokolwiek ręcznie. Dlatego kontrola biegnie po każdym zapisie
i front kopiuje tylko wtedy, gdy nie ma znalezisk blokujących.

Sprawdzane jest WSZYSTKO, co może trafić do schowka — nie tylko pola, które
rekruter edytuje: także warunki składane z rekrutacji (miasto), stałe bloki
z Ustawień i na końcu komplet napisów z ``render.rendered_texts``.

* **Blokują** — reguły strony kariery (``public_profile_lint``, jedno
  źródło dla obu miejsc): nazwa klienta, nazwisko, dane kontaktowe (e-mail,
  także zapisany jako „jan [at] firma”, telefon, link) oraz kwota z walutą
  albo stawką, także słownie („200 złotych”, „30 tys. netto”), i liczba przy
  słowie o wynagrodzeniu („widełki 20–25k”, „budżet: 25 000”; decyzja Artura
  14.10.2026).
* **Doradzają** — tylko tutaj, bo strona kariery nie ma poziomu „uwaga”:
  liczba przy słowie „stawka”/„rate” bez waluty (bywa „rate limiting …
  Java 17”), adres strony bez „www” i wzorce z pomiaru naszych ogłoszeń
  12.10.2026: nagłówki wewnętrznego formularza requestu („Stawka
  kandydata”), liczby MD, numer zlecenia, wymaganie w jednym–dwóch słowach,
  pusty start, długość albo sekcja.

O tym, czy kwota blokuje, decydują TE SAME wzorce, którymi znalazła ją
strona kariery (``CERTAIN_MONEY_PATTERNS`` i ``PAY_WORD_MONEY_PATTERN``) —
własna, węższa kopia przepuszczała „15 tysięcy zł” i „180/godzinę” jako uwagę.

Każdy tekst jest przed porównaniem sprowadzany do postaci bez znaków
niewidocznych (``public_profile_lint.for_lint``): nazwa klienta z miękkim
łącznikiem w środku to nadal nazwa klienta.

Czysta funkcja: nazwy klienta i osób podaje wołający.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Optional, Sequence

from app.services.public_city import address_match
from app.services.public_profile_lint import (
    CERTAIN_MONEY_PATTERNS,
    CODE_CLIENT,
    CODE_CONTACT,
    CODE_MONEY,
    CODE_PERSON,
    PAY_WORD_MONEY_PATTERN,
    for_lint,
    lint_public_texts,
)

SEVERITY_BLOCK = "block"
SEVERITY_ADVISE = "advise"

CODE_POSSIBLE_MONEY = "possible_money"
CODE_LINK = "link"
CODE_INTERNAL_HEADING = "internal_heading"
CODE_MAN_DAYS = "man_days"
CODE_REQUEST_REF = "request_ref"
CODE_SHORT_REQUIREMENT = "short_requirement"
CODE_MISSING_START = "missing_start"
CODE_MISSING_DURATION = "missing_duration"
CODE_EMPTY_SECTION = "empty_section"
CODE_ADDRESS = "address"

# Pola ogłoszenia w kolejności, w jakiej czyta je rekruter.
TEXT_FIELDS = ("title", "lead", "about", "start", "duration", "language", "city")
LIST_FIELDS = ("responsibilities", "requirements", "nice_to_have", "offer")
# Miejsca poza treścią, którą rekruter poprawia w oknie.
FIELD_TERMS = "terms"
FIELD_FIXED = "fixed"

_BLOCK_MESSAGES = {
    CODE_CLIENT: "Nazwa klienta w treści: „{excerpt}”. Klienta opisujemy branżą.",
    CODE_MONEY: (
        "Kwota w treści: „{excerpt}”. Widełki podajesz tylko w polu "
        "wynagrodzenia portalu."
    ),
    CODE_CONTACT: (
        "Dane kontaktowe w treści: „{excerpt}”. Kandydat aplikuje przez portal."
    ),
    CODE_PERSON: "Nazwisko w treści: „{excerpt}”. W ogłoszeniu nie podajemy nazwisk.",
}
_POSSIBLE_MONEY_MESSAGE = (
    "Sprawdź, czy to nie kwota: „{excerpt}”. Widełki podajesz tylko w polu "
    "wynagrodzenia portalu."
)
# Liczba przy słowie o wynagrodzeniu bez waluty bywa czym innym („moduł
# wynagrodzeń dla 10 tys. pracowników”) — rekruter musi wiedzieć, jak wyjść.
_PAY_WORD_HINT = " Jeśli to nie kwota, napisz zdanie bez liczby przy tym słowie."
_WHERE_TO_FIX = {
    FIELD_TERMS: " To pole idzie z rekrutacji — popraw miasto w Profilu Championa.",
    FIELD_FIXED: (
        " To stały blok firmy — poprawia się go w Ustawienia → Rekrutacja → "
        "Stałe części ogłoszenia."
    ),
}

# Adres bez „www”: zwykle strona klienta. Bez końcówek „.net”, „.io”, „.js” —
# to nazwy technologii (ASP.NET, socket.io, Node.js).
_BARE_DOMAIN = re.compile(
    r"(?<![@\w./-])[\w-]+(?:\.[\w-]+)*\.(?:pl|com|eu|org|de|uk)\b(?:/\S*)?",
    re.IGNORECASE,
)
_INTERNAL_HEADING = re.compile(
    r"\b(?:stawka kandydata|nazwa roli|podsumowanie profilu|"
    r"co mo[żz]e zach[ęe]ci[ćc] kandydata|minimum lat do[śs]wiadczenia|"
    r"wymagany zakres do[śs]wiadczenia|dni pracy stacjonarnej)\b",
    re.IGNORECASE,
)
# Tylko wersalikami: „must-have” w zdaniu jest zwykłym słowem, „MUST-HAVE”
# to nagłówek skopiowany z formularza requestu.
_SHOUT_HEADING = re.compile(r"\b(?:MUST[- ]HAVE|NICE[- ]TO[- ]HAVE)\b")
_MAN_DAYS = re.compile(r"(?<![\w/])\d+\s?MD\b")
_REQUEST_REF = re.compile(r"\b(?:RITM|REQ|REK|INC)[-_ ]?\d{3,}\b", re.IGNORECASE)
_WORD = re.compile(r"[^\W_]+")

_ADVICE_PATTERNS = (
    (
        _INTERNAL_HEADING,
        CODE_INTERNAL_HEADING,
        "To wygląda na nagłówek wewnętrznego formularza: „{excerpt}”. "
        "Kandydat nie powinien go zobaczyć.",
    ),
    (
        _SHOUT_HEADING,
        CODE_INTERNAL_HEADING,
        "To wygląda na nagłówek skopiowany z requestu: „{excerpt}”.",
    ),
    (
        _MAN_DAYS,
        CODE_MAN_DAYS,
        "Liczba MD w treści: „{excerpt}”. To rozliczenie z klientem, "
        "nie informacja dla kandydata.",
    ),
    (_REQUEST_REF, CODE_REQUEST_REF, "Numer zlecenia w treści: „{excerpt}”."),
    (
        _BARE_DOMAIN,
        CODE_LINK,
        "Adres strony w treści: „{excerpt}”. Sprawdź, czy nie wskazuje "
        "klienta — linków w ogłoszeniu nie podajemy.",
    ),
)


@dataclass(frozen=True)
class AdFinding:
    code: str
    severity: str
    message: str
    excerpt: Optional[str]
    field: Optional[str]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _strings(value: Any) -> list[str]:
    texts = (
        for_lint(item).strip()
        for item in (value if isinstance(value, (list, tuple)) else [])
        if isinstance(item, str)
    )
    return [text for text in texts if text]


def _field_texts(content: dict[str, Any], tech: Any) -> list[tuple[str, list[str]]]:
    rows: list[tuple[str, list[str]]] = []
    for key in TEXT_FIELDS:
        value = for_lint(str(content.get(key) or "")).strip()
        if value:
            rows.append((key, [value]))
    for key in LIST_FIELDS:
        items = _strings(content.get(key))
        if items:
            rows.append((key, items))
    names = _strings(
        [item.get("name") for item in tech or [] if isinstance(item, dict)]
    )
    if names:
        rows.append(("tech", names))
    return rows


def _excerpt(text: str, match: re.Match[str]) -> str:
    start = max(0, match.start() - 30)
    end = min(len(text), match.end() + 30)
    out = text[start:end].strip()
    return ("…" if start > 0 else "") + out + ("…" if end < len(text) else "")


def _from_public_lint(
    field: Optional[str],
    texts: list[str],
    *,
    client_names: list[str | None],
    person_names: list[str | None],
) -> list[AdFinding]:
    out: list[AdFinding] = []
    for found in lint_public_texts(
        texts, client_names=client_names, person_names=person_names
    ):
        where = _WHERE_TO_FIX.get(field or "", "")
        money = found.code == CODE_MONEY
        certain = money and _certain_money(found.excerpt)
        pay_word = money and not certain and _pay_word(found.excerpt)
        if money and not (certain or pay_word):
            out.append(
                AdFinding(
                    code=CODE_POSSIBLE_MONEY,
                    severity=SEVERITY_ADVISE,
                    message=_POSSIBLE_MONEY_MESSAGE.format(excerpt=found.excerpt)
                    + where,
                    excerpt=found.excerpt,
                    field=field,
                )
            )
            continue
        out.append(
            AdFinding(
                code=found.code,
                severity=SEVERITY_BLOCK,
                message=_BLOCK_MESSAGES[found.code].format(excerpt=found.excerpt)
                + (_PAY_WORD_HINT if pay_word else "")
                + where,
                excerpt=found.excerpt,
                field=field,
            )
        )
    return out


def _certain_money(excerpt: str) -> bool:
    """Wycinek znaleziska zawiera całe dopasowanie, a wzorce pewne idą
    w ``lint_public_texts`` przed wzorcem „stawka N” — więc pewna kwota
    w zdaniu zawsze jest w wycinku."""
    return any(pattern.search(excerpt) for pattern in CERTAIN_MONEY_PATTERNS)


def _pay_word(excerpt: str) -> bool:
    """Liczba przy „budżet / widełki / wynagrodzenie / salary / pensja /
    zarobki” blokuje jak na stronie kariery (decyzja Artura 14.10.2026).
    Ten wzorzec też idzie przed „stawka N”, więc trafienie jest w wycinku."""
    return PAY_WORD_MONEY_PATTERN.search(excerpt) is not None


def _advice(field: str, texts: list[str]) -> list[AdFinding]:
    out: list[AdFinding] = []
    for text in texts:
        for pattern, code, message in _ADVICE_PATTERNS:
            match = pattern.search(text)
            if match:
                excerpt = _excerpt(text, match)
                out.append(
                    AdFinding(
                        code=code,
                        severity=SEVERITY_ADVISE,
                        message=message.format(excerpt=excerpt),
                        excerpt=excerpt,
                        field=field,
                    )
                )
    return out


def _address(field: str, texts: Sequence[str]) -> list[AdFinding]:
    """Adres biura pozwala wygooglować klienta (zgłoszenie 28.10.2026).

    Uwaga, nie blokada (decyzja Artura): nazwa ulicy w opisie projektu bywa
    niewinna.
    """
    out: list[AdFinding] = []
    for text in texts:
        match = address_match(text)
        if match:
            excerpt = _excerpt(text, match)
            out.append(
                AdFinding(
                    code=CODE_ADDRESS,
                    severity=SEVERITY_ADVISE,
                    message=(
                        f"Adres w treści: „{excerpt}”. Po adresie łatwo "
                        "rozpoznać klienta — zostaw samo miasto."
                    ),
                    excerpt=excerpt,
                    field=field,
                )
            )
    return out


def _short_requirements(items: Iterable[str]) -> Optional[AdFinding]:
    short = [item for item in items if len(_WORD.findall(item)) < 3]
    if not short:
        return None
    listed = ", ".join(f"„{item}”" for item in short[:5])
    return AdFinding(
        code=CODE_SHORT_REQUIREMENT,
        severity=SEVERITY_ADVISE,
        message=(
            f"Wymagania w jednym–dwóch słowach: {listed}. Kandydat nie wie, "
            "jakiego doświadczenia oczekujesz."
        ),
        excerpt=None,
        field="requirements",
    )


def _missing(content: dict[str, Any]) -> list[AdFinding]:
    out: list[AdFinding] = []
    for key, code, message in (
        ("start", CODE_MISSING_START, "Brak daty startu projektu."),
        ("duration", CODE_MISSING_DURATION, "Brak długości współpracy."),
    ):
        if not str(content.get(key) or "").strip():
            out.append(AdFinding(code, SEVERITY_ADVISE, message, None, key))
    for key, label in (
        ("responsibilities", "zakresu obowiązków"),
        ("requirements", "wymagań"),
    ):
        if not _strings(content.get(key)):
            out.append(
                AdFinding(
                    CODE_EMPTY_SECTION,
                    SEVERITY_ADVISE,
                    f"Ogłoszenie nie ma {label} — dopisz je albo uzupełnij "
                    "Profil Championa i przygotuj ogłoszenie ponownie.",
                    None,
                    key,
                )
            )
    return out


def lint_ad(
    content: dict[str, Any],
    tech: Any,
    *,
    terms: Sequence[str] = (),
    fixed: Sequence[str] = (),
    rendered: Sequence[str] = (),
    client_names: Iterable[str | None] = (),
    person_names: Iterable[str | None] = (),
) -> list[AdFinding]:
    """Znaleziska dla zapisanej treści; blokujące stoją na początku listy.

    ``terms`` — warunki złożone z rekrutacji, ``fixed`` — stałe bloki,
    ``rendered`` — komplet napisów do schowka (ostatnia siatka: znalezisko,
    którego nie przypisało żadne pole, dostaje ``field=None``).
    """
    names = {"client_names": list(client_names), "person_names": list(person_names)}
    found: list[AdFinding] = []

    def covered(item: AdFinding) -> bool:
        """To samo znalezisko widziane drugi raz — np. w polu i w złożonym
        z niego wierszu („start: …”)."""
        return item.excerpt is not None and any(
            other.code == item.code
            and other.excerpt is not None
            and (other.excerpt in item.excerpt or item.excerpt in other.excerpt)
            for other in found
        )

    def add(items: Iterable[AdFinding]) -> None:
        for item in items:
            if not covered(item):
                found.append(item)

    for field, texts in _field_texts(content, tech):
        add(_from_public_lint(field, texts, **names))
        add(_advice(field, texts))
        add(_address(field, texts))
    add(_from_public_lint(FIELD_TERMS, _strings(list(terms)), **names))
    add(_address(FIELD_TERMS, _strings(list(terms))))
    add(_from_public_lint(FIELD_FIXED, _strings(list(fixed)), **names))
    add(_from_public_lint(None, _strings(list(rendered)), **names))
    short = _short_requirements(_strings(content.get("requirements")))
    if short is not None:
        found.append(short)
    found.extend(_missing(content))
    return sorted(found, key=lambda item: item.severity != SEVERITY_BLOCK)


def lint_fixed_blocks(texts: Iterable[str]) -> list[AdFinding]:
    """Stałe bloki przy zapisie w Ustawieniach: bez kwot i danych kontaktowych.

    Blok trafia do KAŻDEGO ogłoszenia, a rekruter nie ma go jak poprawić.
    """
    return [
        finding
        for finding in _from_public_lint(
            None, _strings(list(texts)), client_names=[], person_names=[]
        )
        if finding.severity == SEVERITY_BLOCK
    ]


def has_blocking(findings: Iterable[AdFinding]) -> bool:
    return any(f.severity == SEVERITY_BLOCK for f in findings)
