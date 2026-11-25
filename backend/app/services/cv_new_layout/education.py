"""„Edukacja”: najwyższy dyplom w wieńcu, 3 najważniejsze certyfikaty (rok + nazwa),
reszta w pełnych listach na końcu CV (Artur 20.11.2026: EH1, CE1, MC2)."""

from __future__ import annotations

import re
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
from app.services.cv_new_layout.wreath import wreath_cert_svg, wreath_svg

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
    score = _scorer(ctx)
    order = {id(c): i for i, c in enumerate(certs)}
    return sorted(
        certs, key=lambda c: (-score(c), -(int(c.year) if c.year else 0), order[id(c)])
    )[:n]


def _scorer(ctx: Ctx):
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

    return score


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


def _certs_page1(ctx: Ctx, certs: Sequence[Cert]) -> tuple[list[Cert], int]:
    """(certyfikaty na stronę 1, ile przeniesionych na koniec CV)."""
    certs = list(certs)
    if len(certs) <= CERTS_ON_PAGE_1:
        return certs, 0
    return top_certs(ctx, certs, CERTS_ON_PAGE_1), len(certs) - CERTS_ON_PAGE_1


def cert_list(rows: Sequence[Cert]) -> str:
    """Certyfikaty bez nagłówka tabeli: rok w kolorze marki, nazwa pogrubiona."""
    if not rows:
        return ""
    body = "".join(
        f"<div class='cli'>{f'<span class=cly>{esc(r.year)}</span>' if r.year else ''}"
        f"<span class='cln'>{esc(r.name)}</span></div>"
        for r in rows
    )
    return f"<div class='cl{'' if any(r.year for r in rows) else ' noy'}'>{body}</div>"


def sub_label(text: str) -> str:
    return f"<div class='sublab'>{esc(text)}</div>"


# ---------- wieniec: certyfikat czy dyplom (Artur 23.11.2026, wariant E4) ----------
# Kurs, szkolenie czy webinar nie trafia do wieńca (np. „Wprowadzenie do dostępności cyfrowej”).
_COURSE = (
    "kurs",
    "szkoleni",
    "wprowadzenie",
    "course",
    "training",
    "webinar",
    "warsztat",
    "essentials",
    "szkoła",
    "podstawy",
    "bootcamp",
)
_PRO = (
    "certified",
    "certyfikowan",
    "istqb",
    "pmp",
    "prince2",
    "ipma",
    "psm",
    "pspo",
    "safe",
    "itil",
    "cbap",
    "ccba",
    "ireb",
    "aws",
    "azure",
    "pl-",
    "az-",
    "oracle",
    "blue prism",
    "cisco",
)
_SHORT_CODE = re.compile(r"\(([A-Z]{2,4}-\d{2,4})\)")
_SHORT_TOKEN = re.compile(
    r"\b(PMP|ISTQB|IPMA|PRINCE2|PSM(?: I{1,3})?|PSPO|ITIL|CBAP|CCBA|IREB|SAFe|CSM|AWS|OCA|OCP|CCNA)\b"
)
_WORD = re.compile(r"[\w+#.-]+", re.U)


def is_course(c: Cert) -> bool:
    low = f" {c.name} ".lower()
    return any(w in low for w in _COURSE)


def is_professional(c: Cert) -> bool:
    low = f" {c.name} ".lower()
    return any(w in low for w in _PRO) and not is_course(c)


def short_name(c: Cert) -> str:
    m = _SHORT_CODE.search(c.name) or _SHORT_TOKEN.search(c.name)
    return m.group(1) if m else ""


def _words(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text or "") if len(w) >= 2}


_CERT_CODE = re.compile(r"\b[A-Z]{2,4}-\d{2,4}\b")


def looks_like_certificate(requirement: str) -> bool:
    """Wymaganie MUST, które samo jest certyfikatem (PMP, PRINCE2, ISTQB, „AWS Certified”,
    kod AZ-104), a nie umiejętnością („UX Design”, „Testy API”)."""
    low = f" {requirement} ".lower()
    return bool(
        _SHORT_TOKEN.search(requirement)
        or _CERT_CODE.search(requirement)
        or any(
            w in low
            for w in (
                "certyfika",
                "certified",
                "certification",
                "practitioner",
                "foundation level",
            )
        )
    )


def required_by_client(ctx: Ctx, c: Cert) -> bool:
    """Certyfikat z wymagań MUST klienta: wymaganie jest certyfikatem i wszystkie jego
    słowa (bez „lub”) stoją w nazwie certyfikatu, np. MUST „PRINCE2 Practitioner” ↔
    „PRINCE2 Practitioner – Axelos”, MUST „ISTQB” ↔ „ISTQB Foundation Level”.
    Umiejętność („UX Design”) nie wciąga kursu do wieńca (staging 23.11.2026)."""
    name = _words(c.name)
    for must in ctx.doc.must_have:
        for option in re.split(r"\s+(?:lub|or)\s+|/", must, flags=re.I):
            need = _words(option)
            if need and looks_like_certificate(option) and need <= name:
                return True
    return False


def wreath_cert(ctx: Ctx) -> Optional[Cert]:
    """Certyfikat do wieńca albo None (wtedy dyplom). Domyślnie certyfikat tylko,
    gdy klient go wymaga (MUST); rekruter może wybrać „certyfikat” albo „szkołę”."""
    choice = ctx.doc.wreath
    if choice == "school":
        return None
    certs = certs_by_year(ctx.doc.certifications)
    required = [c for c in certs if not is_course(c) and required_by_client(ctx, c)]
    if required:
        return required[0]
    if choice != "cert" or not certs:
        return None
    pro = [c for c in certs if is_professional(c)] or certs
    return top_certs(ctx, pro, 1)[0]


def _cert_text(ctx: Ctx, c: Cert) -> str:
    meta = " · ".join(x for x in (c.issuer, c.year) if x)
    return (
        "<div class='wt'>"
        f"<div class='wdl'>{esc(ctx.t['certificate'])}</div>"
        f"<div class='wtt'>{esc(c.name)}</div>"
        + (f"<div class='wts2'>{esc(meta)}</div>" if meta else "")
        + "</div>"
    )


def _school_line(ctx: Ctx) -> str:
    top = highest_school(ctx.doc.education)
    if top is None:
        return ""
    field_, degree = split_degree(top.degree or top.institution)
    bits = [f"<b>{esc(field_)}</b>"] + ([esc(degree)] if degree else [])
    sub = " · ".join(
        x for x in (top.institution if top.degree else "", last_year(top.dates)) if x
    )
    return (
        f"<div class='sch'>{', '.join(bits)}"
        + (f"<div class='wts2'>{esc(sub)}</div>" if sub else "")
        + "</div>"
    )


def _more(ctx: Ctx, key: str, n: int) -> str:
    return (
        f"<div class='cap'>{esc(more_at_end(ctx.lang, key, n))}</div>" if n > 0 else ""
    )


def education_page1(ctx: Ctx) -> tuple[str, int]:
    """(HTML sekcji, ile certyfikatów przeniesionych na koniec CV).

    Lewa kolumna: wieniec — certyfikat (skrót w środku) albo dyplom (rok w środku).
    Prawa: „Wykształcenie” (gdy w wieńcu jest certyfikat) i podpisane
    „Certyfikaty i szkolenia · N”, żeby certyfikatów nie przeoczyć (warsztaty 23.11)."""
    schools = ctx.doc.education
    all_certs = certs_by_year(ctx.doc.certifications)
    kc = wreath_cert(ctx)
    if kc is not None:
        short = short_name(kc)
        emblem = (
            wreath_cert_svg(short, kc.year)
            if short
            else wreath_svg(kc.year, ctx.t["certificate"])
        )
        left = f"<div class='wb'>{emblem}{_cert_text(ctx, kc)}</div>"
        others = [c for c in all_certs if c.name != kc.name]
        shown, hidden = _certs_page1(ctx, others)
        right = ""
        school = _school_line(ctx)
        if school:
            right += (
                sub_label(ctx.t["schooling_head"])
                + school
                + _more(ctx, "school", len(schools) - 1)
            )
        if shown:
            right += (
                ("<div class='gap'></div>" if school else "")
                + sub_label(f"{ctx.t['other_certs']} · {len(others)}")
                + cert_list(shown)
                + _more(ctx, "certificate", hidden)
            )
        if not right:
            return f"<div>{left}</div>", hidden
        return f"<div class='ed'><div>{left}</div><div>{right}</div></div>", hidden
    diploma = diploma_block(ctx)
    shown, hidden = _certs_page1(ctx, all_certs)
    certs = (
        sub_label(f"{ctx.t['certs_training']} · {len(all_certs)}")
        + cert_list(shown)
        + _more(ctx, "certificate", hidden)
        if shown
        else ""
    )
    if diploma and certs:
        left = sub_label(ctx.t["schooling_head"]) + diploma
        return f"<div class='ed'><div>{left}</div><div>{certs}</div></div>", hidden
    return (f"<div>{diploma or certs}</div>" if diploma or certs else ""), hidden


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


# ---------- bez wieńca, gdy wieniec stoi przy wyróżniku (Artur 25.11.2026, wariant ED) ----------
# Ikony: biret przy „Wykształceniu”, odznaka przy „Certyfikatach”; kolor wprost w atrybutach,
# bo WeasyPrint nie stosuje CSS do wnętrza SVG.
ICON_SCHOOL = (
    "<svg class='ic' viewBox='0 0 24 24'><g fill='none' stroke='#E73748' stroke-width='1.7' "
    "stroke-linejoin='round'><path d='M2 9l10-5 10 5-10 5z'/><path d='M6 11v5c2.5 2 9.5 2 12 0v-5'/>"
    "<path d='M22 9v6'/></g></svg>"
)
ICON_CERT = (
    "<svg class='ic' viewBox='0 0 24 24'><g fill='none' stroke='#E73748' stroke-width='1.7' "
    "stroke-linejoin='round'><circle cx='12' cy='9' r='6'/><path d='M8.5 14L7 22l5-3 5 3-1.5-8'/>"
    "<path d='M9.5 9l1.8 1.8L15 7.5'/></g></svg>"
)


def _dot(*parts: str) -> str:
    return " · ".join(esc(p) for p in parts if p)


def education_plain(ctx: Ctx) -> tuple[str, int]:
    """Edukacja bez wieńca: „Wykształcenie” (kierunek, stopień · rok, uczelnia) obok
    „Certyfikaty i szkolenia · N” (nazwa, wystawca · rok; wystawca znika, gdy stoi w nazwie)."""
    schools = ctx.doc.education
    certs = certs_by_year(ctx.doc.certifications)
    shown, hidden = _certs_page1(ctx, certs)
    left = right = ""
    top = highest_school(schools)
    if top is not None:
        field_, degree = split_degree(top.degree or top.institution)
        uni = top.institution if top.degree else ""
        meta = _dot(degree, last_year(top.dates))
        left = (
            f"<div class='edh'>{ICON_SCHOOL}<span>{esc(ctx.t['schooling_head'])}</span></div>"
            f"<div class='edi'><div class='edf'>{esc(field_)}</div>"
            + (f"<div class='edd'>{meta}</div>" if meta else "")
            + (f"<div class='edu'>{esc(uni)}</div>" if uni else "")
            + "</div>"
            + _more(ctx, "school", len(schools) - 1)
        )
    if shown:
        rows = []
        for c in shown:
            issuer = (
                c.issuer if c.issuer and c.issuer.lower() not in c.name.lower() else ""
            )
            meta = _dot(issuer, c.year)
            rows.append(
                f"<div class='edi c'><div class='edf'>{esc(c.name)}</div>"
                + (f"<div class='edd'>{meta}</div>" if meta else "")
                + "</div>"
            )
        right = (
            f"<div class='edh'>{ICON_CERT}<span>{esc(ctx.t['certs_training'])} · {len(certs)}</span></div>"
            + "".join(rows)
            + _more(ctx, "certificate", hidden)
        )
    if not (left or right):
        return "", hidden
    return (
        f"<div class='edp'><div>{left or right}</div><div>{right if left else ''}</div></div>",
        hidden,
    )
