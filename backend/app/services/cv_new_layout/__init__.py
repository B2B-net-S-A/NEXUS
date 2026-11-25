"""Układ „Nowe CV” (makieta Artura z 20–22.11.2026) jako HTML i PDF (WeasyPrint).

Strona 1 = podsumowanie (tytuł z językami, 3 zdania „Dlaczego nasz kandydat”,
oś kariery, indeks umiejętności, szkoła i 3 certyfikaty z ikonami), zawsze na
jednej kartce; od strony 2 stanowiska jako formularze, pełne listy, zrzut zgody
i klauzula RODO na samym końcu. Bez bazy i sieci: wszystko przychodzi
w `NewCvDocument`.
"""

from app.services.cv_new_layout.document import NewCvDocument, Role, School, SkillGroup
from app.services.cv_new_layout.fit import FitReport
from app.services.cv_new_layout.pdf import (
    fit_new_cv_page1,
    render_new_cv_pdf,
    render_new_cv_pdf_with_report,
)
from app.services.cv_new_layout.render import LayoutSettings, render_new_cv_html

__all__ = [
    "FitReport",
    "LayoutSettings",
    "NewCvDocument",
    "Role",
    "School",
    "SkillGroup",
    "fit_new_cv_page1",
    "render_new_cv_html",
    "render_new_cv_pdf",
    "render_new_cv_pdf_with_report",
]
