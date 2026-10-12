"""Text projection for source review of sanitized editor HTML."""

import re
from functools import lru_cache

from lxml import html

from app.services.cv_generator_b2b.factual_verification import verify_final_cv
from app.services.cv_rodo_clause import is_rodo_text

_BLOCKS = {
    "p",
    "div",
    "section",
    "article",
    "h1",
    "h2",
    "h3",
    "h4",
    "li",
    "tr",
    "blockquote",
    "pre",
}
_LABELS = {
    "doświadczenie",
    "doświadczenie zawodowe",
    "experience",
    "work experience",
    "education",
    "wykształcenie",
    "skills",
    "umiejętności",
    "certifications",
    "certyfikaty",
    "languages",
    "języki",
    "podsumowanie",
    "summary",
    "dlaczego ten kandydat",
    "why this candidate",
}


class EditorReviewInputError(ValueError):
    pass


# 2 (12.10.2026): recenzent dostaje twierdzenia jawnie. W wersji 1 wszystkie
# linie szły jako `why_points`, a recenzent v4 nie traktuje tej sekcji jako
# twierdzeń — kontrola po edycji kończyła się błędem protokołu bez wywołania
# modelu (produkcja 27.09–12.10.2026: 12 z 12 zatwierdzeń).
EDITOR_REVIEW_VERSION = 2

# Akapity szablonu, nie treść kandydata: klauzula zgody i etykieta obowiązków.
_TEMPLATE_MARKERS = {"rodo", "duties_label"}
# Znaczniki sekcji narracyjnej („dlaczego ten kandydat”) na nagłówku h2.
_NARRATIVE_MARKERS = {"why_points", "summary"}


def _title(text: str) -> str:
    return " ".join(text.split()).casefold().rstrip(":?").strip()


@lru_cache(maxsize=1)
def _template_texts() -> tuple[frozenset[str], frozenset[str], tuple[str, ...]]:
    # Leniwie, jak `cv_rodo_clause`: `docx_renderer` ciągnie python-docx.
    from app.services.cv_generator_b2b.docx_renderer import TRANSLATIONS

    narrative = {
        "summary",
        "podsumowanie",
        "dlaczego ten kandydat",
        "why this candidate",
    }
    narrative.update(_title(t["why"]) for t in TRANSLATIONS.values())
    duties = {_title(t["responsibilities"]) for t in TRANSLATIONS.values()}
    considered = tuple(
        " ".join(t["considered_for"].split()).casefold() for t in TRANSLATIONS.values()
    )
    return frozenset(narrative), frozenset(duties), considered


def _is_template_line(text: str) -> bool:
    """Linia, którą dokłada szablon: nie ma jej czym potwierdzić w źródłach."""
    _, duties, considered = _template_texts()
    return (
        is_rodo_text(text)
        or _title(text) in duties
        or " ".join(text.split()).casefold().startswith(considered)
    )


def _review_lines(content_html: str) -> list[tuple[str, bool]]:
    """Linie dokumentu w kolejności, każda z flagą „to twierdzenie do sprawdzenia”.

    Twierdzeniem nie jest: sekcja narracyjna (kontrola v4 jej nie recenzuje —
    argumentacja składa fakty z innych pól), tytuł sekcji, klauzula zgody,
    etykieta obowiązków i linia „Rozważany na stanowisko”. Zostają w dokumencie
    jako kontekst dla recenzenta.
    """
    if len(content_html.encode()) > 2_000_000:
        raise EditorReviewInputError("CV jest zbyt duże do kontroli treści.")
    root = html.fragment_fromstring(content_html, create_parent="div")
    if root.xpath(".//img | .//svg | .//object | .//iframe"):
        raise EditorReviewInputError(
            "Kontrola treści wymaga osobnego sprawdzenia obrazów w edytowanym CV."
        )
    narrative_titles = _template_texts()[0]
    rows: list[tuple[str, bool]] = []
    current: list[tuple[str, bool]] = []
    state = {"narrative": False}

    def end_line() -> None:
        text = re.sub(r"\s+", " ", "".join(part for part, _ in current)).strip()
        if text:
            # Kontekstem jest tylko linia w całości z kontekstu — mieszana
            # zostaje twierdzeniem, żeby niczego nie ukryć przed kontrolą.
            rows.append((text, all(ctx for part, ctx in current if part.strip())))
        current.clear()

    def emit(text: str, context: bool) -> None:
        context = context or state["narrative"]
        for piece in text.splitlines(keepends=True):
            body = "".join(piece.splitlines())
            current.append((body, context))
            if body != piece:
                end_line()

    def walk(node, context: bool) -> None:
        element = isinstance(node.tag, str)
        tag = node.tag.lower() if element else ""
        if tag in {"script", "style"}:
            return
        if tag == "h2":
            marker = node.get("data-cv-section")
            state["narrative"] = (
                marker in _NARRATIVE_MARKERS
                or _title("".join(node.itertext())) in narrative_titles
            )
            context = True
        elif element and (
            node.get("data-cv-section") in _TEMPLATE_MARKERS
            or "rodo" in (node.get("class") or "").split()
        ):
            context = True
        if tag in _BLOCKS or tag == "br":
            end_line()
        if node.text:
            emit(node.text, context)
        for child in node:
            walk(child, context)
            if child.tail:
                emit(child.tail, context)
            if child.tag in {"td", "th"}:
                emit(" | ", context)
        if tag in _BLOCKS:
            end_line()

    walk(root, False)
    end_line()
    lines = [
        (text, not (context or _is_template_line(text)))
        for text, context in rows
        if text.casefold().rstrip(":") not in _LABELS
    ]
    if not lines or len(lines) > 1000:
        raise EditorReviewInputError("Nie można objąć całego CV kontrolą treści.")
    return lines


def editor_claims(content_html: str) -> list[str]:
    """Preserve paragraph order, negation and inline text; never silently truncate."""
    return [text for text, _ in _review_lines(content_html)]


def verify_editor_content(
    content_html: str,
    *,
    cv_text: str,
    screening_notes: str,
    identity: str,
    request_id: str,
) -> dict:
    # The complete ordered document is supplied alongside each batch, so dates,
    # companies and adjacent role headings remain available to the reviewer.
    # Twierdzenia podajemy jawnie: sam dokument stoi pod `why_points`, a tę
    # sekcję recenzent pomija, więc bez `claims` nie sprawdziłby niczego.
    lines = _review_lines(content_html)
    return verify_final_cv(
        {"why_points": [text for text, _ in lines]},
        cv_text=cv_text,
        screening_notes=screening_notes,
        identity=identity,
        request_id=request_id,
        claims={
            f"/why_points/{index}": text
            for index, (text, claim) in enumerate(lines)
            if claim
        },
    )
