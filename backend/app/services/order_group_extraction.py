"""„Zczytaj i uzupełnij całe zamówienie" — plan zamówienia z jednego PDF-a.

Jedno okno „Nowe zamówienie" (09.2026) zastępuje dwa kroki: puste zamówienie
z numerem, a potem osobne dodawanie każdego konsultanta z osobnym odczytem
PDF-a. Ten moduł robi JEDEN odczyt dokumentu w trybie wszystkich osób (ten sam,
który od miesięcy działa na poczcie zamówień: ``order_mail_ingest``), stosuje
reguły klientowe i dla każdej rozpoznanej osoby dopasowuje kontrakt u klienta
(``order_consultant_match``).

Nic nie jest zapisywane. Wynik trafia do formularza, w którym Delivery Lead
potwierdza żółte odznaki, wskazuje osoby przy czerwonych i dopiero wtedy
zakłada zamówienie — jednym wywołaniem ``POST /order-groups`` z liniami.

Źródło każdej wartości jest częścią wyniku: stawka przychodowa i MD
pochodzą z pozycji PDF-a (``position_label``), stawka kosztowa — z kontraktu.
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.concurrency import run_in_threadpool

from app.models.candidate import Candidate
from app.models.contract import Contract, ContractStatus
from app.services.client_order_lines import ContractCostRate, contract_cost_rate
from app.services.cv_text_extractor import UnsupportedCvFormat
from app.services.fx_service import rates_to_pln
from app.services.order_consultant_match import (
    MATCH_AMBIGUOUS,
    ContractCandidate,
    raw_words,
    name_tokens,
    resolve_contract,
    split_name,
)
from app.services.order_document_text import OrderDocumentText, extract_order_text
from app.services.order_pdf_parser import (
    ConsultantOrderRow,
    OrderExtraction,
    _names_exactly_equivalent,
    drop_md_absence_reasons,
    md_scope,
    parse_order_document,
)
from app.services.order_policies import (
    PolicyContext,
    active_policies,
    apply_policies,
    apply_rate_kind,
    open_ended_period,
    parse_plan,
    prepare_document_text,
    prepare_parser_text,
)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
ALLOWED_EXTENSIONS = (".pdf", ".docx", ".doc")

# Wiersz pozycji tabeli: numer (1–4 cyfry), opcjonalna kropka/nawias, spacja
# i LITERA. Litera odsiewa daty („03.09.2026") i ilości („35,000 SZT").
# Numer pozycji na początku linii, dalej odstęp albo separator kolumn tabeli
# („1 | Anna Testowa" — tekst tabeli z kolumną „Poz.").
_POSITION_LINE = re.compile(r"^\s*(\d{1,4})[.)]?(?:\s+|\s*[|│]\s*)[^\W\d_]")
# Ile wierszy nad nazwiskiem szukać numeru pozycji (BIK: numer w wierszu
# pozycji, nazwisko w wierszu „Profil UR – …" tuż pod nim).
_POSITION_LOOKBACK = 4


class OrderDocumentError(Exception):
    """Plik nie nadaje się do odczytu — komunikat PL i status HTTP."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class PlanContractOption:
    contract_id: int
    candidate_id: int
    contractor_name: str
    status: str
    start_date: Optional[date]
    end_date: Optional[date]
    rate_cost: Optional[ContractCostRate]


@dataclass
class PlanLine:
    ordinal: int
    document_name: Optional[str]
    position_label: Optional[str]
    rate_revenue: Optional[Decimal]
    rate_revenue_unit: Optional[str]
    rate_revenue_gross: Optional[Decimal]
    md_total: Optional[Decimal]
    start_date: Optional[str]
    end_date: Optional[str]
    match_status: str
    match_reason: str
    contract: Optional[PlanContractOption] = None
    options: list[PlanContractOption] = field(default_factory=list)
    nearest_names: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ── Plik → tekst ────────────────────────────────────────────────────────────


async def read_order_document(
    filename: Optional[str], payload: bytes
) -> OrderDocumentText:
    """Walidacja pliku i tekst dokumentu (PDF natywny, OCR, DOCX)."""

    name = filename or "zamowienie.pdf"
    ext = os.path.splitext(name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise OrderDocumentError(415, "Tylko pliki PDF/DOCX/DOC")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise OrderDocumentError(413, "File too large")
    if not payload:
        raise OrderDocumentError(400, "Pusty plik")

    tmp_path: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=ext, delete=False, prefix="nexus_order_group_"
        ) as tmp:
            tmp.write(payload)
            tmp_path = tmp.name
        try:
            document = await run_in_threadpool(extract_order_text, tmp_path, name)
        except UnsupportedCvFormat as exc:
            raise OrderDocumentError(400, str(exc)) from exc
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    if not document.text.strip():
        raise OrderDocumentError(
            400,
            "Nie udało się odczytać tekstu z dokumentu "
            "(skan, plik zaszyfrowany lub nieobsługiwany format .doc?).",
        )
    return document


@dataclass
class DocumentReading:
    """Odczyt dokumentu z tym, czego plan potrzebuje od reguł klienta."""

    extraction: OrderExtraction
    applied_policies: list[str]
    text: str
    rate_unit_default: Optional[str]
    #: Wiersze osób wyciągnięte DETERMINISTYCZNIE regułą klienta (regex po
    #: tabeli PDF-a) — niezależny dowód dla stawek z modelu, jak w bramce
    #: poczty (``order_mail_gate._row_evidence_reasons``). Pusta = klient
    #: bez reguły tabeli osób.
    evidence_rows: list[ConsultantOrderRow] = field(default_factory=list)
    #: Dokument jednoosobowy bez nazwiska (BNP).
    single_consultant_document: bool = False
    #: Klient, u którego liczba MD z PDF-a nigdy nie jest używana (Orlen).
    ignores_document_md: bool = False
    #: Brak daty końca jest u klienta poprawnym odczytem (BIK: do wyczerpania MD).
    open_ended: bool = False
    #: Wariant, w którym dokument podaje liczbę MD (``per_consultant`` /
    #: ``order``); ``None`` = nie podaje — poprawny odczyt zamówienia kosztowego.
    md_scope: Optional[str] = None


async def extract_all_rows(
    document: OrderDocumentText, *, client_id: int, filename: Optional[str]
) -> DocumentReading:
    """Odczyt modelu + reguły klientowe.

    Wywołujący MUSI obudować to bramką kwoty AI (``ai_feature``).
    Dokument jednoosobowy bez nazwiska (BNP) idzie trybem zwykłym — w trybie
    wszystkich osób nie byłoby czego wypisać, a stawka i MD są polami dokumentu.
    """

    policies = active_policies(client_id)
    plan = parse_plan(policies)
    text = prepare_document_text(document.text, policies)
    parser_text = prepare_parser_text(text, policies)
    if plan.single_consultant_document:
        extraction = await parse_order_document(parser_text)
    else:
        extraction = await parse_order_document(parser_text, all_rows=True)
    extraction, applied = apply_policies(
        extraction,
        PolicyContext(document_text=text, filename=filename),
        policies,
    )
    extraction = apply_rate_kind(extraction, text, policies)
    # O tym, czy liczba MD jest potrzebna, decyduje typ zamówienia wybrany
    # w formularzu (kosztowe / MD per osoba / MD na całe zamówienie), a nie
    # model czytający PDF bez tej wiedzy — patrz `drop_md_absence_reasons`.
    extraction = drop_md_absence_reasons(extraction)
    evidence: list[ConsultantOrderRow] = []
    for policy in sorted(policies, key=lambda item: item.order):
        if policy.extract_rows is not None:
            evidence = policy.extract_rows(text)
            break
    return DocumentReading(
        extraction=extraction,
        applied_policies=applied,
        text=text,
        rate_unit_default=plan.rate_unit_default,
        evidence_rows=evidence,
        single_consultant_document=plan.single_consultant_document,
        # Reguła Orlenu działa wyłącznie przy wskazanej osobie (requires_target),
        # więc tutaj jej sedno — „MD z PDF-a nigdy" — trzeba zastosować wprost.
        ignores_document_md=any(policy.key == "orlen" for policy in policies),
        # „Bezterminowo" tylko gdy odczyt faktycznie nie ma daty końca — dokument
        # innego szablonu u tego klienta (reguła się nie zastosowała) ma swoją.
        open_ended=open_ended_period(policies) and extraction.end_date is None,
        md_scope=(
            None
            if any(policy.key == "orlen" for policy in policies)
            else md_scope(extraction)
        ),
    )


# ── Numer pozycji w dokumencie ──────────────────────────────────────────────


def _line_contains(line: str, tokens: tuple[str, ...]) -> bool:
    available = set(name_tokens(raw_words(line)))
    return bool(tokens) and all(token in available for token in tokens)


def document_position_labels(
    text: str, names: list[Optional[str]]
) -> list[Optional[str]]:
    """Numer pozycji tabeli, pod którą w dokumencie stoi dana osoba.

    Wyłącznie do opisu źródła („z PDF, poz. 10") — nigdy do wyboru wartości.
    Brak pewności = ``None`` i front podaje kolejność osoby zamiast numeru.
    Szukamy w linii z nazwiskiem i najwyżej kilku liniach nad nią, ale nie
    wyżej niż linia poprzedniej osoby: numer cudzej pozycji to gorsza
    informacja niż żadna.
    """

    lines = (text or "").splitlines()
    found: list[Optional[int]] = []
    for name in names:
        tokens = split_name(name).core if name else ()
        index = next(
            (i for i, line in enumerate(lines) if _line_contains(line, tokens)),
            None,
        )
        found.append(index)

    labels: list[Optional[str]] = []
    for index in found:
        if index is None:
            labels.append(None)
            continue
        earlier = [other for other in found if other is not None and other < index]
        lower = max(index - _POSITION_LOOKBACK, (max(earlier) + 1) if earlier else 0)
        label: Optional[str] = None
        for candidate in range(index, lower - 1, -1):
            match = _POSITION_LINE.match(lines[candidate])
            if match:
                label = match.group(1)
                break
        labels.append(label)
    # Ta sama linia dla dwóch osób = nie wiemy, czyja to pozycja.
    duplicated = {
        index for index in found if index is not None and found.count(index) > 1
    }
    return [
        None if index in duplicated else label for index, label in zip(found, labels)
    ]


# ── Kontrakty klienta ───────────────────────────────────────────────────────


async def load_client_contracts(db: AsyncSession, client_id: int) -> list[Contract]:
    """Wszystkie nieanulowane kontrakty klienta z nazwą kontraktora i stawką."""

    result = await db.execute(
        select(Contract)
        .options(
            selectinload(Contract.candidate),
            selectinload(Contract.candidate_rate_schedule),
        )
        .join(Candidate, Candidate.id == Contract.candidate_id)
        .where(
            Contract.client_id == client_id,
            Contract.status != ContractStatus.void,
        )
    )
    return list(result.scalars().unique())


def contractor_name(contract: Contract) -> str:
    candidate = contract.candidate
    if candidate is None:
        return ""
    return (
        f"{(candidate.name or '').strip()} {(candidate.lastname or '').strip()}".strip()
    )


def _status_value(status: object) -> str:
    return status.value if hasattr(status, "value") else str(status)


# ── Plan ────────────────────────────────────────────────────────────────────


def _row_key(row: ConsultantOrderRow) -> tuple:
    return (
        name_tokens(raw_words(row.consultant_name)),
        row.rate_client,
        row.rate_unit,
        row.md_total,
        row.start_date,
        row.end_date,
    )


def _document_rows(
    extraction: OrderExtraction, *, single_consultant_document: bool, ignores_md: bool
) -> list[ConsultantOrderRow]:
    """Wiersze osób bez dosłownych duplikatów.

    Wyłącznie dokument z definicji jednoosobowy (BNP) bez wierszy osób daje
    JEDNĄ kartę bez osoby z polami dokumentu — do ręcznego wskazania
    kontraktora. W dokumencie wieloosobowym stawka z nagłówka nie należy do
    nikogo konkretnego, więc odczyt bez wierszy nie tworzy żadnej karty.
    """

    rows: list[ConsultantOrderRow] = []
    seen: set[tuple] = set()
    for raw in extraction.consultant_rows:
        # Orlen: pozycje on-site/off-site tej samej osoby z tą samą stawką
        # zlewają się w jedną kartę, bo MD z PDF-a i tak nie jest używane.
        row = replace(raw, md_total=None) if ignores_md else raw
        key = _row_key(row)
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
    if rows or not single_consultant_document:
        return rows
    if extraction.rate_client is not None or extraction.md_total is not None:
        return [
            ConsultantOrderRow(
                consultant_name="",
                rate_client=extraction.rate_client,
                rate_unit=extraction.rate_unit,
                md_total=None if ignores_md else extraction.md_total,
                rate_client_gross=extraction.rate_client_gross,
                uncertain=extraction.uncertain,
            )
        ]
    return []


def _evidence_for(
    row: ConsultantOrderRow, evidence: list[ConsultantOrderRow]
) -> Optional[ConsultantOrderRow]:
    matches = [
        source
        for source in evidence
        if row.consultant_name
        and _names_exactly_equivalent(row.consultant_name, source.consultant_name)
    ]
    return matches[0] if len(matches) == 1 else None


def _reconcile_with_evidence(
    rate: Optional[Decimal],
    unit: Optional[str],
    md_total: Optional[Decimal],
    gross: Optional[Decimal],
    row: ConsultantOrderRow,
    evidence: list[ConsultantOrderRow],
) -> tuple[
    Optional[Decimal], Optional[str], Optional[Decimal], Optional[Decimal], list[str]
]:
    """Stawka z modelu kontra wiersz tej osoby z tabeli PDF-a (reguła klienta).

    Model bywa mylony sąsiednią kolumną (liczba MD odczytana jako stawka,
    „godzina" zamiast „dzień"). Gdy reguła klienta czyta tabelę PDF-a wprost
    i jednoznacznie znajduje tę osobę, jej wartości wygrywają; rozbieżność
    zostaje nazwana na karcie. Brak osoby w tabeli = ostrzeżenie, nie cisza.
    """

    if not evidence:
        return rate, unit, md_total, gross, []
    source = _evidence_for(row, evidence)
    if source is None:
        return (
            rate,
            unit,
            md_total,
            gross,
            [
                "Reguła klienta nie potwierdziła tej pozycji w tabeli PDF-a — "
                "porównaj stawkę i liczbę MD z dokumentem"
            ],
        )
    warnings: list[str] = []
    if source.uncertain or source.rate_client is None or source.rate_unit is None:
        warnings.append(
            "Tabela PDF-a nie daje pewnej stawki tej osoby — porównaj z dokumentem"
        )
        return rate, unit, md_total, gross, warnings
    if (rate, unit) != (source.rate_client, source.rate_unit):
        warnings.append(
            "Stawka lub jednostka odczytana przez AI różniła się od tabeli PDF-a "
            "— użyto wartości z tabeli"
        )
    if source.md_total is not None and md_total != source.md_total:
        if md_total is not None:
            warnings.append(
                "Liczba MD odczytana przez AI różniła się od tabeli PDF-a — "
                "użyto wartości z tabeli"
            )
        md_total = source.md_total
    return (
        source.rate_client,
        source.rate_unit,
        md_total,
        source.rate_client_gross,
        warnings,
    )


async def build_plan_lines(
    db: AsyncSession,
    *,
    client_id: int,
    reading: DocumentReading,
    today: date,
) -> list[PlanLine]:
    extraction = reading.extraction
    document_text = reading.text
    rate_unit_default = reading.rate_unit_default
    rows = _document_rows(
        extraction,
        single_consultant_document=reading.single_consultant_document,
        ignores_md=reading.ignores_document_md,
    )
    if not rows:
        return []

    contracts = await load_client_contracts(db, client_id)
    currency_rates = await rates_to_pln(
        db, {c.resolved_rate_candidate_currency for c in contracts}, today
    )
    by_id = {contract.id: contract for contract in contracts}
    candidates = [
        ContractCandidate(
            contract_id=contract.id,
            candidate_id=contract.candidate_id,
            contractor_name=contractor_name(contract),
            status=_status_value(contract.status),
            start_date=contract.start_date,
            end_date=contract.end_date,
        )
        for contract in contracts
        if contract.candidate_id is not None
    ]

    def option(candidate: ContractCandidate) -> PlanContractOption:
        contract = by_id[candidate.contract_id]
        return PlanContractOption(
            contract_id=candidate.contract_id,
            candidate_id=candidate.candidate_id,
            contractor_name=candidate.contractor_name,
            status=candidate.status,
            start_date=candidate.start_date,
            end_date=candidate.end_date,
            rate_cost=contract_cost_rate(
                contract, on=today, currency_rates=currency_rates
            ),
        )

    single_row = len(rows) == 1
    labels = document_position_labels(
        document_text, [row.consultant_name or None for row in rows]
    )
    lines: list[PlanLine] = []
    for ordinal, (row, label) in enumerate(zip(rows, labels), start=1):
        # Pola DOKUMENTU zastępują brak w wierszu tylko przy jednej osobie —
        # przy kilku nie wiadomo, czyja jest stawka z nagłówka.
        rate = row.rate_client
        unit = row.rate_unit
        md_total = row.md_total
        gross = row.rate_client_gross
        if single_row:
            if extraction.rate_client_md is not None:
                # Bank Pocztowy: polityka zamienia stawkę MD na godzinową z
                # zaokrągleniem W GÓRĘ; linia MD potrzebuje oryginału za MD —
                # ×8 z powrotem dałoby 1001,04 zamiast 1001.
                rate, unit = extraction.rate_client_md, "day"
            else:
                rate = rate if rate is not None else extraction.rate_client
                unit = unit or extraction.rate_unit
            md_total = md_total if md_total is not None else extraction.md_total
            gross = gross if gross is not None else extraction.rate_client_gross
        if reading.ignores_document_md:
            md_total = None
        if rate is not None and unit is None:
            unit = rate_unit_default

        warnings: list[str] = []
        rate, unit, md_total, gross, evidence_warnings = _reconcile_with_evidence(
            rate, unit, md_total, gross, row, reading.evidence_rows
        )
        warnings.extend(evidence_warnings)
        if reading.ignores_document_md and row.consultant_name:
            warnings.append(
                "U tego klienta liczby MD z PDF-a nie używamy — wpisz ją ręcznie"
            )
        if row.uncertain and row.uncertain_reason:
            warnings.append(row.uncertain_reason)
        elif row.uncertain:
            warnings.append(
                "Model nie był pewny tej pozycji — porównaj stawkę i liczbę MD z PDF-em"
            )
        if rate is not None and unit is None:
            warnings.append(
                "W pozycji nie znaleziono jednostki stawki — sprawdź, czy to stawka za MD"
            )

        match = resolve_contract(row.consultant_name or None, candidates)
        line = PlanLine(
            ordinal=ordinal,
            document_name=row.consultant_name or None,
            position_label=label,
            rate_revenue=rate,
            rate_revenue_unit=unit,
            rate_revenue_gross=gross,
            md_total=md_total,
            start_date=row.start_date,
            end_date=row.end_date,
            match_status=match.status,
            match_reason=match.reason,
            contract=option(match.contract) if match.contract else None,
            options=[option(item) for item in match.options]
            if match.status == MATCH_AMBIGUOUS
            else [],
            nearest_names=[item.contractor_name for item in match.nearest],
            warnings=warnings,
        )
        lines.append(line)

    return lines
