"""Stałe części ogłoszenia — wpisywane raz w Ustawieniach.

„Co oferujemy”, etapy procesu, zdanie o firmie i dopisek do tytułu trafiają
do każdego ogłoszenia w tym samym brzmieniu; rekruter ich nie przepisuje.
Pomiar 12.10.2026: „co oferujemy” miały 4 z 50 naszych ogłoszeń na
JustJoin.IT, etapów procesu żadne, a tytuły sześć różnych dopisków.

Magazyn: ``app_settings['job_ad_fixed_blocks']``. Wzór:
``request_allocation_rules`` (odczyt łagodny, zapis ścisły).

Od 27.10.2026 tu stoi też opiekun konta Pracuj.pl (imię do powitania i adres):
Pracuj.pl nie ma u nas API, ogłoszenie wstawia opiekun po mailu od Delivery
Leada (``job_ad.pracuj_mail``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.services.job_ad_schema import LANG_EN, LANG_PL

BLOCKS_KEY = "job_ad_fixed_blocks"

SUFFIX_KMX = "kmx"
SUFFIX_KM = "km"
SUFFIX_NONE = "none"
TITLE_SUFFIXES = (SUFFIX_KMX, SUFFIX_KM, SUFFIX_NONE)

OFFER_MAX_ITEMS = 8
PROCESS_MAX_ITEMS = 6
ITEM_MAX_CHARS = 200
ABOUT_MAX_CHARS = 600
CARETAKER_NAME_MAX = 60
CARETAKER_EMAIL_MAX = 254
# Adres skrzynki ogłoszeń Pracuj.pl — działa, zanim HoR wpisze opiekuna.
CARETAKER_DEFAULT_EMAIL = "ogloszenia@pracuj.pl"
_EMAIL = re.compile(r"^[^@\s<>\"',;]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")


@dataclass(frozen=True)
class LangBlocks:
    offer: tuple[str, ...]
    process: tuple[str, ...]
    about: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "offer": list(self.offer),
            "process": list(self.process),
            "about": self.about,
        }


@dataclass(frozen=True)
class PracujCaretaker:
    """Opiekun konta Pracuj.pl: imię do powitania (może być puste) i adres."""

    name: str = ""
    email: str = CARETAKER_DEFAULT_EMAIL

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "email": self.email}


@dataclass(frozen=True)
class FixedBlocks:
    title_suffix: str
    pl: LangBlocks
    en: LangBlocks
    pracuj_caretaker: PracujCaretaker = field(default_factory=PracujCaretaker)

    def for_lang(self, lang: str) -> LangBlocks:
        return self.en if lang == LANG_EN else self.pl

    def as_dict(self) -> dict[str, Any]:
        return {
            "title_suffix": self.title_suffix,
            LANG_PL: self.pl.as_dict(),
            LANG_EN: self.en.as_dict(),
            "pracuj_caretaker": self.pracuj_caretaker.as_dict(),
        }


# Punkty startowe pochodzą z publicznych profili firmy na portalach
# (stan 12.10.2026) — do zmiany w Ustawienia → Rekrutacja.
DEFAULTS = FixedBlocks(
    title_suffix=SUFFIX_KMX,
    pl=LangBlocks(
        offer=(
            "prywatna opieka medyczna",
            "dofinansowanie zajęć sportowych",
            "wsparcie formalne od dokumentów po onboarding",
        ),
        process=(
            "Rozmowa z rekruterem",
            "Rozmowa techniczna",
            "Rozmowa z klientem",
        ),
        about=(
            "B2B Network łączy specjalistów IT z projektami, które do nich "
            "pasują. To Ty wybierasz projekt, my zapewniamy stabilne warunki "
            "i wsparcie."
        ),
    ),
    en=LangBlocks(
        offer=(
            "private medical care",
            "sports card co-financing",
            "formal support from paperwork to onboarding",
        ),
        process=(
            "Interview with a recruiter",
            "Technical interview",
            "Interview with the client",
        ),
        about=(
            "B2B Network connects IT specialists with projects that suit them. "
            "You choose the project, we provide stable terms and support."
        ),
    ),
)


def _lines(value: Any, limit: int) -> Optional[tuple[str, ...]]:
    if not isinstance(value, (list, tuple)):
        return None
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            return None
        text = " ".join(item.split())
        if text:
            out.append(text)
    return tuple(out) if len(out) <= limit else None


def _parse_lang(value: Any, default: LangBlocks) -> LangBlocks:
    data = value if isinstance(value, dict) else {}
    offer = _lines(data.get("offer"), OFFER_MAX_ITEMS)
    process = _lines(data.get("process"), PROCESS_MAX_ITEMS)
    about = data.get("about")
    return LangBlocks(
        offer=default.offer if offer is None else offer,
        process=default.process if process is None else process,
        about=(
            " ".join(about.split())[:ABOUT_MAX_CHARS]
            if isinstance(about, str)
            else default.about
        ),
    )


def _parse_caretaker(value: Any) -> PracujCaretaker:
    data = value if isinstance(value, dict) else {}
    try:
        return validate_caretaker(data)
    except ValueError:
        return PracujCaretaker()


def parse_blocks(value: Optional[dict[str, Any]]) -> FixedBlocks:
    """Odczyt łagodny — zepsuta wartość w bazie daje domyślną, nie 500."""
    data = value if isinstance(value, dict) else {}
    suffix = data.get("title_suffix")
    return FixedBlocks(
        title_suffix=suffix if suffix in TITLE_SUFFIXES else DEFAULTS.title_suffix,
        pl=_parse_lang(data.get(LANG_PL), DEFAULTS.pl),
        en=_parse_lang(data.get(LANG_EN), DEFAULTS.en),
        pracuj_caretaker=_parse_caretaker(data.get("pracuj_caretaker")),
    )


def validate_caretaker(value: dict[str, Any]) -> PracujCaretaker:
    """Imię bez znaków nowej linii (trafia do pierwszej linii maila), adres jeden."""
    name = value.get("name") or ""
    email = value.get("email") or ""
    if not isinstance(name, str) or not isinstance(email, str):
        raise ValueError("Opiekun Pracuj.pl: imię i adres muszą być tekstem.")
    name = " ".join(name.split())
    email = email.strip()
    if len(name) > CARETAKER_NAME_MAX:
        raise ValueError(
            f"Imię opiekuna Pracuj.pl: najwyżej {CARETAKER_NAME_MAX} znaków."
        )
    if len(email) > CARETAKER_EMAIL_MAX or not _EMAIL.match(email):
        raise ValueError("Wpisz jeden poprawny adres e-mail opiekuna Pracuj.pl.")
    return PracujCaretaker(name=name, email=email)


def _validate_lang(value: Any, label: str) -> LangBlocks:
    if not isinstance(value, dict):
        raise ValueError(f"Brakuje bloków w języku: {label}.")
    offer = _lines(value.get("offer"), OFFER_MAX_ITEMS)
    if offer is None:
        raise ValueError(
            f"„Co oferujemy” ({label}): najwyżej {OFFER_MAX_ITEMS} punktów tekstu."
        )
    process = _lines(value.get("process"), PROCESS_MAX_ITEMS)
    if process is None:
        raise ValueError(
            f"„Jak wygląda proces” ({label}): najwyżej {PROCESS_MAX_ITEMS} etapów."
        )
    too_long = next((i for i in (*offer, *process) if len(i) > ITEM_MAX_CHARS), None)
    if too_long is not None:
        raise ValueError(
            f"Punkt jest za długi (najwyżej {ITEM_MAX_CHARS} znaków): „{too_long[:40]}…”."
        )
    about = value.get("about")
    if not isinstance(about, str):
        raise ValueError(f"Zdanie o firmie ({label}) musi być tekstem.")
    about = " ".join(about.split())
    if len(about) > ABOUT_MAX_CHARS:
        raise ValueError(
            f"Zdanie o firmie ({label}): najwyżej {ABOUT_MAX_CHARS} znaków."
        )
    return LangBlocks(offer=offer, process=process, about=about)


def validate_blocks(
    value: dict[str, Any], *, keep_caretaker: Optional[PracujCaretaker] = None
) -> FixedBlocks:
    """Zapis ścisły — błąd po polsku zamiast cichej wartości domyślnej.

    Bez ``pracuj_caretaker`` w danych zostaje ``keep_caretaker`` (zapisany
    wcześniej): okno sprzed 27.10.2026 nie zna tego pola i zapisem „co
    oferujemy” zerowałoby opiekuna.
    """
    suffix = value.get("title_suffix")
    if suffix not in TITLE_SUFFIXES:
        raise ValueError("Nieznany dopisek do tytułu.")
    caretaker = value.get("pracuj_caretaker")
    return FixedBlocks(
        title_suffix=suffix,
        pl=_validate_lang(value.get(LANG_PL), "polski"),
        en=_validate_lang(value.get(LANG_EN), "angielski"),
        pracuj_caretaker=(
            validate_caretaker(caretaker)
            if isinstance(caretaker, dict)
            else keep_caretaker or PracujCaretaker()
        ),
    )


async def load_blocks(db: AsyncSession) -> FixedBlocks:
    row = await db.scalar(select(AppSetting).where(AppSetting.key == BLOCKS_KEY))
    return parse_blocks(row.value if row else None)


async def save_blocks(
    db: AsyncSession, blocks: FixedBlocks, *, user_id: Optional[int]
) -> FixedBlocks:
    row = await db.scalar(
        select(AppSetting).where(AppSetting.key == BLOCKS_KEY).with_for_update()
    )
    if row is None:
        db.add(AppSetting(key=BLOCKS_KEY, value=blocks.as_dict(), updated_by=user_id))
    else:
        row.value = blocks.as_dict()
        row.updated_by = user_id
    await db.flush()
    return blocks
