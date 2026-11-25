"""PDF układu „Nowe CV” z treści edytora (22.11.2026).

Ta sama treść co plik Word: HTML edytora (po sanitizerze i ze stałą klauzulą
RODO), zrzut zgody zamrożony na CV i dodatki strony 1. Zapis generatora
(`render_payload`) uzupełnia tylko to, czego HTML nie niesie (branża
stanowiska, słowa do pogrubienia). Render WeasyPrint idzie w wątku, najwyżej
dwa naraz — kosztuje ok. 1–3 s procesora.
"""

from __future__ import annotations

import asyncio
import html
from dataclasses import dataclass
from typing import Any, Optional

from starlette.concurrency import run_in_threadpool

from app.services.cv_layout import compose_page1_why
from app.services.cv_new_layout.highlight import choice_from_extras
from app.services.cv_new_content import cv_json_from_editor_html
from app.services.cv_page1_result_checks import rechecked_extras

MSG_RENDER_FAILED = (
    "Nie udało się przygotować PDF w układzie „Nowe CV”. "
    "Pobierz klasyczny plik Word albo spróbuj ponownie."
)
MSG_CONSENT_UNREADABLE = (
    "Nie udało się odczytać zrzutu zgody RODO dołączonego do CV, więc PDF "
    "w układzie „Nowe CV” nie powstał. Wgraj zrzut ponownie (PNG, JPEG albo WEBP)."
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


@dataclass(frozen=True)
class CvFacts:
    """Fakty spoza treści edytora (Artur 23.11.2026): miasto kandydata obok języków,
    wymagania MUST z Profilu Championa (certyfikat z MUST stoi pierwszy w Edukacji) i nazwy
    klienta rekrutacji (wyróżnik „Doświadczenie w …”, Artur 25.11.2026)."""

    location: str = ""
    must_have: tuple[str, ...] = ()
    # nazwa, nazwa wyświetlana i pełna nazwa klienta rekrutacji — wyróżnik „praca u klienta”
    client_names: tuple[str, ...] = ()


def must_names(champion_profile: Any) -> tuple[str, ...]:
    """Nazwy wymagań MUST z `champion_profile.stack.must` (słowniki albo napisy)."""
    if not isinstance(champion_profile, dict):
        return ()
    stack = champion_profile.get("stack")
    items = stack.get("must") if isinstance(stack, dict) else None
    names = []
    for item in items if isinstance(items, list) else []:
        name = item.get("name") if isinstance(item, dict) else item
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return tuple(names)


async def cv_facts(db, candidate_id: Optional[int], job_id: Optional[int]) -> CvFacts:
    """Czytane przed końcem transakcji żądania, render idzie potem bez bazy."""
    from sqlalchemy import select

    from app.models.candidate import Candidate
    from app.models.job import Job

    location = (
        await db.scalar(select(Candidate.location).where(Candidate.id == candidate_id))
        if candidate_id
        else None
    )
    from app.models.client import Client

    row = (
        (
            await db.execute(
                select(
                    Job.champion_profile,
                    Client.name,
                    Client.display_name,
                    Client.legal_name,
                )
                .outerjoin(Client, Client.id == Job.client_id)
                .where(Job.id == job_id)
            )
        ).first()
        if job_id
        else None
    )
    profile = row[0] if row else None
    names = tuple(
        dict.fromkeys(n.strip() for n in (row[1:] if row else ()) if n and n.strip())
    )
    return CvFacts((location or "").strip(), must_names(profile), names)


def _consent_image(data: Optional[bytes]) -> tuple[Optional[bytes], Optional[str]]:
    """Zrzut zgody gotowy do wklejenia: PNG i JPEG bez zmian, reszta (WEBP,
    który przyjmuje upload) przepisana przez PIL na PNG.

    Bajty, których nie da się odczytać, to ``NewCvPdfError``, nie PDF bez zgody:
    bramka pobrania (``cv_consent_gate``) widzi zapisany obraz i przepuszcza,
    więc cichy pominięty zrzut dawał klientowi CV bez wymaganej zgody.
    """
    if not data:
        return None, None
    if data.startswith(b"\x89PNG"):
        return data, "image/png"
    if data.startswith(b"\xff\xd8"):
        return data, "image/jpeg"
    from io import BytesIO

    from PIL import Image

    try:
        with Image.open(BytesIO(data)) as image:
            image.load()
            out = BytesIO()
            image.save(out, format="PNG")
    except Exception as error:  # noqa: BLE001 — każdy nieczytelny obraz to odmowa
        raise NewCvPdfError(MSG_CONSENT_UNREADABLE) from error
    return out.getvalue(), "image/png"


def _render(
    content_html: str,
    *,
    language: str,
    blind: bool,
    fallback: Optional[dict[str, Any]],
    extras: Optional[dict],
    consent: Optional[bytes],
    facts: Optional[CvFacts] = None,
) -> NewCvPdf:
    from app.services.cv_new_layout import (
        NewCvDocument,
        render_new_cv_pdf_with_report,
    )

    content = cv_json_from_editor_html(
        content_html, language=language, blind=blind, fallback=fallback
    )
    consent, mime = _consent_image(consent)
    facts = facts or CvFacts()
    # Wynik sprawdzony na innej treści CV — kontrola jeszcze raz na bieżących rolach.
    extras = rechecked_extras(extras, content_html, content.cv_json, blind=blind)
    document = NewCvDocument.from_cv_json(
        {
            **content.cv_json,
            "candidate_location": facts.location,
            "must_have": list(facts.must_have),
            "client_names": list(facts.client_names),
        },
        why=compose_page1_why(content.cv_json.get("why_points") or [], extras),
        highlight=choice_from_extras(extras),
        # Renderer wstawia klauzulę jako HTML — tekst z edytora idzie escapowany.
        rodo_clause_html=html.escape(content.rodo_clause) or None,
        consent_image=consent,
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
    facts: Optional[CvFacts] = None,
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
                facts=facts,
            )
        except NewCvPdfError:
            raise
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
    facts = CvFacts()
    if getattr(version, "candidate_stage_cv_id", None):
        from app.models.candidate_stage_cv import CandidateStageCV

        csv = await db.get(CandidateStageCV, version.candidate_stage_cv_id)
        if csv is not None:
            facts = await cv_facts(db, csv.candidate_id, csv.job_id)
    await db.commit()
    return await render_new_cv_pdf(
        version.content_html or "",
        language=version.language,
        template=version.template,
        fallback=fallback,
        extras=version.page1_extras,
        consent=version.consent_content,
        facts=facts,
    )


async def stage_draft_pdf(db, csv: Any) -> NewCvPdf:
    """Szkic CV etapu jako „Nowe CV” — z zapisanej treści edytora."""
    fallback = await _fallback(db, getattr(csv, "generated_document_id", None))
    facts = await cv_facts(
        db, getattr(csv, "candidate_id", None), getattr(csv, "job_id", None)
    )
    await db.commit()
    return await render_new_cv_pdf(
        csv.branded_draft_html or "",
        language=csv.branded_language,
        template=csv.branded_template,
        fallback=fallback,
        extras=csv.page1_extras,
        consent=csv.branded_consent_content,
        facts=facts,
    )
