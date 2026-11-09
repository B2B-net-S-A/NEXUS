"""Czysta logika raportu BNP: jeden wiersz na rekrutację otwartą w miesiącu.

Kolumny i ich znaczenie pochodzą z szablonu banku. Reguły, które łatwo cofnąć
przy okazji, opisuje ``docs/claude/klienci/raport-miesieczny-bnp.md``.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Iterable, Optional, Sequence
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.models.contract import RateUnit
from app.models.job import Seniority
from app.models.recruitment_pipeline import PipelineStage
from app.services.candidate_followups import add_business_days
from app.services.rejection_reason_labels import CLIENT_NOT_A_VERDICT

# Klient, dla którego istnieje szablon. Numer z bazy, jak w `order_policies`.
BNP_REPORT_CLIENT_IDS = frozenset({12})
SUPPLIER_NAME = "B2B.net S.A."
SLA_WORKDAYS = 10
MIN_CV_FOR_RITM_SLA = 2
HOURS_PER_MD = 8

# Import z Traffita potrafi przeskoczyć „CV wysłane”, więc późniejszy etap u
# klienta też znaczy, że CV poszło. To samo robi `SENT_TO_CLIENT_STAGES` listy.
SENT_STAGES = frozenset(
    {
        PipelineStage.cv_sent,
        PipelineStage.client_interview,
        PipelineStage.acceptance,
        PipelineStage.negotiation,
        PipelineStage.onboarding,
        PipelineStage.hired,
    }
)
# „Ile ofert otrzymaliśmy”, nie ile umów: akceptacja klienta albo dalej.
OFFER_STAGES = frozenset(
    {
        PipelineStage.acceptance,
        PipelineStage.negotiation,
        PipelineStage.onboarding,
        PipelineStage.hired,
    }
)

SENIORITY_LABELS: dict[Seniority, str] = {
    Seniority.junior: "Junior",
    Seniority.mid: "Regular",
    Seniority.senior: "Senior",
    Seniority.lead: "Lead",
    Seniority.architect: "Architect",
}
_SENIORITY_WORDS: dict[str, Seniority] = {
    "junior": Seniority.junior,
    "regular": Seniority.mid,
    "medium": Seniority.mid,
    "mid": Seniority.mid,
    "senior": Seniority.senior,
    "lead": Seniority.lead,
}
_SENIORITY_RE = re.compile(
    r"\b(junior|regular|medium|mid|senior|lead)\b", re.IGNORECASE
)
# Lookbehind zamiast \b: tytuły bywają pisane „Software Developer_RITM123”.
_RITM_RE = re.compile(r"(?<![a-z0-9])RITM\d+\b", re.IGNORECASE)
_RFP_RE = re.compile(r"(?<![a-z0-9])RFP[ _-]?(\d+)\b", re.IGNORECASE)
_TITLE_NUMBER_RE = re.compile(
    r"[\s\-–_(]*(?<![a-z0-9])(?:RITM\d+|RFP[ _-]?\d+)\b\)?", re.IGNORECASE
)
_YEARS_RE = re.compile(r"\b(\d{1,2})\s*\+?\s*lat", re.IGNORECASE)
SENIOR_FROM_YEARS = 4
REGULAR_FROM_YEARS = 2


@dataclass(frozen=True)
class StageEvent:
    """Jeden wiersz historii etapów osoby w rekrutacji, od najstarszego."""

    candidate_id: int
    stage: PipelineStage
    ended_by: Optional[str]
    moved_at: datetime
    client_rate_value: Optional[Decimal] = None
    client_rate_unit: Optional[RateUnit] = None
    client_rate_currency: Optional[str] = None
    expected_rate_value: Optional[Decimal] = None
    expected_rate_unit: Optional[RateUnit] = None
    expected_rate_currency: Optional[str] = None
    rejection_reason: Optional[str] = None


@dataclass(frozen=True)
class RateBand:
    """Widełki z umowy w zł/h, jak w załączniku; arkusz pokazuje je za MD.

    ``id`` jest puste, dopóki nikt ich nie zapisał.
    """

    id: Optional[int]
    role: str
    minimum: int
    maximum: int

    @property
    def average(self) -> float:
        return (self.minimum + self.maximum) / 2


@dataclass(frozen=True)
class ReportJob:
    id: int
    title: str
    working_title: Optional[str]
    description: Optional[str]
    client_reference: Optional[str]
    seniority: Optional[Seniority]
    client_rate_card_id: Optional[int]
    opened_on: date
    closed_on: Optional[date]
    budget_hourly: Optional[float] = None


@dataclass(frozen=True)
class ReportRow:
    job_id: int
    title: str
    start: date
    closed: Optional[date]
    sla: date
    ritm: Optional[str]
    ritm_source: str
    role: str
    seniority: Optional[Seniority]
    seniority_source: str
    rate_card_id: Optional[int]
    contract_role: Optional[str]
    contract_role_source: str
    cv: int
    cv_sla: int
    cv_in_budget: Optional[int]
    rejected_cv: int
    meetings: int
    rejected_after_meeting: int
    offers: int
    offer_min_md: Optional[float]
    offer_max_md: Optional[float]
    band_min_md: Optional[float]
    band_max_md: Optional[float]

    @property
    def seniority_label(self) -> Optional[str]:
        return SENIORITY_LABELS[self.seniority] if self.seniority else None

    @property
    def percent_cv_sla(self) -> Optional[float]:
        return self.cv_sla / self.cv if self.cv else None

    @property
    def ritm_sla(self) -> int:
        return int(self.cv_sla >= MIN_CV_FOR_RITM_SLA)

    @property
    def ritm_sla_and_budget(self) -> Optional[int]:
        if self.cv_in_budget is None:
            return None
        return int(
            self.cv_sla >= MIN_CV_FOR_RITM_SLA
            and self.cv_in_budget >= MIN_CV_FOR_RITM_SLA
        )

    @property
    def meetings_per_cv(self) -> Optional[float]:
        return self.meetings / self.cv if self.cv else None

    @property
    def rejected_per_cv(self) -> Optional[float]:
        return self.rejected_cv / self.cv if self.cv else None

    @property
    def band_average_md(self) -> Optional[float]:
        if self.band_min_md is None or self.band_max_md is None:
            return None
        return (self.band_min_md + self.band_max_md) / 2

    @property
    def recommended_average_md(self) -> Optional[float]:
        """Środek między najniższą i najwyższą stawką, jak formuła w szablonie."""
        if self.offer_min_md is None or self.offer_max_md is None:
            return None
        return (self.offer_min_md + self.offer_max_md) / 2

    @property
    def percent_from_band_average(self) -> Optional[float]:
        recommended, average = self.recommended_average_md, self.band_average_md
        if recommended is None or not average:
            return None
        return (recommended - average) / average

    @property
    def offer_min_minus_top(self) -> Optional[float]:
        if self.band_max_md is None or self.offer_min_md is None:
            return None
        return self.offer_min_md - self.band_max_md

    @property
    def percent_difference(self) -> Optional[float]:
        difference = self.offer_min_minus_top
        if difference is None or not self.band_max_md:
            return None
        return difference / self.band_max_md

    @property
    def needs_attention(self) -> bool:
        """Czy Delivery Lead ma tu coś do uzupełnienia przed wysyłką."""
        return (
            self.ritm_source in {"rfp", "none"}
            or self.seniority_source == "none"
            or self.contract_role_source == "none"
        )


def sla_date(start: date) -> date:
    """START + 10 dni roboczych w kalendarzu firmy (dzień startu się nie liczy)."""
    noon = datetime.combine(start, time(12), tzinfo=ZoneInfo(settings.BUSINESS_TZ))
    return add_business_days(noon, SLA_WORKDAYS)


def hourly_rate(
    value: Optional[Decimal],
    unit: Optional[RateUnit],
    currency: Optional[str],
) -> Optional[float]:
    """Stawka w zł/h. Inna waluta albo stawka miesięczna nie ma tu porównania
    z budżetem ani widełkami, więc raport jej nie zgaduje."""
    if value is None or (currency or "PLN") != "PLN":
        return None
    if unit == RateUnit.hourly or unit is None:
        return float(value)
    if unit == RateUnit.daily:
        return float(value) / HOURS_PER_MD
    return None


def extract_request_number(
    client_reference: Optional[str],
    title: Optional[str],
    working_title: Optional[str],
) -> tuple[Optional[str], str]:
    """Numer zapytania i skąd go wzięto: ``field`` | ``title`` | ``rfp`` | ``none``."""
    if client_reference and client_reference.strip():
        return client_reference.strip(), "field"
    text = f"{title or ''} {working_title or ''}"
    ritm = _RITM_RE.search(text)
    if ritm:
        return ritm.group(0).upper(), "title"
    rfp = _RFP_RE.search(text)
    if rfp:
        return f"RFP {rfp.group(1)}", "rfp"
    return None, "none"


def role_from_title(title: str) -> str:
    """Tytuł rekrutacji bez numeru zapytania."""
    return _TITLE_NUMBER_RE.sub("", title or "").strip(" _–-")


def propose_seniority(
    seniority: Optional[Seniority],
    title: Optional[str],
    working_title: Optional[str],
    description: Optional[str],
) -> tuple[Optional[Seniority], str]:
    """Poziom i źródło: ``field`` | ``title`` | ``years`` | ``description`` | ``none``.

    Lata doświadczenia z nazwy roboczej trafiają lepiej niż słowo w opisie: na
    październiku BNP opis pomylił 2 z 6, a lata 1 z 7 (ręczny plik DL).
    """
    if seniority is not None:
        return seniority, "field"
    named = _SENIORITY_RE.search(f"{title or ''} {working_title or ''}")
    if named:
        return _SENIORITY_WORDS[named.group(1).lower()], "title"
    years = _YEARS_RE.search(working_title or "")
    if years and int(years.group(1)) >= SENIOR_FROM_YEARS:
        return Seniority.senior, "years"
    if years and int(years.group(1)) >= REGULAR_FROM_YEARS:
        return Seniority.mid, "years"
    described = _SENIORITY_RE.search(description or "")
    if described:
        return _SENIORITY_WORDS[described.group(1).lower()], "description"
    return None, "none"


def _normalized(text: str) -> str:
    return re.sub(r"[^a-z0-9.+#]+", " ", text.lower()).strip()


def _has_words(text: str, phrase: str) -> bool:
    return f" {phrase} " in f" {text} "


def propose_band(
    title: Optional[str],
    working_title: Optional[str],
    bands: Sequence[RateBand],
) -> Optional[RateBand]:
    """Rola z umowy wskazana przez nazwę rekrutacji; najdłuższa pasująca nazwa.

    Propozycja: nazwa zapisana przez człowieka zawsze ją zastępuje. Programista
    bez rozpoznanej technologii zostaje bez roli, bo widełki stacków się różnią.
    """
    text = _normalized(f"{title or ''} {working_title or ''}")
    if not text:
        return None
    by_name = {_normalized(band.role): band for band in bands}
    if "automatyzuj" in text or _has_words(text, "automation"):
        automation = by_name.get("test automation engineer")
        if automation:
            return automation
    if _has_words(text, "developer") or _has_words(text, "programista"):
        for words, name in (
            ((".net", "net", "c#"), "software developer net"),
            (("java",), "software developer java"),
            (("angular",), "software developer angular"),
            (
                ("full stack", "fullstack", "android", "kotlin", "ios", "mobile"),
                "software developer full stack",
            ),
        ):
            if any(_has_words(text, word) for word in words):
                return by_name.get(name)
        return None
    matches = [
        band for name, band in by_name.items() if name and _has_words(text, name)
    ]
    return max(matches, key=lambda band: len(band.role), default=None)


def _latest_rate(rows: Sequence[StageEvent], field: str) -> Optional[float]:
    """Najnowsza zapisana stawka pary: ``client`` albo ``expected``, zł/h."""
    for row in reversed(rows):
        value = getattr(row, f"{field}_rate_value")
        if value is not None:
            return hourly_rate(
                value,
                getattr(row, f"{field}_rate_unit"),
                getattr(row, f"{field}_rate_currency"),
            )
    return None


def _is_client_verdict(row: StageEvent) -> bool:
    """Klient ocenił osobę. „Wybrał kogoś innego” przy zamknięciu nie jest oceną."""
    return (
        row.stage == PipelineStage.rejected
        and row.ended_by == "client"
        and row.rejection_reason not in CLIENT_NOT_A_VERDICT
    )


def _summarize(
    events: Iterable[StageEvent],
    sla: date,
    budget_hourly: Optional[float],
    tz: ZoneInfo,
) -> dict:
    per_person: dict[int, list[StageEvent]] = defaultdict(list)
    for event in events:
        per_person[event.candidate_id].append(event)

    cv = cv_sla = in_budget = rejected_cv = meetings = rejected_after = offers = 0
    sent_rates: list[float] = []
    for rows in per_person.values():
        sent = [row for row in rows if row.stage in SENT_STAGES]
        if not sent:
            # Odrzucenie „przez klienta” bez wysłanego CV zdarza się przy
            # zamykaniu rekrutacji; BNP nie dostał tej osoby, więc jej nie ma.
            continue
        cv += 1
        if min(row.moved_at for row in sent).astimezone(tz).date() <= sla:
            cv_sla += 1

        client_rate = _latest_rate(rows, "client")
        if client_rate is not None:
            sent_rates.append(client_rate)
        candidate_rate = _latest_rate(rows, "expected")
        if (
            budget_hourly is not None
            and candidate_rate is not None
            and candidate_rate <= budget_hourly
        ):
            in_budget += 1

        met = any(row.stage == PipelineStage.client_interview for row in rows)
        meetings += int(met)
        if any(_is_client_verdict(row) for row in rows):
            if met:
                rejected_after += 1
            else:
                rejected_cv += 1
        if any(row.stage in OFFER_STAGES for row in rows):
            offers += 1

    return {
        "cv": cv,
        "cv_sla": cv_sla,
        "cv_in_budget": in_budget if budget_hourly is not None else None,
        "rejected_cv": rejected_cv,
        "meetings": meetings,
        "rejected_after_meeting": rejected_after,
        "offers": offers,
        "offer_min_md": min(sent_rates) * HOURS_PER_MD if sent_rates else None,
        "offer_max_md": max(sent_rates) * HOURS_PER_MD if sent_rates else None,
    }


def build_row(
    job: ReportJob,
    events: Sequence[StageEvent],
    bands: Sequence[RateBand],
) -> ReportRow:
    ritm, ritm_source = extract_request_number(
        job.client_reference, job.title, job.working_title
    )
    seniority, seniority_source = propose_seniority(
        job.seniority, job.title, job.working_title, job.description
    )
    band = next((b for b in bands if b.id == job.client_rate_card_id), None)
    if job.client_rate_card_id is not None and band is not None:
        contract_role_source = "field"
    else:
        band = propose_band(job.title, job.working_title, bands)
        contract_role_source = "proposal" if band else "none"

    sla = sla_date(job.opened_on)
    summary = _summarize(events, sla, job.budget_hourly, ZoneInfo(settings.BUSINESS_TZ))
    return ReportRow(
        job_id=job.id,
        title=job.title,
        start=job.opened_on,
        closed=job.closed_on,
        sla=sla,
        ritm=ritm,
        ritm_source=ritm_source,
        role=role_from_title(job.title),
        seniority=seniority,
        seniority_source=seniority_source,
        rate_card_id=band.id if band else None,
        contract_role=band.role if band else None,
        contract_role_source=contract_role_source,
        band_min_md=band.minimum * HOURS_PER_MD if band else None,
        band_max_md=band.maximum * HOURS_PER_MD if band else None,
        **summary,
    )
