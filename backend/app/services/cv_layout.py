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
    """Domyślny układ nowego CV u klienta; klasyczny przy wyłączonej flagze."""
    if not enabled() or not client_id:
        return LAYOUT_CLASSIC
    from app.services.cv_generator_b2b.client_rules import resolve_client_rule

    return rule_layout(await resolve_client_rule(db, client_id))


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
