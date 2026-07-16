"""Rejestr stabilnych stanów semantycznych lifecycle rekrutacji (M4 PR-05).

Audyt P0.2: nazwa kolumny Kanbanu ani legacy enum nie mogą być nośnikiem
reguł biznesowych — custom stage bez ``legacy_enum_value`` zlewa się do
``new`` (baseline PR-00: 79 488 latest rows poza template'em joba, 1 custom
z legacy ``new``). Ten moduł definiuje JEDYNE dozwolone ``semantic_key``
dla ``stage_revisions.semantic_key`` oraz mapping legacy enum → semantic.

Kanoniczny lifecycle pochodzi z sekcji 10.1 planu. Rozszerzenia pragmatyczne
(stan dzisiejszej bazy):

- ``hired`` — decyzja o zatrudnieniu. Decyzją Artura (2026-07-16, §20.1)
  ``hired`` ≠ placement: ``placement_active`` wymaga podpisanego kontraktu
  i potwierdzonego startu (PR-20).
- ``rejected`` / ``candidate_withdrawn`` — legacy terminale bez rozróżnienia
  internal/client; rozdzielenie na ``rejected_internal``/``rejected_client``
  wymaga danych, których historia nie ma (nie zgadujemy).
- ``on_hold`` — NIE-terminalny pause (audyt: „Lista rezerwowa" błędnie
  skonfigurowana jako terminalne withdrawn).
- ``unmapped`` — kwarantanna: stage, którego znaczenia nie da się ustalić
  automatycznie. Bootstrap NIGDY nie zgaduje (wymóg planu PR-05).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

REGISTRY_VERSION = "m4-pr05-v1"


@dataclass(frozen=True)
class SemanticState:
    key: str
    label_pl: str
    is_terminal: bool = False
    # Dla terminali: zgrubna kategoria zgodna z TerminalType (hired/rejected/
    # withdrawn) — adapter na legacy reguły (maile, hooki, raporty).
    terminal_type: Optional[str] = None


_STATES: tuple[SemanticState, ...] = (
    # ── Aktywny lifecycle (sekcja 10.1 planu) ───────────────────────────────
    SemanticState("identified", "Zidentyfikowany"),
    SemanticState("screening_pending", "Screening — oczekuje"),
    SemanticState("screening_completed", "Screening — zakończony"),
    SemanticState("internal_review", "Przegląd wewnętrzny"),
    SemanticState("internally_approved", "Zatwierdzony wewnętrznie"),
    SemanticState("submission_preparation", "Przygotowanie prezentacji"),
    SemanticState("submission_approved", "Prezentacja zatwierdzona"),
    SemanticState("submission_dispatch_pending", "Wysyłka w toku"),
    SemanticState("submitted_to_client", "Wysłany do klienta"),
    SemanticState("client_review", "Przegląd klienta"),
    SemanticState("client_interview_scheduled", "Rozmowa u klienta — umówiona"),
    SemanticState("client_interview_completed", "Rozmowa u klienta — odbyta"),
    SemanticState("feedback_pending", "Oczekiwanie na feedback"),
    SemanticState("client_approved", "Zaakceptowany przez klienta"),
    SemanticState("offer_preparation", "Przygotowanie oferty"),
    SemanticState("offer_approved", "Oferta zatwierdzona"),
    SemanticState("offer_dispatch_pending", "Oferta — wysyłka w toku"),
    SemanticState("offer_sent", "Oferta wysłana"),
    SemanticState("offer_accepted", "Oferta zaakceptowana"),
    SemanticState("contract_preparation", "Przygotowanie kontraktu"),
    SemanticState("contract_signed", "Kontrakt podpisany"),
    SemanticState("start_confirmed", "Start potwierdzony"),
    SemanticState("placement_active", "Placement aktywny"),
    SemanticState("placement_ended", "Placement zakończony"),
    # ── Pause (NIE-terminal — audyt P0.2) ───────────────────────────────────
    SemanticState("on_hold", "Wstrzymany (on hold)"),
    # ── Pragmatyczne rozszerzenia stanu obecnej bazy ────────────────────────
    SemanticState(
        "hired", "Zatrudniony (decyzja)", is_terminal=True, terminal_type="hired"
    ),
    # ── Terminal outcomes (sekcja 10.1) ─────────────────────────────────────
    SemanticState(
        "rejected_internal",
        "Odrzucony wewnętrznie",
        is_terminal=True,
        terminal_type="rejected",
    ),
    SemanticState(
        "rejected_client",
        "Odrzucony przez klienta",
        is_terminal=True,
        terminal_type="rejected",
    ),
    SemanticState("rejected", "Odrzucony", is_terminal=True, terminal_type="rejected"),
    SemanticState(
        "candidate_withdrawn",
        "Kandydat się wycofał",
        is_terminal=True,
        terminal_type="withdrawn",
    ),
    SemanticState(
        "offer_declined", "Oferta odrzucona", is_terminal=True, terminal_type="rejected"
    ),
    SemanticState(
        "offer_expired", "Oferta wygasła", is_terminal=True, terminal_type="rejected"
    ),
    SemanticState(
        "job_cancelled",
        "Oferta pracy anulowana",
        is_terminal=True,
        terminal_type="withdrawn",
    ),
    SemanticState(
        "placement_failed",
        "Placement nieudany",
        is_terminal=True,
        terminal_type="rejected",
    ),
    # ── Kwarantanna (bootstrap nie zgaduje) ─────────────────────────────────
    SemanticState("unmapped", "Niezmapowany (kwarantanna)"),
)

SEMANTIC_STATES: dict[str, SemanticState] = {s.key: s for s in _STATES}

# Legacy PipelineStage enum → semantic_key. Świadome decyzje mapowania:
# - verified → internally_approved (gate stawki = wewnętrzne zatwierdzenie),
# - interview → internal_review (rozmowa techniczna wewnętrzna; w defaultowym
#   template występuje PO verified — mapping oddaje ZNACZENIE, nie kolejność),
# - onboarding → contract_preparation (etap „start pracy" przed hired w
#   obecnym template = przygotowanie startu, nie aktywny placement),
# - hired → hired (decyzja o zatrudnieniu; placement dopiero w PR-20).
LEGACY_TO_SEMANTIC: dict[str, str] = {
    "new": "identified",
    "prep_call": "screening_pending",
    "screening": "screening_completed",
    "verified": "internally_approved",
    "interview": "internal_review",
    "cv_sent": "submitted_to_client",
    "client_interview": "client_interview_scheduled",
    "acceptance": "client_approved",
    "negotiation": "offer_preparation",
    "onboarding": "contract_preparation",
    "hired": "hired",
    "rejected": "rejected",
    "withdrawn": "candidate_withdrawn",
}


def is_valid_semantic_key(key: str) -> bool:
    return key in SEMANTIC_STATES


def semantic_for_legacy(legacy_enum_value: Optional[str]) -> Optional[str]:
    """semantic_key dla legacy enum albo None (→ kwarantanna `unmapped`)."""
    if not legacy_enum_value:
        return None
    return LEGACY_TO_SEMANTIC.get(legacy_enum_value)
