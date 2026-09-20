"""Dlaczego zamówienie z maila wisi w kolejce — i co z tego wynika dla alertu.

Godzinowa ponowna weryfikacja musi rozróżnić dwa światy, bo ticket daje im
przeciwne zachowania:

* **czeka na podpis umowy** — nowy kontraktor bez żywej umowy gdziekolwiek
  w systemie. Podpisanie umowy B2B trwa dłużej niż kilka godzin, więc taki wpis
  czeka bezterminowo i NIE zawraca głowy Delivery Leadowi;
* **wszystko inne** — po trzech nieudanych próbach z rzędu idzie karta do DL.

Rozstrzyga KOD powodu z bramki (``order_mail_gate``), nigdy tekst po polsku:
zdania są redagowane, a cena pomyłki to albo zalanie DL kartami, albo cisza
przy realnym problemie. Reguła jest czysta — bez bazy, bez zegara z zewnątrz
poza jawnym argumentem — więc daje się przetestować tablicowo.

Na końcu modułu mieszka też okno godzin recheku i WYPROWADZONY z niego próg
bezpiecznika (`alert_after_hours`). Te dwie rzeczy czytają konfigurację, więc
nie są czyste — ale muszą stać obok `should_alert`, bo to jedyna obrona przed
wołaniem jej z surowym `ORDER_MAIL_RECHECK_ALERT_AFTER_HOURS` (patrz komentarz
przy `alert_after_hours`).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from app.core.config import settings
from app.core.scheduling import is_within_local_hours
from app.services.order_mail_gate import (
    CODE_AUTOAPPLY_DISABLED,
    CODE_AUTOAPPLY_EXCLUDED_CLIENT,
    CODE_PERSON_DECISION_NEW,
    CODE_PERSON_KNOWN_ELSEWHERE_IDLE,
)

#: Czeka bezterminowo, bez licznika prób i bez karty dla Delivery Leada.
CATEGORY_AWAITING_CONTRACT = "awaiting_contract"
#: Automat wyłączony globalnie albo dla klienta. Kategoria istnieje, żeby
#: historia mówiła, DLACZEGO wpis stoi — ale ESKALUJE jak każda inna, bo
#: wyłącznik gasi wyłącznie zapis automatyczny: ręczne „Zastosuj" go nie czyta,
#: więc taki dokument zapisze WYŁĄCZNIE człowiek. Wyciszenie tej kategorii
#: znaczyłoby, że przestawienie wyłącznika kasuje alarmowanie całej kolejki.
CATEGORY_CONFIG = "config"
#: Nie rozpoznano klienta: nie ma komu wystawić karty (odbiorcami są Delivery
#: Leadzi KLIENTA). Wpis widać w kolejce i w historii ponownych weryfikacji.
CATEGORY_UNRECOGNIZED = "unrecognized"
#: Każdy inny powód — licznik prób rośnie, po progu idzie karta.
CATEGORY_OTHER = "other"

#: Kody, które znaczą „zamówienie przyszło, zanim podpisano umowę".
AWAITING_CONTRACT_CODES = frozenset(
    {
        # Zamówienie MD/kosztowe: osoby nie ma na rosterze klienta i nie ma
        # żywej umowy nigdzie indziej (``ACTION_DECIDE_PERSON``, wariant „new").
        CODE_PERSON_DECISION_NEW,
        # Kandydat jest w bazie, ale bez trwającej współpracy — dokładnie tak
        # wygląda nowy kontraktor z umową B2B w trakcie podpisu.
        CODE_PERSON_KNOWN_ELSEWHERE_IDLE,
    }
)

#: Kody opisujące wyłącznik automatu, a nie dokument.
CONFIG_CODES = frozenset({CODE_AUTOAPPLY_DISABLED, CODE_AUTOAPPLY_EXCLUDED_CLIENT})


def classify_hold(codes: Optional[Iterable[str]], *, client_known: bool = True) -> str:
    """Kategoria wstrzymania dla KOMPLETU kodów jednego dokumentu.

    ``awaiting_contract`` wymaga, żeby **każdy** powód należał do zbioru
    „czeka na podpis". Jeden dodatkowy powód (stawka poza pasmem, niepewny
    odczyt, ucięty tekst) przesuwa dokument do ``other`` — to bezpieczny
    kierunek pomyłki: DL dostanie kartę, zamiast nie dostać jej nigdy.

    Pusta lista kodów znaczy „nie wiemy, dlaczego wisi" (wpis sprzed wdrożenia
    kodów albo wynik spoza bramki) i jest traktowana jak ``other``.
    """
    if not client_known:
        return CATEGORY_UNRECOGNIZED
    present = {c for c in (codes or []) if c}
    if not present:
        return CATEGORY_OTHER
    if present <= AWAITING_CONTRACT_CODES:
        return CATEGORY_AWAITING_CONTRACT
    if present <= CONFIG_CODES:
        return CATEGORY_CONFIG
    return CATEGORY_OTHER


#: Kategorie, które nigdy nie zwiększają licznika prób ani nie alarmują.
#: ``config`` świadomie NIE jest tu wymienione — patrz opis stałej.
_QUIET_CATEGORIES = frozenset({CATEGORY_AWAITING_CONTRACT, CATEGORY_UNRECOGNIZED})


def advance_attempts(
    previous: Optional[dict[str, Any]], *, category: str, now: datetime
) -> dict[str, Any]:
    """Ślad po nieudanej próbie: ``{attempts, last_at, category}``.

    „Trzy nieudane próby **z rzędu**" znaczy, że zmiana kategorii zaczyna
    liczenie od nowa — zamówienie, które przestało czekać na podpis, a zaczęło
    mieć problem z odczytem, dostaje pełne trzy próby na nowy problem.
    """
    before = previous or {}
    if category in _QUIET_CATEGORIES:
        attempts = 0
    elif before.get("category") != category:
        attempts = 1
    else:
        attempts = int(before.get("attempts") or 0) + 1
    meta = {
        "attempts": attempts,
        "category": category,
        "last_at": now.astimezone(timezone.utc).isoformat(),
    }
    if before.get("alerted_at"):
        meta["alerted_at"] = before["alerted_at"]
    return meta


def _parse(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def should_alert(
    meta: Optional[dict[str, Any]],
    *,
    waiting_since: Optional[datetime],
    now: datetime,
    after_attempts: int,
    after_hours: int,
) -> bool:
    """Czy Delivery Lead ma dostać kartę o tym dokumencie.

    JEDNO źródło dla godzinowej ponownej weryfikacji i dla dobowego skanera
    (``rule_order_mail_review``) — dwie kopie tej reguły rozjechałyby się
    i skaner wystawiałby nazajutrz karty, które recheck świadomie wyciszył.

    Bezpiecznik: dokument bez ustalonej kategorii to dokument, którego pętla
    nigdy nie obejrzała (wyłączona, zatrzymana albo wpis sprzed wdrożenia).
    Bez tej gałęzi awaria pętli zamieniłaby „powiadom po trzech próbach"
    w „nie powiadamiaj nigdy".
    """
    meta = meta or {}
    category = meta.get("category")
    if category in _QUIET_CATEGORIES:
        return False
    if int(meta.get("attempts") or 0) >= after_attempts:
        return True
    # Bezpiecznik. Dwa różne stany świata, jedna odpowiedź: pętla nigdy tego
    # wpisu nie widziała (brak kategorii) ALBO przestała go widzieć (ostatnia
    # próba starsza niż okno). Bez drugiego przypadku pętla zatrzymana po
    # pierwszej próbie zamrażała dokument na ``attempts = 1`` na zawsze —
    # a dobowy skaner, nie widząc go w ``live``, zamykał nawet kartę, którą
    # dostał wcześniej.
    deadline = timedelta(hours=after_hours)
    moment = now.astimezone(timezone.utc)
    since = _parse(waiting_since)
    if since is None or moment - since < deadline:
        return False
    last_at = _parse(meta.get("last_at"))
    return last_at is None or moment - last_at >= deadline


# ── Okno godzin pracy i wyprowadzony z niego próg bezpiecznika ───────────────


def recheck_window() -> tuple[int, int]:
    """Godziny (lokalne), w których wolno ruszyć automatycznemu recheckowi."""
    return (
        int(settings.ORDER_MAIL_RECHECK_START_HOUR_LOCAL),
        int(settings.ORDER_MAIL_RECHECK_END_HOUR_LOCAL),
    )


def is_recheck_time(now: datetime) -> bool:
    """Czy ``now`` wypada w oknie automatycznego recheku (`BUSINESS_TZ`).

    Bieg RĘCZNY tego nie pyta: człowiek klikający „Pobierz zamówienia z maila"
    o 19:00 prosi o sprawdzenie teraz.
    """
    start, end = recheck_window()
    return is_within_local_hours(
        now, start_hour=start, end_hour=end, tz=settings.BUSINESS_TZ
    )


def window_closed_hours() -> int:
    """Ile godzin na dobę okno jest ZAMKNIĘTE (0, gdy chodzi całą dobę)."""
    start, end = recheck_window()
    start = max(0, min(23, start))
    end = max(0, min(23, end))
    if start == end:
        return 0
    open_hours = (end - start) if start < end else (24 - start + end)
    return 24 - open_hours


def alert_after_hours() -> int:
    """Efektywny próg bezpiecznika „pętla przestała widzieć ten wpis".

    WYPROWADZONY z okna, nie wpisany ręcznie — i to jest cały sens tej funkcji.
    Bezpiecznik w `should_alert` zakłada, że pętla ogląda dokumenty mniej więcej
    ciągle. Przy oknie 8–18 stempel `last_at` każdego wstrzymanego wpisu ma
    o 01:00 czternaście godzin, więc surowe sześć godzin z konfiguracji kazałoby
    dobowemu skanerowi (`rule_order_mail_review`) wystawić kartę CAŁEJ kolejce
    każdej nocy — a `dl_alerts_loop` chodzi co 24 h od startu kontenera, więc
    trafienie w zamknięte okno jest kwestią godziny ostatniego deployu.

    Dwie godziny zapasu ponad długość nocy: bieg wznawia się ~08:0x, nie
    punktualnie o 08:00. Bezpiecznik dalej łapie martwą pętlę — tylko w ciągu
    doby zamiast sześciu godzin. W normalnej pracy nie odpala się wcale;
    o karcie decyduje licznik prób.
    """
    closed = window_closed_hours()
    minimum = int(settings.ORDER_MAIL_RECHECK_ALERT_AFTER_HOURS)
    if closed <= 0:
        return minimum
    return max(minimum, closed + 2)
