"""Propozycja NEXUSA „zna / korzysta” dla technologii premium z umowy ramowej (F3, 15.11.2026).

Dopłata za technologię wymaga dwóch rzeczy: konsultant ją ZNA i NA PROJEKCIE
klienta z niej KORZYSTA (klient odmawia, gdy technologia jest „nice to have”
albo „używana sporadycznie”). NEXUS składa propozycję z tego, co ma:

* **zna** — technologia w CV, na osi czasu CV albo zweryfikowana na screeningu;
* **korzysta** — karta techniczna kontraktu z rozmowy opiekuna (stack tego
  projektu) albo oś czasu CV oznacza ją jako bieżącą.

To propozycja, nie decyzja: zatwierdza Delivery Lead, potwierdza klient
(decyzja Artura z 15.11.2026). Tu tylko czyste funkcje na danych wejściowych.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

# Ogólna wiedza o nazwach technologii (nie dane klienta): aliasy, pod którymi
# technologia bywa zapisana w CV i w kartach technicznych.
_ALIASES: dict[str, tuple[str, ...]] = {
    "kubernetes": ("kubernetes", "k8s", "openshift", "aks", "eks", "gke"),
    "hadoop": ("hadoop", "hdfs", "hdp", "cloudera"),
    "t24 (temenos transact)": ("t24", "temenos"),
    "cyber ark": ("cyberark", "cyber ark"),
    "sap bw/hana": ("sap bw", "bw/4hana", "s/4hana", "sap hana", "hana"),
    "big data": ("big data", "bigdata"),
    "ibm mdm": ("ibm mdm", "infosphere mdm", "ibm master data"),
    "spark": ("spark", "pyspark"),
    "pega": ("pega", "pegasystems"),
}


def _norm(text: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (text or "").casefold()).strip()


def patterns_for(technology: str) -> tuple[re.Pattern, ...]:
    """Wzorce słowa dla technologii z umowy (np. „T24 (Temenos Transact)” → t24, temenos)."""
    names = _ALIASES.get(_norm(technology)) or (_norm(technology),)
    return tuple(
        re.compile(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])")
        for name in names
        if name
    )


def mentions(technology: str, text: Optional[str]) -> bool:
    value = _norm(text)
    return bool(value) and any(p.search(value) for p in patterns_for(technology))


@dataclass(frozen=True)
class UsageRow:
    skill: str
    months: Optional[int]
    is_current: bool


@dataclass(frozen=True)
class PersonSkills:
    cv_skills: tuple[str, ...] = ()
    verified: tuple[str, ...] = ()
    usage: tuple[UsageRow, ...] = ()
    tech_card: tuple[str, ...] = ()


@dataclass(frozen=True)
class TechEvidence:
    technology: str
    percent: str
    knows: bool
    uses: bool
    sources: tuple[str, ...] = field(default_factory=tuple)


def skill_names(raw: object) -> tuple[str, ...]:
    """Nazwy z ``candidates.skills`` / ``verified_tech`` (lista słowników albo napisów)."""
    if not isinstance(raw, list):
        return ()
    out = []
    for item in raw:
        if isinstance(item, dict):
            name = item.get("name")
        else:
            name = item
        if isinstance(name, str) and name.strip():
            out.append(name.strip())
    return tuple(out)


def evidence_for(technology: str, percent: str, person: PersonSkills) -> TechEvidence:
    sources: list[str] = []
    if any(mentions(technology, s) for s in person.cv_skills):
        sources.append("CV")
    usage = [u for u in person.usage if mentions(technology, u.skill)]
    if usage:
        months = max((u.months or 0) for u in usage)
        current = any(u.is_current for u in usage)
        sources.append(
            "oś czasu CV"
            + (f": {months} mies." if months else "")
            + (", obecnie" if current else "")
        )
    if any(mentions(technology, s) for s in person.verified):
        sources.append("zweryfikowane na screeningu")
    on_card = any(mentions(technology, s) for s in person.tech_card)
    if on_card:
        sources.append("karta techniczna projektu (opieka)")
    knows = bool(sources)
    uses = on_card or any(u.is_current for u in usage)
    return TechEvidence(technology, percent, knows, uses, tuple(sources))


def evidence(
    technologies: Iterable[tuple[str, str]], person: PersonSkills
) -> list[TechEvidence]:
    """Dowody dla wszystkich technologii z umowy; najpierw „korzysta”, potem „zna”."""
    rows = [evidence_for(tech, pct, person) for tech, pct in technologies]
    return sorted(
        (r for r in rows if r.knows or r.uses),
        key=lambda r: (not r.uses, not r.knows, -float(r.percent), r.technology),
    )
