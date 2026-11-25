"""Źródła bez API: sam link wyszukiwarki (stan z 25.11.2026).

- **CBOSA** (orzeczenia NSA i WSA, ``orzeczenia.nsa.gov.pl``) — brak API,
  tylko formularz HTML; z laptopa i z narzędzia do pobierania stron serwis
  nie odpowiadał (brak połączenia / HTTP 500), regulaminu automatu nie dało
  się przeczytać. SAOS sądów administracyjnych nie ma.
- **EUREKA** (interpretacje KIS, ``eureka.mf.gov.pl``) — aplikacja w
  przeglądarce na wewnętrznym API ``/api/public/v1`` bez dokumentacji
  i bez zgody na automat; nie odtwarzamy cudzego, nieopisanego API.
- **Sąd Najwyższy po 2016 r.** (``sn.pl``) — SAOS kończy się na 2016 r., a
  ``sn.pl`` stoi za bramką antybotową.

Zapytania użytkownika nie trafiają do adresu: link prowadzi do wyszukiwarki,
a podpowiedź mówi, co wpisać. Pobranie z tych źródeł = nowa decyzja
i wpis w regule ``docs/claude/asystent-prawny/orzecznictwo-i-interpretacje.md``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SearchLink:
    source: str
    label: str
    url: str
    note: str


LINKS: tuple[SearchLink, ...] = (
    SearchLink(
        source="cbosa",
        label="Orzeczenia NSA i WSA (CBOSA)",
        url="https://orzeczenia.nsa.gov.pl/cbo/query",
        note="Sądy administracyjne: podatki, ZUS, interpretacje — brak API, szukaj ręcznie.",
    ),
    SearchLink(
        source="eureka",
        label="Interpretacje podatkowe KIS (EUREKA)",
        url="https://eureka.mf.gov.pl/",
        note="Interpretacje indywidualne i ogólne Ministra Finansów — brak publicznego API.",
    ),
    SearchLink(
        source="sn",
        label="Orzeczenia Sądu Najwyższego po 2016 r.",
        url="https://www.sn.pl/orzecznictwo/SitePages/Baza_orzeczen.aspx",
        note="SAOS ma orzeczenia SN tylko do 2016 r.; nowsze w bazie SN.",
    ),
)


def search_links(courts: frozenset[str] | None = None) -> list[SearchLink]:
    """Linki do wyszukiwarek bez API; filtr ``courts`` jak w ``search_case_law``."""
    if not courts:
        return list(LINKS)
    wanted: set[str] = set()
    if "administrative" in courts or "tax_authority" in courts:
        wanted |= {"cbosa", "eureka"}
    if "supreme" in courts:
        wanted.add("sn")
    return [link for link in LINKS if link.source in wanted]
