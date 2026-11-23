"""Kim jest konsultant portalu: wyłącznie adres z kontraktu.

Konta nie ma, więc tożsamością jest ``contracts.candidate_email``. Adres pasujący
do dwóch różnych osób (wspólna skrzynka, błąd w danych) nie otwiera niczego: nie
da się powiedzieć, czyje sprawy pokazać. Kontrakt zakończony działa jeszcze
``ENDED_GRACE_DAYS``, bo ostatni raport i faktura przychodzą po końcu współpracy.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contact import Contact
from app.models.contract import Contract, ContractStatus
from app.models.user import User
from app.services.consultant_portal.portal_settings import PortalSettings

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
        rows = await _by_company_address(db, address, today=today)
    return rows


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
    ``jan_kowalski``, ``jankowalski``; nazwisko dwuczłonowe także po członie."""

    given = _fold(first).split()[:1]
    parts = _fold(last).split()
    if not given or not parts:
        return set()
    name = given[0]
    forms: set[str] = set()
    for surname in {"".join(parts), "-".join(parts), *parts}:
        for sep in (".", "_", "-", ""):
            forms.add(name + sep + surname)
        forms.add(name[0] + "." + surname)
        forms.add(name[0] + surname)
    return forms


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
    samym nazwisku, więc nikt.
    """

    local, _, domain = address.partition("@")
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
    """

    from app.services.order_policies import known_clients

    keys = known_clients.SHARED_SENDER_DOMAINS.get(domain) or tuple(
        key for key in (known_clients.KNOWN_SENDER_DOMAINS.get(domain),) if key
    )
    if not keys:
        return None
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


async def resolve_named_in_text(
    db: AsyncSession, text: str, *, today: date
) -> Optional[Contract]:
    """Kontrakt osoby, której imię i nazwisko stoi w temacie albo nazwie pliku.

    Ostatnia deska, gdy nadawca z adresu firmy nikogo nie wskazuje: koordynator
    przesyła cudze pliki („TimeSheet … Nazwisko Imię.xls”). Czytnik pyta tylko dla
    nadawców z domeny firmy, bo temat może napisać każdy. Kolejność słów dowolna, imię
    i każdy człon nazwiska muszą stać w tekście. Dwie osoby w tekście albo jedna
    z dwoma działającymi kontraktami = ``None`` (karta do ręcznego przypisania).
    """

    words = _words(text)
    if len(words) < 2:
        return None
    rows = await _named_rows(db, today=today)
    hits = []
    for contract, first, last in rows:
        person = _fold(first).split()[:1] + _fold(last).split()
        if len(person) >= 2 and set(person) <= words and eligible(contract, today):
            hits.append(contract)
    if len(hits) != 1:
        return None
    return hits[0]


def _words(text: str) -> set[str]:
    return set(_fold(re.sub(r"[^\w]+|_", " ", text)).split())


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
    )
    if client_ids is not None:
        query = query.where(Contract.client_id.in_(client_ids))
    return list((await db.execute(query)).all())


async def client_ids_for_sender(db: AsyncSession, address: str) -> frozenset[int]:
    """Klienci, do których należy domena nadawcy: adres w kontaktach klienta.

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
    return frozenset(rows.all())


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
        given = _fold(first).split()[:1]
        surname = _fold(last).split()
        if not surname or not eligible(contract, today):
            continue
        glued = {"".join(given + surname), "".join(surname + given)}
        if given and (set(given + surname) <= words or glued & words):
            full.append((contract, tuple(surname)))
        elif not set(surname) & _MONTH_WORDS and (
            set(surname) <= words or "".join(surname) in words
        ):
            by_surname.append((contract, tuple(surname)))
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
        surname, given = _fold(last).split(), _fold(first).split()[:1]
        if (
            surname
            and given
            and set(surname) <= words
            and (given[0] in words or given[0][0] in words)
            and eligible(contract, today)
            and (settings.any_sender or settings.open_for(contract.id))
        ):
            hits.append(contract)
    return hits[0] if len(hits) == 1 else None


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
    lowered = [part.lower() for part in full_name.replace("-", " ").split() if part]
    rows = (
        await db.execute(
            select(Contract, Candidate.name, Candidate.lastname)
            .join(Candidate, Candidate.id == Contract.candidate_id)
            .where(func.lower(Candidate.lastname).in_(lowered))
            .order_by(Contract.start_date.desc().nulls_last(), Contract.id.desc())
        )
    ).all()
    matches = [
        contract
        for contract, first, last in rows
        if _tokens(f"{first or ''} {last or ''}") == wanted
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
