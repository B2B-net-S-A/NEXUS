"""Kanoniczny adres profilu LinkedIn kandydata.

Jedna forma ``https://linkedin.com/in/<slug>`` dla deduplikacji, kwarantanny
tożsamości, wtyczki LinkedIn i zapisu przez API integracji. Do 28.11.2026
funkcja leżała w ``app.services.proxycurl.client``; integracja Proxycurl
została usunięta (serwis zamknięty 4.07.2025).
"""

import re
from typing import Optional
from urllib.parse import urlparse

_LINKEDIN_SLUG_RE = re.compile(r"^[\w\-%._]+$", re.IGNORECASE)


def normalize_linkedin_url(url: Optional[str]) -> Optional[str]:
    """Canonicalize a LinkedIn profile URL.

    Accepts common user variants ("linkedin.com/in/jane-doe",
    "https://pl.linkedin.com/in/jane-doe/?foo=bar"). Returns canonical
    "https://linkedin.com/in/<slug>" or None if the input is malformed.
    """

    if not url:
        return None
    raw = url.strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = "https://" + raw
    try:
        parsed = urlparse(raw)
    except ValueError:
        return None

    host = (parsed.netloc or "").lower()
    # Strip regional prefix (pl., www., etc.) — kanoniczna forma linkedin.com.
    if not host.endswith("linkedin.com"):
        return None

    path = parsed.path or ""
    # Match "/in/<slug>" or "/in/<slug>/". Reject other path shapes
    # (company pages, job listings, etc.).
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2 or parts[0].lower() != "in":
        return None
    slug = parts[1]
    if not _LINKEDIN_SLUG_RE.match(slug):
        return None
    return f"https://linkedin.com/in/{slug}"
