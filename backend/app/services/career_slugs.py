"""Slugi i adresy linków strony kariery (kariera.dynaminds.pl).

Dwa rodzaje adresów:

* link rekrutacji — ``/r/<slug>``, slug = tytuł rekrutacji po transliteracji
  + ``-`` + 4 losowe znaki (``senior-java-developer-7kq2``). Losowy sufiks
  sprawia, że dwie rekrutacje o tym samym tytule nie kolidują i że adresu nie
  da się zgadnąć z samego tytułu;
* stały link rekrutera — ``/<slug>``, slug wybiera rekruter (walidacja
  i słowa zastrzeżone niżej — ``r``, ``rodo`` itd. to ścieżki samej strony).
"""

from __future__ import annotations

import re
import secrets
import string
import unicodedata

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.invite_link import CandidateInviteLink

_TRANSLITERATION = str.maketrans(
    {"ł": "l", "Ł": "L", "ß": "ss", "æ": "ae", "Æ": "AE", "ø": "o", "Ø": "O"}
)
_NON_SLUG = re.compile(r"[^a-z0-9]+")
_SUFFIX_ALPHABET = string.ascii_lowercase + string.digits

RECRUITER_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,38})[a-z0-9]$")
RECRUITER_SLUG_MIN = 3
RECRUITER_SLUG_MAX = 40
# Pierwszy segment ścieżki na domenie kariery, który NIE może być slugiem
# rekrutera: ścieżki samej strony, zasoby Next.js i nazwy mylące kandydata.
RESERVED_RECRUITER_SLUGS = frozenset(
    {
        "r",
        "p",
        "rodo",
        "api",
        "_next",
        "kariera",
        "admin",
        "login",
        "logout",
        "apply",
        "static",
        "public",
        "assets",
        "favicon",
        "favicon-ico",
        "robots",
        "robots-txt",
        "sitemap",
        "sitemap-xml",
        "opengraph-image",
        "twitter-image",
        "health",
        "www",
        "app",
        "nexus",
        "dynaminds",
        "b2b",
        "b2bnet",
        "kontakt",
        "privacy",
        "polityka-prywatnosci",
        "regulamin",
        "preview",
        "settings",
        "dashboard",
    }
)

_JOB_SLUG_BASE_MAX = 48


def slugify(value: str | None) -> str:
    """ASCII, małe litery, myślniki; polskie znaki bez ogonków."""
    text = (value or "").translate(_TRANSLITERATION)
    ascii_only = (
        unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    )
    return _NON_SLUG.sub("-", ascii_only.lower()).strip("-")


def random_suffix(length: int = 4) -> str:
    return "".join(secrets.choice(_SUFFIX_ALPHABET) for _ in range(length))


def job_slug_base(title: str | None) -> str:
    base = slugify(title)[:_JOB_SLUG_BASE_MAX].strip("-")
    return base or "rekrutacja"


async def generate_job_slug(db: AsyncSession, title: str | None) -> str:
    """Slug linku rekrutacji, unikalny w tabeli linków."""
    base = job_slug_base(title)
    for _ in range(12):
        candidate = f"{base}-{random_suffix()}"
        taken = await db.scalar(
            select(CandidateInviteLink.token).where(
                CandidateInviteLink.slug == candidate
            )
        )
        if taken is None:
            return candidate
    # 36^4 kombinacji na bazę — dwanaście kolizji z rzędu to sygnał, że coś
    # jest nie tak; dłuższy sufiks i tak kończy sprawę.
    return f"{base}-{random_suffix(8)}"


def recruiter_slug_problem(slug: str | None) -> str | None:
    """Powód, dla którego slug stałego linku jest niepoprawny, albo ``None``."""
    value = (slug or "").strip()
    if len(value) < RECRUITER_SLUG_MIN:
        return f"Adres musi mieć co najmniej {RECRUITER_SLUG_MIN} znaki."
    if len(value) > RECRUITER_SLUG_MAX:
        return f"Adres może mieć najwyżej {RECRUITER_SLUG_MAX} znaków."
    if not RECRUITER_SLUG_RE.match(value):
        return (
            "Dozwolone są małe litery bez polskich znaków, cyfry i myślnik "
            "(nie na początku ani na końcu)."
        )
    if "--" in value:
        return "Adres nie może zawierać dwóch myślników z rzędu."
    if value in RESERVED_RECRUITER_SLUGS:
        return "Ten adres jest zarezerwowany dla strony kariery."
    return None


def suggest_recruiter_slug(name: str | None) -> str:
    """„Marta Nowak" → ``marta-n``."""
    parts = [p for p in slugify(name).split("-") if p]
    if not parts:
        return "rekruter"
    slug = parts[0] if len(parts) == 1 else f"{parts[0]}-{parts[-1][0]}"
    if len(slug) < RECRUITER_SLUG_MIN or slug in RESERVED_RECRUITER_SLUGS:
        slug = f"{slug}-rekruter" if slug else "rekruter"
    return slug[:RECRUITER_SLUG_MAX].strip("-")


def career_base_url() -> str:
    """Adres strony kariery.

    Bez osobnej domeny (``CAREER_PUBLIC_BASE_URL`` puste) strona żyje pod
    ``/kariera`` na hoście aplikacji — to tam middleware ją przepuszcza. Sam
    ``PUBLIC_BASE_URL`` dawałby ``/r/<slug>`` na hoście aplikacji, czyli adres,
    którego nic nie obsługuje.
    """
    base = (settings.CAREER_PUBLIC_BASE_URL or "").strip()
    if base:
        return base.rstrip("/")
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/kariera"


def job_link_url(slug: str) -> str:
    return f"{career_base_url()}/r/{slug}"


def recruiter_link_url(slug: str) -> str:
    return f"{career_base_url()}/{slug}"


def first_name(full_name: str | None) -> str:
    """Tylko imię — nazwisko rekrutera nie trafia na stronę publiczną."""
    return (full_name or "").strip().split(" ", 1)[0]
