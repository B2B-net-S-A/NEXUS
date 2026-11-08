"""E-mail kandydata z CV (``services.cv_parser.parse_cv``) albo z panelu JJIT."""

from __future__ import annotations

import re

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def is_valid_email(email: str | None) -> bool:
    return bool(email) and len(email) <= 254 and bool(EMAIL_RE.match(email))


def preferred_email(parsed: dict, *, panel_email: str) -> str:
    """Adres z CV, gdy prawidłowy; inaczej adres z panelu."""
    email = (parsed.get("email") or "").strip()
    return email if is_valid_email(email) else panel_email.strip()
