"""Insights → Rekrutacja: „Performance per osoba" na danych natywnych NEXUSA.

Odpowiednik serca strony `/rekrutacja` w DynaReporterze: cztery liczby przy
nazwisku (weryfikacje, rekomendacje, interviews, placements) w oknie
`resolve_period`, atrybuowane przez `analytics_first_milestones.first_moved_by`.

Cztery decyzje, które trzymają tę tabelę uczciwą:

1. **Kamienie nieprzypisane NIE znikają.** Ruch wykonany przez operatora
   Traffita, którego nie dało się dopasować do konta w NEXUSIE, ma
   ``first_moved_by IS NULL``. Wycięcie go po cichu sprawia, że suma kolumny
   przestaje zgadzać się z lejkiem (`/api/insights/recruitment/funnel`) —
   a rozbieżność bez wyjaśnienia czyta się jako ZEPSUTA tabela, nie jako
   niekompletna. Dlatego ``unattributed`` jest w odpowiedzi PER ETAP (nie
   jednym skalarem: nieprzypisana weryfikacja i nieprzypisany placement to
   dwie różne dziury i trafiają pod dwie różne kolumny).

2. **Nieaktywni użytkownicy z dorobkiem w oknie ZOSTAJĄ.** Odejście z firmy
   nie kasuje wyników, które ta osoba osiągnęła. Filtr ``is_active = true``
   przepisywałby historię wstecz przy każdym offboardingu — a raport za lipiec
   ma pokazywać lipiec, nie dzisiejszy skład zespołu. Wiersz dostaje
   ``is_active: false``, a UI oznacza go chipem „były pracownik".

3. **Zero limitu wierszy.** Ucięcie tabeli do TOP-N daje dokładnie ten sam
   defekt co punkt 1 — suma kolumny przestaje zgadzać się z lejkiem, i to
   cicho. Liczba wierszy jest ograniczona liczbą osób, które w oknie ruszyły
   choć jeden kamień, więc nie ma czego paginować.

4. **Placement = D2.** Bierzemy PIERWSZE ``hired`` dla pary (kandydat,
   oferta) — czyli wiersz widoku ``analytics_first_milestones``, nigdy
   surowego ``candidate_stages``. Import Traffita dopisuje wiersz na każde
   zdarzenie, więc ponowne wejście na etap liczyłoby się drugi raz.

Bramka: ``CurrentUser`` (decyzja D7 — /insights widzi każda zalogowana rola,
łącznie z danymi imiennymi; patrz docs/insights-dynareporter-migration-plan.md
§0 D7 i blok D7 w backend/tests/test_route_authz_contract.py).
"""

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.periods import PeriodError, resolve_period
from app.api.deps import CurrentUser
from app.core.cache import cache_get, cache_set
from app.core.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter()

CACHE_TTL_SECONDS = 300

# Cztery kolumny tabeli ↔ cztery etapy widoku kamieni milowych.
#
# Każdy z nich JEST w `analytics_first_milestones` (widok niesie: verified,
# cv_sent, interview, client_interview, acceptance, hired — zweryfikowane
# w migracji 0184). Dopisanie tu etapu spoza tej listy dałoby kolumnę stale
# zerową, bo widok o nim nie wie — a zero czytałoby się jako obserwacja.
STAGE_COLUMNS: list[dict] = [
    {"key": "verifications", "stage": "verified", "label": "Weryfikacje"},
    {"key": "recommendations", "stage": "cv_sent", "label": "Rekomendacje"},
    {"key": "interviews", "stage": "interview", "label": "Interviews"},
    {"key": "placements", "stage": "hired", "label": "Placements"},
]

_STAGE_TO_KEY: dict[str, str] = {c["stage"]: c["key"] for c in STAGE_COLUMNS}
_COLUMN_KEYS: list[str] = [c["key"] for c in STAGE_COLUMNS]

# Etykiety ról po polsku. Chip w kolumnie ROLA renderuje `role_label`, ale
# odpowiedź niesie też surowe `role` — kolorowanie i filtrowanie po stronie
# UI musi stać na wartości enuma, nie na przetłumaczonym napisie.
ROLE_LABELS: dict[str, str] = {
    "admin": "Admin",
    "head_of_recruitment": "Head of Recruitment",
    "delivery_lead": "Delivery Lead",
    "finance": "Finanse",
    "tac": "TAC",
    "recruiter": "Rekruter",
    "sourcer": "Sourcer",
    "user": "Viewer",
}


def _empty_counts() -> dict[str, int]:
    return {key: 0 for key in _COLUMN_KEYS}


def _resolve(kind: str, offset: int, anchor: date | None, date_from, date_to):
    try:
        return resolve_period(
            kind, offset=offset, anchor=anchor, date_from=date_from, date_to=date_to
        )
    except PeriodError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.get("/team-table")
async def insights_team_table(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    period: str = Query("month", pattern="^(day|week|month|quarter|year|custom)$"),
    offset: int = Query(0, description="0 = bieżący okres, -1 = poprzedni zamknięty"),
    anchor: date | None = Query(None, description="dowolny dzień wewnątrz okresu"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
):
    """Cztery liczby przy nazwisku w oknie — plus to, czego nie dało się przypisać.

    Dostępne dla KAŻDEGO zalogowanego (decyzja D7). Sekcja niesie dane imienne
    i to jest świadome — nie wolno „naprawić" jej przez `require_capability`,
    bo tamte capability sterują 40+ innymi powierzchniami.
    """
    resolved = _resolve(period, offset, anchor, date_from, date_to)

    # Klucz cache'u NIESIE OKNO (`cache_suffix`). Bez tego liczby jednego
    # okresu wyszłyby pod etykietą drugiego — obie wyglądają wiarygodnie,
    # więc nikt by się nie dowiedział.
    cache_key = f"insights:team:table:v1:{resolved.cache_suffix}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    rows = (
        (
            await db.execute(
                text(
                    """
                SELECT fm.first_moved_by AS user_id,
                       fm.stage::text     AS stage,
                       count(*)           AS cnt
                FROM analytics_first_milestones fm
                WHERE fm.first_reached_at >= :start
                  AND fm.first_reached_at <  :end
                  AND fm.stage::text = ANY(:stages)
                GROUP BY fm.first_moved_by, fm.stage
                """
                ),
                {
                    "start": resolved.start,
                    "end": resolved.end,
                    "stages": list(_STAGE_TO_KEY.keys()),
                },
            )
        )
        .mappings()
        .all()
    )

    per_user: dict[int, dict[str, int]] = {}
    unattributed = _empty_counts()
    for r in rows:
        column = _STAGE_TO_KEY.get(str(r["stage"]))
        if column is None:  # pragma: no cover — filtr SQL już to odsiał
            continue
        cnt = int(r["cnt"] or 0)
        raw_uid = r["user_id"]
        if raw_uid is None:
            unattributed[column] += cnt
            continue
        per_user.setdefault(int(raw_uid), _empty_counts())[column] += cnt

    users: dict[int, dict] = {}
    if per_user:
        user_rows = (
            (
                await db.execute(
                    text(
                        """
                    SELECT id, name, role::text AS role, is_active
                    FROM users
                    WHERE id = ANY(:ids)
                    """
                    ),
                    {"ids": list(per_user.keys())},
                )
            )
            .mappings()
            .all()
        )
        users = {int(u["id"]): dict(u) for u in user_rows}

    entries = []
    for user_id, counts in per_user.items():
        user = users.get(user_id)
        role = str(user["role"]) if user and user["role"] is not None else None
        entries.append(
            {
                "user_id": user_id,
                # `None`, nie zmyślona etykieta: konto zniknęło, ale jego
                # dorobek został i musi wejść w sumę kolumny. UI renderuje
                # „Nieznany użytkownik (#id)" — atrybucja jest znana, tylko
                # osoby już nie potrafimy nazwać. Zwinięcie tego wiersza do
                # `unattributed` byłoby kłamstwem w drugą stronę.
                "name": (user["name"] if user else None),
                "role": role,
                "role_label": ROLE_LABELS.get(role or "", role),
                # `None` = nie wiemy (brak konta). `False` = były pracownik.
                # Chip „były pracownik" wolno postawić WYŁĄCZNIE przy `False`.
                "is_active": (bool(user["is_active"]) if user else None),
                **counts,
                "total": sum(counts.values()),
            }
        )

    # Domyślny porządek: weryfikacje malejąco, remis rozstrzyga nazwisko —
    # ten sam, od którego zaczyna DynaReporter. UI sortuje po swojemu po
    # kliknięciu nagłówka, więc `rank` świadomie NIE wychodzi z serwera:
    # dwa źródła prawdy dla tej samej pozycji rozjeżdżają się przy pierwszym
    # przesortowaniu, a medal usiadłby wtedy na złym wierszu.
    entries.sort(key=lambda e: (-e["verifications"], (e["name"] or "").lower()))

    attributed = _empty_counts()
    for e in entries:
        for key in _COLUMN_KEYS:
            attributed[key] += e[key]

    result = {
        "period": resolved.as_payload(),
        "columns": [
            {"key": c["key"], "label": c["label"], "stage": c["stage"]}
            for c in STAGE_COLUMNS
        ],
        "rows": entries,
        "totals": {
            # Suma widocznych wierszy…
            "attributed": attributed,
            # …to, czego nie da się przypisać nikomu…
            "unattributed": unattributed,
            # …i suma obu, która MUSI zgadzać się z lejkiem org-level.
            "all": {key: attributed[key] + unattributed[key] for key in _COLUMN_KEYS},
            "users": len(entries),
            "former_employees": sum(1 for e in entries if e["is_active"] is False),
        },
    }
    await cache_set(cache_key, result, ttl_seconds=CACHE_TTL_SECONDS)
    return result
