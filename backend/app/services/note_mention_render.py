"""Resolve legacy Traffit `$$user_NN$$` mention tokens to readable @Name labels.

Traffit stored @mentions inside note bodies as `$$user_<traffit_user_id>$$`.
NEXUS imported those notes verbatim (Faza A), so the raw token leaks into the
UI — a recruiter sees `$$user_40$$` instead of "Klaudia Uliasz". The Traffit
user id maps to a NEXUS user via `users.external_id` (str of the Traffit id,
set during import).

This helper batch-resolves the tokens **for display only**. The stored
`Note.content` is left untouched so editing preserves the original token and
HTML/JSON wrapper — we surface the resolved text in a separate
`content_rendered` field on the timeline payload.

Native NEXUS mentions use the `@email` syntax (parsed by `mention_parser.py`)
and are NOT touched here — only the legacy `$$user_NN$$` shape.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

# Legacy Traffit mention marker: `$$user_<traffit_user_id>$$`.
_TRAFFIT_USER_TOKEN_RE = re.compile(r"\$\$user_(\d+)\$\$")

# Defensive: a stray `"` / `\` / `{` / `}` in a name would corrupt the
# surrounding JSON/HTML note wrapper once it reaches the client. Real names
# never contain these (verified against the live dataset), but we strip them
# so a future bad import can't break rendering.
_UNSAFE_NAME_CHARS_RE = re.compile(r'["\\{}]')

# Shown when a token references a Traffit user that was never imported into
# NEXUS (≈5 pruned accounts). Still readable, and never leaks the raw token.
_FALLBACK_LABEL = "użytkownik"


def collect_traffit_user_ids(contents: Iterable[str | None]) -> set[str]:
    """Extract every distinct Traffit user id referenced by `$$user_NN$$`
    tokens across the given note bodies."""
    ids: set[str] = set()
    for content in contents:
        if content:
            ids.update(_TRAFFIT_USER_TOKEN_RE.findall(content))
    return ids


async def build_traffit_user_label_map(
    db: AsyncSession, traffit_ids: set[str]
) -> dict[str, str]:
    """Map Traffit user id (str) → display name, via `users.external_id`.

    Includes inactive users (many mentioned colleagues are disabled Traffit
    imports). Unresolved ids are simply absent — `render_traffit_mentions`
    falls back to a generic label for them.
    """
    if not traffit_ids:
        return {}
    rows = await db.execute(
        select(User.external_id, User.name).where(User.external_id.in_(traffit_ids))
    )
    label_map: dict[str, str] = {}
    for external_id, name in rows.all():
        if external_id is None:
            continue
        label = _UNSAFE_NAME_CHARS_RE.sub("", (name or "").strip())
        label_map[str(external_id)] = label or _FALLBACK_LABEL
    return label_map


def render_traffit_mentions(
    content: str | None, label_map: dict[str, str]
) -> str | None:
    """Replace `$$user_NN$$` tokens with `@Name`.

    Unknown ids render as `@użytkownik` so the raw token never reaches the UI.
    Content without any token is returned unchanged.
    """
    if not content:
        return content

    def _replace(match: re.Match[str]) -> str:
        label = label_map.get(match.group(1), _FALLBACK_LABEL)
        return f"@{label}"

    return _TRAFFIT_USER_TOKEN_RE.sub(_replace, content)


# Etykieta ZAPISYWANA w treści notatki (import i naprawa z 29.09.2026) dla
# tokenu, którego użytkownika nie ma już w Traffit (`/users/`). Inna niż
# `_FALLBACK_LABEL` z renderu: tam nie wiadomo, czy konto istnieje (render
# pyta tylko o `users.external_id`, który SSO nadpisuje), tu Traffit
# potwierdził, że go nie ma.
STORED_UNKNOWN_LABEL = "(były użytkownik)"


def clean_mention_label(name: str | None) -> str:
    """Nazwa bez znaków, które rozbiłyby opakowanie JSON/HTML notatki."""
    return _UNSAFE_NAME_CHARS_RE.sub("", (name or "").strip())


def has_traffit_mentions(content: str | None) -> bool:
    return bool(content) and _TRAFFIT_USER_TOKEN_RE.search(content) is not None


def rewrite_traffit_mentions(
    content: str | None, label_map: dict[str, str]
) -> str | None:
    """Zamień `$$user_NN$$` na `@Imię Nazwisko` w ZAPISYWANEJ treści.

    ``label_map`` = identyfikator użytkownika Traffita → nazwa z Traffit
    `/users/` (nie z `users.external_id`, który logowanie SSO nadpisuje).
    Pusta mapa = nic nie zmieniamy: bez listy użytkowników nie da się
    odróżnić konta usuniętego od niepobranej listy, a zamiana jest
    nieodwracalna w samej notatce (oryginał zostaje w `activities.details`).
    """
    if not content or not label_map:
        return content

    def _replace(match: re.Match[str]) -> str:
        label = label_map.get(match.group(1)) or STORED_UNKNOWN_LABEL
        return f"@{label}"

    return _TRAFFIT_USER_TOKEN_RE.sub(_replace, content)


__all__ = [
    "STORED_UNKNOWN_LABEL",
    "build_traffit_user_label_map",
    "clean_mention_label",
    "collect_traffit_user_ids",
    "has_traffit_mentions",
    "render_traffit_mentions",
    "rewrite_traffit_mentions",
]
