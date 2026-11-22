"""Strona 1: tytuł z językami → Dlaczego nasz kandydat → Przebieg kariery →
Umiejętności → Edukacja. Mieści się zawsze na jednej stronie (`fit.py`)."""

from __future__ import annotations

from typing import Optional

from app.services.cv_new_layout.axis import career_axis
from app.services.cv_new_layout.context import Ctx
from app.services.cv_new_layout.education import education_page1
from app.services.cv_new_layout.facts import lang_code, lang_level, lang_parts
from app.services.cv_new_layout.text import (
    esc,
    key_first,
    md_bold,
    merge_fragments,
    split_items,
)


def title_row(ctx: Ctx) -> str:
    """„Stanowisko – Imię Nazwisko” i pastylki języków („PL ojczysty”, „EN C1/C2”).
    CV blind: samo stanowisko, jak w pliku Word."""
    doc = ctx.doc
    pills = []
    for entry in doc.languages:
        name, level = lang_parts(entry)
        if not name:
            continue
        _, label = lang_level(level, ctx.lang) if level else (None, "")
        pills.append(
            f"<span class='pill'><b>{esc(lang_code(name))}</b>{(' ' + esc(label)) if label else ''}</span>"
        )
    side = f"<div class='pills'>{''.join(pills)}</div>" if pills else ""
    name = (
        ""
        if doc.blind or not doc.name
        else f" – <span class='nm'>{esc(doc.name)}</span>"
    )
    return f"<div class='trow'><div class='tcol'><h1 class='title'>{esc(doc.position)}{name}</h1></div>{side}</div>"


def why_block(ctx: Ctx) -> str:
    """Trzy zdania; `**…**` z generatora to pogrubienie (bez większego kroju)."""
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
    education, certs_hidden = education_page1(ctx)
    blocks = [
        (t["why_blind"] if ctx.doc.blind else t["why"], why_block(ctx)),
        (t["career"], career_axis(ctx)),
        (t["skills"], skills),
        (t["education"], education),
    ]
    body = title_row(ctx) + "".join(
        f"<div class='blk'>{heading(title)}{content}</div>"
        for title, content in blocks
        if content
    )
    return f"<div class='p1'>{body}</div>", truncated, certs_hidden
