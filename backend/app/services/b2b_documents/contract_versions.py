"""Numery paragrafów umowy bazowej, które cytują aneksy i rozwiązania.

Wzory działu miały paragrafy wpisane na sztywno — i w czterech z nich były to
paragrafy STAREJ umowy (data startu § 12 zamiast § 13, zakaz konkurencji § 7
zamiast § 10, wypowiedzenie § 2 i 30 dni zamiast § 12 i miesiąca na koniec
miesiąca, oddelegowanie z nieistniejącym § 2 ust. 5). Aneks, który cytuje zły
paragraf, zmienia nie to, co miał zmienić.

Dlatego paragraf jest parametrem wersji wzoru umowy bazowej
(``b2b_generated_contracts.template_version``). Umowa bez znanej wersji (wiersz
z importu Excela) nie dostaje zgadniętych numerów — formularz dokumentu prosi
o nie, podpowiadając wersję 2026.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta

CURRENT_VERSION = "2026"


@dataclass(frozen=True)
class ContractVersionRefs:
    rate_paragraph: str
    start_paragraph: str
    appendix_start: str
    non_compete_paragraph: str
    notice_paragraph: str
    notice_period_pl: str
    notice_period_en: str
    ip_paragraph: str
    personal_data_paragraph: str
    confidentiality_paragraph: str
    #: Liczba pełnych miesięcy wypowiedzenia i czy skutek na koniec miesiąca.
    notice_months: int
    notice_to_month_end: bool

    def as_context(self) -> dict[str, str]:
        return {k: v for k, v in asdict(self).items() if isinstance(v, str)}


VERSIONS: dict[str, ContractVersionRefs] = {
    "2026": ContractVersionRefs(
        rate_paragraph="§ 6 ust. 1",
        start_paragraph="§ 13 ust. 2",
        appendix_start="Załącznik nr 3",
        non_compete_paragraph="§ 10 ust. 1",
        notice_paragraph="§ 12 ust. 2 pkt 2",
        notice_period_pl="1 (jednego) miesiąca ze skutkiem na koniec miesiąca kalendarzowego",
        notice_period_en="one (1) month, effective at the end of a calendar month",
        ip_paragraph="§ 5",
        personal_data_paragraph="§ 7 i § 7A",
        confidentiality_paragraph="§ 8",
        notice_months=1,
        notice_to_month_end=True,
    ),
}

#: Pola, o które formularz pyta, gdy wersja umowy bazowej jest nieznana.
REF_FIELDS: tuple[str, ...] = tuple(
    k for k, v in asdict(VERSIONS[CURRENT_VERSION]).items() if isinstance(v, str)
)


def refs_for(version: str | None) -> ContractVersionRefs | None:
    return VERSIONS.get(version or "")


def default_refs() -> ContractVersionRefs:
    return VERSIONS[CURRENT_VERSION]


def _month_end(day: date) -> date:
    nxt = day.replace(day=28) + timedelta(days=4)
    return nxt - timedelta(days=nxt.day)


def notice_end_date(delivered_on: date, refs: ContractVersionRefs) -> date:
    """Dzień rozwiązania umowy po wypowiedzeniu doręczonym ``delivered_on``.

    Umowa 2026: miesiąc ze skutkiem na koniec miesiąca kalendarzowego — czyli
    ostatni dzień miesiąca następującego po miesiącu doręczenia (doręczone
    15.09 → 31.10)."""
    month = delivered_on.month - 1 + refs.notice_months
    year = delivered_on.year + month // 12
    month = month % 12 + 1
    if refs.notice_to_month_end:
        return _month_end(date(year, month, 1))
    last = _month_end(date(year, month, 1)).day
    return date(year, month, min(delivered_on.day, last))
