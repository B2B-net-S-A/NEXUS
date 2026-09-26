"""Przegląd DZ: CV dla klienta obok oryginału i zapytania klienta (0353).

Dominik (Head of Recruitment) i Delivery Leadzi zatwierdzają „DZ ✓", sprawdzając
trzy rzeczy (decyzja Artura 23.09.2026):

* czy KAŻDE must-have z zapytania klienta jest w CV przygotowanym dla klienta,
* czy must-have są POGRUBIONE,
* czy must-have jest wpisany w KAŻDEJ roli, w której występuje w oryginalnym CV.

Te trzy sprawdzenia liczy kod, deterministycznie — ten sam wynik przy każdym
otwarciu. Luna (``dz_review``) dokłada podpowiedzi, których kod nie złapie
(synonim zamiast nazwy z zapytania, przesadzone twierdzenie, pogrubienie nie
tego słowa). Podpowiedzi są doradcze: ich awaria nigdy nie blokuje DZ.

Źródła:

* CV dla klienta — CV firmowe pary (sfinalizowane wygrywa ze szkicem, jak
  `_branded_cv_summary_for_pair`), a gdy go nie ma — najnowsze gotowe CV
  z generatora dla tej rekrutacji (auto-CV po „Zweryfikowany").
* Oryginał — snapshot CV z etapu (ten sam, który pokazuje „CV oryginalne"),
  a bez snapshotu tekst CV z profilu kandydata.
* Zapytanie klienta — must-have / nice-to-have tą samą regułą co wyszukiwanie
  (`requirements_for_job`), opis rekrutacji i „O projekcie" z Championa.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Optional

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.zip_guard import assert_safe_ooxml
from app.models.candidate import Candidate
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage
from app.services.cv_enrichment import company_norm
from app.services.keyword_terms import parse_keyword, py_regex

logger = logging.getLogger(__name__)

PROMPT_VERSION = "dz-review-v1"
ORIGINAL_TEXT_MAX = 30_000
REQUEST_TEXT_MAX = 6_000
PROMPT_CV_MAX = 18_000
MAX_HINTS = 12
EXTRA_BOLD_MAX = 15

_HEADINGS = {"h1", "h2", "h3", "h4"}
_BLOCKS = _HEADINGS | {"p", "li", "td", "th", "div"}
_BOLD = {"b", "strong"}
_SKIP = {"style", "script", "head", "title"}


# ── CV dla klienta: HTML → bloki z pogrubieniami ─────────────────────────────


@dataclass
class Block:
    kind: str  # "h" | "p" | "li"
    section: Optional[str]
    runs: list[dict] = field(default_factory=list)  # {"t": str, "b": bool}

    @property
    def text(self) -> str:
        return "".join(r["t"] for r in self.runs).strip()


class _BlockParser(HTMLParser):
    """Spłaszcza HTML CV do bloków; zapamiętuje pogrubienia i sekcje.

    Front renderuje bloki jako tekst React (bez ``innerHTML``), więc treść CV
    z edytora nigdy nie trafia na stronę jako HTML.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[Block] = []
        self._current: Optional[Block] = None
        self._bold = 0
        self._skip = 0
        self._stack: list[str] = []

    def _open(self, tag: str, attrs: dict) -> None:
        self._flush()
        kind = "h" if tag in _HEADINGS else "li" if tag == "li" else "p"
        self._current = Block(kind=kind, section=attrs.get("data-cv-section"))

    def _flush(self) -> None:
        if self._current is not None and self._current.text:
            self.blocks.append(self._current)
        self._current = None

    def handle_starttag(self, tag, attrs):  # noqa: D401
        amap = {k: (v or "") for k, v in attrs}
        if tag in _SKIP:
            self._skip += 1
            return
        if tag in _BOLD:
            self._bold += 1
        elif tag == "br":
            self._append(" ")
        elif tag in _BLOCKS and tag != "div":
            self._open(tag, amap)
        self._stack.append(tag)

    def handle_endtag(self, tag):
        if tag in _SKIP:
            self._skip = max(0, self._skip - 1)
            return
        if tag in _BOLD:
            self._bold = max(0, self._bold - 1)
        elif tag in _BLOCKS and tag != "div":
            self._flush()

    def handle_data(self, data):
        if self._skip:
            return
        self._append(data)

    def _append(self, data: str) -> None:
        text = re.sub(r"\s+", " ", data)
        if not text:
            return
        if self._current is None:
            if not text.strip():
                return
            self._current = Block(kind="p", section=None)
        bold = self._bold > 0
        runs = self._current.runs
        if runs and runs[-1]["b"] == bold:
            runs[-1]["t"] += text
        else:
            runs.append({"t": text, "b": bold})

    def close(self) -> None:
        super().close()
        self._flush()


def html_blocks(html: Optional[str]) -> list[Block]:
    if not html:
        return []
    parser = _BlockParser()
    parser.feed(html)
    parser.close()
    return parser.blocks


def blocks_text(blocks: list[Block], *, mark_bold: bool = False) -> str:
    lines: list[str] = []
    for block in blocks:
        if mark_bold:
            line = "".join(
                f"**{r['t'].strip()}**" if r["b"] and r["t"].strip() else r["t"]
                for r in block.runs
            ).strip()
        else:
            line = block.text
        prefix = "## " if block.kind == "h" else "- " if block.kind == "li" else ""
        lines.append(prefix + line)
    return "\n".join(lines)


# Pogrubienia z szablonu, nie z treści: nagłówek roli (stanowisko), etykiety
# grup umiejętności („Języki programowania: ") i „Rozważany na stanowisko".
_TEMPLATE_BOLD_SECTIONS = {"role", "considered"}


def bold_texts(blocks: list[Block]) -> list[str]:
    """Pogrubione frazy TREŚCI — to, co Dominik sprawdza przy must-have."""
    out: list[str] = []
    for block in blocks:
        if block.kind == "h" or block.section in _TEMPLATE_BOLD_SECTIONS:
            continue
        for run in block.runs:
            text = run["t"].strip()
            if run["b"] and text and not text.endswith(":"):
                out.append(text)
    return out


# ── Wymagania i dopasowanie ──────────────────────────────────────────────────


@dataclass(frozen=True)
class Requirement:
    label: str
    alternatives: tuple[str, ...]
    # Czego szukamy w tekście: nazwa bez opisu po myślniku i bez nawiasów.
    # Puste = szukamy alternatyw dosłownie.
    terms: tuple[str, ...] = ()


# „IT Project Management – prowadzenie i koordynacja…”: szukamy nazwy przed
# opisem. Dywiz musi mieć spacje po obu stronach, bo „CI-CD” to jedno słowo.
_DESCRIPTION_SPLIT = re.compile(r"\s+[–—-]\s+|:\s")
_PARENTHETICAL = re.compile(r"\([^()]*\)")


def _term(text: str) -> str:
    head = _DESCRIPTION_SPLIT.split(text, maxsplit=1)[0]
    head = _PARENTHETICAL.sub(" ", head)
    head = head.replace("(", " ").replace(")", " ")
    return " ".join(head.split()).strip(" ,;.")


def requirement_terms(alternatives: tuple[str, ...]) -> tuple[str, ...]:
    """Frazy do wyszukania dla wymagania, tak jak przeczyta je człowiek.

    Kontrakt wymagań dzieli tekst po „lub”, więc „react.js (v18 lub higher)”
    przychodzi jako „react.js (v18” i „higher)”. Rozdział wewnątrz nawiasu
    to nie są alternatywy — sklejamy je z powrotem i zdejmujemy nawias.
    """
    joined = " lub ".join(alternatives)
    unbalanced = any(a.count("(") != a.count(")") for a in alternatives)
    parts = (
        (joined,)
        if unbalanced and joined.count("(") == joined.count(")")
        else alternatives
    )
    out: list[str] = []
    for part in parts:
        term = _term(part)
        if len(term) >= 2 and term.casefold() not in {t.casefold() for t in out}:
            out.append(term)
    return tuple(out) or alternatives


def _patterns(name: str) -> list[re.Pattern[str]]:
    from app.services.skill_normalize import tech_alias_forms

    forms = {name.strip()}
    forms.update(tech_alias_forms(name))
    out: list[re.Pattern[str]] = []
    for form in sorted(forms, key=len, reverse=True):
        term = parse_keyword(form)
        if term is not None:
            out.append(py_regex(term))
    return out


def _found(text: str, req: Requirement) -> bool:
    names = req.terms or req.alternatives
    return any(p.search(text) for alt in names for p in _patterns(alt))


def _written_names(job: Job) -> dict[str, str]:
    """Nazwy tak, jak wpisał je Delivery Lead (kontrakt wymagań trzyma je
    kanonicznie, małymi literami — „java" zamiast „Java")."""
    from app.services import champion_view
    from app.services.skill_normalize import iter_skill_names

    names: list[str] = []
    for column in ("must_skills", "nice_skills"):
        names.extend(iter_skill_names(getattr(job, column, None)))
    stack = champion_view.stack(getattr(job, "champion_profile", None))
    for key in ("must", "nice"):
        names.extend(iter_skill_names(stack.get(key)))
    return {n.casefold(): n for n in reversed(names) if n}


def job_requirements(job: Job) -> tuple[list[Requirement], list[Requirement]]:
    from app.services.requirement_contract import requirements_for_job

    contract = requirements_for_job(job)
    written = _written_names(job)
    must: list[Requirement] = []
    nice: list[Requirement] = []
    for group in contract.all_of:
        alternatives = tuple(written.get(n.casefold(), n) for n in group.any_of)
        req = Requirement(
            label=" lub ".join(alternatives),
            alternatives=alternatives,
            terms=requirement_terms(alternatives),
        )
        if group.level == "must":
            must.append(req)
        elif group.level == "nice":
            nice.append(req)
    return must, nice


# ── Role: oryginał i CV dla klienta ─────────────────────────────────────────


@dataclass
class Role:
    label: str
    company: Optional[str]
    text: str
    title: Optional[str] = None


def _role_label(company: Optional[str], title: Optional[str]) -> str:
    parts = [p for p in (title, company) if p]
    return " · ".join(parts) if parts else "Stanowisko bez nazwy"


def generated_roles(blocks: list[Block]) -> list[Role]:
    """Role z CV dla klienta po znacznikach sekcji generatora.

    Generator oznacza nagłówek roli (``data-cv-section="role"``) i pracodawcę
    (``employer``); sanitizer edytora zostawia te atrybuty na ``<p>``. Bez
    znaczników (CV wklejone ręcznie) zwraca pustą listę, a wołający dzieli
    tekst po nazwach firm z oryginału.
    """

    roles: list[Role] = []
    current: Optional[dict] = None
    in_experience = False
    for block in blocks:
        if block.kind == "h":
            in_experience = block.section == "experience"
            if current is not None:
                roles.append(_close(current))
                current = None
            continue
        if not in_experience:
            continue
        if block.section == "role":
            if current is not None:
                roles.append(_close(current))
            current = {"title": block.text, "company": None, "lines": [block.text]}
        elif current is not None:
            if block.section == "employer" and current["company"] is None:
                current["company"] = block.text.split(" · ")[0].strip()
            current["lines"].append(block.text)
    if current is not None:
        roles.append(_close(current))
    return roles


def _close(current: dict) -> Role:
    return Role(
        label=_role_label(current["company"], current["title"]),
        company=current["company"],
        text="\n".join(current["lines"]),
        title=current["title"],
    )


def segment_by_companies(text: str, companies: list[str]) -> dict[str, str]:
    """Kawałek tekstu od wzmianki o firmie do następnej wzmianki o innej firmie."""

    hits: list[tuple[int, str]] = []
    low = text.casefold()
    for company in companies:
        needle = (company or "").strip().casefold()
        if len(needle) < 3:
            continue
        pos = low.find(needle)
        if pos >= 0:
            hits.append((pos, company))
    hits.sort()
    out: dict[str, str] = {}
    for i, (pos, company) in enumerate(hits):
        end = hits[i + 1][0] if i + 1 < len(hits) else len(text)
        out.setdefault(company, text[pos:end])
    return out


def original_roles(experience: Any, original_text: str) -> list[Role]:
    """Role z oryginału: wpisy ``candidate.experience`` (odczyt CV).

    Treść roli = opis i technologie z odczytu, a gdy ich brak (odczyt starszy
    niż profil v7) — kawałek tekstu oryginału przy nazwie firmy.
    """

    entries = [e for e in (experience or []) if isinstance(e, dict)]
    companies = [e.get("company") for e in entries if e.get("company")]
    segments = segment_by_companies(original_text or "", companies)
    roles: list[Role] = []
    for e in entries:
        company = e.get("company") or None
        title = e.get("role") or None
        own = " ".join(
            str(v)
            for v in (
                title,
                e.get("desc"),
                " ".join(e.get("technologies") or [])
                if isinstance(e.get("technologies"), list)
                else e.get("technologies"),
            )
            if v
        )
        segment = segments.get(company or "", "")
        roles.append(
            Role(
                label=_role_label(company, title),
                company=company,
                text=f"{own}\n{segment}".strip(),
                title=title,
            )
        )
    return roles


def _same_company(a: Optional[str], b: Optional[str]) -> bool:
    na, nb = company_norm(a), company_norm(b)
    if not na or not nb:
        return False
    return na == nb or na in nb or nb in na


def _same_title(original: Optional[str], generated: Optional[str]) -> bool:
    """Nagłówek roli z generatora to „Stanowisko daty" — porównujemy początek."""
    a = " ".join((original or "").casefold().split())
    b = " ".join((generated or "").casefold().split())
    return bool(a) and b.startswith(a)


def pair_roles(orig_roles: list[Role], gen_roles: list[Role]) -> list[Optional[Role]]:
    """Rola z CV dla klienta dla każdej roli oryginału (``None`` = pominięta).

    Kolejno: ta sama firma, to samo stanowisko, a gdy ŻADNA firma się nie
    zgadza — kolejność. Ostatnie to CV „blind": generator zamienia nazwy firm
    na „Firma z branży …", więc bez tego każda rola wyglądałaby na pominiętą.
    Przy zwykłym CV brak firmy znaczy naprawdę pominiętą rolę.
    """

    pairs: list[Optional[Role]] = [None] * len(orig_roles)
    used: set[int] = set()
    by_company = False
    for i, role in enumerate(orig_roles):
        for j, gen in enumerate(gen_roles):
            if j not in used and _same_company(gen.company, role.company):
                pairs[i], by_company = gen, True
                used.add(j)
                break
    for i, role in enumerate(orig_roles):
        if pairs[i] is not None:
            continue
        for j, gen in enumerate(gen_roles):
            if j not in used and _same_title(role.title, gen.title):
                pairs[i] = gen
                used.add(j)
                break
    if not by_company:
        free = [g for j, g in enumerate(gen_roles) if j not in used]
        for i in range(len(orig_roles)):
            if pairs[i] is None and free:
                pairs[i] = free.pop(0)
    return pairs


def analyze(
    must: list[Requirement],
    nice: list[Requirement],
    blocks: list[Block],
    original_text: str,
    experience: Any,
    *,
    bold_known: bool = True,
) -> dict:
    """Trzy sprawdzenia Dominika dla każdego must-have.

    ``bolded`` = ``None``, gdy pogrubień nie da się odczytać (CV z PDF-a).
    Gdy w CV dla klienta nie da się rozpoznać ŻADNEJ roli, sprawdzenie ról
    jest pomijane (``roles_checked = False``) — lepiej powiedzieć „sprawdź
    ręcznie" niż ogłosić każdą rolę pominiętą.
    """

    gen_text = blocks_text(blocks)
    bolds = bold_texts(blocks)
    bold_joined = "\n".join(bolds)
    orig_roles = original_roles(experience, original_text)
    gen_roles = generated_roles(blocks)
    if not gen_roles and orig_roles:
        # CV bez znaczników generatora: role po nazwach firm z oryginału.
        segs = segment_by_companies(
            gen_text, [r.company for r in orig_roles if r.company]
        )
        gen_roles = [
            Role(label=r.label, company=r.company, text=segs[r.company], title=r.title)
            for r in orig_roles
            if r.company and r.company in segs
        ]

    roles_checked = bool(gen_roles)
    pairs = pair_roles(orig_roles, gen_roles)
    checks: list[dict] = []
    for req in must:
        in_cv = bool(gen_text) and _found(gen_text, req)
        bolded: Optional[bool] = (
            (bool(bolds) and _found(bold_joined, req)) if bold_known else None
        )
        in_original: list[str] = []
        missing_in_roles: list[str] = []
        roles_absent: list[str] = []
        for role, match in zip(orig_roles, pairs):
            if not _found(role.text, req):
                continue
            in_original.append(role.label)
            if not roles_checked:
                continue
            if match is None:
                roles_absent.append(role.label)
            elif not _found(match.text, req):
                missing_in_roles.append(role.label)
        checks.append(
            {
                "label": req.label,
                "terms": list(req.terms or req.alternatives),
                "in_cv": in_cv,
                "bolded": bolded,
                "in_original": bool(original_text) and _found(original_text, req),
                "original_roles": in_original,
                "missing_in_roles": missing_in_roles,
                "roles_absent": roles_absent,
            }
        )

    wanted = must + nice
    extra: list[str] = []
    seen: set[str] = set()
    for text in bolds if bold_known else []:
        key = text.casefold()
        if key in seen or len(text) > 60:
            continue
        seen.add(key)
        if not any(_found(text, r) for r in wanted):
            extra.append(text)
    return {
        "checks": checks,
        "extra_bold": extra[:EXTRA_BOLD_MAX],
        "summary": {
            "must_total": len(checks),
            "must_in_cv": sum(1 for c in checks if c["in_cv"]),
            "must_bolded": sum(1 for c in checks if c["bolded"]),
            "roles_missing": sum(len(c["missing_in_roles"]) for c in checks),
            "generated_roles": len(gen_roles),
            "roles_checked": roles_checked,
            "bold_known": bold_known,
        },
    }


# ── Wczytanie źródeł ────────────────────────────────────────────────────────


def _strip_html(value: Optional[str]) -> str:
    if not value:
        return ""
    if "<" not in value:
        return value.strip()
    return blocks_text(html_blocks(value)).strip()


def _champion_about(job: Job) -> str:
    """„O projekcie" z Championa (także ze starego kształtu profilu)."""
    from app.services import champion_view

    project = champion_view.project(getattr(job, "champion_profile", None))
    parts = [project.get("about"), project.get("responsibilities")]
    return "\n".join(str(p).strip() for p in parts if p and str(p).strip())


async def _generated_cv(
    db: AsyncSession, candidate_id: int, job_id: int
) -> Optional[dict]:
    row = (
        await db.execute(
            select(CandidateStageCV)
            .join(
                CandidateStage, CandidateStage.id == CandidateStageCV.candidate_stage_id
            )
            .where(
                CandidateStage.candidate_id == candidate_id,
                CandidateStage.job_id == job_id,
                CandidateStageCV.branded_status.in_(("draft", "finalized")),
                CandidateStageCV.branded_draft_html.is_not(None),
            )
            .order_by(
                (CandidateStageCV.branded_status == "finalized").desc(),
                CandidateStage.moved_at.desc(),
                CandidateStage.id.desc(),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is not None:
        return {
            "source": "branded_finalized"
            if row.branded_status == "finalized"
            else "branded_draft",
            "stage_id": row.candidate_stage_id,
            "generated_document_id": row.generated_document_id,
            "updated_at": row.branded_finalized_at or row.branded_updated_at,
            "html": row.branded_draft_html,
        }
    doc = (
        await db.execute(
            select(CvGeneratedDocument)
            .where(
                CvGeneratedDocument.candidate_id == candidate_id,
                CvGeneratedDocument.job_id == job_id,
                CvGeneratedDocument.status == "ready",
                CvGeneratedDocument.render_payload.is_not(None),
            )
            .order_by(
                CvGeneratedDocument.created_at.desc(), CvGeneratedDocument.id.desc()
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if doc is None:
        return None
    from app.services.cv_generator_b2b.html_export import render_interactive_html
    from app.services.cv_generator_b2b.public_view import build_public_payload

    try:
        html = render_interactive_html(
            build_public_payload(doc.render_payload), [], document_only=True
        )
    except Exception:  # noqa: BLE001 — stary kształt payloadu: brak CV, nie 500
        logger.warning(
            "[dz_review] render generated doc=%s failed", doc.id, exc_info=True
        )
        return None
    return {
        "source": "generated",
        "stage_id": None,
        "generated_document_id": doc.id,
        "updated_at": doc.created_at,
        "html": html,
    }


_EXPERIENCE_HEADING = re.compile(
    r"do[sś]wiadczeni|experience|historia zatrudnienia|employment", re.IGNORECASE
)


def _run_bold(run: Any, paragraph_bold: bool) -> bool:
    if run.bold is not None:
        return bool(run.bold)
    style = getattr(run, "style", None)
    if style is not None and style.font is not None and style.font.bold:
        return True
    return paragraph_bold


def _docx_heading(text: str, style_name: str) -> bool:
    name = (style_name or "").casefold()
    if name.startswith(("heading", "nagłówek", "naglowek", "title", "tytuł")):
        return True
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and len(text) <= 60 and all(c.isupper() for c in letters)


def docx_blocks(data: bytes) -> list[Block]:
    """CV z Worda → bloki z pogrubieniami, w kolejności dokumentu.

    CV dla klienta przy Nordei robi się dziś poza NEXUSEM (plik „…B2B…" z
    Traffita, zmierzone 23.09.2026: 16 z 18 osób w kolejce DZ). Nagłówek =
    styl nagłówka albo krótka linia WIELKIMI literami; punkt = numeracja Worda
    albo styl listy; w sekcji doświadczenia w całości pogrubiony akapit to
    nagłówek roli (jak ``data-cv-section="role"`` z generatora), więc jego
    pogrubienie nie udaje pogrubionego must-have.
    """

    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    assert_safe_ooxml(data)
    doc = Document(io.BytesIO(data))
    blocks: list[Block] = []
    in_experience = False

    def paragraph(p: Any) -> None:
        nonlocal in_experience
        text = p.text.strip()
        if not text:
            return
        style = p.style
        style_name = style.name if style is not None else ""
        para_bold = bool(
            style is not None and style.font is not None and style.font.bold
        )
        runs: list[dict] = []
        for run in p.runs:
            if not run.text:
                continue
            bold = _run_bold(run, para_bold)
            if runs and runs[-1]["b"] == bold:
                runs[-1]["t"] += run.text
            else:
                runs.append({"t": run.text, "b": bold})
        if not runs:
            runs = [{"t": text, "b": para_bold}]
        numbered = p._p.pPr is not None and p._p.pPr.numPr is not None
        if _docx_heading(text, style_name) and not numbered:
            in_experience = bool(_EXPERIENCE_HEADING.search(text))
            blocks.append(
                Block(
                    kind="h",
                    section="experience" if in_experience else None,
                    runs=[{"t": text, "b": False}],
                )
            )
            return
        is_list = numbered or "list" in style_name.casefold()
        fully_bold = all(r["b"] for r in runs if r["t"].strip())
        section = "role" if in_experience and fully_bold and not is_list else None
        blocks.append(Block(kind="li" if is_list else "p", section=section, runs=runs))

    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            paragraph(Paragraph(child, doc))
        elif tag == "tbl":
            table = Table(child, doc)
            for row in table.rows:
                seen: set[int] = set()
                for cell in row.cells:
                    if id(cell._tc) in seen:
                        continue
                    seen.add(id(cell._tc))
                    for p in cell.paragraphs:
                        paragraph(p)
    return blocks


def text_blocks(text: str) -> list[Block]:
    return [
        Block(kind="p", section=None, runs=[{"t": line.strip(), "b": False}])
        for line in text.splitlines()
        if line.strip()
    ]


def _client_token(client_name: Optional[str]) -> Optional[str]:
    words = re.findall(r"[^\W\d_]{3,}", client_name or "")
    return words[0].casefold() if words else None


# Runda 8 (R8-N8-1): JEDNA reguła wyboru pliku „…B2B…" — QC CV czyta nią
# plik do oceny, a kolejka Cpro i wymagania przejścia (`move_requirements.
# company_cv_refs`) wskazują nią plik do pobrania. Do rundy 8 kolejka brała
# najnowszy plik po id, bez nazwy klienta: osoba od Cpro pobierała CV
# przygotowane pod innego klienta niż to, które przeszło QC.
_NOT_CV_DOCUMENT_KINDS = ("cover_letter", "certificate")


def document_cv_conditions() -> list[Any]:
    """Warunki pliku kandydata, który może być CV dla klienta spoza generatora."""

    from app.models.candidate_document import CandidateDocument

    return [
        CandidateDocument.filename.ilike("%b2b%"),
        CandidateDocument.source_deleted_at.is_(None),
        CandidateDocument.document_kind.notin_(_NOT_CV_DOCUMENT_KINDS),
    ]


def pick_document_cv(rows: Any, client_name: Optional[str]) -> Optional[int]:
    """Id pliku „…B2B…" dla klienta z wierszy ``(id, filename, uploaded_at,
    created_at)`` jednego kandydata: najpierw plik z nazwą klienta w nazwie,
    potem najnowszy (``uploaded_at``, a bez niej ``created_at``), potem id."""

    token = _client_token(client_name)

    def key(row: Any) -> tuple:
        doc_id, filename, uploaded_at, created_at = row
        stamp = uploaded_at or created_at
        miss = 0 if token and token in (filename or "").casefold() else 1
        return (
            miss,
            -stamp.timestamp() if stamp is not None else float("inf"),
            -doc_id,
        )

    ordered = sorted(rows, key=key)
    return ordered[0][0] if ordered else None


async def _document_cv(
    db: AsyncSession, candidate_id: int, client_name: Optional[str]
) -> Optional[dict]:
    """CV dla klienta przygotowane POZA generatorem: plik „…B2B…" kandydata.

    Wybór pliku: ``pick_document_cv``. PDF daje sam tekst — pogrubień z niego
    nie odczytamy (``bold_known = False``).
    """

    from app.models.candidate_document import CandidateDocument

    rows = (
        await db.execute(
            select(
                CandidateDocument.id,
                CandidateDocument.filename,
                CandidateDocument.uploaded_at,
                CandidateDocument.created_at,
            ).where(
                CandidateDocument.candidate_id == candidate_id,
                *document_cv_conditions(),
            )
        )
    ).all()
    doc_id = pick_document_cv(rows, client_name)
    doc = await db.get(CandidateDocument, doc_id) if doc_id is not None else None
    if doc is None:
        return None
    content: Optional[bytes] = None
    try:
        if doc.storage_key:
            from app.services.object_storage import download_cv

            content = await run_in_threadpool(download_cv, doc.storage_key)
        else:
            await db.refresh(doc, attribute_names=["file_content"])
            content = bytes(doc.file_content) if doc.file_content else None
    except Exception:  # noqa: BLE001 — magazyn chwilowo niedostępny
        logger.warning("[dz_review] document=%s unavailable", doc.id)
    if not content:
        return None
    filename = doc.filename or "cv.docx"
    bold_known = filename.casefold().endswith(".docx")
    if bold_known:
        try:
            blocks = await run_in_threadpool(docx_blocks, content)
        except Exception:  # noqa: BLE001 — zepsuty DOCX: sam tekst
            logger.warning("[dz_review] docx parse failed document=%s", doc.id)
            bold_known = False
            blocks = text_blocks(await run_in_threadpool(_extract, content, filename))
    else:
        blocks = text_blocks(await run_in_threadpool(_extract, content, filename))
    if not blocks:
        return None
    return {
        "source": "document",
        "stage_id": None,
        "generated_document_id": None,
        "document_id": doc.id,
        "filename": filename,
        "updated_at": doc.uploaded_at or doc.created_at,
        "bold_known": bold_known,
        "blocks": blocks,
    }


def _extract(content: bytes, filename: str) -> str:
    from app.services.cv_text_extractor import extract_text

    suffix = os.path.splitext(filename)[1] or ".bin"
    with tempfile.NamedTemporaryFile(suffix=suffix) as fh:
        fh.write(content)
        fh.flush()
        try:
            return extract_text(fh.name, filename)
        except Exception:  # noqa: BLE001 — nieobsługiwany format / zepsuty plik
            return ""


async def _original_cv(
    db: AsyncSession, candidate: Candidate, stage_id: int, job_id: int
) -> dict:
    """Snapshot oryginału z etapu przeglądu, a bez niego z najnowszego etapu
    tej samej pary, który go ma; bez żadnego — tekst CV z profilu."""
    from sqlalchemy import or_

    from app.services.candidate_stage_cv_service import (
        load_original_cv_bytes,
        snapshot_exists,
    )

    snapshots = (
        (
            await db.execute(
                select(CandidateStageCV)
                .join(
                    CandidateStage,
                    CandidateStage.id == CandidateStageCV.candidate_stage_id,
                )
                .where(
                    CandidateStage.candidate_id == candidate.id,
                    CandidateStage.job_id == job_id,
                    or_(
                        CandidateStageCV.original_cv_content.is_not(None),
                        CandidateStageCV.original_cv_storage_key.is_not(None),
                    ),
                )
                .order_by(
                    (CandidateStageCV.candidate_stage_id == stage_id).desc(),
                    CandidateStage.moved_at.desc(),
                    CandidateStage.id.desc(),
                )
                .limit(1)
            )
        )
        .scalars()
        .all()
    )
    for csv in snapshots:
        if not snapshot_exists(csv):
            continue
        try:
            content = await load_original_cv_bytes(csv)
        except Exception:  # noqa: BLE001 — magazyn chwilowo niedostępny
            logger.warning(
                "[dz_review] snapshot stage=%s unavailable", csv.candidate_stage_id
            )
            content = None
        text = ""
        if content:
            text = await run_in_threadpool(
                _extract, content, csv.original_cv_filename or "cv.pdf"
            )
        return {
            "source": "snapshot",
            "stage_id": csv.candidate_stage_id,
            "filename": csv.original_cv_filename,
            "text": text[:ORIGINAL_TEXT_MAX] or None,
        }
    profile_text = (candidate.raw_cv_text or "").strip()
    return {
        "source": "profile_text" if profile_text else None,
        "stage_id": None,
        "filename": None,
        "text": profile_text[:ORIGINAL_TEXT_MAX] or None,
    }


@dataclass
class ReviewSources:
    """Wszystko, co przegląd czyta o parze — wspólne dla DZ i QC CV (v5)."""

    candidate: Candidate
    job: Job
    client_name: Optional[str]
    must: list[Requirement]
    nice: list[Requirement]
    # Źródło CV dla klienta (`_generated_cv` / `_document_cv`) albo None.
    generated: Optional[dict]
    original: dict
    blocks: list[Block]
    bold_known: bool


async def load_sources(db: AsyncSession, stage: CandidateStage) -> ReviewSources:
    """Wczytaj źródła przeglądu pary z wiersza etapu. Wołający sprawdził dostęp."""

    candidate = await db.get(Candidate, stage.candidate_id)
    job = await db.get(Job, stage.job_id)
    if candidate is None or job is None:
        raise LookupError("stage without candidate or job")
    must, nice = job_requirements(job)
    client_name = None
    if job.client_id is not None:
        from app.models.client import Client  # noqa: PLC0415

        client = await db.get(Client, job.client_id)
        client_name = (client.display_name or client.name) if client else None
    generated = await _generated_cv(db, candidate.id, job.id)
    if generated is None:
        generated = await _document_cv(db, candidate.id, client_name)
    original = await _original_cv(db, candidate, stage.id, job.id)
    if generated is None:
        blocks: list[Block] = []
    elif "blocks" in generated:
        blocks = generated["blocks"]
    else:
        blocks = html_blocks(generated["html"])
    bold_known = bool(generated) and generated.get("bold_known", True)
    return ReviewSources(
        candidate=candidate,
        job=job,
        client_name=client_name,
        must=must,
        nice=nice,
        generated=generated,
        original=original,
        blocks=blocks,
        bold_known=bold_known,
    )


async def build_review(db: AsyncSession, stage: CandidateStage) -> dict:
    """Pełny przegląd pary z wiersza etapu. Wołający sprawdził dostęp."""

    src = await load_sources(db, stage)
    candidate, job, client_name = src.candidate, src.job, src.client_name
    must, nice = src.must, src.nice
    generated, original = src.generated, src.original
    blocks, bold_known = src.blocks, src.bold_known
    analysis = analyze(
        must,
        nice,
        blocks,
        original.get("text") or "",
        candidate.experience,
        bold_known=bold_known,
    )
    name = " ".join(p for p in (candidate.name, candidate.lastname) if p) or "Kandydat"
    return {
        "stage_id": stage.id,
        "candidate_id": candidate.id,
        "candidate_name": name,
        "job_id": job.id,
        "job_title": job.title,
        "client_name": client_name,
        "client_request": {
            "must": [r.label for r in must],
            "nice": [r.label for r in nice],
            "description": _strip_html(job.description)[:REQUEST_TEXT_MAX] or None,
            "project_about": _champion_about(job)[:REQUEST_TEXT_MAX] or None,
        },
        "generated_cv": (
            {
                "source": generated["source"],
                "stage_id": generated["stage_id"],
                "generated_document_id": generated["generated_document_id"],
                "document_id": generated.get("document_id"),
                "filename": generated.get("filename"),
                "bold_known": bold_known,
                "updated_at": generated["updated_at"],
                "blocks": [
                    {"kind": b.kind, "section": b.section, "runs": b.runs}
                    for b in blocks
                ],
            }
            if generated
            else None
        ),
        "original_cv": original,
        **analysis,
    }


# ── Podpowiedzi Luny ────────────────────────────────────────────────────────

_HINT_KINDS = {
    "missing_must",
    "not_bolded",
    "missing_in_role",
    "unsupported",
    "wording",
    "other",
}
_SEVERITIES = {"high", "medium", "low"}

_PROMPT = """Jesteś asystentem Delivery Leada w firmie body-leasingowej IT. Przed
wysłaniem CV do klienta sprawdza on, czy CV przygotowane dla klienta dobrze
pokazuje wymagania klienta. Sprawdź TYLKO to:

1. Czy każde must-have z zapytania jest w CV dla klienta (także pod inną
   nazwą — wtedy zaproponuj nazwę z zapytania).
2. Czy must-have są pogrubione (w tekście CV pogrubienie = **tekst**).
   Zwróć uwagę na pogrubienia nie tych słów, co trzeba.
3. Czy must-have jest wpisany w każdej roli, w której oryginalne CV pokazuje
   jego użycie.
4. Czy CV dla klienta nie twierdzi czegoś, czego nie ma w oryginale
   (technologia, lata, rola).

Nie oceniaj stylu ani długości. Nie wymyślaj faktów o kandydacie — opieraj się
wyłącznie na dwóch tekstach poniżej. Pisz po polsku, krótko, konkretnie:
co poprawić i gdzie. Cytat (quote) kopiuj dosłownie z jednego z tekstów
albo zostaw null.

Wynik kodu (już policzony, nie powtarzaj go dosłownie, uzupełnij):
{checks}

ZAPYTANIE KLIENTA
Stanowisko: {title}
Must-have: {must}
Nice-to-have: {nice}
Opis: {description}

CV DLA KLIENTA
{generated}

ORYGINALNE CV
{original}

Zwróć WYŁĄCZNIE JSON:
{{"verdict": "ok" | "fix", "hints": [{{"kind": "missing_must" | "not_bolded" |
"missing_in_role" | "unsupported" | "wording" | "other", "severity": "high" |
"medium" | "low", "must_have": string | null, "message": string,
"quote": string | null}}]}}
Najwyżej {max_hints} podpowiedzi, najważniejsze pierwsze. Gdy wszystko jest
w porządku: {{"verdict": "ok", "hints": []}}."""


def hints_input(review: dict) -> dict:
    """Materiał dla modelu — ten sam dla skrótu i dla promptu."""

    blocks = [
        Block(kind=b["kind"], section=b["section"], runs=b["runs"])
        for b in ((review.get("generated_cv") or {}).get("blocks") or [])
    ]
    request = review["client_request"]
    checks = [
        {
            k: c[k]
            for k in ("label", "in_cv", "bolded", "missing_in_roles", "roles_absent")
        }
        for c in review["checks"]
    ]
    return {
        "title": review["job_title"],
        "must": request["must"],
        "nice": request["nice"],
        "description": (
            request.get("description") or request.get("project_about") or ""
        )[:REQUEST_TEXT_MAX],
        "generated": blocks_text(blocks, mark_bold=True)[:PROMPT_CV_MAX],
        "original": ((review.get("original_cv") or {}).get("text") or "")[
            :PROMPT_CV_MAX
        ],
        "checks": checks,
    }


def input_hash(material: dict, model: str) -> str:
    payload = json.dumps(
        {"v": PROMPT_VERSION, "model": model, **material},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _norm(text: str) -> str:
    return " ".join(text.replace("**", "").split()).casefold()


def parse_hints(raw: str, material: dict) -> dict:
    """JSON modelu → podpowiedzi; cytat spoza obu tekstów jest usuwany."""

    body = raw.strip()
    if body.startswith("```"):
        body = body.strip("`")
        if body.lower().startswith("json"):
            body = body[4:]
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in model output")
    data = json.loads(body[start : end + 1])
    haystack = _norm(material["generated"]) + "\n" + _norm(material["original"])
    hints: list[dict] = []
    for item in data.get("hints") or []:
        if not isinstance(item, dict):
            continue
        message = str(item.get("message") or "").strip()
        if not message:
            continue
        kind = item.get("kind") if item.get("kind") in _HINT_KINDS else "other"
        severity = (
            item.get("severity") if item.get("severity") in _SEVERITIES else "medium"
        )
        quote = item.get("quote")
        quote = str(quote).strip() if quote else None
        if quote and _norm(quote) not in haystack:
            quote = None
        must_have = item.get("must_have")
        hints.append(
            {
                "kind": kind,
                "severity": severity,
                "must_have": str(must_have)[:120] if must_have else None,
                "message": message[:400],
                "quote": quote[:300] if quote else None,
            }
        )
        if len(hints) >= MAX_HINTS:
            break
    verdict = data.get("verdict")
    if verdict not in ("ok", "fix"):
        verdict = "fix" if hints else "ok"
    return {"verdict": verdict, "hints": hints}


async def generate_hints(
    db: AsyncSession, stage: CandidateStage, review: dict, *, user_id: int
) -> dict:
    """Podpowiedzi Luny z pamięcią per (etap, skrót wejścia). Nigdy nie rzuca."""

    from app.models.ai_feature import AIFeatureKey
    from app.models.dz_review_hint import DzReviewHint
    from app.services.ai_models import model_chain_for
    from app.services.llm_providers import api_key_configured

    if review.get("generated_cv") is None:
        return {
            "status": "no_cv",
            "hints": [],
            "verdict": None,
            "model": None,
            "cached": False,
        }
    chain = model_chain_for(AIFeatureKey.dz_review)
    material = hints_input(review)
    digest = input_hash(material, chain[0])
    cached = await db.scalar(
        select(DzReviewHint).where(
            DzReviewHint.candidate_stage_id == stage.id,
            DzReviewHint.input_hash == digest,
        )
    )
    if cached is not None:
        return {**cached.payload, "status": "ok", "model": cached.model, "cached": True}
    if not api_key_configured(chain[0]):
        return {
            "status": "unavailable",
            "hints": [],
            "verdict": None,
            "model": chain[0],
            "cached": False,
        }

    from app.services.ai_quota import ai_feature
    from app.services.claude_client import call_claude, text_of

    prompt = _PROMPT.format(
        checks=json.dumps(material["checks"], ensure_ascii=False),
        title=material["title"],
        must=", ".join(material["must"]) or "(brak)",
        nice=", ".join(material["nice"]) or "(brak)",
        description=material["description"] or "(brak opisu)",
        generated=material["generated"] or "(brak)",
        original=material["original"] or "(brak tekstu oryginału)",
        max_hints=MAX_HINTS,
    )
    try:
        async with ai_feature(db, AIFeatureKey.dz_review, user_id=user_id):
            await db.commit()
            message = await run_in_threadpool(
                call_claude,
                model=chain[0],
                fallback_models=chain[1:] or None,
                max_tokens=2000,
                thinking={"type": "disabled"},
                messages=[{"role": "user", "content": prompt}],
            )
        result = parse_hints(text_of(message), material)
    except Exception as exc:  # noqa: BLE001 — podpowiedź doradcza, nigdy bramka
        logger.warning(
            "[dz_review] hints failed stage=%s: %s", stage.id, type(exc).__name__
        )
        return {
            "status": "unavailable",
            "hints": [],
            "verdict": None,
            "model": chain[0],
            "cached": False,
        }
    model = getattr(message, "model", None) or chain[0]
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    await db.execute(
        pg_insert(DzReviewHint)
        .values(
            candidate_stage_id=stage.id,
            input_hash=digest,
            model=str(model)[:80],
            payload=result,
        )
        .on_conflict_do_nothing(constraint="uq_dz_review_hints_stage_hash")
    )
    await db.commit()
    return {**result, "status": "ok", "model": str(model), "cached": False}
