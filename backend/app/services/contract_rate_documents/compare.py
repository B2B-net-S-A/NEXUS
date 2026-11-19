"""Różnica między stawką z dokumentów kontraktu a harmonogramem w NEXUSIE.

Czysta funkcja, bez bazy: wejście to odczyty plików (``reader.clean_fields``)
i harmonogram stawki kandydata, wyjście to różnica per odczyt albo ``None``.

Reguły z ręcznego przeglądu 1164 plików 18.11.2026:

* **Okno kroku** trwa od jego daty do daty najbliższego późniejszego kroku
  z DOWOLNEGO dokumentu kontraktu (nowsza umowa albo aneks zastępuje starszy).
  Porównujemy okna, które sięgają dzisiaj, przyszłe i te, które skończyły się
  w ostatnich ``HISTORY_DAYS`` dniach — przy 216 krok 130 zł/h z 09–10.2026
  był pominięty, bo patrzyliśmy tylko na „dziś”. Starsze okna to historia,
  której NEXUS zwykle nie ma (harmonogram powstał w 2026).
* **Do sprawdzenia** zamiast wpisu: dwa dokumenty podają różne stawki od tego
  samego dnia, krok z warunkiem zamiast daty, inna waluta albo stawka
  miesięczna przy kontrakcie godzinowym, różnica ponad ``MAX_AUTO_CHANGE``,
  harmonogram ma późniejszą zmianę niż dokument (brak nowszego pliku w
  teczce), krok sprzed startu kontraktu, krok sprzed ponad ``HISTORY_DAYS``
  dni, który nadal obowiązuje (w teczce może brakować nowszego aneksu).
* **Nowszy dokument wygrywa** w okresie swojego kroku: aneks z 11.06 ze
  stawką 120 do 31.12 zastępuje krok 130 od 03.08 z umowy z 03.06.
* Odczyt odrzucony przez człowieka (``dismissed``) nie bierze udziału.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional, Sequence

HISTORY_DAYS = 180
MAX_AUTO_CHANGE = Decimal("0.30")
TOLERANCE = Decimal("0.01")
HOURS_PER_DAY = Decimal(8)

REASON_CONFLICT = "Inny dokument podaje inną stawkę od tego samego dnia."
REASON_CONDITION = (
    "Krok zależy od warunku (np. klienta albo okresu próbnego), nie tylko od daty."
)
REASON_SAME_DOC = (
    "Dokument podaje kilka stawek od tego samego dnia (np. dla różnych klientów)."
)
REASON_UNIT = "Stawka w innej walucie albo jednostce niż kontrakt."
REASON_BIG = "Różnica ponad 30%."
REASON_NEXUS_NEWER = "W kontrakcie jest późniejsza zmiana stawki niż w tym dokumencie."
REASON_BEFORE_START = "Krok sprzed rozpoczęcia kontraktu."
REASON_OLD = (
    "Dokument sprzed ponad pół roku, a kontrakt ma inną stawkę — "
    "w teczce może brakować nowszego aneksu."
)


@dataclass(frozen=True)
class ScheduleStep:
    effective_from: date
    rate: Decimal


@dataclass(frozen=True)
class ContractRates:
    start_date: Optional[date]
    currency: str
    baseline_rate: Optional[Decimal]
    #: Kolejność jak w bazie (data, id) — remis rozstrzyga późniejszy wpis.
    schedule: tuple[ScheduleStep, ...] = ()


@dataclass(frozen=True)
class ReadInput:
    read_id: int
    result: dict[str, Any]
    dismissed: bool = False


@dataclass(frozen=True)
class _Step:
    read_id: int
    order: tuple[date, int]
    frm: Optional[date]
    to: Optional[date]
    rate: Optional[Decimal]  # zł/h w walucie kontraktu albo None (nieporównywalna)
    raw_rate: Decimal
    condition: Optional[str]


@dataclass
class Finding:
    category: str  # "auto" | "review"
    steps: list[dict[str, Any]]
    reasons: list[str] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {"category": self.category, "steps": self.steps, "reasons": self.reasons}


def _d(raw: Any) -> Optional[date]:
    if not isinstance(raw, str):
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def rate_on(contract: ContractRates, day: date) -> Optional[Decimal]:
    """Stawka z harmonogramu w danym dniu — ta sama reguła co
    ``Contract._resolve_scheduled_rate`` (najpóźniejszy krok ≤ dzień, remis
    wygrywa późniejszy wpis; same kroki przyszłe = najwcześniejszy)."""

    entries = list(contract.schedule)
    if not entries:
        return contract.baseline_rate
    past = [(i, e) for i, e in enumerate(entries) if e.effective_from <= day]
    if past:
        return max(past, key=lambda ie: (ie[1].effective_from, ie[0]))[1].rate
    earliest = min(e.effective_from for e in entries)
    return max(
        (ie for ie in enumerate(entries) if ie[1].effective_from == earliest),
        key=lambda ie: ie[0],
    )[1].rate


def _per_hour(
    rate: Decimal, unit: Any, currency: str, contract: ContractRates
) -> Optional[Decimal]:
    if currency != contract.currency:
        return None
    if unit == "hour":
        return rate
    if unit == "day":
        return (rate / HOURS_PER_DAY).quantize(Decimal("0.000001"))
    return None


def _steps_of(read: ReadInput, contract: ContractRates) -> list[_Step]:
    res = read.result
    if not res.get("changes_rate"):
        return []
    kind = res.get("kind")
    doc_date = _d(res.get("document_date"))
    effective = _d(res.get("effective_from"))
    out: list[_Step] = []
    for raw in res.get("rate_steps") or []:
        condition = raw.get("condition")
        frm = _d(raw.get("from")) or (None if condition else effective)
        if frm is None and kind == "contract" and not condition:
            frm = doc_date or contract.start_date
        rate = Decimal(str(raw["rate"]))
        out.append(
            _Step(
                read_id=read.read_id,
                order=(doc_date or date.min, read.read_id),
                frm=frm,
                to=_d(raw.get("to")),
                rate=_per_hour(
                    rate, raw.get("unit"), str(raw.get("currency") or "PLN"), contract
                ),
                raw_rate=rate,
                condition=condition,
            )
        )
    return out


def compare(
    contract: ContractRates, reads: Sequence[ReadInput], today: date
) -> dict[int, Optional[Finding]]:
    findings: dict[int, Optional[Finding]] = {r.read_id: None for r in reads}
    steps = [s for r in reads if not r.dismissed for s in _steps_of(r, contract)]
    dated = sorted((s for s in steps if s.frm), key=lambda s: (s.frm, s.order))
    horizon = today - timedelta(days=HISTORY_DAYS)
    nexus_dates = [s.effective_from for s in contract.schedule]

    def window_end(step: _Step) -> Optional[date]:
        later = [o.frm for o in dated if o.frm > step.frm]
        ends = [
            d for d in (min(later) - timedelta(days=1) if later else None, step.to) if d
        ]
        return min(ends) if ends else None

    def superseded(step: _Step) -> bool:
        """Krok z dokumentu, który na ten dzień ustala nowszy dokument.

        Aneks zastępuje paragraf o wynagrodzeniu w całości: krok starszej umowy
        przypadający w okresie kroku z nowszego aneksu nie obowiązuje."""

        return any(
            o.order[0] > step.order[0]
            and o.read_id != step.read_id
            and o.frm <= step.frm
            and (o.to is None or step.frm <= o.to)
            for o in dated
        )

    per_read: dict[int, list[tuple[_Step, Optional[Decimal], list[str]]]] = {}
    for step in steps:
        reasons: list[str] = []
        if step.frm is None:
            reasons.append(REASON_CONDITION)
            per_read.setdefault(step.read_id, []).append((step, None, reasons))
            continue
        if superseded(step):
            continue  # późniejszy dokument ustala stawkę na ten okres
        end = window_end(step)
        if end is not None and end < horizon:
            continue  # historia, której NEXUS zwykle nie zna
        if end is not None and contract.start_date and end < contract.start_date:
            continue  # okno skończyło się przed tym kontraktem (poprzednia umowa)
        day = step.frm
        if contract.start_date and day < contract.start_date:
            day = contract.start_date
            if step.to is None or step.to >= contract.start_date:
                reasons.append(REASON_BEFORE_START)
        nexus = rate_on(contract, day)
        if step.rate is None:
            reasons.append(REASON_UNIT)
        elif nexus is not None and abs(step.rate - nexus) < TOLERANCE:
            continue
        same_day = [
            o
            for o in dated
            if o.frm == step.frm
            and o.read_id != step.read_id
            and o.rate is not None
            and step.rate is not None
            and abs(o.rate - step.rate) >= TOLERANCE
        ]
        if same_day:
            reasons.append(REASON_CONFLICT)
        if step.condition:
            reasons.append(REASON_CONDITION)
        if any(
            o.read_id == step.read_id
            and o is not step
            and o.frm == step.frm
            and o.raw_rate != step.raw_rate
            for o in dated
        ):
            reasons.append(REASON_SAME_DOC)
        last_day = min(today, end) if end else today
        if any(step.frm < d <= last_day for d in nexus_dates):
            reasons.append(REASON_NEXUS_NEWER)
        if step.rate is not None and nexus:
            if abs(step.rate - nexus) / nexus > MAX_AUTO_CHANGE:
                reasons.append(REASON_BIG)
        if step.frm < horizon:
            reasons.append(REASON_OLD)
        per_read.setdefault(step.read_id, []).append((step, nexus, reasons))

    for read_id, items in per_read.items():
        items.sort(key=lambda it: it[0].frm or date.max)
        reasons = sorted({r for _s, _n, rs in items for r in rs})
        findings[read_id] = Finding(
            category="review" if reasons else "auto",
            reasons=reasons,
            steps=[
                {
                    "from": s.frm.isoformat() if s.frm else None,
                    "to": s.to.isoformat() if s.to else None,
                    "rate": float(s.rate) if s.rate is not None else float(s.raw_rate),
                    "nexus_rate": float(n) if n is not None else None,
                    "condition": s.condition,
                }
                for s, n, _rs in items
            ],
        )
    return findings
