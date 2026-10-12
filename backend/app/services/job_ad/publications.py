"""Gdzie wisi ogłoszenie — oznaczenia publikacji (0431).

Rekruter wkleja treść na portalu ręcznie, a potem oznacza to tutaj. Stan
czyta okno „Ogłoszenie na portale”, sekcja „Zespół i ogłoszenie” i kolumna
„Ogłoszenia” na liście rekrutacji.

„Do aktualizacji” znaczy: zapisana treść ogłoszenia (język, pola, technologie)
jest inna niż w chwili oznaczenia. Odcisk liczy się z samego wiersza
``job_ads``, żeby lista rekrutacji mogła go policzyć jednym zapytaniem na
stronę; zmiana samej rekrutacji albo stałych bloków firmy go nie rusza —
o zmianie rekrutacji mówi baner ``stale`` w oknie.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Optional
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job_ad import JobAd
from app.models.job_ad_publication import JobAdPublication
from app.models.user import User
from app.services.job_ad_publication_schema import (
    PORTAL_JJIT,
    PORTAL_PRACUJ,
    PORTALS,
    URL_MAX,
)

_HASH_VERSION = "v1"
# Link prowadzi z listy rekrutacji prosto na portal — przyjmujemy tylko adres
# tego portalu, nie dowolną stronę.
_PORTAL_DOMAINS = {PORTAL_PRACUJ: "pracuj.pl", PORTAL_JJIT: "justjoin.it"}
_PORTAL_NAMES = {PORTAL_PRACUJ: "Pracuj.pl", PORTAL_JJIT: "JustJoin.IT"}


@dataclass(frozen=True)
class Publication:
    portal: str
    url: Optional[str]
    outdated: bool
    published_at: datetime
    published_by_name: Optional[str] = None
    removed_at: Optional[datetime] = None


def content_hash(lang: str, content: Any, tech: Any) -> str:
    """Odcisk zapisanej treści ogłoszenia."""
    payload = json.dumps(
        {"v": _HASH_VERSION, "lang": lang, "content": content, "tech": tech},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def ad_hash(ad: JobAd) -> str:
    return content_hash(ad.lang, ad.content, ad.tech)


def clean_url(value: Optional[str], portal: str) -> Optional[str]:
    """Adres ogłoszenia na portalu albo ``None``; błąd po polsku."""
    text = (value or "").strip()
    if not text:
        return None
    name = _PORTAL_NAMES[portal]
    if len(text) > URL_MAX or any(ch.isspace() or not ch.isprintable() for ch in text):
        raise ValueError(f"To nie wygląda na link do ogłoszenia na {name}.")
    parts = urlsplit(text)
    host = (parts.hostname or "").lower()
    domain = _PORTAL_DOMAINS[portal]
    if (
        parts.scheme not in ("http", "https")
        or parts.username is not None
        or parts.password is not None
        or not (host == domain or host.endswith("." + domain))
    ):
        raise ValueError(
            f"Wklej adres ogłoszenia z {name} (zaczyna się od https://) albo "
            "zostaw pole puste."
        )
    return text


def _sorted(items: Iterable[Publication]) -> list[Publication]:
    return sorted(items, key=lambda item: PORTALS.index(item.portal))


async def for_job(
    db: AsyncSession, job_id: int, ad: Optional[JobAd]
) -> list[Publication]:
    """Oznaczenia jednej rekrutacji, także zdjęte (ślad), w kolejności portali."""
    rows = (
        await db.execute(
            select(JobAdPublication, User.name)
            .outerjoin(User, User.id == JobAdPublication.published_by)
            .where(JobAdPublication.job_id == job_id)
        )
    ).all()
    current = ad_hash(ad) if ad is not None else None
    return _sorted(
        Publication(
            portal=row.portal,
            url=row.url,
            outdated=row.removed_at is None and row.content_hash != current,
            published_at=row.published_at,
            published_by_name=name,
            removed_at=row.removed_at,
        )
        for row, name in rows
    )


async def for_jobs(
    db: AsyncSession, job_ids: Iterable[int]
) -> dict[int, list[Publication]]:
    """Aktywne ogłoszenia dla strony listy rekrutacji — jedno zapytanie."""
    ids = list(dict.fromkeys(job_ids))
    out: dict[int, list[Publication]] = {job_id: [] for job_id in ids}
    if not ids:
        return out
    rows = (
        await db.execute(
            select(JobAdPublication, JobAd.lang, JobAd.content, JobAd.tech)
            .outerjoin(JobAd, JobAd.job_id == JobAdPublication.job_id)
            .where(
                JobAdPublication.job_id.in_(ids),
                JobAdPublication.removed_at.is_(None),
            )
        )
    ).all()
    hashes: dict[int, Optional[str]] = {}
    for row, lang, content, tech in rows:
        if row.job_id not in hashes:
            hashes[row.job_id] = (
                content_hash(lang, content, tech) if content is not None else None
            )
        out[row.job_id].append(
            Publication(
                portal=row.portal,
                url=row.url,
                outdated=row.content_hash != hashes[row.job_id],
                published_at=row.published_at,
            )
        )
    return {job_id: _sorted(items) for job_id, items in out.items()}


async def mark_published(
    db: AsyncSession, ad: JobAd, *, portal: str, url: Optional[str], user_id: int
) -> None:
    """Ogłoszenie wisi na portalu w OBECNEJ treści. Ponowne oznaczenie
    (zmiana linku, aktualizacja po poprawce, powrót po zdjęciu) nadpisuje
    wiersz — bez wyścigu o klucz przy dwóch kliknięciach naraz."""
    now = datetime.now(timezone.utc)
    values = {
        "url": url,
        "content_hash": ad_hash(ad),
        "published_at": now,
        "published_by": user_id,
        "removed_at": None,
        "removed_by": None,
        "updated_at": now,
    }
    await db.execute(
        pg_insert(JobAdPublication)
        .values(job_id=ad.job_id, portal=portal, **values)
        .on_conflict_do_update(
            index_elements=[JobAdPublication.job_id, JobAdPublication.portal],
            set_=values,
        )
    )


async def mark_removed(
    db: AsyncSession, job_id: int, *, portal: str, user_id: int
) -> bool:
    """Zdjęte z portalu. ``False`` = nie było aktywnego oznaczenia."""
    row = await db.get(JobAdPublication, (job_id, portal), with_for_update=True)
    if row is None or row.removed_at is not None:
        return False
    row.removed_at = datetime.now(timezone.utc)
    row.removed_by = user_id
    return True
