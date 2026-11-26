"""Link do ogłoszenia na Pracuj.pl z maila Pracuj.pl (26.11.2026).

Zgłoszenie DL-a: „za każdym razem trzeba ręcznie dodawać link do Pracuja?”.
Do 26.11 tak — link wklejał człowiek (decyzja z 27.10). Pracuj.pl po
wstawieniu ogłoszenia sam wysyła z ``extranet@pracuj.pl`` mail „Publikacja
ogłoszenia na <tytuł>” z publicznym linkiem ``www.pracuj.pl/praca?groupId=…``,
a ten mail i tak trafia do NEXUSA synchronizacją skrzynki DL-a (``emails``).
Pomiar 26.11: 59 takich maili, ``groupId`` z maila = ``groupId`` wklejony
potem ręcznie w każdym porównywalnym przypadku, mediana opóźnienia ręcznego
oznaczenia 50 h. Decyzja Artura 26.11.2026 (makiety
https://claude.ai/artifact/KoLmrJj6VdA6sD4jbdGdRw): wariant A.

* **Pewne dopasowanie oznacza samo.** Mail w skrzynce osoby, która z NEXUSA
  wysłała prośbę do opiekuna (``pracuj_mail.ACTION``) w ciągu
  ``REQUEST_WINDOW`` przed mailem, rekrutacja bez aktywnego oznaczenia
  Pracuj.pl i dokładnie jedna taka rekrutacja z tym samym tytułem
  (``title_key``) — wtedy ``mark_published`` z publicznym linkiem.
* **Niepewne to propozycja** w oknie „Ogłoszenie” („To ta rekrutacja” /
  „Nie”): kilka rekrutacji z tym samym tytułem, jedyna prośba z innym, ale
  podobnym tytułem, albo treść z blokującym znaleziskiem (takiej NEXUS nie
  potwierdza za człowieka).
* **„To nie to ogłoszenie”** zapisuje ``REJECTED`` dla pary rekrutacja–mail;
  ta para nie wraca ani jako oznaczenie, ani jako propozycja.

Ślad to wiersze Historii zdarzeń, bez nowej tabeli — jak prośba do opiekuna.
NEXUS nadal nie czyta korespondencji z opiekunem: bierze wyłącznie
automatyczny mail Pracuj.pl.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.job import Job
from app.models.job_ad import JobAd
from app.models.job_ad_publication import JobAdPublication
from app.models.m365 import Email, EmailDirection
from app.services.job_ad import pracuj_mail, publications
from app.services.job_ad_publication_schema import PORTAL_PRACUJ

SENDER = "extranet@pracuj.pl"
SUBJECT_PREFIX = "publikacja ogłoszenia na "
LINKED = "job_ad_pracuj_link_from_mail"
REJECTED = "job_ad_pracuj_mail_rejected"
# Opiekun wstawia ogłoszenie zwykle w 1–2 dni robocze; dwa tygodnie łapią
# też poprawkę po moderacji, a nie łączą maila z dawną prośbą.
REQUEST_WINDOW = timedelta(days=14)
# Pętla przegląda maile z tylu dni — pierwszy przebieg łapie zaległe.
SCAN_WINDOW = timedelta(days=21)
# Podobieństwo tytułów (wspólne słowa), przy którym jedyna prośba osoby
# staje się propozycją.
_SIMILAR_MIN = 0.5

_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_GROUP_ID = re.compile(r"groupId=(" + _UUID + r")(?![0-9a-fA-F-])")
# „(k/m/x)”, „(f/m/x)”, „(K/M/N)”, „(m/k)” — dopisek płci na portalu.
_GENDER = re.compile(r"\(\s*[a-z]{1,2}(?:\s*/\s*[a-z]{1,2})+\s*\)")
# „Tester Manualny x4” — liczba wakatów dopisana w NEXUSIE.
_HEADCOUNT = re.compile(r"\s+x\s?\d+\s*$")
_DASHES = re.compile(r"[‐‑‒–—―]")
_SEPARATORS = re.compile(r"\s*([/-])\s*")
_WORD = re.compile(r"[^\W_]{3,}")


def public_url(group_id: str) -> str:
    return publications.pracuj_public_url(group_id)


def group_id(body_html: Optional[str]) -> Optional[str]:
    """Identyfikator ogłoszenia z linku w treści maila; dwa różne = żaden."""
    found = {m.lower() for m in _GROUP_ID.findall(body_html or "")}
    return found.pop() if len(found) == 1 else None


def mail_title(subject: Optional[str]) -> Optional[str]:
    text = (subject or "").strip()
    if not text.lower().startswith(SUBJECT_PREFIX):
        return None
    return text[len(SUBJECT_PREFIX) :].strip() or None


def title_key(title: Optional[str]) -> str:
    """Tytuł do porównania: bez dopisku płci, liczby wakatów, rodzaju myślnika
    i spacji przy „/” albo „-”."""
    text = unicodedata.normalize("NFKC", title or "").lower()
    text = _GENDER.sub(" ", text)
    text = _HEADCOUNT.sub("", text)
    text = _DASHES.sub("-", text)
    text = _SEPARATORS.sub(r"\1", text)
    return " ".join(text.split()).strip(" .,;:")


def _similarity(a: str, b: str) -> float:
    left, right = set(_WORD.findall(a)), set(_WORD.findall(b))
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


@dataclass(frozen=True)
class PracujMail:
    email_id: int
    user_id: int
    subject: str
    title: str
    received_at: datetime
    url: str


@dataclass(frozen=True)
class Candidate:
    job_id: int
    titles: tuple[str, ...]


@dataclass(frozen=True)
class Match:
    """``auto`` = oznacz bez pytania; ``suggested`` = zapytaj DL-a."""

    auto: Optional[int]
    suggested: tuple[int, ...]


def decide(mail_title_text: str, candidates: Iterable[Candidate]) -> Match:
    """Reguła dopasowania — czysta funkcja, testowana bez bazy."""
    pool = list(candidates)
    key = title_key(mail_title_text)
    exact = [c.job_id for c in pool if key and key in {title_key(t) for t in c.titles}]
    if len(exact) == 1:
        return Match(auto=exact[0], suggested=())
    if exact:
        return Match(auto=None, suggested=tuple(exact))
    if len(pool) == 1 and any(
        _similarity(key, title_key(t)) >= _SIMILAR_MIN for t in pool[0].titles
    ):
        return Match(auto=None, suggested=(pool[0].job_id,))
    return Match(auto=None, suggested=())


def _mail(row: Email) -> Optional[PracujMail]:
    title = mail_title(row.subject)
    gid = group_id(row.body_html)
    if title is None or gid is None or row.user_id is None:
        return None
    return PracujMail(
        email_id=row.id,
        user_id=row.user_id,
        subject=row.subject or "",
        title=title,
        received_at=row.received_at,
        url=public_url(gid),
    )


def _mail_filter():
    return (
        Email.from_address == SENDER,
        Email.direction == EmailDirection.received,
        Email.is_private_filtered.is_(False),
        func.lower(Email.subject).like(SUBJECT_PREFIX + "%"),
    )


async def recent_mails(
    db: AsyncSession, *, now: datetime, user_ids: Optional[Iterable[int]] = None
) -> list[PracujMail]:
    stmt = select(Email).where(*_mail_filter(), Email.received_at >= now - SCAN_WINDOW)
    if user_ids is not None:
        stmt = stmt.where(Email.user_id.in_(list(set(user_ids))))
    rows = await db.scalars(stmt.order_by(Email.received_at, Email.id))
    return [mail for row in rows if (mail := _mail(row)) is not None]


async def mail_by_id(db: AsyncSession, email_id: int) -> Optional[PracujMail]:
    row = await db.scalar(select(Email).where(Email.id == email_id, *_mail_filter()))
    return _mail(row) if row is not None else None


async def _rejected_pairs(
    db: AsyncSession, email_ids: list[int]
) -> set[tuple[int, int]]:
    if not email_ids:
        return set()
    rows = await db.execute(
        select(Activity.entity_id, Activity.details["email_id"].astext).where(
            Activity.entity_type == "job",
            Activity.action == REJECTED,
            Activity.details["email_id"].astext.in_([str(i) for i in email_ids]),
        )
    )
    return {(job_id, int(email_id)) for job_id, email_id in rows if email_id}


async def _used_urls(db: AsyncSession, urls: list[str]) -> set[str]:
    if not urls:
        return set()
    rows = await db.scalars(
        select(JobAdPublication.url).where(
            JobAdPublication.portal == PORTAL_PRACUJ,
            JobAdPublication.removed_at.is_(None),
            JobAdPublication.url.in_(urls),
        )
    )
    return set(rows)


async def candidates_for(db: AsyncSession, mail: PracujMail) -> list[Candidate]:
    """Rekrutacje z prośbą tej osoby przed mailem i bez oznaczenia Pracuj.pl."""
    requested = (
        select(Activity.entity_id)
        .where(
            Activity.entity_type == "job",
            Activity.action == pracuj_mail.ACTION,
            Activity.user_id == mail.user_id,
            Activity.created_at <= mail.received_at,
            Activity.created_at >= mail.received_at - REQUEST_WINDOW,
        )
        .distinct()
        .subquery()
    )
    active = select(JobAdPublication.job_id).where(
        JobAdPublication.portal == PORTAL_PRACUJ,
        JobAdPublication.removed_at.is_(None),
    )
    rows = await db.execute(
        select(Job.id, Job.title, JobAd.content)
        .join(requested, requested.c.entity_id == Job.id)
        .join(JobAd, JobAd.job_id == Job.id)
        .where(Job.id.not_in(active))
    )
    return [
        Candidate(
            job_id=job_id,
            titles=tuple(
                t
                for t in (title, (content or {}).get("title"))
                if isinstance(t, str) and t.strip()
            ),
        )
        for job_id, title, content in rows
    ]


@dataclass(frozen=True)
class Planned:
    mail: PracujMail
    match: Match


async def plan(db: AsyncSession, mails: list[PracujMail]) -> list[Planned]:
    """Dopasowania maili po odjęciu odrzuconych par i linków już w użyciu."""
    rejected = await _rejected_pairs(db, [m.email_id for m in mails])
    used = await _used_urls(db, [m.url for m in mails])
    out: list[Planned] = []
    for mail in mails:
        if mail.url in used:
            continue
        pool = [
            c
            for c in await candidates_for(db, mail)
            if (c.job_id, mail.email_id) not in rejected
        ]
        match = decide(mail.title, pool)
        if match.auto is not None or match.suggested:
            out.append(Planned(mail=mail, match=match))
    return out


async def suggestions_for_job(
    db: AsyncSession, job_id: int, *, now: Optional[datetime] = None
) -> list[PracujMail]:
    """Maile Pracuj.pl, o które okno pyta DL-a przy tej rekrutacji."""
    request = (await pracuj_mail.last_requests(db, [job_id])).get(job_id)
    if request is None or request.sent_by is None:
        return []
    mails = await recent_mails(
        db, now=now or datetime.now(timezone.utc), user_ids=[request.sent_by]
    )
    return [
        p.mail
        for p in await plan(db, mails)
        if job_id in p.match.suggested or p.match.auto == job_id
    ]


def log_linked(
    db: AsyncSession,
    job_id: int,
    mail: PracujMail,
    *,
    user_id: Optional[int],
    mode: str,
) -> None:
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action=LINKED,
            user_id=user_id,
            details={
                "email_id": mail.email_id,
                "url": mail.url,
                "subject": mail.subject,
                "received_at": mail.received_at.isoformat(),
                "mode": mode,
            },
        )
    )


def log_rejected(db: AsyncSession, job_id: int, email_id: int, user_id: int) -> None:
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action=REJECTED,
            user_id=user_id,
            details={"email_id": email_id},
        )
    )


async def link_auto(db: AsyncSession, job_id: int, mail: PracujMail) -> bool:
    """Pewne dopasowanie: oznacz Pracuj.pl z linkiem z maila.

    Treść z blokującym znaleziskiem zostaje propozycją — potwierdzenie takiej
    treści i tak kończy się odmową, a decyzja należy do człowieka.
    """
    from app.services.job_ad import lint, portal_content

    job = await db.get(Job, job_id)
    ad = await db.get(JobAd, job_id)
    if job is None or ad is None:
        return False
    row = await db.get(
        JobAdPublication,
        (job_id, PORTAL_PRACUJ),
        with_for_update=True,
        populate_existing=True,
    )
    if row is not None and row.removed_at is None:
        # DL oznaczył ręcznie między planem a zapisem — jego link wygrywa.
        return False
    mat = await portal_content.ad_material(db, job)
    _, findings = await portal_content.checked_render(db, job, ad, mat)
    if lint.has_blocking(findings):
        return False
    await publications.mark_published(
        db, ad, portal=PORTAL_PRACUJ, url=mail.url, user_id=mail.user_id
    )
    log_linked(db, job_id, mail, user_id=mail.user_id, mode="auto")
    return True


@dataclass(frozen=True)
class LinkedFrom:
    email_id: int
    subject: str
    received_at: Optional[str]


async def linked_from(
    db: AsyncSession, job_id: int, url: Optional[str]
) -> Optional[LinkedFrom]:
    """Mail, z którego pochodzi obecny link (najnowszy wpis z tym adresem)."""
    if not url:
        return None
    activity = await db.scalar(
        select(Activity)
        .where(
            Activity.entity_type == "job",
            Activity.entity_id == job_id,
            Activity.action == LINKED,
            Activity.details["url"].astext == url,
        )
        .order_by(Activity.id.desc())
        .limit(1)
    )
    if activity is None:
        return None
    details = activity.details or {}
    return LinkedFrom(
        email_id=int(details.get("email_id") or 0),
        subject=str(details.get("subject") or ""),
        received_at=details.get("received_at"),
    )


__all__ = [
    "Candidate",
    "LINKED",
    "LinkedFrom",
    "Match",
    "PracujMail",
    "REJECTED",
    "SENDER",
    "decide",
    "group_id",
    "link_auto",
    "linked_from",
    "log_linked",
    "log_rejected",
    "mail_by_id",
    "mail_title",
    "plan",
    "public_url",
    "recent_mails",
    "suggestions_for_job",
    "title_key",
]
