"""Insights → „Lejek po etapach” — statystyki wszystkich etapów przy 8 kolumnach.

Tablica ma od 24.09.2026 osiem kolumn (Nowi · Screening · Zweryfikowany ·
QC CV · CV wysłane · Rozmowa u klienta · Umowa · Zatrudniony), a reszta etapów
szablonu jest znacznikiem na karcie („w kolejce Cpro”, „Prep”, „Po rozmowie”,
„Umowa wysłana/podpisana”, „Onboarding”). Statystyki nie mogą tego zgubić:
każdy znacznik ma tu własny wiersz pod kolumną, do której należy.

Wiersz etapu dostaje KLUCZ tą samą regułą co Tablica — odznaka rozpoznana po
NAZWIE etapu szablonu (`stage_badge_kind`), potem kolumna z kodu etapu
(`board_column_for`). Nazwa jest w Pythonie, więc klucz etapu szablonu liczy
Python (`def_override`), a SQL dostaje gotową mapę `stage_def_id → klucz`
i dokłada regułę kodu etapu (`_KEY_CASE_SQL`). Obie połowy są lustrem jednej
funkcji `stage_key` — pilnuje tego test na przypadkach z
`frontend/src/lib/__fixtures__/board-stage-cases.json`.

Dwie liczby na wiersz:

* **Doszło** — pary (kandydat, rekrutacja), które PIERWSZY raz weszły na etap
  w oknie. „Zatrudnieni” idą z `analytics_first_milestones` (reguła D2 —
  pierwsze `hired` pary, bez wykluczonych placementów), więc zgadzają się
  z lejkiem i z kaflem placementów.
* **Teraz** — pary, których NAJNOWSZY wiersz stoi dziś na tym etapie,
  w rekrutacjach opublikowanych. To stan na dziś, nie zależy od okna.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.board_stage_badges import normalize_stage_name, stage_badge_kind
from app.services.rejection_reason_labels import rejection_reason_label


@dataclass(frozen=True)
class BreakdownRow:
    column: str
    column_label: str
    key: str
    label: str
    # Wiersz główny kolumny — do niego liczy się konwersja następnych wierszy.
    is_main: bool


# Kolejność Tablicy. Odznaka stoi pod kolumną, do której należy
# (`_COLUMN_BY_NAME_BADGE` w `board_stage_badges`).
ROWS: tuple[BreakdownRow, ...] = (
    BreakdownRow("new", "Nowi", "added", "Dodani", True),
    BreakdownRow("new", "Nowi", "reassign", "Przepięcie", False),
    BreakdownRow("screening", "Screening", "screening", "Screening", True),
    BreakdownRow("verified", "Zweryfikowany", "verified", "Zweryfikowani", True),
    BreakdownRow("cv_qc", "QC CV", "qc", "QC CV", True),
    BreakdownRow("cv_qc", "QC CV", "cpro", "W kolejce Cpro", False),
    BreakdownRow("cv_sent", "CV wysłane", "cv_sent", "Wysłani do klienta", True),
    BreakdownRow("client_interview", "Rozmowa u klienta", "prep", "Prep", False),
    BreakdownRow(
        "client_interview",
        "Rozmowa u klienta",
        "client_interview",
        "Rozmowa u klienta",
        True,
    ),
    BreakdownRow(
        "client_interview", "Rozmowa u klienta", "after_interview", "Po rozmowie", False
    ),
    BreakdownRow("contract", "Umowa", "acceptance", "Akceptacja", True),
    BreakdownRow("contract", "Umowa", "contract_sent", "Umowa wysłana", False),
    BreakdownRow("contract", "Umowa", "contract_signed", "Umowa podpisana", False),
    BreakdownRow("hired", "Zatrudniony", "hired", "Zatrudnieni", True),
    BreakdownRow("hired", "Zatrudniony", "onboarding", "Onboarding", False),
)

# Klucz → kolumna Tablicy (także dla kluczy technicznych). Czyta go test
# zgodności z `board_column_for`.
KEY_COLUMN: dict[str, str] = {row.key: row.column for row in ROWS}
KEY_COLUMN.update({"__closed": "closed", "__reserve": "closed"})

CLOSED_BY: tuple[tuple[str, str], ...] = (
    ("candidate", "Zrezygnował"),
    ("recruiter", "Odrzucony przez nas"),
    ("delivery_lead", "Odrzucony przez DL"),
    ("client", "Odrzucony przez klienta"),
)
_CLOSED_BY_KEYS = tuple(k for k, _ in CLOSED_BY)

TOP_REASONS = 3
_REASON_MAX_CHARS = 80
# Ile treści pokazuje dymek „Inne” — reszta jako „… i jeszcze N”.
OTHER_DETAILS_MAX = 20

NO_REASON_LABEL = "Bez podanego powodu"
OTHER_LABEL = "Inne"
# Treść w dymku „Inne” dla katalogowego „Inne (rejected/withdrawn)”.
OTHER_CATALOG_DETAIL = "Inne (z listy powodów)"

# Zaślepka importu Traffita w `rejection_reasons.name` — to brak powodu, nie
# powód: liczy się wtedy notatka (`rejection_note` z Traffita), a bez niej
# wiersz „Bez podanego powodu”. Etykiety pozostałych kodów daje jeden słownik
# `app.services.rejection_reason_labels`.
_NO_REASON_CODES = frozenset({"legacy_unknown"})

# Odrzucenie bez `ended_by` z powodem „… przez Kandydata” (import Traffita:
# „Odrzucenie oferty przez Kandydata”, „Rezygnacja przez Kandydata”) to
# decyzja kandydata, nie nasza. Jedno wyrażenie dla SQL (`~*`) i Pythona.
CANDIDATE_DECISION_PATTERN = r"przez\s+kandydat"
# Lustro dla klienta: „Rezygnacja przez Klienta” z importu = decyzja klienta.
CLIENT_DECISION_PATTERN = r"przez\s+klient"

DEFINITIONS = {
    "reached": (
        "Doszło — ile par (kandydat, rekrutacja) pierwszy raz weszło na etap "
        "w wybranym okresie. Zatrudnieni to pierwsze zatrudnienie pary, tak jak "
        "w lejku i placementach."
    ),
    "now": (
        "Teraz — ile osób stoi dziś na tym etapie w opublikowanych rekrutacjach. "
        "Nie zależy od wybranego okresu."
    ),
}


# ── Klucz etapu ──────────────────────────────────────────────────────────────


def def_override(
    name: Optional[str], category: Optional[str], terminal_type: Optional[str]
) -> Optional[str]:
    """Część klucza wynikająca z ETAPU SZABLONU (nazwa, kategoria, typ końca).

    `None` = etap szablonu nic nie rozstrzyga, decyduje kod etapu. Kolejność
    jest lustrem `board_column_for`: odznaka z nazwy → lista rezerwowa →
    zatrudnienie z typu końca → etap końcowy szablonu.
    """

    kind = stage_badge_kind(name)
    # Etap końcowy z „QC”/„Cpro” w nazwie to zamknięcie — lustro
    # `board_column_for`.
    if kind in ("qc", "cpro") and category == "terminal":
        kind = None
    if kind is not None:
        return kind
    if "rezerw" in normalize_stage_name(name):
        return "__reserve"
    if terminal_type == "hired":
        return "__hired"
    if category == "terminal":
        return "__withdrawn" if terminal_type == "withdrawn" else "__terminal"
    return None


def key_from_parts(override: Optional[str], stage: Optional[str]) -> str:
    """Klucz wiersza z części szablonu i KODU etapu — lustro `_KEY_CASE_SQL`."""

    if override is not None and not override.startswith("__"):
        return override
    if override == "__reserve":
        return "__reserve"
    if stage == "hired" or override == "__hired":
        return "hired"
    if override in ("__terminal", "__withdrawn") or stage in ("rejected", "withdrawn"):
        return "__closed"
    if stage == "onboarding":
        return "onboarding"
    if stage in ("screening", "prep_call"):
        return "screening"
    if stage in ("verified", "interview"):
        return "verified"
    if stage == "cv_sent":
        return "cv_sent"
    if stage == "client_interview":
        return "client_interview"
    if stage in ("acceptance", "negotiation"):
        return "acceptance"
    return "added"


def stage_key(
    name: Optional[str],
    stage: Optional[str],
    *,
    category: Optional[str] = None,
    terminal_type: Optional[str] = None,
) -> str:
    """Klucz wiersza statystyk dla etapu — kolumna zgodna z `board_column_for`."""

    return key_from_parts(def_override(name, category, terminal_type), stage)


# Lustro `key_from_parts` w SQL. `m.o` = `def_override` etapu szablonu wiersza.
_KEY_CASE_SQL = """
    CASE
      WHEN m.o IS NOT NULL AND left(m.o, 2) <> '__' THEN m.o
      WHEN m.o = '__reserve' THEN '__reserve'
      WHEN cs.stage::text = 'hired' OR m.o = '__hired' THEN 'hired'
      WHEN m.o IN ('__terminal', '__withdrawn')
        OR cs.stage::text IN ('rejected', 'withdrawn') THEN '__closed'
      WHEN cs.stage::text = 'onboarding' THEN 'onboarding'
      WHEN cs.stage::text IN ('screening', 'prep_call') THEN 'screening'
      WHEN cs.stage::text IN ('verified', 'interview') THEN 'verified'
      WHEN cs.stage::text = 'cv_sent' THEN 'cv_sent'
      WHEN cs.stage::text = 'client_interview' THEN 'client_interview'
      WHEN cs.stage::text IN ('acceptance', 'negotiation') THEN 'acceptance'
      ELSE 'added'
    END
"""

_DEF_MAP_CTE = """
    def_map AS (
      SELECT m.def_id, m.o
      FROM unnest(CAST(:def_ids AS integer[]), CAST(:def_keys AS text[]))
           AS m(def_id, o)
    )
"""

# `:job_ids` = NULL w API; testy zawężają do własnych rekrutacji, bo baza
# testowa jest wspólna.
_JOB_FILTER_SQL = (
    "(CAST(:job_ids AS integer[]) IS NULL OR {col} = ANY(CAST(:job_ids AS integer[])))"
)


async def _load_def_map(db: AsyncSession) -> tuple[list[int], list[str]]:
    rows = (
        await db.execute(
            text(
                """
                SELECT sd.id, sd.name, sd.category::text AS category,
                       sd.terminal_type::text AS terminal_type
                FROM pipeline_stage_defs sd
                """
            )
        )
    ).all()
    ids: list[int] = []
    keys: list[str] = []
    for def_id, name, category, terminal_type in rows:
        override = def_override(name, category, terminal_type)
        if override is not None:
            ids.append(int(def_id))
            keys.append(override)
    return ids, keys


# ── Zapytania ────────────────────────────────────────────────────────────────


async def _reached(
    db: AsyncSession, params: dict[str, Any]
) -> tuple[dict[str, int], int]:
    """Pierwsze wejścia na klucz w oknie + pary dodane w oknie.

    Para, która PIERWSZY raz weszła na etap w oknie, ma w oknie jakiś wiersz —
    więc przeglądamy tylko pary dotknięte w oknie (`touched`), nie całą historię.
    """

    job_filter = _JOB_FILTER_SQL.format(col="cs.job_id")
    rows = (
        await db.execute(
            text(
                f"""
                WITH {_DEF_MAP_CTE},
                touched AS (
                  SELECT DISTINCT cs.candidate_id, cs.job_id
                  FROM candidate_stages cs
                  WHERE cs.moved_at >= :start AND cs.moved_at < :end
                    AND {job_filter}
                ),
                keyed AS (
                  SELECT cs.candidate_id, cs.job_id, cs.moved_at,
                         {_KEY_CASE_SQL} AS key
                  FROM candidate_stages cs
                  JOIN touched t
                    ON t.candidate_id = cs.candidate_id AND t.job_id = cs.job_id
                  JOIN jobs j ON j.id = cs.job_id
                  LEFT JOIN def_map m ON m.def_id = cs.stage_def_id
                  WHERE j.status::text IN ('published', 'closed')
                    AND (cs.stage::text <> 'verified'
                         OR cs.verification_status::text = 'active')
                ),
                key_firsts AS (
                  SELECT key, min(moved_at) AS first_at
                  FROM keyed GROUP BY candidate_id, job_id, key
                ),
                pair_firsts AS (
                  SELECT min(moved_at) AS first_at
                  FROM keyed GROUP BY candidate_id, job_id
                )
                SELECT key, count(*) AS cnt
                FROM key_firsts
                WHERE first_at >= :start AND first_at < :end
                GROUP BY key
                UNION ALL
                SELECT '__pairs_added' AS key, count(*) AS cnt
                FROM pair_firsts
                WHERE first_at >= :start AND first_at < :end
                """
            ),
            params,
        )
    ).all()
    counts = {str(key): int(cnt) for key, cnt in rows}
    added = counts.pop("__pairs_added", 0)
    return counts, added


async def _hired_reached(db: AsyncSession, params: dict[str, Any]) -> int:
    """Placementy D2 — ta sama liczba co „Zatrudniony” w lejku."""

    job_filter = _JOB_FILTER_SQL.format(col="fm.job_id")
    value = (
        await db.execute(
            text(
                f"""
                SELECT count(*)
                FROM analytics_first_milestones fm
                WHERE fm.stage::text = 'hired'
                  AND fm.first_reached_at >= :start
                  AND fm.first_reached_at < :end
                  AND {job_filter}
                """
            ),
            params,
        )
    ).scalar_one()
    return int(value or 0)


async def _reassign_reached(db: AsyncSession, params: dict[str, Any]) -> int:
    job_filter = _JOB_FILTER_SQL.format(col="rp.job_id")
    value = (
        await db.execute(
            text(
                f"""
                SELECT count(*)
                FROM recruitment_processes rp
                JOIN jobs j ON j.id = rp.job_id
                WHERE rp.entry_source = 'reassign'
                  AND rp.status::text <> 'voided'
                  AND COALESCE(rp.opened_at, rp.created_at) >= :start
                  AND COALESCE(rp.opened_at, rp.created_at) < :end
                  AND j.status::text IN ('published', 'closed')
                  AND {job_filter}
                """
            ),
            params,
        )
    ).scalar_one()
    return int(value or 0)


async def _now(db: AsyncSession, params: dict[str, Any]) -> tuple[dict[str, int], int]:
    """Najnowszy wiersz pary w rekrutacjach opublikowanych — stan na dziś."""

    job_filter = _JOB_FILTER_SQL.format(col="cs.job_id")
    rows = (
        await db.execute(
            text(
                f"""
                WITH {_DEF_MAP_CTE},
                latest AS (
                  SELECT DISTINCT ON (cs.candidate_id, cs.job_id)
                         cs.candidate_id, cs.job_id, {_KEY_CASE_SQL} AS key
                  FROM candidate_stages cs
                  JOIN jobs j ON j.id = cs.job_id
                  LEFT JOIN def_map m ON m.def_id = cs.stage_def_id
                  WHERE j.status::text = 'published'
                    AND {job_filter}
                  ORDER BY cs.candidate_id, cs.job_id, cs.moved_at DESC, cs.id DESC
                )
                SELECT l.key, count(*) AS cnt,
                       count(*) FILTER (
                         WHERE EXISTS (
                           SELECT 1 FROM recruitment_processes rp
                           WHERE rp.candidate_id = l.candidate_id
                             AND rp.job_id = l.job_id
                             AND rp.status::text = 'open'
                             AND rp.entry_source = 'reassign'
                         )
                       ) AS reassign
                FROM latest l
                GROUP BY l.key
                """
            ),
            params,
        )
    ).all()
    counts: dict[str, int] = {}
    reassign = 0
    for key, cnt, reassign_cnt in rows:
        counts[str(key)] = int(cnt)
        if key == "added":
            reassign = int(reassign_cnt or 0)
    return counts, reassign


async def _closed_by(db: AsyncSession, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Pary, których najnowszy wiersz jest końcem procesu z datą w oknie.

    `ended_by` NULL (wiersz sprzed 0352 albo z importu) czytamy po typie końca:
    wycofanie = zrezygnował kandydat; odrzucenie z powodem „… przez
    Kandydata” (`CANDIDATE_DECISION_PATTERN`) też kandydat; reszta odrzuceń =
    „odrzucony przez nas”.
    """

    job_filter = _JOB_FILTER_SQL.format(col="cs.job_id")
    rows = (
        await db.execute(
            text(
                f"""
                WITH {_DEF_MAP_CTE},
                touched AS (
                  SELECT DISTINCT cs.candidate_id, cs.job_id
                  FROM candidate_stages cs
                  WHERE cs.moved_at >= :start AND cs.moved_at < :end
                    AND {job_filter}
                ),
                latest AS (
                  SELECT DISTINCT ON (cs.candidate_id, cs.job_id)
                         cs.moved_at, cs.stage::text AS stage, cs.ended_by,
                         cs.rejection_reason_id, cs.rejection_note,
                         m.o, {_KEY_CASE_SQL} AS key
                  FROM candidate_stages cs
                  JOIN touched t
                    ON t.candidate_id = cs.candidate_id AND t.job_id = cs.job_id
                  JOIN jobs j ON j.id = cs.job_id
                  LEFT JOIN def_map m ON m.def_id = cs.stage_def_id
                  WHERE j.status::text IN ('published', 'closed')
                  ORDER BY cs.candidate_id, cs.job_id, cs.moved_at DESC, cs.id DESC
                )
                SELECT
                  CASE
                    WHEN l.ended_by = ANY(CAST(:closed_by_keys AS text[]))
                      THEN l.ended_by
                    WHEN l.stage = 'withdrawn' OR l.o = '__withdrawn'
                      THEN 'candidate'
                    WHEN concat_ws(' ', rr.name, l.rejection_note)
                         ~* :candidate_decision
                      THEN 'candidate'
                    WHEN concat_ws(' ', rr.name, l.rejection_note)
                         ~* :client_decision
                      THEN 'client'
                    ELSE 'recruiter'
                  END AS who,
                  NULLIF(btrim(rr.name), '') AS reason_name,
                  NULLIF(btrim(l.rejection_note), '') AS reason_note,
                  count(*) AS cnt
                FROM latest l
                LEFT JOIN rejection_reasons rr ON rr.id = l.rejection_reason_id
                WHERE l.key = '__closed'
                  AND l.moved_at >= :start AND l.moved_at < :end
                GROUP BY 1, 2, 3
                """
            ),
            {
                **params,
                "closed_by_keys": list(_CLOSED_BY_KEYS),
                "candidate_decision": CANDIDATE_DECISION_PATTERN,
                "client_decision": CLIENT_DECISION_PATTERN,
            },
        )
    ).all()
    return [
        {
            "who": str(who),
            "reason_name": reason_name,
            "reason_note": reason_note,
            "count": int(cnt),
        }
        for who, reason_name, reason_note, cnt in rows
    ]


def _short(label: str) -> str:
    label = " ".join(label.split())
    if len(label) <= _REASON_MAX_CHARS:
        return label
    return label[: _REASON_MAX_CHARS - 1].rstrip() + "…"


def reason_label(name: Optional[str]) -> Optional[str]:
    """Etykieta powodu z katalogu po polsku; `None` = brak prawdziwego powodu.

    Kody zasiane migracjami tłumaczy wspólny słownik
    (`rejection_reason_label`); nazwa wpisana w szablonie przechodzi bez zmian.
    """

    if name is None or not name.strip():
        return None
    if name.strip() in _NO_REASON_CODES:
        return None
    return rejection_reason_label(name.strip())


def _detail(label: str, count: int) -> str:
    return label if count == 1 else f"{label} ({count})"


def summarize_closed_by(groups: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Grupy „kto zakończył” z powodami, których suma = liczba procesów.

    Każdy proces trafia do dokładnie jednego wiersza powodów:

    * powód z katalogu (etykieta po polsku) albo wolny tekst powtórzony co
      najmniej dwa razy — `TOP_REASONS` najczęstszych ma własny wiersz;
    * wolny tekst użyty raz i powody spoza pierwszej trójki — wiersz
      „Inne” z listą treści w `details` (dymek na ekranie; decyzja
      właściciela produktu 23.09.2026, żeby nic nie znikało z sumy);
    * brak powodu (także zaślepka importu `legacy_unknown` bez notatki) —
      „Bez podanego powodu”.
    """

    totals: dict[str, int] = defaultdict(int)
    named: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    free: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    free_labels: dict[str, dict[str, str]] = defaultdict(dict)
    missing: dict[str, int] = defaultdict(int)
    other_catalog: dict[str, int] = defaultdict(int)
    for g in groups:
        who = g["who"]
        count = int(g["count"])
        totals[who] += count
        catalog = reason_label(g.get("reason_name"))
        note = (g.get("reason_note") or "").strip()
        if catalog == OTHER_LABEL:
            # Katalogowe „Inne” z seeda 0006 — ten sam sens co zbiorczy wiersz,
            # więc tam trafia (dwa wiersze „Inne” obok siebie byłyby zagadką).
            other_catalog[who] += count
        elif catalog:
            named[who][_short(catalog)] += count
        elif note:
            label = _short(note)
            folded = label.casefold()
            free_labels[who].setdefault(folded, label)
            free[who][folded] += count
        else:
            missing[who] += count

    result: list[dict[str, Any]] = []
    for key, label in CLOSED_BY:
        reasons: dict[str, int] = dict(named[key])
        singles: list[tuple[str, int]] = []
        for folded, count in free[key].items():
            text_label = free_labels[key][folded]
            if count >= 2:
                reasons[text_label] = reasons.get(text_label, 0) + count
            else:
                singles.append((text_label, count))
        if other_catalog[key]:
            singles.append((OTHER_CATALOG_DETAIL, other_catalog[key]))
        ranked = sorted(reasons.items(), key=lambda item: (-item[1], item[0]))
        top = ranked[:TOP_REASONS]
        other = sorted(
            ranked[TOP_REASONS:] + singles, key=lambda item: (-item[1], item[0])
        )

        top_reasons: list[dict[str, Any]] = [
            {"label": name, "count": count, "kind": "reason", "details": []}
            for name, count in top
        ]
        if other:
            details = [_detail(name, count) for name, count in other]
            if len(details) > OTHER_DETAILS_MAX:
                rest = len(details) - OTHER_DETAILS_MAX
                details = details[:OTHER_DETAILS_MAX] + [f"… i jeszcze {rest}"]
            top_reasons.append(
                {
                    "label": OTHER_LABEL,
                    "count": sum(count for _, count in other),
                    "kind": "other",
                    "details": details,
                }
            )
        if missing[key]:
            top_reasons.append(
                {
                    "label": NO_REASON_LABEL,
                    "count": missing[key],
                    "kind": "none",
                    "details": [],
                }
            )
        result.append(
            {
                "key": key,
                "label": label,
                "count": totals.get(key, 0),
                "top_reasons": top_reasons,
            }
        )
    return result


async def compute_stage_breakdown(
    db: AsyncSession,
    *,
    start: datetime,
    end: datetime,
    job_ids: Optional[Sequence[int]] = None,
) -> dict[str, Any]:
    """Wiersze „Lejka po etapach” i „Zamknięci — kto skończył”.

    Sześć zapytań niezależnie od liczby etapów i szablonów. `job_ids` zawęża
    wynik (testy na wspólnej bazie); API go nie przekazuje.
    """

    def_ids, def_keys = await _load_def_map(db)
    params: dict[str, Any] = {
        "start": start,
        "end": end,
        "def_ids": def_ids,
        "def_keys": def_keys,
        "job_ids": list(job_ids) if job_ids is not None else None,
    }

    reached, added = await _reached(db, params)
    reached["added"] = added
    reached["hired"] = await _hired_reached(db, params)
    reached["reassign"] = await _reassign_reached(db, params)

    now, reassign_now = await _now(db, params)
    now["reassign"] = reassign_now

    closed = summarize_closed_by(await _closed_by(db, params))

    rows = [
        {
            "column": row.column,
            "column_label": row.column_label,
            "key": row.key,
            "label": row.label,
            "is_main": row.is_main,
            "reached": reached.get(row.key, 0),
            "now": now.get(row.key, 0),
        }
        for row in ROWS
    ]
    return {"rows": rows, "closed_by": closed, "definitions": dict(DEFINITIONS)}
