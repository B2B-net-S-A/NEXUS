"""Pozycja jednej osoby w Lidze Mistrzów — do przycisku ligi w górnym pasku.

Czyste funkcje na wierszach `award_ranked_rows` (ta sama numeracja co podium
na „Rywalizacji” i zamrożenie kwartału), bez bazy. Wiersze idą najpierw
z miejscem 1..n w kolejności nagrodowej, potem bez miejsca (`rank: None` —
niezakwalifikowani), w kolejności wyniku.

`/my-position` oddaje tylko ±2 sąsiadów, więc dystansu do podium od 6. miejsca
nie dało się z niego policzyć. Tu dystans liczy się z całej listy.
"""

from typing import Literal, Optional, Union

from app.models.user import User, UserRole

PODIUM_SIZE = 3
NEIGHBOURS_EACH_SIDE = 2
LEADERS_LIMIT = 5

LeagueKind = Literal["recruiter", "delivery_lead", "spectator"]

# Pola wiersza, które pasek pokazuje o innych osobach. Wynik i nagroda są
# jawne na „Rywalizacji” dla każdego zalogowanego; marżę `award_ranked_rows`
# wycina wcześniej (`_MARGIN_EXTRAS`). `hit_ratio` — wynik ligi DL.
_PUBLIC_KEYS = (
    "rank",
    "user_id",
    "name",
    "metric_value",
    "hit_ratio",
    "prize_pln",
    "tied",
)

Number = Union[int, float]


def league_kind(user: User) -> LeagueKind:
    """Która liga dotyczy osoby — z ról, tak jak predykaty obu rankingów.

    Liga DL bierze każdego z rolą Delivery Leada (główną albo dodatkową),
    liga rekruterów — każdego z rolą rekrutera. Zakres pulpitu się nie nadaje:
    stawia HoR/TCM przed DL, więc HoR z rolą DL wychodziłby „widzem”, choć gra
    w lidze DL. Osoba z obiema rolami dostaje tu ligę DL; `my_league` przełącza
    ją na ligę rekruterów, gdy w kwartale nie ma portfela DL.
    """
    if user.has_role(UserRole.delivery_lead):
        return "delivery_lead"
    if user.has_role(UserRole.recruiter):
        return "recruiter"
    return "spectator"


def _public(row: dict) -> dict:
    return {key: row.get(key) for key in _PUBLIC_KEYS}


def _gap(high: Number, low: Number) -> Number:
    """Różnica wyników; hit ratio (ułamek) zaokrąglone do 0,1 jak w rankingu."""
    diff = high - low
    return round(diff, 1) if isinstance(diff, float) else diff


def league_standing(
    rows: list[dict],
    user_id: int,
    ties: Optional[list[dict]] = None,
    *,
    value_key: str = "metric_value",
) -> dict:
    """Miejsce, dystanse i sąsiedzi osoby `user_id`.

    `value_key` — pole wyniku: `metric_value` (punkty Ligi rekruterów) albo
    `hit_ratio` (liga DL od 25.10.2026, dystanse w punktach procentowych).
    Hit ratio niepoliczone (brak zamkniętych rekrutacji) liczy się jak 0.

    - `position_by_value` — pozycja po samym wyniku, także dla osoby bez
      miejsca w klasyfikacji („po punktach to 7. pozycja”).
    - `gap_to_place_above` — ile brakuje do miejsca wyżej (od 2. miejsca).
    - `lead_over_next` — przewaga nad następnym miejscem (z miejscem).
    - `gap_to_podium` — ile brakuje do wyniku 3. miejsca, dla miejsca ≥ 4 i dla
      osoby bez miejsca; `None`, gdy podium nie jest pełne. Nigdy ujemny:
      niezakwalifikowany z wynikiem ponad podium ma problem z warunkiem, nie
      z punktami.

    - `tie_for` — o które miejsce jest remis, którego regulamin nie
      rozstrzyga (`ties` z `/current`). Z grupy remisu, nie z flagi `tied`
      wiersza: pozycje remisu kończą się na podium, więc przy remisie 3. i 4.
      miejsca flagę ma tylko 3., a przy remisie 1. i 2. osoba z 2. miejsca
      walczy o 1.

    Osoby bez wyniku nie ma na liście (`me: None`) — liczy się wtedy od zera.
    """
    index = next(
        (i for i, row in enumerate(rows) if row.get("user_id") == user_id), None
    )
    me = rows[index] if index is not None else None

    def score(row: dict) -> Number:
        raw = row.get(value_key)
        if raw is None:
            return 0
        return float(raw) if value_key == "hit_ratio" else int(raw)

    value = score(me) if me else 0
    rank: Optional[int] = me.get("rank") if me else None

    by_rank = {row["rank"]: row for row in rows if row.get("rank") is not None}
    third = by_rank.get(PODIUM_SIZE)

    gap_to_place_above: Optional[Number] = None
    lead_over_next: Optional[Number] = None
    if rank is not None:
        above = by_rank.get(rank - 1)
        if above is not None:
            gap_to_place_above = _gap(score(above), value)
        below = by_rank.get(rank + 1)
        if below is not None:
            lead_over_next = _gap(value, score(below))

    gap_to_podium: Optional[Number] = None
    if third is not None and (rank is None or rank > PODIUM_SIZE):
        gap_to_podium = max(_gap(score(third), value), 0)

    neighbours: list[dict] = []
    position_by_value: Optional[int] = None
    if index is not None:
        start = max(0, index - NEIGHBOURS_EACH_SIDE)
        neighbours = [
            _public(row) for row in rows[start : index + NEIGHBOURS_EACH_SIDE + 1]
        ]
        position_by_value = 1 + sum(1 for row in rows if score(row) > value)

    tie_for: Optional[int] = None
    for tie in ties or []:
        if user_id in tie.get("user_ids", []) and tie.get("positions"):
            tie_for = int(tie["positions"][0])
            break

    return {
        "me": me,
        "rank": rank,
        "tie_for": tie_for,
        "value": value,
        "position_by_value": position_by_value,
        "gap_to_place_above": gap_to_place_above,
        "lead_over_next": lead_over_next,
        "gap_to_podium": gap_to_podium,
        "neighbours": neighbours,
    }


def league_leaders(rows: list[dict], limit: int = LEADERS_LIMIT) -> list[dict]:
    """Pierwsze miejsca klasyfikacji — dla osób, które nie grają."""
    return [_public(row) for row in rows if row.get("rank") is not None][:limit]


__all__ = [
    "LeagueKind",
    "league_kind",
    "league_leaders",
    "league_standing",
]
