"""Publiczny link CV niesie stały arkusz szablonu, nigdy CSS z treści.

``sanitize_cv_html`` wycina ``<head>``/``<style>`` (CSS z treści to droga
wstrzyknięcia), więc ``/cv/{token}``, ``/cv/i/{token}`` i dokumenty pakietu
pokazywały klientowi CV bez arkusza szablonu (audyt responsywności 23.09, W4).
Arkusz ma pochodzić z kodu renderera szablonu, treść CV dalej przechodzi
sanitizer. Testy bez bazy: ``pytest --noconftest``.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from starlette.requests import Request
from starlette.responses import Response

from app.services.cv_generator_b2b.html_export import render_interactive_html
from app.services.html_sanitizer import sanitize_cv_html

_PAYLOAD = {
    "language": "pl",
    "candidate_name": "Jan",
    "position": "Senior Python Developer",
    "why_points": ["8 lat w Pythonie"],
    "skills": [{"label": "Języki", "content": "Python, Go"}],
    "experience": [
        {
            "position": "Backend Developer",
            "company": "Firma",
            "dates": "2020 – 2024",
            "responsibilities": ["API w FastAPI"],
            "technologies": ["Python"],
        }
    ],
}


def _styles(html: str) -> list[str]:
    return re.findall(r"<style[^>]*>(.*?)</style>", html, re.S | re.I)


# Stary szablon „CV firmowe” wycofano w generatorze v3 razem z rendererem —
# w bazie zostały zapisane w nim CV etapów. To jest dokument wygenerowany
# ostatnią wersją renderera (fikcyjny kandydat Jan Kowalski).
_LEGACY_BRANDED_HTML = (
    Path(__file__).parent / "fixtures" / "cv" / "legacy_branded_stage_cv.html"
).read_text(encoding="utf-8")


async def _public_stage_cv(html: str) -> dict:
    from app.api import public_share as api

    row = SimpleNamespace(
        token="v2$revoke",
        token_sha256="digest",
        revoked=False,
        expires_at=None,
        candidate_stage_cv_id=5,
        document_version_id=None,
        package_versions=None,
    )
    csv = SimpleNamespace(
        id=5,
        candidate_id=1,
        job_id=2,
        branded_status="finalized",
        branded_draft_html=html,
    )
    db = SimpleNamespace(
        scalar=AsyncMock(
            side_effect=[
                row,
                csv,
                SimpleNamespace(name="Jan"),
                SimpleNamespace(title="Dev"),
            ]
        ),
        execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: 1)),
        add=Mock(),
        commit=AsyncMock(),
    )
    return await api.get_public_cv.__wrapped__(
        token="raw",
        request=Request({"type": "http", "method": "GET", "path": "/"}),
        response=Response(),
        db=db,
    )


async def test_public_stage_cv_keeps_branded_template_stylesheet():
    html = _LEGACY_BRANDED_HTML
    template_css = _styles(html)[0]

    served = (await _public_stage_cv(html))["cv_html"]

    assert _styles(served) == [template_css]
    assert "Jan Kowalski" in served
    # Siatka szablonu (.cv-body: sidebar + treść) wymaga kolumny bocznej.
    assert '<aside class="cv-sidebar">' in served


async def test_public_generated_document_keeps_document_stylesheet():
    stored = sanitize_cv_html(render_interactive_html(_PAYLOAD, [], document_only=True))
    template_css = _styles(render_interactive_html(_PAYLOAD, []))[0]

    served = (await _public_stage_cv(stored))["cv_html"]

    styles = _styles(served)
    assert len(styles) == 1
    assert template_css in styles[0]
    assert served.count('<article class="cv">') == 1
    assert "Backend Developer" in served


async def test_edited_markup_without_template_classes_gets_document_frame():
    # Edytor (Tiptap) gubi <article class="cv"> i klasy, zostawia data-cv-section.
    edited = (
        "<h1>Senior Python Developer</h1><hr>"
        '<h2 data-cv-section="skills">Umiejętności</h2><p>Python</p>'
    )

    served = (await _public_stage_cv(edited))["cv_html"]

    assert '<article class="cv"><h1>Senior Python Developer</h1>' in served
    assert len(_styles(served)) == 1


async def test_css_from_cv_content_never_reaches_public_document():
    hostile = (
        "<style>body{background:url(https://evil.example/leak)}</style>"
        '<p style="position:fixed;background:url(https://evil.example/x)">CV</p>'
        "<p>&lt;/style&gt;&lt;script&gt;alert(1)&lt;/script&gt;</p>"
        '<div class="cv-wrapper"><style>.cv-body{display:none}</style></div>'
    )

    served = (await _public_stage_cv(hostile))["cv_html"]

    assert "evil.example" not in served
    assert ".cv-body{display:none}" not in served.replace(" ", "")
    assert "<script" not in served.lower()
    assert served.lower().count("<style") == 1
    assert served.lower().count("</style>") == 1


async def test_empty_cv_stays_empty():
    assert (await _public_stage_cv(""))["cv_html"] == ""
