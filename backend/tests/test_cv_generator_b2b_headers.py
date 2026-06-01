"""Regression tests for CV Generator B2B response headers.

HTTP headers must be latin-1 (ISO-8859-1) encodable. Polish candidate names
(``Rafał``, ``Małgorzata``…) and Polish Claude warnings contain code points
outside latin-1, which previously crashed response serialization with
``UnicodeEncodeError`` and surfaced to the recruiter as a bare HTTP 500
(generic "Generowanie nie powiodło się." toast).

These tests pin the contract: every header value the endpoint emits must be
latin-1 safe, and the encoded values must round-trip back to the originals on
the client (percent-decoding for the name, JSON parsing for the warnings).
"""

from __future__ import annotations

import json
from urllib.parse import unquote

from app.api.cv_generator_b2b import _build_docx_response


def _assert_all_headers_latin1(response) -> None:
    for key, value in response.headers.items():
        # Raises UnicodeEncodeError if a value is not latin-1 encodable — the
        # exact failure the ASGI server hit before the fix.
        value.encode("latin-1")
        key.encode("latin-1")


def test_polish_candidate_name_header_is_latin1_safe():
    response = _build_docx_response(
        docx_bytes=b"PK\x03\x04 fake docx",
        filename="B2B_Java_Developer_Rafal_Pogorzelski.docx",
        candidate_name="Rafał Pogorzelski",
        warnings=[],
        processing_time_ms=1234,
    )

    _assert_all_headers_latin1(response)

    # Percent-encoded on the wire, decodes back to the original Polish name.
    encoded = response.headers["X-Generator-Candidate-Name"]
    assert unquote(encoded) == "Rafał Pogorzelski"


def test_polish_warnings_header_is_latin1_safe_and_roundtrips():
    warnings = [
        "Brak technologii MUST-HAVE: Kubernetes",
        "Kandydat nie potwierdził doświadczenia z Ansible (zażółć gęślą jaźń)",
    ]
    response = _build_docx_response(
        docx_bytes=b"PK\x03\x04 fake docx",
        filename="B2B_kandydat.docx",
        candidate_name="Małgorzata Żółć",
        warnings=warnings,
        processing_time_ms=42,
    )

    _assert_all_headers_latin1(response)

    # ensure_ascii=True emits \uXXXX escapes; JSON.parse on the client (json.loads
    # here) decodes them back to the original Polish strings.
    assert json.loads(response.headers["X-Generator-Warnings"]) == warnings


def test_ascii_name_is_unchanged_enough_to_read():
    response = _build_docx_response(
        docx_bytes=b"PK\x03\x04 fake docx",
        filename="B2B_Java_Developer_Anna_Kowalska.docx",
        candidate_name="Anna Kowalska",
        warnings=[],
        processing_time_ms=0,
    )

    _assert_all_headers_latin1(response)
    assert unquote(response.headers["X-Generator-Candidate-Name"]) == "Anna Kowalska"
    assert (
        response.headers["Content-Disposition"]
        == 'attachment; filename="B2B_Java_Developer_Anna_Kowalska.docx"'
    )
