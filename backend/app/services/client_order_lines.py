"""Linie konsultantów zamówienia wielo-konsultantowego: budżet MD i jego zużycie.

Linia = zwykłe ``ClientOrder`` wpięte w ``ClientOrderGroup``, więc niesie już
kontrakt, kandydata, daty i status. Ten moduł dokłada to, czego wcześniej nie
było: budżet MD, jego topnienie z miesięcznych raportów i zamianę kontraktora.

Trzy reguły, na których stoi cała reszta:

1. **``md_remaining`` jest WYLICZANE, nie modyfikowane przyrostowo.**
   ``md_total - Σ konsumpcji + md_manual_adjustment``, przeliczane od zera przy
   każdej zmianie. To jest mechanizm idempotencji importu: powtórka miesiąca
   nadpisuje wiersz konsumpcji i przelicza pozostałość, zamiast odjąć MD drugi
   raz. Odejmowanie „na bieżąco" wymagałoby pamiętania, co już odjęto — czyli
   i tak tych samych wierszy, tylko z ryzykiem rozjazdu.

2. **Dopasowanie po nazwisku nigdy nie zgaduje.** Arkusz z Finansów nie ma
   numeru zamówienia. Jedno trafienie → zastosuj; zero → „brak aktywnego
   zamówienia"; więcej niż jedno → „wymaga przypisania" i czeka na człowieka.
   Automatyczny wybór „pierwszej lepszej" linii odjąłby MD nie temu klientowi
   i wyszedłby dopiero na fakturze.

3. **Zamiana kontraktora działa od dnia zamiany w przód.** Przelicza wyłącznie
   MD POZOSTAŁE; MD zaraportowane wcześniej rozlicza się stawką poprzednika,
   więc wpisy konsumpcji sprzed daty zamiany zostają nietknięte.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import (
    GROUP_STATUS_ACTIVE,
    ClientOrderGroup,
    ClientOrderGroupEvent,
)
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.job import Job
from app.models.md_consumption import (
    CONSUMPTION_SOURCE_IMPORT,
    ClientOrderMdConsumption,
)
from app.services.candidate_identity_quarantine import normalize_person_name_part
from app.services.fx_service import rates_to_pln
from app.services.multi_consultant_orders import (
    EVENT_MD_TRANSFER,
    format_md,
    is_multi_consultant_client,
    quantize_md,
)

ZERO = Decimal("0")
HOURS_PER_MD = Decimal("8")
STANDARD_WORKING_DAYS_PER_MONTH = Decimal("22")
MONEY_SCALE = Decimal("0.01")

# Nazwy miesięcy w MIANOWNIKU — wpis historii brzmi „Za lipiec 2026", a nie
# „Za 2026-07". Forma mianownikowa jest poprawna po przyimku „za" dla każdego
# z dwunastu miesięcy, więc nie potrzeba drugiej odmiany.
_POLISH_MONTHS: tuple[str, ...] = (
    "styczeń",
    "luty",
    "marzec",
    "kwiecień",
    "maj",
    "czerwiec",
    "lipiec",
    "sierpień",
    "wrzesień",
    "październik",
    "listopad",
    "grudzień",
)


# ── Miesiąc raportu ─────────────────────────────────────────────────────────


def month_bounds(period_month: str) -> tuple[date, date]:
    """``'2026-07'`` → (1 lipca, 31 lipca). Rzuca ``ValueError`` na śmieciach."""
    try:
        year_s, month_s = period_month.split("-")
        year, month = int(year_s), int(month_s)
        first = date(year, month, 1)
    except (ValueError, AttributeError) as exc:
        raise ValueError("Miesiąc musi być w formacie RRRR-MM (np. 2026-07)") from exc
    last = date(year, month, calendar.monthrange(year, month)[1])
    return first, last


def format_period_month(period_month: str) -> str:
    """``'2026-07'`` → ``'lipiec 2026'`` na potrzeby wpisu w historii.

    Śmieciowy kształt NIE wywraca zapisu — wraca surowa wartość. Ten tekst
    jest opisem zdarzenia, a nie danymi: wywrócenie importu na formatowaniu
    zabrałoby ze sobą także poprawnie rozliczone wiersze.
    """
    try:
        year_s, month_s = period_month.split("-")
        return f"{_POLISH_MONTHS[int(month_s) - 1]} {int(year_s)}"
    except (ValueError, AttributeError, IndexError):
        return period_month


# ── Dopasowanie po imieniu i nazwisku ───────────────────────────────────────


def name_tokens(full_name: str | None) -> frozenset[str]:
    """Nazwisko → zbiór znormalizowanych tokenów.

    Zbiór, a nie lista, bo arkusze zapisują ludzi raz jako „Jan Kowalski", raz
    jako „Kowalski Jan" — a to ta sama osoba. Normalizacja tokenów zdejmuje
    diakrytyki i wielkość liter (reużyta z modułu tożsamości kandydata, więc
    „Michał" i „Michal" nie rozjeżdżają się tutaj inaczej niż tam).
    """
    if not full_name:
        return frozenset()
    tokens = {
        normalized
        for part in str(full_name).split()
        if (normalized := normalize_person_name_part(part))
    }
    return frozenset(tokens)


def candidate_name_tokens(candidate: Candidate | None) -> frozenset[str]:
    if candidate is None:
        return frozenset()
    return name_tokens(f"{candidate.name or ''} {candidate.lastname or ''}")


# ── Kogo można dołożyć do zamówienia ────────────────────────────────────────
#
# Dwa źródła w JEDNEJ liście: osoby z kontraktem u tego klienta oraz pozostali
# aktywni konsultanci z bazy. Wcześniej picker pokazywał wyłącznie to pierwsze
# źródło, więc osoby, której nie rekrutowaliśmy u tego klienta, nie dało się
# dołożyć do zamówienia — a to jest zwyczajny scenariusz: konsultant kończy
# projekt u jednego klienta i wchodzi na zamówienie u drugiego.
#
# Świadomie NIE zwracamy nazwy klienta, u którego dana osoba pracuje TERAZ.
# Odbiorcą tej listy jest zespół JEDNEGO klienta; sama obsada innego klienta
# jest informacją handlową i nie jest tu do niczego potrzebna.

SOURCE_CLIENT_RECRUITMENT = "client_recruitment"
SOURCE_NEXUS_BASE = "nexus_base"

CONSULTANT_SOURCE_LABELS: dict[str, str] = {
    SOURCE_CLIENT_RECRUITMENT: "Rekrutacja u klienta",
    SOURCE_NEXUS_BASE: "Baza Nexus",
}

# „Aktywny konsultant" w całej bazie. `ending` jest w środku celowo: to nadal
# ktoś, kto dziś pracuje (kontrakt < 30 dni do końca), czyli dokładnie osoba,
# którą planuje się na kolejne zamówienie. Wycięcie jej ukryłoby najbardziej
# oczywistych kandydatów do obsady.
LIVE_CONTRACT_STATUSES: tuple[ContractStatus, ...] = (
    ContractStatus.active,
    ContractStatus.ending,
)

# Źródło „u tego klienta" ZACHOWUJE dotychczasową zawartość pickera — te same
# statusy co `client_orders.list_active_contracts_for_extension`, łącznie
# z `draft`. Ticket jest rozszerzeniem, nie zamianą, więc lista, którą operator
# widział wczoraj, musi być podzbiorem tej, którą zobaczy dziś.
CLIENT_CONTRACT_STATUSES: tuple[ContractStatus, ...] = LIVE_CONTRACT_STATUSES + (
    ContractStatus.draft,
)


@dataclass(frozen=True)
class ConsultantOption:
    """Jedna pozycja pickera „Konsultant" przy dodawaniu osoby do zamówienia."""

    candidate_id: int
    #: `None` = osoba nie ma kontraktu u tego klienta; zapis linii go utworzy.
    contract_id: Optional[int]
    first_name: str
    last_name: str
    full_name: str
    source: str
    #: Rekrutacja u TEGO klienta (źródło A). Dla bazy Nexus zawsze `None`.
    job_title: Optional[str]
    #: Aktualna stawka kosztowa z aktywnego/kończącego się kontraktu
    #: TEJ osoby u TEGO klienta. To tylko podpowiedź dla nowej linii
    #: zamówienia — jej późniejsza edycja nie zapisuje nic na kontrakcie.
    suggested_rate_cost: Optional[Decimal]
    #: Surowa efektywna stawka kontraktu. Osobne pole zachowuje kompatybilność:
    #: starszy frontend nadal czyta ``suggested_rate_cost`` jako PLN/MD.
    suggested_contract_rate_cost: Optional[Decimal]
    #: Jednostka, waluta i kurs należą do SUROWEJ stawki kontraktu. Bez nich
    #: frontend nie umiałby bezpiecznie przeliczyć jej do kanonicznego PLN/MD.
    suggested_rate_cost_unit: Optional[RateUnit]
    suggested_rate_cost_currency: Optional[str]
    suggested_rate_cost_rate_to_pln: Optional[Decimal]
    #: Co najmniej dwa nieanulowane kontrakty tej osoby u klienta mają różne
    #: efektywne stawki kosztowe. Front pokazuje wtedy ostrzeżenie zamiast
    #: udawać, że podpowiedź jest jedyną możliwą wartością.
    has_different_client_contract_rates: bool

    @property
    def source_label(self) -> str:
        return CONSULTANT_SOURCE_LABELS.get(self.source, self.source)


def _option(
    *,
    candidate_id: int,
    contract_id: Optional[int],
    name: Optional[str],
    lastname: Optional[str],
    source: str,
    job_title: Optional[str] = None,
    suggested_rate_cost: Optional[Decimal] = None,
    suggested_contract_rate_cost: Optional[Decimal] = None,
    suggested_rate_cost_unit: Optional[RateUnit] = None,
    suggested_rate_cost_currency: Optional[str] = None,
    suggested_rate_cost_rate_to_pln: Optional[Decimal] = None,
    has_different_client_contract_rates: bool = False,
) -> ConsultantOption:
    first = (name or "").strip()
    last = (lastname or "").strip()
    return ConsultantOption(
        candidate_id=candidate_id,
        contract_id=contract_id,
        first_name=first,
        last_name=last,
        # Osoba bez imienia i nazwiska (import zostawia „?") nadal musi być
        # wybieralna — pusty wiersz nie dałby się kliknąć świadomie.
        full_name=f"{first} {last}".strip() or f"#{candidate_id}",
        source=source,
        job_title=job_title,
        suggested_rate_cost=suggested_rate_cost,
        suggested_contract_rate_cost=suggested_contract_rate_cost,
        suggested_rate_cost_unit=suggested_rate_cost_unit,
        suggested_rate_cost_currency=suggested_rate_cost_currency,
        suggested_rate_cost_rate_to_pln=suggested_rate_cost_rate_to_pln,
        has_different_client_contract_rates=has_different_client_contract_rates,
    )


def _contract_recency_key(contract: Contract) -> tuple[date, int]:
    """Deterministyczny wybór najnowszego kontraktu w tej samej klasie statusu."""
    return (contract.start_date or date.min, contract.id)


def _rate_suggestion(
    contracts: list[Contract],
    *,
    on: date,
    currency_rates: dict[str, Optional[Decimal]],
) -> tuple[
    Optional[Decimal],
    Optional[Decimal],
    Optional[RateUnit],
    Optional[str],
    Optional[Decimal],
    bool,
    Optional[int],
]:
    """Podpowiedź PLN/MD i surowa stawka kontraktu + metadane/rozbieżność.

    `active` i `ending` są biznesowo żywe (cron przenosi kontrakt do
    `ending` już 30 dni przed końcem), więc oba kwalifikują się do
    podpowiedzi. Stawkę rozwiązujemy z harmonogramu na dzień odczytu, a nie
    z cache'owanej kolumny `contracts.rate_candidate`, która może być
    nieaktualna po wejściu w życie zaplanowanego aneksu.

    ``suggested_rate_cost`` zachowuje swój historyczny kontrakt: kanoniczne
    PLN/MD, żeby starszy frontend nie zapisał surowych 60 PLN/h jako 60 PLN/MD.
    Osobne ``suggested_contract_rate_cost`` niesie dokładnie efektywną stawkę
    z kontraktu w jej jednostce i walucie. Brak kursu waluty obcej zachowuje
    dotychczasową bezpieczną odmowę podpowiedzi; nigdy nie udajemy kursu 1:1.

    Ostrzeżenie porównuje wszystkie nieanulowane kontrakty tej osoby u TEGO
    klienta, także historyczne, po tej samej kanonicznej wartości co pole
    zgodności: godzina × 8, dzień × 1, miesiąc ÷ 22, na końcu FX. Ta
    normalizacja nigdy nie zmienia osobnego pola surowego.
    ``billing_hours_per_month`` nie opisuje długości MD i nie może uczestniczyć
    w tym przeliczeniu. Brak stawki/kursu nie jest inną stawką.
    """

    def rate_per_md_pln(contract: Contract) -> Optional[Decimal]:
        raw_rate = contract.effective_candidate_rate(on)
        currency = (contract.currency or "PLN").upper()
        rate_to_pln = currency_rates.get(currency)
        if raw_rate is None or rate_to_pln is None:
            return None

        rate = Decimal(str(raw_rate))
        unit = RateUnit(contract.rate_unit)
        if unit == RateUnit.hourly:
            rate_per_md = rate * HOURS_PER_MD
        elif unit == RateUnit.daily:
            rate_per_md = rate
        else:  # RateUnit.monthly
            rate_per_md = rate / STANDARD_WORKING_DAYS_PER_MONTH
        # Linia zapisuje Numeric(12,2), więc pole zgodności i ostrzeżenie
        # operują dokładnie na wartościach, które mogą się różnić po zapisie.
        return (rate_per_md * rate_to_pln).quantize(MONEY_SCALE, rounding=ROUND_HALF_UP)

    live = [c for c in contracts if c.status in LIVE_CONTRACT_STATUSES]
    current = max(live, key=_contract_recency_key) if live else None
    suggested_per_md_pln = rate_per_md_pln(current) if current is not None else None
    suggested_contract_rate: Optional[Decimal] = None
    suggested_unit: Optional[RateUnit] = None
    suggested_currency: Optional[str] = None
    suggested_rate_to_pln: Optional[Decimal] = None
    if current is not None:
        current_rate = current.effective_candidate_rate(on)
        current_currency = (current.currency or "PLN").upper()
        current_rate_to_pln = currency_rates.get(current_currency)
        if current_rate is not None and suggested_per_md_pln is not None:
            suggested_contract_rate = Decimal(str(current_rate))
            suggested_unit = RateUnit(current.rate_unit)
            suggested_currency = current_currency
            suggested_rate_to_pln = current_rate_to_pln

    distinct_rates = {
        rate.normalize()
        for contract in contracts
        if contract.status != ContractStatus.void
        and (rate := rate_per_md_pln(contract)) is not None
    }
    return (
        suggested_per_md_pln,
        suggested_contract_rate,
        suggested_unit,
        suggested_currency,
        suggested_rate_to_pln,
        len(distinct_rates) > 1,
        current.id if current else None,
    )


def _sort_key(option: ConsultantOption) -> tuple[str, str, int]:
    """Alfabetycznie po imieniu, po kluczu bez diakrytyków.

    Sortowanie robimy w Pythonie, a nie `ORDER BY` w bazie, bo „Łukasz"
    w SQL-u wylądowałby za „Zbigniewem". Powodem NIE jest brak rozszerzenia
    `unaccent` (tak mówił poprzedni komentarz i wysyłał następną osobę
    w ślepą uliczkę: `unaccent` nie ma wpływu na `ORDER BY`). Powodem jest
    KOLACJA: prod stoi na `postgres:16-alpine`, czyli musl, a musl nie
    implementuje żadnej kolacji — porównanie tekstu degraduje się do porządku
    bajtowego, w którym Ł (U+0142) jest większe niż z (0x7A). Zmierzone na tym
    samym tagu obrazu: `SELECT 'Łukasz' < 'Zbigniew'` zwraca `f`, a katalog
    i tak raportuje `datcollate = en_US.utf8`, więc odczyt `pg_database`
    daje złą odpowiedź.

    Ten sam normalizator co przy dopasowaniu nazwisk, żeby kolejność i wyniki
    wyszukiwania nie rozjeżdżały się między sobą. Odpowiednik po stronie SQL
    (ten sam fold, przez `translate()`) to `api.clients.polish_alphabetical_key`.
    """
    return (
        normalize_person_name_part(option.first_name),
        normalize_person_name_part(option.last_name),
        option.candidate_id,
    )


def _search_parts(option: ConsultantOption) -> list[str]:
    return [
        normalized
        for part in f"{option.first_name} {option.last_name}".split()
        if (normalized := normalize_person_name_part(part))
    ]


def option_matches_query(option: ConsultantOption, query: str) -> bool:
    """Czy pozycja pasuje do wpisanego imienia i nazwiska.

    Zapytanie jest rozbijane na tokeny i KAŻDY musi trafić w którąś część
    nazwiska — dlatego „Jan Kowalski" zwraca Jana Kowalskiego, a nie wszystkich
    Janów i wszystkich Kowalskich. O to chodzi w wymaganiu „dokładne
    dopasowanie po kombinacji imię + nazwisko, a nie po pojedynczym fragmencie".

    Token dopasowuje się PREFIKSEM, nie równością. Równość byłaby pułapką:
    „Anna Kowal" wpisane w trakcie pisania nie zwracałoby nic, a pusta lista
    czyta się jak „nie ma takiej osoby w bazie" — i kończy założeniem duplikatu.
    Pełne imię i nazwisko wpisane w całości i tak zawęża wynik do jednej osoby.
    """
    tokens = [
        normalized
        for part in str(query or "").split()
        if (normalized := normalize_person_name_part(part))
    ]
    if not tokens:
        return True
    parts = _search_parts(option)
    return all(any(part.startswith(token) for part in parts) for token in tokens)


async def list_consultant_options(
    db: AsyncSession,
    *,
    client_id: int,
    query: str = "",
    limit: int = 100,
) -> tuple[list[ConsultantOption], int]:
    """Scalona, posortowana lista kandydatów na linię zamówienia.

    Zwraca `(pozycje przycięte do limitu, liczba wszystkich pasujących)`.
    Licznik jest częścią kontraktu, a nie ozdobą: bez niego przycięcie listy
    byłoby cichym obcięciem, a operator czytałby „to wszyscy" tam, gdzie jest
    „tylu się zmieściło".
    """
    options: list[ConsultantOption] = []
    seen: set[int] = set()

    # Zapytania listy nadal wyciągają KOLUMNY, nie pełne encje: picker
    # potrzebuje nazwiska i tytułu, a hydratacja wszystkich relacji kontraktu
    # kosztowałaby tysiące obiektów. Pełne encje pobieramy niżej wyłącznie
    # dla kontraktów tych kandydatów i tylko z harmonogramem stawki.

    # ── A. Kontrakty u TEGO klienta ────────────────────────────────────────
    client_rows = list(
        (
            await db.execute(
                select(
                    Contract.id,
                    Candidate.id,
                    Candidate.name,
                    Candidate.lastname,
                    Job.title,
                    Contract.status,
                    Contract.start_date,
                )
                # JOIN, nie `candidate_id IS NOT NULL`: umowa osieroconego
                # kandydata (`ON DELETE SET NULL`) nie ma kogo pokazać.
                .join(Candidate, Candidate.id == Contract.candidate_id)
                .outerjoin(Job, Job.id == Contract.job_id)
                .where(
                    Contract.client_id == client_id,
                    Contract.status.in_(CLIENT_CONTRACT_STATUSES),
                )
            )
        ).all()
    )

    # Historia jest potrzebna WYŁĄCZNIE dla osób, które i tak mają trafić
    # do źródła A. `selectinload` dociąga autorytatywny harmonogram stawki;
    # bez niego resolver w async próbowałby lazy-loadu i kończył 500.
    client_candidate_ids = {row[1] for row in client_rows}
    contracts_by_candidate: dict[int, list[Contract]] = {}
    if client_candidate_ids:
        history_result = await db.execute(
            select(Contract)
            .options(selectinload(Contract.candidate_rate_schedule))
            .where(
                Contract.client_id == client_id,
                Contract.candidate_id.in_(client_candidate_ids),
                Contract.status != ContractStatus.void,
            )
        )
        for contract in history_result.scalars():
            if contract.candidate_id is not None:
                contracts_by_candidate.setdefault(contract.candidate_id, []).append(
                    contract
                )

    today = date.today()
    currency_rates = await rates_to_pln(
        db,
        {
            (contract.currency or "PLN").upper()
            for contracts in contracts_by_candidate.values()
            for contract in contracts
        },
        today,
    )

    rows_by_candidate: dict[int, list[tuple]] = {}
    for row in client_rows:
        rows_by_candidate.setdefault(row[1], []).append(row)

    for candidate_id, rows in rows_by_candidate.items():
        contracts = contracts_by_candidate.get(candidate_id, [])
        (
            suggested_rate,
            suggested_contract_rate,
            suggested_rate_unit,
            suggested_rate_currency,
            suggested_rate_to_pln,
            has_different_rates,
            current_contract_id,
        ) = _rate_suggestion(contracts, on=today, currency_rates=currency_rates)

        # Aktywny/kończący się kontrakt wygrywa z nowszym szkicem. Dopiero
        # gdy nie ma żywego kontraktu, wybieramy najnowszy draft — zachowuje to
        # dotychczasową listę, ale nigdy nie podpowiada draftu jako „aktywnego".
        chosen = next((row for row in rows if row[0] == current_contract_id), None)
        if chosen is None:
            chosen = max(rows, key=lambda row: (row[6] or date.min, row[0]))
        contract_id, _, name, lastname, job_title, _, _ = chosen

        seen.add(candidate_id)
        options.append(
            _option(
                candidate_id=candidate_id,
                contract_id=contract_id,
                name=name,
                lastname=lastname,
                source=SOURCE_CLIENT_RECRUITMENT,
                job_title=job_title,
                suggested_rate_cost=suggested_rate,
                suggested_contract_rate_cost=suggested_contract_rate,
                suggested_rate_cost_unit=suggested_rate_unit,
                suggested_rate_cost_currency=suggested_rate_currency,
                suggested_rate_cost_rate_to_pln=suggested_rate_to_pln,
                has_different_client_contract_rates=has_different_rates,
            )
        )

    # ── B. Pozostali aktywni konsultanci z bazy ────────────────────────────
    # Filtrujemy po `seen`, a nie po `client_id != ...`: osoba z zakończonym
    # kontraktem u tego klienta i żywym u innego NIE jest w źródle A, więc musi
    # się tu pojawić — inaczej wypadłaby z listy w całości.
    #
    # `GROUP BY` po kandydacie zwija konsultanta z kilkoma żywymi kontraktami
    # do jednego wiersza JUŻ W BAZIE. Kontrakt i tak nie jedzie na drut (osoba
    # z tego źródła nie ma go u tego klienta), więc nie ma czego wybierać
    # między nimi — a bez zwijania jedna osoba potrafiła nadjechać kilka razy
    # tylko po to, żeby wypaść na dedupie w Pythonie.
    base_rows = await db.execute(
        select(Candidate.id, Candidate.name, Candidate.lastname)
        .join(Contract, Contract.candidate_id == Candidate.id)
        .where(Contract.status.in_(LIVE_CONTRACT_STATUSES))
        .group_by(Candidate.id, Candidate.name, Candidate.lastname)
    )
    for candidate_id, name, lastname in base_rows:
        if candidate_id in seen:
            continue
        seen.add(candidate_id)
        options.append(
            _option(
                candidate_id=candidate_id,
                contract_id=None,
                name=name,
                lastname=lastname,
                source=SOURCE_NEXUS_BASE,
            )
        )

    matching = [o for o in options if option_matches_query(o, query)]
    matching.sort(key=_sort_key)
    return matching[:limit], len(matching)


# ── Odczyt linii ────────────────────────────────────────────────────────────


def _line_query():
    """Linie MD z kompletem relacji potrzebnych do prezentacji.

    ``selectinload`` na kontrakcie i kandydacie jest OBOWIĄZKOWY: w async
    SQLAlchemy leniwe doczytanie relacji leci ``MissingGreenlet`` — 500 bez
    nagłówków CORS, czyli w przeglądarce „Network Error" bez żadnej wskazówki.
    """
    return (
        select(ClientOrder)
        .options(
            selectinload(ClientOrder.contract).selectinload(Contract.candidate),
            selectinload(ClientOrder.md_consumptions),
            selectinload(ClientOrder.predecessor)
            .selectinload(ClientOrder.contract)
            .selectinload(Contract.candidate),
        )
        .where(ClientOrder.order_group_id.isnot(None))
    )


async def lines_for_group(db: AsyncSession, group_id: int) -> list[ClientOrder]:
    result = await db.execute(
        _line_query()
        .where(ClientOrder.order_group_id == group_id)
        .order_by(ClientOrder.start_date.asc().nullsfirst(), ClientOrder.id.asc())
    )
    return list(result.scalars())


@dataclass(frozen=True)
class LineMatch:
    """Kandydat na dopasowanie wiersza importu."""

    order: ClientOrder
    group: ClientOrderGroup
    consultant_name: str


async def active_md_lines(db: AsyncSession, period_month: str) -> list[LineMatch]:
    """Wszystkie AKTYWNE linie MD obowiązujące w danym miesiącu.

    Linia obowiązuje w miesiącu, jeśli jej okres zachodzi na ten miesiąc
    choćby jednym dniem — miesiąc rozliczeniowy dzieli się między poprzednika
    i następcę dokładnie w miesiącu zamiany kontraktora, więc porównanie
    z jednym dniem (np. pierwszym) gubiłoby jedną ze stron.

    Filtr po liście klientów jest tutaj celowo, nie tylko w widoku: klient
    zdjęty z ``MULTI_CONSULTANT_ORDER_CLIENT_IDS`` przestaje pokazywać te
    linie w interfejsie, więc import nie może dalej po cichu odejmować im MD —
    powstałby stan niewidoczny i niemożliwy do poprawienia z aplikacji.
    """
    first, last = month_bounds(period_month)
    result = await db.execute(
        _line_query()
        .options(selectinload(ClientOrder.order_group))
        .where(
            ClientOrder.md_total.isnot(None),
            ClientOrder.status == ClientOrderStatus.active,
            (ClientOrder.start_date.is_(None)) | (ClientOrder.start_date <= last),
            (ClientOrder.end_date.is_(None)) | (ClientOrder.end_date >= first),
        )
    )
    matches: list[LineMatch] = []
    for order in result.scalars():
        group = order.order_group
        if group is None or not is_multi_consultant_client(order.client_id):
            continue
        candidate = order.contract.candidate if order.contract else None
        display = (
            f"{candidate.name or ''} {candidate.lastname or ''}".strip()
            if candidate
            else ""
        )
        matches.append(LineMatch(order=order, group=group, consultant_name=display))
    return matches


async def active_cost_lines(db: AsyncSession, period_month: str) -> list[LineMatch]:
    """Linie należące do AKTYWNYCH zamówień KOSZTOWYCH obowiązujących w miesiącu.

    Lustro ``active_md_lines``, ale z dwiema świadomymi różnicami:

    * linia kosztowa NIE ma budżetu MD (``md_total IS NULL``), więc filtr po
      ``md_total`` byłby tu dokładnie odwrotny do potrzeby,
    * pytamy o stan GRUPY, nie tylko linii — z wyczerpanego zamówienia nie
      wolno już nic zdejmować, a z zakończonego tym bardziej.

    Filtr po liście klientów kosztowych stoi tutaj, nie tylko w widoku: klient
    zdjęty z ``COST_ORDER_CLIENT_IDS`` przestaje pokazywać te zamówienia
    w interfejsie, więc import nie może dalej po cichu zdejmować z nich kwot.
    """
    from app.services.cost_orders import is_cost_order_client

    first, last = month_bounds(period_month)
    result = await db.execute(
        _line_query()
        .join(ClientOrderGroup, ClientOrder.order_group_id == ClientOrderGroup.id)
        .options(selectinload(ClientOrder.order_group))
        .where(
            ClientOrderGroup.is_cost_based.is_(True),
            ClientOrderGroup.status == GROUP_STATUS_ACTIVE,
            ClientOrder.status.in_([ClientOrderStatus.active, ClientOrderStatus.draft]),
            (ClientOrder.start_date.is_(None)) | (ClientOrder.start_date <= last),
            (ClientOrder.end_date.is_(None)) | (ClientOrder.end_date >= first),
        )
    )
    matches: list[LineMatch] = []
    for order in result.scalars():
        group = order.order_group
        if group is None or not is_cost_order_client(order.client_id):
            continue
        candidate = order.contract.candidate if order.contract else None
        display = (
            f"{candidate.name or ''} {candidate.lastname or ''}".strip()
            if candidate
            else ""
        )
        matches.append(LineMatch(order=order, group=group, consultant_name=display))
    return matches


async def active_shared_md_lines(
    db: AsyncSession, period_month: str
) -> list[LineMatch]:
    """Aktywne linie wspólnej puli MD Cyfrowego Polsatu w danym miesiącu.

    To osobna pula na grupie, więc jej linie celowo mają ``md_total IS NULL``
    i nie mogą przejść przez historyczny ``active_md_lines`` ani jego matcher
    po samym nazwisku. Raport dla wspólnej puli wymaga jednocześnie konsultanta
    i numeru zamówienia z kolumny „Uwagi".
    """
    from app.services.cyfrowy_polsat_orders import (
        is_cyfrowy_polsat_order_types_client,
    )

    first, last = month_bounds(period_month)
    result = await db.execute(
        _line_query()
        .join(ClientOrderGroup, ClientOrder.order_group_id == ClientOrderGroup.id)
        .options(selectinload(ClientOrder.order_group))
        .where(
            ClientOrderGroup.is_md_budget_based.is_(True),
            ClientOrderGroup.status == GROUP_STATUS_ACTIVE,
            ClientOrder.status == ClientOrderStatus.active,
            (ClientOrder.start_date.is_(None)) | (ClientOrder.start_date <= last),
            (ClientOrder.end_date.is_(None)) | (ClientOrder.end_date >= first),
        )
    )
    matches: list[LineMatch] = []
    for order in result.scalars():
        group = order.order_group
        if group is None or not is_cyfrowy_polsat_order_types_client(order.client_id):
            continue
        candidate = order.contract.candidate if order.contract else None
        display = (
            f"{candidate.name or ''} {candidate.lastname or ''}".strip()
            if candidate
            else ""
        )
        matches.append(LineMatch(order=order, group=group, consultant_name=display))
    return matches


def match_by_name(
    candidates: Iterable[LineMatch], reported_name: str
) -> list[LineMatch]:
    """Linie, których konsultant odpowiada nazwisku z arkusza."""
    wanted = name_tokens(reported_name)
    if not wanted:
        return []
    return [m for m in candidates if name_tokens(m.consultant_name) == wanted]


# ── Budżet MD ───────────────────────────────────────────────────────────────


async def consumed_md(db: AsyncSession, order_id: int) -> Decimal:
    total = await db.scalar(
        select(func.coalesce(func.sum(ClientOrderMdConsumption.md_reported), 0)).where(
            ClientOrderMdConsumption.order_id == order_id
        )
    )
    return Decimal(str(total or 0))


async def _has_successor_line(db: AsyncSession, order: ClientOrder) -> bool:
    """Czy jakaś linia przejęła tę przy zamianie kontraktora."""
    successor = await db.scalar(
        select(ClientOrder.id)
        .where(ClientOrder.predecessor_order_id == order.id)
        .limit(1)
    )
    return successor is not None


async def sync_md_line_status(db: AsyncSession, order: ClientOrder) -> bool:
    """Dopasuj status linii MD do jej budżetu. Zwraca, czy status się zmienił.

    Lustro ``cost_orders.settle_group``, tyle że na LINII: tam pula mieszka na
    grupie i to grupa dostaje ``exhausted``, tutaj budżet jest per konsultant,
    więc kończy się pojedyncza linia. Reguła jest ta sama i nadrzędna dla
    całego modułu: **zamówienie MD kończy budżet, nie kalendarz**. Data opisuje
    okres obowiązywania i steruje alertami wygasania, ale statusu nie zmienia
    (patrz `dl_portal_expiry_scanner._promote_statuses`).

    Wskrzeszenie linii z powrotem na ``active`` jest tu równie ważne jak jej
    domknięcie: korekta budżetu albo cofnięcie omyłkowego zakończenia zostawiały
    linię ``completed``, przez co import zużycia MD przestawał ją widzieć
    (``active_md_lines`` pyta o linie aktywne) i budżet zamierał.

    Trzy rzeczy, których ta funkcja CELOWO nie robi:

    * **nie rusza linii ``draft``** — to linia w zamówieniu ``scheduled``,
      a aktywna linia w zaplanowanej grupie łamie niezmiennik pilnowany
      w ``_build_line``/``add_line``;
    * **nie rusza linii ``cancelled`` ani ``paused``** — obie są decyzją
      człowieka o wstrzymaniu, a nie skutkiem stanu budżetu;
    * **nie wskrzesza linii świadomie zakończonej.** Linie domknięte datą,
      terminacją kontraktu, ręcznym ``close_order_group`` albo zamianą
      kontraktora niosą ``end_date`` z przeszłości — stąd warunek okresu.
      Wyjątkiem jest zamiana „na dziś": ``end_date`` równa się wtedy
      dzisiejszemu dniu i sam warunek daty by jej nie zatrzymał, a poprzednik
      zachowuje swoje ``md_remaining`` (MD przechodzą na następcę jako osobny
      budżet). Dlatego linia z następcą jest wykluczona wprost.
    """
    if order.md_total is None:
        return False

    remaining = Decimal(str(order.md_remaining or 0))

    if order.status == ClientOrderStatus.active:
        if remaining > ZERO:
            return False
        order.status = ClientOrderStatus.completed
        return True

    if order.status != ClientOrderStatus.completed or remaining <= ZERO:
        return False
    if order.end_date is not None and order.end_date < business_today():
        return False
    if await _has_successor_line(db, order):
        return False
    order.status = ClientOrderStatus.active
    return True


async def recompute_remaining(db: AsyncSession, order: ClientOrder) -> Decimal:
    """Przelicz ``md_remaining`` od zera i zapisz na linii.

    Jedyny writer tego pola. Wartość może zejść do zera i poniżej —
    przekroczony budżet jest faktem handlowym, więc nie jest tu ścinany;
    sygnalizuje go interfejs kolorem.

    Status linii schodzi z tej samej liczby, więc synchronizacja siedzi TUTAJ,
    a nie u każdego z wołających: import zużycia, edycja budżetu, ręczna korekta
    i materializacja szkicu przechodzą wszystkie przez tę funkcję, a rozsypanie
    wywołań po nich gwarantowałoby, że pierwsza nowa ścieżka o nim zapomni.
    """
    if order.md_total is None:
        order.md_remaining = None
        return ZERO
    consumed = await consumed_md(db, order.id)
    adjustment = Decimal(str(order.md_manual_adjustment or 0))
    remaining = quantize_md(Decimal(str(order.md_total)) - consumed + adjustment)
    order.md_remaining = remaining
    await sync_md_line_status(db, order)
    return remaining


async def upsert_consumption(
    db: AsyncSession,
    *,
    order: ClientOrder,
    period_month: str,
    md_reported: Decimal,
    source: str = CONSUMPTION_SOURCE_IMPORT,
    import_id: Optional[int] = None,
    user_id: Optional[int] = None,
) -> tuple[ClientOrderMdConsumption, Decimal, Decimal]:
    """Zapisz zużycie za miesiąc i przelicz pozostałość.

    Zwraca ``(wiersz, poprzednie_md, nowa_pozostałość)``.

    Zapis idzie przez ``INSERT … ON CONFLICT DO UPDATE``, a nie przez
    „SELECT, potem INSERT albo UPDATE": ta druga wersja ma okno wyścigu między
    odczytem a zapisem, w którym dwa równoległe żądania widzą brak wiersza,
    oba próbują wstawić i drugie dostaje ``IntegrityError`` — czyli 500 zamiast
    idempotentnego nadpisania. Dotyczy to nie tylko dwóch importów naraz, ale
    i dwóch osób rozstrzygających ten sam niejednoznaczny wiersz.

    ``previous`` służy wyłącznie treści wpisu w historii; autorytatywna
    pozostałość i tak jest przeliczana od zera po zapisie.
    """
    month_bounds(period_month)  # walidacja kształtu, zanim cokolwiek zapiszemy
    value = quantize_md(md_reported)

    previous_raw = await db.scalar(
        select(ClientOrderMdConsumption.md_reported).where(
            ClientOrderMdConsumption.order_id == order.id,
            ClientOrderMdConsumption.period_month == period_month,
        )
    )
    previous = Decimal(str(previous_raw)) if previous_raw is not None else ZERO

    stmt = (
        pg_insert(ClientOrderMdConsumption)
        .values(
            order_id=order.id,
            period_month=period_month,
            md_reported=value,
            source=source,
            import_id=import_id,
            created_by_user_id=user_id,
        )
        .on_conflict_do_update(
            index_elements=[
                ClientOrderMdConsumption.order_id,
                ClientOrderMdConsumption.period_month,
            ],
            set_={
                "md_reported": value,
                "source": source,
                "import_id": import_id,
                "created_by_user_id": user_id,
                "updated_at": func.now(),
            },
        )
        .returning(ClientOrderMdConsumption.id)
    )
    row_id = await db.scalar(stmt)

    # Po zapisie Core'em mapa tożsamości sesji może trzymać nieaktualną wersję
    # tego wiersza — pobieramy świeżo, żeby wołający dostał to, co jest w bazie.
    row = await db.scalar(
        select(ClientOrderMdConsumption)
        .where(ClientOrderMdConsumption.id == row_id)
        .execution_options(populate_existing=True)
    )

    remaining = await recompute_remaining(db, order)
    return row, previous, remaining


# ── Podział zużycia między zamówieniem bieżącym a jego następcą ──────────────
#
# Konsultant nie przestaje pracować w dniu, w którym kończy się budżet MD jego
# zamówienia. Miesięczny raport przychodzi jedną liczbą za cały miesiąc, więc
# nadwyżka ponad pozostały budżet należy do zamówienia-następcy — i to na jego
# linii musi zostać zapisana, inaczej faktura pokazuje przekroczenie na
# zamówieniu, które klient już zamknął, a nowe stoi puste.


@dataclass(frozen=True)
class MdConsumptionOutcome:
    """Wynik zapisu zużycia MD za miesiąc — z ewentualnym podziałem."""

    #: MD zapisane wcześniej na linii bieżącej za ten sam miesiąc (do treści wpisu).
    previous: Decimal
    #: Ile z raportu zmieściło się w budżecie linii bieżącej.
    applied: Decimal
    #: Pozostałość linii bieżącej po zapisie.
    remaining: Decimal
    #: Ile przeszło na następcę. ``0`` = podziału nie było.
    transferred: Decimal
    successor_order: Optional[ClientOrder]
    successor_group: Optional[ClientOrderGroup]


async def successor_line_for(
    db: AsyncSession, order: ClientOrder
) -> tuple[Optional[ClientOrder], Optional[ClientOrderGroup]]:
    """Linia TEGO SAMEGO konsultanta w zamówieniu-następcy.

    Dopasowanie idzie po ``contract_id``, a gdy takiej linii nie ma — po
    kandydacie: następca bywa zakładany na nowym kontrakcie tej samej osoby.

    **Niejednoznaczność nie jest rozstrzygana zgadywaniem.** Gdy pod jeden
    klucz podpada więcej niż jedna linia, funkcja zwraca pustkę i nadwyżka
    zostaje na linii bieżącej jako przekroczenie budżetu — widoczne w
    interfejsie i możliwe do poprawienia ręcznie. Wybór „pierwszej lepszej"
    dopisałby MD nie tej osobie i wyszedłby dopiero na fakturze.
    """
    if order.order_group_id is None:
        return None, None
    successor = await db.scalar(
        select(ClientOrderGroup)
        .where(ClientOrderGroup.predecessor_group_id == order.order_group_id)
        # Deterministycznie: kontynuacją jest ta zaczynająca się najwcześniej.
        .order_by(ClientOrderGroup.start_date.asc(), ClientOrderGroup.id.asc())
        .limit(1)
    )
    if successor is None:
        return None, None

    lines = list(
        (
            await db.scalars(
                _line_query().where(ClientOrder.order_group_id == successor.id)
            )
        ).all()
    )
    open_lines = [
        line
        for line in lines
        if line.md_total is not None and line.status != ClientOrderStatus.cancelled
    ]
    by_contract = [line for line in open_lines if line.contract_id == order.contract_id]
    if len(by_contract) == 1:
        return by_contract[0], successor
    if by_contract:
        return None, None

    wanted = order.contract.candidate_id if order.contract else None
    if wanted is None:
        return None, None
    by_candidate = [
        line
        for line in open_lines
        if line.contract is not None and line.contract.candidate_id == wanted
    ]
    if len(by_candidate) == 1:
        return by_candidate[0], successor
    return None, None


async def _capacity_outside_month(
    db: AsyncSession, order: ClientOrder, period_month: str
) -> Decimal:
    """Ile MD linia może przyjąć za TEN miesiąc, licząc od zera.

    Suma konsumpcji jest brana z pominięciem rozliczanego miesiąca —
    inaczej powtórka importu widziałaby własny, poprzedni zapis jako zużycie
    i przesunęła na następcę MD, które już raz przesunęła. Podział musi dać
    ten sam wynik przy każdym powtórzeniu, tak samo jak sam ``md_remaining``.
    """
    other = await db.scalar(
        select(func.coalesce(func.sum(ClientOrderMdConsumption.md_reported), 0)).where(
            ClientOrderMdConsumption.order_id == order.id,
            ClientOrderMdConsumption.period_month != period_month,
        )
    )
    capacity = quantize_md(
        Decimal(str(order.md_total))
        - Decimal(str(other or 0))
        + Decimal(str(order.md_manual_adjustment or 0))
    )
    # Budżet przekroczony wcześniejszymi miesiącami nie „oddaje" MD następcy —
    # ujemna pojemność znaczy tylko tyle, że tu nie mieści się już nic.
    return capacity if capacity > ZERO else ZERO


async def apply_md_consumption(
    db: AsyncSession,
    *,
    order: ClientOrder,
    group: Optional[ClientOrderGroup],
    period_month: str,
    md_reported: Decimal,
    source: str = CONSUMPTION_SOURCE_IMPORT,
    import_id: Optional[int] = None,
    user_id: Optional[int] = None,
) -> MdConsumptionOutcome:
    """Zapisz zużycie MD, dzieląc nadwyżkę na zamówienie-następcę.

    Jedyne wejście importu do budżetu MD — obie ścieżki (wsadowa i ręczne
    rozstrzygnięcie niejednoznacznego wiersza) idą tędy, żeby podział nie
    zależał od tego, którą z nich operator akurat wybrał.

    Bez następcy zachowanie jest dotychczasowe: całość ląduje na linii
    bieżącej, a przekroczenie budżetu widać jako ujemną pozostałość. Następcy
    nie wymyślamy — zamówienie, którego nie ma, nie przejmie zużycia.
    """
    value = quantize_md(md_reported)
    successor_line, successor_group = await successor_line_for(db, order)

    applied = value
    overflow = ZERO
    if successor_line is not None and order.md_total is not None:
        capacity = await _capacity_outside_month(db, order, period_month)
        if value > capacity:
            applied = capacity
            overflow = quantize_md(value - capacity)

    _, previous, remaining = await upsert_consumption(
        db,
        order=order,
        period_month=period_month,
        md_reported=applied,
        source=source,
        import_id=import_id,
        user_id=user_id,
    )

    if successor_line is not None:
        # Zapis zerowy jest potrzebny, gdy podział już kiedyś nastąpił, a teraz
        # nadwyżki nie ma (np. po podniesieniu budżetu linii bieżącej).
        # Zostawienie starego wiersza policzyłoby te MD drugi raz — na obu
        # zamówieniach naraz.
        stale = await db.scalar(
            select(ClientOrderMdConsumption.id).where(
                ClientOrderMdConsumption.order_id == successor_line.id,
                ClientOrderMdConsumption.period_month == period_month,
            )
        )
        if overflow > ZERO or stale is not None:
            await upsert_consumption(
                db,
                order=successor_line,
                period_month=period_month,
                md_reported=overflow,
                source=source,
                import_id=import_id,
                user_id=user_id,
            )

    if overflow > ZERO and group is not None and successor_group is not None:
        _record_md_transfer(
            db,
            group=group,
            order=order,
            successor_group=successor_group,
            successor_order=successor_line,
            period_month=period_month,
            transferred=overflow,
            user_id=user_id,
        )
        # Import lokalny: `order_group_lifecycle` importuje `record_event`
        # z tego modułu, więc import na górze pliku byłby cyklem.
        #
        # Materializacja TUTAJ, a nie u wołających: dopiero ona przenosi
        # następcę na `active`, a poprzednika do historii — bez niej oba wpisy
        # w dzienniku mówiłyby o stanie, którego jeszcze nie ma. Bramka
        # materializatora sama sprawdzi, czy CAŁE zamówienie jest wyczerpane;
        # przy kilku konsultantach nie ruszy się, dopóki któryś ma budżet.
        from app.services.order_group_lifecycle import (
            materialize_scheduled_order_groups,
        )

        await materialize_scheduled_order_groups(db, client_id=order.client_id)

    return MdConsumptionOutcome(
        previous=previous,
        applied=applied,
        remaining=remaining,
        transferred=overflow,
        successor_order=successor_line,
        successor_group=successor_group,
    )


def _record_md_transfer(
    db: AsyncSession,
    *,
    group: ClientOrderGroup,
    order: ClientOrder,
    successor_group: ClientOrderGroup,
    successor_order: ClientOrder,
    period_month: str,
    transferred: Decimal,
    user_id: Optional[int],
) -> None:
    """Wpis o podziale w historii OBU zamówień.

    Dwa wpisy, nie jeden: karta zamówienia pokazuje wyłącznie własny dziennik,
    więc pojedynczy wpis byłby niewidoczny po jednej ze stron — a to właśnie
    tam ktoś szuka odpowiedzi „skąd te MD" albo „czemu to się skończyło".
    ``payload`` jest wspólny i niesie obie strony, żeby front mógł zbudować
    odsyłacz niezależnie od tego, którą kartę ma otwartą.
    """
    payload = {
        "md_transferred": str(transferred),
        "period_month": period_month,
        "predecessor_group_id": group.id,
        "successor_group_id": successor_group.id,
        "predecessor_order_number": group.order_number,
        "successor_order_number": successor_group.order_number,
    }
    record_event(
        db,
        group_id=group.id,
        order_id=order.id,
        event_type=EVENT_MD_TRANSFER,
        description=(
            "Zamówienie zakończone — budżet MD wyczerpany, kontynuacja "
            f"na zamówieniu nr {successor_group.order_number}"
        ),
        payload=dict(payload),
        user_id=user_id,
    )
    record_event(
        db,
        group_id=successor_group.id,
        order_id=successor_order.id,
        event_type=EVENT_MD_TRANSFER,
        description=(
            "Zamówienie aktywowane — przejęcie zużycia z zamówienia nr "
            f"{group.order_number} ({format_md(transferred)} MD za "
            f"{format_period_month(period_month)})"
        ),
        payload=dict(payload),
        user_id=user_id,
    )


# ── Historia ────────────────────────────────────────────────────────────────


def record_event(
    db: AsyncSession,
    *,
    group_id: int,
    event_type: str,
    description: str,
    order_id: Optional[int] = None,
    payload: Optional[dict] = None,
    user_id: Optional[int] = None,
) -> ClientOrderGroupEvent:
    event = ClientOrderGroupEvent(
        group_id=group_id,
        order_id=order_id,
        event_type=event_type,
        description=description,
        payload=payload,
        created_by_user_id=user_id,
    )
    db.add(event)
    return event


def consultant_display_name(order: ClientOrder) -> str:
    candidate = order.contract.candidate if order.contract else None
    if candidate is None:
        return "—"
    return f"{candidate.name or ''} {candidate.lastname or ''}".strip() or "—"


def describe_import(
    order: ClientOrder,
    period_month: str,
    md_reported: Decimal,
    previous: Decimal,
    *,
    order_number: str,
) -> str:
    """Wpis „Import MD" w historii zamówienia.

    Numer zamówienia jest w treści, bo ten sam konsultant bywa obsadzony na
    kolejnych zamówieniach tego klienta — bez numeru wpis nie odpowiada na
    pytanie, z KTÓREJ puli zeszły te MD.

    ``wykorzystano`` liczymy jako ``md_total − md_remaining``, czyli tak, by
    razem z pozostałością sumowało się do budżetu widocznego na karcie. Ręczna
    korekta (``md_manual_adjustment``) świadomie NIE wchodzi do tej różnicy —
    licznik ma opisywać wykorzystanie budżetu, nie sumę arytmetyczną korekt.

    ``md_reported`` to MD, które trafiły na TĘ linię — po ewentualnym podziale
    z następcą, nie surowa liczba z arkusza. Inaczej wpis głosiłby zużycie,
    którego to zamówienie nie przyjęło.
    """
    who = consultant_display_name(order)
    used = (
        None
        if order.md_total is None or order.md_remaining is None
        else quantize_md(
            Decimal(str(order.md_total)) - Decimal(str(order.md_remaining))
        )
    )
    context = who
    if previous and previous != md_reported:
        context = f"{who}, nadpisano wcześniejsze {format_md(previous)} MD"
    return (
        f"Za {format_period_month(period_month)} zużyto {format_md(md_reported)} MD "
        f"z zamówienia nr {order_number} ({context}) — wykorzystano "
        f"{format_md(used)} / pozostało {format_md(order.md_remaining)} MD."
    )
