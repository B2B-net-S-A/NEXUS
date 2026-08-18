"""Dealbreaker-switche: twarde ukrywanie zamiast punktowania (runda 3).

Punkty degradują, ale nie usuwają — kandydat za 250 PLN/h przy budżecie
120 PLN/h nadal wypływa na listę, tylko niżej. Dla rekrutera to nie jest
„trochę gorszy match", tylko strata czasu. Te filtry są TWARDĄ, świadomie
włączaną wersją tych samych porównań, które scoring robi miękko.

Trzy żelazne zasady, każda okupiona zmierzonym wypadkiem:

1. **Nieznany PRZECHODZI.** Wycinamy wyłącznie na POZYTYWNEJ wiedzy
   (stawka znana i ponad budżet; `remote_only is True`). Filtr stażu przy
   pokryciu 1,2% zredukował kiedyś lejek 11 091 → 45 — brak danych nie jest
   dowodem niedopasowania.
2. **Margines na negocjacje, zmierzony na danych.** GT-loss na zamrożonych
   zbiorach A+B (2 212 par z historii decyzji, 18.08): margines 0% ukryłby
   44% realnie dowiezionych kandydatów, +15% → 27%, +30% → 14%, +50% → 5%.
   Stawki są negocjowane w dół rutynowo — stąd default +30% i switch
   domyślnie WYŁĄCZONY (świadome zawężenie, nie automat).
3. **Ukrywanie nigdy nie jest ciche.** Konsument dostaje liczniki per powód
   i renderuje „ukryto N" — pustka bez wyjaśnienia czyta się jak utrata
   danych (reguła „awaria ≠ pustka").

Granica finansowa: budżet PLN/h to stawka KANDYDACKA (operacyjna — rekruter
rozmawia o niej z kandydatem codziennie; stawka Championa jest widoczna na
karcie oferty). Cennik klienta pozostaje za VIEW_FINANCE i ten moduł go nie
dotyka. Jedyna porównywalna para jednostek to PLN/h ↔ PLN/h — legacy
``Job.salary_min/max`` (PLN/mies.) jest tu ignorowane z tych samych powodów,
dla których odmawia go warstwa salary (brak polityki konwersji).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

BUDGET_MARGINS = (0, 15, 30, 50)
DEFAULT_BUDGET_MARGIN = 30


def resolve_job_budget_hourly(job) -> Optional[float]:
    """Budżet PLN/h dla kandydata: jawne pole oferty, fallback Champion.

    ``rate_budget_hourly`` ustawia rekruter na formularzu oferty; gdy puste,
    używamy stawki z profilu Championa (`rate_value` — z definicji dokumentu
    stawka DLA KANDYDATA w PLN/h). Import przez scoring_service, żeby nie
    dublować parsowania profilu i respektować flagę sygnałów Championa.
    """
    explicit = getattr(job, "rate_budget_hourly", None)
    if explicit is not None:
        try:
            value = float(explicit)
        except (TypeError, ValueError):
            value = 0.0
        if value > 0:
            return value
    from app.services.scoring_service import _champion_hourly_rate

    return _champion_hourly_rate(job)


def _candidate_rate_pln_hourly(candidate) -> Optional[float]:
    """Stawka kandydata w PLN/h albo None (nieznana / niekanoniczna waluta)."""
    rate = getattr(candidate, "expected_rate_hourly", None)
    if rate is None:
        return None
    currency = getattr(candidate, "expected_rate_currency", None)
    from app.services.candidate_profile_rate import (
        is_canonical_profile_rate_currency,
    )

    if not is_canonical_profile_rate_currency(currency):
        # Stawka w obcej walucie bez polityki przeliczenia — to jest
        # „nie wiemy", nie „za drogo".
        return None
    try:
        value = float(rate)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def budget_excludes(candidate, budget_hourly: float, margin_pct: int) -> bool:
    """True wyłącznie, gdy ZNANA stawka przekracza budżet ponad margines."""
    cand = _candidate_rate_pln_hourly(candidate)
    if cand is None:
        return False
    return cand > budget_hourly * (1.0 + margin_pct / 100.0)


def remote_only_refuses_office(candidate) -> bool:
    """True tylko przy POZYTYWNYM „wyłącznie zdalnie" z notatek.

    Źródło: ``_notes_insights.preferences.remote_only`` — pole strukturalne
    ekstrakcji rozmów (True u 1 382 kandydatów, False u 5 893; reszta to
    nieznane i PRZECHODZI). Świadomie nie zgadujemy z wolnego tekstu.
    """
    from app.services.location_utils import _notes_insights_dict

    ins = _notes_insights_dict(candidate)
    if ins is None:
        return False
    prefs = ins.get("preferences")
    if not isinstance(prefs, dict):
        return False
    return prefs.get("remote_only") is True


@dataclass
class DealbreakerResult:
    kept: list = field(default_factory=list)
    hidden_over_budget: int = 0
    hidden_remote_only: int = 0

    def hidden_meta(self) -> dict:
        return {
            "over_budget": self.hidden_over_budget,
            "remote_only": self.hidden_remote_only,
        }


def apply_dealbreakers(
    candidates: list,
    *,
    exclude_over_budget: bool = False,
    budget_hourly: Optional[float] = None,
    budget_margin_pct: int = DEFAULT_BUDGET_MARGIN,
    exclude_remote_only: bool = False,
) -> DealbreakerResult:
    """Przefiltruj listę kandydatów switchami; policz ukrytych per powód.

    Kolejność powodów jest deterministyczna (budżet przed biurem), żeby
    kandydat łapiący oba nie migrował między licznikami między odczytami.
    ``exclude_over_budget`` bez znanego budżetu jest no-opem — brak budżetu
    po stronie oferty to także „nie wiemy", nie powód do ukrywania.
    """
    result = DealbreakerResult()
    budget_active = exclude_over_budget and budget_hourly is not None
    for candidate in candidates:
        if budget_active and budget_excludes(
            candidate, budget_hourly, budget_margin_pct
        ):
            result.hidden_over_budget += 1
            continue
        if exclude_remote_only and remote_only_refuses_office(candidate):
            result.hidden_remote_only += 1
            continue
        result.kept.append(candidate)
    return result
