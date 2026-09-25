"""Pure order lifecycle plan, shared by ingestion, refresh and the writer.

Existing live orders take priority over drafts. A first order creates a draft,
any single existing draft is filled. A return after a gap creates a NEW order
next to the completed one — a completed order is never rewritten (decision of
2026-09-10): invoices were settled against it. A draft written from another
mail document for a disjoint period counts as a planned order, not an empty
draft (same number or overlapping period = its correction). Actual period
overlaps, ambiguous targets and revisions require review. On MD and cost
orders a person whose engagement ended, or who is not in the system, waits for
a human decision (``ACTION_DECIDE_PERSON``) instead of being revived or created.
A person missing from this client's roster keeps the initial-draft plan, and
when present in the base also carries the concrete finding
(``existing_person_ids``), so the queue proposes an identity to confirm instead
of a new contractor. The plan stays a draft so a human "Zastosuj" can still
write it, but the gate holds every such row: on any order type a contractor is
born from a signed B2B agreement, never from the client's purchase order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
import re
from typing import Optional

from app.services.order_consultant_match import (
    inactive_consultant_reason,
    unknown_consultant_reason,
)
from app.services.order_mail_resolver import ResolvedConsultant
from app.services.order_pdf_parser import (
    ConsultantOrderRow,
    OrderExtraction,
    _names_exactly_equivalent,
)

ACTION_FILL_DRAFT = "fill_draft"
ACTION_FUTURE = "future"
ACTION_NEW = "new"
ACTION_NEW_DRAFT = "new_draft"
#: Powrót po przerwie. Nazwa zostaje historyczna (utrwalone plany i etykiety
#: frontu), ale od 10.09.2026 znaczy „NOWE zamówienie na nowy okres, obok
#: zakończonego" — writer nie dotyka zakończonego zamówienia, więc akcja może
#: zostać automatyczna.
ACTION_REACTIVATE = "reactivate"
ACTION_UNCHANGED = "unchanged"
ACTION_REVISION = "revision"
ACTION_OVERLAP = "overlap"
ACTION_GROUP = "group"
ACTION_SKIP = "skip"
#: Zamówienie MD/kosztowe z osobą, której współpraca u klienta się zakończyła
#: albo której nie ma w systemie (ticket 09.2026, reguła ogólna dla wszystkich
#: klientów rozliczanych w MD lub budżetem). Automat NIE zgaduje: wznowienie
#: kontraktu, zapis historyczny, zastępstwo albo pominięcie osoby to decyzja
#: Delivery Leada. Podejmuje ją w oknie zamówienia (ten sam mechanizm co
#: „Nowe zamówienie" i „Uzupełnij zamówienie"), do którego kolejka prowadzi
#: z tym PDF-em.
ACTION_DECIDE_PERSON = "decide_person"
#: Wartości ``RowProposal.decision_kind`` — patrz opis pola.
DECISION_NEW = "new"
DECISION_NEW_AMBIGUOUS = "new_ambiguous"
DECISION_ENDED = "ended"
#: Typy zamówień, dla których osoba nieaktywna/nieznaleziona czeka na DECYZJĘ
#: człowieka w oknie zamówienia (``ACTION_DECIDE_PERSON``). Zamówienie okresowe
#: zostaje przy decyzji z 10.09.2026: powrót po przerwie to nowe zamówienie,
#: a nie wskrzeszenie zakończonego.
#:
#: UWAGA — to NIE jest lista typów, dla których nowa osoba jedzie automatem.
#: Osoby spoza rostera wstrzymuje BRAMKA, na każdym typie zamówienia
#: (``CODE_PERSON_NEW_TO_SYSTEM`` / ``_known_elsewhere_code``): plan zostaje
#: szkicem, żeby ręczne „Zastosuj" działało, ale automat go nie zapisze.
DECIDE_PERSON_ORDER_TYPES = frozenset({"md", "cost"})
AUTO_ACTIONS = frozenset(
    {
        ACTION_FILL_DRAFT,
        ACTION_FUTURE,
        ACTION_NEW,
        ACTION_NEW_DRAFT,
        ACTION_REACTIVATE,
        ACTION_UNCHANGED,
    }
)

PLACEHOLDER_TITLE = "(bez numeru)"

#: Powód dla dwóch pozycji tej samej osoby w jednym dokumencie (audyt 24.09, W2).
REPEATED_PERSON_REASON = (
    "Ta sama osoba ma w dokumencie więcej niż jedną pozycję (np. dwie stawki "
    "albo dwa okresy) — zdecyduj, które zamówienia założyć, i zapisz je ręcznie "
    "w oknie zamówienia"
)


@dataclass(frozen=True)
class ExistingOrder:
    id: int
    status: str
    title: str
    start_date: Optional[date]
    end_date: Optional[date]
    order_group_id: Optional[int] = None
    has_file: bool = False
    rate_client: Optional[Decimal] = None
    rate_unit: Optional[str] = None
    #: Zamówienie zapisane już z dokumentu mailowego (Activity ``order_mail_*``).
    #: Jego szkic niesie TAMTO zamówienie, a nie pusty szkic z zatrudnienia.
    from_order_mail: bool = False


@dataclass
class RowProposal:
    row_index: int
    row_name: str
    action: str
    candidate_id: Optional[int] = None
    contract_id: Optional[int] = None
    target_order_id: Optional[int] = None
    title: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    rate_client: Optional[str] = None
    rate_unit: Optional[str] = None
    md_total: Optional[str] = None
    reasons: list[str] = field(default_factory=list)
    previous_end_date: Optional[str] = None
    order_type: str = "periodic"
    #: Wartość CAŁEGO dokumentu — tylko przy dokumencie jednoosobowym. Przy
    #: kilku osobach kwota z nagłówka nie jest wartością zamówienia żadnej
    #: z nich, a skopiowana na każde zamówienie sumowałaby się N-krotnie
    #: w rankingu klientów (audyt 22.09, FIN-MAIL-01).
    total_value: Optional[str] = None
    #: Waluta z dokumentu (kod ISO). ``None`` = dokument jej nie podał —
    #: writer bierze wtedy walutę kontraktu. Inna niż PLN idzie do kolejki:
    #: automat nie ma kursu, a 110 EUR zapisane jako 110 PLN trafiało przez
    #: synchronizację na kontrakt (audyt 22.09, FIN-MAIL-02).
    currency: Optional[str] = None
    #: Kandydaci o tym imieniu i nazwisku spoza rostera klienta. Niepusta lista
    #: przy ``new_draft`` znaczy „nie proponuj nowego kontraktora bez pytania" —
    #: kolejka pokazuje wtedy podpowiedź zamiast samej etykiety akcji.
    existing_person_ids: list[int] = field(default_factory=list)
    #: Przy ``ACTION_DECIDE_PERSON``: CO dokładnie czeka na człowieka.
    #: ``new`` — nowy kontraktor bez żywej umowy gdziekolwiek (czeka na podpis),
    #: ``new_ambiguous`` — osoba jest w bazie z trwającą współpracą albo jest
    #: kilku imienników (pytanie do człowieka, nie do zegara),
    #: ``ended`` — współpraca u tego klienta się zakończyła.
    #: Godzinowa ponowna weryfikacja czyta to pole, więc nie da się go zgadnąć
    #: z tekstu powodu.
    decision_kind: Optional[str] = None


@dataclass
class DocumentProposal:
    client_id: int
    order_number: Optional[str]
    is_group_client: bool
    rows: list[RowProposal]
    blocking: list[str] = field(default_factory=list)

    @property
    def auto_eligible_actions(self) -> bool:
        return bool(self.rows) and all(r.action in AUTO_ACTIONS for r in self.rows)


def namesake_return_reason(ids: tuple[int, ...] | list[int]) -> str:
    """Zdanie dla powrotu po przerwie, gdy w bazie jest imiennik."""
    listing = ", ".join(f"#{i}" for i in ids)
    return (
        f"W bazie jest też inna osoba o tym imieniu i nazwisku ({listing}) — "
        "potwierdź, że to powrót tej samej osoby, i zastosuj ręcznie"
    )


def renewal_gap_phrase(days: int) -> str:
    """„Powrót po 1 dniu” / „po 32 dniach” — miejscownik (UAT B76)."""
    return f"Powrót po {days} {'dniu' if days == 1 else 'dniach'}"


def _iso(d: Optional[date]) -> Optional[str]:
    return d.isoformat() if d else None


_PFRON_PREFIX = re.compile(r"^zlecenie\s+nr\.?\s+", re.I)


def _digit_core(title: str) -> Optional[str]:
    """Cyfry numeru, gdy numer składa się WYŁĄCZNIE z cyfr.

    Dopuszczalny jest słowny przedrostek („SAP 4500030751”, „Zamówienie nr
    4500030751”): same litery, spacje, kropki, „#” i „:”. Ukośnik albo cyfra
    przed resztą znaczy, że numer ma strukturę („830/2026”) — wtedy ``None``.
    Pętla zamiast wyrażenia z zagnieżdżonym powtórzeniem, które przy długim
    tytule szkicu cofałoby się wykładniczo.
    """
    i = 0
    while i < len(title) and (title[i].isalpha() or title[i] in " .#:\t"):
        i += 1
    rest = title[i:].replace(" ", "")
    return rest if rest and rest.isascii() and rest.isdigit() else None


def titles_collide(a: Optional[str], b: Optional[str]) -> bool:
    """Czy dwa numery zamówienia to ten sam numer.

    Końcówka liczy się wyłącznie między numerami z samych cyfr (BIK:
    ``4500030751`` ↔ ``30751``). Do 25.09.2026 końcówkę brano z cyfr
    WYCIĄGNIĘTYCH z całego numeru, więc ``830/2026`` był tym samym co
    ``1830/2026``, a ``3/07/2026/BL`` tym samym co ``13/07/2026/BL`` — mail
    z nowym zamówieniem trafiał w cudze zamówienie jako jego korekta.
    Numer z separatorami albo literami porównujemy w całości, bez wielkości
    liter i spacji.
    """
    # PFRON's labelled title is the same identity as its historical bare number.
    # Strip only this explicit prefix; generic short digit extraction would
    # conflate unrelated order numbers such as ABC/22 and DEF/22.
    a = _PFRON_PREFIX.sub("", (a or "").strip())
    b = _PFRON_PREFIX.sub("", (b or "").strip())
    if not a or not b:
        return False
    if re.sub(r"\s+", "", a).lower() == re.sub(r"\s+", "", b).lower():
        return True
    da, db_ = _digit_core(a), _digit_core(b)
    if da is None or db_ is None:
        return False
    if len(da) >= 5 and len(db_) >= 5 and (da.endswith(db_) or db_.endswith(da)):
        return True
    return False


def _overlaps(order: ExistingOrder, start: date, end: Optional[str]) -> bool:
    """Czy okres zamówienia nachodzi na okres z dokumentu (brak końca = bez końca)."""
    return (order.end_date is None or order.end_date >= start) and (
        end is None
        or order.start_date is None
        or order.start_date <= date.fromisoformat(end)
    )


def _is_draft_shell(
    order: ExistingOrder, number: Optional[str], start: date, end: Optional[str]
) -> bool:
    """Szkic do uzupełnienia — chyba że niesie już zamówienie na INNY okres.

    Dwa zamówienia tej samej osoby przychodzą osobnymi mailami (Alior: wrzesień
    i październik–grudzień). Póki kontrakt nie jest podpisany, szkic wypełniony
    pierwszym PDF-em nie staje się aktywnym zamówieniem — bez tego warunku drugi
    PDF „uzupełniał" go i po cichu nadpisywał numer i okres pierwszego. Szkic
    „niesie zamówienie", gdy zapisano go z maila albo ma dołączony PDF
    zamówienia. Ten sam numer albo nachodzący okres to ten sam dokument (albo
    jego korekta), więc uzupełnienie wolno; rozłączny okres to osobne zamówienie.
    Szkic LINII zamówienia MD/kosztowego nigdy nie jest szkicem do
    uzupełnienia: ma własny cykl życia (budżet MD, zamiana kontraktora,
    decyzja po offboardingu), a writer wypełniał go jak zamówienie okresowe —
    numer, okres i stawka z PDF-a, bez budżetu i bez grupy (audyt 25.09.2026).
    Takim szkicem zajmuje się ``plan_document`` (``ACTION_GROUP``).
    """
    if order.status != "draft" or order.order_group_id is not None:
        return False
    carries_order = order.from_order_mail or order.has_file
    if not carries_order or titles_collide(order.title, number):
        return True
    return _overlaps(order, start, end)


def _period_for_row(
    row: ConsultantOrderRow,
    extraction: OrderExtraction,
    *,
    document_period_authoritative: bool = False,
) -> tuple[Optional[str], Optional[str]]:
    """Okres wiersza; u klienta z okresem z reguły — WYŁĄCZNIE okres dokumentu.

    Reguła klienta (BIK, Polkomtel, BNP, PFRON, Credit Agricole) ustala okres
    z etykiety dokumentu. Okres wiersza pochodzi wtedy od modelu i nie może
    wygrać z regułą — do 22.09.2026 wygrywał, więc np. zamówienie BIK
    (bezterminowe z reguły) dostawało datę końca zgadniętą przez model.
    Brak daty w regule zostaje brakiem (bramka odeśle do kolejki), a nie
    podmianą na datę modelu (audyt 22.09, FIN-MAIL-03).
    """
    if document_period_authoritative:
        return extraction.start_date, extraction.end_date
    return (
        row.start_date or extraction.start_date,
        row.end_date or extraction.end_date,
    )


def _rate_for_row(
    row: ConsultantOrderRow, extraction: OrderExtraction, *, single_person: bool
) -> tuple[Optional[Decimal], Optional[str], Optional[Decimal]]:
    """Stawka, jednostka i liczba MD wiersza — stawka i jednostka z JEDNEGO źródła.

    Pola dokumentu opisują osobę wyłącznie w dokumencie jednoosobowym. Przy
    kilku osobach „60 MD na zamówienie" to wspólna pula, a stawka z nagłówka
    nie jest stawką osoby, której wiersz jej nie podał — skopiowana na każdy
    wiersz dawała ręcznemu „Zastosuj" 3 × 60 MD i cudzą stawkę (audyt 24.09,
    W1; ta sama reguła co ``total_value``, FIN-MAIL-01).

    Jednostka idzie za stawką. Dokument pożycza jednostkę wierszowi tylko
    wtedy, gdy mówi o tej samej kwocie (albo nie ma własnej): Bank Pocztowy
    przelicza stawkę DOKUMENTU z MD na godziny, więc wiersz z 1200 zł za MD
    dostawał jednostkę „hour" i zapisywał się jako 1200 zł/h (W3).
    """
    if row.rate_client is not None:
        rate = row.rate_client
        unit = row.rate_unit or (
            extraction.rate_unit
            if extraction.rate_client is None or extraction.rate_client == rate
            else None
        )
    elif single_person:
        rate, unit = extraction.rate_client, extraction.rate_unit
    else:
        rate, unit = None, None
    if row.md_total is not None:
        md = row.md_total
    else:
        md = extraction.md_total if single_person else None
    return rate, unit, md


def _person_decision_reason(rp: RowProposal, res: ResolvedConsultant) -> Optional[str]:
    """Komunikat „nie ma już aktywnej współpracy / nie znaleziono" albo ``None``.

    Tylko dla zamówień MD i kosztowych. Tekst pochodzi z tego samego źródła co
    karta w oknie zamówienia (``order_consultant_match``), więc Delivery Lead
    widzi w kolejce dokładnie to zdanie, które zobaczy po otwarciu okna.
    """

    if rp.order_type not in DECIDE_PERSON_ORDER_TYPES:
        return None
    if res.match_kind == "none":
        return unknown_consultant_reason(rp.row_name)
    if res.is_unique_person and res.contract_status == "ended":
        ended_on = (
            date.fromisoformat(res.contract_end_date) if res.contract_end_date else None
        )
        return inactive_consultant_reason(rp.row_name, ended_on=ended_on)
    return None


def plan_document(
    *,
    client_id: int,
    extraction: OrderExtraction,
    resolved: list[ResolvedConsultant],
    existing_orders_by_contract: dict[int, list[ExistingOrder]],
    is_group_client: bool,
    today: date,
    order_type: Optional[str] = None,
    document_period_authoritative: bool = False,
) -> DocumentProposal:
    rows = extraction.consultant_rows
    proposal = DocumentProposal(
        client_id=client_id,
        order_number=extraction.title,
        is_group_client=is_group_client,
        rows=[],
    )
    if not rows:
        proposal.blocking.append("Dokument bez rozpoznanych osób")
        return proposal
    if not extraction.title:
        proposal.blocking.append("Brak numeru zamówienia")

    # Dokument ze stawką oznaczoną jako brutto (Erste, PFRON, rozpoznanie
    # ogólne): stawka przeszła ÷ 1,23, a wartość całkowita nie — jej charakter
    # (brutto czy netto) nie wynika z oznaczenia stawki i nie wolno go zgadywać.
    # Przeniesiona na zamówienie zawyżała przychód o 23% (audyt 24.09, S1).
    gross_document = extraction.rate_client_gross is not None or any(
        row.rate_client_gross is not None for row in rows
    )
    for row, res in zip(rows, resolved):
        start, end = _period_for_row(
            row,
            extraction,
            document_period_authoritative=document_period_authoritative,
        )
        rate, unit, md = _rate_for_row(row, extraction, single_person=len(rows) == 1)
        rp = RowProposal(
            row_index=res.row_index,
            row_name=row.consultant_name,
            action=ACTION_SKIP,
            candidate_id=res.candidate_id,
            contract_id=res.contract_id,
            title=extraction.title,
            start_date=start,
            end_date=end,
            rate_client=str(rate) if rate is not None else None,
            rate_unit=unit,
            md_total=str(md) if md is not None else None,
            order_type=order_type or ("md" if is_group_client else "periodic"),
            total_value=str(extraction.total_value)
            if extraction.total_value is not None
            and len(rows) == 1
            and not gross_document
            else None,
            currency=(extraction.currency or "").strip().upper() or None,
        )
        decision = _person_decision_reason(rp, res)
        if decision is not None:
            rp.action = ACTION_DECIDE_PERSON
            if res.match_kind != "none":
                rp.decision_kind = DECISION_ENDED
            elif res.is_new_without_live_contract:
                rp.decision_kind = DECISION_NEW
            else:
                rp.decision_kind = DECISION_NEW_AMBIGUOUS
            rp.reasons.append(decision)
            # „Nie znaleziono u tego klienta" i „jest w bazie pod innym
            # klientem" to dwa różne zdania — decyzję podejmuje ten sam
            # człowiek, więc widzi oba.
            if res.known_elsewhere_ids:
                rp.existing_person_ids = list(res.known_elsewhere_ids)
                rp.reasons.append(res.reason)
            proposal.rows.append(rp)
            continue
        if res.match_kind == "none":
            rp.action = ACTION_NEW_DRAFT
            # Szkic, nie decyzja: bramka i tak wstrzyma ten wiersz, a ręczne
            # „Zastosuj" bramki nie czyta — Delivery Lead zachowuje drogę dla
            # kontraktora bez umowy B2B (UoP, zlecenie, klient spoza generatora).
            # Osoba jest w bazie, tylko nie u tego klienta: po potwierdzeniu
            # writer dopnie istniejącą kartotekę, ale Delivery Lead musi
            # zobaczyć KOGO znaleziono, zanim kliknie — inaczej dokument
            # przypięty do zdublowanego rekordu klienta wygląda jak zwyczajny
            # nowy kontraktor.
            if res.known_elsewhere_ids:
                rp.existing_person_ids = list(res.known_elsewhere_ids)
                rp.reasons.append(res.reason)
            proposal.rows.append(rp)
            continue
        if not res.is_unique_person or res.contract_id is None:
            rp.reasons.append(res.reason or "Nie ustalono osoby/kontraktu")
            proposal.rows.append(rp)
            continue
        if not start:
            rp.reasons.append("Brak daty początku okresu w dokumencie")
            proposal.rows.append(rp)
            continue

        existing = existing_orders_by_contract.get(res.contract_id, [])
        new_start = date.fromisoformat(start)
        # Punkt odniesienia powrotu to wyłącznie samodzielne zamówienie
        # (okresowe/kosztowe). Linia grupy MD ma własny cykl życia (budżet,
        # zamiana kontraktora, decyzja o MD po offboardingu) i nie jest
        # „poprzednim zamówieniem" osoby — writer i tak jej nie zmieni.
        completed_return = [
            o
            for o in existing
            if o.order_group_id is None
            and o.status == "completed"
            and o.end_date
            and o.end_date < new_start
        ]
        if completed_return and not any(
            o.status in ("active", "paused", "draft") for o in existing
        ):
            target = max(completed_return, key=lambda o: (o.end_date, o.id))
            rp.action = ACTION_REACTIVATE
            rp.target_order_id = target.id
            rp.previous_end_date = _iso(target.end_date)
            rp.reasons.append(
                f"{renewal_gap_phrase((new_start - target.end_date).days)} "
                "od zakończenia poprzedniego zamówienia"
            )
            if res.namesake_ids:
                # Powrót rozpoznany wyłącznie po imieniu i nazwisku, a w bazie
                # jest też inna osoba o tym samym — automat nie zgaduje, czy
                # to ta sama osoba (audyt 22.09, FIN-MAIL-07).
                rp.existing_person_ids = list(res.namesake_ids)
                rp.reasons.append(namesake_return_reason(res.namesake_ids))
            proposal.rows.append(rp)
            continue
        same_number = [
            o
            for o in existing
            if o.status != "draft" and titles_collide(o.title, extraction.title)
        ]
        if len(same_number) == 1:
            target = same_number[0]
            target_unit = {"hourly": "hour", "daily": "day", "monthly": "month"}.get(
                target.rate_unit, target.rate_unit
            )
            if (
                target.start_date,
                _iso(target.end_date),
                target.rate_client,
                target_unit,
            ) == (new_start, end, rate, unit):
                rp.action = ACTION_UNCHANGED
                rp.target_order_id = target.id
                proposal.rows.append(rp)
                continue
        if same_number:
            rp.action = ACTION_REVISION
            rp.target_order_id = same_number[0].id
            rp.reasons.append(
                f"Zamówienie o tym numerze już istnieje (#{same_number[0].id}, "
                f"{_iso(same_number[0].start_date) or '—'} – {_iso(same_number[0].end_date) or 'bezterminowo'}) — porównaj"
            )
            proposal.rows.append(rp)
            continue

        open_live = [o for o in existing if o.status in ("active", "paused")]
        group_drafts = [
            o for o in existing if o.status == "draft" and o.order_group_id is not None
        ]
        shells = [
            o for o in existing if _is_draft_shell(o, extraction.title, new_start, end)
        ]
        # Szkic z innego PDF-a na rozłączny okres to zaplanowane zamówienie:
        # liczy się jak otwarte, więc ten dokument dostaje osobne zamówienie.
        # Szkic linii grupy tu nie wchodzi — obsługuje go gałąź ``ACTION_GROUP``.
        mail_drafts = [
            o
            for o in existing
            if o.status == "draft" and o not in shells and o not in group_drafts
        ]
        if group_drafts and not open_live:
            # Osoba czeka na linii zamówienia MD/kosztowego. Automat nie wypełni
            # tej linii (budżet i grupę prowadzi okno zamówienia) ani nie założy
            # obok niej zamówienia okresowego — rozdwoiłby współpracę.
            rp.action = ACTION_GROUP
            rp.reasons.append(
                "Osoba ma szkic linii zamówienia MD/kosztowego "
                f"(#{group_drafts[0].id}, {group_drafts[0].title}) — uzupełnij go "
                "w oknie zamówienia u tego klienta"
            )
            proposal.rows.append(rp)
            continue
        if len(shells) > 1 and not open_live:
            rp.reasons.append("Więcej niż jeden draft tej osoby — wybierz zamówienie")
            proposal.rows.append(rp)
            continue
        if shells and not open_live:
            rp.action = ACTION_FILL_DRAFT
            rp.target_order_id = shells[0].id
            proposal.rows.append(rp)
            continue

        open_orders = open_live + mail_drafts
        overlapping = [o for o in open_orders if _overlaps(o, new_start, end)]
        if overlapping:
            rp.action = ACTION_OVERLAP
            rp.target_order_id = overlapping[0].id
            rp.reasons.append(
                f"Okres nachodzi na otwarte zamówienie #{overlapping[0].id} "
                f"({overlapping[0].title}, do {_iso(overlapping[0].end_date) or 'bezterminowo'})"
            )
            proposal.rows.append(rp)
            continue
        rp.action = ACTION_FUTURE if open_orders else ACTION_NEW
        proposal.rows.append(rp)
    _hold_repeated_people(proposal.rows)
    return proposal


def _hold_repeated_people(rows: list[RowProposal]) -> None:
    """Dwie pozycje tej samej osoby w jednym PDF-ie — nigdy automatem.

    On-site 150 i off-site 130 albo dwa okresy tej samej osoby: planer dawał
    obu wierszom „nowe zamówienie”, a zabezpieczenie przed duplikatem w zapisie
    (kontrakt + numer + dokument) trafiało przy drugim wierszu w zamówienie
    założone dla pierwszego. Druga pozycja przepadała, a dokument szedł jako
    „Zastosowano” (audyt 24.09, W2). Które pozycje są osobnymi zamówieniami,
    a które jednym ze wspólną stawką, rozstrzyga człowiek.

    Ta sama osoba = ten sam kontrakt, a bez kontraktu (osoba spoza rostera) —
    to samo imię i nazwisko.
    """
    repeated: set[int] = set()
    for i, first in enumerate(rows):
        for second in rows[i + 1 :]:
            if first.contract_id is not None and second.contract_id is not None:
                same = first.contract_id == second.contract_id
            else:
                # Wiersz bez odczytanego nazwiska nie jest „tą samą osobą"
                # co inny taki wiersz — zatrzymuje go dopasowanie osoby.
                same = bool(first.row_name.strip()) and _names_exactly_equivalent(
                    first.row_name, second.row_name
                )
            if same:
                repeated.update((first.row_index, second.row_index))
    for rp in rows:
        if rp.row_index not in repeated:
            continue
        if rp.action in AUTO_ACTIONS:
            rp.action = ACTION_SKIP
        rp.reasons.append(REPEATED_PERSON_REASON)
