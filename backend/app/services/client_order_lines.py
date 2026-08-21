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
from decimal import Decimal
from typing import Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.candidate import Candidate
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import (
    GROUP_STATUS_ACTIVE,
    ClientOrderGroup,
    ClientOrderGroupEvent,
)
from app.models.contract import Contract, ContractStatus
from app.models.job import Job
from app.models.md_consumption import (
    CONSUMPTION_SOURCE_IMPORT,
    ClientOrderMdConsumption,
)
from app.services.candidate_identity_quarantine import normalize_person_name_part
from app.services.fx_service import rates_to_pln
from app.services.multi_consultant_orders import (
    format_md,
    is_multi_consultant_client,
    quantize_md,
)

ZERO = Decimal("0")
STANDARD_WORKING_DAYS_PER_MONTH = Decimal("22")
MONEY_SCALE = Decimal("0.01")


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
) -> tuple[Optional[Decimal], bool, Optional[int]]:
    """Podpowiedź kosztu /MD z bieżącego kontraktu + sygnał rozbieżności.

    `active` i `ending` są biznesowo żywe (cron przenosi kontrakt do
    `ending` już 30 dni przed końcem), więc oba kwalifikują się do
    podpowiedzi. Stawkę rozwiązujemy z harmonogramu na dzień odczytu, a nie
    z cache'owanej kolumny `contracts.rate_candidate`, która może być
    nieaktualna po wejściu w życie zaplanowanego aneksu.

    Kontrakt przechowuje stawkę godzinową, dzienną albo miesięczną, a linia
    zamówienia zawsze zł/MD. Dlatego każdą stawkę normalizujemy najpierw do
    miesięcznej wartości tym samym mechanizmem co marża kontraktu, a potem do
    standardowego miesiąca 22 MD. Kwoty w obcych walutach przeliczamy po
    zapisanym kursie na PLN; przy braku kursu nie podpowiadamy wartości. W
    przeciwnym razie np. 100 EUR/h trafiłoby do formularza jako 100 zł/MD.

    Ostrzeżenie porównuje wszystkie nieanulowane kontrakty tej osoby u TEGO
    klienta, także historyczne, już po tej samej normalizacji. Brak stawki nie
    jest inną stawką; dwa kontrakty z tą samą wartością /MD nie generują
    ostrzeżenia.
    """

    def rate_per_md(contract: Contract) -> Optional[Decimal]:
        rate = contract.effective_candidate_rate(on)
        monthly = contract.monthly_rate(rate)
        currency = (contract.currency or "PLN").upper()
        rate_to_pln = currency_rates.get(currency)
        if monthly is None or rate_to_pln is None:
            return None
        return (monthly * rate_to_pln / STANDARD_WORKING_DAYS_PER_MONTH).quantize(
            MONEY_SCALE
        )

    live = [c for c in contracts if c.status in LIVE_CONTRACT_STATUSES]
    current = max(live, key=_contract_recency_key) if live else None
    suggested = rate_per_md(current) if current is not None else None

    distinct_rates = {
        rate.normalize()
        for contract in contracts
        if contract.status != ContractStatus.void
        and (rate := rate_per_md(contract)) is not None
    }
    return suggested, len(distinct_rates) > 1, current.id if current else None


def _sort_key(option: ConsultantOption) -> tuple[str, str, int]:
    """Alfabetycznie po imieniu, po kluczu bez diakrytyków.

    Sortowanie robimy w Pythonie, a nie `ORDER BY` w bazie: prod nie ma
    rozszerzenia `unaccent`, więc „Łukasz" w SQL-u wylądowałby za „Zbigniewem".
    Ten sam normalizator co przy dopasowaniu nazwisk, żeby kolejność i wyniki
    wyszukiwania nie rozjeżdżały się między sobą.
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
        suggested_rate, has_different_rates, current_contract_id = _rate_suggestion(
            contracts, on=today, currency_rates=currency_rates
        )

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


async def recompute_remaining(db: AsyncSession, order: ClientOrder) -> Decimal:
    """Przelicz ``md_remaining`` od zera i zapisz na linii.

    Jedyny writer tego pola. Wartość może zejść do zera i poniżej —
    przekroczony budżet jest faktem handlowym, więc nie jest tu ścinany;
    sygnalizuje go interfejs kolorem.
    """
    if order.md_total is None:
        order.md_remaining = None
        return ZERO
    consumed = await consumed_md(db, order.id)
    adjustment = Decimal(str(order.md_manual_adjustment or 0))
    remaining = quantize_md(Decimal(str(order.md_total)) - consumed + adjustment)
    order.md_remaining = remaining
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
    order: ClientOrder, period_month: str, md_reported: Decimal, previous: Decimal
) -> str:
    who = consultant_display_name(order)
    if previous and previous != md_reported:
        return (
            f"Import MD za {period_month}: {who} — {format_md(md_reported)} MD "
            f"(nadpisano wcześniejsze {format_md(previous)} MD). "
            f"Pozostało {format_md(order.md_remaining)} MD."
        )
    return (
        f"Import MD za {period_month}: {who} — {format_md(md_reported)} MD. "
        f"Pozostało {format_md(order.md_remaining)} MD."
    )
