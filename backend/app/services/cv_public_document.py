"""Dokument CV pod publicznym linkiem: treść po sanitizerze + arkusz szablonu.

``sanitize_cv_html`` wycina ``<head>`` i ``<style>`` — CSS z treści CV to
droga wstrzyknięcia (wygląd podszyty pod inną firmę, zasoby z obcych adresów).
Bez arkusza klient otwierający ``/cv/{token}`` albo ``/cv/i/{token}`` widział
jednak CV bez stylów szablonu. Arkusz dokładamy tutaj wyłącznie z kodu: to
``<style>`` z renderera szablonu wywołanego bez danych kandydata, więc zmiana
szablonu (np. blok ``@media``) przechodzi też do linków, a nic z treści CV nie
trafia do ``<style>``.
"""

from __future__ import annotations

import re
from functools import lru_cache
from types import SimpleNamespace

from app.services.html_sanitizer import sanitize_cv_html

_STYLE = re.compile(r"<style>(.*?)</style>", re.S)

# Edytor (Tiptap) gubi klasy szablonu i zostawia tylko ``data-cv-section``;
# te reguły dają poprawionej treści wygląd sekcji z ``.job-co``/``.lbl``/``.rodo``.
_EDITED_MARKUP_CSS = """
  .cv p[data-cv-section="role"]:not([class]) { font-size: 14.5px; margin-top: 12px; }
  .cv p[data-cv-section="employer"]:not([class]) { font-size: 13px; color: #808080; margin: 1px 0 4px; }
  .cv p[data-cv-section="duties_label"]:not([class]),
  .cv p[data-cv-section="technologies"]:not([class]) { font-size: 12px; font-weight: 600; margin-top: 5px; }
  .cv p[data-cv-section="rodo"]:not([class]) { color: #9a9a9a; margin-top: 26px;
    border-top: 1px solid #eee; padding-top: 10px; text-align: justify; }
"""


def _template_style(document: str) -> str:
    return _STYLE.search(document).group(1)


@lru_cache(maxsize=None)
def _document_css() -> str:
    """Arkusz dokumentu z Generatora B2B (``<article class="cv">``)."""
    from app.services.cv_generator_b2b.html_export import render_interactive_html

    return _template_style(render_interactive_html({}, [])) + _EDITED_MARKUP_CSS


@lru_cache(maxsize=None)
def _branded_css() -> str:
    """Arkusz starego szablonu brandowanego CV etapu (``.cv-wrapper``)."""
    from app.services.cv_html_renderer import _generate_cv_html

    blank = SimpleNamespace(
        name="",
        lastname="",
        email=None,
        phone=None,
        location=None,
        linkedin=None,
        ai_summary="",
        skills=[],
        experience=[],
        education=[],
        languages=[],
        competence_category=None,
    )
    return _template_style(_generate_cv_html(blank, "standard", "pl"))


def public_cv_document(html: str | None) -> str:
    """Pełny dokument HTML do ``srcDoc`` publicznej ramki CV ("" dla pustego CV)."""
    body = sanitize_cv_html(html)
    if not body.strip():
        return ""
    if 'class="cv-wrapper"' in body:
        css = _branded_css()
    else:
        css = _document_css()
        if 'class="cv"' not in body:
            body = f'<article class="cv">{body}</article>'
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<style>{css}</style></head><body>{body}</body></html>"
    )
