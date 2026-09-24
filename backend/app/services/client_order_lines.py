"""Linie konsultantów zamówienia wielo-konsultantowego: budżet MD i jego zużycie.

Linia = zwykłe ``ClientOrder`` wpięte w ``ClientOrderGroup``, więc niesie już
kontrakt, kandydata, daty i status. Ten moduł dokłada to, czego wcześniej nie
było: budżet MD, jego topnienie z miesięcznych raportów i zamianę kontraktora.

Trzy reguły, na których stoi cała reszta:

1. **``md_remaining`` jest WYLICZANE, nie modyfikowane przyrostowo.**
   ``md_total + md_optional_total - Σ konsumpcji + md_manual_adjustment``,
   przeliczane od zera przy
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

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.scheduling import business_today
from app.core.work_time import HOURS_PER_MD_DEC, MD_PER_MONTH_DEC
from app.models.candidate import Candidate
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import (
    GROUP_STATUS_ACTIVE,
    GROUP_STATUS_COMPLETED,
    GROUP_STATUS_EXHAUSTED,
    ClientOrderGroup,
    ClientOrderGroupEvent,
    ClientOrderGroupMdConsumption,
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
    EVENT_CONSULTANT_ENDED,
    EVENT_MD_IMPORT,
    EVENT_MD_TRANSFER,
    LINE_DECISION_KEEP_HISTORY,
    LINE_DECISION_REMOVED,
    format_md,
    is_multi_consultant_client,
    quantize_md,
)
from app.services.shared_md_orders import uses_shared_md_pool

ZERO = Decimal("0")
HOURS_PER_MD = HOURS_PER_MD_DEC
STANDARD_WORKING_DAYS_PER_MONTH = MD_PER_MONTH_DEC
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


def contract_rate_cost_per_md_pln(
    contract: Contract,
    *,
    on: date,
    currency_rates: dict[str, Optional[Decimal]],
) -> Optional[Decimal]:
    """Efektywna stawka kosztowa kontraktu w kanonicznym PLN/MD.

    Godzina × 8, dzień × 1, miesiąc ÷ 21 (``app.core.work_time``), na końcu
    kurs waluty. Brak stawki
    albo kursu = ``None`` — nigdy nie udajemy kursu 1:1.
    """
    raw_rate = contract.effective_candidate_rate(on)
    currency = contract.resolved_rate_candidate_currency
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


@dataclass(frozen=True)
class ContractCostRate:
    """Stawka kosztowa JEDNEGO kontraktu: surowa (jednostka, waluta) + PLN/MD."""

    raw: Decimal
    unit: RateUnit
    currency: str
    rate_to_pln: Optional[Decimal]
    per_md_pln: Decimal


def contract_cost_rate(
    contract: Contract,
    *,
    on: date,
    currency_rates: dict[str, Optional[Decimal]],
) -> Optional[ContractCostRate]:
    """Stawka kosztowa wskazanego kontraktu — podpowiedź dla linii zamówienia.

    Te same zasady co podpowiedź pickera (``_rate_suggestion``), ale dla
    konkretnego kontraktu, a nie „najnowszego żywego" osoby: okno „Nowe
    zamówienie" dopasowuje osobę z PDF-a do KONTRAKTU i stawka musi pochodzić
    dokładnie z niego.
    """
    per_md_pln = contract_rate_cost_per_md_pln(
        contract, on=on, currency_rates=currency_rates
    )
    raw = contract.effective_candidate_rate(on)
    if per_md_pln is None or raw is None:
        return None
    currency = contract.resolved_rate_candidate_currency
    return ContractCostRate(
        raw=Decimal(str(raw)),
        unit=RateUnit(contract.rate_unit),
        currency=currency,
        rate_to_pln=currency_rates.get(currency),
        per_md_pln=per_md_pln,
    )


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
        return contract_rate_cost_per_md_pln(
            contract, on=on, currency_rates=currency_rates
        )

    live = [c for c in contracts if c.status in LIVE_CONTRACT_STATUSES]
    current = max(live, key=_contract_recency_key) if live else None
    suggested_per_md_pln = rate_per_md_pln(current) if current is not None else None
    suggested_contract_rate: Optional[Decimal] = None
    suggested_unit: Optional[RateUnit] = None
    suggested_currency: Optional[str] = None
    suggested_rate_to_pln: Optional[Decimal] = None
    if current is not None:
        current_rate = current.effective_candidate_rate(on)
        current_currency = current.resolved_rate_candidate_currency
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

    today = business_today()
    currency_rates = await rates_to_pln(
        db,
        {
            contract.resolved_rate_candidate_currency
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


def group_settles_in_month(group: ClientOrderGroup, first_day: date) -> bool:
    """Czy import za miesiąc zaczynający się ``first_day`` może rozliczać grupę.

    Aktywna — zawsze. Zakończona — wtedy, gdy data zakończenia nie jest
    wcześniejsza niż pierwszy dzień importowanego miesiąca. ``close_order_group``
    stawia ``completed`` OD RAZU, także dla daty w przyszłości, a linie zostają
    aktywne do tej daty (konsultant dalej pracuje) — bez tego import za bieżący
    miesiąc gubił dni i faktury zamówienia zakończonego „z datą na koniec
    miesiąca". Okres samej linii (``end_date`` = data zakończenia) nadal
    wyznacza granicę, więc miesiąc PO zakończeniu i tak niczego nie dopasuje.
    Lustro ``_HISTORICAL_GROUP_STATUSES``/``_historical_period_conditions``;
    ``exhausted`` świadomie poza — z wyczerpanej puli nic się już nie zdejmuje.
    """
    if group.status == GROUP_STATUS_ACTIVE:
        return True
    return (
        group.status == GROUP_STATUS_COMPLETED
        and group.closure_date is not None
        and group.closure_date >= first_day
    )


def _group_settles_in_month_clause(first_day: date):
    """SQL-owe lustro ``group_settles_in_month`` (zapytania z JOIN na grupie)."""
    return or_(
        ClientOrderGroup.status == GROUP_STATUS_ACTIVE,
        and_(
            ClientOrderGroup.status == GROUP_STATUS_COMPLETED,
            ClientOrderGroup.closure_date.isnot(None),
            ClientOrderGroup.closure_date >= first_day,
        ),
    )


def _exhausted_with_month_entry_clause(period_month: str, *, cost: bool):
    """Audyt 22.09 r2 (FIN-MD-08): korekta miesiąca, który WYCZERPAŁ pulę.

    ``group_settles_in_month`` celowo pomija ``exhausted`` (z wyczerpanej puli
    nic się już nie zdejmuje) — ale przez to ponowny import TEGO SAMEGO
    miesiąca z mniejszą liczbą (korekta raportu Finansów) był niemożliwy,
    a pula zostawała wyczerpana na zawsze. Grupa ``exhausted``, która ma już
    wpis za ten miesiąc, jest więc celem korekty; ``settle`` sam przywraca
    ``active``, gdy po korekcie coś zostaje. Wzorzec:
    ``historical_shared_md_lines``.
    """
    from app.models.md_consumption import ClientOrderInvoiceConsumption

    if cost:
        entry = (
            select(ClientOrderInvoiceConsumption.id)
            .join(ClientOrder, ClientOrder.id == ClientOrderInvoiceConsumption.order_id)
            .where(
                ClientOrder.order_group_id == ClientOrderGroup.id,
                ClientOrderInvoiceConsumption.period_month == period_month,
            )
            .exists()
        )
    else:
        entry = (
            select(ClientOrderGroupMdConsumption.id)
            .where(
                ClientOrderGroupMdConsumption.group_id == ClientOrderGroup.id,
                ClientOrderGroupMdConsumption.period_month == period_month,
            )
            .exists()
        )
    return and_(ClientOrderGroup.status == GROUP_STATUS_EXHAUSTED, entry)


async def exhausted_groups_with_month_entry(
    db: AsyncSession, group_ids: Iterable[int], period_month: str
) -> frozenset[int]:
    """Id grup ``exhausted`` z wpisem za ``period_month`` (MD puli albo faktura)."""
    from app.models.md_consumption import ClientOrderInvoiceConsumption

    ids = sorted(set(group_ids))
    if not ids:
        return frozenset()
    shared = set(
        (
            await db.scalars(
                select(ClientOrderGroupMdConsumption.group_id)
                .join(
                    ClientOrderGroup,
                    ClientOrderGroup.id == ClientOrderGroupMdConsumption.group_id,
                )
                .where(
                    ClientOrderGroupMdConsumption.group_id.in_(ids),
                    ClientOrderGroupMdConsumption.period_month == period_month,
                    ClientOrderGroup.status == GROUP_STATUS_EXHAUSTED,
                )
            )
        ).all()
    )
    cost = set(
        (
            await db.scalars(
                select(ClientOrder.order_group_id)
                .join(
                    ClientOrderInvoiceConsumption,
                    ClientOrderInvoiceConsumption.order_id == ClientOrder.id,
                )
                .join(
                    ClientOrderGroup, ClientOrderGroup.id == ClientOrder.order_group_id
                )
                .where(
                    ClientOrder.order_group_id.in_(ids),
                    ClientOrderInvoiceConsumption.period_month == period_month,
                    ClientOrderGroup.status == GROUP_STATUS_EXHAUSTED,
                )
            )
        ).all()
    )
    return frozenset(g for g in shared | cost if g is not None)


# ── Kwalifikacja linii do importu: OKRES, nie status ────────────────────────
#
# Do 09.2026 import pytał wyłącznie o linie ``active``. Konsultant, który
# zszedł z zamówienia, znikał przez to z matchera RAZEM z miesiącami, w
# których jeszcze pracował — a raport z Finansów za sierpień trafia do systemu
# w połowie września, czyli długo po jego zejściu. Rozliczenie za taki miesiąc
# lądowało jako „Brak aktywnego zamówienia" i nie dawało się przypisać nawet
# ręcznie.
#
# Regułą jest więc OKRES: linia jest celem importu za miesiąc M, jeżeli jej
# okres obejmuje M choćby jednym dniem, jej kontrakt nie jest ``void``, a
# grupa rozlicza M (``group_settles_in_month``). To ta sama reguła, którą od
# dawna stosuje replay Polkomtela (``_historical_period_conditions``) —
# przeniesiona do zwykłej ścieżki importu zamiast pozostawania jej wyjątkiem.
#
# ``cancelled`` NIGDY nie wchodzi: anulowana linia znaczy „tej osoby tu nie
# było", więc dopisanie jej zużycia byłoby zapisaniem faktu, który się nie
# wydarzył. ``draft`` wchodzi wyłącznie dla zamówień kosztowych — tak jak
# przed tą zmianą.
#
# UWAGA: to NIE jest ta sama reguła co ``is_line_on_active_roster``. Tamta
# dzieli kartę zamówienia na „Aktywną obsadę" i „Zakończone" i jest wyłącznie
# prezentacją; ta decyduje o pieniądzach. Zlanie ich w jedną przywróciłoby
# dokładnie ten defekt: osoba zdjęta z obsady znowu przestałaby przyjmować
# zaległe rozliczenia.

_SETTLING_LINE_STATUSES: tuple[ClientOrderStatus, ...] = (
    ClientOrderStatus.active,
    ClientOrderStatus.completed,
)


def _settling_line_statuses(*, include_draft: bool) -> tuple[ClientOrderStatus, ...]:
    if include_draft:
        return _SETTLING_LINE_STATUSES + (ClientOrderStatus.draft,)
    return _SETTLING_LINE_STATUSES


def line_settles_in_month_conditions(period_month: str, *, include_draft: bool = False):
    """Warunki SQL: linia obsadzała zamówienie w importowanym miesiącu.

    Wymaga JOIN-a na ``Contract`` — bez niego ``Contract.status`` zbudowałby
    ukryty iloczyn kartezjański zamiast warunku o kontrakcie tej linii.
    """
    first, last = month_bounds(period_month)
    return (
        ClientOrder.status.in_(_settling_line_statuses(include_draft=include_draft)),
        Contract.status != ContractStatus.void,
        (ClientOrder.start_date.is_(None)) | (ClientOrder.start_date <= last),
        (ClientOrder.end_date.is_(None)) | (ClientOrder.end_date >= first),
    )


def line_settles_in_month(
    order: ClientOrder,
    period_month: str,
    *,
    contract: Optional[Contract] = None,
    include_draft: bool = False,
) -> bool:
    """Pythonowe lustro ``line_settles_in_month_conditions``.

    Woła je ponowne sprawdzenie pod blokadą wiersza (``md_consumption``), więc
    dobór kandydatów i zapis odpowiadają na dokładnie to samo pytanie.
    ``contract`` podaje wołający, żeby nie doczytywać relacji leniwie w sesji
    async (``MissingGreenlet``).
    """
    if order.status not in _settling_line_statuses(include_draft=include_draft):
        return False
    resolved = contract if contract is not None else order.contract
    if resolved is not None and resolved.status == ContractStatus.void:
        return False
    first, last = month_bounds(period_month)
    if order.start_date is not None and order.start_date > last:
        return False
    if order.end_date is not None and order.end_date < first:
        return False
    return True


async def md_lines_settling_in_month(
    db: AsyncSession, period_month: str
) -> list[LineMatch]:
    """Linie MD, które OBSADZAŁY zamówienie w danym miesiącu.

    Linia obowiązuje w miesiącu, jeśli jej okres zachodzi na ten miesiąc
    choćby jednym dniem — miesiąc rozliczeniowy dzieli się między poprzednika
    i następcę dokładnie w miesiącu zamiany kontraktora, więc porównanie
    z jednym dniem (np. pierwszym) gubiłoby jedną ze stron.

    Do 09.2026 funkcja nazywała się ``active_md_lines`` i pytała o
    ``status == active``. Przez to konsultant, który zszedł z zamówienia,
    przestawał przyjmować rozliczenie za miesiąc, w którym JESZCZE PRACOWAŁ —
    a raport z Finansów za ten miesiąc przychodzi kilka tygodni po jego
    zejściu. Decyduje ``line_settles_in_month_conditions``, czyli okres.

    Filtr po liście klientów jest tutaj celowo, nie tylko w widoku: klient
    zdjęty z ``MULTI_CONSULTANT_ORDER_CLIENT_IDS`` przestaje pokazywać te
    linie w interfejsie, więc import nie może dalej po cichu odejmować im MD —
    powstałby stan niewidoczny i niemożliwy do poprawienia z aplikacji.
    """
    first, _last = month_bounds(period_month)
    result = await db.execute(
        _line_query()
        .join(Contract, ClientOrder.contract_id == Contract.id)
        .options(selectinload(ClientOrder.order_group))
        .where(
            ClientOrder.md_total.isnot(None),
            *line_settles_in_month_conditions(period_month),
        )
    )
    matches: list[LineMatch] = []
    for order in result.scalars():
        group = order.order_group
        if group is None or (
            not is_multi_consultant_client(order.client_id)
            and group.md_budget_mode != "per_person"
        ):
            continue
        if not group_settles_in_month(group, first):
            continue
        candidate = order.contract.candidate if order.contract else None
        display = (
            f"{candidate.name or ''} {candidate.lastname or ''}".strip()
            if candidate
            else ""
        )
        matches.append(LineMatch(order=order, group=group, consultant_name=display))
    return matches


async def cost_lines_settling_in_month(
    db: AsyncSession, period_month: str
) -> list[LineMatch]:
    """Linie zamówień KOSZTOWYCH, które obsadzały je w danym miesiącu.

    Lustro ``md_lines_settling_in_month``, ale z dwiema świadomymi różnicami:

    * linia kosztowa NIE ma budżetu MD (``md_total IS NULL``), więc filtr po
      ``md_total`` byłby tu dokładnie odwrotny do potrzeby,
    * pytamy o stan GRUPY, nie tylko linii — z wyczerpanego zamówienia nie
      wolno już nic zdejmować, a z zakończonego wyłącznie za miesiące, które
      nie leżą po dacie zakończenia (``group_settles_in_month``).

    Historyczne grupy (``order_type IS NULL``) nadal wymagają starej listy
    klientów. Wyłącznie nowa, jawnie oznaczona grupa ``order_type='cost'``
    omija tę bramkę — dzięki temu wdrożenie nie poszerza matchera żadnego
    istniejącego zamówienia.
    """
    from app.services.cost_orders import is_cost_order_client

    first, _last = month_bounds(period_month)
    result = await db.execute(
        _line_query()
        .join(ClientOrderGroup, ClientOrder.order_group_id == ClientOrderGroup.id)
        .join(Contract, ClientOrder.contract_id == Contract.id)
        .options(selectinload(ClientOrder.order_group))
        .where(
            ClientOrderGroup.is_cost_based.is_(True),
            or_(
                _group_settles_in_month_clause(first),
                _exhausted_with_month_entry_clause(period_month, cost=True),
            ),
            *line_settles_in_month_conditions(period_month, include_draft=True),
        )
    )
    matches: list[LineMatch] = []
    for order in result.scalars():
        group = order.order_group
        if group is None or (
            group.order_type != "cost" and not is_cost_order_client(order.client_id)
        ):
            continue
        candidate = order.contract.candidate if order.contract else None
        display = (
            f"{candidate.name or ''} {candidate.lastname or ''}".strip()
            if candidate
            else ""
        )
        matches.append(LineMatch(order=order, group=group, consultant_name=display))
    return matches


async def shared_md_lines_settling_in_month(
    db: AsyncSession, period_month: str
) -> list[LineMatch]:
    """Linie wspólnej puli MD, które obsadzały zamówienie w danym miesiącu.

    To osobna pula na grupie, więc jej linie celowo mają ``md_total IS NULL``
    i nie mogą przejść przez ``md_lines_settling_in_month`` ani jego matcher
    po samym nazwisku. Raport dla wspólnej puli wymaga jednocześnie konsultanta
    i numeru zamówienia z kolumny „Uwagi".
    """
    first, _last = month_bounds(period_month)
    result = await db.execute(
        _line_query()
        .join(ClientOrderGroup, ClientOrder.order_group_id == ClientOrderGroup.id)
        .join(Contract, ClientOrder.contract_id == Contract.id)
        .options(selectinload(ClientOrder.order_group))
        .where(
            ClientOrderGroup.is_md_budget_based.is_(True),
            or_(
                _group_settles_in_month_clause(first),
                _exhausted_with_month_entry_clause(period_month, cost=False),
            ),
            *line_settles_in_month_conditions(period_month),
        )
    )
    matches: list[LineMatch] = []
    for order in result.scalars():
        group = order.order_group
        if group is None or not uses_shared_md_pool(group):
            continue
        candidate = order.contract.candidate if order.contract else None
        display = (
            f"{candidate.name or ''} {candidate.lastname or ''}".strip()
            if candidate
            else ""
        )
        matches.append(LineMatch(order=order, group=group, consultant_name=display))
    return matches


# A replay of an old Finance batch cannot use today's status snapshot.  An
# order that was valid in the batch month can legitimately be completed or
# exhausted by the time the SAP-prefix correction is run.  Since 09.2026 the
# ordinary importer follows the same period-based rule for the LINE; these
# queries stay separate because a replay additionally accepts an exhausted
# GROUP and re-proves the contract-to-order client link.
_HISTORICAL_GROUP_STATUSES: tuple[str, ...] = (
    GROUP_STATUS_ACTIVE,
    GROUP_STATUS_COMPLETED,
    GROUP_STATUS_EXHAUSTED,
)


def _historical_period_conditions(period_month: str):
    """Replay starej paczki: okres linii plus okres grupy.

    Reguła linii jest od 09.2026 wspólna ze zwykłym importem
    (``line_settles_in_month_conditions``) — replay był jej pierwowzorem.
    Replay dokłada do niej dwie rzeczy: okres samej GRUPY (zwykła ścieżka pyta
    zamiast tego ``group_settles_in_month``) i zgodność klienta kontraktu
    z klientem linii, bo korekta prefiksu SAP potrafi trafić w rozjechany
    rekord sprzed lat.
    """
    first, last = month_bounds(period_month)
    return (
        *line_settles_in_month_conditions(period_month),
        Contract.client_id == ClientOrder.client_id,
        ClientOrderGroup.start_date <= last,
        (ClientOrderGroup.end_date.is_(None)) | (ClientOrderGroup.end_date >= first),
    )


async def historical_md_lines(db: AsyncSession, period_month: str) -> list[LineMatch]:
    """Per-consultant MD candidates valid in an already imported month.

    Current ``completed`` state is not evidence that the line was inactive in
    the historical month.  The inclusive date overlap is the temporal
    boundary.  Draft/paused/cancelled lines, void contracts and scheduled
    groups remain excluded because replay cannot prove that they ever entered
    the settlement lifecycle.
    """

    result = await db.execute(
        _line_query()
        .join(Contract, ClientOrder.contract_id == Contract.id)
        .join(ClientOrderGroup, ClientOrder.order_group_id == ClientOrderGroup.id)
        .options(selectinload(ClientOrder.order_group))
        .where(
            ClientOrder.md_total.isnot(None),
            ClientOrderGroup.status.in_(_HISTORICAL_GROUP_STATUSES),
            *_historical_period_conditions(period_month),
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


async def historical_cost_lines(db: AsyncSession, period_month: str) -> list[LineMatch]:
    """Cost candidates valid in an old batch, including closed/exhausted pools."""

    from app.services.cost_orders import is_cost_order_client

    result = await db.execute(
        _line_query()
        .join(Contract, ClientOrder.contract_id == Contract.id)
        .join(ClientOrderGroup, ClientOrder.order_group_id == ClientOrderGroup.id)
        .options(selectinload(ClientOrder.order_group))
        .where(
            ClientOrderGroup.is_cost_based.is_(True),
            ClientOrderGroup.status.in_(_HISTORICAL_GROUP_STATUSES),
            *_historical_period_conditions(period_month),
        )
    )
    matches: list[LineMatch] = []
    for order in result.scalars():
        group = order.order_group
        if group is None or (
            group.order_type != "cost" and not is_cost_order_client(order.client_id)
        ):
            continue
        candidate = order.contract.candidate if order.contract else None
        display = (
            f"{candidate.name or ''} {candidate.lastname or ''}".strip()
            if candidate
            else ""
        )
        matches.append(LineMatch(order=order, group=group, consultant_name=display))
    return matches


async def historical_shared_md_lines(
    db: AsyncSession, period_month: str
) -> list[LineMatch]:
    """Shared-MD candidates valid in an old batch, including exhausted pools."""

    result = await db.execute(
        _line_query()
        .join(Contract, ClientOrder.contract_id == Contract.id)
        .join(ClientOrderGroup, ClientOrder.order_group_id == ClientOrderGroup.id)
        .options(selectinload(ClientOrder.order_group))
        .where(
            ClientOrderGroup.is_md_budget_based.is_(True),
            ClientOrderGroup.status.in_(_HISTORICAL_GROUP_STATUSES),
            *_historical_period_conditions(period_month),
        )
    )
    matches: list[LineMatch] = []
    for order in result.scalars():
        group = order.order_group
        if group is None or not uses_shared_md_pool(group):
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
    """Linie, których konsultant odpowiada nazwisku z arkusza.

    Czyste dopasowanie po nazwisku, bez żadnej preferencji — rozstrzyganie
    remisów należy do ``prefer_active_line`` i musi biec PO zawężeniu numerem
    zamówienia (patrz tam).
    """
    wanted = name_tokens(reported_name)
    if not wanted:
        return []
    return [m for m in candidates if name_tokens(m.consultant_name) == wanted]


def prefer_active_line(matches: list[LineMatch]) -> list[LineMatch]:
    """Remis rozstrzyga linia aktywna — zakończona jest celem ZAPASOWYM.

    Odkąd pula kandydatów obejmuje też linie zakończone
    (``line_settles_in_month``), ta sama osoba potrafi trafić w dwie linie
    tego samego miesiąca: tę, z której zeszła, i tę, na którą weszła. Bez tej
    preferencji rozliczenie, które wcześniej dopasowywało się samo, wpadałoby
    do „wymaga przypisania" — czyli naprawa jednego defektu robiłaby drugi.

    **Wołaj to na SAMYM KOŃCU zawężania, nigdy wewnątrz ``match_by_name``.**
    Matchery najpierw dopasowują nazwisko, a dopiero potem numer zamówienia
    z „Uwag"; preferencja wpięta przed numerem wycinała linię, którą numer
    właśnie miał wskazać — i wiersz z poprawnym numerem kończył jako
    niedopasowany (złapane przez ``test_polkomtel_finance_order_matching``).

    Preferencja jest wąska z rozmysłem: wymaga DOKŁADNIE JEDNEJ linii
    aktywnej. Dwie aktywne albo dwie zakończone to nadal niejednoznaczność
    i nadal rozstrzyga ją człowiek — system nie zgaduje (reguła 2 modułu).
    """
    if len(matches) <= 1:
        return matches
    active = [m for m in matches if m.order.status == ClientOrderStatus.active]
    if len(active) == 1:
        return active
    return matches


# ── Budżet MD ───────────────────────────────────────────────────────────────


async def consumed_md(db: AsyncSession, order_id: int) -> Decimal:
    total = await db.scalar(
        select(func.coalesce(func.sum(ClientOrderMdConsumption.md_reported), 0)).where(
            ClientOrderMdConsumption.order_id == order_id
        )
    )
    return Decimal(str(total or 0))


def is_line_on_active_roster(
    order: ClientOrder,
    group_end_date: Optional[date],
    today: Optional[date] = None,
) -> bool:
    """Czy linia należy do AKTYWNEJ OBSADY zamówienia — reguła PREZENTACJI.

    Karta zamówienia dzieli konsultantów na „Aktywną obsadę" i „Zakończone".
    Do 09.2026 decydował o tym sam ``ClientOrder.status``, a linia MD **nie
    kończy się datą, tylko budżetem** (``sync_md_line_status``, skaner
    ``dl_portal_expiry_scanner._promote_statuses`` wprost pomija linie MD).
    Osoba z zapisaną datą końca współpracy, której został limit MD, wisiała
    więc wśród aktywnych.

    Ta funkcja **nie dotyka statusu w bazie i nie wolno jej do tego użyć.**
    Status rządzi cyklem życia linii: zamianą kontraktora (``swap_consultant``
    wymaga ``active``), wyczerpaniem puli (``sync_md_group_exhaustion`` liczy
    obsadę po statusie) i bramką dokładania konsultantów. Domknięcie linii
    datą przestawiłoby te trzy rzeczy przy okazji naprawiania wyglądu karty.

    Kwalifikacja do importu zużycia to od 09.2026 OSOBNA reguła —
    ``line_settles_in_month`` — i pyta o OKRES, nie o status ani o obsadę.
    Dzięki temu osoba zdjęta z obsady nadal przyjmuje zaległe rozliczenie za
    miesiąc, w którym pracowała (raport za sierpień trafia do systemu w
    połowie września). **Nie zlewaj tych dwóch reguł w jedną** — to właśnie
    zlanie ich było defektem, który ta zmiana naprawia.

    Data własna linii zdejmuje z obsady tylko wtedy, gdy osoba zeszła
    WCZEŚNIEJ niż kończy się samo zamówienie: linia dziedziczy ``end_date``
    grupy (``_build_line``: ``payload.end_date or group.end_date``), więc
    porównanie z samym „dziś" przerzucałoby całą obsadę wygasłego zamówienia
    do „Zakończonych" — łącznie z ludźmi, którzy dalej pracują i czekają na
    przedłużenie. O tym, że skończyło się CAŁE zamówienie, mówi status grupy
    i jej data zakończenia, nie wiersz przy nazwisku.
    """
    if order.status != ClientOrderStatus.active:
        return False
    end = order.end_date
    if end is None:
        return True
    # Granica jest WŁĄCZAJĄCA, jak w `is_current_order_period` i froncie
    # (`isCurrentOrder`): konsultant pracuje do końca swojego ostatniego dnia.
    if end >= (today or business_today()):
        return True
    return group_end_date is not None and end >= group_end_date


def line_budget_total(order: ClientOrder) -> Decimal:
    """Cały budżet MD linii: zakres podstawowy + opcjonalny (Faza B, 09.2026).

    ``md_optional_total`` jest ``NULL`` = „brak opcji w umowie", więc wchodzi
    jako zero. Wołający musi wcześniej sprawdzić ``md_total is not None`` —
    linia bez budżetu (kosztowa, wspólna pula) nie ma czego sumować.
    """
    return Decimal(str(order.md_total or 0)) + Decimal(
        str(order.md_optional_total or 0)
    )


def split_md_usage(order: ClientOrder, used: Decimal) -> tuple[Decimal, Decimal]:
    """Podział zużycia na podstawę i opcję: ``(md_base_used, md_optional_used)``.

    Zużycie wypełnia NAJPIERW zakres podstawowy, a dopiero nadwyżka schodzi
    z opcji — tak liczy je klient (Centrum e-Zdrowia), więc obie liczby muszą
    zgadzać się z jego protokołem, a nie tylko sumować do ``used``.
    Nadwyżka ponad podstawę jest przypisywana opcji także wtedy, gdy opcja nie
    istnieje albo jest już wyczerpana — przekroczenie jest faktem handlowym
    i nie znika przez przycięcie do budżetu.
    """
    base_total = Decimal(str(order.md_total or 0))
    consumed = quantize_md(used)
    base_used = min(consumed, base_total)
    optional_used = max(ZERO, consumed - base_total)
    return quantize_md(base_used), quantize_md(optional_used)


async def consumption_rows(
    db: AsyncSession, order_id: int
) -> list[ClientOrderMdConsumption]:
    """Wpisy zejść MD jednej linii, po miesiącu, z autorem (selectinload).

    Autor jest doczytywany tutaj, bo lista trafia do odpowiedzi API, a leniwe
    ``row.author`` w sesji async leci ``MissingGreenlet``.
    """
    result = await db.execute(
        select(ClientOrderMdConsumption)
        .options(selectinload(ClientOrderMdConsumption.author))
        .where(ClientOrderMdConsumption.order_id == order_id)
        .order_by(ClientOrderMdConsumption.period_month.asc())
    )
    return list(result.scalars())


async def delete_consumption(
    db: AsyncSession, order: ClientOrder, period_month: str
) -> Optional[Decimal]:
    """Usuń zejście za miesiąc i przelicz pozostałość linii.

    Zwraca poprzednio zapisane MD (do treści wpisu w historii) albo ``None``,
    gdy wpisu za ten miesiąc nie było — wołający decyduje, czy to 404.
    Pozostałość przeliczana od zera po usunięciu, jak przy każdej innej
    zmianie zużycia (patrz ``recompute_remaining``).
    """
    month_bounds(period_month)
    row = await db.scalar(
        select(ClientOrderMdConsumption).where(
            ClientOrderMdConsumption.order_id == order.id,
            ClientOrderMdConsumption.period_month == period_month,
        )
    )
    if row is None:
        return None
    previous = Decimal(str(row.md_reported))
    await db.delete(row)
    await db.flush()
    await recompute_remaining(db, order)
    return previous


async def _has_successor_line(db: AsyncSession, order: ClientOrder) -> bool:
    """Czy jakaś linia przejęła tę przy zamianie kontraktora."""
    successor = await db.scalar(
        select(ClientOrder.id)
        .where(ClientOrder.predecessor_order_id == order.id)
        .limit(1)
    )
    return successor is not None


async def _has_open_offboarding_case(db: AsyncSession, order: ClientOrder) -> bool:
    """Czy linia czeka na decyzję Delivery Leada o pozostałej puli MD.

    Odkąd import zużycia przyjmuje linie zakończone (``line_settles_in_month``),
    ``recompute_remaining`` biegnie także na liniach domkniętych
    offboardingiem. Bez tego warunku zaległe rozliczenie linii z datą końca
    „dziś" (data zejścia jest wtedy równa dzisiejszej, więc sam warunek okresu
    jej nie zatrzyma) wskrzeszałoby ją na ``active`` — czyli cofało decyzję
    o zakończeniu współpracy, zanim człowiek zdążył ją rozstrzygnąć.
    """
    if order.id is None:
        return False

    from app.models.client_order_offboarding import (
        OFFBOARDING_STATUS_PENDING,
        ClientOrderOffboardingCase,
    )

    open_case = await db.scalar(
        select(ClientOrderOffboardingCase.id)
        .where(
            ClientOrderOffboardingCase.order_id == order.id,
            ClientOrderOffboardingCase.status == OFFBOARDING_STATUS_PENDING,
        )
        .limit(1)
    )
    return open_case is not None


async def sync_md_line_status(db: AsyncSession, order: ClientOrder) -> bool:
    """Dopasuj status linii MD do jej budżetu. Zwraca, czy status się zmienił.

    Lustro ``cost_orders.settle_group``, tyle że na LINII: tam pula mieszka na
    grupie i to grupa dostaje ``exhausted``, tutaj budżet jest per konsultant,
    więc kończy się pojedyncza linia. Reguła jest ta sama i nadrzędna dla
    całego modułu: **zamówienie MD kończy budżet, nie kalendarz**. Data opisuje
    okres obowiązywania i steruje alertami wygasania, ale statusu nie zmienia
    (patrz `dl_portal_expiry_scanner._promote_statuses`).

    Wskrzeszenie linii z powrotem na ``active`` jest tu równie ważne jak jej
    domknięcie: korekta budżetu albo cofnięcie omyłkowego zakończenia
    zostawiały linię ``completed``, czyli poza obsadą zamówienia, poza bramką
    zamiany kontraktora i poza liczeniem wyczerpania puli — budżet zamierał.
    (Importu zużycia to nie dotyczy od 09.2026: on pyta o okres, nie o status
    — ``line_settles_in_month``.)

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
    if await _has_open_offboarding_case(db, order):
        return False
    # Osoba z ZAKOŃCZONĄ współpracą nie wraca na obsadę przez stan budżetu —
    # także zapis historyczny z niewykorzystanym limitem MD (ticket 09.2026),
    # którego data końca udziału bywa dzisiejsza. Wznowienie współpracy to
    # decyzja człowieka (przywrócenie w offboardingu, nowy kontrakt).
    contract = await db.get(Contract, order.contract_id)
    if contract is not None and (
        getattr(contract.status, "value", contract.status) == "ended"
    ):
        return False
    # Osoba świadomie usunięta z zamówienia albo zostawiona jako historia nie
    # wraca na obsadę przez korektę budżetu — to była decyzja człowieka.
    decided = await db.scalar(
        select(func.count(ClientOrderGroupEvent.id)).where(
            ClientOrderGroupEvent.order_id == order.id,
            ClientOrderGroupEvent.event_type == EVENT_CONSULTANT_ENDED,
            ClientOrderGroupEvent.payload["reason"].astext.in_(
                (LINE_DECISION_REMOVED, LINE_DECISION_KEEP_HISTORY)
            ),
        )
    )
    if decided:
        return False
    order.status = ClientOrderStatus.active
    return True


async def _refresh_open_offboarding_snapshot(
    db: AsyncSession, order: ClientOrder, remaining: Decimal
) -> None:
    """Dociągnij migawkę puli MD w NIEROZSTRZYGNIĘTEJ sprawie offboardingu.

    Sprawa niesie ``remaining_md_snapshot`` z chwili zejścia konsultanta i to
    z niej liczy się przeniesienie puli na inną osobę
    (``client_order_groups``: ``remaining = max(0, case.remaining_md_snapshot)``).
    Odkąd import zużycia przyjmuje linie zakończone, MD zaraportowane PO
    zejściu zmniejszają realną pozostałość — nieodświeżona migawka
    przeniosłaby więc na kogoś innego dni, które odchodzący już wypracował.

    Sprawy rozstrzygnięte to historia decyzji i zostają nietknięte. Wspólna
    pula MD ma migawkę zerową z definicji (pula mieszka na grupie), więc też
    jej nie dotykamy.
    """
    if order.id is None:
        # Linia jeszcze nie istnieje w bazie (materializacja szkicu), więc nie
        # może mieć sprawy offboardingu — i nie ma po co jej szukać.
        return

    from app.models.client_order_offboarding import (
        OFFBOARDING_STATUS_PENDING,
        ClientOrderOffboardingCase,
    )

    case = await db.scalar(
        select(ClientOrderOffboardingCase)
        .where(
            ClientOrderOffboardingCase.order_id == order.id,
            ClientOrderOffboardingCase.status == OFFBOARDING_STATUS_PENDING,
            ClientOrderOffboardingCase.uses_shared_md_pool.is_(False),
        )
        .limit(1)
    )
    if case is None:
        return
    # Nadwyżka zużycia jest historią, nigdy ujemną pulą do przeniesienia —
    # ta sama zasada co przy zakładaniu sprawy.
    refreshed = max(ZERO, quantize_md(remaining))
    if Decimal(str(case.remaining_md_snapshot)) != refreshed:
        case.remaining_md_snapshot = refreshed


async def recompute_remaining(
    db: AsyncSession, order: ClientOrder, *, rebalance: bool = True
) -> Decimal:
    """Przelicz ``md_remaining`` od zera i zapisz na linii.

    ``rebalance`` (audyt 22.09 r2, FIN-MD-02): po przeliczeniu poprzednika
    koryguje budżet NASTĘPCY po zamianie kontraktora i celu transferu puli
    przy offboardingu — patrz :func:`_rebalance_swap_successor` i
    :func:`_rebalance_offboarding_transfer`. Korekta woła tę funkcję dla
    następcy z ``rebalance=False`` (głębokość 1).

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
    # Budżet, z którego schodzą MD, to podstawa + zakres opcjonalny (Faza B,
    # 09.2026). Sama podstawa dawałaby ujemną pozostałość — i alert
    # o wyczerpaniu — osobie, która dopiero weszła w opcję z umowy.
    remaining = quantize_md(line_budget_total(order) - consumed + adjustment)
    order.md_remaining = remaining
    await _refresh_open_offboarding_snapshot(db, order, remaining)
    await sync_md_line_status(db, order)
    if order.order_group_id is not None:
        # Klienci, u których zamówienie kończy wyczerpanie limitów WSZYSTKICH
        # osób (BIK) — import leniwy: moduł importuje stąd `record_event`.
        from app.services.order_md_exhaustion import sync_md_group_exhaustion

        await sync_md_group_exhaustion(
            db, order.order_group_id, client_id=order.client_id
        )
    if rebalance and order.id is not None:
        await _rebalance_swap_successor(db, order)
        await _rebalance_offboarding_transfer(db, order)
    return order.md_remaining if order.md_remaining is not None else remaining


# ── Audyt 22.09 r2 (FIN-MD-02): korekta budżetu następcy ────────────────────
#
# Zamiana kontraktora (i transfer puli przy offboardingu) liczy budżet
# następcy z pozostałości poprzednika W CHWILI KLIKNIĘCIA. Raport Finansów za
# miesiąc zamiany przychodzi później i schodzi już tylko z linii poprzednika
# (``line_settles_in_month``), więc te same MD były rozdane dwa razy: raz jako
# zużycie poprzednika, raz w budżecie następcy. Decyzja właściciela:
# automatyczna korekta — ale WYŁĄCZNIE, gdy budżet następcy nie był od tamtej
# pory edytowany ręcznie (porównanie z liczbą zapisaną w dzienniku).


def _dec_or_none(value: object) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001 — dziennik przeżywa dane starsze od walidacji
        return None


def _same_md(left: object, right: object) -> bool:
    a, b = _dec_or_none(left), _dec_or_none(right)
    if a is None or b is None:
        return a is None and b is None
    return quantize_md(a) == quantize_md(b)


async def _swap_split_remaining(
    db: AsyncSession, old: ClientOrder, md_remaining_old: Decimal
) -> tuple[Decimal, Decimal]:
    """(podstawa, opcja) pozostałości poprzednika — lustro ``swap_consultant``."""
    optional_remaining = ZERO
    if old.md_optional_total is not None:
        _, optional_used = split_md_usage(old, await consumed_md(db, old.id))
        optional_unused = max(ZERO, Decimal(str(old.md_optional_total)) - optional_used)
        optional_remaining = max(ZERO, min(optional_unused, md_remaining_old))
    base_remaining = max(ZERO, md_remaining_old - optional_remaining)
    return base_remaining, optional_remaining


async def _person_name(db: AsyncSession, order: ClientOrder) -> str:
    """Imię i nazwisko osoby z linii — BEZ leniwego doczytania relacji."""
    row = (
        await db.execute(
            select(Candidate.name, Candidate.lastname)
            .join(Contract, Contract.candidate_id == Candidate.id)
            .where(Contract.id == order.contract_id)
        )
    ).first()
    if row is None:
        return "—"
    return f"{row[0] or ''} {row[1] or ''}".strip() or "—"


async def _rebalance_swap_successor(db: AsyncSession, order: ClientOrder) -> None:
    from app.services.multi_consultant_orders import (
        EVENT_CONSULTANT_SWAPPED,
        EVENT_MANUAL_EDIT,
        swap_md_total,
    )

    if order.md_total is None or order.order_group_id is None:
        return
    successors = list(
        (
            await db.scalars(
                select(ClientOrder).where(
                    ClientOrder.predecessor_order_id == order.id,
                    ClientOrder.order_group_id == order.order_group_id,
                    ClientOrder.status != ClientOrderStatus.cancelled,
                )
            )
        ).all()
    )
    if len(successors) != 1 or successors[0].md_total is None:
        return
    succ = successors[0]
    event = await db.scalar(
        select(ClientOrderGroupEvent)
        .where(
            ClientOrderGroupEvent.group_id == order.order_group_id,
            ClientOrderGroupEvent.order_id == succ.id,
            ClientOrderGroupEvent.event_type == EVENT_CONSULTANT_SWAPPED,
        )
        .order_by(ClientOrderGroupEvent.id.desc())
        .limit(1)
    )
    payload = dict(event.payload or {}) if event is not None else {}
    recorded_total = payload.get("new_md_total")
    if not payload.get("auto_rebalance"):
        # Zamiana sprzed audytu 22.09 r2: jej budżet mógł zostać przyjęty
        # i rozliczony z klientem — nie korygujemy historii po cichu.
        return
    if recorded_total is None:
        # Zamiana sprzed tej reguły (albo zamówienie kosztowe / wspólna pula):
        # bez zapisanej liczby nie odróżnimy ręcznej edycji od korekty.
        return
    if not _same_md(succ.md_total, recorded_total) or not _same_md(
        succ.md_optional_total, payload.get("new_md_optional_total")
    ):
        return  # budżet następcy edytowany ręcznie — nie ruszamy
    rate_old = _dec_or_none(payload.get("old_rate_revenue")) or _dec_or_none(
        order.md_rate_revenue
    )
    rate_new = _dec_or_none(payload.get("new_rate_revenue")) or _dec_or_none(
        succ.md_rate_revenue
    )
    if rate_old is None or rate_new is None or rate_new <= 0:
        return
    md_remaining_old = max(ZERO, Decimal(str(order.md_remaining or 0)))
    base_rem, opt_rem = await _swap_split_remaining(db, order, md_remaining_old)
    method = payload.get("md_transfer_method")
    if method:
        # Zamiana z jawnym sposobem przeniesienia (ticket 09.2026): 1:1 dla
        # puli w MD, wybór stawki dla puli w kwocie — ta sama reguła co
        # w chwili zamiany, nie „zachowanie wartości w PLN".
        from app.services.order_line_takeover import split_transferred

        new_total, new_optional = split_transferred(
            method=str(method),
            base_remaining=base_rem,
            optional_remaining=opt_rem,
            has_optional=succ.md_optional_total is not None,
            departing_rate=rate_old,
            incoming_rate=rate_new,
        )
    else:
        new_total = swap_md_total(
            md_remaining_old=base_rem,
            rate_revenue_old=rate_old,
            rate_revenue_new=rate_new,
        )
        new_optional = (
            None
            if succ.md_optional_total is None
            else swap_md_total(
                md_remaining_old=opt_rem,
                rate_revenue_old=rate_old,
                rate_revenue_new=rate_new,
            )
        )
    if _same_md(succ.md_total, new_total) and _same_md(
        succ.md_optional_total, new_optional
    ):
        return
    previous_total = Decimal(str(succ.md_total))
    succ_name = await _person_name(db, succ)
    succ.md_total = new_total
    succ.md_input_value = new_total
    succ.md_optional_total = new_optional
    payload["new_md_total"] = str(new_total)
    if new_optional is not None:
        payload["new_md_optional_total"] = str(new_optional)
    payload["old_md_remaining"] = str(md_remaining_old)
    # Nowy dict: mutacja JSONB w miejscu nie jest widoczna dla ORM.
    event.payload = payload
    record_event(
        db,
        group_id=order.order_group_id,
        order_id=succ.id,
        event_type=EVENT_MANUAL_EDIT,
        description=(
            "Korekta budżetu następcy po rozliczeniu miesiąca zamiany: "
            f"{succ_name} {format_md(previous_total)} MD → "
            f"{format_md(new_total)} MD (pozostałość poprzednika "
            f"{format_md(md_remaining_old)} MD)."
        ),
        payload={
            "kind": "swap_successor_rebalance",
            "predecessor_order_id": order.id,
            "previous_md_total": str(previous_total),
            "new_md_total": str(new_total),
        },
    )
    await recompute_remaining(db, succ, rebalance=False)


async def _rebalance_offboarding_transfer(db: AsyncSession, order: ClientOrder) -> None:
    from app.models.client_order_offboarding import (
        OFFBOARDING_RESOLUTION_TRANSFER,
        OFFBOARDING_STATUS_RESOLVED,
        ClientOrderOffboardingCase,
    )
    from app.services.multi_consultant_orders import (
        EVENT_MANUAL_EDIT,
        INPUT_MODE_AMOUNT,
        INPUT_MODE_MD,
    )

    if order.md_total is None or order.order_group_id is None:
        return
    case = await db.scalar(
        select(ClientOrderOffboardingCase)
        .where(
            ClientOrderOffboardingCase.order_id == order.id,
            ClientOrderOffboardingCase.status == OFFBOARDING_STATUS_RESOLVED,
            ClientOrderOffboardingCase.resolution == OFFBOARDING_RESOLUTION_TRANSFER,
            ClientOrderOffboardingCase.uses_shared_md_pool.is_(False),
            ClientOrderOffboardingCase.target_order_id.is_not(None),
        )
        .order_by(ClientOrderOffboardingCase.id.desc())
        .limit(1)
    )
    if case is None:
        return
    payload = dict(case.resolution_payload or {})
    before = payload.get("source_before")
    if not isinstance(before, dict):
        return  # decyzja sprzed tej reguły
    if not _same_md(
        order.md_total, payload.get("source_md_total_after")
    ) or not _same_md(order.md_optional_total, payload.get("source_md_optional_after")):
        return  # linia odchodzącego edytowana ręcznie
    target = await db.get(ClientOrder, case.target_order_id)
    if target is None or target.md_total is None:
        return
    if not _same_md(target.md_total, payload.get("target_md_total_after")):
        return  # budżet celu edytowany ręcznie
    basis = _dec_or_none(payload.get("basis_rate"))
    target_rate = _dec_or_none(payload.get("target_rate_revenue"))
    old_remaining = _dec_or_none(payload.get("remaining_md_snapshot"))
    old_transferred = _dec_or_none(payload.get("transferred_md"))
    if (
        basis is None
        or target_rate is None
        or target_rate <= 0
        or old_remaining is None
        or old_transferred is None
    ):
        return

    before_total = Decimal(str(before.get("md_total")))
    before_optional = _dec_or_none(before.get("md_optional_total"))
    before_adjustment = _dec_or_none(before.get("md_manual_adjustment")) or ZERO
    consumed = await consumed_md(db, order.id)
    budget_before = before_total + (before_optional or ZERO)
    new_remaining = max(ZERO, quantize_md(budget_before - consumed + before_adjustment))
    if new_remaining == quantize_md(old_remaining):
        return

    # Odtwórz budżet odchodzącego sprzed decyzji i zdejmij z niego NOWĄ pulę
    # tą samą regułą co decyzja (opcja pierwsza).
    from fastapi import HTTPException

    from app.api.client_order_groups import _reduce_legacy_md_budget

    order.md_total = before_total
    order.md_optional_total = before_optional
    order.md_manual_adjustment = before_adjustment
    order.md_input_mode = before.get("md_input_mode")
    order.md_input_value = _dec_or_none(before.get("md_input_value"))
    try:
        _reduce_legacy_md_budget(order, new_remaining)
    except HTTPException:
        return
    new_transferred = quantize_md(new_remaining * basis / target_rate)
    if payload.get("md_transfer_method") == "incoming_rate":
        # Przeliczenie „po stawce osoby przychodzącej" jest zaokrąglane do
        # 0,1 MD (ticket 09.2026) — korekta trzyma tę samą regułę co decyzja.
        from app.services.order_line_takeover import round_to_tenth

        new_transferred = round_to_tenth(new_transferred)
    delta = new_transferred - quantize_md(old_transferred)
    target.md_total = quantize_md(Decimal(str(target.md_total)) + delta)
    if target.md_input_mode == INPUT_MODE_AMOUNT:
        target.md_input_value = quantize_md(
            Decimal(str(target.md_input_value or 0)) + delta * target_rate
        )
    else:
        target.md_input_mode = INPUT_MODE_MD
        target.md_input_value = quantize_md(
            Decimal(str(target.md_input_value or 0)) + delta
        )
    payload.update(
        {
            "remaining_md_snapshot": str(new_remaining),
            "transferred_md": str(new_transferred),
            "source_md_total_after": str(order.md_total),
            "source_md_optional_after": (
                None
                if order.md_optional_total is None
                else str(order.md_optional_total)
            ),
            "target_md_total_after": str(target.md_total),
        }
    )
    case.resolution_payload = payload
    target_name = await _person_name(db, target)
    source_name = await _person_name(db, order)
    record_event(
        db,
        group_id=order.order_group_id,
        order_id=target.id,
        event_type=EVENT_MANUAL_EDIT,
        description=(
            "Korekta przeniesionej puli MD po rozliczeniu miesiąca zejścia: "
            f"{target_name} {format_md(old_transferred)} MD → "
            f"{format_md(new_transferred)} MD (pozostałość "
            f"{source_name} {format_md(new_remaining)} MD)."
        ),
        payload={
            "kind": "offboarding_transfer_rebalance",
            "offboarding_case_id": case.id,
            "previous_transferred_md": str(old_transferred),
            "transferred_md": str(new_transferred),
        },
    )
    await recompute_remaining(db, order, rebalance=False)
    await recompute_remaining(db, target, rebalance=False)


async def upsert_consumption(
    db: AsyncSession,
    *,
    order: ClientOrder,
    period_month: str,
    md_reported: Decimal,
    source: str = CONSUMPTION_SOURCE_IMPORT,
    import_id: Optional[int] = None,
    user_id: Optional[int] = None,
    status: Optional[str] = None,
    note: Optional[str] = None,
) -> tuple[ClientOrderMdConsumption, Decimal, Decimal]:
    """Zapisz zużycie za miesiąc i przelicz pozostałość.

    Zwraca ``(wiersz, poprzednie_md, nowa_pozostałość)``.

    ``status`` (``accepted`` | ``protocol`` | ``None``) i ``note`` to ręczny
    opis rozliczenia miesiąca (Faza B, 09.2026). Import XLSX ich NIE podaje,
    więc wpis z importu, który nadpisuje ręczny wpis za ten sam miesiąc,
    ustawia ``status=NULL`` i ``note=NULL`` — świadomie: arkusz z Finansów
    jest nowszym źródłem liczby, a status opisywał liczbę, której już nie ma.
    Zachowanie starego statusu przy nowej liczbie twierdziłoby, że ktoś
    zaakceptował wartość, której nigdy nie widział.

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
    if order.order_group_id is not None:
        budget_group = await db.get(ClientOrderGroup, order.order_group_id)
        if budget_group is not None and budget_group.md_budget_mode is not None:
            budget_group.md_budget_mode_locked = True
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
            status=status,
            note=note,
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
                "status": status,
                "note": note,
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
    #: Linia (i jej grupa), na której faktycznie zaczęło się rozliczenie
    #: miesiąca — po przekierowaniu na poprzednika (FIN-MD-01) inna niż ta,
    #: którą podał wołający.
    order: Optional[ClientOrder] = None
    group: Optional[ClientOrderGroup] = None


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


async def predecessor_line_for(
    db: AsyncSession, order: ClientOrder
) -> tuple[Optional[ClientOrder], Optional[ClientOrderGroup]]:
    """Linia TEGO SAMEGO konsultanta w zamówieniu-poprzedniku (lustro
    :func:`successor_line_for`).

    Audyt 22.09 r2 (FIN-MD-01). Po materializacji następca jest ``active``,
    więc powtórka importu miesiąca, w którym nadwyżka przeszła na następcę,
    dopasowywała wiersz do NASTĘPCY (``prefer_active_line``) i zapisywała na
    nim pełną liczbę — a wpis poprzednika za ten miesiąc zostawał. 20 MD
    liczone podwójnie. Podział miesiąca zaczyna się zawsze od poprzednika.

    Ta sama reguła dopasowania: najpierw ``contract_id``, potem kandydat;
    niejednoznaczność = pustka (bez zgadywania).
    """
    if order.order_group_id is None:
        return None, None
    group = await db.get(ClientOrderGroup, order.order_group_id)
    if group is None or group.predecessor_group_id is None:
        return None, None
    predecessor = await db.get(ClientOrderGroup, group.predecessor_group_id)
    if predecessor is None:
        return None, None
    lines = list(
        (
            await db.scalars(
                _line_query().where(ClientOrder.order_group_id == predecessor.id)
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
        return by_contract[0], predecessor
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
        return by_candidate[0], predecessor
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
        line_budget_total(order)
        - Decimal(str(other or 0))
        + Decimal(str(order.md_manual_adjustment or 0))
    )
    # Budżet przekroczony wcześniejszymi miesiącami nie „oddaje" MD następcy —
    # ujemna pojemność znaczy tylko tyle, że tu nie mieści się już nic.
    return capacity if capacity > ZERO else ZERO


async def _revert_earlier_transfer(
    db: AsyncSession,
    *,
    order: ClientOrder,
    group: ClientOrderGroup,
    period_month: str,
    import_id: Optional[int],
    user_id: Optional[int],
) -> None:
    """Zapis wskazany numerem cofa nadwyżkę przeniesioną wcześniej na następcę.

    Wcześniejsza paczka za ten miesiąc mogła podzielić raport tej osoby:
    część na tym zamówieniu, nadwyżka na następcy (``transfer_md``). Nowy
    wiersz z numerem TEGO zamówienia niesie całą jego liczbę, więc stary wpis
    następcy za ten miesiąc liczyłby te same MD drugi raz. Cofamy go tylko
    wtedy, gdy dziennik potwierdza przeniesienie z tego zamówienia za ten
    miesiąc, a wpis następcy pochodzi z INNEJ paczki (wiersz następcy z tej
    samej paczki jest jego własnym rozliczeniem).
    """
    successor_line, successor_group = await successor_line_for(db, order)
    if successor_line is None or successor_group is None:
        return
    transferred = await db.scalar(
        select(ClientOrderGroupEvent.id)
        .where(
            ClientOrderGroupEvent.group_id == successor_group.id,
            ClientOrderGroupEvent.event_type == EVENT_MD_TRANSFER,
            ClientOrderGroupEvent.payload["period_month"].astext == period_month,
            ClientOrderGroupEvent.payload["predecessor_group_id"].astext
            == str(group.id),
        )
        .limit(1)
    )
    if transferred is None:
        return
    entry = await db.scalar(
        select(ClientOrderMdConsumption).where(
            ClientOrderMdConsumption.order_id == successor_line.id,
            ClientOrderMdConsumption.period_month == period_month,
        )
    )
    if entry is None or (import_id is not None and entry.import_id == import_id):
        return
    from app.services.contract_lifecycle import lock_contract_then_orders

    # Kolejność blokad kontrakt → zamówienie (jak każdy writer zamówień).
    await lock_contract_then_orders(db, order_ids=[successor_line.id])
    removed = Decimal(str(entry.md_reported))
    await delete_consumption(db, successor_line, period_month)
    record_event(
        db,
        group_id=successor_group.id,
        order_id=successor_line.id,
        event_type=EVENT_MD_IMPORT,
        description=(
            f"Za {format_period_month(period_month)} cofnięto {format_md(removed)} MD "
            f"przeniesione wcześniej z zamówienia nr {group.order_number} — "
            "import wskazał to zamówienie numerem i rozliczył na nim całość."
        ),
        payload={
            "period_month": period_month,
            "md_reverted": str(removed),
            "predecessor_group_id": group.id,
            "import_id": import_id,
        },
        user_id=user_id,
    )


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
    allow_successor_transfer: bool = True,
    explicit_order: bool = False,
) -> MdConsumptionOutcome:
    """Zapisz zużycie MD, dzieląc nadwyżkę na zamówienie-następcę.

    Jedyne wejście importu do budżetu MD — obie ścieżki (wsadowa i ręczne
    rozstrzygnięcie niejednoznacznego wiersza) idą tędy, żeby podział nie
    zależał od tego, którą z nich operator akurat wybrał.

    Bez następcy zachowanie jest dotychczasowe: całość ląduje na linii
    bieżącej, a przekroczenie budżetu widać jako ujemną pozostałość. Następcy
    nie wymyślamy — zamówienie, którego nie ma, nie przejmie zużycia.

    ``allow_successor_transfer=False`` jest bezpiecznikiem jednorazowego
    replayu historycznego. Replay najpierw fail-closed wykrywa istniejącą
    kontynuację; wyłączenie transferu tutaj domyka wyścig z kontynuacją
    utworzoną już po tym sprawdzeniu, zanim zapis zdążyłby dotknąć jej
    ręcznego/nowszego rozliczenia.

    ``explicit_order=True`` (ticket 23.09.2026): wiersz arkusza wskazał TO
    zamówienie numerem. Finanse rozliczyły miesiąc osobno na każde zamówienie,
    więc zużycie zostaje dokładnie tutaj — bez przekierowania na poprzednika
    i bez przenoszenia nadwyżki na następcę. Przekroczenie budżetu zostaje
    widoczne jako ujemna pozostałość, nie jako MD na cudzym zamówieniu.
    """
    value = quantize_md(md_reported)
    successor_line: Optional[ClientOrder] = None
    successor_group: Optional[ClientOrderGroup] = None
    if allow_successor_transfer and not explicit_order:
        # Audyt 22.09 r2 (FIN-MD-01): miesiąc już raz podzielony z poprzednika
        # rozliczamy ZNOWU od poprzednika — inaczej powtórka importu po
        # materializacji zapisałaby całość na następcy, a wpis poprzednika
        # za ten miesiąc zostałby (MD liczone dwa razy).
        #
        # Tylko wpis z INNEJ paczki jest śladem takiego podziału. Wpis z tej
        # samej paczki to osobny wiersz arkusza dla poprzednika (miesiąc
        # zamiany zamówień, BIK 23.09.2026) — przekierowanie nadpisywało go
        # liczbą z wiersza następcy.
        pred_line, pred_group = await predecessor_line_for(db, order)
        pred_entry_import = (
            await db.execute(
                select(ClientOrderMdConsumption.import_id).where(
                    ClientOrderMdConsumption.order_id == pred_line.id,
                    ClientOrderMdConsumption.period_month == period_month,
                )
            )
            if pred_line is not None
            else None
        )
        pred_entry = pred_entry_import.first() if pred_entry_import else None
        if pred_entry is not None and (
            import_id is None or pred_entry.import_id != import_id
        ):
            # Poprzednik to zwykle ten sam kontrakt (ta sama osoba), więc jego
            # blokada już jest — helper dokłada tylko linię, w kolejności kontrakt → linia.
            from app.services.contract_lifecycle import lock_contract_then_orders

            await lock_contract_then_orders(db, order_ids=[pred_line.id])
            await db.scalar(
                select(ClientOrder.id)
                .where(ClientOrder.id == pred_line.id)
                .with_for_update()
            )
            order, group = pred_line, pred_group
        successor_line, successor_group = await successor_line_for(db, order)
    elif allow_successor_transfer and group is not None:
        await _revert_earlier_transfer(
            db,
            order=order,
            group=group,
            period_month=period_month,
            import_id=import_id,
            user_id=user_id,
        )

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
        order=order,
        group=group,
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
    # Cały budżet (podstawa + opcja) minus pozostałość — inaczej linia z opcją
    # pokazywałaby „wykorzystano" pomniejszone o zakres opcjonalny.
    used = (
        None
        if order.md_total is None or order.md_remaining is None
        else quantize_md(line_budget_total(order) - Decimal(str(order.md_remaining)))
    )
    context = who
    if previous and previous != md_reported:
        context = f"{who}, nadpisano wcześniejsze {format_md(previous)} MD"
    return (
        f"Za {format_period_month(period_month)} zużyto {format_md(md_reported)} MD "
        f"z zamówienia nr {order_number} ({context}) — wykorzystano "
        f"{format_md(used)} / pozostało {format_md(order.md_remaining)} MD."
    )
