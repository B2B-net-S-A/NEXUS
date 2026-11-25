"""Dane osób i firm do modelu wyłącznie jako znaczniki (decyzja Artura 25.11.2026).

``mask`` zamienia podane wartości (imię i nazwisko Partnera, nazwa firmy,
adres, NIP …) na znaczniki ``[PARTNER]``, ``[NIP]``; druga inna wartość tej
samej etykiety dostaje ``[PARTNER_2]``. Dodatkowo, bez podawania, wyłapuje
numery i adresy, które zdradzają osobę: PESEL i NIP (z cyfrą kontrolną),
rachunek bankowy, e-mail i telefon. ``unmask`` podmienia znaczniki z powrotem
po stronie NEXUSA; znacznik spoza mapy zostaje i pokazuje go
``unknown_tokens`` (model coś wymyślił).

Imiona i nazwiska odmieniają się („Jana Kowalskiego”), więc przy
``inflect=True`` każde słowo pasuje z końcówką, a samo nazwisko też jest
maskowane. Wielkość liter i odstępy nie mają znaczenia; w numerach — także
spacje i myślniki.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

_TOKEN = re.compile(r"\[([A-ZĄĆĘŁŃÓŚŹŻ]+(?:_[A-ZĄĆĘŁŃÓŚŹŻ]+)*(?:_\d+)?)\]")
_UNMASK = re.compile(r"(\[[A-ZĄĆĘŁŃÓŚŹŻ]+(?:_[A-ZĄĆĘŁŃÓŚŹŻ]+)*(?:_\d+)?\])(\.?)")
_LABEL = re.compile(r"^[A-ZĄĆĘŁŃÓŚŹŻ]+(?:_[A-ZĄĆĘŁŃÓŚŹŻ]+)*$")


@dataclass(frozen=True)
class Entity:
    """Wartość do ukrycia: ``Entity("PARTNER", "Jan Kowalski", inflect=True)``."""

    label: str
    value: str
    inflect: bool = False


def _digits_pattern(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    return r"(?<!\d)" + r"[\s-]?".join(digits) + r"(?!\d)"


def _word_pattern(word: str, inflect: bool) -> str:
    if not inflect or len(word) < 3 or not word.isalpha():
        return re.escape(word)
    stem = word[:-1] if word[-1].lower() in "aeiouyąęó" else word
    if len(stem) < 3:
        stem = word
    return re.escape(stem) + r"\w{0,4}"


def _value_pattern(entity: Entity) -> str | None:
    value = entity.value.strip()
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    if len(digits) >= 6 and len(digits) >= 0.7 * len(re.sub(r"\s", "", value)):
        return _digits_pattern(value)
    words = value.split()
    body = r"\s+".join(_word_pattern(word, entity.inflect) for word in words)
    return r"(?<!\w)" + body + r"(?!\w)"


def _pesel_ok(digits: str) -> bool:
    weights = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)
    total = sum(int(d) * w for d, w in zip(digits, weights))
    return (10 - total % 10) % 10 == int(digits[10])


def _nip_ok(digits: str) -> bool:
    weights = (6, 5, 7, 2, 3, 4, 5, 6, 7)
    total = sum(int(d) * w for d, w in zip(digits, weights)) % 11
    return total != 10 and total == int(digits[9])


_AUTO: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    (
        "RACHUNEK",
        re.compile(r"(?<!\w)(?:PL\s?)?\d{2}(?:[\s-]?\d{4}){6}(?!\d)", re.IGNORECASE),
    ),
    ("PESEL", re.compile(r"(?<!\d)\d{11}(?!\d)")),
    (
        "NIP",
        re.compile(
            r"(?<!\d)(?:\d{10}|\d{3}-\d{3}-\d{2}-\d{2}|\d{3}-\d{2}-\d{2}-\d{3})(?!\d)"
        ),
    ),
    (
        "TELEFON",
        re.compile(r"(?<![\w+])(?:\+48[\s-]?)?\d{3}[\s-]\d{3}[\s-]\d{3}(?!\d)"),
    ),
)


def _auto_valid(label: str, surface: str) -> bool:
    digits = re.sub(r"\D", "", surface)
    if label == "PESEL":
        return _pesel_ok(digits)
    if label == "NIP":
        return len(digits) == 10 and _nip_ok(digits)
    return True


class _Tokens:
    def __init__(self) -> None:
        self.mapping: dict[str, str] = {}
        self._by_value: dict[tuple[str, str], str] = {}
        self._count: dict[str, int] = {}

    def token(self, label: str, value: str) -> str:
        norm = (label, re.sub(r"\s+", " ", value.strip().lower()))
        if norm in self._by_value:
            return self._by_value[norm]
        count = self._count.get(label, 0) + 1
        self._count[label] = count
        token = f"[{label}]" if count == 1 else f"[{label}_{count}]"
        self._by_value[norm] = token
        self.mapping[token] = value.strip()
        return token


def mask(
    text: str, entities: Iterable[Entity] = (), *, detect: bool = True
) -> tuple[str, dict[str, str]]:
    """Tekst ze znacznikami zamiast danych i mapa ``znacznik → wartość``."""
    tokens = _Tokens()
    rules: list[tuple[str, str]] = []
    for entity in entities:
        label = entity.label.strip().upper()
        if not _LABEL.match(label):
            raise ValueError(
                f"Etykieta znacznika tylko z liter i „_”: {entity.label!r}"
            )
        pattern = _value_pattern(entity)
        if pattern is None:
            continue
        token = tokens.token(label, entity.value)
        rules.append((pattern, token))
        words = entity.value.split()
        if entity.inflect and len(words) > 1 and len(words[-1]) >= 4:
            rules.append(
                (r"(?<!\w)" + _word_pattern(words[-1], True) + r"(?!\w)", token)
            )
    # Dłuższe wartości najpierw: „Jan Kowalski” przed samym „Kowalski”.
    rules.sort(key=lambda rule: -len(rule[0]))

    def _auto(text: str, detectors: Iterable[tuple[str, re.Pattern[str]]]) -> str:
        for label, pattern in detectors:

            def _replace(match: re.Match[str], label: str = label) -> str:
                surface = match.group(0)
                if not _auto_valid(label, surface):
                    return surface
                return tokens.token(label, surface)

            text = pattern.sub(_replace, text)
        return text

    masked = text or ""
    if detect:
        # E-mail przed nazwiskami: „jan.kowalski@…” po masce nazwiska byłby
        # „jan.[PARTNER]@…” i reszta adresu szłaby do modelu jawnie.
        masked = _auto(masked, _AUTO[:1])
    for pattern, token in rules:
        masked = re.sub(pattern, token, masked, flags=re.IGNORECASE)
    if detect:
        masked = _auto(masked, _AUTO[1:])
    return masked, dict(tokens.mapping)


def unmask(text: str, mapping: dict[str, str]) -> str:
    """Znaczniki z mapy → prawdziwe wartości; nieznane zostają bez zmian.

    Wartość kończąca się kropką („31 stycznia 2027 r.”) przed kropką zdania
    nie daje „r..”.
    """

    def _replace(match: re.Match[str]) -> str:
        token, dot = match.group(1), match.group(2)
        value = mapping.get(token)
        if value is None:
            return match.group(0)
        if dot and value.endswith("."):
            return value
        return value + dot

    return _UNMASK.sub(_replace, text or "")


def unknown_tokens(text: str, mapping: dict[str, str]) -> list[str]:
    """Znaczniki w tekście, których nie ma w mapie (w kolejności, bez powtórek)."""
    seen: list[str] = []
    for match in _TOKEN.finditer(text or ""):
        token = match.group(0)
        if token not in mapping and token not in seen:
            seen.append(token)
    return seen


def entities_from(
    pairs: Sequence[tuple[str, str]],
    *,
    inflect_labels: Iterable[str] = ("PARTNER", "OSOBA", "KONSULTANT", "PODPISUJACY"),
) -> list[Entity]:
    """Skrót dla wołających: pary (etykieta, wartość) → ``Entity``."""
    names = {label.upper() for label in inflect_labels}
    return [
        Entity(label, value, inflect=label.upper() in names) for label, value in pairs
    ]


def partner_entities(partner: Mapping[str, str]) -> list[Entity]:
    """Dane Partnera (``trainings.agreement.partner_from_contract``) do maski.

    Wzór: ``letter_service._model_entities``.

    Imię i nazwisko z odmianą (samo nazwisko też), adres w całości i osobno
    ulica oraz kod z miejscowością — w umowie często stoją w dwóch wierszach;
    ulica z odmianą („przy ul. Długiej 5”).
    """
    address = ", ".join(
        p for p in (partner.get("address"), partner.get("postal_city")) if p
    )
    pairs = [
        Entity("PARTNER", partner.get("full_name") or "", inflect=True),
        Entity("FIRMA_PARTNERA", partner.get("company") or ""),
        Entity("NIP", partner.get("nip") or ""),
        Entity("REGON", partner.get("regon") or ""),
        Entity("ADRES_PARTNERA", address, inflect=True),
        Entity("ADRES_PARTNERA", partner.get("address") or "", inflect=True),
        Entity("ADRES_PARTNERA", partner.get("postal_city") or ""),
        Entity("EMAIL_PARTNERA", partner.get("email") or ""),
        Entity("TELEFON_PARTNERA", partner.get("phone") or ""),
    ]
    return [e for e in pairs if e.value.strip()]
