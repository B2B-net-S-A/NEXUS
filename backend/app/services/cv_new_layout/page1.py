"""Strona 1: stanowisko, imię i nazwisko, języki od B1 i miasto → wyróżnik (gdy jest) →
Dlaczego nasz kandydat → Przebieg kariery → Umiejętności → Edukacja. Mieści się zawsze
na jednej stronie (`fit.py`). Wieniec jest na stronie raz: z wyróżnikiem Edukacja idzie
bez wieńca (Artur 25.11.2026)."""

from __future__ import annotations

import re
from typing import Optional

from app.services.cv_new_layout.axis import career_axis
from app.services.cv_new_layout.context import Ctx
from app.services.cv_new_layout.education import education_page1, education_plain
from app.services.cv_new_layout.facts import lang_code, lang_level, lang_parts
from app.services.cv_new_layout.highlight import Highlight, resolve
from app.services.cv_new_layout.text import (
    esc,
    key_first,
    md_bold,
    merge_fragments,
    split_items,
)
from app.services.cv_new_layout.wreath import wreath_badge_svg


# Poziomy poniżej B1 nie trafiają na stronę 1 (Artur 23.11: „tylko B1 w górę”).
MIN_LEVEL = 3  # A1=1, A2=2, B1=3
_BASIC = ("podstaw", "basic", "elementar", "beginner", "początk")

# kolor wprost w atrybutach: WeasyPrint nie stosuje `currentColor` ani CSS do wnętrza SVG
PIN = (
    "<svg class='pin' viewBox='0 0 24 24'><g fill='none' stroke='#E73748' stroke-width='2.1' "
    "stroke-linejoin='round'><path d='M12 21.5s-6.8-6.3-6.8-11.4a6.8 6.8 0 0 1 13.6 0"
    "c0 5.1-6.8 11.4-6.8 11.4z'/><circle cx='12' cy='10' r='2.4'/></g></svg>"
)


_UNSPECIFIED = ("not specified", "unspecified", "nieokreślon", "nie określ")


def shown_language(level: str, lang: str) -> Optional[str]:
    """Etykieta poziomu albo None, gdy poziom jest poniżej B1 (słownie: „podstawowy”);
    „level not specified” = sam kod języka (przegląd 25.11.2026)."""
    if not level or any(w in level.lower() for w in _UNSPECIFIED):
        return ""
    degree, label = lang_level(level, lang)
    if degree is not None:
        return label if degree >= MIN_LEVEL else None
    return None if any(w in level.lower() for w in _BASIC) else label


def city(location: str) -> str:
    """„Warszawa, PL” → „Warszawa”; inny kraj zostaje kodem („Berlin, DE”)."""
    return re.sub(r",\s*PL$", "", (location or "").strip())


def title_row(ctx: Ctx) -> str:
    """Stanowisko, pod nim imię i nazwisko (bez myślnika); po prawej w jednym rzędzie
    języki od B1 i miasto kandydata. CV blind: samo stanowisko, bez miasta."""
    doc = ctx.doc
    pills = []
    for entry in doc.languages:
        name, level = lang_parts(entry)
        if not name:
            continue
        label = shown_language(level, ctx.lang)
        if label is None:
            continue
        pills.append(
            f"<span class='pill'><b>{esc(lang_code(name))}</b>{(' ' + esc(label)) if label else ''}</span>"
        )
    where = city(doc.location)
    if where and not doc.blind:
        pills.append(f"<span class='pill loc'>{PIN}{esc(where)}</span>")
    side = f"<div class='pills'>{''.join(pills)}</div>" if pills else ""
    name = "" if doc.blind or not doc.name else f"<div class='nm'>{esc(doc.name)}</div>"
    return (
        f"<div class='trow'><div class='tcol'><h1 class='title'>{esc(doc.position)}</h1>{name}</div>"
        f"{side}</div>"
    )


def highlight_block(hl: Optional[Highlight]) -> str:
    """Wyróżnik pod nazwiskiem: wieniec ze znakiem, etykieta (z latami) i jedno zdanie;
    bez ramki i tła (Artur 25.11.2026)."""
    if hl is None:
        return ""
    label = esc(hl.label) + (f" · {esc(hl.sub)}" if hl.sub else "")
    return (
        f"<div class='hl'>{wreath_badge_svg(hl.token)}"
        f"<div><div class='hlk'>{label}</div><div class='hlt'>{md_bold(hl.text)}</div></div></div>"
    )


def why_block(ctx: Ctx) -> str:
    """Trzy zdania bez kropek, oddzielone cienkimi paskami; `**…**` to pogrubienie."""
    items = "".join(f"<li>{md_bold(w)}</li>" for w in ctx.doc.why)
    return f"<ul class='why'>{items}</ul>" if items else ""


def skill_items(ctx: Ctx, content: str) -> list[str]:
    return key_first(merge_fragments(split_items(content)), ctx.keys)


def skills_index(ctx: Ctx, cap: Optional[int]) -> tuple[str, bool]:
    """Kategorie z pozycjami; pozycje z rekrutacji pogrubione i pierwsze, nadmiar jako „+N”.
    Zwraca (HTML, czy coś skrócono)."""
    rows, truncated = [], False
    for group in ctx.doc.skills:
        items = skill_items(ctx, group.content)
        if not items:
            continue
        shown = items[:cap] if cap else items
        more = len(items) - len(shown)
        truncated = truncated or more > 0
        spans = []
        for i, item in enumerate(shown):
            classes = (
                "it"
                + (" k" if ctx.keys.is_key(item) else "")
                + (" sep" if i < len(shown) - 1 else "")
            )
            spans.append(f"<span class='{classes}'>{esc(item)}</span>")
        tail = f"<span class='more'> +{more}</span>" if more else ""
        # znak o zerowej szerokości = miejsce łamania między pozycjami (same się nie łamią)
        rows.append(
            f"<div class='s1r'><div class='s1c'>{esc(group.label)}</div>"
            f"<div class='s1i'>{chr(0x200B).join(spans)}{tail}</div></div>"
        )
    if not rows:
        return "", False
    html = f"<div class='s1'>{''.join(rows)}</div>"
    if truncated:
        html += f"<div class='cap'>{esc(ctx.t['skills_more_note'])}</div>"
    return html, truncated


def heading(title: str) -> str:
    return f"<h2><span>{esc(title)}</span></h2>"


def page1(ctx: Ctx, cap: Optional[int]) -> tuple[str, bool, int]:
    """(HTML strony 1, czy umiejętności skrócono, ile certyfikatów na koniec CV)."""
    t = ctx.t
    skills, truncated = skills_index(ctx, cap)
    hl = resolve(ctx)
    education, certs_hidden = education_plain(ctx) if hl else education_page1(ctx)
    blocks = [
        (t["why_blind"] if ctx.doc.blind else t["why"], why_block(ctx)),
        (t["career"], career_axis(ctx)),
        (t["skills"], skills),
        (t["education"], education),
    ]
    body = (
        title_row(ctx)
        + highlight_block(hl)
        + "".join(
            f"<div class='blk'>{heading(title)}{content}</div>"
            for title, content in blocks
            if content
        )
    )
    return f"<div class='p1'>{body}</div>", truncated, certs_hidden
