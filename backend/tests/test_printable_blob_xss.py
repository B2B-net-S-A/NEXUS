"""Dokumenty „do druku” otwierane jako blob nie wykonują wstrzykniętego HTML.

Audyt bezpieczeństwa 24.09.2026: imię i nazwisko kandydata (publiczny
formularz kariery, bez walidacji znaków) szło bez escapowania do ``<title>``
wydruku CV etapu i szkicu umowy. Front otwiera te dokumenty jako ``blob:``
pod originem aplikacji — nagłówek CSP z trasy tam nie działa — więc
``</title><img onerror>`` wykonywał skrypt z dostępem do tokena w
``localStorage`` rekrutera, który kliknął „Drukuj”.
"""

from __future__ import annotations

import pytest

PAYLOAD = "</title><img src=x onerror=alert(1)><script>alert(2)</script>"


def _head_before_title(html: str) -> str:
    return html[: html.index("<title>")]


def _wrappers():
    from app.api.candidate_stage_cv import _wrap_printable_cv
    from app.api.contracts import _wrap_printable
    from app.services.candidate_stage_cv_service import wrap_printable_cv

    return [
        ("contract", lambda body, label: _wrap_printable(body, 7, label)),
        ("stage_cv_api", lambda body, label: _wrap_printable_cv(body, 7, label)),
        ("stage_cv_service", lambda body, label: wrap_printable_cv(body, 7, label)),
    ]


@pytest.mark.parametrize("name", ["contract", "stage_cv_api", "stage_cv_service"])
def test_candidate_label_is_escaped_in_title(name: str) -> None:
    wrap = dict(_wrappers())[name]
    html = wrap("<p>treść</p>", f"Jan {PAYLOAD}")

    assert "<img" not in html
    assert "onerror=alert(1)>" not in html.replace("&lt;img", "")
    assert "&lt;/title&gt;&lt;img" in html


@pytest.mark.parametrize("name", ["contract", "stage_cv_api", "stage_cv_service"])
def test_csp_meta_is_the_first_thing_in_head(name: str) -> None:
    from app.core.printable_html import AUTOPRINT_HASH, AUTOPRINT_JS

    wrap = dict(_wrappers())[name]
    html = wrap("<p>treść</p>", "Jan Kowalski")
    head = _head_before_title(html)

    assert 'http-equiv="Content-Security-Policy"' in head
    assert "default-src 'none'" in head
    assert f"'{AUTOPRINT_HASH}'" in head
    # Nasz auto-print dalej działa: jego bajty zgadzają się ze skrótem.
    assert f"<script>{AUTOPRINT_JS}</script>" in html


@pytest.mark.parametrize("name", ["stage_cv_api", "stage_cv_service"])
def test_stage_cv_body_goes_through_the_allowlist(name: str) -> None:
    wrap = dict(_wrappers())[name]
    html = wrap(f"<p>ok</p>{PAYLOAD}", "Jan Kowalski")
    body = html[html.index("<body>") :]

    assert "<script>alert(2)" not in body
    assert "onerror" not in body
    assert "<p>ok</p>" in body


def test_contract_route_header_policy_equals_the_document_policy() -> None:
    from app.api.contracts import _CONTRACT_PREVIEW_CSP
    from app.core.printable_html import PRINTABLE_CSP

    assert _CONTRACT_PREVIEW_CSP == PRINTABLE_CSP
