"""Wspólny kontekst jednego renderu: dokument, „dziś”, daty ról, słowa kluczowe."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from app.services.cv_new_layout.document import NewCvDocument, Role
from app.services.cv_new_layout.facts import Span, parse_dates, year_fraction
from app.services.cv_new_layout.labels import labels_for
from app.services.cv_new_layout.text import Keywords


@dataclass(frozen=True)
class DatedRole:
    role: Role
    start: Optional[float]
    end: Optional[float]
    months_known: bool
    index: int  # kolejność w CV — tożsamość roli także po skróceniu końca na osi

    @property
    def span(self) -> Span:
        return Span(self.start, self.end, self.months_known)

    @property
    def months(self) -> int:
        if self.start is None or self.end is None:
            return 999
        return round((self.end - self.start) * 12)


@dataclass(frozen=True)
class Ctx:
    doc: NewCvDocument
    now: float
    keys: Keywords
    roles: tuple[DatedRole, ...]

    @property
    def lang(self) -> str:
        return self.doc.language

    @property
    def t(self) -> dict[str, str]:
        return labels_for(self.doc.language)

    def is_current(self, r: DatedRole) -> bool:
        return r.end is not None and r.end >= self.now - 0.01


def build_context(doc: NewCvDocument, today: Optional[date] = None) -> Ctx:
    if today is None:
        from app.core.scheduling import business_today

        today = business_today()
    now = year_fraction(today)
    roles = []
    for i, role in enumerate(doc.experience):
        span = parse_dates(role.dates, now)
        roles.append(DatedRole(role, span.start, span.end, span.months_known, i))
    return Ctx(
        doc=doc,
        now=now,
        keys=Keywords.build(doc.highlight_keywords),
        roles=tuple(roles),
    )
