"""Cienka warstwa do fundamentu asystenta prawnego (część A planu).

Cały kontakt pakietu ``legal_redline`` z fundamentem jest w tym module:
``SourcePassage`` z ``legal.citations``, maska z ``legal.pseudonymize``
(odmiana nazwisk, numery z cyfrą kontrolną) i przepisy z korpusu
(``corpus.search_provisions``).

Sprawdzanie cytatów zmian (``verify_sources``) jest własne: cytat zmiany to
dosłowny fragment źródła o danym ``ref``, a nie odwołanie w tekście, które
rozbiera ``citations.verify`` fundamentu.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import replace
from typing import Any

from app.services.legal.citations import SourcePassage
from app.services.legal.pseudonymize import Entity, mask, unknown_tokens, unmask
from app.services.legal_redline.model import ChangeSource

__all__ = [
    "Entity",
    "SourcePassage",
    "mask",
    "search_law",
    "unknown_tokens",
    "unmask",
    "verify_sources",
]

logger = logging.getLogger(__name__)

#: Tyle znaków przepisu idzie do modelu (art. 21 ustawy o PIT ma 120 tys.).
LAW_PASSAGE_CHARS = 6000


async def search_law(db: Any, query: str, *, limit: int = 8) -> list[SourcePassage]:
    """Przepisy z korpusu do polecenia; ``ref`` niesie klucz aktu („kc art. 77 § 1”).

    Źródła są dodatkiem: awaria wyszukiwania daje pustą listę, a model cytuje
    wtedy tylko sam dokument (i to sprawdza kod).
    """

    from sqlalchemy.exc import SQLAlchemyError  # noqa: PLC0415

    from app.services.legal import corpus  # noqa: PLC0415

    try:
        hits = await corpus.search_provisions(db, query, limit=limit)
    except Exception as exc:  # noqa: BLE001 — źródła to dodatek
        logger.warning(
            "legal_redline: wyszukiwanie przepisów nieudane (%s)", type(exc).__name__
        )
        if isinstance(exc, SQLAlchemyError):
            await db.rollback()
        return []
    from app.services.legal.assistant import allowed_passages  # noqa: PLC0415

    return allowed_passages(
        SourcePassage(
            kind="law",
            ref=f"{hit.act_key} {hit.ref}",
            text=hit.text[:LAW_PASSAGE_CHARS],
            url=hit.url,
            label=f"{hit.ref} {hit.act_short_name} (tekst od {hit.valid_from.isoformat()})",
            act_key=hit.act_key,
        )
        for hit in hits
    )


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[„”“\"«»]", '"', text)
    text = re.sub(r"[’‘']", "'", text)
    text = re.sub(r"[‐‑‒–—]", "-", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def verify_sources(
    sources: list[ChangeSource], passages: list[SourcePassage]
) -> list[ChangeSource]:
    """Stan każdego cytatu: ``ok`` (dosłownie w źródle), ``mismatch`` (źródło jest,
    cytatu w nim nie ma), ``missing`` (źródła o tym ``ref`` nie podaliśmy)."""

    by_ref = {p.ref: p for p in passages}
    checked = []
    for source in sources:
        passage = by_ref.get(source.ref)
        if passage is None:
            state = "missing"
        elif source.quote.strip() and _normalize(source.quote) in _normalize(
            passage.text
        ):
            state = "ok"
        else:
            state = "mismatch"
        checked.append(
            replace(
                source,
                state=state,
                kind=passage.kind if passage else source.kind,
                url=passage.url if passage else source.url,
                label=source.label
                or (passage.label if passage and passage.label else source.ref),
            )
        )
    return checked
