"""Canonical HTTP read/write classification for section RBAC and impersonation.

Most reads use GET/HEAD/OPTIONS. A small, audited set of endpoints uses POST
because its query or preview payload is too structured for query parameters.
Those exceptions are expressed as exact Starlette route templates so a sibling
mutation can never inherit read semantics merely by sharing a URL prefix.
"""

from __future__ import annotations

from starlette.routing import compile_path


SAFE_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

READ_ONLY_POST_ROUTE_TEMPLATES: tuple[str, ...] = (
    "/api/search/candidates/scores",
    "/api/search/candidates/diagnostics",
    "/api/search/candidates",
    "/api/search/semantic",
    "/api/talent-radar/search",
    "/api/talent-radar/parse-champion",
    "/api/jobs/champion-profile/historical-matches",
    "/api/jobs/request-history/preview",
    "/api/jobs/{job_id}/classify-cc",
    "/api/jobs/{job_id}/generate-criteria-preview",
    "/api/recommendations/cv-upload-preview",
    "/api/prep-kit/generate",
    "/api/email-templates/{template_id}/preview",
    "/api/emails/preview",
    "/api/candidates/check-duplicates",
    "/api/candidates/export",
    "/api/candidates/bulk-cv-download",
)

_READ_ONLY_POST_ROUTE_PATTERNS = tuple(
    compile_path(template)[0] for template in READ_ONLY_POST_ROUTE_TEMPLATES
)


def is_read_only_post_path(path: str) -> bool:
    """Return True only when ``path`` exactly matches an audited template."""

    return any(
        pattern.match(path) is not None for pattern in _READ_ONLY_POST_ROUTE_PATTERNS
    )


def is_read_only_http_request(method: str, path: str) -> bool:
    """Classify a request identically for section levels and impersonation."""

    normalized_method = method.upper()
    return normalized_method in SAFE_READ_METHODS or (
        normalized_method == "POST" and is_read_only_post_path(path)
    )
