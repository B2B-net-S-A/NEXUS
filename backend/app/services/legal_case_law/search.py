"""``search_case_law`` — orzeczenia z pamięci NEXUSA jako ``SourcePassage(kind="case")``.

Kolejność: po słowach (tsvector na tekście bez polskich znaków: najpierw
orzeczenia z największą liczbą słów pytania, potem ``ts_rank``) i po
znaczeniu (Qdrant), złączone RRF. Bez wektorów zostaje ranking po słowach.
Wyszukiwanie czyta tylko bazę — źródła zewnętrzne odpytuje zasilenie
(``scripts/seed_legal_case_law.py``), więc awaria SAOS nie dotyka asystenta.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional, Sequence

from sqlalchemy import Integer, cast, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.legal_case_law import LegalCase
from app.services.framework_contract_text import query_stems
from app.services.help_search import fold
from app.services.hybrid_search import reciprocal_rank_fusion
from app.services.legal_case_law import index, schema
from app.services.legal_case_law.passage import SourcePassage

logger = logging.getLogger(__name__)

KEYWORD_HITS = 20
MAX_LIMIT = 20
EXCERPT_CHARS = 1200
SUMMARY_CHARS = 1500
MAX_HITS = 2000
DUPLICATE_PREFIX = 300

RETRIEVAL_HYBRID = "hybrid"
RETRIEVAL_KEYWORDS = "keywords"
RETRIEVAL_NONE = "none"

_KIND_LABELS = {
    "judgment": "wyrok",
    "decision": "postanowienie",
    "resolution": "uchwała",
    "order": "zarządzenie",
    "reasons": "uzasadnienie",
    "interpretation": "interpretacja",
}
_COURT_SHORT = {"supreme": "SN", "constitutional": "TK", "appeal_chamber": "KIO"}


@dataclass(frozen=True)
class CaseLawOutcome:
    passages: list[SourcePassage]
    retrieval: str


def normalize_courts(courts: Optional[Iterable[str]]) -> Optional[frozenset[str]]:
    """Znane rodzaje sądów; nieznane wartości odpadają (``None`` = wszystkie)."""
    if not courts:
        return None
    known = frozenset(c for c in courts if c in schema.COURT_TYPES)
    return known or None


def label_for(row: LegalCase) -> str:
    kind = _KIND_LABELS.get(row.kind, "orzeczenie")
    court = _COURT_SHORT.get(row.court_type) or row.court.split(" — ")[0]
    when = f" z {row.judgment_date:%d.%m.%Y} r." if row.judgment_date else ""
    return f"{court}, {kind}{when}, {row.signature}"


def fold_same_length(text: str) -> str:
    """``fold`` znak w znak: pozycje trafień zgadzają się z oryginałem.

    Zwykłe ``fold`` rozkłada np. „…” na trzy kropki i przesuwa pozycje.
    """
    out = []
    for ch in text:
        folded = fold(ch)
        out.append(folded[0] if folded else " ")
    return "".join(out)


def best_hit(folded: str, stems: Sequence[str], span: int) -> int:
    """Początek okna ``span`` znaków z największą liczbą różnych słów pytania.

    Nagłówek wyroku („Sąd … w składzie”) zawiera zwykle jedno słowo pytania;
    okno z kilkoma różnymi słowami to fragment o sprawie. ``-1`` = brak trafień.
    """
    hits: list[tuple[int, str]] = []
    for stem in stems:
        for match in re.finditer(rf"\b{re.escape(stem)}", folded):
            hits.append((match.start(), stem))
            if len(hits) >= MAX_HITS:
                break
    if not hits:
        return -1
    hits.sort()
    best, best_score, right = -1, (0, 0), 0
    for left, (position, _stem) in enumerate(hits):
        right = max(right, left)
        while right + 1 < len(hits) and hits[right + 1][0] < position + span:
            right += 1
        window = hits[left : right + 1]
        score = (len({stem for _p, stem in window}), len(window))
        if score > best_score:
            best, best_score = position, score
    return best


def excerpt(text: str, stems: Sequence[str], size: int = EXCERPT_CHARS) -> str:
    """Fragment z największą liczbą słów pytania; bez trafienia — początek tekstu."""
    if len(text) <= size:
        return text
    hit = best_hit(fold_same_length(text), stems, size * 2 // 3)
    if hit < 0:
        start = 0
    else:
        start = max(0, hit - size // 3)
        # Początek na granicy zdania albo słowa, żeby cytat nie zaczynał się w pół wyrazu.
        sentence = text.rfind(". ", max(0, start - 200), hit)
        if sentence >= 0:
            start = sentence + 2
        else:
            space = text.find(" ", start, hit)
            start = space + 1 if space >= 0 else start
    end = min(len(text), start + size)
    if end < len(text):
        space = text.rfind(" ", start, end)
        end = space if space > start else end
    prefix = "… " if start > 0 else ""
    suffix = " …" if end < len(text) else ""
    return f"{prefix}{text[start:end].strip()}{suffix}"


def to_passage(row: LegalCase, stems: Sequence[str]) -> SourcePassage:
    body = excerpt(row.text, stems)
    if row.summary:
        body = f"{row.summary[:SUMMARY_CHARS]}\n\n{body}"
    return SourcePassage(
        kind="case", ref=row.signature, text=body, url=row.url, label=label_for(row)
    )


def _filters(courts: Optional[frozenset[str]], since: Optional[date]) -> list:
    clauses = []
    if courts:
        clauses.append(LegalCase.court_type.in_(sorted(courts)))
    if since:
        clauses.append(LegalCase.judgment_date >= since)
    return clauses


async def keyword_ranking(
    db: AsyncSession,
    stems: Sequence[str],
    courts: Optional[frozenset[str]],
    since: Optional[date],
) -> list[int]:
    if not stems:
        return []
    any_query = func.to_tsquery("simple", literal(" | ".join(f"{s}:*" for s in stems)))
    coverage = sum(
        cast(LegalCase.search_tsv.op("@@")(func.to_tsquery("simple", literal(f"{s}:*"))), Integer)
        for s in stems
    )
    rows = await db.execute(
        select(LegalCase.id)
        .where(LegalCase.search_tsv.op("@@")(any_query), *_filters(courts, since))
        .order_by(
            coverage.desc(),
            func.ts_rank(LegalCase.search_tsv, any_query, 32).desc(),
            LegalCase.judgment_date.desc().nullslast(),
        )
        .limit(KEYWORD_HITS)
    )
    return [int(case_id) for case_id in rows.scalars()]


async def search_case_law_outcome(
    db: AsyncSession,
    query: str,
    *,
    courts: Optional[Iterable[str]] = None,
    since: Optional[date] = None,
    limit: int = 5,
) -> CaseLawOutcome:
    stems = query_stems(query)
    if not stems:
        return CaseLawOutcome([], RETRIEVAL_NONE)
    wanted = normalize_courts(courts)
    limit = max(1, min(limit, MAX_LIMIT))
    keyword_ids = await keyword_ranking(db, stems, wanted, since)
    vector_ids = await index.vector_ranking(query)
    retrieval = RETRIEVAL_KEYWORDS
    ranked = keyword_ids
    if vector_ids:
        allowed = set(
            (
                await db.execute(
                    select(LegalCase.id).where(
                        LegalCase.id.in_(vector_ids), *_filters(wanted, since)
                    )
                )
            ).scalars()
        )
        fused = reciprocal_rank_fusion(
            [[i for i in vector_ids if i in allowed], keyword_ids]
        )
        ranked = [case_id for case_id, _score in fused]
        retrieval = RETRIEVAL_HYBRID
    # Zapas na pominięte powtórki tekstu.
    top = ranked[: limit * 2]
    if not top:
        return CaseLawOutcome([], RETRIEVAL_NONE)
    rows = {
        row.id: row
        for row in (
            await db.execute(select(LegalCase).where(LegalCase.id.in_(top)))
        ).scalars()
    }
    passages: list[SourcePassage] = []
    seen: set[str] = set()
    # SAOS ma czasem ten sam wyrok pod sygnaturą sądu I i II instancji (tekst różni
    # się o kilka akapitów) — ten sam początek fragmentu = jedna pozycja.
    for case_id in top:
        if len(passages) >= limit:
            break
        row = rows.get(case_id)
        if row is None:
            continue
        passage = to_passage(row, stems)
        opening = " ".join(passage.text.split())[:DUPLICATE_PREFIX]
        if row.content_sha256 in seen or opening in seen:
            continue
        seen.update((row.content_sha256, opening))
        passages.append(passage)
    return CaseLawOutcome(passages, retrieval)


async def search_case_law(
    db: AsyncSession,
    query: str,
    *,
    courts: Optional[Iterable[str]] = None,
    since: Optional[date] = None,
    limit: int = 5,
) -> list[SourcePassage]:
    """Orzeczenia pasujące do pytania (kontrakt części C planu asystenta)."""
    outcome = await search_case_law_outcome(
        db, query, courts=courts, since=since, limit=limit
    )
    return outcome.passages
