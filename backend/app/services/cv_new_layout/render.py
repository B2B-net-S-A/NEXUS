"""Składanie HTML i PDF układu „Nowe CV”.

PDF robi WeasyPrint z fetcherem, który wpuszcza wyłącznie `data:` i pliki
z `app/assets` (kroje, znak). Klauzula RODO przychodzi jako HTML od wołającego,
a WeasyPrint domyślnie pobiera `http(s)://` i `file://` po stronie serwera —
bez tego fetchera byłoby to SSRF i odczyt plików (wzór: `autenti/pdf_renderer`).
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional

from app.services.cv_new_layout.context import Ctx, build_context
from app.services.cv_new_layout.document import NewCvDocument
from app.services.cv_new_layout.labels import consent_heading, default_rodo_clause
from app.services.cv_new_layout.page1 import page1
from app.services.cv_new_layout.roles import rest_pages
from app.services.cv_new_layout.styles import stylesheet
from app.services.cv_new_layout.text import esc

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LayoutSettings:
    """Ustawienia strony 1: stopień pisma, najwięcej pozycji w kategorii umiejętności,
    odstęp między sekcjami i luz w środku sekcji (wolne miejsce strony podzielone)."""

    font_pt: float = 10.0
    skill_cap: Optional[int] = None
    block_gap_mm: float = 0.0
    inner_mm: float = 0.0  # luz w środku sekcji (odstępy zdań, wierszy, osi)


_IMAGE_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


def sniff_image_mime(data: bytes) -> Optional[str]:
    for magic, mime in _IMAGE_SIGNATURES:
        if data.startswith(magic):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def consent_block(doc: NewCvDocument) -> str:
    """Zrzut zgody kandydata (wymóg PKO BP) w zwykłym przepływie, przed klauzulą.
    Nieczytelny plik = CV bez zrzutu, nie wywrócony render (jak w pliku Word)."""
    data = doc.consent_image
    if not data:
        return ""
    mime = sniff_image_mime(data)
    if mime is None:
        logger.warning(
            "cv_new_layout: zrzut zgody pominięty — nierozpoznany format (%s)",
            doc.consent_image_mime,
        )
        return ""
    uri = f"data:{mime};base64,{base64.b64encode(data).decode()}"
    return f"<div class='consent'><h4>{esc(consent_heading(doc.language))}</h4><img src='{uri}' alt=''></div>"


def rodo_block(doc: NewCvDocument) -> str:
    clause = doc.rodo_clause_html
    if clause is None or not clause.strip():
        clause = esc(default_rodo_clause(doc.language))
    return f"<div class='rodo'>{clause}</div>"


def build_html(ctx: Ctx, settings: LayoutSettings, *, page1_only: bool = False) -> str:
    doc = ctx.doc
    p1, truncated, certs_hidden = page1(ctx, settings.skill_cap)
    body = p1
    if not page1_only:
        body += f"<div class='rest'>{rest_pages(ctx, truncated, certs_hidden)}{consent_block(doc)}{rodo_block(doc)}</div>"
    title = (
        f"{ctx.t['doc_title']} – {doc.position}" if doc.position else ctx.t["doc_title"]
    )
    css = stylesheet(
        font_pt=settings.font_pt,
        footer=ctx.t["footer"],
        block_gap_mm=settings.block_gap_mm,
        inner_mm=settings.inner_mm,
    )
    return (
        f"<!doctype html><html lang='{doc.language}'><head><meta charset='utf-8'><title>{esc(title)}</title>"
        f"<style>{css}</style></head><body>{body}</body></html>"
    )


def render_new_cv_html(
    doc: NewCvDocument,
    *,
    settings: Optional[LayoutSettings] = None,
    today: Optional[date] = None,
) -> str:
    """Cały dokument jako HTML do WeasyPrint. Bez `settings` = pismo 10 pt, pełne
    umiejętności, sekcje bez rozsunięcia; ustawienia dopasowane do strony 1 daje
    `fit_new_cv_page1(doc).settings`."""
    return build_html(build_context(doc, today), settings or LayoutSettings())


def html_to_document(html: str):
    """Układ WeasyPrint (strony) z fetcherem wpuszczającym tylko zasoby z repo."""
    from weasyprint import HTML  # leniwie: biblioteki natywne tylko tam, gdzie PDF
    from weasyprint.urls import URLFetcher

    from app.services.cv_new_layout.assets import is_local_asset

    class _AssetsOnlyFetcher(URLFetcher):
        """`data:` i pliki z `app/assets`; reszta odrzucona (WeasyPrint pomija zasób)."""

        def fetch(self, url: str, headers: Optional[dict] = None):
            if url.startswith("data:") or is_local_asset(url):
                return super().fetch(url, headers)
            raise ValueError(f"blocked resource in CV PDF: {url[:64]!r}")

    return HTML(string=html, url_fetcher=_AssetsOnlyFetcher()).render()


def html_to_pdf(html: str) -> bytes:
    pdf = html_to_document(html).write_pdf()
    if pdf is None:
        raise RuntimeError("WeasyPrint returned no PDF bytes")
    return pdf
