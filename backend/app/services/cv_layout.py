"""Układ CV: klasyczny Word albo „Nowe CV” w PDF (decyzje Artura z 22.11.2026).

- Jedna treść, dwa układy: oba czytają HTML edytora, więc przełączenie nie
  generuje CV od nowa i nie kasuje poprawek.
- Układ to jedno ustawienie CV (`candidate_stage_cvs.cv_layout`), widoczne
  w generatorze, karcie „CV do klienta” i edytorze. Po „CV wysłane” jest
  zablokowane, tak jak podmiana CV.
- Domyślnie klasyczny; „Nowe CV” domyślnie tylko u klienta z regułą
  `client_cv_rules.cv_layout = 'new'` (start na 2 tygodnie, potem decyzja na
  liczbach).
- Word to zawsze układ klasyczny. Nowy układ istnieje tylko jako PDF.
- Cała funkcja za flagą `CV_NEW_LAYOUT_ENABLED`: wyłączona = PDF zawsze
  z pliku Word, a interfejs nie pokazuje wyboru.
"""

from __future__ import annotations

import re
from typing import Any, Literal, Optional

from app.core.config import settings
from app.services.cv_layout_schema import LAYOUTS

Layout = Literal["classic", "new"]
LAYOUT_CLASSIC: Layout = "classic"
LAYOUT_NEW: Layout = "new"

MSG_DISABLED = "Układ „Nowe CV” jest wyłączony."
MSG_LOCKED = "CV jest już u klienta — układu nie zmienisz."
MSG_NO_CV = "Najpierw wygeneruj CV do klienta."


def enabled() -> bool:
    return bool(settings.CV_NEW_LAYOUT_ENABLED)


def normalized(value: Any) -> Layout:
    return LAYOUT_NEW if value == LAYOUT_NEW else LAYOUT_CLASSIC


def effective(value: Any) -> Layout:
    """Układ, który faktycznie obowiązuje: „Nowe CV” tylko przy włączonej fladze."""
    return LAYOUT_NEW if enabled() and value == LAYOUT_NEW else LAYOUT_CLASSIC


def is_new(value: Any) -> bool:
    """Czy plik do klienta to PDF „Nowego CV” (zapisany układ + flaga)."""
    return effective(value) == LAYOUT_NEW


_DOCUMENT_EXTENSION = re.compile(r"\.(?:docx|pdf)$", re.IGNORECASE)


def filename_for(name: Optional[str], layout: Any) -> Optional[str]:
    """Nazwa pliku do klienta w układzie CV: Nowe CV — ten sam wzór z ``.pdf``.

    Zapisana nazwa (`branded_docx_filename`, `docx_filename`) zostaje ``.docx``,
    bo z niej idzie pobranie pliku Word — ten jest zawsze klasyczny.
    """
    if not name or not is_new(layout):
        return name
    return f"{_DOCUMENT_EXTENSION.sub('', name)}.pdf"


def wanted(requested_layout: Optional[str], stored: Any) -> Layout:
    """Układ pliku: jawny ``?layout=`` (miniatura drugiego układu, „Word (klasyczne)”)
    albo zapisany. Przy wyłączonej fladze zawsze klasyczny — jak dotąd."""
    if not enabled():
        return LAYOUT_CLASSIC
    if requested_layout in LAYOUTS:
        return normalized(requested_layout)
    return normalized(stored)


def requested(value: Optional[str]) -> Optional[Layout]:
    """Układ z żądania (generator, przełącznik); ``None`` = bez zmiany."""
    if value is None or not enabled():
        return None
    if value not in LAYOUTS:
        raise ValueError(f"Nieznany układ CV: {value}")
    return normalized(value)


def rule_layout(rule: Any) -> Layout:
    """Domyślny układ z reguły klienta (zatwierdzonej albo centralnej)."""
    return normalized(getattr(rule, "cv_layout", None))


async def default_for_client(db, client_id: Optional[int]) -> Layout:
    """Domyślny układ nowego CV u klienta; klasyczny przy wyłączonej flagze.

    Czyta kolumnę zatwierdzonej reguły wprost, nie przez `resolve_client_rule`:
    pod zasadami centralnymi klient spoza katalogu dostaje regułę zbudowaną
    w pamięci (bez układu), a klient czekający na synchronizację — 503, które
    wywracałoby odczyt CV etapu. Układ ustawia DL w `/settings/cv-rules` także
    przy zasadach centralnych (`client_cv_rules.set_client_cv_layout`).
    """
    if not enabled() or not client_id:
        return LAYOUT_CLASSIC
    from sqlalchemy import select

    from app.models.client_cv_rule import ClientCvRule

    return normalized(
        await db.scalar(
            select(ClientCvRule.cv_layout).where(
                ClientCvRule.client_id == client_id,
                ClientCvRule.confirmed_at.is_not(None),
            )
        )
    )


async def default_for_job(db, job_id: Optional[int]) -> Layout:
    if not enabled() or not job_id:
        return LAYOUT_CLASSIC
    from app.models.job import Job

    job = await db.get(Job, job_id)
    return await default_for_client(db, getattr(job, "client_id", None))


def page1_why(extras: Optional[dict]) -> Optional[list[str]]:
    """Trzy zdania strony 1 poprawione przez rekrutera (dodatki strony 1)."""
    if not isinstance(extras, dict):
        return None
    why = extras.get("why")
    if not isinstance(why, list):
        return None
    texts = [str(item).strip() for item in why if str(item or "").strip()]
    return texts[:3] or None


WREATH_CHOICES = ("auto", "cert", "school")


def page1_wreath(extras: Optional[dict]) -> str:
    """Co idzie do wieńca na stronie 1 (Artur 23.11.2026): „auto” = certyfikat,
    gdy klient go wymaga (MUST), inaczej dyplom; „cert” albo „school” wybiera rekruter."""
    value = extras.get("wreath") if isinstance(extras, dict) else None
    return value if value in WREATH_CHOICES else "auto"


def chosen_result(extras: Optional[dict]) -> Optional[str]:
    """„Najmocniejszy wynik” do strony 1: zdanie wpisane przez rekrutera
    (`result_text`) albo wybrane z listy modelu — tylko sprawdzone z cytatem
    z CV (`results[i].verified`)."""
    if not isinstance(extras, dict):
        return None
    manual = str(extras.get("result_text") or "").strip()
    if manual:
        return manual
    results = extras.get("results")
    if not isinstance(results, list) or not results:
        return None
    index = extras.get("result_index", 0)
    if not isinstance(index, int) or not 0 <= index < len(results):
        index = 0
    item = results[index]
    if not isinstance(item, dict) or item.get("verified") is not True:
        return None
    text = str(item.get("text") or "").strip()
    return text or None


_RESULT_KEYS = ("result_text", "result_index", "results", "results_source_sha")


def forget_page1_result(extras: Optional[dict]) -> Optional[dict]:
    """Dodatki strony 1 po wczytaniu innej generacji (przegląd 25.11.2026):
    bez najmocniejszego wyniku (listy, wyboru, zdania rekrutera) i bez własnego
    wyróżnika (`highlight.mode == "custom"`) — opisują poprzednie CV. Wieniec
    i wyłączony wyróżnik zostają. ``None`` = nic nie zostało."""
    if not isinstance(extras, dict):
        return extras
    kept = {k: v for k, v in extras.items() if k not in _RESULT_KEYS}
    highlight = kept.get("highlight")
    if isinstance(highlight, dict) and highlight.get("mode") == "custom":
        kept.pop("highlight")
    return kept or None


def compose_page1_why(
    why_points: list[str], extras: Optional[dict]
) -> Optional[list[str]]:
    """Trzy zdania „Dlaczego nasz kandydat” na stronie 1 (wariant E2, 22.11.2026).

    Zdania poprawione w edytorze wygrywają. Inaczej: lata (punkt 1 generatora),
    technologie (punkt 2) i najmocniejszy wynik z całego CV; bez sprawdzonego
    wyniku — trzeci punkt generatora (najważniejsze wymaganie). ``None`` =
    render bierze pierwsze trzy punkty sam.
    """
    edited = page1_why(extras)
    if edited:
        return edited
    result = chosen_result(extras)
    if result is None:
        return None
    points = [str(p).strip() for p in why_points if str(p or "").strip()]
    return points[:2] + [result]
