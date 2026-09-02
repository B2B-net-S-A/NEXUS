"""Bramka auto-zapisu — osiem warunków, wszystkie naraz; CZYSTA funkcja.

Decyzja właściciela: pewne → zapis bez człowieka, niepewne → kolejka. Ciężar
idzie więc w definicję „pewne". Brak choćby jednego warunku → ``review``
z listą powodów po polsku (to one mówią operatorowi, czego szukać).

Czysta i bez bazy, bo to jest miejsce, które trzeba móc przetestować na całym
korpusie bez Postgresa i bez skrzynki. Startuje w TRYBIE CIENIA
(``ORDER_MAIL_AUTOAPPLY_ENABLED=false``): werdykt i powód lądują w dzienniku,
nic nie jest zapisywane — po dwóch tygodniach jest tabela „co poszłoby
automatem i czy słusznie".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable, Mapping, Optional

from app.services.order_mail_planner import AUTO_ACTIONS, DocumentProposal
from app.services.order_mail_resolver import MATCH_EXACT, ResolvedConsultant
from app.services.order_pdf_parser import ConsultantOrderRow, OrderExtraction

VERDICT_AUTO = "auto"
VERDICT_REVIEW = "review"

#: Pasma sensowności stawki NETTO per jednostka (PLN). Poza pasmem → kolejka.
RATE_BANDS: dict[str, tuple[Decimal, Decimal]] = {
    "hour": (Decimal("50"), Decimal("500")),
    "day": (Decimal("400"), Decimal("4000")),
    "month": (Decimal("5000"), Decimal("60000")),
}
#: Maksymalna odchyłka od stawki efektywnej z harmonogramu kontraktu.
MAX_RATE_DEVIATION = Decimal("0.40")


@dataclass(frozen=True)
class GateInput:
    identification_method: Optional[str]
    policies_applied: tuple[str, ...]
    extraction: OrderExtraction
    document_truncated: bool
    ocr_capped: bool
    resolved: tuple[ResolvedConsultant, ...]
    proposal: DocumentProposal
    #: Wiersze z deterministycznego ekstraktora polityki (``extract_rows``).
    deterministic_rows: tuple[ConsultantOrderRow, ...]
    #: contract_id → (stawka efektywna z harmonogramu, jednostka) — może być puste.
    current_rates: Mapping[int, tuple[Optional[Decimal], Optional[str]]]
    autoapply_enabled: bool
    excluded_client_ids: frozenset[int] = frozenset()


@dataclass
class GateVerdict:
    verdict: str
    reasons: list[str] = field(default_factory=list)

    @property
    def is_auto(self) -> bool:
        return self.verdict == VERDICT_AUTO


def _rates_of(rows: Iterable[ConsultantOrderRow]) -> list[Decimal]:
    return sorted(r.rate_client for r in rows if r.rate_client is not None)


def evaluate(inp: GateInput) -> GateVerdict:
    reasons: list[str] = []
    ex = inp.extraction
    prop = inp.proposal

    # 0) przełączniki
    if prop.client_id in inp.excluded_client_ids:
        reasons.append(
            "Klient wykluczony z automatu (ORDER_MAIL_AUTOAPPLY_EXCLUDE_CLIENT_IDS)"
        )

    # 1) klient po numerze rejestrowym
    if inp.identification_method != "registry_id":
        reasons.append(
            "Klient rozpoznany bez numeru rejestrowego (marker/domena) — nie jest to dowód"
        )

    # 2) własna polityka + odczyt modelem (fallback regexowy nigdy nie autozapisuje)
    if not inp.policies_applied:
        reasons.append("Klient nie ma własnej polityki odczytu")
    if ex.source != "claude":
        reasons.append(f"Odczyt bez modelu (source={ex.source}) — fallback awaryjny")

    # 3) + 4) osoby: dokładne, jednoznaczne, jeden żywy kontrakt
    if not inp.resolved:
        reasons.append("Brak osób do dopasowania")
    for res in inp.resolved:
        if res.match_kind != MATCH_EXACT:
            reasons.append(f"„{res.row_name}”: {res.reason}")
        elif not res.has_single_live_contract:
            reasons.append(
                f"„{res.row_name}”: {len(res.live_contract_ids)} żywych kontraktów u klienta"
                if res.live_contract_ids
                else f"„{res.row_name}”: brak żywego (active/ending) kontraktu — automat nie wskrzesza"
            )

    # 5) proweniencja: numer i okres z etykiet (confidence 1.0 = polityka), stawki
    #    wierszy potwierdzone deterministycznym ekstraktorem
    if ex.confidence.get("title") != 1.0:
        reasons.append(
            "Numer zamówienia bez potwierdzenia etykietą (proweniencja modelu)"
        )
    llm_rates = _rates_of(ex.consultant_rows)
    det_rates = _rates_of(inp.deterministic_rows)
    if not inp.deterministic_rows:
        reasons.append("Polityka nie potwierdza wierszy osób deterministycznie")
    elif len(inp.deterministic_rows) != len(ex.consultant_rows):
        reasons.append(
            f"Liczba osób z modelu ({len(ex.consultant_rows)}) ≠ z tabeli ({len(inp.deterministic_rows)})"
        )
    elif llm_rates != det_rates:
        reasons.append(
            "Stawki z modelu nie zgadzają się ze stawkami z tabeli dokumentu"
        )
    if ex.uncertain:
        details = [f"Odczyt niepewny: {r}" for r in ex.uncertain_reasons[:3]]
        reasons.extend(details or ["Odczyt oznaczony jako niepewny"])

    # 6) kompletność tekstu
    if inp.document_truncated:
        reasons.append("Tekst dokumentu ucięty przed odczytem")
    if inp.ocr_capped:
        reasons.append("Skan dłuższy niż limit OCR — lista osób może być niekompletna")

    # 7) stawka w paśmie + odchyłka od stawki efektywnej kontraktu
    for row_prop in prop.rows:
        if row_prop.rate_client is None or row_prop.rate_unit is None:
            reasons.append(f"„{row_prop.row_name}”: brak stawki albo jednostki")
            continue
        rate = Decimal(row_prop.rate_client)
        band = RATE_BANDS.get(row_prop.rate_unit)
        if band and not (band[0] <= rate <= band[1]):
            reasons.append(
                f"„{row_prop.row_name}”: stawka {rate} {row_prop.rate_unit} poza pasmem {band[0]}–{band[1]}"
            )
        current = inp.current_rates.get(row_prop.contract_id or -1)
        if current and current[0] and current[1] == row_prop.rate_unit:
            deviation = abs(rate - current[0]) / current[0]
            if deviation > MAX_RATE_DEVIATION:
                reasons.append(
                    f"„{row_prop.row_name}”: stawka {rate} odbiega o {deviation:.0%} od obowiązującej {current[0]}"
                )

    # 8) precondition + addytywność + atomowość + okres z dokumentu
    if prop.blocking:
        reasons.extend(prop.blocking)
    for row_prop in prop.rows:
        if row_prop.action not in AUTO_ACTIONS:
            reasons.append(
                f"„{row_prop.row_name}”: {row_prop.action} — "
                + "; ".join(row_prop.reasons or ["poza zakresem automatu"])
            )
        if not row_prop.start_date or not row_prop.end_date:
            reasons.append(
                f"„{row_prop.row_name}”: okres niepełny w dokumencie (od {row_prop.start_date or '—'} do {row_prop.end_date or '—'})"
            )

    if not inp.autoapply_enabled and not reasons:
        # Tryb cienia: werdykt „auto" zapisujemy, ale zapis się nie odbywa.
        return GateVerdict(VERDICT_AUTO, [])
    return GateVerdict(
        VERDICT_AUTO if not reasons else VERDICT_REVIEW, _dedupe(reasons)
    )


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out
