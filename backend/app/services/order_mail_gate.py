"""Pure decision: an automatic verdict always goes to the shared writer.

Review reasons describe source ambiguity, incomplete data, conflicting people,
rate outliers or an actual incompatible order. A person who is not on the
client's roster NEVER auto-applies, on any order type: the contract is born
from a signed B2B agreement, not from the client's purchase order, so such a
document waits (``awaiting_contract`` — silent, no Delivery Lead card) until
the contract exists. On a periodic order an *ended* engagement at this client
stays a normal lifecycle state (10.09.2026: a return after a break is a new
order). On MD and cost orders the planner stops both cases at
``ACTION_DECIDE_PERSON`` (keep as history / resume / replace / remove is the
Delivery Lead's decision), which lands here as an ordinary non-auto action.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
import re
from typing import Mapping, Optional

from app.services.order_mail_planner import (
    ACTION_DECIDE_PERSON,
    ACTION_REACTIVATE,
    AUTO_ACTIONS,
    DocumentProposal,
)
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

# ── Kody powodów ─────────────────────────────────────────────────────────────
#
# Powód jest zdaniem po polsku dla człowieka; kod jest tym samym powodem dla
# maszyny. Godzinowa ponowna weryfikacja musi wiedzieć, CZY zamówienie czeka na
# podpis umowy (czeka bezterminowo, bez alarmowania Delivery Leada), czy utknęło
# na czymś innym (po trzech próbach idzie karta). Rozpoznawanie tego regexem po
# prozie zepsułoby się przy pierwszej korekcie stylistycznej, a cena pomyłki to
# albo zalanie DL kartami, albo cisza przy realnym problemie.
#
# KAŻDE dopisanie powodu MUSI nieść kod (pilnuje `test_order_mail_gate_and_planner`).
CODE_AUTOAPPLY_EXCLUDED_CLIENT = "autoapply_excluded_client"
CODE_CLIENT_NOT_CONFIRMED = "client_not_confirmed"
CODE_NO_CLIENT_POLICY = "no_client_policy"
CODE_FALLBACK_READ = "fallback_read"
CODE_NO_PEOPLE = "no_people"
CODE_PERSON_MATCH_UNCERTAIN = "person_match_uncertain"
CODE_PERSON_KNOWN_ELSEWHERE_IDLE = "person_known_elsewhere_idle"
CODE_PERSON_KNOWN_ELSEWHERE_OPEN = "person_known_elsewhere_open"
CODE_PERSON_NAMESAKES = "person_namesakes"
#: Osoby nie ma ani u tego klienta, ani nigdzie w bazie — zamówienie od klienta
#: wyprzedziło podpis umowy. Automat NIE zakłada kontraktora z PDF-a klienta:
#: kontrakt rodzi się z podpisanej umowy B2B, a nie z zamówienia.
CODE_PERSON_NEW_TO_SYSTEM = "person_new_to_system"
CODE_PERSON_MULTIPLE_CONTRACTS = "person_multiple_contracts"
CODE_TITLE_NOT_CONFIRMED = "title_not_confirmed"
CODE_ROW_EVIDENCE_MISSING = "row_evidence_missing"
CODE_ROW_EVIDENCE_COUNT = "row_evidence_count"
CODE_ROW_EVIDENCE_PERSON = "row_evidence_person"
CODE_ROW_EVIDENCE_UNCERTAIN = "row_evidence_uncertain"
CODE_ROW_EVIDENCE_RATE = "row_evidence_rate"
#: Okres z planu nie zgadza się z okresem wiersza z pól PDF albo — u klienta,
#: którego okres ustala reguła — nie został przez regułę potwierdzony
#: (audyt 22.09, FIN-MAIL-03).
CODE_ROW_EVIDENCE_PERIOD = "row_evidence_period"
#: Waluta dokumentu inna niż PLN — automat nie ma kursu (FIN-MAIL-02).
CODE_CURRENCY_FOREIGN = "currency_foreign"
CODE_READ_UNCERTAIN = "read_uncertain"
CODE_TEXT_TRUNCATED = "text_truncated"
CODE_OCR_CAPPED = "ocr_capped"
CODE_RATE_MISSING = "rate_missing"
CODE_RATE_OUT_OF_BAND = "rate_out_of_band"
CODE_RATE_DEVIATION = "rate_deviation"
CODE_MD_MISSING = "md_missing"
CODE_MD_SHARED_POOL = "md_shared_pool"
CODE_PLAN_BLOCKING = "plan_blocking"
#: Nowy kontraktor bez żywej umowy gdziekolwiek — zamówienie czeka na podpis.
CODE_PERSON_DECISION_NEW = "person_decision_new"
#: Osoba z trwającą współpracą u innego klienta albo kilku imienników.
CODE_PERSON_DECISION_AMBIGUOUS = "person_decision_ambiguous"
#: Współpraca u TEGO klienta się zakończyła — decyzja Delivery Leada.
CODE_PERSON_DECISION_ENDED = "person_decision_ended"
CODE_ACTION_NOT_AUTO = "action_not_auto"
CODE_PERIOD_INCOMPLETE = "period_incomplete"
CODE_PERIOD_REVERSED = "period_reversed"

# Powody wstrzykiwane POZA bramką (writer, wyłącznik automatu, ponowny odczyt
# AI). Mieszkają tutaj, żeby cały katalog kodów był w jednym pliku.
CODE_AUTOAPPLY_DISABLED = "autoapply_disabled"
CODE_WRITE_FAILED = "write_failed"
CODE_AI_RETRY_EXHAUSTED = "ai_retry_exhausted"
CODE_RECHECK_FAILED = "recheck_failed"
#: Nordea: dokument z tej skrzynki, który nie jest zamówieniem.
CODE_NON_ORDER = "non_order"
#: Wpis sprzed wdrożenia kodów albo powód zapisany bez kodu.
CODE_UNKNOWN = "unknown"

#: Mapa akcji planera bez rozstrzygnięcia osoby na kod.
_DECISION_CODES = {
    "new": CODE_PERSON_DECISION_NEW,
    "new_ambiguous": CODE_PERSON_DECISION_AMBIGUOUS,
    "ended": CODE_PERSON_DECISION_ENDED,
}


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
    #: Okres zamówienia ustala reguła klienta z etykiety dokumentu — musi być
    #: przez nią potwierdzony (confidence 1.0), inaczej kolejka (FIN-MAIL-03).
    document_period_authoritative: bool = False


@dataclass
class GateVerdict:
    verdict: str
    reasons: list[str] = field(default_factory=list)
    #: Kody powodów — ta sama długość i kolejność co ``reasons``.
    codes: list[str] = field(default_factory=list)

    @property
    def is_auto(self) -> bool:
        return self.verdict == VERDICT_AUTO


def _row_evidence_reasons(
    rows: list[ConsultantOrderRow], evidence: tuple[ConsultantOrderRow, ...]
) -> list[tuple[str, str]]:
    """Confirm each person's own rate/unit, never a sorted bag of amounts."""
    if not evidence:
        return [
            (
                CODE_ROW_EVIDENCE_MISSING,
                "Brak niezależnego potwierdzenia osób i stawek z pól dokumentu PDF",
            )
        ]
    if len(rows) != len(evidence):
        return [
            (
                CODE_ROW_EVIDENCE_COUNT,
                f"Liczba osób z modelu ({len(rows)}) ≠ z tabeli ({len(evidence)})",
            )
        ]
    reasons: list[tuple[str, str]] = []
    used: set[int] = set()
    for row in rows:
        matches = [
            i
            for i, source in enumerate(evidence)
            if _names_exactly_equivalent(row.consultant_name, source.consultant_name)
        ]
        if len(matches) != 1 or matches[0] in used:
            reasons.append(
                (
                    CODE_ROW_EVIDENCE_PERSON,
                    f"„{row.consultant_name}”: brak jednoznacznego potwierdzenia osoby w polach PDF",
                )
            )
            continue
        index = matches[0]
        used.add(index)
        source = evidence[index]
        if source.uncertain or source.rate_client is None or source.rate_unit is None:
            # Wiersz bywa niepewny przez nazwisko albo okres, nie tylko stawkę —
            # konkretny powód niesie odczyt („Odczyt niepewny: …").
            reasons.append(
                (
                    CODE_ROW_EVIDENCE_UNCERTAIN,
                    f"„{row.consultant_name}”: niepewny odczyt wiersza osoby z pól PDF",
                )
            )
        if (row.rate_client, row.rate_unit) != (source.rate_client, source.rate_unit):
            reasons.append(
                (
                    CODE_ROW_EVIDENCE_RATE,
                    f"„{row.consultant_name}”: stawka lub jednostka z modelu nie zgadza się z polem PDF tej osoby",
                )
            )
    return reasons


def _period_evidence_reasons(inp: GateInput) -> list[tuple[str, str]]:
    """Okres z planu kontra okres z pól dokumentu (FIN-MAIL-03).

    Dwa źródła dowodu. (1) Wiersz osoby odczytany deterministycznie z tabeli
    ma własny okres — plan musi go powtórzyć. (2) U klienta, którego okres
    ustala reguła z etykiety dokumentu, reguła musiała go faktycznie ustalić
    (confidence 1.0); data zostawiona przez model nie jest dowodem.
    """
    out: list[tuple[str, str]] = []
    ex = inp.extraction
    if inp.document_period_authoritative:
        missing = [
            label
            for key, label, required in (
                ("start_date", "data początku", True),
                ("end_date", "data końca", not inp.open_ended_period),
            )
            if required
            and getattr(ex, key) is not None
            and ex.confidence.get(key) != 1.0
        ]
        if missing:
            out.append(
                (
                    CODE_ROW_EVIDENCE_PERIOD,
                    "Okres zamówienia nie został potwierdzony regułą klienta w polu "
                    f"dokumentu ({', '.join(missing)})",
                )
            )
    for row_prop in inp.proposal.rows:
        sources = [
            source
            for source in inp.deterministic_rows
            if _names_exactly_equivalent(row_prop.row_name, source.consultant_name)
        ]
        if len(sources) != 1:
            continue  # brak jednoznacznego wiersza — mówi o tym _row_evidence_reasons
        source = sources[0]
        if (source.start_date and source.start_date != row_prop.start_date) or (
            source.end_date and source.end_date != row_prop.end_date
        ):
            out.append(
                (
                    CODE_ROW_EVIDENCE_PERIOD,
                    f"„{row_prop.row_name}”: okres z planu ({row_prop.start_date or '—'} – "
                    f"{row_prop.end_date or '—'}) różni się od okresu w polach PDF "
                    f"({source.start_date or '—'} – {source.end_date or '—'})",
                )
            )
    return out


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


def _known_elsewhere_code(res: ResolvedConsultant) -> str:
    """Kod dla osoby spoza rostera, która JEST w bazie.

    Trzy różne stany świata, trzy różne dalsze kroki: kilku imienników i osoba
    z trwającą współpracą u innego klienta wymagają człowieka, a osoba bez
    żadnej żywej umowy po prostu czeka na podpis.
    """
    if len(res.known_elsewhere_ids) > 1:
        return CODE_PERSON_NAMESAKES
    if res.known_elsewhere_open_ids:
        return CODE_PERSON_KNOWN_ELSEWHERE_OPEN
    return CODE_PERSON_KNOWN_ELSEWHERE_IDLE


def evaluate(inp: GateInput) -> GateVerdict:
    reasons: list[tuple[str, str]] = []
    ex = inp.extraction
    prop = inp.proposal

    # 0) przełączniki
    if prop.client_id in inp.excluded_client_ids:
        reasons.append(
            (
                CODE_AUTOAPPLY_EXCLUDED_CLIENT,
                "Automatyczny zapis jest wyłączony dla tego klienta",
            )
        )

    # 1) NIP albo jednoznaczny marker/domena PFRON i aktywny rekord z bazy.
    trusted_pfron = (
        inp.trusted_policy_identity == "pfron"
        and "PFRON" in inp.policies_applied
        and inp.identification_method in {"marker", "sender_domain"}
    )
    if inp.identification_method != "registry_id" and not trusted_pfron:
        reasons.append(
            (
                CODE_CLIENT_NOT_CONFIRMED,
                "Nie potwierdzono jednoznacznie klienta numerem rejestrowym ani zatwierdzoną regułą dokumentu",
            )
        )

    # 2) własna polityka + odczyt modelem (fallback regexowy nigdy nie autozapisuje)
    if not inp.policies_applied:
        reasons.append(
            (CODE_NO_CLIENT_POLICY, "Klient nie ma własnej polityki odczytu")
        )
    if ex.source != "claude":
        failure = f" (AI: {ex.ai_failure})" if ex.ai_failure else ""
        reasons.append(
            (
                CODE_FALLBACK_READ,
                f"Odczyt awaryjny{failure} — sprawdź zgodność pól z PDF",
            )
        )

    # 3) + 4) exact person; osoba spoza rostera nigdy nie jedzie automatem
    if not inp.resolved:
        reasons.append((CODE_NO_PEOPLE, "Brak osób do dopasowania"))
    decided_rows = {
        row.row_index for row in prop.rows if row.action == ACTION_DECIDE_PERSON
    }
    for res in inp.resolved:
        if res.match_kind not in (MATCH_EXACT, "none"):
            reasons.append(
                (CODE_PERSON_MATCH_UNCERTAIN, f"„{res.row_name}”: {res.reason}")
            )
        elif res.match_kind == "none":
            # Osoba, która w bazie JEST (imiennik albo ten sam człowiek pod
            # drugim rekordem tego klienta), wymaga człowieka: writer i tak by
            # odmówił, a tu odmowa jest widoczna w kolejce razem z tym, kogo
            # znaleziono. Osoby, której w bazie NIE MA, automat nie zakłada
            # wcale — zamówienie klienta wyprzedziło podpis umowy i czeka.
            # Wiersz zatrzymany już przez planera (MD/kosztowe,
            # ``ACTION_DECIDE_PERSON``) dostaje swoje zdanie w kroku 8; drugie
            # o tym samym tylko zaśmieciłoby kolejkę.
            if res.known_elsewhere_ids:
                reasons.append((_known_elsewhere_code(res), res.reason))
            elif res.row_index not in decided_rows:
                reasons.append(
                    (
                        CODE_PERSON_NEW_TO_SYSTEM,
                        f"„{res.row_name}”: nie ma jej wśród konsultantów tego "
                        "klienta ani w bazie — zamówienie czeka na podpisaną "
                        "umowę B2B",
                    )
                )
        elif len(res.live_contract_ids) > 1:
            reasons.append(
                (
                    CODE_PERSON_MULTIPLE_CONTRACTS,
                    f"„{res.row_name}”: kilka aktywnych kontraktów — wybierz właściwy",
                )
            )

    # 5) proweniencja: numer i okres z etykiet (confidence 1.0 = polityka), stawki
    #    wierszy potwierdzone deterministycznym ekstraktorem
    if ex.confidence.get("title") != 1.0:
        reasons.append(
            (
                CODE_TITLE_NOT_CONFIRMED,
                "Numer zamówienia nie został potwierdzony w oznaczonym polu dokumentu",
            )
        )
    reasons.extend(_row_evidence_reasons(ex.consultant_rows, inp.deterministic_rows))
    reasons.extend((code, text) for code, text in _period_evidence_reasons(inp))
    if ex.uncertain:
        actionable = [
            r
            for r in ex.uncertain_reasons
            if not _unused_total_mapping_reason(r, inp)
            and not _irrelevant_md_absence_reason(r, inp)
        ]
        reasons.extend(
            (CODE_READ_UNCERTAIN, f"Odczyt niepewny: {r}") for r in actionable
        )
        if not ex.uncertain_reasons:
            reasons.append((CODE_READ_UNCERTAIN, "Odczyt oznaczony jako niepewny"))

    # 6) kompletność tekstu
    if inp.document_truncated:
        reasons.append((CODE_TEXT_TRUNCATED, "Tekst dokumentu ucięty przed odczytem"))
    if inp.ocr_capped:
        reasons.append(
            (
                CODE_OCR_CAPPED,
                "Skan dłuższy niż limit OCR — lista osób może być niekompletna",
            )
        )

    # 7) stawka w paśmie + odchyłka od stawki efektywnej kontraktu
    for row_prop in prop.rows:
        if row_prop.rate_client is None or row_prop.rate_unit is None:
            reasons.append(
                (
                    CODE_RATE_MISSING,
                    f"„{row_prop.row_name}”: brak stawki albo jednostki",
                )
            )
            continue
        rate = Decimal(row_prop.rate_client)
        band = RATE_BANDS.get(row_prop.rate_unit)
        if band and not (band[0] <= rate <= band[1]):
            reasons.append(
                (
                    CODE_RATE_OUT_OF_BAND,
                    f"„{row_prop.row_name}”: stawka {rate} {row_prop.rate_unit} poza pasmem {band[0]}–{band[1]}",
                )
            )
        current = inp.current_rates.get(row_prop.contract_id or -1)
        if current and current[0] and current[1] == row_prop.rate_unit:
            deviation = abs(rate - current[0]) / current[0]
            if deviation > MAX_RATE_DEVIATION:
                reasons.append(
                    (
                        CODE_RATE_DEVIATION,
                        f"„{row_prop.row_name}”: stawka {rate} odbiega o {deviation:.0%} od obowiązującej {current[0]}",
                    )
                )

    # 7a) waluta: automat zapisuje wyłącznie PLN (brak kursu) — FIN-MAIL-02
    for row_prop in prop.rows:
        if row_prop.currency and row_prop.currency != "PLN":
            reasons.append(
                (
                    CODE_CURRENCY_FOREIGN,
                    f"„{row_prop.row_name}”: stawka w walucie {row_prop.currency} — "
                    "automat zapisuje wyłącznie kwoty w PLN, sprawdź i zastosuj ręcznie",
                )
            )

    # 7b) zamówienie MD wymaga liczby MD — przy osobie albo na całe zamówienie
    for row_prop in _md_rows(inp):
        if row_prop.md_total is None:
            reasons.append(
                (
                    CODE_MD_MISSING,
                    f"„{row_prop.row_name}”: zamówienie MD bez liczby MD — dokument nie "
                    "podaje jej ani przy osobie, ani na całe zamówienie",
                )
            )
    if _md_rows(inp) and md_scope(ex) == MD_SCOPE_ORDER:
        # Plan przenosi liczbę dokumentu na każdy wiersz, a zapis per osoba
        # dałby każdemu całą pulę. Wspólną pulę zakłada człowiek w oknie
        # zamówienia — automat jej nie dzieli.
        reasons.append(
            (
                CODE_MD_SHARED_POOL,
                "Dokument podaje jedną liczbę MD na całe zamówienie — załóż wspólny "
                "budżet MD ręcznie, automat nie dzieli puli między osoby",
            )
        )

    # 8) precondition + addytywność + atomowość + okres z dokumentu
    if prop.blocking:
        reasons.extend((CODE_PLAN_BLOCKING, r) for r in prop.blocking)
    for row_prop in prop.rows:
        if row_prop.action == ACTION_REACTIVATE and row_prop.existing_person_ids:
            # Powrót rozpoznany po samym nazwisku przy imienniku w bazie
            # (FIN-MAIL-07) — akcja jest automatyczna, ale ten wiersz nie.
            reasons.append(
                (
                    CODE_ACTION_NOT_AUTO,
                    f"„{row_prop.row_name}”: " + "; ".join(row_prop.reasons),
                )
            )
        if row_prop.action not in AUTO_ACTIONS:
            reasons.append(
                (
                    _DECISION_CODES.get(
                        row_prop.decision_kind or "", CODE_ACTION_NOT_AUTO
                    )
                    if row_prop.action == ACTION_DECIDE_PERSON
                    else CODE_ACTION_NOT_AUTO,
                    f"„{row_prop.row_name}”: "
                    + "; ".join(
                        row_prop.reasons
                        or ["Nie ustalono jednoznacznego miejsca zapisu"]
                    ),
                )
            )
        if not row_prop.start_date or (
            not row_prop.end_date and not inp.open_ended_period
        ):
            reasons.append(
                (
                    CODE_PERIOD_INCOMPLETE,
                    f"„{row_prop.row_name}”: okres niepełny w dokumencie (od {row_prop.start_date or '—'} do {row_prop.end_date or '—'})",
                )
            )
        elif row_prop.end_date and row_prop.start_date > row_prop.end_date:
            # Daty ISO porównują się jak tekst; odwrócony okres nigdy nie jest
            # poprawny, a tabela zamówień go nie odrzuci. Bez daty końca
            # (zamówienie bezterminowe, BIK) nie ma czego odwrócić.
            reasons.append(
                (
                    CODE_PERIOD_REVERSED,
                    f"„{row_prop.row_name}”: okres odwrócony w dokumencie ({row_prop.start_date} – {row_prop.end_date})",
                )
            )

    deduped = _dedupe(reasons)
    return GateVerdict(
        VERDICT_AUTO if not deduped else VERDICT_REVIEW,
        [text for _, text in deduped],
        [code for code, _ in deduped],
    )


def _dedupe(items: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Deduplikuje po TREŚCI — kod jedzie razem ze swoim zdaniem."""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for code, text in items:
        if text not in seen:
            seen.add(text)
            out.append((code, text))
    return out
