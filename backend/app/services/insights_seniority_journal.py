"""Dziennik obserwacji poziomu seniority — wykrywanie CICHYCH zmian.

`insights_seniority` liczy poziom przy odczycie i nie przechowuje go; ten
moduł tej decyzji NIE odwraca. Poziom nadal nie ma tu swojej prawdy — tabela
`insights_seniority_snapshots` jest dziennikiem OBSERWACJI i odpowiada na
pytanie, na które moduł liczący przy odczycie odpowiedzieć nie może:

    czy komuś zmienił się poziom, mimo że ta osoba nic dziś nie zrobiła?

Bo poziom jest funkcją historii atrybucji, a ta się zmienia bez udziału
osoby, której dotyczy: import Traffita dopisuje zaległe `hired`, ktoś
przepina placement na inne konto. Przy odczycie widać wyłącznie stan
BIEŻĄCY — poprzedni nie istnieje nigdzie, więc taka zmiana jest niewidoczna
z definicji, a nie przez niedopatrzenie.

Reguła „bez degradacji" z modułu liczącego (poziom raz osiągnięty zostaje)
sprawia, że SPADEK poziomu jest zawsze anomalią: nie da się go wytłumaczyć
upływem czasu ani słabszym kwartałem. Dlatego spadek jest stemplowany przy
zapisie jako `is_regression` i wychodzi na wierzch w `/api/insights/recruitment/seniority`.

Czego ten moduł świadomie NIE robi:

* **Nie pisze wiersza, gdy nic się nie zmieniło.** Codzienny wiersz na osobę
  to ~22 tys. rekordów rocznie, w których kilkanaście istotnych zdarzeń jest
  nie do znalezienia. Dziennik ma być krótki, żeby dało się go przeczytać.
* **Nie zmienia ani nie „naprawia" poziomu.** Wykrycie regresji to informacja
  dla człowieka; automatyczne przywrócenie poprzedniego poziomu zapisałoby
  jako fakt coś, czego dane już nie potwierdzają.
* **Nie myli zmiany PROGU ze zmianą HISTORII.** Odcisk progów siedzi na
  wierszu; obniżenie poprzeczki przez operatora ma w dzienniku inny odcisk
  niż cofnięta atrybucja przy tych samych progach.
"""

import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.periods import ANALYTICS_TIMEZONE
from app.services.insights_seniority import (
    LEVEL_ORDER,
    SeniorityThresholds,
    compute_seniority,
    load_thresholds,
)

logger = logging.getLogger(__name__)


def _level_rank(level: str) -> int:
    """Pozycja poziomu na ścieżce; nieznany poziom ląduje NAJNIŻEJ.

    Nieznana wartość nie może udawać awansu — gdyby literówka w konfiguracji
    dała poziom spoza `LEVEL_ORDER`, porównanie „w górę czy w dół" musi
    wskazać spadek i zostać zauważone, a nie przejść jako neutralne.
    """
    try:
        return LEVEL_ORDER.index(level)
    except ValueError:
        return -1


async def _last_observations(db: AsyncSession) -> dict[int, dict]:
    """Ostatnia obserwacja na osobę (DISTINCT ON — jeden przebieg po indeksie)."""
    rows = (
        await db.execute(
            text(
                """
                SELECT DISTINCT ON (user_id)
                       user_id, level, total_placements, thresholds_fingerprint
                FROM insights_seniority_snapshots
                ORDER BY user_id, observed_at DESC, id DESC
                """
            )
        )
    ).mappings()
    return {r["user_id"]: dict(r) for r in rows}


async def record_seniority_observations(
    db: AsyncSession,
    *,
    as_of: date | None = None,
    thresholds: SeniorityThresholds | None = None,
) -> dict:
    """Zapisz do dziennika wyłącznie te osoby, którym coś się zmieniło.

    Zwraca licznik: ile osób obejrzano, ile wierszy dopisano, ile z nich to
    regresje. Zero dopisanych wierszy to poprawny, spodziewany wynik.
    """
    effective_thresholds = thresholds or await load_thresholds(db)
    # Dzień w kalendarzu ANALITYCZNYM, nie w UTC — tak samo jak w endpoincie.
    # O 00:30 czasu polskiego `date.today()` w UTC pokazuje jeszcze wczoraj,
    # więc placement sprzed pół godziny wypadałby z okna i pętla zapisałaby
    # obserwację niezgodną z tym, co widać na ekranie.
    effective_as_of = as_of or datetime.now(ZoneInfo(ANALYTICS_TIMEZONE)).date()
    computed = await compute_seniority(
        db, as_of=effective_as_of, thresholds=effective_thresholds
    )
    fingerprint = effective_thresholds.cache_suffix
    previous = await _last_observations(db)

    inserted = 0
    regressions = 0
    for row in computed.rows:
        last = previous.get(row.user_id)
        if (
            last is not None
            and last["level"] == row.level
            and last["total_placements"] == row.total_placements
            and last["thresholds_fingerprint"] == fingerprint
        ):
            # Nic się nie zmieniło — także liczba placementów, bo poziom bywa
            # ten sam po zniknięciu placementu, a to wciąż jest zdarzenie.
            continue

        is_regression = last is not None and _level_rank(row.level) < _level_rank(
            last["level"]
        )
        await db.execute(
            text(
                """
                INSERT INTO insights_seniority_snapshots
                    (user_id, level, previous_level, total_placements,
                     previous_total_placements, senior_since, expert_since,
                     thresholds_fingerprint, is_regression)
                VALUES
                    (:user_id, :level, :previous_level, :total_placements,
                     :previous_total, :senior_since, :expert_since,
                     :fingerprint, :is_regression)
                """
            ),
            {
                "user_id": row.user_id,
                "level": row.level,
                "previous_level": last["level"] if last else None,
                "total_placements": row.total_placements,
                "previous_total": last["total_placements"] if last else None,
                "senior_since": row.senior_since,
                "expert_since": row.expert_since,
                "fingerprint": fingerprint,
                "is_regression": is_regression,
            },
        )
        inserted += 1
        regressions += 1 if is_regression else 0

    await db.commit()
    if regressions:
        logger.warning(
            "seniority journal: %s regresji poziomu w tym przebiegu", regressions
        )
    return {
        "observed_users": len(computed.rows),
        "inserted": inserted,
        "regressions": regressions,
        "thresholds_fingerprint": fingerprint,
    }


async def load_journal_status(db: AsyncSession) -> dict:
    """Czy dziennik w ogóle KIEDYKOLWIEK coś zaobserwował.

    Bez tego pusta lista regresji znaczy DWIE różne rzeczy naraz: „sprawdzono
    i nikomu nic nie spadło" oraz „pętla nigdy nie wystartowała". Front
    renderowałby oba przypadki jako ciszę, więc zepsuta pętla w nieskończoność
    mówiłaby „wszystko w porządku" — dokładnie ten tryb awarii, przed którym
    broni `regressions: null` na ścieżce ODCZYTU.

    Sonda w `/api/health/deep` tego nie łapie: sprawdza, że tabela istnieje,
    a pusta tabela istnieje tak samo dobrze jak zapełniona.
    """
    row = (
        (
            await db.execute(
                text(
                    """
                SELECT max(observed_at) AS last_observed_at,
                       count(*)         AS observations
                FROM insights_seniority_snapshots
                """
                )
            )
        )
        .mappings()
        .one()
    )
    last = row["last_observed_at"]
    return {
        "last_observed_at": last.isoformat() if last else None,
        "observations": int(row["observations"] or 0),
    }


async def load_open_regressions(db: AsyncSession, *, limit: int = 25) -> list[dict]:
    """Osoby, których OSTATNIA obserwacja jest spadkiem poziomu.

    Świadomie „ostatnia", nie „jakakolwiek w historii": spadek, po którym
    ktoś odzyskał poziom, jest zamkniętą sprawą i trzymanie go na wierzchu
    zamieniłoby ostrzeżenie w tło, którego nikt nie czyta.
    """
    rows = (
        await db.execute(
            text(
                """
                WITH last_per_user AS (
                    SELECT DISTINCT ON (s.user_id)
                           s.user_id, s.level, s.previous_level,
                           s.total_placements, s.previous_total_placements,
                           s.observed_at, s.is_regression,
                           s.thresholds_fingerprint
                    FROM insights_seniority_snapshots s
                    ORDER BY s.user_id, s.observed_at DESC, s.id DESC
                )
                SELECT l.user_id, u.name, l.level, l.previous_level,
                       l.total_placements, l.previous_total_placements,
                       l.observed_at, l.thresholds_fingerprint
                FROM last_per_user l
                JOIN users u ON u.id = l.user_id
                WHERE l.is_regression IS TRUE
                ORDER BY l.observed_at DESC, l.user_id ASC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )
    ).mappings()
    return [
        {
            "user_id": r["user_id"],
            "name": r["name"],
            "level": r["level"],
            "previous_level": r["previous_level"],
            "total_placements": r["total_placements"],
            "previous_total_placements": r["previous_total_placements"],
            "observed_at": r["observed_at"].isoformat() if r["observed_at"] else None,
            "thresholds_fingerprint": r["thresholds_fingerprint"],
        }
        for r in rows
    ]
