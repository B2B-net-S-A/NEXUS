"""Zasilenie pamięci orzeczeń z SAOS: tematy umów B2B → zapytania → zapis.

Wywołuje je skrypt ``scripts/seed_legal_case_law.py`` (ręcznie, nie w pętli
aplikacji). Każde zapytanie to jedno wyszukiwanie i najwyżej ``per_query``
pobrań treści, w tempie klienta SAOS (1 zapytanie na sekundę).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import date
from typing import Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.legal_case_law import saos
from app.services.legal_case_law.http import PoliteClient
from app.services.legal_case_law.store import store_records

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TopicQuery:
    query: str
    court_type: str
    since: Optional[date] = None


@dataclass(frozen=True)
class Topic:
    key: str
    label: str
    queries: tuple[TopicQuery, ...]


#: Tematy z planu (część C): kwalifikacja umowy B2B, autorskie, kary umowne,
#: wypowiedzenie usług, zakaz konkurencji. SN w SAOS kończy się na 2016 r.,
#: więc nowsze stanowiska dają sądy apelacyjne (sądy powszechne od 2020 r.).
TOPICS: tuple[Topic, ...] = (
    Topic(
        "b2b_employment",
        "Umowa B2B a stosunek pracy (art. 22 KP)",
        (
            TopicQuery('"stosunek pracy" "umowa cywilnoprawna" art. 22', "supreme"),
            TopicQuery('"działalność gospodarcza" "stosunek pracy" samozatrudnienie', "supreme"),
            TopicQuery('"ustalenie istnienia stosunku pracy" "działalności gospodarczej"', "common", date(2020, 1, 1)),
        ),
    ),
    Topic(
        "copyright_transfer",
        "Przeniesienie autorskich praw majątkowych (forma, pola eksploatacji)",
        (
            TopicQuery('"przeniesienie autorskich praw majątkowych" "formy pisemnej"', "supreme"),
            TopicQuery('"pola eksploatacji" "autorskich praw majątkowych" umowa', "supreme"),
            TopicQuery('"przeniesienie autorskich praw majątkowych" "pola eksploatacji"', "common", date(2020, 1, 1)),
        ),
    ),
    Topic(
        "penalty_reduction",
        "Kara umowna i miarkowanie (art. 484 § 2 KC)",
        (
            TopicQuery('"miarkowanie kary umownej"', "supreme"),
            TopicQuery('"kara umowna" "rażąco wygórowana"', "supreme"),
            TopicQuery('"miarkowanie kary umownej" "484 § 2"', "common", date(2022, 1, 1)),
        ),
    ),
    Topic(
        "service_termination",
        "Wypowiedzenie umowy o świadczenie usług (art. 746 i 750 KC)",
        (
            TopicQuery('"art. 746" "ważnych powodów" wypowiedzenie zlecenia', "supreme"),
            TopicQuery('"umowa o świadczenie usług" "art. 750" wypowiedzenie', "supreme"),
            TopicQuery('"art. 746" "ważnych powodów" "świadczenie usług"', "common", date(2020, 1, 1)),
        ),
    ),
    Topic(
        "non_compete",
        "Zakaz konkurencji w umowie cywilnoprawnej",
        (
            TopicQuery('"zakaz konkurencji" "umowy cywilnoprawnej"', "supreme"),
            TopicQuery('"zakazu konkurencji" "odszkodowanie" "po ustaniu"', "supreme"),
            TopicQuery('"zakaz konkurencji" "umowa o współpracy" "kara umowna"', "common", date(2020, 1, 1)),
        ),
    ),
)


@dataclass(frozen=True)
class TopicReport:
    key: str
    found: int
    fetched: int
    inserted: int
    updated: int
    unchanged: int


async def ingest_topic(
    db: AsyncSession,
    client: PoliteClient,
    topic: Topic,
    *,
    per_query: int = 8,
    skip_ids: Sequence[int] = (),
) -> TopicReport:
    """Pobiera orzeczenia tematu i zapisuje je (commit po temacie)."""
    seen: set[int] = set()
    records: list[saos.CaseRecord] = []
    found = 0
    skipped = set(skip_ids)
    for topic_query in topic.queries:
        ids = await saos.search_ids(
            client,
            topic_query.query,
            court_type=topic_query.court_type,
            since=topic_query.since,
            limit=per_query,
        )
        found += len(ids)
        fresh = [i for i in ids if i not in seen and i not in skipped]
        seen.update(ids)
        for record in await saos.fetch_many(client, fresh):
            records.append(replace(record, topics=(topic.key,)))
    result = await store_records(db, records)
    await db.commit()
    logger.info(
        "[orzecznictwo] %s: znaleziono %s, pobrano %s, nowe %s",
        topic.key,
        found,
        len(records),
        result.inserted,
    )
    return TopicReport(
        topic.key, found, len(records), result.inserted, result.updated, result.unchanged
    )
