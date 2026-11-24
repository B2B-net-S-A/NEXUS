"""Czyj jest plik z poczty rozliczeń: przypadki z próby IX–X 2026 (kopia produkcji, 24.11).

* plik osoby nierozpoznanej nie dziedziczy kontraktu innej osoby z tego samego maila;
* kartoteka po zmianie nazwiska („Nowa (Stara)”) pasuje do obu nazwisk;
* literówka w imieniu wśród klientów z portfela DL-a z wątku;
* skrzynka konsultanta u klienta w poddomenie z przedrostkiem ``external.``;
* numer umowy wykonawczej w temacie albo nazwie pliku;
* treść maila z Time Sheet, gdy w wątku pisze klient (``proof.excel_with_mail``);
* akceptacja przekazana ze skrzynki samego konsultanta, bez nazwiska w temacie.

Skrzynka to atrapa, osoby, adresy i numery fikcyjne.
"""

from __future__ import annotations

import base64
import random
import string
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from email.message import EmailMessage

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, update

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup
from app.models.client_settlement import ClientSettlementRuleSet
from app.models.consultant_portal import CpDocument, CpMailboxState
from app.models.contract import Contract
from app.models.user import User, UserRole
from app.services import storage_service
from app.services.consultant_portal import identity, mailbox
from app.services.consultant_portal.portal_settings import PortalSettings
from app.services.order_policies import known_clients
from tests.care_announcements_seed import (  # noqa: F401  (fixture'y)
    care_on,
    make_client,
    make_consultant,
    make_user,
    tag,
)
from tests.consultant_portal_seed import (  # noqa: F401  (fixture'y)
    make_person,
    portal_restored,
    set_portal,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("care_on")]

COMPANY = "firma.example.com"
INTERNAL = PortalSettings(state="internal")
PDF = b"%PDF-1.4 fikcyjny protokol"


@pytest_asyncio.fixture(autouse=True)
async def _quiet_documents():
    async with AsyncSessionLocal() as db:
        await db.execute(delete(CpDocument))
        state = await db.get(CpMailboxState, 1)
        if state is not None:
            await db.delete(state)
        await db.commit()
    yield


@pytest.fixture(autouse=True)
def _storage(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)


@pytest.fixture(autouse=True)
def _company_domain(monkeypatch):
    monkeypatch.setattr(identity, "_company_domains", lambda: frozenset({COMPANY}))


@pytest_asyncio.fixture(autouse=True)
async def _internal(portal_restored):  # noqa: F811  (fixture z seeda)
    await set_portal("internal")
    yield


class Box:
    def __init__(self, messages, files, raw=None) -> None:
        self.messages = messages
        self.files = files
        self.raw = raw or {}

    async def list_messages(self, since):
        return self.messages

    async def attachments(self, message_id):
        return self.files.get(message_id, [])

    async def mime(self, message_id):
        return self.raw.get(message_id)


def _message(
    message_id: str,
    sender: str,
    subject: str,
    *,
    to: tuple[str, ...] = (),
    files: bool = True,
) -> dict:
    return {
        "id": message_id,
        "subject": subject,
        "hasAttachments": files,
        "from": {"emailAddress": {"address": sender}},
        "toRecipients": [{"emailAddress": {"address": a}} for a in to],
        "receivedDateTime": datetime.now(timezone.utc).isoformat(),
    }


def _file(name: str, data: bytes = PDF) -> dict:
    return {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": name,
        "isInline": False,
        "contentBytes": base64.b64encode(data).decode(),
    }


def _eml(sender: str, subject: str, text: str) -> bytes:
    message = EmailMessage()
    message["From"] = sender
    message["Subject"] = subject
    message.set_content(text)
    return message.as_bytes()


async def _read(box: Box) -> dict:
    async with AsyncSessionLocal() as db:
        result = await mailbox.run_once(db, mailbox=box)
        await db.commit()
    return result


async def _owners() -> dict[str, int | None]:
    async with AsyncSessionLocal() as db:
        rows = (await db.scalars(select(CpDocument).order_by(CpDocument.id))).all()
    return {row.file_name: row.contract_id for row in rows}


async def _rename(candidate_id: int, first: str, last: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Candidate)
            .where(Candidate.id == candidate_id)
            .values(name=first, lastname=last)
        )
        await db.commit()


async def _named(first: str, last: str):
    person = await make_person(activated=False)
    await _rename(person.candidate_id, first, last)
    return person


async def _full_name(person) -> str:
    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, person.candidate_id)
    return f"{candidate.name} {candidate.lastname}"


def _letters() -> str:
    """Nazwisko bez cyfr: ``tag()`` ma cyfry, a nazwa pliku dzieli słowa na literach."""

    return "".join(random.choices(string.ascii_lowercase, k=8))


# ── 1. Plik osoby nierozpoznanej nie dziedziczy osoby z maila ──────────────────


async def test_plik_osoby_nierozpoznanej_nie_dziedziczy_kontraktu_z_maila() -> None:
    """Koordynator wysyła protokoły dwóch osób; druga ma w nazwie pliku nazwisko,
    którego nie ma w kartotece (stare nazwisko). Jej plik czeka na człowieka."""

    first = await make_person(activated=False)
    other = await _named("Kornelia", f"Nowa{_letters()}")
    old = f"Stara{_letters()}"
    message = _message("m1", f"koordynator@{COMPANY}", f"TS_{old}_{tag()}")
    mine = f"PROTOKÓŁ_ {await _full_name(first)}_WRZESIEŃ 2026.pdf"
    hers = f"PROTOKÓŁ_ Kornelia {old}_WRZESIEŃ 2026.pdf"
    await _read(Box([message], {"m1": [_file(mine), _file(hers, b"%PDF-1.4 drugi")]}))
    assert await _owners() == {mine: first.contract_id, hers: None}
    assert other.contract_id not in (await _owners()).values()


async def test_plik_z_imieniem_innej_osoby_nie_dziedziczy_osoby_z_tematu() -> None:
    first = await make_person(activated=False)
    await _named("Kornelia", f"Nowa{_letters()}")
    message = _message("m1", f"koordynator@{COMPANY}", f"TS {await _full_name(first)}")
    files = [
        _file("TimeSheet.pdf"),
        _file(f"TimeSheet Kornelia {_letters()}.pdf", b"%PDF-1.4 drugi"),
    ]
    await _read(Box([message], {"m1": files}))
    owners = await _owners()
    assert owners["TimeSheet.pdf"] == first.contract_id
    assert [cid for name, cid in owners.items() if "Kornelia" in name] == [None]


# ── 2. Zmiana nazwiska: „Nowa (Stara)” ────────────────────────────────────────


async def test_kartoteka_po_zmianie_nazwiska_pasuje_do_obu_nazwisk() -> None:
    old, new = f"Stara{_letters()}", f"Nowa{_letters()}"
    person = await _named("Kornelia", f"{new} ({old})")
    today = business_today()
    async with AsyncSessionLocal() as db:
        for text in (
            f"PROTOKÓŁ_ Kornelia {old}_WRZESIEŃ 2026.pdf",
            f"PROTOKÓŁ_ Kornelia {new}_PAŹDZIERNIK 2026.pdf",
            f"PROTOKÓŁ_ Kornelia {new} ({old})_WRZESIEŃ 2026.pdf",
        ):
            found = await identity.resolve_named_in_text(db, text, today=today)
            assert found is not None and found.id == person.contract_id, text
        for local in (f"kornelia.{old.lower()}", f"kornelia.{new.lower()}"):
            found = await identity.resolve_sender(
                db, f"{local}@{COMPANY}", settings=INTERNAL, today=today
            )
            assert found is not None and found.id == person.contract_id, local
        # Klient przysyła plik z jednym z nazwisk (bez imienia, jedyna osoba u klienta).
        found = await identity.resolve_named_at_client(
            db,
            f"TimeSheet {old} wrzesien.pdf",
            client_ids=frozenset({person.client_id}),
            today=today,
        )
        assert found is not None and found.id == person.contract_id


# ── 3. Literówka w imieniu wśród klientów z portfela DL-a ─────────────────────


async def _dl_person(first: str):
    dl = await make_user(UserRole.delivery_lead)
    address = f"dl-{tag()}@{COMPANY}"
    async with AsyncSessionLocal() as db:
        await db.execute(update(User).where(User.id == dl.id).values(email=address))
        await db.commit()
    client_id = await make_client(dl=dl)
    contract_id, candidate_id = await make_consultant(client_id, first_name=first)
    surname = f"Testowski{_letters()}"
    await _rename(candidate_id, first, surname)
    return address, contract_id, surname


async def test_literowka_w_imieniu_u_klienta_z_portfela_dl() -> None:
    dl, contract_id, surname = await _dl_person("Tomasz")
    from_dl = _message("m1", dl, f"TS_{surname}_wrzesień 2026")
    # Odpowiedź z podpisanym plikiem idzie do DL-a: portfel z adresata.
    to_dl = _message("m2", f"podpis@{COMPANY}", f"ODP: TS_{surname}", to=(dl,))
    stranger = _message("m3", f"ktos@{COMPANY}", f"TS_{surname}_wrzesień 2026")
    files = {
        "m1": [_file(f"PROTOKÓŁ_ Tomsz {surname}_WRZESIEŃ 2026.pdf")],
        "m2": [
            _file(f"PROTOKÓŁ_ Tomsz {surname}_WRZESIEŃ 2026-sig.pdf", b"%PDF-1.4 p")
        ],
        "m3": [_file(f"PROTOKÓŁ_ Tomsz {surname}_X.pdf", b"%PDF-1.4 obcy")],
    }
    await _read(Box([from_dl, to_dl, stranger], files))
    assert await _owners() == {
        f"PROTOKÓŁ_ Tomsz {surname}_WRZESIEŃ 2026.pdf": contract_id,
        f"PROTOKÓŁ_ Tomsz {surname}_WRZESIEŃ 2026-sig.pdf": contract_id,
        # Bez DL-a w wątku nie ma klienta, wśród którego szukać.
        f"PROTOKÓŁ_ Tomsz {surname}_X.pdf": None,
    }


# ── 4. Skrzynka u klienta w poddomenie: external.imie.nazwisko@de.<klient> ─────


async def test_skrzynka_external_w_poddomenie_klienta_z_rejestru() -> None:
    nip = known_clients.KNOWN_REGISTRY_IDS["bosch"][0]
    person = await make_person(activated=False)
    surname = f"Testowa{_letters()}"
    await _rename(person.candidate_id, "Ola", surname)
    async with AsyncSessionLocal() as db:
        clash = await db.scalar(
            select(Client.id).where(Client.nip == nip, Client.id != person.client_id)
        )
        if clash is not None:
            pytest.skip("klient z numerem z rejestru istnieje już w bazie testowej")
        await db.execute(
            update(Contract)
            .where(Contract.id == person.contract_id)
            .values(candidate_email=None)
        )
        client = await db.get(Client, person.client_id)
        client.nip = nip
        await db.commit()
    try:
        today = business_today()
        local = f"external.ola.{surname.lower()}"
        async with AsyncSessionLocal() as db:
            found = await identity.resolve_sender(
                db, f"{local}@de.bosch.com", settings=INTERNAL, today=today
            )
            other = await identity.resolve_sender(
                db, f"{local}@de.inna-firma.example", settings=INTERNAL, today=today
            )
            # Poddomena innej domeny z rejestru nie wskazuje klienta: skrzynki
            # ``consult.`` Nordei to nasi konsultanci jako strona klienta w wątku.
            nordea = await identity._clients_of_domain(db, "consult.nordea.com")
        assert found is not None and found.id == person.contract_id
        assert nordea is None
        assert other is None
    finally:
        async with AsyncSessionLocal() as db:
            client = await db.get(Client, person.client_id)
            client.nip = None
            await db.commit()


# ── 5. Numer umowy wykonawczej ────────────────────────────────────────────────


async def _agreement(client_id: int, number: str, *contract_ids: int) -> int:
    start = business_today() - timedelta(days=60)
    async with AsyncSessionLocal() as db:
        group = ClientOrderGroup(
            client_id=client_id,
            order_number=number,
            start_date=start,
            status="active",
            order_type="md",
            is_cost_based=False,
            is_md_budget_based=False,
        )
        db.add(group)
        await db.flush()
        for contract_id in contract_ids:
            db.add(
                ClientOrder(
                    client_id=client_id,
                    contract_id=contract_id,
                    order_group_id=group.id,
                    title="linia MD",
                    status=ClientOrderStatus.active,
                    start_date=start,
                    md_total=Decimal("20"),
                    md_remaining=Decimal("20"),
                    md_input_mode="md",
                    md_input_value=Decimal("20"),
                    md_rate_cost=Decimal("1000"),
                    md_rate_revenue=Decimal("1100"),
                )
            )
        await db.commit()
        return group.id


async def test_numer_umowy_wykonawczej_wskazuje_kontrakt() -> None:
    person = await make_person(activated=False)
    second = await make_person(activated=False)
    prefix = "".join(random.choices(string.ascii_uppercase, k=4))
    await _agreement(person.client_id, f"{prefix}/17/2026", person.contract_id)
    await _agreement(
        person.client_id, f"{prefix}/18/2026", person.contract_id, second.contract_id
    )
    messages = [
        # Numer w nazwie pliku, w temacie inne imię niż w kartotece.
        _message("m1", f"pm@{COMPANY}", f"FW: Protokół odbioru Bartek {tag()}"),
        # Numer tylko w temacie.
        _message(
            "m2",
            f"pm@{COMPANY}",
            f"Protokół odbioru za 10/2026 do umowy {prefix}/17/2026",
        ),
        # Umowa dwóch osób nie wskazuje nikogo.
        _message("m3", f"pm@{COMPANY}", f"Protokół do umowy {prefix}/18/2026"),
    ]
    files = {
        "m1": [_file(f"Protokół Odbioru 10_2026 do {prefix}_17_2026-sig.pdf")],
        "m2": [_file("Protokół odbioru.pdf", b"%PDF-1.4 drugi")],
        "m3": [_file("Protokół odbioru X.pdf", b"%PDF-1.4 trzeci")],
    }
    await _read(Box(messages, files))
    assert await _owners() == {
        f"Protokół Odbioru 10_2026 do {prefix}_17_2026-sig.pdf": person.contract_id,
        "Protokół odbioru.pdf": person.contract_id,
        "Protokół odbioru X.pdf": None,
    }


# ── 6. Akceptacja klienta w wątku maila z Time Sheet i ze skrzynki konsultanta ──


async def _rules(client_id: int, rules: dict) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            ClientSettlementRuleSet(
                client_id=client_id, effective_from="2026-01", rules=rules
            )
        )
        await db.commit()


async def _drop_rules(client_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(ClientSettlementRuleSet).where(
                ClientSettlementRuleSet.client_id == client_id
            )
        )
        await db.commit()


QUOTED = """Przesyłam Time Sheet z akceptacją poniżej.

*From:* Kierownik Testowy <kierownik@{domain}>
*Sent:* Monday, October 5, 2026 11:02 AM
*Subject:* ODP: Potwierdzenie godzin - wrzesień

Potwierdzam
"""


async def test_tresc_maila_z_ts_zapisana_gdy_w_watku_pisze_klient() -> None:
    domain = f"klient-{tag()}.example"
    person = await make_person(activated=False)
    await _rules(
        person.client_id,
        {"proof.excel_with_mail": {"level": "warn", "params": {"domain": domain}}},
    )
    try:
        subject = "Potwierdzenie godzin i faktura - wrzesień 2026"
        with_client = _message("m1", person.email, subject)
        without = _message("m2", person.email, "Faktura - wrzesień 2026")
        box = Box(
            [with_client, without],
            {
                "m1": [_file("Timesheet wrzesien.pdf")],
                "m2": [_file("TS wrzesien 2.pdf", b"%PDF-1.4 inny ts")],
            },
            {
                "m1": _eml(person.email, subject, QUOTED.format(domain=domain)),
                "m2": _eml(person.email, "Faktura", "W załączniku TS."),
            },
        )
        await _read(box)
        owners = await _owners()
        assert owners == {
            "Timesheet wrzesien.pdf": person.contract_id,
            f"{subject}.eml": person.contract_id,
            # Bez wiadomości klienta w wątku treści nie zapisujemy.
            "TS wrzesien 2.pdf": person.contract_id,
        }
    finally:
        await _drop_rules(person.client_id)


async def test_akceptacja_ze_skrzynki_konsultanta_u_klienta_bez_nazwiska() -> None:
    domain = f"klient-{tag()}.example"
    address = f"konsultant.{tag()}@{domain}"
    person = await make_person(activated=False, email=address)
    await _rules(
        person.client_id,
        {"proof.excel_with_mail": {"level": "warn", "params": {"domain": domain}}},
    )
    try:
        subject = "PD: akcept rozliczenia"
        message = _message("m1", address, subject, to=("rozliczenia@example.com",))
        message["hasAttachments"] = False
        text = f"Podsyłam akcept.\n\nOd: Kierownik <kierownik@{domain}>\nakceptuję\n"
        await _read(Box([message], {}, {"m1": _eml(address, subject, text)}))
        assert await _owners() == {f"{subject}.eml": person.contract_id}
    finally:
        await _drop_rules(person.client_id)


async def test_akceptacja_z_tematem_o_innej_osobie_czeka_na_czlowieka() -> None:
    """Konsultant przekazuje akceptację za kogoś innego: temat nazywa osobę, której
    czytnik nie przypisze (inny klient albo dwa kontrakty). Mail nie idzie do nadawcy."""

    domain = f"klient-{tag()}.example"
    address = f"konsultant.{tag()}@{domain}"
    person = await make_person(activated=False, email=address)
    surname = f"Nowa{_letters()}"
    await _named("Kornelia", surname)
    await _rules(
        person.client_id,
        {"proof.excel_with_mail": {"level": "warn", "params": {"domain": domain}}},
    )
    try:
        subject = f"PD: akceptacja godzin Kornelia {surname}"
        message = _message("m1", address, subject, to=("rozliczenia@example.com",))
        message["hasAttachments"] = False
        text = f"Podsyłam akcept.\n\nOd: Kierownik <kierownik@{domain}>\nakceptuję\n"
        await _read(Box([message], {}, {"m1": _eml(address, subject, text)}))
        assert await _owners() == {f"{subject}.eml": None}
    finally:
        await _drop_rules(person.client_id)


async def test_wlasny_mail_konsultanta_ze_skrzynki_u_klienta_to_nie_akceptacja() -> (
    None
):
    """Skrzynka konsultanta u klienta jest w domenie klienta, ale jego własny mail
    z fakturą albo pytaniem nie jest wiadomością klienta: bez kierownika w wątku nie
    zapisujemy treści i nie przypisujemy maila bez pliku."""

    domain = f"klient-{tag()}.example"
    address = f"konsultant.{tag()}@{domain}"
    person = await make_person(activated=False, email=address)
    await _rules(
        person.client_id,
        {"proof.excel_with_mail": {"level": "warn", "params": {"domain": domain}}},
    )
    try:
        invoice = _message("m1", address, "09.26 rozliczenie")
        question = _message(
            "m2", address, "rozliczenie za wrzesień", to=("rozliczenia@example.com",)
        )
        question["hasAttachments"] = False
        kesu = _message("m3", address, f"RE: KEŚU wrzesień - Ola {_letters()}")
        box = Box(
            [invoice, question, kesu],
            {
                "m1": [_file("Faktura 09.2026.pdf")],
                "m3": [_file("KESU wrzesien.pdf", b"%PDF-1.4 kesu")],
            },
            {
                "m1": _eml(address, "09.26 rozliczenie", "W załączniku faktura."),
                "m2": _eml(address, "rozliczenie", "Kiedy przelew?"),
                "m3": _eml(
                    address,
                    "RE: KEŚU",
                    f"Podpisane.\n\nOd: Kierownik <kierownik@{domain}>\nakceptuję\n",
                ),
            },
        )
        await _read(box)
        assert await _owners() == {
            "Faktura 09.2026.pdf": person.contract_id,
            "rozliczenie za wrzesień.eml": None,
            "KESU wrzesien.pdf": person.contract_id,
        }
    finally:
        await _drop_rules(person.client_id)
