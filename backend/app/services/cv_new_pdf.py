"""PDF układu „Nowe CV” z treści edytora (22.11.2026).

Ta sama treść co plik Word: HTML edytora (po sanitizerze i ze stałą klauzulą
RODO), zrzut zgody zamrożony na CV i dodatki strony 1. Zapis generatora
(`render_payload`) uzupełnia tylko to, czego HTML nie niesie (branża
stanowiska, słowa do pogrubienia). Render WeasyPrint idzie w wątku, najwyżej
dwa naraz — kosztuje ok. 1–3 s procesora.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Optional

from starlette.concurrency import run_in_threadpool

from app.services.cv_layout import compose_page1_why
from app.services.cv_new_content import cv_json_from_editor_html

MSG_RENDER_FAILED = (
    "Nie udało się przygotować PDF w układzie „Nowe CV”. "
    "Pobierz klasyczny plik Word albo spróbuj ponownie."
)
_SLOTS = asyncio.Semaphore(2)


class NewCvPdfError(RuntimeError):
    """Render nowego CV się nie udał — wołający oddaje 503 z polskim komunikatem."""


@dataclass(frozen=True)
class NewCvPdf:
    pdf: bytes
    fits: bool
    font_pt: float
    steps: tuple[str, ...]
    unmapped_sections: tuple[str, ...]

    def headers(self) -> dict[str, str]:
        """Nagłówki dla podglądu: „strona 1 mieści się · pismo 10 pt”.

        Przeglądarka widzi je dzięki liście `expose_headers` w `main.py`.
        """
        return {
            "X-CV-Layout": "new",
            "X-CV-Page1-Fits": "1" if self.fits else "0",
            "X-CV-Page1-Font": f"{self.font_pt:g}",
            "X-CV-Unmapped-Sections": str(len(self.unmapped_sections)),
        }


def _image_mime(data: Optional[bytes]) -> Optional[str]:
    if not data:
        return None
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    return None


def _render(
    content_html: str,
    *,
    language: str,
    blind: bool,
    fallback: Optional[dict[str, Any]],
    extras: Optional[dict],
    consent: Optional[bytes],
) -> NewCvPdf:
    from app.services.cv_new_layout import (
        NewCvDocument,
        render_new_cv_pdf_with_report,
    )

    content = cv_json_from_editor_html(
        content_html, language=language, blind=blind, fallback=fallback
    )
    mime = _image_mime(consent)
    document = NewCvDocument.from_cv_json(
        content.cv_json,
        why=compose_page1_why(content.cv_json.get("why_points") or [], extras),
        rodo_clause_html=content.rodo_clause or None,
        consent_image=consent if mime else None,
        consent_image_mime=mime,
    )
    pdf, report = render_new_cv_pdf_with_report(document)
    return NewCvPdf(
        pdf=pdf,
        fits=bool(report.fits),
        font_pt=float(report.font_pt),
        steps=tuple(report.steps),
        unmapped_sections=content.unmapped_sections,
    )


async def render_new_cv_pdf(
    content_html: str,
    *,
    language: Optional[str],
    template: Optional[str],
    fallback: Optional[dict[str, Any]],
    extras: Optional[dict],
    consent: Optional[bytes],
) -> NewCvPdf:
    """PDF nowego CV; awaria renderu = ``NewCvPdfError`` (ślad w logu serwera)."""
    import logging

    async with _SLOTS:
        try:
            return await run_in_threadpool(
                _render,
                content_html,
                language="en" if language == "en" else "pl",
                blind=template == "blind",
                fallback=fallback,
                extras=extras,
                consent=consent,
            )
        except Exception as error:  # noqa: BLE001 — każdy błąd renderu to 503
            logging.getLogger(__name__).exception("new CV PDF render failed")
            raise NewCvPdfError(MSG_RENDER_FAILED) from error


# ── CV, które idzie dalej: Cpro, panel klienta, API v1 (22.11.2026) ─────────


async def _fallback(db, generated_id: Optional[int]) -> Optional[dict[str, Any]]:
    """Zapis generatora (sama kolumna) — uzupełnia branżę i słowa do pogrubienia."""
    if not generated_id:
        return None
    from sqlalchemy import select

    from app.models.cv_generated_document import CvGeneratedDocument

    payload = await db.scalar(
        select(CvGeneratedDocument.render_payload).where(
            CvGeneratedDocument.id == generated_id
        )
    )
    return payload if isinstance(payload, dict) else None


async def approved_version_pdf(db, version: Any) -> NewCvPdf:
    """Zatwierdzona wersja jako „Nowe CV”: z jej zamrożonej treści, języka,
    szablonu, dodatków strony 1 i zrzutu zgody — to samo, co zatwierdził DL.

    Przed renderem kończy transakcję żądania (render trwa sekundy; bez blokad
    i połączenia z bazą). Awaria = ``NewCvPdfError``, wołający oddaje 503.
    """
    fallback = await _fallback(db, getattr(version, "generated_document_id", None))
    await db.commit()
    return await render_new_cv_pdf(
        version.content_html or "",
        language=version.language,
        template=version.template,
        fallback=fallback,
        extras=version.page1_extras,
        consent=version.consent_content,
    )


async def stage_draft_pdf(db, csv: Any) -> NewCvPdf:
    """Szkic CV etapu jako „Nowe CV” — z zapisanej treści edytora."""
    fallback = await _fallback(db, getattr(csv, "generated_document_id", None))
    await db.commit()
    return await render_new_cv_pdf(
        csv.branded_draft_html or "",
        language=csv.branded_language,
        template=csv.branded_template,
        fallback=fallback,
        extras=csv.page1_extras,
        consent=csv.branded_consent_content,
    )
