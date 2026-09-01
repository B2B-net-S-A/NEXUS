"""Canonical, versioned candidate/job embedding text (plan PR7).

One place that turns an entity into the text we embed, built from *labeled,
PII-free* sections instead of a flat name+CV blob. Deliberate properties:

* **No PII** — name, lastname, email, phone, address, city and raw contact
  fields never enter the embedding (they add noise and are a privacy risk).
* **Labeled sections** so the same facts serialise stably and a reader can see
  what drove a match.
* **Normalised skills** — list-of-dict / list-of-str / dict / str all collapse
  to a clean token list.
* **Quality-gated free text** — an AI summary or raw-CV excerpt that looks like
  OCR/CID junk is dropped rather than embedded.
* **Raw CV only as a fallback** — used (quality-gated, truncated) only when the
  structured sections are empty.

Selected by ``AI_TEXT_SCHEMA_V2``; the legacy builder stays the default. See
``embedding_service._build_candidate_text`` for the dispatcher.
"""

from __future__ import annotations

import hashlib
import re

from app.services import champion_view

TEXT_SCHEMA_V1 = "text-v1-legacy"
TEXT_SCHEMA_V2 = "text-v2-canonical"
TEXT_SCHEMA_V3 = "text-v3-cv-notes"

# Fields that must never be embedded (PII / noise).
_PII_FIELDS = frozenset(
    {"name", "lastname", "email", "phone", "address", "city", "postal_code"}
)

_CID_RE = re.compile(r"\(cid:\d+\)")
_WS_RE = re.compile(r"\s+")


def content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def looks_like_junk(text: str) -> bool:
    """Heuristic OCR/CID-junk gate for free text before embedding."""
    if not text or not text.strip():
        return True
    t = text.strip()
    if _CID_RE.search(t):
        return True
    letters = sum(c.isalpha() for c in t)
    # Mostly non-alphabetic (symbol soup / broken extraction) → junk.
    return letters / max(len(t), 1) < 0.5


def _clean(text: str) -> str:
    return _WS_RE.sub(" ", _CID_RE.sub(" ", text or "")).strip()


def _skill_names(skills) -> list[str]:
    out: list[str] = []
    if isinstance(skills, list):
        for s in skills:
            if isinstance(s, dict):
                n = s.get("name") or s.get("skill") or ""
                if n:
                    out.append(str(n))
            elif isinstance(s, str) and s.strip():
                out.append(s.strip())
    elif isinstance(skills, dict):
        for key in ("technologies", "skills", "stack", "tech"):
            v = skills.get(key)
            if isinstance(v, list):
                out.extend(str(x) for x in v if x)
            elif isinstance(v, str) and v.strip():
                out.extend(t.strip() for t in re.split(r"[,;]+", v) if t.strip())
    elif isinstance(skills, str) and skills.strip():
        out.extend(t.strip() for t in re.split(r"[,;\n]+", skills) if t.strip())
    # De-dupe, preserve order.
    seen: set[str] = set()
    uniq: list[str] = []
    for s in out:
        k = s.lower()
        if k not in seen:
            seen.add(k)
            uniq.append(s)
    return uniq


_REF_NOISE_RE = re.compile(r"\b(ref|nr|no)\.?\s*[:#]?\s*[\w-]+", re.IGNORECASE)


def _strip_ref_noise(title: str) -> str:
    return _clean(_REF_NOISE_RE.sub(" ", title or ""))


def _seniority_phrase(years) -> str | None:
    if years is None:
        return None
    try:
        y = float(years)
    except (TypeError, ValueError):
        return None
    if y >= 7:
        band = "senior"
    elif y >= 3:
        band = "mid-level"
    else:
        band = "junior"
    return f"{int(y)}+ years ({band})"


def build_candidate_text_v2(candidate) -> str:
    """PII-free, labeled canonical candidate document."""
    sections: list[str] = []

    cc = getattr(candidate, "competence_category", None)
    if cc:
        sections.append(f"[ROLE] {_clean(str(cc))}")

    sen = _seniority_phrase(getattr(candidate, "years_it_experience", None))
    if sen:
        sections.append(f"[SENIORITY] {sen}")

    skills = _skill_names(getattr(candidate, "skills", None))
    if skills:
        sections.append("[SKILLS] " + ", ".join(skills))

    verified = _skill_names(getattr(candidate, "verified_tech", None))
    if verified:
        sections.append("[VERIFIED] " + ", ".join(verified))

    exp = getattr(candidate, "experience", None)
    exp_lines: list[str] = []
    if isinstance(exp, list):
        for e in exp[:8]:  # recent-experience cap
            if isinstance(e, dict):
                role = _clean(str(e.get("role") or ""))
                company = _clean(str(e.get("company") or ""))
                desc = _clean(str(e.get("desc") or ""))[:300]
                bit = " — ".join(x for x in (role, company) if x)
                if desc:
                    bit = f"{bit}: {desc}" if bit else desc
                if bit:
                    exp_lines.append(bit)
    elif isinstance(exp, str) and exp.strip():
        exp_lines.append(_clean(exp)[:500])
    if exp_lines:
        sections.append("[EXPERIENCE] " + " | ".join(exp_lines))

    prefs = getattr(candidate, "preferences", None)
    if isinstance(prefs, dict):
        industries = prefs.get("industries") or []
        if isinstance(industries, list) and industries:
            sections.append("[DOMAINS] " + ", ".join(str(i) for i in industries if i))

    summary = getattr(candidate, "ai_summary", None)
    if summary and not looks_like_junk(summary):
        sections.append("[SUMMARY] " + _clean(summary)[:1000])

    # Raw CV only as a fallback when structured sections are empty, and only if
    # it does not look like extraction junk.
    if not sections:
        raw = getattr(candidate, "raw_cv_text", None)
        if raw and not looks_like_junk(raw):
            sections.append("[CV] " + _clean(raw)[:2000])

    return "\n".join(sections)


# v3: pełne CV zawsze + fakty z notatek. Zmierzone na prodzie 2026-08-18:
# 63% CV (32k z 50,6k) jest dłuższych niż 3000 znaków, które ucinał builder v1,
# a 7,3k kandydatów ma potwierdzone w rozmowach umiejętności, które nigdy nie
# trafiały do wektora. voyage-3-large przyjmuje 32k tokenów — limit 3000 znaków
# był NASZYM literałem, nie ograniczeniem modelu.
_V3_CV_CAP = 12_000

# Pola z ekstrakcji notatek, które wchodzą do embeddingu. Świadomie WĄSKI
# wybór: stawki, veta klientów i statusy pozwoleń to dane wrażliwe/finansowe,
# a `skills_gaps_observed` to sygnał NEGATYWNY — w wektorze przyciągałby
# dopasowania dokładnie tam, gdzie kandydatowi czegoś brakuje.
_V3_NOTES_SKILL_FIELDS = ("skills_evidenced", "certifications")


def _notes_insights_of(candidate) -> dict | None:
    """`cv_extracted_data._notes_insights` albo None.

    Bez idiomu `or {}` — `cv_extracted_data` na prodzie bywa LISTĄ (pilnuje
    tego repo-wide guard-test), więc każdy krok to jawny isinstance.
    """
    data = getattr(candidate, "cv_extracted_data", None)
    if not isinstance(data, dict):
        return None
    ins = data.get("_notes_insights")
    return ins if isinstance(ins, dict) else None


def _notes_section(candidate) -> str | None:
    ins = _notes_insights_of(candidate)
    if ins is None:
        return None
    bits: list[str] = []
    for field in _V3_NOTES_SKILL_FIELDS:
        val = ins.get(field)
        if not isinstance(val, list):
            continue
        for item in val:
            if isinstance(item, dict):
                n = item.get("name")
                if isinstance(n, str) and n.strip():
                    bits.append(n.strip())
            elif isinstance(item, str) and item.strip():
                bits.append(item.strip())
    langs = ins.get("languages_observed")
    if isinstance(langs, list):
        bits.extend(str(x).strip() for x in langs if isinstance(x, str) and x.strip())
    if not bits:
        return None
    seen: set[str] = set()
    uniq: list[str] = []
    for b in bits:
        k = b.lower()
        if k not in seen:
            seen.add(k)
            uniq.append(b)
    return "[NOTES] " + ", ".join(uniq)


def build_candidate_text_v3(candidate) -> str:
    """v2 + pełne CV zawsze (nie fallback) + fakty potwierdzone w notatkach.

    Różnice względem v2 są dokładnie dwie i obie mają zmierzone uzasadnienie
    (patrz komentarz przy `_V3_CV_CAP`): CV przestaje być fallbackiem i wchodzi
    ZAWSZE (bramkowane jakością, cap 12k), a sekcja [NOTES] niesie umiejętności
    potwierdzone w rozmowach. PII nadal nie wchodzi.
    """
    base = build_candidate_text_v2(candidate)
    sections = [base] if base else []

    notes = _notes_section(candidate)
    if notes:
        sections.append(notes)

    raw = getattr(candidate, "raw_cv_text", None)
    if raw and not looks_like_junk(raw):
        cv = "[CV] " + _clean(raw)[:_V3_CV_CAP]
        # v2 mógł już dodać [CV] jako fallback (pusty szkielet strukturalny) —
        # wtedy zastępujemy krótszy wycinek pełnym, zamiast dublować sekcję.
        if base and "[CV] " in base:
            sections[0] = "\n".join(
                line for line in base.split("\n") if not line.startswith("[CV] ")
            )
        sections.append(cv)

    return "\n".join(s for s in sections if s)


# Warianty zapytania dla multi-query retrieval (runda 2, punkt 2). Jedno
# zapytanie z jednego tekstu oferty ma jeden „kierunek" w przestrzeni — unia
# pul z kilku sformułowań podnosi recall bez dotykania indeksu. Warianty
# decydują o CZŁONKOSTWIE w puli; podobieństwo semantyczne dla wybranych
# liczy się osobno względem tekstu głównego (ten sam wzorzec co hybryda
# w `retrieval_pool` — wyniki z różnych zapytań żyją na różnych skalach).
def build_job_query_variants(job, base_text: str | None = None) -> list[str]:
    """Krótkie, komplementarne sformułowania zapytania dla jednej oferty.

    Zwraca listę BEZ tekstu głównego (ten idzie osobno jako zapytanie
    pierwotne): [tytuł+seniority] oraz [must+nice skills]. Puste warianty
    i duplikaty tekstu głównego odpadają.
    """
    variants: list[str] = []

    title = _strip_ref_noise(getattr(job, "title", "") or "")
    seniority = getattr(job, "seniority", None)
    sen_val = getattr(seniority, "value", seniority)
    title_bits = [b for b in (title, str(sen_val) if sen_val else "") if b]
    if title_bits:
        variants.append(" ".join(title_bits))

    skills = _skill_names(getattr(job, "must_skills", None)) + _skill_names(
        getattr(job, "nice_skills", None)
    )
    if skills:
        variants.append(", ".join(skills))

    base = (base_text or "").strip()
    return [v for v in variants if v.strip() and v.strip() != base]


def build_job_text_v2(job) -> str:
    """PII-free, labeled canonical job document."""
    sections: list[str] = []

    title = _strip_ref_noise(getattr(job, "title", "") or "")
    if title:
        sections.append(f"[TITLE] {title}")

    seniority = getattr(job, "seniority", None)
    if seniority is not None:
        val = getattr(seniority, "value", seniority)
        sections.append(f"[SENIORITY] {val}")

    for label, attr in (("SUBCATEGORY", "subcategory"), ("INDUSTRY", "industry")):
        v = getattr(job, attr, None)
        if v:
            sections.append(f"[{label}] {_clean(str(v))}")

    must = _skill_names(getattr(job, "must_skills", None))
    if must:
        sections.append("[MUST_SKILLS] " + ", ".join(must))
    nice = _skill_names(getattr(job, "nice_skills", None))
    if nice:
        sections.append("[NICE_SKILLS] " + ", ".join(nice))

    desc = getattr(job, "description", None)
    if desc:
        sections.append("[DESCRIPTION] " + _clean(desc)[:1200])
    reqs = getattr(job, "requirements", None)
    if reqs:
        sections.append("[REQUIREMENTS] " + _clean(reqs)[:1200])

    # Champion — przez `champion_view`, więc czytany niezależnie od tego, czy
    # oferta ma kształt sprzed czy po przebudowie szablonu (09.2026).
    #
    # `embedding_parts`, NIE `narrative_parts`: dla profilu w starym kształcie
    # zwraca dokładnie te same trzy pola co dotąd, więc tekst kanoniczny 949
    # istniejących ofert nie drgnie i indeks nie wymaga przeliczenia.
    for part in champion_view.embedding_parts(job):
        sections.append(f"[CHAMPION] {_clean(part)[:800]}")

    return "\n".join(sections)
