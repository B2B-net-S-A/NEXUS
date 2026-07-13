"""Security boundary for persisted branded-CV HTML documents."""

from __future__ import annotations

import hashlib
import hmac
import re

from app.services.m365.html_sanitize import sanitize_html


GENERATED_CV_MARKER = "<!-- nexus-generated-cv-v1 -->"

# SHA-256 of the fixed stylesheet emitted by ``cv_html_renderer``.  The marker
# alone is not a trust boundary: a legacy stored payload could contain the same
# public comment.  We therefore retain CSS only when it is byte-for-byte the
# reviewed server stylesheet; every body still passes through Bleach.
TRUSTED_GENERATED_CV_STYLE_SHA256 = (
    "cbfb615e5b265b56b848d4930ac433097ab8e8e55b8d0689c052589d4d1aece8"
)

_STYLE_RE = re.compile(r"<style\b[^>]*>(.*?)</style\s*>", re.IGNORECASE | re.DOTALL)
_BODY_RE = re.compile(r"<body\b[^>]*>(.*?)</body\s*>", re.IGNORECASE | re.DOTALL)


def sanitize_branded_cv_html(raw: str) -> str:
    """Sanitize a branded CV and preserve only our generated static CSS.

    Manually edited HTML is sanitized as an ordinary fragment.  A freshly
    generated CV carries a marker and an exact reviewed stylesheet digest, so
    its fixed CSS can be retained while the body still passes through the
    closed allowlist.  Manual saves pass through ``sanitize_html`` before
    persistence, which removes comments and ``style``; legacy rows cannot gain
    trust from the public marker alone.
    """
    if not raw:
        return ""
    if GENERATED_CV_MARKER in raw:
        style_match = _STYLE_RE.search(raw)
        body_match = _BODY_RE.search(raw)
        style_digest = (
            hashlib.sha256(style_match.group(1).encode()).hexdigest()
            if style_match
            else ""
        )
        if (
            style_match
            and body_match
            and hmac.compare_digest(
                style_digest,
                TRUSTED_GENERATED_CV_STYLE_SHA256,
            )
        ):
            safe_body = sanitize_html(body_match.group(1))
            return f"<style>{style_match.group(1)}</style>{safe_body}"
    # Bleach removes a disallowed ``<style>`` tag but intentionally preserves
    # its text.  Strip complete style blocks first so a forged marker cannot
    # smuggle attacker CSS into the returned document even as inert content.
    return sanitize_html(_STYLE_RE.sub("", raw))
