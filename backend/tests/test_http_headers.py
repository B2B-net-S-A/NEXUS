"""Unit tests for app.core.http_headers.content_disposition_attachment.

Pins the latin-1 safety contract for download filenames. A raw Polish upload
name ("Życiorys_Małgorzaty.pdf") in a Content-Disposition header used to crash
ASGI header serialization with UnicodeEncodeError → bare HTTP 500. The helper
must always produce a latin-1-encodable value while preserving the original
name via the RFC 5987 filename* token.
"""

from __future__ import annotations

from urllib.parse import unquote

from app.core.http_headers import content_disposition, content_disposition_attachment


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
