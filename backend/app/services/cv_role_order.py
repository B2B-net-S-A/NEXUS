"""Kolejność stanowisk w CV — od najnowszego, liczona z dat (16.10.2026).

Rekruterka zgłosiła CV z generatora z doświadczeniem nie po kolei, a asystent
edytora odmówił „ułożenia miejsc pracy chronologicznie”. Prompt generatora
prosi o „doświadczenie od najnowszego”, ale ten sam prompt pozwala modelowi
„zmieniać kolejność” pod wymagania klienta — więc kolejność ustawia kod. Ta sama
reguła działa w generatorze (`legacy_v7.pipeline`, `standalone_service`) i w
asystencie edytora (`cv_command_ai`, operacja ``reorder_roles``):

* przestawiamy tylko pewne błędy: rolę, która skończyła się, zanim zaczęła się
  rola stojąca niżej, i rolę zakończoną nad trwającą („obecnie”, „present”),
* poza tym kolejność zostaje taka, jaką dał model albo rekruter — nakładające
  się, zakończone stanowiska ułożone po dacie rozpoczęcia to też chronologia
  (pomiar produkcji 16.10.2026: 52 ze 107 CV „nie po kolei” z 30 dni to był ten
  przypadek, a tylko 55 to prawdziwe błędy),
* stanowisko bez czytelnych dat zostaje na swoim miejscu, a pozostałe układają
  się na wolnych miejscach — kod nie zgaduje, gdzie stoi rola bez dat.

Ta sama reguła liczy uwagę QC „Stanowiska od najnowszego” i jej poprawkę
(`cv_qc`, akcja ``role_order``).

Daty czytamy w formatach, które pisze generator i reguły klienta
(``MM.YYYY``, ``MM/YYYY``, ``MM-YYYY``, ``YYYY-MM``, ``YYYY``). Przy kilku
datach w tekście liczą się dwie ostatnie: rok w nazwie stanowiska
(„Windows Server 2019”) stoi przed okresem, a nie po nim.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Optional

# Słowa trwającego stanowiska; granice słów, bo „now” siedzi w „Snowflake”.
_ONGOING = re.compile(
    r"\b(?:obecnie|nadal|teraz|do\s+dzi[śs]|currently|present|now|ongoing|today)\b",
    re.IGNORECASE,
)
_YEAR = r"(?:19|20)\d{2}"
_MONTH = r"(?:0?[1-9]|1[0-2])"
_DATE = re.compile(
    rf"(?<![\d./])(?:"
    rf"(?P<month_first>{_MONTH})[./-](?P<year_after>{_YEAR})"
    rf"|(?P<year_first>{_YEAR})-(?P<month_after>{_MONTH})"
    rf"|(?P<year>{_YEAR})"
    rf")(?!\d)"
)
_FOREVER = 10_000 * 12
# Więcej stanowisk nie ma żadne prawdziwe CV; kolejność liczy się w czasie
# kwadratowym, a treść z edytora (do 500 KB) mogłaby nieść ich tysiące.
ROLES_MAX = 100


def _events(text: str) -> list[tuple[int, Optional[tuple[int, Optional[int]]]]]:
    """Daty (rok, miesiąc albo ``None``) i słowa „obecnie” w kolejności tekstu."""
    found: list[tuple[int, Optional[tuple[int, Optional[int]]]]] = []
    for match in _DATE.finditer(text):
        year = (
            match.group("year_after")
            or match.group("year_first")
            or match.group("year")
        )
        month = match.group("month_first") or match.group("month_after")
        found.append((match.start(), (int(year), int(month) if month else None)))
    for match in _ONGOING.finditer(text):
        found.append((match.start(), None))
    return sorted(found, key=lambda event: event[0])


def period(text: str) -> Optional[tuple[int, int]]:
    """``(koniec, początek)`` stanowiska jako numery miesięcy — albo ``None``.

    Rok bez miesiąca to styczeń na początku i grudzień na końcu okresu.
    Stanowisko trwające kończy się „w nieskończoności”.
    """
    events = [value for _, value in _events(text or "")]
    if not any(value is not None for value in events):
        return None
    last = events[-1]
    before = events[-2] if len(events) > 1 else None
    if last is None:
        end = _FOREVER
        if before is None:
            # „obecnie” bez daty tuż przed nim: początek to ostatnia data w tekście.
            before = next(value for value in reversed(events) if value is not None)
        start_year, start_month = before
        return end, start_year * 12 + (start_month or 1) - 1
    end_year, end_month = last
    end = end_year * 12 + (end_month or 12) - 1
    start_year, start_month = before if before is not None else last
    # Odwrócony okres („2020 – 2018”) czytamy jako zakończony w dacie końca —
    # inaczej dwa takie stanowiska byłyby „nowsze” jedno od drugiego.
    return end, min(start_year * 12 + (start_month or 1) - 1, end)


def dates_text(rest: str, whole: str) -> str:
    """Tekst, z którego czytamy daty linii stanowiska.

    ``rest`` to linia bez pogrubionej nazwy roli („**Senior Developer**
    03.2020 – obecnie” → „ 03.2020 – obecnie”): rok w nazwie roli („Windows
    Server 2019”) nie jest datą stanowiska. Gdy tam dat nie ma (pogrubiona cała
    linia, linia wpisana ręcznie), cała linia.
    """
    return rest if period(rest) else whole


def _newer(a: tuple[int, int], b: tuple[int, int]) -> bool:
    """Stanowisko ``a`` jest na pewno nowsze od ``b``.

    Trwa, a ``b`` się skończyło — albo zaczęło się po końcu ``b``. Dwa
    zakończone, nakładające się stanowiska nie są „na pewno” w żadnej kolejności.
    """
    (end_a, start_a), (end_b, _) = a, b
    return (end_a == _FOREVER and end_b != _FOREVER) or start_a > end_b


def newest_first(texts: Sequence[str], *, newest: bool = True) -> Optional[list[int]]:
    """Nowa kolejność stanowisk: ``wynik[k]`` = numer stanowiska na miejscu ``k``.

    ``newest=False`` — od najstarszego. ``None``, gdy żadne stanowisko nie ma
    czytelnych dat (nie ma czego ustawiać) albo stanowisk jest więcej niż
    ``ROLES_MAX``.

    Sortowanie topologiczne po relacji „na pewno nowsze”, stabilne: z ról,
    nad którymi nie musi stać żadna inna, bierzemy pierwszą w kolejności
    wejścia. Relacja jest przechodnia i bez cykli (początek ≤ koniec), więc
    taka rola zawsze jest.
    """
    if len(texts) > ROLES_MAX:
        return None
    periods = [period(text) for text in texts]
    dated = [index for index, value in enumerate(periods) if value is not None]
    if not dated:
        return None

    def above(a: int, b: int) -> bool:
        first, second = (a, b) if newest else (b, a)
        return _newer(periods[first], periods[second])  # type: ignore[arg-type]

    waiting = {i: sum(1 for j in dated if j != i and above(j, i)) for i in dated}
    left = list(dated)
    ranked: list[int] = []
    while left:
        pick = next((i for i in left if waiting[i] == 0), left[0])
        left.remove(pick)
        ranked.append(pick)
        for i in left:
            if above(pick, i):
                waiting[i] -= 1
    order = list(range(len(texts)))
    for slot, index in zip(dated, ranked):
        order[slot] = index
    return order


def sort_experience(candidate_data: dict) -> bool:
    """Doświadczenie z generatora od najnowszego (w miejscu). ``True``, gdy coś się zmieniło."""
    roles = candidate_data.get("experience")
    if not isinstance(roles, list) or len(roles) < 2:
        return False
    texts = [
        str(role.get("dates") or "") if isinstance(role, dict) else "" for role in roles
    ]
    order = newest_first(texts)
    if order is None or order == list(range(len(roles))):
        return False
    candidate_data["experience"] = [roles[index] for index in order]
    return True
