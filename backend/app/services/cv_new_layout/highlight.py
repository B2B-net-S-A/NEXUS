"""Wyróżnik kandydata na stronie 1 (Artur 25.11.2026, wariant H4 bez ramki).

Jedna rzecz, która daje kandydatowi przewagę, pod imieniem i nazwiskiem: wieniec
laurowy ze znakiem (np. „PKO BP”, „2015”), etykieta i jedno zdanie. Wieniec jest
na stronie tylko raz, więc z wyróżnikiem Edukacja idzie bez wieńca.

Źródło (`page1_extras.highlight.mode`):
- „auto” (domyślne): kandydat pracował u klienta tej rekrutacji — firma ze
  stanowiska to klient (te same słowa po kolei w nazwie, nazwie wyświetlanej albo
  pełnej nazwie klienta). Zdanie z dat i stanowiska, bez dopowiadania. Brak
  takiej pracy albo CV anonimowe = bez wyróżnika.
- „ai” (26.11.2026): propozycja AI z CV (nagroda, wyróżnienie, certyfikat
  z MUST, `services/cv_page1_highlight.py`) — dopiero po przyjęciu przez
  rekrutera; propozycje same (`page1_extras.highlight_proposals`) render
  pomija. Przed renderem `cv_page1_highlight_checks.rechecked_highlight`
  sprawdza cytat na bieżącej treści.
- „custom”: etykieta, znak i zdanie wpisane przez rekrutera.
- „off”: bez wyróżnika.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Sequence

from app.services.cv_new_layout.axis import company_name
from app.services.cv_new_layout.context import Ctx
from app.services.cv_new_layout.document import HighlightChoice
from app.services.cv_new_layout.facts import Span, duration_text
from app.services.cv_new_layout.labels import counted

MODES = ("auto", "ai", "custom", "off")
LABEL_MAX, TOKEN_MAX, TEXT_MAX = 60, 8, 160
_LEGAL = re.compile(
    r"\b(s\.?\s*a|sp\.?\s*z\s*o\.?\s*o|spółka akcyjna|bank polski|polska|poland|group|grupa)\b\.?",
    re.I,
)


@dataclass(frozen=True)
class Highlight:
    label: str
    token: str
    text: str  # `**…**` = pogrubienie
    sub: str = ""  # np. lata pracy u klienta, dopisane do etykiety


def choice_from_extras(extras: Optional[dict]) -> HighlightChoice:
    raw = extras.get("highlight") if isinstance(extras, dict) else None
    if not isinstance(raw, dict) or raw.get("mode") not in MODES:
        return HighlightChoice()

    def field_(key: str, limit: int) -> str:
        return " ".join(str(raw.get(key) or "").split())[:limit]

    return HighlightChoice(
        raw["mode"],
        field_("label", LABEL_MAX),
        field_("token", TOKEN_MAX),
        field_("text", TEXT_MAX),
    )


def _words(name: str) -> list[str]:
    return re.findall(r"[0-9a-ząćęłńóśźż]+", _LEGAL.sub(" ", (name or "").lower()))


_GENERIC = {
    "bank",
    "it",
    "software",
    "solutions",
    "consulting",
    "services",
    "systems",
    "freelance",
    "freelancer",
}


def _contains(words: list[str], target: list[str]) -> bool:
    n = len(target)
    return any(words[i : i + n] == target for i in range(len(words) - n + 1))


def matches_client(company: str, client_names: Sequence[str]) -> bool:
    """Te same słowa po kolei w nazwie firmy i nazwie klienta, w jedną albo drugą
    stronę („PKO BP” ~ „PKO.BP”, „Orlen” ~ „PKN Orlen S.A.”, „Credit Agricole” ~
    „Credit Agricole Bank Polska S.A.”); „ING” nie trafia w „Ingenium”, a samo
    „Bank” czy „Software” w nic."""
    words = _words(company)
    if not words or set(words) <= _GENERIC:
        return False
    for name in client_names:
        target = _words(name)
        if not target or set(target) <= _GENERIC:
            continue
        if _contains(words, target) or _contains(target, words):
            return True
    return False


def short_client(client_names: Sequence[str]) -> str:
    """Najkrótsza nazwa klienta do etykiety i wieńca („PKO BP”, nie pełna nazwa)."""
    names = [n.strip() for n in client_names if n and n.strip()]
    return min(names, key=len) if names else ""


def client_highlight(ctx: Ctx, client_names: Sequence[str]) -> Optional[Highlight]:
    """Wcześniejsza (albo obecna) praca u klienta rekrutacji — z dat stanowisk."""
    if ctx.doc.blind or not client_names:
        return None
    roles = [
        r
        for r in ctx.roles
        if r.start is not None
        and r.end is not None
        and matches_client(company_name(r.role.company) or r.role.company, client_names)
    ]
    if not roles:
        return None
    start = min(r.start for r in roles)
    end = max(r.end for r in roles)
    exact = all(r.months_known for r in roles)
    current = any(ctx.is_current(r) for r in roles)
    t = ctx.t
    client = short_client(client_names)
    last = max(roles, key=lambda r: r.end)
    duration = duration_text(Span(start, end, exact), ctx.lang)
    end_label = (
        t["today"] if current else str(int(end + 0.001 - (1 / 24 if exact else 0)))
    )
    years = f"{int(start + 0.001)}–{end_label}"
    position = last.role.position.strip()
    template = (
        "highlight_client_text"
        if position and duration
        else "highlight_client_text_short"
    )
    text = t[template].format(
        duration=duration or years, position=position, client=client
    )
    return Highlight(
        label=t["highlight_client"].format(client=client),
        token=client if len(client) <= TOKEN_MAX else _tenure_token(end - start, ctx),
        text=text,
        sub=years,
    )


def _tenure_token(years: float, ctx: Ctx) -> str:
    """Znak w wieńcu, gdy nazwa klienta się nie mieści: pełne lata pracy u klienta
    („5 lat”), krócej niż rok — miesiące („8 mies.”)."""
    full = int(years + 1e-6)
    if full >= 1:
        return counted(ctx.lang, "year", full)
    return f"{max(round(years * 12), 1)} {ctx.t['months_short']}"


def resolve(ctx: Ctx) -> Optional[Highlight]:
    choice = ctx.doc.highlight
    if choice.mode == "off":
        return None
    if choice.mode in ("ai", "custom"):
        if not (choice.label and choice.text):
            return None
        return Highlight(choice.label, choice.token, choice.text)
    return client_highlight(ctx, ctx.doc.client_names)
