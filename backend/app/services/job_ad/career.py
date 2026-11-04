"""Strona kariery z ogłoszenia — jedna treść rekrutacji (21.10.2026).

Do tej daty strona ``kariera.b2bnetwork.pl/r/<slug>`` miała własny „Opis
publiczny” (osobny szkic AI, osobna kontrola, „Zapisz” + „Zatwierdź”), a 203
z 205 otwartych rekrutacji nie miało strony wcale. Teraz „Opublikuj na
stronie” w oknie „Ogłoszenie” przepisuje treść ogłoszenia do opisu
publicznego i zatwierdza go tą samą drogą co okno „Udostępnij”
(``jpp.approve_profile``) — strona, tablica, plakat i grafika OG działają
bez zmian.

Mapowanie:

* podtytuł = wstęp ogłoszenia (jedno zdanie),
* opis = „O projekcie” + akapit z obowiązkami,
* tytuł strony ZOSTAJE tytułem publicznym rekrutacji: ogłoszenie i tak
  zaczyna od niego, a tytuł wchodzi do odcisku materiału — przepisanie go
  zapalałoby w oknie „Rekrutacja zmieniła się od przygotowania ogłoszenia”,
* „Wymagane” i „Mile widziane” = punkty ogłoszenia („Nasze wymagania”,
  „Mile widziane”) — od 29.10.2026, wcześniej słowa do szukania,
* miasto, tryb i start strona bierze z rekrutacji (migawka zatwierdzenia).

Reguły: ``docs/claude/rekrutacja-tworzenie/ogloszenie-jedna-tresc-strona-kariery.md``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job
from app.models.job_ad import JobAd
from app.models.job_public_profile import JobPublicProfile
from app.models.user import User
from app.services import career_board
from app.services import job_public_profile as jpp
from app.services.career_slugs import job_link_url
from app.services.job_ad.text import visible

STATUS_NONE = "none"
STATUS_LIVE = "live"
# Strona działa, ale pokazuje inną treść niż obecne ogłoszenie.
STATUS_OUTDATED = "outdated"

_DUTIES_HEADING = {"pl": "Czym się zajmiesz", "en": "What you will do"}


class NothingToPublish(ValueError):
    """Ogłoszenie nie ma ani wstępu, ani opisu projektu, ani obowiązków."""


@dataclass(frozen=True)
class CareerText:
    subtitle: Optional[str]
    about: Optional[str]


def _line(value: Any) -> str:
    return " ".join(visible(str(value or "")).split())


def career_text(content: dict[str, Any], lang: str) -> CareerText:
    """Podtytuł i opis strony kariery z treści ogłoszenia."""
    lead = _line(content.get("lead"))
    subtitle = jpp.trim_subtitle(lead, jpp.SUBTITLE_MAX) if lead else ""
    paragraphs = [
        _line(part)
        for part in re.split(r"\n\s*\n", visible(str(content.get("about") or "")))
        if part.strip()
    ]
    duties = [
        _line(item).rstrip(" .;,")
        for item in content.get("responsibilities") or []
        if _line(item)
    ]
    if duties:
        heading = _DUTIES_HEADING.get(lang, _DUTIES_HEADING["pl"])
        paragraphs.append(f"{heading}: {'; '.join(duties)}.")
    about = ""
    for paragraph in paragraphs:
        # Cały akapit albo nic — urwane zdanie na stronie wygląda jak błąd.
        candidate = f"{about}\n\n{paragraph}" if about else paragraph
        if len(candidate) > jpp.ABOUT_MAX:
            break
        about = candidate
    return CareerText(subtitle=subtitle or None, about=about or None)


@dataclass(frozen=True)
class CareerState:
    status: str
    url: Optional[str] = None
    published_at: Optional[datetime] = None
    published_by_name: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "url": self.url,
            "published_at": self.published_at,
            "published_by_name": self.published_by_name,
        }


def career_points(content: dict[str, Any]) -> Optional[dict[str, list[str]]]:
    """Punkty „Wymagane” i „Mile widziane” strony z treści ogłoszenia."""
    return jpp.requirement_points(
        [_line(item) for item in content.get("requirements") or []],
        [_line(item) for item in content.get("nice_to_have") or []],
    )


def _same_text(profile: JobPublicProfile, ad: JobAd) -> bool:
    text = career_text(ad.content, ad.lang)
    return (
        (profile.subtitle or None) == text.subtitle
        and (profile.about or None) == text.about
        and jpp.approved_points(profile.sections) == career_points(ad.content)
    )


async def career_state(
    db: AsyncSession, job: Job, ad: Optional[JobAd], *, user_id: int
) -> CareerState:
    """Czy strona kariery rekrutacji działa i czy pokazuje obecne ogłoszenie.

    Adres: własny aktywny link osoby (zgłoszenia liczą się jej), a bez niego
    link, pod którym rekrutacja stoi na tablicy.
    """
    profile = await db.get(JobPublicProfile, job.id)
    if profile is None or not jpp.job_is_open(job):
        return CareerState(status=STATUS_NONE)
    version = await jpp.published_version(db, job, profile)
    if version is None:
        return CareerState(status=STATUS_NONE)
    status = STATUS_LIVE
    if ad is not None:
        approved = not version.pending_changes
        if not approved or not _same_text(profile, ad):
            status = STATUS_OUTDATED
    own = await career_board.own_job_link(db, job, user_id)
    slug = (
        own.slug if own is not None else await career_board.canonical_job_slug(db, job)
    )
    published_by_name = (
        await db.scalar(select(User.name).where(User.id == profile.approved_by))
        if profile.approved_by
        else None
    )
    return CareerState(
        status=status,
        url=job_link_url(slug) if slug else None,
        published_at=profile.approved_at,
        published_by_name=published_by_name,
    )


async def publish(db: AsyncSession, job: Job, ad: JobAd, *, user_id: int) -> None:
    """Treść ogłoszenia → opis publiczny → zatwierdzenie → link osoby.

    ``NothingToPublish`` przy pustej treści, ``jpp.ProfileFindings`` przy
    znalezisku kontroli strony kariery (ta czyta też kody wewnętrzne,
    których kontrola ogłoszenia nie zna). Commit zostaje u wołającego.
    """
    text = career_text(ad.content, ad.lang)
    if not text.subtitle and not text.about:
        raise NothingToPublish()
    # `populate_existing`: ta sesja wczytała już opis bez blokady (stan okna),
    # a bez odświeżenia zatwierdzenie nadpisałoby przełączniki i tytuł,
    # które ktoś zapisał w oknie „Udostępnij” w międzyczasie.
    profile = await db.get(
        JobPublicProfile, job.id, with_for_update=True, populate_existing=True
    )
    if profile is None:
        profile = JobPublicProfile(job_id=job.id, sections=jpp.normalize_sections(None))
        db.add(profile)
    else:
        await jpp.keep_published_text(db, job, profile)
    profile.subtitle = text.subtitle
    profile.about = text.about
    await jpp.approve_profile(
        db, job, profile, user_id=user_id, points=career_points(ad.content)
    )
    await db.flush()
    _default, title = await jpp.public_titles(db, job, profile)
    await career_board.ensure_own_job_link(db, job, user_id, title)
