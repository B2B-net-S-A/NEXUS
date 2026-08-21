"""Pydantic schemas for `/api/jobs/{id}/candidates-from-similar`.

Response shape is designed for direct consumption by the React
`HistoricalCandidatesSection` widget — each candidate carries enough metadata
to render the badge, tooltip (expandable sources list), and availability state
without a second roundtrip.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


TierLabel = Literal["A", "B"]
TierUsed = Literal["primary", "extended", "empty"]


class SimilarJobOut(BaseModel):
    job_id: int
    title: str
    similarity: float
    tier: TierLabel


class HistoricalSourceOut(BaseModel):
    job_id: int
    job_title: str
    stage: str
    similarity: float
    months_ago: float
    moved_at: datetime
    stage_weight: float
    contribution: float
    client_id: Optional[int] = None


class HistoricalCandidateOut(BaseModel):
    candidate_id: int
    name: str
    lastname: str
    avatar_url: Optional[str] = None
    competence_category: Optional[str] = None
    historical_score: float
    tier: TierLabel
    negative_signal: bool
    recommended_count: int = Field(
        ..., description="Total number of distinct source jobs (may exceed sources[])"
    )
    sources: list[HistoricalSourceOut]
    current_availability: Literal["available", "busy", "unknown"]
    current_status: Optional[str] = None
    # Szybkie przepinanie (Faza 3): kandydat był rozważany u klienta tego
    # joba — UI grupuje takich na górze ("Znani temu klientowi").
    same_client: bool = False
    # Ten sam klient go odrzucił / kandydat się wycofał — UI pokazuje mocne
    # ostrzeżenie i wyklucza z "zaznacz wszystkich".
    rejected_by_same_client: bool = False


class HistoricalCandidatesMeta(BaseModel):
    tier_a_count: int
    tier_b_count: int
    total_sources: int
    reason_if_empty: Optional[str] = None
    hidden_ineligible: int = 0
    """Ilu kandydatów z historii wycięła bramka dopuszczalności.

    Osobne pole, świadomie NIE kształt `{over_budget, remote_only}` znany
    z `meta.hidden` w `/recommendations`: tam liczniki opisują DEALBREAKERY
    (świadomie włączone przełączniki rekrutera), a tu wycina ZAWIERANIE —
    blacklista klienta, NDA, konflikt konkurencyjny, weto hiring managera.
    Inna decyzja, inne prawo do informacji, inny tekst w UI.

    Liczba nie mówi KTO i mówić nie może (to byłby przeciek NDA). Mówi, że dane
    ISTNIEJĄ i są zablokowane — czyli zamienia „nic tu nie ma" w „są, ale nie
    dla tego klienta". Ta sekcja z definicji celuje w ludzi rozważanych już
    u TEGO klienta, więc będzie pusta dokładnie tam, gdzie historia jest
    najgrubsza; bez tej liczby pustka byłaby nie do odróżnienia od braku historii.

    Default `0` trzyma kontrakt addytywnym: wczesny return przy braku podobnych
    ofert nie wymaga zmiany, a starsi konsumenci nie pękają.
    """


class CandidatesFromSimilarOut(BaseModel):
    job_id: int
    tier_used: TierUsed
    similar_jobs: list[SimilarJobOut]
    candidates: list[HistoricalCandidateOut]
    meta: HistoricalCandidatesMeta
