"""Enforce frozen blind-CV identity exclusions independently of factual truth."""

import re
import unicodedata
from lxml import html
from fastapi import HTTPException


def _normalized(text):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text).casefold()).strip()


def check_editor_privacy(content_html: str, metadata: dict | None):
    metadata = metadata or {}
    if metadata.get("blind_identity_guard") is not True:
        return
    root = html.fragment_fromstring(content_html, create_parent="div")
    text = _normalized(root.text_content())
    for term in metadata.get("blind_identity_terms", []):
        needle = _normalized(term)
        if needle and re.search(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", text):
            # Do not include the forbidden identity in client-visible errors/logs.
            raise HTTPException(
                422,
                "CV anonimowe zawiera dane identyfikujące osobę lub firmę. Usuń je przed zatwierdzeniem.",
            )
