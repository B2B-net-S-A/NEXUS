"""How full each searchable candidate column actually is.

Written for the Champion "recommended searches" prompt. The LLM designs
structured filters, and a filter over a column that is empty for 99% of the
base does not narrow a search — it empties it. Measured on prod 2026-08-07, an
AI-proposed "2-6 years of experience" chip took a genuinely relevant pool of
11 091 people down to 45, entirely because ``years_it_experience`` is filled
for 1.2% of rows.

A flat prohibition in the prompt ("do not use experience_years") would be a
patch: the next author to touch the prompt sees a field that looks perfectly
sensible and adds it back. Injecting the *measured* density instead makes the
instruction self-correcting — when a column fills up, the prompt stops warning
against it without anyone editing a line.

Cached for a day: these numbers move on the scale of imports and backfills,
and the prompt is rendered at most a few times per hour.

One row here is not a measurement of the column itself but a lower-bound
estimate of state held in another system — see ``_LOWER_BOUND_ONLY``.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 24 * 60 * 60

# (label, SQL predicate for "this row has a usable value").
# `skills` is deliberately counted as *non-empty array*, not `IS NOT NULL`:
# 33 625 rows hold `[]`, which is present-but-useless and would otherwise
# report 60% coverage for a column that can answer 0.5% of skill filters.
_COLUMNS: tuple[tuple[str, str], ...] = (
    ("embedding_id", "embedding_id IS NOT NULL"),
    # ↑ jedyna pozycja, która NIE jest pomiarem stanu kolumny "na wartość", tylko
    # oszacowaniem stanu W INNYM SYSTEMIE — patrz `_LOWER_BOUND_ONLY` niżej.
    ("raw_cv_text", "raw_cv_text IS NOT NULL AND btrim(raw_cv_text) <> ''"),
    ("competence_category_id", "competence_category_id IS NOT NULL"),
    ("ai_summary", "ai_summary IS NOT NULL AND btrim(ai_summary) <> ''"),
    (
        "location",
        "(city IS NOT NULL AND btrim(city) <> '') "
        "OR (location IS NOT NULL AND btrim(location) <> '')",
    ),
    ("years_it_experience", "years_it_experience IS NOT NULL"),
    (
        "skills",
        "jsonb_typeof(skills) = 'array' AND skills <> '[]'::jsonb",
    ),
    ("expected_rate_hourly", "expected_rate_hourly IS NOT NULL"),
)


# Kolumny, których liczba jest DOLNĄ GRANICĄ, nie pomiarem.
#
# `candidates.embedding_id` to kopia identyfikatora zapisywana przez
# `embed_candidate`, więc mierzy nie samą siebie, tylko obecność wektora
# w Qdrancie — a Qdrant o tym zapisie nie wie. Wektor da się dołożyć i usunąć
# poza ścieżkami, które tę kolumnę piszą (ręczny `delete`, przebudowa kolekcji,
# odtworzenie ze starszej migawki), więc żadna liczba stąd nie jest twarda.
# Jedynym autorytetem jest `embedding_service.indexed_candidate_ids` — pyta
# Qdranta wprost i zwraca `None`, gdy nie umie odpowiedzieć.
#
# Bez tego znacznika 80,1% w prompcie czyta się jak zmierzony fakt i prowadzi do
# wniosku "co piąty kandydat jest niewyszukiwalny" — czyli do backfillu, który
# w większości przeliczyłby wektory już istniejące.
_LOWER_BOUND_ONLY: frozenset[str] = frozenset({"embedding_id"})


@dataclass(frozen=True)
class ColumnCoverage:
    total: int
    pct: dict[str, float]

    def as_prompt_block(self) -> str:
        """Render as the prompt section, densest column first."""
        if not self.total:
            return ""
        lines = [f"POKRYCIE DANYCH W BAZIE ({self.total} kandydatów, pomiar bieżący):"]
        for name, pct in sorted(self.pct.items(), key=lambda kv: -kv[1]):
            marker = "  ← filtr po tym polu prawie nic nie zwróci" if pct < 20 else ""
            if not marker and name in _LOWER_BOUND_ONLY:
                # Bez "←": ten znak niesie w bloku znaczenie "kolumna zbyt rzadka
                # na filtr", a tu chodzi o coś innego — liczba jest niepewna,
                # nie niska.
                marker = "  (dolna granica, nie pomiar — kolumna nie jest autorytetem)"
            lines.append(f"  {name:24s} {pct:5.1f}%{marker}")
        lines.append(
            "Filtruj po kolumnach o WYSOKIM pokryciu. Sygnały z kolumn rzadkich "
            "(poniżej 20%) przenoś do `q` — wyszukiwanie semantyczne czyta je "
            "z treści CV — zamiast robić z nich filtr strukturalny, który wytnie "
            "kandydatów tylko dlatego, że nikt nie uzupełnił rubryki."
        )
        return "\n".join(lines)


_cache: tuple[float, ColumnCoverage] | None = None


async def candidate_column_coverage(db: AsyncSession) -> ColumnCoverage:
    """Percentage of candidates with a usable value in each searchable column.

    One query, all columns — a `count(*) FILTER (WHERE ...)` per column over a
    single sequential scan rather than N separate ones.
    """
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < _CACHE_TTL_SECONDS:
        return _cache[1]

    selects = ", ".join(
        f"count(*) FILTER (WHERE {pred}) AS {name}" for name, pred in _COLUMNS
    )
    row = (
        (await db.execute(text(f"SELECT count(*) AS total, {selects} FROM candidates")))
        .mappings()
        .one()
    )

    total = int(row["total"] or 0)
    pct = {
        name: (round(100.0 * int(row[name] or 0) / total, 1) if total else 0.0)
        for name, _ in _COLUMNS
    }
    coverage = ColumnCoverage(total=total, pct=pct)
    _cache = (now, coverage)
    return coverage


def reset_cache_for_tests() -> None:
    global _cache
    _cache = None
