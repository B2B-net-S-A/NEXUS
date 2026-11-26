"""Osoba z dwoma działającymi kontraktami u dwóch klientów (próba IX–X 2026).

To nie błąd danych: konsultant pracuje naraz u dwóch klientów i fakturujemy obu
(Nordea i Bosch, Bank Pocztowy i VeloBank). Dwa kontrakty dalej znaczą „karta do
ręcznego przypisania”, chyba że mail sam wskazuje klienta. Raport wtedy idzie do
tego kontraktu, a faktura nie: żadną drogą nie przypina się sama (26.11.2026):

- skrzynka u klienta (``p.nazwisko@<domena klienta>``) → kontrakt u tego klienta,
  a domena wspólna dla grupy (``plus.pl``: Polkomtel i Cyfrowy Polsat) nic nie
  rozstrzyga;
- drugi kontrakt u klienta rozliczanego z raportu T4T → raport godzin z poczty idzie
  do pozostałego kontraktu. Faktura nie, bo bywa jedna na obu klientów (IX 2026:
  252 h = Nordea + MS Enter-Prise na jednej fakturze);
- zmiana klienta: poprzedni kontrakt działa jeszcze 60 dni po końcu, więc adres
  wskazuje oba. Raport z okresem w nazwie albo temacie idzie do jedynego kontraktu,
  który działa w tym miesiącu. Okres zgadnięty z daty maila i faktura nie rozstrzygają.

Dane fikcyjne.
"""

from __future__ import annotations

import secrets
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, update

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_settlement import ClientSettlementRuleSet
from app.models.contract import Contract, ContractStatus
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import UserRole
from app.services.client_settlements import time_reports
from app.services.consultant_portal import identity, mailbox
from app.services.consultant_portal.portal_settings import PortalSettings
from app.services.order_policies import known_clients
from tests.care_announcements_seed import (  # noqa: F401  (fixture)
    care_on,
    make_user,
    tag,
)
from tests.consultant_portal_seed import (  # noqa: F401  (fixture'y)
    make_person,
    portal_restored,
)
from tests.test_consultant_portal_internal import (  # noqa: F401  (fixture'y)
    FakeMailbox,
    _attachment,
    _documents,
    _message,
    _quiet_documents,
    _read,
    _storage,
    company_domain,
    internal,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("care_on")]

CLIENT_DOMAIN = "bank-testowy.example"
GROUP_DOMAIN = "grupa-testowa.example"
INTERNAL = PortalSettings(state="internal")
PDF = b"%PDF-1.4 fikcyjny dokument"


async def _person_at_two_clients(first: str, last: str):
    """Jedna osoba, dwa działające kontrakty u dwóch różnych klientów."""

    one = await make_person(activated=False)
    two = await make_person(activated=False, candidate_id=one.candidate_id)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Candidate)
            .where(Candidate.id == one.candidate_id)
            .values(name=first, lastname=last)
        )
        await db.commit()
    return one, two


async def _nip(client_id: int, nip: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(update(Client).where(Client.id == client_id).values(nip=nip))
        await db.commit()


def _registry(monkeypatch, domains: dict, nips: dict, shared: dict | None = None):
    monkeypatch.setattr(known_clients, "KNOWN_SENDER_DOMAINS", domains)
    monkeypatch.setattr(known_clients, "KNOWN_REGISTRY_IDS", nips)
    monkeypatch.setattr(
        known_clients, "SHARED_SENDER_DOMAINS", shared or {}, raising=False
    )


def _t4t(monkeypatch, *client_ids: int) -> None:
    async def enabled(db, month):
        return sorted(client_ids)

    monkeypatch.setattr(time_reports, "enabled_clients", enabled)


async def _resolve(address: str, today: date | None = None):
    async with AsyncSessionLocal() as db:
        return await identity.resolve_sender(
            db, address, settings=INTERNAL, today=today or business_today()
        )


def _nip_for_test() -> str:
    return str(secrets.randbelow(9 * 10**9) + 10**9)


# ── Skrzynka u klienta ───────────────────────────────────────────────────────


async def test_client_mailbox_picks_the_contract_at_that_client(monkeypatch) -> None:
    """BP 425 / VeloBank 469: KCP przychodzi z ``P.Nazwisko@pocztowy.pl``, TS
    z ``Imie.Nazwisko@velobank.pl``. Domena nadawcy wskazuje klienta."""

    last = f"Klimek{tag()}"
    bank, other = await _person_at_two_clients("Piotr", last)
    nip = _nip_for_test()
    await _nip(bank.client_id, nip)
    _registry(monkeypatch, {CLIENT_DOMAIN: "bank_testowy"}, {"bank_testowy": (nip,)})

    for local in (f"p.{last.lower()}", f"piotr.{last.lower()}"):
        found = await _resolve(f"{local}@{CLIENT_DOMAIN}")
        assert found is not None and found.id == bank.contract_id, local
    assert other.contract_id != bank.contract_id


async def test_client_mailbox_without_contract_at_that_client(monkeypatch) -> None:
    """Imię i nazwisko konsultanta w skrzynce klienta, u którego nie pracuje:
    to raczej pracownik klienta o tym samym nazwisku, więc nikt."""

    last = f"Obcy{tag()}"
    await _person_at_two_clients("Jan", last)
    nip = _nip_for_test()
    elsewhere = await make_person(activated=False)
    await _nip(elsewhere.client_id, nip)
    _registry(monkeypatch, {CLIENT_DOMAIN: "bank_testowy"}, {"bank_testowy": (nip,)})

    assert await _resolve(f"jan.{last.lower()}@{CLIENT_DOMAIN}") is None


async def test_shared_group_domain_decides_nothing(monkeypatch) -> None:
    """Polkomtel 471 / Cyfrowy Polsat 633: obie spółki piszą z ``plus.pl``, a wpis
    w rejestrze domen wskazuje tylko Polkomtel. Dla CP 634 X wybrałby źle."""

    last = f"Wysocka{tag()}"
    one, two = await _person_at_two_clients("Ewa", last)
    nip_one, nip_two = _nip_for_test(), _nip_for_test()
    await _nip(one.client_id, nip_one)
    await _nip(two.client_id, nip_two)
    _registry(
        monkeypatch,
        {GROUP_DOMAIN: "spolka_a"},
        {"spolka_a": (nip_one,), "spolka_b": (nip_two,)},
        shared={GROUP_DOMAIN: ("spolka_a", "spolka_b")},
    )

    assert await _resolve(f"ewa.{last.lower()}@{GROUP_DOMAIN}") is None


async def test_client_mailbox_of_staff_never_matches(monkeypatch) -> None:
    from app.models.user import User, UserRole
    from tests.care_announcements_seed import make_user

    last = f"Kadra{tag()}"
    bank, _ = await _person_at_two_clients("Ola", last)
    nip = _nip_for_test()
    await _nip(bank.client_id, nip)
    _registry(monkeypatch, {CLIENT_DOMAIN: "bank_testowy"}, {"bank_testowy": (nip,)})
    address = f"ola.{last.lower()}@{CLIENT_DOMAIN}"
    staff = await make_user(UserRole.finance)
    async with AsyncSessionLocal() as db:
        await db.execute(update(User).where(User.id == staff.id).values(email=address))
        await db.commit()

    assert await _resolve(address) is None


# ── Drugi kontrakt u klienta z raportem T4T ──────────────────────────────────


async def _company_mail(monkeypatch, files: list[dict]):
    """Oba kontrakty pod jednym adresem (z kontraktu): nadawca wskazuje osobę."""

    t4t_side, other = await _person_at_two_clients("Dorota", f"Hanecka{tag()}")
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Contract)
            .where(Contract.id == other.contract_id)
            .values(candidate_email=t4t_side.email)
        )
        await db.commit()
    _t4t(monkeypatch, t4t_side.client_id)
    reader = FakeMailbox([_message("m1", t4t_side.email)], {"m1": files})
    return t4t_side, other, reader


@pytest.mark.usefixtures("internal")
async def test_report_goes_to_the_contract_outside_t4t(monkeypatch) -> None:
    """Nordea 292 / Bosch 623: Nordea liczy godziny z T4T, więc timesheet z poczty
    jest Boscha („W załączniku Timesheet (Bosch)”, 30.09 i 31.10.2026)."""

    _, bosch, reader = await _company_mail(
        monkeypatch, [_attachment("TS_September2026.pdf", PDF + b" raport")]
    )

    assert (await _read(reader))["created"] == 1
    assert [row.contract_id for row in await _documents()] == [bosch.contract_id]


@pytest.mark.usefixtures("internal")
async def test_invoice_of_two_clients_still_waits(monkeypatch) -> None:
    """Faktura bywa jedna na obu klientów (252 h = Nordea + MS Enter-Prise), więc
    z poczty nie trafia do kontraktu spoza T4T. Raport z tego samego maila tak."""

    _, other, reader = await _company_mail(
        monkeypatch,
        [
            _attachment("Faktura_09_2026.pdf", PDF),
            _attachment("Time Sheet 09.2026.pdf", PDF + b" raport"),
        ],
    )

    assert (await _read(reader))["created"] == 2
    by_kind = {row.kind: row.contract_id for row in await _documents()}
    assert by_kind == {"invoice": None, "report": other.contract_id}


@pytest.mark.usefixtures("internal")
async def test_without_t4t_two_clients_still_wait(monkeypatch) -> None:
    _, _, reader = await _company_mail(
        monkeypatch, [_attachment("TS_September2026.pdf", PDF + b" raport")]
    )
    _t4t(monkeypatch)

    assert (await _read(reader))["created"] == 1
    assert [row.contract_id for row in await _documents()] == [None]


@pytest.mark.usefixtures("internal")
async def test_two_contracts_outside_t4t_still_wait(monkeypatch) -> None:
    """Trzeci kontrakt poza T4T: dwa kandydaty na raport, więc karta."""

    t4t_side, other, reader = await _company_mail(
        monkeypatch, [_attachment("TS_September2026.pdf", PDF + b" raport")]
    )
    third = await make_person(activated=False, candidate_id=t4t_side.candidate_id)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Contract)
            .where(Contract.id == third.contract_id)
            .values(candidate_email=t4t_side.email)
        )
        await db.commit()
    assert third.client_id not in (t4t_side.client_id, other.client_id)

    assert (await _read(reader))["created"] == 1
    assert [row.contract_id for row in await _documents()] == [None]


# ── Zmiana klienta: okres kontraktu a miesiąc pliku ──────────────────────────

COMPANY_DOMAIN = "firma.example.com"  # fixture ``company_domain``


async def _changed_client(*, old_end: date, new_start: date | None = None):
    """Osoba przeszła do drugiego klienta i pisze ze skrzynki firmowej.

    Poprzedni kontrakt jest zakończony ``old_end``, ale działa jeszcze 60 dni, więc
    adres firmowy wskazuje oba kontrakty (jak 418 i 467 w próbie IX–X 2026)."""

    last = f"Zmienna{tag()}"
    old, new = await _person_at_two_clients("Marta", last)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Contract)
            .where(Contract.id == old.contract_id)
            .values(status=ContractStatus.ended, end_date=old_end)
        )
        if new_start is not None:
            await db.execute(
                update(Contract)
                .where(Contract.id == new.contract_id)
                .values(start_date=new_start)
            )
        await db.commit()
    return old, new, f"marta.{last.lower()}@{COMPANY_DOMAIN}"


def _mail(sender: str, *files: dict) -> FakeMailbox:
    return FakeMailbox([_message("m1", sender)], {"m1": list(files)})


def _ts(day: date) -> dict:
    return _attachment(
        f"TS_{day.month:02d}_{day.year}.pdf", PDF + f" raport {day:%Y-%m}".encode()
    )


@pytest.mark.usefixtures("internal", "company_domain")
async def test_report_after_old_contract_ended_goes_to_new_contract() -> None:
    """VeloBank 466 i 467: Time Sheet za IX z adresu firmy czekał na człowieka, bo
    adres wskazywał też kontrakt w Banku Pocztowym zakończony 31.08. Raport za
    miesiąc po końcu kontraktu nie jest tego kontraktu."""

    today = business_today()
    _, new, address = await _changed_client(
        old_end=today.replace(day=1) - timedelta(days=1)
    )

    assert (await _read(_mail(address, _ts(today))))["created"] == 1
    assert [row.contract_id for row in await _documents()] == [new.contract_id]


@pytest.mark.usefixtures("internal", "company_domain")
async def test_last_report_of_old_contract_goes_to_old_contract() -> None:
    """Ostatni raport przychodzi po końcu współpracy (po to kontrakt działa jeszcze
    60 dni): raport za miesiąc przed startem nowego kontraktu jest poprzedniego."""

    month_start = business_today().replace(day=1)
    before = month_start - timedelta(days=1)
    old, _, address = await _changed_client(old_end=before, new_start=month_start)

    assert (await _read(_mail(address, _ts(before))))["created"] == 1
    assert [row.contract_id for row in await _documents()] == [old.contract_id]


@pytest.mark.usefixtures("internal", "company_domain")
async def test_report_for_month_of_both_contracts_still_waits() -> None:
    """Oba kontrakty działają w miesiącu pliku (Bank Pocztowy VII–VIII obok
    VeloBanku): plik czeka na człowieka jak dotąd."""

    today = business_today()
    _, _, address = await _changed_client(old_end=today.replace(day=1))

    assert (await _read(_mail(address, _ts(today))))["created"] == 1
    assert [row.contract_id for row in await _documents()] == [None]


@pytest.mark.usefixtures("internal", "company_domain")
async def test_guessed_period_decides_nothing() -> None:
    """Bez okresu w nazwie i temacie miesiąc zgaduje data maila, a plik może być
    spóźnionym raportem poprzedniego kontraktu: czeka na człowieka."""

    year, month, guessed = mailbox.period_for(
        "Raport", "TS.pdf", datetime.now(timezone.utc).date()
    )
    assert guessed
    _, _, address = await _changed_client(
        old_end=date(year, month, 1) - timedelta(days=1)
    )
    reader = _mail(address, _attachment("TS.pdf", PDF + b" raport"))

    assert (await _read(reader))["created"] == 1
    assert [row.contract_id for row in await _documents()] == [None]


@pytest.mark.usefixtures("internal", "company_domain")
async def test_invoice_after_client_change_still_waits() -> None:
    """Numer faktury niesie miesiąc wystawienia („FV3_10_2026” w mailu z Time Sheet
    za IX), a ostatnia faktura za poprzedni kontrakt przychodzi po jego końcu:
    faktura czeka, raport z tego samego maila idzie do nowego kontraktu."""

    today = business_today()
    _, new, address = await _changed_client(
        old_end=today.replace(day=1) - timedelta(days=1)
    )
    reader = _mail(
        address,
        _attachment(f"Faktura_FV3_{today.month:02d}_{today.year}.pdf", PDF),
        _ts(today),
    )

    assert (await _read(reader))["created"] == 2
    by_kind = {row.kind: row.contract_id for row in await _documents()}
    assert by_kind == {"invoice": None, "report": new.contract_id}


@pytest.mark.usefixtures("internal")
async def test_two_people_under_one_address_still_wait() -> None:
    """Adres z kontraktów dwóch różnych osób (wspólna skrzynka, błąd w danych) nie
    wskazuje nikogo, choć kontrakt jednej z nich skończył się przed miesiącem pliku."""

    today = business_today()
    gone = await make_person(activated=False)
    other = await make_person(activated=False)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Contract)
            .where(Contract.id == gone.contract_id)
            .values(
                status=ContractStatus.ended,
                end_date=today.replace(day=1) - timedelta(days=1),
            )
        )
        await db.execute(
            update(Contract)
            .where(Contract.id == other.contract_id)
            .values(candidate_email=gone.email)
        )
        await db.commit()

    assert (await _read(_mail(gone.email, _ts(today))))["created"] == 1
    assert [row.contract_id for row in await _documents()] == [None]


# ── Faktura osoby u dwóch klientów nie przypina się sama (od 26.11.2026) ─────


async def _bank_mailbox_person(monkeypatch):
    """Osoba u dwóch klientów; pierwszy (bank) pisze z ``CLIENT_DOMAIN``."""

    last = f"Skrzynska{tag()}"
    bank, other = await _person_at_two_clients("Olga", last)
    nip = _nip_for_test()
    await _nip(bank.client_id, nip)
    _registry(monkeypatch, {CLIENT_DOMAIN: "bank_testowy"}, {"bank_testowy": (nip,)})
    return bank, other, f"olga.{last.lower()}@{CLIENT_DOMAIN}", last


def _invoice_and_report(who: str = "") -> tuple[dict, dict]:
    suffix = f" {who}" if who else ""
    return (
        _attachment(f"Faktura{suffix} 09_2026.pdf", PDF),
        _attachment(f"Time Sheet{suffix} 09.2026.pdf", PDF + b" raport"),
    )


async def _by_kind() -> dict[str, int | None]:
    return {row.kind: row.contract_id for row in await _documents()}


@pytest.mark.usefixtures("internal")
async def test_invoice_from_client_mailbox_of_two_clients_waits(monkeypatch) -> None:
    """Skrzynka w jednym banku wskazuje jego kontrakt, ale faktura bywa jedna na oba:
    czeka na człowieka, a raport z tego samego maila idzie do banku jak dotąd."""

    bank, _, address, _ = await _bank_mailbox_person(monkeypatch)

    assert (await _read(_mail(address, *_invoice_and_report())))["created"] == 2
    assert await _by_kind() == {"invoice": None, "report": bank.contract_id}


@pytest.mark.usefixtures("internal")
async def test_invoice_from_address_of_one_contract_waits() -> None:
    """Adres prywatny wpisany tylko w jednym kontrakcie wskazuje ten kontrakt, ale
    nie fakturę (na kopii z 26.11.2026 tak miała jedna z siedmiu takich osób)."""

    one, _ = await _person_at_two_clients("Olga", f"Prywatna{tag()}")

    assert (await _read(_mail(one.email, *_invoice_and_report())))["created"] == 2
    assert await _by_kind() == {"invoice": None, "report": one.contract_id}


@pytest.mark.usefixtures("internal")
async def test_invoice_forwarded_by_client_waits(monkeypatch) -> None:
    """Pracownik klienta przekazuje fakturę z nazwiskiem: raport trafia do kontraktu
    u tego klienta, faktura czeka."""

    bank, _, _, last = await _bank_mailbox_person(monkeypatch)
    reader = _mail(f"kierownik@{CLIENT_DOMAIN}", *_invoice_and_report(f"Olga {last}"))

    assert (await _read(reader))["created"] == 2
    assert await _by_kind() == {"invoice": None, "report": bank.contract_id}


@pytest.mark.usefixtures("internal")
async def test_invoice_from_client_mailbox_of_one_client_goes_to_it(
    monkeypatch,
) -> None:
    """Drugi kontrakt skończony dawniej niż 60 dni temu się nie liczy: jak dotąd."""

    bank, other, address, _ = await _bank_mailbox_person(monkeypatch)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Contract)
            .where(Contract.id == other.contract_id)
            .values(
                status=ContractStatus.ended,
                end_date=business_today() - timedelta(days=90),
            )
        )
        await db.commit()

    assert (await _read(_mail(address, _invoice_and_report()[0])))["created"] == 1
    assert await _by_kind() == {"invoice": bank.contract_id}


class _Accepted(FakeMailbox):
    """Mail z cytowaną akceptacją kierownika z banku; ``readable`` = MIME dostępny."""

    def __init__(self, sender: str, files: list[dict], *, subject: str) -> None:
        message = _message("m1", sender)
        message["subject"] = subject
        super().__init__([message], {"m1": files})
        mail = EmailMessage()
        mail["From"] = sender
        mail["Subject"] = subject
        mail.set_content(
            "W zalaczniku.\n\n"
            f"From: Kierownik <kierownik@{CLIENT_DOMAIN}>\n"
            "Sent: Monday, October 5, 2026 11:02 AM\n"
            "Subject: ODP: akceptacja\n\nPotwierdzam\n"
        )
        self.raw = mail.as_bytes()
        self.readable = True

    async def mime(self, message_id):
        return self.raw if self.readable else None


@pytest_asyncio.fixture
async def accepts_by_mail():
    """Reguła „Excel z mailem” klienta: czytnik zapisuje treść maila przy kontrakcie."""

    clients: list[int] = []

    async def enable(client_id: int) -> None:
        rules = {
            "proof.excel_with_mail": {
                "level": "warn",
                "params": {"domain": CLIENT_DOMAIN},
            }
        }
        async with AsyncSessionLocal() as db:
            db.add(
                ClientSettlementRuleSet(
                    client_id=client_id, effective_from="2026-01", rules=rules
                )
            )
            await db.commit()
        clients.append(client_id)

    yield enable
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(ClientSettlementRuleSet).where(
                ClientSettlementRuleSet.client_id.in_(clients)
            )
        )
        await db.commit()


async def _owners() -> dict[str, int | None]:
    return {row.file_name: row.contract_id for row in await _documents()}


@pytest.mark.usefixtures("internal")
async def test_mail_body_still_goes_to_the_client_mailbox_contract(
    monkeypatch, accepts_by_mail
) -> None:
    """Faktura czeka, ale mail z akceptacją kierownika to dalej dowód godzin, także
    gdy treść udaje się pobrać dopiero przy ponownym odczycie tej samej faktury."""

    bank, _, address, _ = await _bank_mailbox_person(monkeypatch)
    await accepts_by_mail(bank.client_id)
    subject = f"Faktura {tag()}"
    reader = _Accepted(address, [_invoice_and_report()[0]], subject=subject)
    reader.readable = False

    assert (await _read(reader))["created"] == 1
    reader.readable = True
    assert (await _read(reader))["created"] == 1

    assert await _owners() == {
        "Faktura 09_2026.pdf": None,
        f"{subject}.eml": bank.contract_id,
    }


@pytest.mark.usefixtures("internal")
async def test_mail_body_goes_to_the_client_that_forwarded_the_invoice(
    monkeypatch, accepts_by_mail
) -> None:
    bank, _, _, last = await _bank_mailbox_person(monkeypatch)
    await accepts_by_mail(bank.client_id)
    subject = f"Faktura {tag()}"
    invoice = _invoice_and_report(f"Olga {last}")[0]
    reader = _Accepted(f"kierownik@{CLIENT_DOMAIN}", [invoice], subject=subject)

    assert (await _read(reader))["created"] == 2

    assert await _owners() == {
        invoice["name"]: None,
        f"{subject}.eml": bank.contract_id,
    }


async def _delivery_lead(client_id: int) -> str:
    """Delivery Lead z portfelem z jednym klientem; zwraca jego adres."""

    lead = await make_user(UserRole.delivery_lead)
    async with AsyncSessionLocal() as db:
        db.add(
            DeliveryLeadClientAssignment(
                delivery_lead_user_id=lead.id, client_id=client_id, is_head=True
            )
        )
        await db.commit()
    return lead.email


def _to_settlements_and(sender: str, lead: str, *files: dict) -> FakeMailbox:
    message = _message("m1", sender)
    message["toRecipients"] = [
        {"emailAddress": {"address": address}}
        for address in (f"rozliczenia@{COMPANY_DOMAIN}", lead)
    ]
    return FakeMailbox([message], {"m1": list(files)})


@pytest.mark.usefixtures("internal", "company_domain")
@pytest.mark.parametrize("local", ["olga.{last}", "koordynator"])
async def test_invoice_named_in_dl_portfolio_of_two_clients_waits(local: str) -> None:
    """Delivery Lead w adresatach ma w portfelu jeden z banków, więc nazwisko z nazwy
    pliku wskazywało jego kontrakt: faktura czeka, raport idzie do banku jak dotąd.
    Tak samo, gdy pisze sama osoba ze skrzynki firmowej albo koordynator."""

    last = f"Portfelowa{tag()}"
    bank, _ = await _person_at_two_clients("Olga", last)
    lead = await _delivery_lead(bank.client_id)
    sender = f"{local.format(last=last.lower())}@{COMPANY_DOMAIN}"
    reader = _to_settlements_and(sender, lead, *_invoice_and_report(f"Olga {last}"))

    assert (await _read(reader))["created"] == 2
    assert await _by_kind() == {"invoice": None, "report": bank.contract_id}


@pytest.mark.usefixtures("internal", "company_domain")
async def test_invoice_named_in_dl_portfolio_of_one_client_goes_to_it() -> None:
    """Literówka w imieniu, jeden kontrakt: portfel DL-a wskazuje go jak dotąd."""

    last = f"Jedyny{tag()}"
    person = await make_person(activated=False)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Candidate)
            .where(Candidate.id == person.candidate_id)
            .values(name="Tomasz", lastname=last)
        )
        await db.commit()
    lead = await _delivery_lead(person.client_id)
    invoice = _attachment(f"Faktura Tomsz {last} 09_2026.pdf", PDF)
    reader = _to_settlements_and(f"koordynator@{COMPANY_DOMAIN}", lead, invoice)

    assert (await _read(reader))["created"] == 1
    assert await _by_kind() == {"invoice": person.contract_id}


# ── „Przypisz”: kontrakty nadawcy jako podpowiedź (od 26.11.2026) ────────────

STAFF = "/api/back-office/portal"


async def _card_rows(app_client) -> list[dict]:
    """Wiersze dokumentów z kart Back office, oczami Finansów."""

    from app.models.back_office import BoCard
    from app.services.back_office import sync
    from tests.care_announcements_seed import headers

    async with AsyncSessionLocal() as db:
        result = await sync.sync_kinds(db, ["document"], today=business_today())
        await db.commit()
        assert result["failed"] == []
        cards = (
            await db.scalars(
                select(BoCard)
                .where(BoCard.source_kind == "document", BoCard.state != "done")
                .order_by(BoCard.id)
            )
        ).all()
    finance = await make_user(UserRole.finance)
    rows: list[dict] = []
    for card in cards:
        listed = await app_client.get(
            f"{STAFF}/documents/by-card/{card.id}", headers=headers(finance)
        )
        assert listed.status_code == 200, listed.text
        rows += listed.json()["items"]
    return rows


@pytest.mark.usefixtures("internal")
async def test_held_invoice_suggests_both_contracts_of_the_sender(
    app_client, monkeypatch
) -> None:
    """Faktura ze skrzynki w banku czeka bez kontraktu, a karta podpowiada osobę
    i oba jej kontrakty: klient, numer, okres. Bez kwot."""

    bank, other, address, last = await _bank_mailbox_person(monkeypatch)
    await _read(_mail(address, *_invoice_and_report()))

    rows = {row["kind"]: row for row in await _card_rows(app_client)}

    hint = rows["invoice"]["sender_person"]
    assert hint["name"] == f"Olga {last}"
    assert {c["id"] for c in hint["contracts"]} == {
        bank.contract_id,
        other.contract_id,
    }
    assert all(
        set(c) == {"id", "client", "start_date", "end_date"} for c in hint["contracts"]
    )
    assert all(c["client"] for c in hint["contracts"])
    # Raport ma kontrakt: nic do podpowiadania.
    assert rows["report"]["sender_person"] is None


@pytest.mark.usefixtures("internal", "company_domain")
async def test_unknown_sender_gets_no_suggestion(app_client) -> None:
    reader = _mail(f"koordynator@{COMPANY_DOMAIN}", _invoice_and_report()[0])
    await _read(reader)

    rows = await _card_rows(app_client)

    assert [row["sender_person"] for row in rows] == [None]


async def _held_invoice(sender: str):
    """Faktura bez kontraktu od tego nadawcy, zapisana jak przez czytnik."""

    from app.services.consultant_portal import documents

    today = business_today()
    async with AsyncSessionLocal() as db:
        stored = await documents.store(
            db,
            contract_id=None,
            kind="invoice",
            year=today.year,
            month=today.month,
            content=PDF + tag().encode(),
            file_name="Faktura.pdf",
            channel="mailbox",
            now=datetime.now(timezone.utc),
            graph_message_id=f"m-{tag()}",
            sender_email=sender,
        )
        await db.commit()
        return await documents.sender_contracts(db, stored.document, today=today)


@pytest.mark.usefixtures("internal")
async def test_suggestion_skips_contract_ended_long_ago() -> None:
    """Kontrakt zakończony dawniej niż 60 dni temu nie jest podpowiedzią."""

    one, other = await _person_at_two_clients("Olga", f"Dawna{tag()}")
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Contract)
            .where(Contract.id == other.contract_id)
            .values(
                status=ContractStatus.ended,
                end_date=business_today() - timedelta(days=90),
            )
        )
        await db.commit()

    hint = await _held_invoice(one.email)

    assert [c["id"] for c in hint["contracts"]] == [one.contract_id]


@pytest.mark.usefixtures("internal")
async def test_two_people_under_one_address_get_no_suggestion() -> None:
    gone = await make_person(activated=False)
    other = await make_person(activated=False)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Contract)
            .where(Contract.id == other.contract_id)
            .values(candidate_email=gone.email)
        )
        await db.commit()

    assert await _held_invoice(gone.email) is None
