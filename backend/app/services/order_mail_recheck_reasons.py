"""Dlaczego zamówienie z maila wisi w kolejce — i co z tego wynika dla alertu.

Godzinowa ponowna weryfikacja musi rozróżnić dwa światy, bo ticket daje im
przeciwne zachowania:

* **czeka na podpis umowy** — nowy kontraktor bez żywej umowy gdziekolwiek
  w systemie. Podpisanie umowy B2B trwa dłużej niż kilka godzin, więc taki wpis
  czeka bezterminowo i NIE zawraca głowy Delivery Leadowi;
* **wszystko inne** — po trzech nieudanych próbach z rzędu idzie karta do DL.

Rozstrzyga KOD powodu z bramki (``order_mail_gate``), nigdy tekst po polsku:
zdania są redagowane, a cena pomyłki to albo zalanie DL kartami, albo cisza
przy realnym problemie. Moduł jest czysty — bez bazy, bez zegara z zewnątrz
poza jawnym argumentem — więc cała reguła daje się przetestować tablicowo.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

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
