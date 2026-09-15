"""Pure decision: an automatic verdict always goes to the shared writer.

Review reasons describe source ambiguity, incomplete data, conflicting people,
rate outliers or an actual incompatible order. On a periodic order a missing
or ended engagement is a normal lifecycle state, not a reason to stop a complete
order. On MD and cost orders the planner stops such a person at
``ACTION_DECIDE_PERSON`` (keep as history / resume / replace / remove is the
Delivery Lead's decision), which lands here as an ordinary non-auto action.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
import re
from typing import Mapping, Optional

from app.services.order_mail_planner import AUTO_ACTIONS, DocumentProposal
from app.services.order_mail_resolver import MATCH_EXACT, ResolvedConsultant
from app.services.order_pdf_parser import (
    ConsultantOrderRow,
    OrderExtraction,
    _names_exactly_equivalent,
    MD_SCOPE_ORDER,
    _fold_policy_text,
    is_md_absence_reason,
    md_scope,
)

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
    #: Serwer potwierdził jeden aktywny rekord w jawnej puli polityki PFRON.
    trusted_policy_identity: Optional[str] = None
    #: Polityka klienta deklaruje zamówienia BEZTERMINOWE (BIK) — brak daty
    #: końca jest wtedy poprawnym odczytem, nie niepełnym okresem.
    open_ended_period: bool = False


@dataclass
class GateVerdict:
    verdict: str
    reasons: list[str] = field(default_factory=list)

    @property
    def is_auto(self) -> bool:
        return self.verdict == VERDICT_AUTO


def _row_evidence_reasons(
    rows: list[ConsultantOrderRow], evidence: tuple[ConsultantOrderRow, ...]
) -> list[str]:
    """Confirm each person's own rate/unit, never a sorted bag of amounts."""
    if not evidence:
        return ["Brak niezależnego potwierdzenia osób i stawek z pól dokumentu PDF"]
    if len(rows) != len(evidence):
        return [f"Liczba osób z modelu ({len(rows)}) ≠ z tabeli ({len(evidence)})"]
    reasons = []
    used: set[int] = set()
    for row in rows:
        matches = [
            i
            for i, source in enumerate(evidence)
            if _names_exactly_equivalent(row.consultant_name, source.consultant_name)
        ]
        if len(matches) != 1 or matches[0] in used:
            reasons.append(
                f"„{row.consultant_name}”: brak jednoznacznego potwierdzenia osoby w polach PDF"
            )
            continue
        index = matches[0]
        used.add(index)
        source = evidence[index]
        if source.uncertain or source.rate_client is None or source.rate_unit is None:
            # Wiersz bywa niepewny przez nazwisko albo okres, nie tylko stawkę —
            # konkretny powód niesie odczyt („Odczyt niepewny: …").
            reasons.append(
                f"„{row.consultant_name}”: niepewny odczyt wiersza osoby z pól PDF"
            )
        if (row.rate_client, row.rate_unit) != (source.rate_client, source.rate_unit):
            reasons.append(
                f"„{row.consultant_name}”: stawka lub jednostka z modelu nie zgadza się z polem PDF tej osoby"
            )
    return reasons


def _unused_total_mapping_reason(reason: str, inp: GateInput) -> bool:
    """Ignore only a schema-mapping concern about an absent, unused total.

    Periodic orders use rate and dates; MD/cost budgets retain their concerns.
    Never hide unreadable amounts, conflicting rates, people or dates.
    """
    if (
        inp.extraction.total_value is not None
        or not inp.proposal.rows
        or any(row.order_type != "periodic" for row in inp.proposal.rows)
    ):
        return False
    folded = _fold_policy_text(reason)
    if re.search(
        r"stawk|\brate\b|dat[ay]|okres|osob|nazwisk|nieczyteln|sprzeczn|rozne kwot",
        folded,
    ):
        return False
    return "total_value" in folded and any(
        phrase in folded
        for phrase in (
            "nie jest jednoznacznie oznaczone",
            "nie jest przypisane jednoznacznie",
        )
    )


def _md_rows(inp: GateInput) -> list:
    return [row for row in inp.proposal.rows if row.order_type == "md"]


def _irrelevant_md_absence_reason(reason: str, inp: GateInput) -> bool:
    """„Brak liczby MD" od modelu, który nie znał typu zamówienia.

    Zamówienie kosztowe i okresowe liczby MD nie potrzebują w ogóle. Zamówienie
    MD potrzebuje jej w JEDNYM z dwóch wariantów — przy każdej osobie albo raz
    na całe zamówienie (plan przenosi liczbę dokumentu na wiersz). Gdy wiersz
    ma MD w którymkolwiek wariancie, zastrzeżenie modelu jest fałszywym alarmem;
    gdy nie ma w żadnym, o braku mówi deterministyczny powód z kroku 7b.
    """
    if not is_md_absence_reason(reason) or not inp.proposal.rows:
        return False
    return all(row.md_total is not None for row in _md_rows(inp))


def evaluate(inp: GateInput) -> GateVerdict:
    reasons: list[str] = []
    ex = inp.extraction
    prop = inp.proposal

    # 0) przełączniki
    if prop.client_id in inp.excluded_client_ids:
        reasons.append("Automatyczny zapis jest wyłączony dla tego klienta")

    # 1) NIP albo jednoznaczny marker/domena PFRON i aktywny rekord z bazy.
    trusted_pfron = (
        inp.trusted_policy_identity == "pfron"
        and "PFRON" in inp.policies_applied
        and inp.identification_method in {"marker", "sender_domain"}
    )
    if inp.identification_method != "registry_id" and not trusted_pfron:
        reasons.append(
            "Nie potwierdzono jednoznacznie klienta numerem rejestrowym ani zatwierdzoną regułą dokumentu"
        )

    # 2) własna polityka + odczyt modelem (fallback regexowy nigdy nie autozapisuje)
    if not inp.policies_applied:
        reasons.append("Klient nie ma własnej polityki odczytu")
    if ex.source != "claude":
        failure = f" (AI: {ex.ai_failure})" if ex.ai_failure else ""
        reasons.append(f"Odczyt awaryjny{failure} — sprawdź zgodność pól z PDF")

    # 3) + 4) exact person, or an initial draft; ambiguous people/contracts block
    if not inp.resolved:
        reasons.append("Brak osób do dopasowania")
    for res in inp.resolved:
        if res.match_kind not in (MATCH_EXACT, "none"):
            reasons.append(f"„{res.row_name}”: {res.reason}")
        elif len(res.live_contract_ids) > 1:
            reasons.append(
                f"„{res.row_name}”: kilka aktywnych kontraktów — wybierz właściwy"
            )

    # 5) proweniencja: numer i okres z etykiet (confidence 1.0 = polityka), stawki
    #    wierszy potwierdzone deterministycznym ekstraktorem
    if ex.confidence.get("title") != 1.0:
        reasons.append(
            "Numer zamówienia nie został potwierdzony w oznaczonym polu dokumentu"
        )
    reasons.extend(_row_evidence_reasons(ex.consultant_rows, inp.deterministic_rows))
    if ex.uncertain:
        actionable = [
            r
            for r in ex.uncertain_reasons
            if not _unused_total_mapping_reason(r, inp)
            and not _irrelevant_md_absence_reason(r, inp)
        ]
        reasons.extend(f"Odczyt niepewny: {r}" for r in actionable)
        if not ex.uncertain_reasons:
            reasons.append("Odczyt oznaczony jako niepewny")

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

    # 7b) zamówienie MD wymaga liczby MD — przy osobie albo na całe zamówienie
    for row_prop in _md_rows(inp):
        if row_prop.md_total is None:
            reasons.append(
                f"„{row_prop.row_name}”: zamówienie MD bez liczby MD — dokument nie "
                "podaje jej ani przy osobie, ani na całe zamówienie"
            )
    if _md_rows(inp) and md_scope(ex) == MD_SCOPE_ORDER:
        # Plan przenosi liczbę dokumentu na każdy wiersz, a zapis per osoba
        # dałby każdemu całą pulę. Wspólną pulę zakłada człowiek w oknie
        # zamówienia — automat jej nie dzieli.
        reasons.append(
            "Dokument podaje jedną liczbę MD na całe zamówienie — załóż wspólny "
            "budżet MD ręcznie, automat nie dzieli puli między osoby"
        )

    # 8) precondition + addytywność + atomowość + okres z dokumentu
    if prop.blocking:
        reasons.extend(prop.blocking)
    for row_prop in prop.rows:
        if row_prop.action not in AUTO_ACTIONS:
            reasons.append(
                f"„{row_prop.row_name}”: "
                + "; ".join(
                    row_prop.reasons or ["Nie ustalono jednoznacznego miejsca zapisu"]
                )
            )
        if not row_prop.start_date or (
            not row_prop.end_date and not inp.open_ended_period
        ):
            reasons.append(
                f"„{row_prop.row_name}”: okres niepełny w dokumencie (od {row_prop.start_date or '—'} do {row_prop.end_date or '—'})"
            )
        elif row_prop.end_date and row_prop.start_date > row_prop.end_date:
            # Daty ISO porównują się jak tekst; odwrócony okres nigdy nie jest
            # poprawny, a tabela zamówień go nie odrzuci. Bez daty końca
            # (zamówienie bezterminowe, BIK) nie ma czego odwrócić.
            reasons.append(
                f"„{row_prop.row_name}”: okres odwrócony w dokumencie ({row_prop.start_date} – {row_prop.end_date})"
            )

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
