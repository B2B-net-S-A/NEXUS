"""Text projection for source review of sanitized editor HTML."""

import re
from lxml import html

from app.services.cv_generator_b2b.factual_verification import verify_final_cv

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


EDITOR_REVIEW_VERSION = 1


def editor_claims(content_html: str) -> list[str]:
    """Preserve paragraph order, negation and inline text; never silently truncate."""
    if len(content_html.encode()) > 2_000_000:
        raise EditorReviewInputError("CV jest zbyt duże do kontroli treści.")
    root = html.fragment_fromstring(content_html, create_parent="div")
    if root.xpath(".//img | .//svg | .//object | .//iframe"):
        raise EditorReviewInputError(
            "Kontrola treści wymaga osobnego sprawdzenia obrazów w edytowanym CV."
        )
    parts = []

    def walk(node):
        tag = node.tag.lower() if isinstance(node.tag, str) else ""
        if tag in {"script", "style"}:
            return
        if tag in _BLOCKS or tag == "br":
            parts.append("\n")
        if node.text:
            parts.append(node.text)
        for child in node:
            walk(child)
            if child.tail:
                parts.append(child.tail)
            if child.tag in {"td", "th"}:
                parts.append(" | ")
        if tag in _BLOCKS:
            parts.append("\n")

    walk(root)
    lines = [re.sub(r"\s+", " ", line).strip() for line in "".join(parts).splitlines()]
    lines = [
        line for line in lines if line and line.casefold().rstrip(":") not in _LABELS
    ]
    if not lines or len(lines) > 1000:
        raise EditorReviewInputError("Nie można objąć całego CV kontrolą treści.")
    return lines


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
    return verify_final_cv(
        {"why_points": editor_claims(content_html)},
        cv_text=cv_text,
        screening_notes=screening_notes,
        identity=identity,
        request_id=request_id,
    )
