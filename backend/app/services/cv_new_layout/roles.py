"""Od strony 2: stanowiska jako tabele-formularze (okres, firma, stanowisko,
zakres zadań, technologie), potem pełne listy tego, co strona 1 skróciła."""

from __future__ import annotations

from app.services.cv_new_layout.context import Ctx, DatedRole
from app.services.cv_new_layout.education import education_full
from app.services.cv_new_layout.facts import CURRENT_WORD, duration_text
from app.services.cv_new_layout.page1 import skills_index
from app.services.cv_new_layout.text import clean, esc


def role_period(ctx: Ctx, r: DatedRole) -> str:
    """„08.2024 – 12.2025 (1 rok 5 mies.)”; rola bez początku = „obecnie”. Generator
    pisze „obecnie” także w CV po angielsku — tu słowo idzie za językiem CV."""
    if r.start is None:
        base = ctx.t["current"] if r.end is not None else r.role.dates
    else:
        base = CURRENT_WORD.sub(ctx.t["current"], r.role.dates.replace(" - ", " – "))
    length = duration_text(r.span, ctx.lang) if r.start is not None else ""
    return base + (f" ({length})" if length else "")


def role_table(ctx: Ctx, r: DatedRole) -> str:
    t, role = ctx.t, r.role
    rows = []
    period = role_period(ctx, r)
    if period:
        rows.append(
            f"<tr class='h'><th>{esc(t['period'])}</th><td>{esc(period)}</td></tr>"
        )
    if role.company:
        rows.append(
            f"<tr class='h'><th>{esc(t['company'])}</th><td><b>{esc(role.company)}</b></td></tr>"
        )
    if role.position:
        rows.append(
            f"<tr class='h'><th>{esc(t['position'])}</th><td><b>{esc(role.position)}</b></td></tr>"
        )
    duties = "".join(
        f"<li>{ctx.keys.bold(clean(d))}</li>" for d in role.responsibilities if clean(d)
    )
    if duties:  # puste pola znikają, zamiast stać jako pusty wiersz
        rows.append(f"<tr><th>{esc(t['tasks'])}</th><td><ul>{duties}</ul></td></tr>")
    if role.technologies:
        rows.append(
            f"<tr><th>{esc(t['technologies'])}</th><td>{ctx.keys.bold(', '.join(role.technologies))}</td></tr>"
        )
    return f"<table class='role'>{''.join(rows)}</table>" if rows else ""


def rest_pages(ctx: Ctx, skills_truncated: bool, certs_hidden: int) -> str:
    t = ctx.t
    out = ""
    if skills_truncated:
        out += f"<h2>{esc(t['skills_full'])}</h2><div class='skills-full'>{skills_index(ctx, None)[0]}</div>"
    roles = "".join(role_table(ctx, r) for r in ctx.roles)
    if roles:
        out += f"<h2>{esc(t['experience'])}</h2>{roles}"
    end = education_full(ctx, certs_hidden)
    if end:
        out += f"<h2>{esc(t['education_full'])}</h2>{end}"
    return out
