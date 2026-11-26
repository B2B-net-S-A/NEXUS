"""Kim jest konsultant portalu: wyłącznie adres z kontraktu.

Konta nie ma, więc tożsamością jest ``contracts.candidate_email``. Adres pasujący
do dwóch różnych osób (wspólna skrzynka, błąd w danych) nie otwiera niczego: nie
da się powiedzieć, czyje sprawy pokazać. Kontrakt zakończony działa jeszcze
``ENDED_GRACE_DAYS``, bo ostatni raport i faktura przychodzą po końcu współpracy.
"""

from __future__ import annotations

import calendar
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING, Iterable, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contact import Contact
from app.models.contract import Contract, ContractStatus
from app.models.user import User
from app.services.consultant_portal.portal_settings import PortalSettings

if TYPE_CHECKING:
    from app.services.client_settlements import timesheet_plus

ENDED_GRACE_DAYS = 60
_LIVE = (ContractStatus.active, ContractStatus.ending)


@dataclass(frozen=True)
class Consultant:
    contract_id: int
    email: str
    contract_ids: tuple[int, ...]
    candidate_id: Optional[int]
    first_name: Optional[str]
    phone: Optional[str]


def normalize_email(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def eligible(contract: Contract, today: date) -> bool:
    if contract.status in _LIVE:
        return True
    return (
        contract.status == ContractStatus.ended
        and contract.end_date is not None
        and contract.end_date >= today - timedelta(days=ENDED_GRACE_DAYS)
    )


async def _contracts_for_email(
    db: AsyncSession, email: str, *, settings: PortalSettings, today: date
) -> list[Contract]:
    rows = (
        await db.scalars(
            select(Contract)
            .where(func.lower(Contract.candidate_email) == email)
            .order_by(Contract.start_date.desc().nulls_last(), Contract.id.desc())
        )
    ).all()
    return [row for row in rows if eligible(row, today) and settings.open_for(row.id)]


async def resolve_by_email(
    db: AsyncSession, email: str, *, settings: PortalSettings, today: date
) -> Optional[Contract]:
    """Kontrakt, na który wolno wysłać link, albo ``None``."""

    address = normalize_email(email)
    if not address:
        return None
    contracts = await _contracts_for_email(db, address, settings=settings, today=today)
    if not contracts:
        return None
    people = {
        row.candidate_id if row.candidate_id else f"c{row.id}" for row in contracts
    }
    return contracts[0] if len(people) == 1 else None


async def resolve_sender(
    db: AsyncSession, email: str, *, settings: PortalSettings, today: date
) -> Optional[Contract]:
    """Kontrakt nadawcy maila na rozliczenia@ albo ``None`` (karta do przypisania).

    W pilotażu tylko osoby z aktywnym panelem (jak link). W ``internal`` i ``all`` każdy
    działający kontrakt: najpierw adres z kontraktu, potem adres z kartoteki kandydata.
    Dopasowanie nie otwiera panelu ani nie wysyła maila, a dokument z maila i tak czeka
    na decyzję Finansów. Więcej niż jeden działający kontrakt pod adresem = ``None``.
    """

    if not settings.any_sender:
        return await resolve_by_email(db, email, settings=settings, today=today)
    rows = await _sender_contracts(db, normalize_email(email), today=today)
    # Jeden działający kontrakt = jedno dopasowanie. Dwa (zmiana kontraktu w ostatnich
    # 60 dniach, dwóch klientów naraz) albo dwie osoby = karta do ręcznego przypisania:
    # przypisanego dokumentu Finanse nie przepną, a RCP od razu liczy rozliczenie.
    # Raport z okresem rozstrzyga dopiero ``resolve_sender_in_month``.
    return rows[0] if len(rows) == 1 else None


async def resolve_report_owner(
    db: AsyncSession, email: str, *, settings: PortalSettings, today: date
) -> Optional[Contract]:
    """Kontrakt dla raportu godzin od osoby pracującej naraz u dwóch klientów.

    Klient rozliczany z raportu T4T (Nordea) nie bierze godzin z poczty, więc raport
    od osoby z kontraktem u niego i jednym kontraktem gdzie indziej jest tego
    drugiego (Nordea 292 / Bosch 623: „W załączniku Timesheet (Bosch)”). Faktura
    nie: konsultant bywa, że wystawia jedną na obu klientów (IX 2026: 252 h =
    Nordea + MS Enter-Prise), więc czeka na ręczne przypisanie jak dotąd.
    """

    if not settings.any_sender:
        return None
    rows = await _sender_contracts(db, normalize_email(email), today=today)
    people = {row.candidate_id for row in rows}
    if len(rows) < 2 or len(people) != 1 or None in people:
        return None
    from app.services.client_settlements import time_reports

    from_t4t = set(await time_reports.enabled_clients(db, f"{today:%Y-%m}"))
    rest = [row for row in rows if row.client_id not in from_t4t]
    return rest[0] if len(rest) == 1 and len(rest) < len(rows) else None


def works_in_month(contract: Contract, year: int, month: int) -> bool:
    """Okres kontraktu obejmuje choć jeden dzień miesiąca (brak daty = bez granicy)."""

    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    return (contract.start_date is None or contract.start_date <= last) and (
        contract.end_date is None or contract.end_date >= first
    )


async def resolve_sender_in_month(
    db: AsyncSession, email: str, *, year: int, month: int, today: date
) -> Optional[Contract]:
    """Kontrakt nadawcy dla raportu za ``year``-``month``, gdy adres wskazuje kilka.

    Osoba zmienia klienta, a poprzedni kontrakt działa jeszcze ``ENDED_GRACE_DAYS``
    po końcu, więc adres wskazuje oba i raport czekał na człowieka (próba IX–X 2026,
    VeloBank 466 i 467: Time Sheet za IX z adresu firmy, kontrakty w Banku Pocztowym
    zakończone 31.08). Raport za miesiąc, którego okres kontraktu nie obejmuje, nie
    jest tego kontraktu. Tylko kontrakty jednej osoby; dwa kontrakty w tym miesiącu
    albo żaden = ``None``. Okres musi wynikać z pliku albo tematu, nie z daty maila.
    """

    rows = await _sender_contracts(db, normalize_email(email), today=today)
    people = {row.candidate_id for row in rows}
    if len(rows) < 2 or len(people) != 1 or None in people:
        return None
    hits = [row for row in rows if works_in_month(row, year, month)]
    return hits[0] if len(hits) == 1 else None


async def contracts_at_several_clients(
    db: AsyncSession,
    *,
    owner_id: Optional[int],
    sender: str,
    settings: PortalSettings,
    today: date,
) -> list[Contract]:
    """Działające kontrakty osoby, która pracuje naraz u co najmniej dwóch klientów.

    Osoba to ta z kontraktu wybranego już dla pliku (``owner_id``), a bez niego
    jedyna osoba pod adresem nadawcy. Nieustalona osoba albo kontrakty u jednego
    klienta = pusta lista.
    """

    if owner_id is not None:
        owner = await db.get(Contract, owner_id)
        people = {owner.candidate_id} if owner is not None else set()
    else:
        rows = await _sender_contracts(db, normalize_email(sender), today=today)
        people = {row.candidate_id for row in rows}
    if len(people) != 1 or None in people:
        return []
    rows = await db.scalars(
        select(Contract).where(Contract.candidate_id == next(iter(people)))
    )
    contracts = [
        row
        for row in rows.all()
        if eligible(row, today) and (settings.any_sender or settings.open_for(row.id))
    ]
    return contracts if len({row.client_id for row in contracts}) > 1 else []


@dataclass(frozen=True)
class TemplateChoice:
    """Kontrakt wskazany wzorem dokumentu; ``None`` = karta do ręcznego przypisania."""

    contract: Optional[Contract]


async def resolve_by_template(
    db: AsyncSession,
    contracts: list[Contract],
    *,
    client_key: str,
    person: Optional[str],
    month: Optional[tuple[int, int]],
    owner_id: Optional[int],
) -> Optional[TemplateChoice]:
    """Kontrakt dla dokumentu we wzorze klienta, gdy osoba pracuje u dwóch klientów.

    Konsultant z kontraktem w Banku Pocztowym i VeloBanku wysyła z adresu firmy
    jednym mailem kartę KCP i Time Sheet (VII i VIII 2026), więc nadawca nie
    rozstrzyga, a temat i cytaty w treści wskazują najwyżej jeden z banków. Wzór
    dokumentu (``templates.recognize``) mówi, którego klienta to plik.
    ``contracts`` to wynik ``contracts_at_several_clients``.

    ``None`` = wzór niczego tu nie zmienia i czytnik działa jak dotąd: u klienta
    wzoru osoba nie ma kontraktu, w pliku stoi inna osoba albo wybrany już
    kontrakt jest u tego klienta.

    Inaczej wynik to jedyny kontrakt osoby u klienta wzoru, który działa
    w miesiącu dokumentu. Dwa takie, żaden albo brak miesiąca = ``contract=None``:
    przypisuje człowiek, a plik nie idzie do klienta, którego wzorem nie jest.
    """

    clients = await _clients_of_keys(db, (client_key,))
    there = [row for row in contracts if row.client_id in clients]
    if not there or any(row.id == owner_id for row in there):
        return None
    if person and not await _is_person(db, there[0].candidate_id, person):
        return None
    hits = [row for row in there if month and works_in_month(row, *month)]
    return TemplateChoice(hits[0] if len(hits) == 1 else None)


async def _is_person(db: AsyncSession, candidate_id: int, text: str) -> bool:
    """Imię i nazwisko z pliku to ta osoba z kartoteki. Dodatkowe słowa nie
    przeszkadzają: karta Banku Pocztowego ma w tym polu także skrót działu."""

    words = _words(text)
    row = (
        await db.execute(
            select(Candidate.name, Candidate.lastname).where(
                Candidate.id == candidate_id
            )
        )
    ).first()
    return row is not None and any(
        len(name) >= 2 and set(name) <= words for name in _people(row[0], row[1])
    )


async def sender_contract_ids(
    db: AsyncSession, address: str, *, today: date
) -> frozenset[int]:
    """Działające kontrakty, których konsultant pisze z tego adresu (bez wyboru jednego)."""

    rows = await _sender_contracts(db, normalize_email(address), today=today)
    return frozenset(row.id for row in rows)


async def _sender_contracts(
    db: AsyncSession, address: str, *, today: date
) -> list[Contract]:
    """Działające kontrakty pod adresem: z kontraktu, z kartoteki, z adresu firmy."""

    if not address:
        return []
    by_contract = (
        await db.scalars(
            select(Contract)
            .where(func.lower(func.btrim(Contract.candidate_email)) == address)
            .order_by(Contract.start_date.desc().nulls_last(), Contract.id.desc())
        )
    ).all()
    rows = [row for row in by_contract if eligible(row, today)]
    if not rows:
        by_card = (
            await db.scalars(
                select(Contract)
                .join(Candidate, Candidate.id == Contract.candidate_id)
                .where(func.lower(func.btrim(Candidate.email)) == address)
                .order_by(Contract.start_date.desc().nulls_last(), Contract.id.desc())
            )
        ).all()
        rows = [row for row in by_card if eligible(row, today)]
    if not rows:
        rows = await _by_gmail_alias(db, address, today=today)
    if not rows:
        rows = await _by_company_address(db, address, today=today)
    return rows


_GMAIL = ("gmail.com", "googlemail.com")


async def _by_gmail_alias(
    db: AsyncSession, address: str, *, today: date
) -> list[Contract]:
    """Ten sam adres Gmaila zapisany z kropkami albo bez (``jan.nowak@`` = ``jannowak@``).

    Gmail pomija kropki w nazwie skrzynki, więc konsultant pisze z jednej formy, a
    kontrakt ma drugą (próba IX–X 2026, BIK 690: raport z ``imienazwisko@gmail.com``,
    w kontrakcie ``imie.nazwisko@gmail.com``). Tylko adres z kontraktu, bez kartoteki.
    """

    local, _, domain = address.partition("@")
    if domain not in _GMAIL or not local:
        return []
    stored = func.lower(func.btrim(Contract.candidate_email))
    rows = (
        await db.scalars(
            select(Contract)
            .where(
                func.split_part(stored, "@", 2).in_(_GMAIL),
                func.replace(func.split_part(stored, "@", 1), ".", "")
                == local.replace(".", ""),
            )
            .order_by(Contract.start_date.desc().nulls_last(), Contract.id.desc())
        )
    ).all()
    return [row for row in rows if eligible(row, today)]


def _company_domains() -> frozenset[str]:
    """Domeny adresów rozliczeń: konsultanci mają w nich skrzynki firmowe."""

    from app.services import support_mail_route

    return frozenset(
        address.rsplit("@", 1)[1]
        for address in support_mail_route.settlements_addresses()
        if "@" in address
    )


def _personal_domains() -> frozenset[str]:
    """Domeny skrzynek od klienta (``imie.nazwisko@external.bnpparibas.pl``)."""

    from app.core.config import settings

    raw = settings.CONSULTANT_PORTAL_PERSONAL_DOMAINS or ""
    return frozenset(
        part.strip().lower().lstrip("@") for part in raw.split(",") if part.strip()
    )


def is_company_address(address: str) -> bool:
    return normalize_email(address).rpartition("@")[2] in _company_domains()


def _address_forms(first: Optional[str], last: Optional[str]) -> set[str]:
    """Lokalne części adresu firmowego osoby: ``jan.kowalski``, ``j.kowalski``,
    ``jan_kowalski``, ``jankowalski``; nazwisko dwuczłonowe także po członie,
    po zmianie nazwiska także stare (``Nowe (Stare)``)."""

    given = _given(first)
    if not given:
        return set()
    name = given[0]
    forms: set[str] = set()
    for parts in _surnames(last):
        for surname in {"".join(parts), "-".join(parts), *parts}:
            for sep in (".", "_", "-", ""):
                forms.add(name + sep + surname)
            forms.add(name[0] + "." + surname)
            forms.add(name[0] + surname)
    return forms


# Skrzynka konsultanta u klienta bywa z przedrostkiem: Bosch zakłada
# ``external.imie.nazwisko@de.bosch.com`` (próba IX–X 2026, Bosch 627).
_EXTERNAL_PREFIX = re.compile(r"^(?:external|ext)[._-]")


async def _by_company_address(
    db: AsyncSession, address: str, *, today: date
) -> list[Contract]:
    """Działające kontrakty osoby z adresu firmowego ``imie.nazwisko@<domena>``.

    Kontrakt i kartoteka mają adres prywatny, a konsultanci piszą ze skrzynek
    firmowych (próba IX–XI 2026: bez tego 14% dokumentów z nadawcą). Konto
    NEXUSA pod tym adresem = pracownik przesyła cudze pliki, więc nikt. Dwie
    osoby o tej samej formie adresu = nikt (karta do ręcznego przypisania).
    Tak samo skrzynka od klienta (``CONSULTANT_PORTAL_PERSONAL_DOMAINS``):
    BNP zakłada konsultantom ``imie.nazwisko@external.bnpparibas.pl``.

    Skrzynka w domenie znanego klienta (``P.Nazwisko@pocztowy.pl``) wskazuje
    tylko kontrakty u tego klienta: osoba pracuje naraz w Banku Pocztowym
    i VeloBanku, a KCP przychodzi z jednej domeny, timesheet z drugiej (próba
    IX–X 2026). Bez kontraktu u tego klienta to raczej jego pracownik o tym
    samym nazwisku, więc nikt. Poddomena klienta (``de.bosch.com``) i przedrostek
    ``external.`` przed imieniem wskazują tak samo.
    """

    local, _, domain = address.partition("@")
    local = _EXTERNAL_PREFIX.sub("", local)
    at_client = await _clients_of_domain(db, domain)
    if not local or (
        at_client is None and domain not in (_company_domains() | _personal_domains())
    ):
        return []
    staff = await db.scalar(
        select(User.id).where(func.lower(func.btrim(User.email)) == address).limit(1)
    )
    if staff is not None:
        return []
    rows = (
        await db.execute(
            select(Contract, Candidate.name, Candidate.lastname)
            .join(Candidate, Candidate.id == Contract.candidate_id)
            .where(
                Contract.status.in_(_LIVE)
                | (
                    (Contract.status == ContractStatus.ended)
                    & (Contract.end_date >= today - timedelta(days=ENDED_GRACE_DAYS))
                )
            )
            .order_by(Contract.start_date.desc().nulls_last(), Contract.id.desc())
        )
    ).all()
    hits = [
        contract
        for contract, first, last in rows
        if local in _address_forms(first, last) and eligible(contract, today)
    ]
    if len({c.candidate_id for c in hits}) != 1:
        return []
    if at_client is not None:
        return [c for c in hits if c.client_id in at_client]
    return hits


async def _clients_of_domain(db: AsyncSession, domain: str) -> Optional[frozenset[int]]:
    """Klienci, z których domeny piszą ich pracownicy, albo ``None`` (domena obca).

    Klucz z rejestru domen zamówień, klient po numerze rejestrowym. Domena grupy
    (``plus.pl``) daje wszystkie spółki grupy, więc kontrakt wybiera dopiero człowiek.
    Poddomena należy do klienta tylko przy domenie z ``SUBDOMAIN_SENDER_DOMAINS``:
    Bosch pisze z ``pl.bosch.com`` i ``de.bosch.com``, a rejestr zna ``bosch.com``.
    Inne poddomeny (``consult.nordea.com``) zostają obce.
    """

    from app.services.order_policies import known_clients

    labels = domain.split(".")
    for start in range(max(len(labels) - 1, 0)):
        candidate = ".".join(labels[start:])
        if start and candidate not in known_clients.SUBDOMAIN_SENDER_DOMAINS:
            continue
        keys = known_clients.SHARED_SENDER_DOMAINS.get(candidate) or tuple(
            key for key in (known_clients.KNOWN_SENDER_DOMAINS.get(candidate),) if key
        )
        if keys:
            return await _clients_of_keys(db, keys)
    return None


async def _clients_of_keys(db: AsyncSession, keys: tuple[str, ...]) -> frozenset[int]:
    """Klienci z rejestru zamówień (``known_clients``) po numerze rejestrowym."""

    from app.services.order_policies import known_clients

    numbers: set[str] = set()
    for key in keys:
        numbers.update(known_clients.KNOWN_REGISTRY_IDS.get(key, ()))
        markers = known_clients.KNOWN_MARKERS.get(key)
        if markers is not None:
            numbers.update(markers.foreign_registry_ids)
    if not numbers:
        return frozenset()
    nip = func.upper(func.replace(func.replace(Client.nip, "-", ""), " ", ""))
    rows = await db.scalars(
        select(Client.id).where(nip.in_(numbers), Client.deleted_at.is_(None))
    )
    return frozenset(rows.all())


async def resolve_from_sheet(
    db: AsyncSession, sheet: "timesheet_plus.Sheet", *, sender: str, today: date
) -> Optional[Contract]:
    """Kontrakt z raportu godzin grupy Polkomtel / Cyfrowy Polsat.

    Konsultant grupy ma kontrakt w każdej spółce (Polkomtel 471 / Cyfrowy Polsat
    633), więc nadawca nie rozstrzyga, a plik tak: osoba z wiersza, kontrakt z jej
    linii zamówienia o numerze z wiersza (bez anulowanych). Raport Polkomtelu bez
    numeru albo z numerem spoza NEXUSA należy do kontraktu u Polkomtelu (decyzja
    Artura z 23.11.2026). Treść pliku wskazuje osobę tylko od skrzynki firmy, od
    klienta z domeny z rejestru (wśród jego kontraktów) albo od tej samej osoby.
    Dwie osoby w pliku albo dwa kontrakty w trafieniu = ``None``.
    """

    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.client_order_group import ClientOrderGroup
    from app.services.client_settlements import timesheet_plus

    named = timesheet_plus.people(sheet)
    if len(named) != 1:
        return None
    address = normalize_email(sender)
    scope: Optional[frozenset[int]] = None
    own: Optional[set[Optional[int]]] = None
    if not is_company_address(address):
        scope = await _clients_of_domain(db, address.rpartition("@")[2])
        if scope is None:
            own = {
                c.candidate_id
                for c in await _sender_contracts(db, address, today=today)
            }
            if not own:
                return None
    mine = [
        contract
        for contract, first, last in await _named_rows(
            db, today=today, client_ids=scope
        )
        if named[0] in _name_sets(first, last)
        and eligible(contract, today)
        and (own is None or contract.candidate_id in own)
    ]
    if len({c.candidate_id for c in mine}) != 1:
        return None
    hits: list[Contract] = []
    orders = {timesheet_plus.order_key(row.order) for row in sheet.rows} - {None}
    if orders:
        lines = await db.execute(
            select(ClientOrder.contract_id, ClientOrderGroup.order_number)
            .join(ClientOrderGroup, ClientOrderGroup.id == ClientOrder.order_group_id)
            .where(
                ClientOrder.contract_id.in_([c.id for c in mine]),
                ClientOrder.status != ClientOrderStatus.cancelled,
            )
        )
        ordered = {
            cid for cid, number in lines if timesheet_plus.order_key(number) in orders
        }
        hits = [c for c in mine if c.id in ordered]
    if not hits and sheet.source == timesheet_plus.POLKOMTEL:
        polkomtel = await _clients_of_keys(db, ("polkomtel",))
        hits = [c for c in mine if c.client_id in polkomtel]
    return hits[0] if len(hits) == 1 else None


async def resolve_sheet_contracts(
    db: AsyncSession, sheet: "timesheet_plus.Sheet", *, sender: str, today: date
) -> list[Contract]:
    """Kontrakty wszystkich osób i zamówień z arkusza grupy Polkomtel / Cyfrowy Polsat.

    Próba VI–VIII 2026: jeden wykaz od kierownika klienta niesie wiersze dwóch osób
    albo jednej osoby na zamówieniach Polsatu i Polkomtelu (kontrakt w każdej
    spółce). Każda para (osoba, numer zamówienia) przechodzi ``resolve_from_sheet``
    na wycinku arkusza z tymi wierszami, więc zasady nadawcy i numeru zostają te same.
    Kolejność kontraktów jak w pliku, bez powtórzeń."""

    from dataclasses import replace

    from app.services.client_settlements import timesheet_plus
    from app.services.client_settlements.rcp_checks import name_tokens

    found: list[Contract] = []
    groups: dict[tuple[frozenset[str], Optional[str]], list] = {}
    for row in sheet.rows:
        key = (frozenset(name_tokens(row.person)), timesheet_plus.order_key(row.order))
        groups.setdefault(key, []).append(row)
    for rows in groups.values():
        part = replace(sheet, rows=tuple(rows))
        contract = await resolve_from_sheet(db, part, sender=sender, today=today)
        if contract is not None and contract.id not in {c.id for c in found}:
            found.append(contract)
    return found


async def split_client(db: AsyncSession, order_keys: frozenset[str]) -> Optional[int]:
    """Klient, do którego należą numery zamówień z tabeli klienta (podział na
    zamówienia z maila, ``client_settlements/order_split``). Numery u dwóch
    klientów albo żaden w NEXUS-ie = ``None``."""

    from app.models.client_order_group import ClientOrderGroup
    from app.services.client_settlements import order_split

    if not order_keys:
        return None
    rows = await db.execute(
        select(ClientOrderGroup.client_id, ClientOrderGroup.order_number).where(
            or_(*(ClientOrderGroup.order_number.contains(key) for key in order_keys))
        )
    )
    clients = {
        client_id
        for client_id, number in rows.all()
        if order_split.order_key(number) in order_keys
    }
    return next(iter(clients)) if len(clients) == 1 else None


async def resolve_split_row(
    db: AsyncSession,
    name: str,
    *,
    client_id: int,
    order_keys: frozenset[str],
    today: date,
) -> Optional[Contract]:
    """Kontrakt osoby z wiersza tabeli klienta „osoba × numer zamówienia”.

    Tylko wśród kontraktów tego klienta (decyzja z 24.11.2026, jak przy nazwie
    pliku od klienta): wszystkie słowa imienia i nazwiska, kolejność dowolna
    („Nazwisko Imię” z tabeli przestawnej). Osoba z dwoma kontraktami u klienta:
    ten z linią zamówienia o numerze z tabeli. Dwie osoby albo dwa kontrakty
    w trafieniu = ``None``."""

    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.client_order_group import ClientOrderGroup
    from app.services.client_settlements import order_split

    wanted = _tokens(name)
    if len(wanted) < 2:
        return None
    mine = [
        contract
        for contract, first, last in await _named_rows(
            db, today=today, client_ids=frozenset({client_id})
        )
        if _tokens(f"{first or ''} {last or ''}") == wanted
        and eligible(contract, today)
    ]
    if len({c.candidate_id for c in mine}) != 1:
        return None
    if len(mine) == 1:
        return mine[0]
    lines = await db.execute(
        select(ClientOrder.contract_id, ClientOrderGroup.order_number)
        .join(ClientOrderGroup, ClientOrderGroup.id == ClientOrder.order_group_id)
        .where(
            ClientOrder.contract_id.in_([c.id for c in mine]),
            ClientOrder.status != ClientOrderStatus.cancelled,
        )
    )
    ordered = {
        cid
        for cid, number in lines.all()
        if order_split.order_key(number) in order_keys
    }
    hits = [c for c in mine if c.id in ordered]
    return hits[0] if len(hits) == 1 else None


async def resolve_named_in_text(
    db: AsyncSession, text: str, *, today: date
) -> Optional[Contract]:
    """Kontrakt osoby, której imię i nazwisko stoi w temacie albo nazwie pliku.

    Ostatnia deska, gdy nadawca z adresu firmy nikogo nie wskazuje: koordynator
    przesyła cudze pliki („TimeSheet … Nazwisko Imię.xls”). Czytnik pyta tylko dla
    nadawców z domeny firmy, bo temat może napisać każdy. Kolejność słów dowolna, imię
    i każdy człon nazwiska muszą stać w tekście. Po zmianie nazwiska (kartoteka
    „Nowe (Stare)”) wystarcza jedno z nazwisk. Dwie osoby w tekście albo jedna
    z dwoma działającymi kontraktami = ``None`` (karta do ręcznego przypisania).
    """

    words = _words(text)
    if len(words) < 2:
        return None
    rows = await _named_rows(db, today=today)
    hits = []
    for contract, first, last in rows:
        if eligible(contract, today) and any(
            len(person) >= 2 and set(person) <= words for person in _people(first, last)
        ):
            hits.append(contract)
    if len(hits) != 1:
        return None
    return hits[0]


def _words(text: str) -> set[str]:
    return set(_fold(re.sub(r"[^\w]+|_", " ", text)).split())


# Poprzednie nazwisko w kartotece stoi w nawiasie: „Nowe (Stare)” (Orlen, zmiana
# nazwiska wpisana na produkcji 23.11.2026).
_PREVIOUS_SURNAME = re.compile(r"\(([^()]*)\)")


def _given(first: Optional[str]) -> list[str]:
    return _fold(first).split()[:1]


def _surnames(last: Optional[str]) -> list[list[str]]:
    """Człony nazwiska: obecnego i każdego poprzedniego z nawiasu.

    Po zmianie nazwiska pliki przychodzą raz ze starym, raz z nowym nazwiskiem,
    a raz z oboma, więc każde wskazuje osobę samo. Nawias nie jest częścią członu:
    dotąd „(stare)” nie trafiało w żadne słowo nazwy pliku i osoba znikała
    z rozliczeń (próba IX–X 2026, Orlen 429).
    """

    folded = _fold(last)
    previous = [group.split() for group in _PREVIOUS_SURNAME.findall(folded)]
    current = re.sub(r"[()]", " ", _PREVIOUS_SURNAME.sub(" ", folded)).split()
    return [parts for parts in (current, *previous) if parts]


def _people(first: Optional[str], last: Optional[str]) -> list[list[str]]:
    """Imię i człony nazwiska w każdym wariancie nazwiska."""

    given = _given(first)
    return [given + parts for parts in _surnames(last)]


def _name_sets(first: Optional[str], last: Optional[str]) -> list[set[str]]:
    """Wszystkie słowa imion z każdym wariantem nazwiska (porównanie całych zbiorów)."""

    names = _tokens(first)
    return [names | set(parts) for parts in _surnames(last)]


async def _named_rows(
    db: AsyncSession, *, today: date, client_ids: Optional[frozenset[int]] = None
) -> list:
    query = (
        select(Contract, Candidate.name, Candidate.lastname)
        .join(Candidate, Candidate.id == Contract.candidate_id)
        .where(
            Contract.status.in_(_LIVE)
            | (
                (Contract.status == ContractStatus.ended)
                & (Contract.end_date >= today - timedelta(days=ENDED_GRACE_DAYS))
            )
        )
        .order_by(Contract.start_date.desc().nulls_last(), Contract.id.desc())
    )
    if client_ids is not None:
        query = query.where(Contract.client_id.in_(client_ids))
    return list((await db.execute(query)).all())


async def client_ids_for_sender(db: AsyncSession, address: str) -> frozenset[int]:
    """Klienci, do których należy domena nadawcy: adres w kontaktach klienta albo
    domena z rejestru domen klientów (``known_clients``, po NIP-ie). Orlen Upstream
    pisze z ``pgnig.pl``, a w kontaktach Orlenu jest tylko ``orlen.pl`` (protokół IX
    2026 przyszedł z ``pgnig.pl``, przegląd skrzynek 23.11.2026).

    Domena firmy (adresy rozliczeń i SSO), skrzynek konsultantów u klienta i poczty
    publicznej (gmail, wp) nie należy do żadnego klienta, bo pisze z niej każdy.
    """

    from app.services.m365.matcher import PUBLIC_EMAIL_DOMAINS

    domain = normalize_email(address).rpartition("@")[2]
    from app.core.config import settings

    if not domain or domain in (
        PUBLIC_EMAIL_DOMAINS
        | _company_domains()
        | _personal_domains()
        | set(settings.sso_allowed_domains_list)
    ):
        return frozenset()
    rows = await db.scalars(
        select(Contact.client_id)
        .where(func.lower(func.split_part(func.btrim(Contact.email), "@", 2)) == domain)
        .distinct()
    )
    known = await _clients_of_domain(db, domain) or frozenset()
    return frozenset(rows.all()) | known


# Słowo miesiąca w nazwie pliku („TimeSheet maj 2026”) nie jest samym nazwiskiem.
_MONTH_WORDS = frozenset(
    {
        "styczen", "stycznia", "luty", "lutego", "marzec", "marca",
        "kwiecien", "kwietnia", "maj", "maja", "czerwiec", "czerwca",
        "lipiec", "lipca", "sierpien", "sierpnia", "wrzesien", "wrzesnia",
        "pazdziernik", "pazdziernika", "listopad", "listopada",
        "grudzien", "grudnia", "march", "may", "june", "august",
    }
)  # fmt: skip


async def resolve_named_at_client(
    db: AsyncSession, text: str, *, client_ids: frozenset[int], today: date
) -> Optional[Contract]:
    """Kontrakt osoby z nazwy pliku, który klient tej osoby przysłał ze swojej domeny.

    Klient przekazuje raport konsultanta („TimeSheet 2609 - Nazwisko Imię.xlsm”,
    „TimeSheet_ImięNazwisko_wrzesień.xlsx”, „Nazwisko, wrzesien 2026 Time Sheet.pdf”;
    próba IX–X 2026: PKO, ERGO, BIK). Szukamy tylko wśród kontraktów tych klientów
    (decyzja Artura z 23.11.2026). Imię i nazwisko w dowolnej kolejności albo
    sklejone; bez imienia samo nazwisko, gdy u tych klientów nosi je jedna osoba,
    nie jest słowem miesiąca, a w nazwie nie stoi imię innej osoby z działającym
    kontraktem. Dwa kontrakty w trafieniu = ``None``.
    """

    words = _words(text)
    if not words or not client_ids:
        return None
    full: list[tuple[Contract, tuple[str, ...]]] = []
    by_surname: list[tuple[Contract, tuple[str, ...]]] = []
    for contract, first, last in await _named_rows(
        db, today=today, client_ids=client_ids
    ):
        if not eligible(contract, today):
            continue
        given = _given(first)
        surnames = _surnames(last)
        whole = next(
            (
                surname
                for surname in surnames
                if given
                and (
                    set(given + surname) <= words
                    or {"".join(given + surname), "".join(surname + given)} & words
                )
            ),
            None,
        )
        alone = next(
            (
                surname
                for surname in surnames
                if not set(surname) & _MONTH_WORDS
                and (set(surname) <= words or "".join(surname) in words)
            ),
            None,
        )
        if whole is not None:
            full.append((contract, tuple(whole)))
        elif alone is not None:
            by_surname.append((contract, tuple(alone)))
    if len(full) == 1:
        # Imię rozstrzyga między osobami o tym samym nazwisku, ale inne nazwisko
        # osoby klienta w tej samej nazwie pliku to druga osoba.
        named = full[0][1]
        return None if any(s != named for _, s in by_surname) else full[0][0]
    if full or len(by_surname) != 1:
        return None
    # Samo nazwisko, ale z cudzym imieniem w nazwie („Kowalski Anna”, gdy u klienta
    # pracuje Jan Kowalski) to inna osoba, nie jedyna osoba klienta o tym nazwisku.
    contract = by_surname[0][0]
    own = await db.scalar(
        select(Candidate.name).where(Candidate.id == contract.candidate_id)
    )
    others = {
        name
        for _, first, _ in await _named_rows(db, today=today)
        for name in _fold(first).split()[:1]
    } - set(_fold(own).split()[:1])
    return None if words & others else contract


async def resolve_named_for_clients(
    db: AsyncSession,
    text: str,
    client_ids: frozenset[int],
    *,
    settings: PortalSettings,
    today: date,
) -> Optional[Contract]:
    """Osoba z tematu akceptacji od klienta, tylko wśród kontraktów tego klienta.

    Klient odpisuje w wątku z TS bez załącznika: „Akceptacja godzin wrzesień 2026 -
    P. Nowak” (BIK), „Odbiór usług za 10.2026: Nowak Piotr” (PKO). Każdy człon nazwiska
    musi stać w tekście, imię pełne albo jego inicjał. Szukamy tylko u klientów z domeny
    nadawcy, więc mail od jednego klienta nie wskaże osoby u innego. Dwie osoby albo
    osoba z dwoma kontraktami = ``None`` (karta do ręcznego przypisania).
    """

    words = set(_fold(re.sub(r"[^\w]+|_", " ", text)).split())
    if len(words) < 2 or not client_ids:
        return None
    rows = (
        await db.execute(
            select(Contract, Candidate.name, Candidate.lastname)
            .join(Candidate, Candidate.id == Contract.candidate_id)
            .where(Contract.client_id.in_(client_ids))
        )
    ).all()
    hits = []
    for contract, first, last in rows:
        given = _given(first)
        if (
            given
            and any(set(surname) <= words for surname in _surnames(last))
            and (given[0] in words or given[0][0] in words)
            and eligible(contract, today)
            and (settings.any_sender or settings.open_for(contract.id))
        ):
            hits.append(contract)
    return hits[0] if len(hits) == 1 else None


async def staff_client_ids(
    db: AsyncSession, addresses: Iterable[str]
) -> frozenset[int]:
    """Klienci z portfela Delivery Leadów piszących z tych adresów albo do nich.

    Koordynator po naszej stronie (DL klienta) przesyła pliki swoich ludzi, a jego
    odpowiedź z podpisanym plikiem idzie do niego (próba IX–X 2026, Orlen). Portfel
    to ``delivery_lead_client_assignments``, tak jak zakres DL w modułach Delivery.
    """

    from app.models.team_structure import DeliveryLeadClientAssignment

    emails = {normalize_email(address) for address in addresses} - {""}
    if not emails:
        return frozenset()
    rows = await db.scalars(
        select(DeliveryLeadClientAssignment.client_id)
        .join(User, User.id == DeliveryLeadClientAssignment.delivery_lead_user_id)
        .where(func.lower(func.btrim(User.email)).in_(emails), User.is_active.is_(True))
    )
    return frozenset(rows.all())


def _one_typo(name: str, word: str) -> bool:
    """Słowo różni się od imienia jedną literą (brak, nadmiar, zamiana, przestawienie),
    a pierwsza litera się zgadza: „tomsz” i „tomasz”."""

    if name == word or name[:1] != word[:1] or abs(len(name) - len(word)) > 1:
        return False
    if len(name) == len(word):
        diff = [i for i, (a, b) in enumerate(zip(name, word)) if a != b]
        return len(diff) == 1 or (
            len(diff) == 2
            and diff[1] == diff[0] + 1
            and name[diff[0]] == word[diff[1]]
            and name[diff[1]] == word[diff[0]]
        )
    short, long = sorted((name, word), key=len)
    return any(long[:i] + long[i + 1 :] == short for i in range(len(long)))


async def resolve_named_in_scope(
    db: AsyncSession, text: str, *, client_ids: frozenset[int], today: date
) -> Optional[Contract]:
    """Osoba z nazwy pliku wśród kontraktów tych klientów, także z literówką w imieniu.

    Koordynator wysłał „PROTOKÓŁ_ Tomsz Nazwisko_WRZESIEŃ 2026.pdf” (próba IX–X 2026,
    Orlen 432): pełne imię nie pasuje, więc ``resolve_named_in_text`` nikogo nie
    wskazuje. Każdy człon nazwiska stoi w tekście, imię stoi całe albo jedno słowo
    różni się od niego jedną literą (imię od 4 liter), a nazwisko nosi u tych klientów
    jedna osoba. Imię innej osoby z działającym kontraktem w tekście, dwie osoby albo
    osoba z dwoma kontraktami = ``None``.
    """

    words = _words(text)
    if len(words) < 2 or not client_ids:
        return None
    by_surname: list[Contract] = []
    hits: list[Contract] = []
    for contract, first, last in await _named_rows(
        db, today=today, client_ids=client_ids
    ):
        surnames = [s for s in _surnames(last) if not set(s) & _MONTH_WORDS]
        if not eligible(contract, today) or not any(set(s) <= words for s in surnames):
            continue
        by_surname.append(contract)
        given = _given(first)
        if given and (
            given[0] in words
            or (len(given[0]) >= 4 and any(_one_typo(given[0], w) for w in words))
        ):
            hits.append(contract)
    if len(hits) != 1 or len({c.candidate_id for c in by_surname}) != 1:
        return None
    own = await db.scalar(
        select(Candidate.name).where(Candidate.id == hits[0].candidate_id)
    )
    others = {
        name
        for _, first, _ in await _named_rows(db, today=today)
        for name in _given(first)
    } - set(_given(own))
    return None if words & others else hits[0]


async def names_someone_else(
    db: AsyncSession, text: str, contract: Contract, *, today: date
) -> bool:
    """Czy tekst (nazwa pliku) nazywa inną osobę niż osoba z ``contract``.

    Osoba z tematu przechodzi na pliki maila, ale nie na plik z imieniem albo
    nazwiskiem innej osoby z działającym kontraktem: taki plik czeka na człowieka
    (próba IX–X 2026, Orlen: plik osoby ze starym nazwiskiem trafił do kontraktu
    innej osoby z tego samego maila). Słowa z imienia i nazwisk osoby z ``contract``
    oraz nazwy miesięcy nie liczą się jako inna osoba.
    """

    words = _words(text) - _MONTH_WORDS
    person = (
        await db.execute(
            select(Candidate.name, Candidate.lastname).where(
                Candidate.id == contract.candidate_id
            )
        )
    ).first()
    own: set[str] = set()
    if person is not None:
        own = set(_given(person[0])).union(*_surnames(person[1]))
    words -= own
    if not words:
        return False
    for other, first, last in await _named_rows(db, today=today):
        if other.candidate_id == contract.candidate_id or not eligible(other, today):
            continue
        given = _given(first)
        if given and len(given[0]) >= 3 and given[0] in words:
            return True
        if any(set(surname) <= words for surname in _surnames(last)):
            return True
    return False


# Numer umowy wykonawczej w temacie albo nazwie pliku: „Umowa nr CeZ/177/2026”,
# „Protokół … do CeZ_177_2026-sig.pdf”. Bez spacji między członami: „za 10/2026”
# w tym samym temacie to okres, nie numer.
_AGREEMENT = re.compile(
    r"(?<![^\W\d_])([^\W\d_]{2,6})[/_-](\d{1,4})[/_-](20\d{2})(?!\d)"
)


def agreement_numbers(text: str) -> frozenset[str]:
    """Numery umów wykonawczych w tekście, w postaci ``cez/177/2026``."""

    return frozenset(
        f"{_fold(prefix)}/{int(number)}/{year}"
        for prefix, number, year in _AGREEMENT.findall(text or "")
    )


async def resolve_by_agreement(
    db: AsyncSession,
    text: str,
    *,
    today: date,
    client_ids: Optional[frozenset[int]] = None,
) -> Optional[Contract]:
    """Kontrakt z numeru umowy wykonawczej (zamówienia) w tekście.

    CeZ zawiera umowę wykonawczą na osobę i pisze jej numer w temacie protokołu
    (próba IX–X 2026, CeZ 668: w temacie inne imię niż w kartotece). Numer musi być
    numerem zamówienia w NEXUS-ie, a zamówienie mieć jedną osobę z działającym
    kontraktem. Dwa różne numery w tekście, zamówienie kilku osób albo osoba z dwoma
    kontraktami w nim = ``None``. ``client_ids`` zawęża do zamówień tych klientów.
    """

    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.client_order_group import ClientOrderGroup

    numbers = agreement_numbers(text)
    if len(numbers) != 1:
        return None
    query = (
        select(ClientOrderGroup.order_number, ClientOrder.contract_id)
        .join(ClientOrder, ClientOrder.order_group_id == ClientOrderGroup.id)
        .where(
            # Wyrażenie Postgresa: wąski zbiór kandydatów, dokładnie porównuje Python.
            ClientOrderGroup.order_number.op("~*")(
                r"^[[:alpha:]]{2,6}[/_-][0-9]{1,4}[/_-]20[0-9]{2}$"
            ),
            ClientOrder.contract_id.is_not(None),
            ClientOrder.status != ClientOrderStatus.cancelled,
        )
    )
    if client_ids is not None:
        query = query.where(ClientOrderGroup.client_id.in_(client_ids))
    ids = {
        contract_id
        for number, contract_id in (await db.execute(query)).all()
        if agreement_numbers(number) == numbers
    }
    if not ids:
        return None
    contracts = [
        contract
        for contract in (
            await db.scalars(select(Contract).where(Contract.id.in_(ids)))
        ).all()
        if eligible(contract, today)
    ]
    return contracts[0] if len(contracts) == 1 else None


def _fold(text: Optional[str]) -> str:
    raw = unicodedata.normalize(
        "NFKD", (text or "").replace("ł", "l").replace("Ł", "L")
    )
    return raw.encode("ascii", "ignore").decode().lower().replace("-", " ")


def _tokens(text: Optional[str]) -> set[str]:
    return {token for token in _fold(text).split() if token}


async def resolve_by_name(
    db: AsyncSession, full_name: str, *, settings: PortalSettings, today: date
) -> Optional[Contract]:
    """Kontrakt po imieniu i nazwisku z tematu maila od koordynatora (E6.3).

    Tylko dla maili, które z formatu tematu niosą osobę (KEŚU z Jiry): nadawcą
    jest koordynator, a nie konsultant. Ta sama osoba w dwóch kandydatach albo
    dwie osoby o tym nazwisku = ``None`` (karta do ręcznego przypisania).
    """

    wanted = _tokens(full_name)
    if len(wanted) < 2:
        return None
    # Bez filtra po całym nazwisku w SQL: kartoteka po zmianie nazwiska ma
    # „Nowe (Stare)”, a temat jedno z nazwisk.
    rows = await _named_rows(db, today=today)
    matches = [
        contract
        for contract, first, last in rows
        if wanted in _name_sets(first, last)
        and eligible(contract, today)
        # Osoba z KEŚU nic nie wysyła i nie musi mieć aktywnego panelu; w pilotażu
        # czytnik bierze jednak tylko osoby z pilotażu.
        and (settings.any_sender or settings.open_for(contract.id))
    ]
    if not matches or len({c.candidate_id for c in matches}) != 1:
        return None
    return matches[0]


async def load_consultant(
    db: AsyncSession,
    *,
    contract_id: int,
    email: str,
    settings: PortalSettings,
    today: date,
) -> Optional[Consultant]:
    """Świeży obraz osoby: kontrakt musi działać i nadal mieć ten sam adres."""

    contract = await db.get(Contract, contract_id)
    if (
        contract is None
        or normalize_email(contract.candidate_email) != email
        or not eligible(contract, today)
        or not settings.open_for(contract.id)
    ):
        return None
    siblings = await _contracts_for_email(db, email, settings=settings, today=today)
    own = [
        row.id
        for row in siblings
        if row.id == contract.id
        or (row.candidate_id is not None and row.candidate_id == contract.candidate_id)
    ]
    candidate = (
        await db.get(Candidate, contract.candidate_id)
        if contract.candidate_id
        else None
    )
    return Consultant(
        contract_id=contract.id,
        email=email,
        contract_ids=tuple(own),
        candidate_id=contract.candidate_id,
        first_name=(candidate.name.strip() or None)
        if candidate and candidate.name
        else None,
        phone=(contract.candidate_phone or "").strip() or None,
    )
