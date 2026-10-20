"""„Po rozmowie”: pytania klienta i oferta z notatki z telefonu (20.10.2026, PR 4).

Zgłoszenie: zebranie pytań po rozmowie u klienta to wypełnianie wielu pól
naraz, więc pytania lądują w notatkach. Teraz rekruter wkleja albo pisze
w trakcie telefonu do kandydata jedno pole tekstu, a okno debriefu wypełnia
się samo: pytania klienta, gotowość do oferty z warunkiem, nowa stawka
i termin startu (do komentarza). Rekruter sprawdza i zapisuje zwykły debrief.

Podział pracy jak w innych odczytach „znajdź i zacytuj” (F25):

* model zwraca każdy element z DOSŁOWNYM cytatem z notatki,
* KOD odrzuca element bez cytatu z notatki; kwotę stawki przyjmuje tylko
  wtedy, gdy ta liczba stoi w notatce (jak `_drop_ungrounded_rate`
  w odczycie notatek).

Trasa niczego nie zapisuje; tekst notatki trafia do komentarza debriefu
dopiero, gdy rekruter go zapisze. Do logu idą długości i liczby, nie treść.
Model jest dodatkiem: błąd = ``status: "unavailable"``, okno działa jak dotąd.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_feature import AIFeatureKey
from app.services.ai_models import model_chain_for
from app.services.ai_quota import ai_feature
from app.services.cv_qc import _json_object
from app.services.interview_slot_mail import _quote_in_text
from app.services.llm_prompts import DEBRIEF_FROM_TEXT
from app.services.llm_providers import api_key_configured
from app.services.prompt_fencing import fence

logger = logging.getLogger(__name__)

FEATURE = AIFeatureKey.debrief_from_text
TEXT_MAX = 8000
MAX_QUESTIONS = 30
QUESTION_MAX = 500

MSG_UNAVAILABLE = "Nie udało się rozpisać notatki — uzupełnij pola ręcznie."
MSG_EMPTY = "Nie znalazłem w notatce pytań klienta ani informacji o ofercie."

_OFFER = {"yes", "likely", "no", "unknown"}
_UNITS = {"hourly", "daily", "monthly"}
_DIGITS = re.compile(r"\d+")


def _short(value: Any, limit: int) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = re.sub(r"\s+", " ", value).strip()
    return value[:limit] or None


def _amount_in_text(amount: Any, text: str) -> Optional[str]:
    """Kwota z modelu, o ile ta liczba stoi w notatce („160”, „16 000”, „16k” nie)."""
    if not isinstance(amount, (str, int, float)) or isinstance(amount, bool):
        return None
    digits = "".join(_DIGITS.findall(str(amount).split(".")[0].split(",")[0]))
    if not digits or len(digits) > 7:
        return None
    # Liczby w notatce bez spacji tysięcy („16 000” → „16000”).
    compact = re.sub(r"(?<=\d)[\s .](?=\d{3}\b)", "", text)
    if digits not in set(_DIGITS.findall(compact)):
        return None
    return digits


def check_parse(raw: str, *, text: str) -> dict:
    """Odpowiedź modelu → elementy, które przeszły kontrolę kodu. Czysta funkcja."""
    data = _json_object(raw)
    questions: list[dict] = []
    seen: set[str] = set()
    dropped = 0
    for item in data.get("questions") or []:
        if not isinstance(item, dict):
            dropped += 1
            continue
        question = _short(item.get("text"), QUESTION_MAX)
        quote = _quote_in_text(item.get("quote"), text)
        if not question or quote is None:
            dropped += 1
            continue
        key = question.lower()
        if key in seen:
            continue
        seen.add(key)
        questions.append({"text": question, "quote": quote})
    questions = questions[:MAX_QUESTIONS]

    offer = None
    raw_offer = data.get("offer")
    if isinstance(raw_offer, dict) and raw_offer.get("value") in _OFFER:
        quote = _quote_in_text(raw_offer.get("quote"), text)
        if quote is not None:
            offer = {
                "value": raw_offer["value"],
                "condition": _short(raw_offer.get("condition"), 500),
                "quote": quote,
            }
        else:
            dropped += 1

    rate = None
    raw_rate = data.get("rate")
    if isinstance(raw_rate, dict):
        quote = _quote_in_text(raw_rate.get("quote"), text)
        amount = _amount_in_text(raw_rate.get("amount"), text)
        unit = raw_rate.get("unit") if raw_rate.get("unit") in _UNITS else None
        if quote is not None and amount is not None:
            rate = {"amount": amount, "unit": unit, "quote": quote}
        else:
            dropped += 1

    start = None
    raw_start = data.get("start")
    if isinstance(raw_start, dict):
        quote = _quote_in_text(raw_start.get("quote"), text)
        start_text = _short(raw_start.get("text"), 120)
        if quote is not None and start_text:
            start = {"text": start_text, "quote": quote}

    return {
        "questions": questions,
        "offer": offer,
        "rate": rate,
        "start": start,
        "dropped": dropped,
    }


def build_prompt(text: str) -> str:
    return DEBRIEF_FROM_TEXT.render(note=fence("recruiter_note", text))


def _call_model(system: str, prompt: str, chain: tuple[str, ...]) -> str:
    from app.services.claude_client import call_claude, text_of  # noqa: PLC0415

    message = call_claude(
        model=chain[0],
        fallback_models=list(chain[1:]) or None,
        max_tokens=2000,
        thinking={"type": "disabled"},
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return text_of(message)


def _empty(status: str, message: Optional[str]) -> dict:
    return {
        "status": status,
        "message": message,
        "questions": [],
        "offer": None,
        "rate": None,
        "start": None,
        "dropped": 0,
    }


async def read_note(db: AsyncSession, *, text: str, user_id: int) -> dict:
    """Pytania i oferta z notatki. Nigdy nie rzuca — model to podpowiedź."""
    text = (text or "").replace("\x00", "").strip()
    if not text:
        return _empty("empty", MSG_EMPTY)
    chain = tuple(model_chain_for(FEATURE))
    if not api_key_configured(chain[0]):
        return _empty("unavailable", MSG_UNAVAILABLE)
    try:
        system = DEBRIEF_FROM_TEXT.system_prompt or ""
        async with ai_feature(db, FEATURE, user_id=user_id):
            # Licznik AI zapisuje wiersz w tej sesji — commit PRZED modelem.
            await db.commit()
            raw = await run_in_threadpool(
                _call_model, system, build_prompt(text), chain
            )
        result = check_parse(raw, text=text)
    except Exception as exc:  # noqa: BLE001 — AI to podpowiedź, nigdy bramka
        logger.warning(
            "[debrief_from_text] read failed chars=%s (%s)",
            len(text),
            type(exc).__name__,
        )
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            logger.warning("[debrief_from_text] rollback failed")
        return _empty("unavailable", MSG_UNAVAILABLE)
    logger.info(
        "[debrief_from_text] chars=%s questions=%s offer=%s rate=%s dropped=%s",
        len(text),
        len(result["questions"]),
        result["offer"] is not None,
        result["rate"] is not None,
        result["dropped"],
    )
    found = result["questions"] or result["offer"] or result["rate"] or result["start"]
    if not found:
        return {"status": "empty", "message": MSG_EMPTY, **result}
    return {"status": "ok", "message": None, **result}
