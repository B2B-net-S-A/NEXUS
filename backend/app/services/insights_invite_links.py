"""Skuteczność linków aplikacyjnych — jedna implementacja dla dwóch powierzchni.

`/api/reports/invite-links` (admin/DL/HoR/finance) i nowy
`/api/insights/recruitment/invite-links` (D7: każdy zalogowany) muszą pokazywać
TE SAME liczby. Guard i kształt odpowiedzi zostają w routerach — tutaj jest
wyłącznie liczenie.

Trzy rzeczy, które trzeba o tych liczbach wiedzieć, zanim się je zinterpretuje:

1. **``applications`` to LICZNIK NA LINKU, nie zdarzenia w oknie.**
   ``CandidateInviteLink.use_count`` rośnie przy każdej udanej aplikacji
   (``public_share.py``) i jest kumulatywny od chwili powstania linku. Okno
   filtruje więc LINKI (po ``created_at``), a nie aplikacje: link założony
   w oknie wnosi WSZYSTKIE swoje aplikacje, także te sprzed granicy okna
   i te po niej. Nie da się tego naprawić bez tabeli zdarzeń, więc
   ``/insights`` mówi to wprost w kopercie, zamiast udawać precyzję,
   której nie ma.

2. **Linki cofnięte są wyłączone.** ``revoked`` znaczy „ten kanał już nie
   działa"; wliczanie go rozcieńczałoby konwersję kanałów żywych.

3. **Procenty liczy ROUTER.** Legacy używa ``_safe_pct`` (0.0 przy zerowym
   mianowniku), Insights ``_ratio`` (``None``). Serwis zwraca surowe liczniki,
   żeby żadna z tych konwencji nie wyciekła do drugiej powierzchni.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.invite_link import CandidateInviteLink

__all__ = [
    "InviteLinkChannelRow",
    "compute_invite_link_channels",
    "count_invite_link_candidates",
]

# Prefiks, którym `public_share.py` stempluje `Candidate.source` przy aplikacji
# z linku (`invite_link:<prefiks tokenu>`). Kolumna jest indeksowana, więc LIKE
# po niej jest tani i nie wymaga wchodzenia w JSON.
_INVITE_SOURCE_PREFIX = "invite_link:%"


@dataclass(frozen=True)
class InviteLinkChannelRow:
    """Jeden kanał (etykieta linku). ``channel is None`` = link bez etykiety."""

    channel: str | None
    links_count: int
    applications: int
    last_used_at: datetime | None


def _window(column, since: datetime | None, until: datetime | None) -> list:
    """Predykaty okna dla kolumny czasu.

    ``since=None`` daje „od zawsze" (legacy ``period='all'``), ``until=None``
    brak sufitu (kroczące okno legacy). Rozdzielenie jest celowe: półotwarte
    ``[since, until)`` z ``resolve_period`` i kroczące okno legacy to dwie różne
    semantyki i żadna nie może narzucić się drugiej powierzchni po cichu.
    """
    out = []
    if since is not None:
        out.append(column >= since)
    if until is not None:
        out.append(column < until)
    return out


async def compute_invite_link_channels(
    db: AsyncSession,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[InviteLinkChannelRow]:
    """Rollup linków aplikacyjnych po etykiecie kanału, malejąco po aplikacjach."""
    rows = (
        await db.execute(
            select(
                CandidateInviteLink.label.label("channel"),
                func.count(CandidateInviteLink.token).label("links_count"),
                func.coalesce(func.sum(CandidateInviteLink.use_count), 0).label(
                    "applications"
                ),
                func.max(CandidateInviteLink.last_used_at).label("last_used_at"),
            )
            .where(
                CandidateInviteLink.revoked.is_(False),
                *_window(CandidateInviteLink.created_at, since, until),
            )
            .group_by(CandidateInviteLink.label)
            .order_by(func.coalesce(func.sum(CandidateInviteLink.use_count), 0).desc())
        )
    ).all()

    return [
        InviteLinkChannelRow(
            channel=r.channel,
            links_count=int(r.links_count or 0),
            applications=int(r.applications or 0),
            last_used_at=r.last_used_at,
        )
        for r in rows
    ]


async def count_invite_link_candidates(
    db: AsyncSession,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> int:
    """Unikalni kandydaci, którzy weszli linkiem aplikacyjnym.

    Okno filtruje tu ``Candidate.created_at``, czyli MOMENT APLIKACJI — inaczej
    niż w rollupie kanałów, gdzie filtrowany jest moment założenia linku. To nie
    jest niespójność do naprawienia, tylko jedyna liczba w tej sekcji, którą da
    się przypiąć do okna uczciwie; koperta ``/insights`` mówi o tym wprost.
    """
    return int(
        (
            await db.execute(
                select(func.count(func.distinct(Candidate.id))).where(
                    Candidate.source.like(_INVITE_SOURCE_PREFIX),
                    *_window(Candidate.created_at, since, until),
                )
            )
        ).scalar()
        or 0
    )
