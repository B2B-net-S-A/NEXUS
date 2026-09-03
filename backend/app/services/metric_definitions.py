"""Kody definicji metryk — jedno miejsce, jeden string.

Kod definicji jest kontraktem: konsument porównuje DWA kody i dostaje
odpowiedź „ta sama reguła / inna reguła". Dlatego ten sam string musi być
dosłownie ten sam wszędzie, gdzie reguła jest ta sama — własny wariant
(`..._by_mover`) daje maszynowo „różne" tam, gdzie jest identycznie, czyli
odwrotność tego, do czego to pole służy.

Do 09.2026 literał `first_hired_per_candidate_job` był powtórzony w czterech
miejscach, a jako nazwana stała istniał tylko w jednym. Front tłumaczy kody na
polski (`InsightsFormat.DEFINITION_PL`) i **pokazuje nieznany kod**
(`Definicja z serwera: …`) zamiast go chować — więc nowe kody można dodawać
backendem bez deployu frontu.

Kontekst rozjazdu, który to pole ma tłumaczyć: za rok 2026 aplikacja podawała
cztery różne liczby placementów (Insights 213 · kafle 228 · raport 317 · suma
wierszy tego samego raportu 332), bo współistnieją dwie rodziny atrybucji.
Rozjazd przestaje być błędem, a staje się informacją dopiero wtedy, gdy każdy
ekran mówi, którą regułę pokazuje.
"""

from __future__ import annotations

# Pierwsze wejście pary (kandydat, rekrutacja) na etap „Zatrudniony".
# Źródło: widok `analytics_first_milestones`. Atrybucja: osoba, która
# przesunęła etap (`first_moved_by`).
FIRST_HIRED_PER_CANDIDATE_JOB = "first_hired_per_candidate_job"

# Zamknięte rekrutacje, które miały co najmniej jeden placement.
CLOSED_JOBS_WITH_PLACEMENT = "closed_jobs_with_at_least_one_placement"

# Kamienie milowe kotwiczone na WERYFIKATORZE: zasługę za wszystkie etapy
# pary dostaje osoba, która przeniosła kandydata na „Zweryfikowany".
# To druga rodzina atrybucji — ta, która niesie pieniądze (KPI, konkursy).
VERIFIER_ANCHORED_MILESTONES = "verifier_anchored_milestones"

__all__ = [
    "CLOSED_JOBS_WITH_PLACEMENT",
    "FIRST_HIRED_PER_CANDIDATE_JOB",
    "VERIFIER_ANCHORED_MILESTONES",
]
