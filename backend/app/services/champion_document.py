"""Lossless table reading for the six-section Champion form; no AI guesses."""

from __future__ import annotations

import io
import re
import unicodedata
from copy import deepcopy


def folded(value: str) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", value.lower().replace("ł", "l"))
        if not unicodedata.combining(c)
    )


def meaningful(value) -> bool:
    text = folded(str(value or "")).strip(" :.-–—\n\t")
    return bool(text) and not re.fullmatch(
        r"(?:brak|nie dotyczy|do ustalenia|n/?a|tbd|rr rr|rrrr-mm-dd|pytanie\s*\d*|idealna odpowiedz|deal[ -]?breaker|sugerowane odpowiedzi|[._…]+)",
        text,
    )


def document_text(data: bytes) -> str:
    from docx import Document
    from docx.text.paragraph import Paragraph

    def blocks(container):
        for block in container.iter_inner_content():
            if isinstance(block, Paragraph):
                if block.text.strip():
                    yield block.text
            else:
                seen = set()
                for row in block.rows:
                    cells = []
                    for cell in row.cells:
                        if cell._tc in seen:
                            continue
                        seen.add(cell._tc)
                        value = "\n".join(blocks(cell)).strip()
                        if value:
                            cells.append(value)
                    if cells:
                        yield " | ".join(cells)

    return "\n".join(blocks(Document(io.BytesIO(data))))


def table_profile(data: bytes) -> dict | None:
    """Recognize the form by labels, never by file name or example values."""
    from docx import Document
    from docx.text.paragraph import Paragraph

    doc = Document(io.BytesIO(data))
    profile = {
        key: {}
        for key in ("basics", "search", "stack", "experience", "project", "client")
    }
    profile["screening_questions"] = []
    raw = {}
    document_context = {}
    section = ""
    found = set()
    labels = (
        ("nazwa roli", "basics.role_name"),
        ("minimum lat doswiadczenia", "basics.seniority_min_years"),
        ("maks. stawka kandydata", "basics.rate_value"),
        ("tryb pracy", "basics.work_mode"),
        ("dni w biurze", "basics.onsite_days_per_week"),
        ("lokalizacja biura", "basics.candidate_location_pref"),
        ("jezyk pracy", "basics.language"),
        ("start", "basics.start_date"),
        ("deadline", "basics.deadline"),
        ("dlugosc kontraktu", "basics.contract_length"),
        ("kluczowe slowa", "search.keywords"),
        ("firmy docelowe", "search.target_companies"),
        ("kogo odrzucamy", "search.disqualifiers"),
        ("must-have:", "stack.must"),
        ("nice-to-have:", "stack.nice"),
        ("obowiazki na stanowisku", "project.responsibilities"),
        ("co przekona", "client.selling_points"),
        ("insight od", "client.consultant_insight"),
        ("historyczne pytania", "client.historical_questions"),
        # Wzór v5 (09.2026): sekcja 4 i 8.
        ("dziedzina", "experience.domains"),
        ("certyfikaty", "experience.certifications"),
        ("regulacje", "experience.regulations"),
        ("od klienta", "insights.client"),
    )

    def put(path, value):
        found.add(path)
        raw[path] = value
        group, key = path.split(".")
        if group == "experience":
            value = experience_from_text(value, with_years=key == "domains")
        if group == "insights":
            if meaningful(value):
                profile.setdefault("insights", []).append(
                    {
                        "id": f"new-doc-{key}",
                        "source": key,
                        "topic": "other",
                        "audience": "team",
                        "text": value.strip(),
                        "origin": "document",
                    }
                )
            return
        profile[group][key] = value

    for block in doc.iter_inner_content():
        if isinstance(block, Paragraph):
            heading = folded(block.text).strip()
            # „O projekcie” to sekcja 4 we wzorze v4 i 5 we wzorze v5 (09.2026).
            if re.match(r"[45][.)]\s*o projekcie", heading):
                section = "project"
            elif re.match(r"[2-8][.)]", heading):
                section = heading[0]
            elif heading.startswith("uwagi / standardy"):
                section = "standards"
            continue
        rows = []
        seen_cells = set()
        for row in block.rows:
            cells, row_cells = [], set()
            for cell in row.cells:
                if cell._tc in row_cells:
                    continue
                row_cells.add(cell._tc)
                cells.append("" if cell._tc in seen_cells else cell.text.strip())
                seen_cells.add(cell._tc)
            rows.append(cells)
        if rows and any("pytania od delivery" in folded(c) for c in rows[0]):
            found.add("screening_questions")
            for cells in rows[1:]:
                if len(cells) < 2 or not meaningful(cells[0]):
                    continue
                question = re.sub(r"^Pytanie\s*\d+\s*:\s*", "", cells[0], flags=re.I)
                answer = re.sub(r"^Idealna odpowiedź\s*:\s*", "", cells[1], flags=re.I)
                parts = re.split(
                    r"deal[ -]?breaker\s*:", answer, maxsplit=1, flags=re.I
                )
                profile["screening_questions"].append(
                    {
                        "id": f"q{len(profile['screening_questions']) + 1}",
                        "question": question,
                        "ideal_answer": parts[0].strip(),
                        "deal_breaker": parts[1].strip() if len(parts) > 1 else "",
                    }
                )
            continue
        if section == "project" and len(rows) == 1 and len(rows[0]) == 1:
            put("project.about", rows[0][0])
            continue
        for cells in rows:
            for i in range(0, len(cells) - 1, 2):
                label = folded(cells[i])
                for prefix, key in (
                    ("klient (", "client_name"),
                    ("delivery lead", "delivery_lead"),
                    ("data i wersja", "profile_revision"),
                    ("rozmowy zrodlowe", "source_conversations"),
                    ("za prep", "prep_owner"),
                    ("ostatnia zmiana", "last_change"),
                ):
                    if label.startswith(prefix) and meaningful(cells[i + 1]):
                        document_context[key] = cells[i + 1]
                if label.startswith("uwagi / plan"):
                    put("search.notes", cells[i + 1])
                elif label.startswith("uwagi / niuanse"):
                    put("stack.notes", cells[i + 1])
                else:
                    for prefix, path in labels:
                        if label.startswith(prefix):
                            put(path, cells[i + 1])
                            break
    if not {"stack.must", "stack.nice", "screening_questions"}.issubset(found):
        return None
    footer = " ".join(
        p.text for section in doc.sections for p in section.footer.paragraphs
    )
    version = re.search(r"wzór\s+v([\d.]+)", footer, re.I)
    return {
        "profile": deepcopy(profile),
        "raw_fields": raw,
        "document_context": document_context,
        "template_version": version.group(1) if version else None,
    }


_NICE_MARK = re.compile(r"\(\s*mile[^)]*\)", re.I)
# „lata” przed „lat”: alternatywa bierze pierwsze trafienie, a „lat” zostawiłoby
# z „2 lata” samo „a” w nazwie dziedziny.
_YEARS_MARK = re.compile(
    r"(?:min\.?|minimum)\s*(\d{1,2})\s*(?:lata|lat|roku|rok|l\.)", re.I
)


def experience_from_text(value: str, *, with_years: bool) -> list[dict]:
    """Komórka sekcji 4 wzoru v5 → pozycje: „płatności (min. 2 lata), e-commerce (mile)”.

    „(mile)” oznacza mile widziane, „min. N lat” — lata (tylko dziedzina).
    Znaczniki są wycinane z nazwy; reszta normalizacji jest w
    `champion_intake.normalize_experience_items`.
    """
    items: list[dict] = []
    for part in re.split(r"[\n;,]+", value or ""):
        text = part.strip()
        if not meaningful(text):
            continue
        level = "nice" if _NICE_MARK.search(text) else "must"
        years = _YEARS_MARK.search(text) if with_years else None
        name = _NICE_MARK.sub("", text)
        if with_years:
            name = _YEARS_MARK.sub("", name)
        name = re.sub(r"\(\s*\)", "", name)
        name = re.sub(r"\s+", " ", name).strip(" -–—:()")
        if name:
            items.append(
                {
                    "name": name,
                    "level": level,
                    "min_years": int(years.group(1)) if years else None,
                }
            )
    return items


def _split_skills(raw: str) -> list[str]:
    r"""Split MUST-HAVE / NICE-TO-HAVE blob into discrete tech names.

    Splits on newline, and on comma/semicolon only OUTSIDE parentheses, so a
    chip like ``Java (Spring, Hibernate)`` or ``WCAG 2.1/2.2 (AA, AAA)`` stays
    whole instead of shattering at the inner comma. Trims bullets/whitespace,
    drops empty and pure-bullet fragments.

    (Deliberately diverges from the JS 1:1 port ``text.split(/[\n,;]/)`` in
    ``lib/cv-shared.ts``, which broke parenthesised list items.)
    """
    if not raw:
        return []
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in raw:
        if ch in "([{":
            depth += 1
            buf.append(ch)
        elif ch in ")]}":
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch == "\n" or (ch in ",;" and depth == 0):
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    out: list[str] = []
    for p in parts:
        s = re.sub(r"^\s*(?:[-•●▪–—*]+|\d+[.)])\s*", "", p).strip()
        if not s or re.fullmatch(r"[-•●▪–—*\s]+", s):
            continue
        out.append(s)
    return out
