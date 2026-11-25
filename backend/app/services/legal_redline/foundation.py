"""Cienka warstwa do fundamentu asystenta prawnego (część A planu).

Kontrakt z ``docs/asystent-prawny-plan.md``: pakiet ``app.services.legal``
z ``SourcePassage``, ``pseudonymize.mask/unmask`` i ``search_provisions``.
Część A powstaje równolegle, więc do scalenia działają tu ZAŚLEPKI o tym samym
interfejsie (oznaczone ``ZAŚLEPKA``). Po scaleniu części A sesja główna
podmienia je na import z ``app.services.legal`` i usuwa ten komentarz —
reszta pakietu ``legal_redline`` korzysta wyłącznie z tego modułu.

Sprawdzanie cytatów zmian (``verify_sources``) jest własne i zostaje: cytat
zmiany to dosłowny fragment źródła o danym ``ref``, a nie odwołanie w tekście,
które rozbiera ``citations.verify`` fundamentu.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from typing import Any, Literal

from app.services.legal_redline.model import ChangeSource

PassageKind = Literal["law", "contract", "client", "template", "case"]


@dataclass(frozen=True)
class SourcePassage:
    """ZAŚLEPKA (część A): ten sam kształt co ``app.services.legal.SourcePassage``."""

    kind: PassageKind
    ref: str
    text: str
    url: str | None = None
    label: str | None = None


@dataclass(frozen=True)
class Entity:
    """Dana osoby/firmy do zamaskowania: ``tag`` to znacznik bez nawiasów (``PARTNER``)."""

    tag: str
    value: str


# ── pseudonimizacja ─────────────────────────────────────────────────────────

_DETECTORS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?\d{4}){4,7}\b")),
    ("KONTO", re.compile(r"\b\d{2}(?:[ ]?\d{4}){6}\b")),
    ("PESEL", re.compile(r"\b\d{11}\b")),
    ("NIP", re.compile(r"\b\d{3}-?\d{3}-?\d{2}-?\d{2}\b")),
    ("TELEFON", re.compile(r"(?<!\d)(?:\+48[ ]?)?\d{3}[ -]\d{3}[ -]\d{3}(?!\d)")),
)


def detect_entities(text: str) -> list[Entity]:
    """Dane, które rozpoznaje sam kod (e-mail, konto, PESEL, NIP, telefon).

    Nazwiska i nazwy firm podaje wołający (z kontraktu) — z gołego tekstu
    umowy przysłanej przez klienta kod ich nie zgadnie.
    """

    found: list[Entity] = []
    taken: list[tuple[int, int]] = []
    for tag, pattern in _DETECTORS:
        for m in pattern.finditer(text):
            if any(s < m.end() and m.start() < e for s, e in taken):
                continue
            taken.append((m.start(), m.end()))
            found.append(Entity(tag, m.group()))
    return found


def mask(text: str, entities: list[Entity]) -> tuple[str, dict[str, str]]:
    """ZAŚLEPKA (część A): ``pseudonymize.mask`` — wartości → ``[TAG]``, ``[TAG_2]``…"""

    mapping: dict[str, str] = {}
    by_value: dict[str, str] = {}
    counters: dict[str, int] = {}
    for entity in sorted(entities, key=lambda e: len(e.value), reverse=True):
        value = entity.value.strip()
        if len(value) < 3 or value in by_value:
            continue
        counters[entity.tag] = counters.get(entity.tag, 0) + 1
        n = counters[entity.tag]
        marker = f"[{entity.tag}]" if n == 1 else f"[{entity.tag}_{n}]"
        by_value[value] = marker
        mapping[marker] = value
    for value, marker in sorted(
        by_value.items(), key=lambda kv: len(kv[0]), reverse=True
    ):
        text = text.replace(value, marker)
    return text, mapping


def unmask(text: str, mapping: dict[str, str]) -> str:
    """ZAŚLEPKA (część A): ``pseudonymize.unmask``."""

    for marker in sorted(mapping, key=len, reverse=True):
        text = text.replace(marker, mapping[marker])
    return text


# ── źródła ──────────────────────────────────────────────────────────────────


async def search_law(db: Any, query: str, *, limit: int = 8) -> list[SourcePassage]:
    """ZAŚLEPKA (część A): ``corpus.search_provisions`` — do scalenia bez przepisów.

    Bez korpusu model cytuje tylko sam dokument (i to sprawdza kod); zmiana
    bez podstawy w przepisie ma wtedy sam powód, bez cytatu.
    """

    return []


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[„”“\"«»]", '"', text)
    text = re.sub(r"[’‘']", "'", text)
    text = re.sub(r"[‐‑‒–—]", "-", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def verify_sources(
    sources: list[ChangeSource], passages: list[SourcePassage]
) -> list[ChangeSource]:
    """Stan każdego cytatu: ``ok`` (dosłownie w źródle), ``mismatch`` (źródło jest,
    cytatu w nim nie ma), ``missing`` (źródła o tym ``ref`` nie podaliśmy)."""

    by_ref = {p.ref: p for p in passages}
    checked = []
    for source in sources:
        passage = by_ref.get(source.ref)
        if passage is None:
            state = "missing"
        elif source.quote.strip() and _normalize(source.quote) in _normalize(
            passage.text
        ):
            state = "ok"
        else:
            state = "mismatch"
        checked.append(
            replace(
                source,
                state=state,
                kind=passage.kind if passage else source.kind,
                url=passage.url if passage else source.url,
                label=source.label
                or (passage.label if passage and passage.label else source.ref),
            )
        )
    return checked
