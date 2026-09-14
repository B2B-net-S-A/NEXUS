"""Unit tests for app.core.http_headers.content_disposition_attachment.

Pins the latin-1 safety contract for download filenames. A raw Polish upload
name ("Życiorys_Małgorzaty.pdf") in a Content-Disposition header used to crash
ASGI header serialization with UnicodeEncodeError → bare HTTP 500. The helper
must always produce a latin-1-encodable value while preserving the original
name via the RFC 5987 filename* token.
"""

from __future__ import annotations

from urllib.parse import unquote

from starlette.datastructures import Headers, MutableHeaders

from app.core.http_headers import (
    apply_credentialed_cache_policy,
    content_disposition,
    content_disposition_attachment,
)


def test_polish_filename_is_latin1_safe():
    value = content_disposition_attachment("Życiorys_Małgorzaty.pdf")
    # The exact failure mode before the fix:
    value.encode("latin-1")  # must not raise
    assert value.startswith("attachment;")
    assert "filename*=UTF-8''" in value


def test_filename_star_roundtrips_to_original():
    original = "Rafał_Pogorzelski_CV.pdf"
    value = content_disposition_attachment(original)
    token = value.split("filename*=UTF-8''", 1)[1]
    assert unquote(token) == original


def test_ascii_fallback_present_and_clean():
    value = content_disposition_attachment("Żółw ćma.pdf")
    # Legacy filename="" token: ASCII-only, no stray quotes/backslashes.
    legacy = value.split('filename="', 1)[1].split('"', 1)[0]
    legacy.encode("ascii")  # must not raise
    assert '"' not in legacy and "\\" not in legacy


def test_quote_injection_is_neutralised():
    # A filename trying to break out of the quoted string must not inject
    # extra header directives into the legacy token.
    value = content_disposition_attachment('evil".pdf')
    legacy = value.split('filename="', 1)[1].split('"', 1)[0]
    assert '"' not in legacy
    value.encode("latin-1")


def test_empty_filename_falls_back():
    value = content_disposition_attachment("")
    assert 'filename="download"' in value
    value.encode("latin-1")


def test_all_nonascii_name_still_safe():
    # Name with no ASCII chars at all → legacy token falls back, filename* keeps it.
    value = content_disposition_attachment("Żółć.pdf")
    value.encode("latin-1")
    token = value.split("filename*=UTF-8''", 1)[1]
    assert unquote(token) == "Żółć.pdf"


def test_inline_disposition_uses_inline_prefix():
    value = content_disposition("Żółć.pdf", "inline")
    value.encode("latin-1")  # must not raise
    assert value.startswith("inline;")
    assert "attachment" not in value
    assert "filename*=UTF-8''" in value


def test_default_disposition_is_attachment():
    value = content_disposition("plain.pdf")
    assert value.startswith("attachment;")


def test_attachment_alias_matches_content_disposition():
    # Backwards-compat alias must produce identical output for "attachment".
    assert content_disposition_attachment("Żółć.pdf") == content_disposition(
        "Żółć.pdf", "attachment"
    )


# ── UAT M07-B01: odpowiedzi na żądania z poświadczeniami poza cache ────────


def _apply(request: dict, response: dict | None = None) -> MutableHeaders:
    out = MutableHeaders(headers=response or {})
    apply_credentialed_cache_policy(Headers(headers=request), out)
    return out


def test_file_response_to_bearer_request_is_not_cacheable():
    headers = _apply(
        {"authorization": "Bearer x"},
        {"etag": '"abc"', "last-modified": "Sun, 13 Sep 2026 10:00:00 GMT"},
    )
    assert headers["cache-control"] == "private, no-store"
    vary = {part.strip().lower() for part in headers["vary"].split(",")}
    assert {"authorization", "x-api-key", "x-impersonate-user-id"} <= vary


def test_endpoint_own_cache_policy_is_kept_but_keyed_per_credential():
    headers = _apply(
        {"authorization": "Bearer x"},
        {"cache-control": "private, max-age=60", "vary": "Origin"},
    )
    assert headers["cache-control"] == "private, max-age=60"
    parts = [part.strip() for part in headers["vary"].split(",")]
    assert parts[0] == "Origin"
    assert "Authorization" in parts


def test_api_key_and_impersonation_count_as_credentials():
    assert _apply({"x-api-key": "k"})["cache-control"] == "private, no-store"
    assert (
        _apply({"x-impersonate-user-id": "5"})["cache-control"] == "private, no-store"
    )


def test_anonymous_request_is_left_alone():
    headers = _apply({}, {"cache-control": "public, max-age=300"})
    assert headers["cache-control"] == "public, max-age=300"
    assert "vary" not in headers


def test_vary_star_is_not_rewritten():
    headers = _apply({"authorization": "Bearer x"}, {"vary": "*"})
    assert headers["vary"] == "*"
