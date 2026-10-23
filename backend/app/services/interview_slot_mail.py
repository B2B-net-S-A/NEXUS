"""Terminy rozmowy u klienta z wklejonego maila (20.10.2026).

Zgłoszenie DL-i: przepisywanie terminów od klienta pole po polu (data, godzina,
kolejny termin…) zabiera najwięcej czasu w całym cyklu rozmowy. Teraz DL
wkleja maila, model wypisuje terminy, a okno „Terminy od klienta” (i „Kiedy
rozmowa?” przy ruchu karty) wypełnia się samo. Człowiek sprawdza i wysyła.

Podział pracy jak w innych odczytach „znajdź i zacytuj” (F22–F25):

* model zwraca dzień, godzinę i DOSŁOWNY cytat z maila dla każdego terminu,
* KOD sprawdza: cytat stoi w mailu (inaczej termin odpada), termin nie jest
  z przeszłości, dzień tygodnia z cytatu zgadza się z datą (inaczej termin
  zostaje z ostrzeżeniem — „czwartek 24.10” to błąd klienta albo modelu
  i decyduje człowiek), weekend i godziny poza 7–21 też dostają ostrzeżenie.

Treści maila NIE zapisujemy (decyzja Artura 20.10.2026): idzie tylko do
modelu, a w bazie zostają terminy, długość, „odpowiedz do” i notatka, które
DL wyśle wnioskiem. Do logu trafiają długości i liczby, nigdy tekst.

Model jest dodatkiem: brak klucza, błąd albo zła odpowiedź to
``status: "unavailable"`` i okno działa jak dotąd (terminy wpisuje się ręcznie).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date, datetime, time, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import DEFAULT_TZ
from app.models.ai_feature import AIFeatureKey
from app.services.ai_models import model_chain_for
from app.services.ai_quota import ai_feature
from app.services.cv_qc import _json_object
from app.services.interview_slots import MAX_SLOTS
from app.services.llm_prompts import INTERVIEW_SLOTS_FROM_MAIL
from app.services.llm_providers import api_key_configured
from app.services.prompt_fencing import fence

logger = logging.getLogger(__name__)

FEATURE = AIFeatureKey.interview_slots_from_mail
TEXT_MAX = 8000

MSG_UNAVAILABLE = "Nie udało się odczytać terminów z maila — wpisz je ręcznie."
MSG_EMPTY = "Nie znalazłem w tym tekście terminów z dniem i godziną."

WARN_WEEKDAY = "weekday_mismatch"
WARN_QUOTE = "quote_mismatch"
WARN_WEEKEND = "weekend"
WARN_HOURS = "unusual_hour"

_WEEKDAYS_PL = (
    "poniedziałek",
    "wtorek",
    "środa",
    "czwartek",
    "piątek",
    "sobota",
    "niedziela",
)

# Odmiany i skróty dni tygodnia → numer dnia (pon = 0). Pełne formy zamiast
# rdzeni: „piątego listopada” i „środowisko” to nie dni tygodnia. Granice słów
# przez `\w` (litery i cyfry): „środę” kończy się literą spoza ASCII, a „22nd”
# w angielskim mailu to nie niedziela.
_WEEKDAY_PATTERNS: tuple[tuple[int, str], ...] = (
    (0, r"poniedziałek|poniedziałku|poniedzialek|poniedzialku|pon"),
    (1, r"wtorek|wtorku|wt"),
    (2, r"środa|środę|środy|środzie|sroda|srode|srody|srodzie|śr"),
    (3, r"czwartek|czwartku|czw"),
    (4, r"piątek|piątku|piatek|piatku|pt"),
    (5, r"sobota|sobotę|soboty|sobocie|sobote|sob"),
    (6, r"niedziela|niedzielę|niedzieli|niedziele|niedz|nd"),
)
_WEEKDAY_RE = [
    (day, re.compile(rf"(?<!\w)(?:{pattern})(?!\w)", re.IGNORECASE))
    for day, pattern in _WEEKDAY_PATTERNS
]
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Data w cytacie: „22.10”, „22/10”, „22.10.2026”.
_QUOTE_DATE_RE = re.compile(r"(?<!\d)(\d{1,2})[./](\d{1,2})(?:[./]\d{2,4})?(?!\d)")
# Godzina w cytacie: „10:00”, „10.30” po „o”, albo sama liczba („o 10”, „9 a 12”).
_QUOTE_TIME_RE = re.compile(r"(?<!\d)(\d{1,2})(?:[:.](\d{2}))?(?!\d)")
# „o 10.10”, „godz. 9.05” — po tych słowach „D.M” to godzina, nie data.
_QUOTE_TIME_MARK_RE = re.compile(
    r"(?:(?<!\w)(?:o|godz|godz\.|g\.|ok\.|około|at)\s*)$", re.IGNORECASE
)
_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def _norm(text: str) -> str:
    """Do porównania cytatu: bez różnic w białych znakach, myślnikach i wielkości liter."""
    text = unicodedata.normalize("NFKC", text or "").lower()
    text = re.sub(r"[‐-―−]", "-", text)
    return re.sub(r"\s+", " ", text).strip()


def _quote_in_text(quote: Any, text: str) -> Optional[str]:
    if not isinstance(quote, str):
        return None
    quote = quote.strip().strip("„”\"'")
    if len(quote) < 3:
        return None
    return quote if _norm(quote) in _norm(text) else None


def _parse_date(value: Any) -> Optional[date]:
    if not isinstance(value, str) or not _DATE_RE.match(value.strip()):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _parse_time(value: Any) -> Optional[time]:
    if not isinstance(value, str):
        return None
    match = _TIME_RE.match(value.strip())
    if not match:
        return None
    return time(int(match.group(1)), int(match.group(2)))


def weekdays_in(quote: str) -> set[int]:
    return {day for day, rx in _WEEKDAY_RE if rx.search(quote)}


def quote_contradicts(quote: str, day: date, start: time) -> bool:
    """Czy cytat mówi inną datę albo godzinę niż termin od modelu.

    Cytat to jedyny ślad, skąd model wziął termin — „czwartek 22.10 o 10:00”
    z terminem 29.10 albo 11:00 to pomyłka modelu, którą dzień tygodnia nie
    wykryje. Cytat bez daty („albo 14:30”) sprawdzamy tylko po godzinie.
    """
    dates: list[tuple[int, int]] = []
    without_dates = quote
    for match in reversed(list(_QUOTE_DATE_RE.finditer(quote))):
        if _QUOTE_TIME_MARK_RE.search(quote[: match.start()]):
            continue  # „o 10.10” to godzina — zostaje do sprawdzenia niżej
        without_dates = (
            without_dates[: match.start()] + " " + without_dates[match.end() :]
        )
        d, m = int(match.group(1)), int(match.group(2))
        if 1 <= d <= 31 and 1 <= m <= 12:
            dates.append((d, m))
    if dates and (day.day, day.month) not in dates:
        return True
    times = [
        (int(h), int(m) if m else None)
        for h, m in _QUOTE_TIME_RE.findall(without_dates)
        if int(h) <= 23 and (not m or int(m) <= 59)
    ]
    if not times:
        return False
    return not any(
        h == start.hour and (m is None or m == start.minute) for h, m in times
    )


def _duration(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    minutes = int(value)
    return minutes if 15 <= minutes <= 480 else None


def _short(value: Any, limit: int) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = re.sub(r"\s+", " ", value).strip()
    return value[:limit] or None


def check_parse(
    raw: str,
    *,
    text: str,
    mail_date: date,
    now: datetime,
    tz: str = DEFAULT_TZ,
) -> dict:
    """Odpowiedź modelu → terminy, które przeszły kontrolę kodu.

    Czysta funkcja (bez bazy i modelu) — na niej stoją testy reguł.
    ``now`` musi mieć strefę; terminy wracają w ISO ze strefą firmy.
    """
    zone = ZoneInfo(tz)
    data = _json_object(raw)
    duration = _duration(data.get("duration_minutes"))
    slot_minutes = duration or 60

    slots: dict[datetime, dict] = {}
    dropped = 0
    for item in data.get("slots") or []:
        if not isinstance(item, dict):
            dropped += 1
            continue
        day = _parse_date(item.get("date"))
        start_t = _parse_time(item.get("start"))
        quote = _quote_in_text(item.get("quote"), text)
        if day is None or start_t is None or quote is None:
            dropped += 1
            continue
        start = datetime.combine(day, start_t, tzinfo=zone)
        if start < now - timedelta(minutes=5):
            dropped += 1
            continue
        end_t = _parse_time(item.get("end"))
        end = datetime.combine(day, end_t, tzinfo=zone) if end_t else None
        if end is not None and end <= start:
            end = None
        window = bool(item.get("window")) and end is not None
        if end is None or (
            not window and end - start != timedelta(minutes=slot_minutes)
        ):
            # Koniec spoza okna liczymy z długości rozmowy — jak formularz.
            end = start + timedelta(minutes=slot_minutes)
        warning: Optional[str] = None
        named = weekdays_in(quote)
        if quote_contradicts(quote, day, start_t):
            warning = WARN_QUOTE
        elif named and day.weekday() not in named:
            warning = WARN_WEEKDAY
        elif day.weekday() >= 5:
            warning = WARN_WEEKEND
        elif not 7 <= start_t.hour <= 20:
            warning = WARN_HOURS
        if start in slots:
            continue
        slots[start] = {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "window": window,
            "quote": quote,
            "warning": warning,
        }

    ordered = [slots[key] for key in sorted(slots)]
    extra = max(0, len(ordered) - MAX_SLOTS)

    respond_by: Optional[str] = None
    rb = data.get("respond_by")
    if isinstance(rb, dict):
        rb_day = _parse_date(rb.get("date"))
        rb_time = _parse_time(rb.get("time")) or time(12, 0)
        if rb_day is not None and rb_day >= mail_date:
            moment = datetime.combine(rb_day, rb_time, tzinfo=zone)
            if moment > now:
                respond_by = moment.isoformat()

    fmt = data.get("format")
    unclear = [
        u for u in (_short(x, 160) for x in (data.get("unclear") or [])[:5]) if u
    ]
    return {
        "slots": ordered[:MAX_SLOTS],
        "extra_slots": extra,
        "dropped": dropped,
        "duration_minutes": duration,
        "respond_by": respond_by,
        "format": fmt if fmt in ("online", "onsite", "phone") else None,
        "location_note": _short(data.get("location_note"), 120),
        "people": _short(data.get("people"), 160),
        "unclear": unclear,
    }


def build_prompt(text: str, *, mail_date: date, today: date) -> str:
    return INTERVIEW_SLOTS_FROM_MAIL.render(
        today=today.isoformat(),
        today_weekday=_WEEKDAYS_PL[today.weekday()],
        mail_date=mail_date.isoformat(),
        mail_weekday=_WEEKDAYS_PL[mail_date.weekday()],
        mail=fence("client_mail", text),
    )


def _call_model(system: str, prompt: str, chain: tuple[str, ...]) -> str:
    from app.services.claude_client import call_claude, text_of  # noqa: PLC0415

    message = call_claude(
        model=chain[0],
        fallback_models=list(chain[1:]) or None,
        max_tokens=1500,
        thinking={"type": "disabled"},
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return text_of(message)


def _empty(status: str, message: Optional[str], **extra: Any) -> dict:
    return {
        "status": status,
        "message": message,
        "slots": [],
        "extra_slots": 0,
        "dropped": 0,
        "duration_minutes": None,
        "respond_by": None,
        "format": None,
        "location_note": None,
        "people": None,
        "unclear": [],
        **extra,
    }


async def read_slots(
    db: AsyncSession,
    *,
    text: str,
    mail_date: date,
    today: date,
    now: datetime,
    user_id: int,
) -> dict:
    """Terminy z maila klienta. Nigdy nie rzuca — model to podpowiedź."""
    text = (text or "").replace("\x00", "").strip()
    if not text:
        return _empty("empty", MSG_EMPTY)
    chain = tuple(model_chain_for(FEATURE))
    if not api_key_configured(chain[0]):
        return _empty("unavailable", MSG_UNAVAILABLE)
    try:
        prompt = build_prompt(text, mail_date=mail_date, today=today)
        system = INTERVIEW_SLOTS_FROM_MAIL.system_prompt or ""
        async with ai_feature(db, FEATURE, user_id=user_id):
            # Licznik AI zapisuje wiersz w tej sesji — commit PRZED modelem,
            # żeby żądanie nie trzymało połączenia przez cały round-trip.
            await db.commit()
            raw = await run_in_threadpool(_call_model, system, prompt, chain)
        result = check_parse(raw, text=text, mail_date=mail_date, now=now)
    except Exception as exc:  # noqa: BLE001 — AI to podpowiedź, nigdy bramka
        logger.warning(
            "[interview_slot_mail] read failed chars=%s (%s)",
            len(text),
            type(exc).__name__,
        )
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            logger.warning("[interview_slot_mail] rollback failed")
        return _empty("unavailable", MSG_UNAVAILABLE)
    logger.info(
        "[interview_slot_mail] chars=%s slots=%s dropped=%s extra=%s",
        len(text),
        len(result["slots"]),
        result["dropped"],
        result["extra_slots"],
    )
    if not result["slots"]:
        return {"status": "empty", "message": MSG_EMPTY, **result}
    return {"status": "ok", "message": None, **result}
