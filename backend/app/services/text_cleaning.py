"""Shared rich-text → plain-text cleaning for candidate-list previews.

Notes in NEXUS are authored through the Tiptap editor and stored either as HTML
(legacy Word/Outlook paste — ``<p class="MsoNormal">…</p>`` with ``&nbsp;``
entities) or as a serialized Tiptap JSON document. Anywhere we surface that text
in the candidates list — the „Ostatnia notatka" column and the match-snippet
shown under a row — it must be flattened to clean, readable text: no tags, no
HTML entities, no ``$$user_NN$$`` mention markers.

Pure-Python, no DB I/O, no truncation (callers truncate to taste), so it is safe
to import from both the API layer (`api/candidates.py`) and the snippet service
(`services/candidate_snippets.py`).
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
# Frontend stores @-mentions inside Tiptap notes as `$$user_NN$$` markers
# (resolved client-side against the users cache). For a plain-text preview we
# strip them down to a "@user" placeholder so the recruiter sees text, not
# internal ids.
_USER_MENTION_RE = re.compile(r"\$\$user_\d+\$\$")
_HTML_ENTITIES = {
    "&nbsp;": " ",
    "&amp;": "&",
    "&lt;": "<",
    "&gt;": ">",
    "&quot;": '"',
    "&#39;": "'",
    "&apos;": "'",
}


def _extract_tiptap_text(node: Any) -> str:
    """Walk Tiptap doc JSON and concatenate all `text` nodes. Tiptap shapes:
    ``{"type":"doc","content":[{"type":"paragraph","content":[{"type":"text",
    "text":"..."}]}]}``. Some richer notes wrap as ``{"content": [...]}`` or
    ``{"content": "raw text"}`` — we handle both. Anything we can't parse falls
    back to the raw string.
    """
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return " ".join(_extract_tiptap_text(item) for item in node if item is not None)
    if isinstance(node, dict):
        # Leaf text node
        if node.get("type") == "text" and isinstance(node.get("text"), str):
            return node["text"]
        # Container — walk `content` recursively (Tiptap convention)
        if "content" in node:
            return _extract_tiptap_text(node["content"])
        # Fallback: join any string-valued field — defensive for legacy shapes.
        return " ".join(v for v in node.values() if isinstance(v, str) and v.strip())
    return ""


def clean_rich_text(raw: Optional[str]) -> str:
    """Flatten a note/free-text value to clean plain text.

    Unwraps a serialized Tiptap JSON document, strips HTML tags, decodes the
    common HTML entities, replaces `$$user_NN$$` mention markers, and collapses
    whitespace runs. Does **not** truncate — callers cap length to taste.
    Returns ``""`` for falsy input.
    """
    if not raw:
        return ""
    raw = raw.strip()
    # JSON-shaped (Tiptap doc) — `{"type":"doc",…}` or `{"content":…}`.
    if raw.startswith("{") or raw.startswith("["):
        try:
            text_only = _extract_tiptap_text(json.loads(raw))
        except (ValueError, TypeError):
            text_only = raw
    else:
        text_only = raw
    text_only = _HTML_TAG_RE.sub(" ", text_only)
    text_only = _USER_MENTION_RE.sub("@user", text_only)
    for entity, replacement in _HTML_ENTITIES.items():
        text_only = text_only.replace(entity, replacement)
    return _WHITESPACE_RE.sub(" ", text_only).strip()


def flatten_json_text(value: Any) -> str:
    """Recursively collect every string/number leaf of a JSONB value into a
    single space-joined string.

    Used for the candidate's ``experience`` / ``skills`` / ``tags`` / ``education``
    / ``languages`` JSONB columns when building a search snippet: unlike
    ``json.dumps`` it drops the structural punctuation (braces, quotes, keys)
    that made the raw fragment unreadable, while still surfacing **all** nested
    text so a matched search term is never hidden inside a nested object.
    Returns ``""`` for ``None``/empty.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        # bool is an int subclass — guard so we don't emit "True"/"False" noise.
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        return " ".join(flatten_json_text(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(flatten_json_text(item) for item in value)
    return str(value)
