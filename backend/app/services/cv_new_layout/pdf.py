"""Publiczne wejście PDF: dopasowanie strony 1 i render całego CV."""

from __future__ import annotations

from datetime import date
from typing import Optional

from app.services.cv_new_layout.context import build_context
from app.services.cv_new_layout.document import NewCvDocument
from app.services.cv_new_layout.fit import FitReport, fit_page1
from app.services.cv_new_layout.render import build_html, html_to_pdf


def fit_new_cv_page1(doc: NewCvDocument, *, today: Optional[date] = None) -> FitReport:
    """Same kroki dopasowania strony 1 (bez całego PDF); `report.settings` daje
    ten sam układ w `render_new_cv_html`."""
    return fit_page1(build_context(doc, today))


def render_new_cv_pdf_with_report(
    doc: NewCvDocument, *, today: Optional[date] = None
) -> tuple[bytes, FitReport]:
    ctx = build_context(doc, today)
    report = fit_page1(ctx)
    return html_to_pdf(build_html(ctx, report.settings)), report


def render_new_cv_pdf(doc: NewCvDocument, *, today: Optional[date] = None) -> bytes:
    return render_new_cv_pdf_with_report(doc, today=today)[0]
