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
2. **Twardy sufit BEZ marginesu i BEZ osobnego uzbrajania (decyzja
   produktowa Artura, 19.08).** Wpisana/znana stawka budżetu ukrywa każdą
   ZNANĄ stawkę kandydata powyżej niej (strict ``>``; równa przechodzi),
   a sama obecność budżetu aktywuje filtr — zero dodatkowych przełączników.
   Pomiar z 18.08 zostaje tu jako świadomie zaakceptowany koszt: na zbiorach
   A+B (2 212 par z historii decyzji) sufit bez marginesu ukrywa 44% realnie
   dowiezionych kandydatów, bo stawki są rutynowo negocjowane w dół.
   Właściciel produktu wybrał przewidywalność („budżet znaczy budżet") nad
   recall — NIE przywracaj marginesu bez jego decyzji.
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
    from app.services.scoring_service import get_champion_hourly_rate

    return get_champion_hourly_rate(job)


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


def budget_excludes(candidate, budget_hourly: float) -> bool:
    """True wyłącznie, gdy ZNANA stawka jest ŚCIŚLE powyżej budżetu.

    Równość przechodzi — kandydat „dokładnie w budżecie" mieści się w nim.
    """
    cand = _candidate_rate_pln_hourly(candidate)
    if cand is None:
        return False
    return cand > budget_hourly


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
    exclude_over_budget: bool = True,
    budget_hourly: Optional[float] = None,
    exclude_remote_only: bool = False,
) -> DealbreakerResult:
    """Przefiltruj listę kandydatów switchami; policz ukrytych per powód.

    ``exclude_over_budget`` ma default ``True`` z decyzji produktowej 19.08:
    znany budżet działa Z AUTOMATU jako dealbreaker (konsument może go jawnie
    wyłączyć, żeby pokazać też przekraczających). Bez znanego budżetu filtr
    jest no-opem — brak budżetu po stronie oferty to także „nie wiemy",
    nie powód do ukrywania. Kolejność powodów jest deterministyczna (budżet
    przed biurem), żeby kandydat łapiący oba nie migrował między licznikami.
    """
    result = DealbreakerResult()
    budget_active = exclude_over_budget and budget_hourly is not None
    for candidate in candidates:
        if budget_active and budget_excludes(candidate, budget_hourly):
            result.hidden_over_budget += 1
            continue
        if exclude_remote_only and remote_only_refuses_office(candidate):
            result.hidden_remote_only += 1
            continue
        result.kept.append(candidate)
    return result
