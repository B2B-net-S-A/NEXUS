"""„Edukacja”: najwyższy dyplom w wieńcu, 3 najważniejsze certyfikaty (rok + nazwa),
reszta w pełnych listach na końcu CV (Artur 20.11.2026: EH1, CE1, MC2)."""

from __future__ import annotations

from typing import Optional, Sequence

from app.services.cv_new_layout.context import Ctx
from app.services.cv_new_layout.document import School
from app.services.cv_new_layout.facts import (
    Cert,
    certs_by_year,
    edu_rank,
    last_year,
    split_degree,
)
from app.services.cv_new_layout.labels import more_at_end
from app.services.cv_new_layout.text import esc
from app.services.cv_new_layout.wreath import wreath_svg

CERTS_ON_PAGE_1 = 3

# dziedzina roli → słowa w roli/wymaganiach i słowa w nazwie certyfikatu
CERT_DOMAINS = {
    "pm": (
        ("projekt", "project", "kierownik", "manager", "delivery", "pmo"),
        ("pmp", "prince2", "ipma", "pmi", "capm"),
    ),
    "agile": (
        ("scrum", "agile", "safe", "kanban", "product owner"),
        ("psm", "pspo", "csm", "safe", "scrum", "agile", "kanban"),
    ),
    "test": (
        ("test", "qa", "quality", "jakoś"),
        ("istqb", "selenium", "testing", "tester", "test"),
    ),
    "ms": (
        ("power platform", "azure", "microsoft", "dynamics", "power apps", ".net"),
        ("microsoft", "azure", "power platform", "pl-", "az-", "ai-900"),
    ),
    "cloud": (
        ("aws", "cloud", "devops", "chmur", "kubernetes"),
        ("aws", "gcp", "google cloud", "kubernetes", "cka", "terraform"),
    ),
    "analysis": (
        ("analityk", "analyst", "analiz", "bpmn", "uml", "wymagań"),
        ("iiba", "cbap", "ccba", "ireb", "bpmn", "uml"),
    ),
    "rpa": (("rpa", "blue prism", "uipath"), ("blue prism", "uipath", "rpa")),
    "itsm": (("itil", "service desk"), ("itil",)),
    "data": (
        ("data", "dane", "spark", "bi ", "machine learning", "ml"),
        ("data", "machine learning", "databricks", "snowflake", "tableau", "power bi"),
    ),
    "ux": (
        ("ux", "ui/ux", "user experience", "product design"),
        (
            "ux",
            "user experience",
            "usability",
            "wcag",
            "dostępnoś",
            "interaction design",
            "design thinking",
        ),
    ),
}


def highest_school(schools: Sequence[School]) -> Optional[School]:
    """Najwyższy stopień; przerwane studia się nie liczą; remis = kolejność z CV."""
    return (
        max(schools, key=lambda s: edu_rank(s.degree, s.institution))
        if schools
        else None
    )


def top_certs(ctx: Ctx, certs: Sequence[Cert], n: int) -> list[Cert]:
    """Najważniejsze dla roli: dziedzina zgodna z nazwą roli lub słowami rekrutacji (6),
    z umiejętnościami w CV (4), słowo kluczowe w nazwie (3), słowo z nazwy roli (1);
    remis — nowszy, potem kolejność z CV."""
    doc = ctx.doc
    short_keys = [k for k in doc.highlight_keywords if len(k.split()) <= 2]
    head = f" {doc.position} {' '.join(short_keys)} ".lower()
    skills = " ".join(f"{g.label} {g.content}" for g in doc.skills).lower()
    pos_words = [
        w for w in doc.position.lower().replace("/", " ").split() if len(w) >= 4
    ]

    def score(c: Cert) -> int:
        name = f" {c.name} {c.issuer} ".lower()
        sc = 0
        for role_words, cert_words in CERT_DOMAINS.values():
            if any(w in name for w in cert_words):
                if any(w in head for w in role_words):
                    sc += 6
                elif any(w in skills for w in role_words):
                    sc += 4
        sc += 3 * sum(1 for k in short_keys if len(k) > 2 and k.lower() in name)
        sc += sum(1 for w in pos_words if w in name)
        return sc

    order = {id(c): i for i, c in enumerate(certs)}
    return sorted(
        certs, key=lambda c: (-score(c), -(int(c.year) if c.year else 0), order[id(c)])
    )[:n]


def cert_table(ctx: Ctx, rows: Sequence[Cert]) -> str:
    if not rows:
        return ""
    has_year = any(r.year for r in rows)
    head = (
        f"<span>{esc(ctx.t['year'])}</span>" if has_year else ""
    ) + f"<span>{esc(ctx.t['certificate'])}</span>"
    body = "".join(
        "<div class='cer'>"
        + (f"<span class='cey'>{esc(r.year)}</span>" if has_year else "")
        + f"<span>{esc(r.name)}</span></div>"
        for r in rows
    )
    return f"<div class='ce{'' if has_year else ' noy'}'><div class='ceh'>{head}</div>{body}</div>"


def diploma_block(ctx: Ctx) -> str:
    schools = ctx.doc.education
    top = highest_school(schools)
    if top is None:
        return ""
    title = top.degree or top.institution
    sub = top.institution if top.degree else ""
    label = (
        ctx.t["diploma"]
        if edu_rank(top.degree, top.institution)
        else ctx.t["schooling"]
    )
    field_, degree = split_degree(title)
    text = (
        "<div class='wt'>"
        + (f"<div class='wdl'>{esc(degree)}</div>" if degree else "")
        + f"<div class='wtt'>{esc(field_)}</div>"
        + (f"<div class='wts2'>{esc(sub)}</div>" if sub else "")
        + "</div>"
    )
    more = (
        f"<div class='cap'>{esc(more_at_end(ctx.lang, 'school', len(schools) - 1))}</div>"
        if len(schools) > 1
        else ""
    )
    return (
        f"<div class='wb'>{wreath_svg(last_year(top.dates), label)}{text}</div>{more}"
    )


def education_page1(ctx: Ctx) -> tuple[str, int]:
    """(HTML sekcji, ile certyfikatów przeniesionych na koniec CV)."""
    diploma = diploma_block(ctx)
    certs = certs_by_year(ctx.doc.certifications)
    hidden = 0
    if len(certs) > CERTS_ON_PAGE_1:
        hidden = len(certs) - CERTS_ON_PAGE_1
        certs = top_certs(ctx, certs, CERTS_ON_PAGE_1)
    reg = cert_table(ctx, certs)
    if hidden:
        reg += f"<div class='cap'>{esc(more_at_end(ctx.lang, 'certificate', hidden))}</div>"
    if diploma and reg:
        return f"<div class='ed'><div>{diploma}</div><div>{reg}</div></div>", hidden
    if diploma or reg:
        return f"<div>{diploma or reg}</div>", hidden
    return "", hidden


def education_full(ctx: Ctx, certs_hidden: int) -> str:
    """Pełna tabela szkół (gdy jest ich więcej niż jedna) i pełna lista certyfikatów
    (gdy strona 1 pokazała tylko część)."""
    schools = ctx.doc.education
    out = ""
    if len(schools) > 1:
        rows = "".join(
            f"<tr><td class='n'>{esc(s.dates.replace(' - ', ' – ')) or '—'}</td>"
            f"<td><b>{esc(s.institution)}</b></td><td>{esc(s.degree)}</td></tr>"
            for s in schools
        )
        out += (
            "<table class='edu'><colgroup><col style='width:20%'><col style='width:42%'><col style='width:38%'>"
            f"</colgroup><thead><tr><th>{esc(ctx.t['dates'])}</th><th>{esc(ctx.t['school'])}</th>"
            f"<th>{esc(ctx.t['field_degree'])}</th></tr></thead><tbody>{rows}</tbody></table>"
        )
    if certs_hidden:
        out += cert_table(ctx, certs_by_year(ctx.doc.certifications))
    return out
