"""Informacja zwrotna o wadach rozliczenia: co jest źle, jak to poprawić, do skutku.

Powtórka 7 próby IX–X (24.11.2026): 16 uwag NEXUS-a było prawdziwych i 5 to
proces, ale uwaga stała na karcie Finansów i nie docierała do osoby, która ma
ją poprawić. Reguły: ``docs/claude/finanse-insights/rozliczenia-informacja-zwrotna-o-wadach.md``.

* **Wada** = uwaga ``warn``/``fail`` z ``client_settlements.checks`` z katalogu
  ``CATALOG`` (klucz ``rule`` albo początek tytułu), raport-zdjęcie bez MD albo
  „Do poprawy” od Finansów. Uwag spoza katalogu (nadgodziny, dwie stawki, ta sama
  osoba u dwóch klientów) rozstrzygają Finanse i nikt nie dostaje komunikatu.
* **Jeden komunikat na wadę i miesiąc**: wiersz ``client_settlement_feedback``
  (kontrakt, miesiąc, kod). Wady tego samego kontraktu i miesiąca dla jednej
  osoby idą w jednym mailu albo dzwonku.
* **Przypomnienia** co ``every_days`` dni roboczych od ostatniego komunikatu;
  **koniec**, gdy wady już nie ma (nowy plik bez uwagi) albo rozliczenie
  przyjęto (``resolved_on``).
* **Adresat**: konsultant (``contracts.candidate_email``), akceptujący u klienta
  (adres z prośby o akceptację w uwadze, konsultant w kopii) albo opiekun
  (``reminders.pick_owner``: opiekun kontraktu, opiekun klienta, DL klienta).
  Gdy do konsultanta albo klienta nie wolno pisać, wada idzie dzwonkiem do
  opiekuna z prośbą o przekazanie; bez opiekuna — „bez adresata” w dzienniku.
* **Wyłącznik** ``app_settings['client_settlement_feedback']``: ``mode`` =
  ``off`` (domyślnie) / ``dry_run`` (zapisuje „wysłałbym: komu, co, kiedy”
  w ``sends``, nic nie wysyła) / ``on``; ``external`` = ``off`` (domyślnie,
  do ludzi spoza firmy nic) / ``panel`` (tylko kontrakty z otwartym panelem,
  przez ``portal_mail.send``) / ``all``. ``external`` zmienia się wyłącznie po
  wyraźnym „tak” Artura w czacie.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Any, Iterable, Mapping, Optional, Sequence

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_settlement import ClientSettlement
from app.models.client_settlement_feedback import ClientSettlementFeedback
from app.models.consultant_portal import CpDocument
from app.models.contract import Contract
from app.models.notification import NotificationType
from app.models.user import User
from app.services import client_settlement_feedback_schema as schema
from app.services.care.announcement_mail import MailOutcome
from app.services.client_order_lines import format_period_month
from app.services.client_settlements import reminders
from app.services.client_settlements import settings as module_settings
from app.services.consultant_portal import identity, portal_mail, portal_settings
from app.services.hr.payroll_periods import add_months
from app.services.person_workdays import business_days

logger = logging.getLogger(__name__)

SETTING_KEY = "client_settlement_feedback"
MODES = ("off", "dry_run", "on")
EXTERNAL = ("off", "panel", "all")
DEFAULT_EVERY_DAYS = 3
MAX_EVERY_DAYS = 20
#: Ile miesięcy wstecz automat pilnuje wad (poprzedni i jeszcze jeden).
MONTHS_BACK = 2
#: Rozliczenia, w których wada czeka na kogoś; ``ok`` i ``accepted`` nie mają wad.
OPEN_STATUSES = ("warnings", "checking", "no_md", "needs_fix")
#: Rozliczenie bez MD: raport-zdjęcie jest wtedy wadą (z MD — nie).
NO_MD_STATUSES = ("checking", "no_md")
#: Wynik zapisu w dzienniku ``sends``.
DRY_RUN = "dry_run"
NO_RECIPIENT = "no_recipient"
#: Darmowe skrzynki: plik z nich to „prywatna poczta” w treści komunikatu.
PRIVATE_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "wp.pl",
        "o2.pl",
        "onet.pl",
        "op.pl",
        "onet.eu",
        "vp.pl",
        "interia.pl",
        "interia.eu",
        "poczta.fm",
        "gazeta.pl",
        "tlen.pl",
        "icloud.com",
        "me.com",
        "outlook.com",
        "hotmail.com",
        "live.com",
        "yahoo.com",
        "proton.me",
        "protonmail.com",
    }
)


# ── Przełącznik ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Settings:
    mode: str = "off"
    external: str = "off"
    every_days: int = DEFAULT_EVERY_DAYS

    @property
    def active(self) -> bool:
        return self.mode != "off"

    @property
    def dry_run(self) -> bool:
        return self.mode == "dry_run"

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "external": self.external,
            "every_days": self.every_days,
        }


def normalize(raw: object) -> Settings:
    """Nieczytelny wpis = wyłączone: to wyłącznik wysyłki do ludzi."""

    if not isinstance(raw, dict):
        return Settings()
    mode = raw.get("mode") if raw.get("mode") in MODES else "off"
    external = raw.get("external") if raw.get("external") in EXTERNAL else "off"
    every = raw.get("every_days")
    if not isinstance(every, int) or isinstance(every, bool):
        every = DEFAULT_EVERY_DAYS
    return Settings(
        mode=mode, external=external, every_days=min(max(every, 1), MAX_EVERY_DAYS)
    )


async def load(db: AsyncSession) -> Settings:
    raw = await db.scalar(select(AppSetting.value).where(AppSetting.key == SETTING_KEY))
    return normalize(raw)


async def save(db: AsyncSession, value: Settings, *, actor: User) -> dict[str, Any]:
    """Zapis przełącznika (bez commita)."""

    data = value.as_dict()
    statement = insert(AppSetting).values(
        key=SETTING_KEY, value=data, updated_by=actor.id
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": statement.excluded.value, "updated_by": actor.id},
        )
    )
    return data


# ── Katalog wad ─────────────────────────────────────────────────────────────

CONSULTANT = "consultant"
CLIENT = "client"
OWNER = "owner"


@dataclass(frozen=True)
class Defect:
    """Wada, którą poprawia ktoś poza Finansami, i instrukcja po polsku.

    ``instruction`` dostaje ``{month}``, ``{address}``, ``{client}``,
    ``{person}`` i ``{detail}``. ``rules``/``titles`` dopasowują uwagę z
    ``checks`` (pierwszy pasujący wpis wygrywa). ``detail`` = pierwsze zdanie
    szczegółu uwagi trafia do komunikatu (tylko MD i godziny, nigdy kwoty)."""

    code: str
    audience: str
    title: str
    instruction: str
    rules: tuple[str, ...] = ()
    titles: tuple[str, ...] = ()
    detail: bool = False
    #: Instrukcja dla konsultanta, gdy akceptującego u klienta nie ma jak
    #: zapytać (brak adresu albo wysyłka do klientów wyłączona).
    consultant_instruction: Optional[str] = None


ACCEPT_NO_REPLY = "accept.no_reply"
IMAGE_REPORT = "proof.image_file"
NEEDS_FIX = "finance.needs_fix"

CATALOG: tuple[Defect, ...] = (
    Defect(
        code=ACCEPT_NO_REPLY,
        audience=CLIENT,
        title="Prośba o akceptację godzin bez odpowiedzi",
        instruction=(
            "Prosimy o odpowiedź „Akceptuję” na prośbę o akceptację czasu pracy "
            "za {month} od konsultanta B2Bnetwork: {person}. Liczba godzin jest "
            "w treści prośby. Odpowiedź prosimy wysłać do konsultanta z kopią "
            "na {address}."
        ),
        consultant_instruction=(
            "Akceptujący u klienta nie odpowiedział na Twoją prośbę o akceptację "
            "godzin za {month}. Poproś go o odpowiedź „Akceptuję” na Twój mail "
            "i prześlij nam cały wątek (MSG albo EML) na {address}."
        ),
        rules=("proof.accept_has_hours",),
        titles=("Mail bez odpowiedzi akceptującego",),
    ),
    Defect(
        code="accept.fix",
        audience=CONSULTANT,
        title="Akceptacja godzin do poprawy",
        instruction=(
            "Prześlij mail, w którym akceptujący u klienta potwierdza liczbę "
            "godzin za {month} (MSG albo EML, z liczbą godzin w treści), "
            "na {address}."
        ),
        rules=("proof.accept_has_hours",),
        detail=True,
    ),
    Defect(
        code="proof.excel_with_mail",
        audience=CONSULTANT,
        title="Excel z RCP bez maila akceptującego usługi",
        instruction=(
            "Do RCP w Excelu za {month} dołącz mail, w którym akceptujący "
            "u klienta potwierdza usługi (MSG, EML albo PDF z wydrukiem maila), "
            "i wyślij oba pliki na {address}."
        ),
        rules=("proof.excel_with_mail",),
    ),
    Defect(
        code="proof.signed_pdf",
        audience=CONSULTANT,
        title="PDF z RCP bez podpisu elektronicznego",
        instruction=(
            "Wyślij RCP za {month} jako PDF podpisany kwalifikowanym podpisem "
            "elektronicznym akceptującego u klienta, bez zmian w pliku po "
            "podpisie (bez drukowania i skanowania), na {address}."
        ),
        rules=("proof.signed_pdf",),
    ),
    Defect(
        code="fields.rows_sum",
        audience=CONSULTANT,
        title="Wiersze opisu prac nie sumują się do SUMA",
        instruction=(
            "Popraw RCP za {month} tak, żeby wiersze opisu prac sumowały się "
            "do wiersza SUMA ({detail}), i wyślij poprawiony plik z akceptacją "
            "klienta na {address}."
        ),
        titles=("Wiersze opisu prac nie sumują się do SUMA",),
        detail=True,
    ),
    Defect(
        code="fields.total_hours",
        audience=CONSULTANT,
        title="Suma godzin w raporcie inna niż suma wierszy",
        instruction=(
            "Popraw sumę godzin w raporcie za {month} („Total Hours”, pole "
            "Check) tak, żeby zgadzała się z wierszami ({detail}), i wyślij "
            "poprawiony plik z akceptacją klienta na {address}."
        ),
        titles=(
            "Suma „Total Hours” inna niż suma wierszy",
            "Szablon pokazuje błąd sum (pole Check)",
        ),
        detail=True,
    ),
    Defect(
        code=IMAGE_REPORT,
        audience=CONSULTANT,
        title="Raport godzin jako zdjęcie",
        instruction=(
            "Raport godzin za {month} przyszedł jako zdjęcie. Wyślij go jako "
            "plik PDF albo Excel z akceptacją klienta (nie zdjęcie ani zrzut "
            "ekranu){private}, na {address}."
        ),
    ),
    Defect(
        code="amount.protocol",
        audience=OWNER,
        title="Kwota do faktury inna niż w protokole klienta",
        instruction=(
            "Przed wystawieniem faktury za {month}: kwota do faktury różni się "
            "od protokołu klienta. Ustal z klientem MD, stawkę i zamówienie (PO) "
            "albo poproś o poprawiony protokół. Szczegóły na karcie rozliczenia."
        ),
        titles=("Kwota do faktury inna niż w protokole klienta",),
    ),
    Defect(
        code=NEEDS_FIX,
        audience=CONSULTANT,
        title="Raport odesłany przez Finanse do poprawy",
        instruction=(
            "Finanse odesłały raport za {month} do poprawy: „{detail}”. "
            "Wyślij poprawiony raport na {address}."
        ),
        detail=True,
    ),
)
BY_CODE: dict[str, Defect] = {d.code: d for d in CATALOG}


def match(check: Mapping[str, Any]) -> Optional[Defect]:
    """Wpis katalogu dla uwagi z ``checks``; ``None`` = sprawa Finansów."""

    if check.get("state") not in ("warn", "fail"):
        return None
    rule = check.get("rule")
    title = str(check.get("title") or "")
    for defect in CATALOG:
        if defect.code in (IMAGE_REPORT, NEEDS_FIX):
            continue
        by_rule = not defect.rules or rule in defect.rules
        by_title = not defect.titles or title.startswith(defect.titles)
        if (defect.rules or defect.titles) and by_rule and by_title:
            return defect
    return None


def first_sentence(text: Optional[str]) -> Optional[str]:
    """Szczegół uwagi do komunikatu: pierwsze zdanie, bez rad dla Finansów."""

    clean = " ".join((text or "").split())
    if not clean:
        return None
    head = clean.split(". ", 1)[0].rstrip(".")
    return head[: schema.DETAIL_MAX] or None


@dataclass(frozen=True)
class Found:
    """Wada znaleziona w rozliczeniu (bez bazy)."""

    code: str
    detail: Optional[str] = None
    #: Adres akceptującego u klienta (z prośby o akceptację), gdy jest.
    acceptor: Optional[str] = None
    #: Raport-zdjęcie przyszedł z darmowej skrzynki.
    private: bool = False


def is_private(address: Optional[str]) -> bool:
    email = identity.normalize_email(address)
    return "@" in email and email.rsplit("@", 1)[1] in PRIVATE_DOMAINS


def defects_in(
    *,
    status: str,
    checks: Sequence[Any],
    fix_reason: Optional[str] = None,
    report_mime: Optional[str] = None,
    report_sender: Optional[str] = None,
    consultant_reports: bool = True,
) -> list[Found]:
    """Wady rozliczenia w kolejności uwag; jedna na kod (czysta funkcja).

    ``consultant_reports=False``: godziny przysyła klient (Nordea, T4T), więc
    zdjęcie od konsultanta nie jest jego raportem i nie jest wadą (powtórka 7:
    15 takich rozliczeń Nordei w IX–X)."""

    if status not in OPEN_STATUSES:
        return []
    found: dict[str, Found] = {}
    if status == "needs_fix":
        found[NEEDS_FIX] = Found(NEEDS_FIX, detail=first_sentence(fix_reason))
    for group in checks or []:
        if not isinstance(group, dict):
            continue
        for check in group.get("checks") or []:
            if not isinstance(check, dict):
                continue
            defect = match(check)
            if defect is None or defect.code in found:
                continue
            acceptors = check.get("acceptors") or []
            found[defect.code] = Found(
                defect.code,
                detail=first_sentence(check.get("detail")) if defect.detail else None,
                acceptor=next(
                    (a for a in acceptors if isinstance(a, str) and "@" in a), None
                ),
            )
    if (
        consultant_reports
        and status in NO_MD_STATUSES
        and (report_mime or "").startswith("image/")
        and IMAGE_REPORT not in found
    ):
        found[IMAGE_REPORT] = Found(IMAGE_REPORT, private=is_private(report_sender))
    return list(found.values())


# ── Harmonogram ─────────────────────────────────────────────────────────────


def months_for(today: date) -> list[str]:
    """Miesiące, których wady automat pilnuje: ``MONTHS_BACK`` przed bieżącym."""

    out = []
    for back in range(1, MONTHS_BACK + 1):
        year, month = add_months(today.year, today.month, -back)
        out.append(f"{year}-{month:02d}")
    return out


def due(last_sent_on: Optional[date], today: date, every_days: int) -> bool:
    """Pierwszy komunikat od razu, potem co ``every_days`` dni roboczych."""

    if last_sent_on is None:
        return True
    if last_sent_on >= today:
        return False
    return len(business_days(last_sent_on + timedelta(days=1), today)) >= every_days


# ── Adresat ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Target:
    """Kto dostaje komunikat: ``consultant``, ``client``, ``owner`` albo ``none``.

    ``why`` mówi, dlaczego wada nie poszła do osoby z ``audience``
    (``external_off``, ``panel_closed``, ``no_email``, ``no_acceptor``)."""

    kind: str
    address: Optional[str] = None
    user_id: Optional[int] = None
    cc: Optional[str] = None
    why: Optional[str] = None

    @property
    def key(self) -> tuple[str, Optional[str], Optional[int]]:
        return (self.kind, self.address, self.user_id)


@dataclass(frozen=True)
class Who:
    """Adresy kontraktu potrzebne do wyboru adresata."""

    consultant_email: Optional[str]
    owner: Optional[reminders.Owner]
    panel_open: bool


def external_block(settings: Settings, who: Who) -> Optional[str]:
    if settings.external == "off":
        return "external_off"
    if settings.external == "panel" and not who.panel_open:
        return "panel_closed"
    return None


def target_for(
    defect: Defect, found: Found, who: Who, settings: Settings
) -> tuple[Target, str]:
    """(adresat, instrukcja do użycia). Kolejność: osoba z ``audience``,
    potem konsultant (dla akceptującego), potem opiekun z prośbą o przekazanie."""

    owner = who.owner
    owner_target = (
        Target(OWNER, address=owner.email, user_id=owner.user_id) if owner else None
    )
    if defect.audience == OWNER:
        return (owner_target or Target("none", why="no_owner"), defect.instruction)
    blocked = external_block(settings, who)
    instruction = defect.instruction
    why: Optional[str] = blocked
    if defect.audience == CLIENT:
        if blocked is None and found.acceptor:
            return (
                Target(CLIENT, address=found.acceptor, cc=who.consultant_email),
                instruction,
            )
        instruction = defect.consultant_instruction or instruction
        why = blocked or "no_acceptor"
    if blocked is None and who.consultant_email:
        return (
            Target(
                CONSULTANT,
                address=who.consultant_email,
                cc=owner.email if owner else None,
                why=why if defect.audience == CLIENT else None,
            ),
            instruction,
        )
    why = why or "no_email"
    if owner_target is not None:
        return (replace(owner_target, why=why), instruction)
    return (Target("none", why=why), instruction)


# ── Treść ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Item:
    """Jedna wada w komunikacie (wiersz bazy + katalog + instrukcja)."""

    row_id: int
    defect: Defect
    found: Found
    instruction: str


@dataclass(frozen=True)
class Context:
    contract_id: int
    client_id: Optional[int]
    client_name: str
    person: str
    month: str
    settlement_id: Optional[int] = None


def _fill(text: str, ctx: Context, found: Found, address: str) -> str:
    return text.format(
        month=format_period_month(ctx.month),
        address=address,
        client=ctx.client_name,
        person=ctx.person,
        detail=found.detail or "",
        private=" z adresu firmowego, nie z prywatnej skrzynki"
        if found.private
        else "",
    ).replace(" ()", "")


SIGNATURE = "Pozdrawiamy\nZespół rozliczeń B2Bnetwork"


def compose_mail(
    target: Target, ctx: Context, items: list[Item], address: str, *, reminder: bool
) -> tuple[str, str]:
    """Temat i treść maila do konsultanta albo akceptującego u klienta."""

    label = format_period_month(ctx.month)
    lead = "Przypomnienie: " if reminder else ""
    if target.kind == CLIENT:
        subject = f"{lead}Akceptacja czasu pracy za {label}: {ctx.person}"
        body = "\n\n".join(_fill(i.instruction, ctx, i.found, address) for i in items)
        return subject, f"Dzień dobry,\n\n{body}\n\nDziękujemy.\n\n{SIGNATURE}"
    if len(items) == 1:
        subject = f"{lead}Rozliczenie za {label}: {items[0].defect.title.lower()}"
    else:
        subject = f"{lead}Rozliczenie za {label}: {len(items)} rzeczy do poprawy"
    lines = []
    for number, item in enumerate(items, start=1):
        what = item.defect.title
        if item.found.detail and "{detail}" not in item.defect.instruction:
            what += f" ({item.found.detail})"
        lines.append(
            f"{number}. {what}.\n   Co zrobić: {_fill(item.instruction, ctx, item.found, address)}"
        )
    text = (
        "Dzień dobry,\n\n"
        f"w rozliczeniu za {label} u klienta {ctx.client_name} "
        f"{'jest jedna rzecz' if len(items) == 1 else 'są rzeczy'} do poprawy:\n\n"
        + "\n\n".join(lines)
        + "\n\nGdy poprawka do nas dotrze, przypomnienia ustaną. Bez niej nie "
        "rozliczymy miesiąca ani Twojej faktury.\n\n"
        f"{SIGNATURE}"
    )
    return subject, text


def compose_bell(
    target: Target, ctx: Context, items: list[Item], address: str
) -> tuple[str, str]:
    """Tytuł i opis dzwonka opiekuna (bez kwot i stawek)."""

    label = format_period_month(ctx.month)
    forward = [i for i in items if i.defect.audience != OWNER]
    own = [i for i in items if i.defect.audience == OWNER]
    title = f"Rozliczenie {label}: {ctx.person}, {ctx.client_name}"
    parts = [_fill(i.instruction, ctx, i.found, address) for i in own]
    if forward:
        names = "; ".join(
            i.defect.title + (f" ({i.found.detail})" if i.found.detail else "")
            for i in forward
        )
        parts.append(
            f"Przekaż konsultantowi: {names}. "
            + " ".join(_fill(i.instruction, ctx, i.found, address) for i in forward)
        )
    return title, " ".join(parts)


# ── Baza: wady, stan, dziennik ──────────────────────────────────────────────


@dataclass
class Settlement:
    """Rozliczenie z danymi potrzebnymi do wad i adresata."""

    id: int
    contract_id: int
    client_id: int
    client_name: str
    person: str
    month: str
    status: str
    checks: list[Any]
    fix_reason: Optional[str]
    report_mime: Optional[str]
    report_sender: Optional[str]
    consultant_email: Optional[str]
    contract_owner: Optional[int]
    client_owner: Optional[int]
    found: list[Found] = field(default_factory=list)


async def _settlements(
    db: AsyncSession, month: str, *, client_ids: Optional[set[int]] = None
) -> list[Settlement]:
    stmt = (
        select(
            ClientSettlement.id,
            ClientSettlement.contract_id,
            ClientSettlement.client_id,
            Client.name,
            reminders._FULL_NAME,
            ClientSettlement.status,
            ClientSettlement.checks,
            ClientSettlement.fix_reason,
            CpDocument.mime,
            CpDocument.sender_email,
            Contract.candidate_email,
            Candidate.email,
            reminders._CONTRACTS_CARE.c.care_owner_user_id,
            reminders._CLIENTS_CARE.c.default_care_owner_user_id,
        )
        .join(Contract, Contract.id == ClientSettlement.contract_id)
        .join(Client, Client.id == ClientSettlement.client_id)
        .join(reminders._CONTRACTS_CARE, reminders._CONTRACTS_CARE.c.id == Contract.id)
        .join(
            reminders._CLIENTS_CARE,
            reminders._CLIENTS_CARE.c.id == ClientSettlement.client_id,
        )
        .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
        .outerjoin(CpDocument, CpDocument.id == ClientSettlement.report_document_id)
        .where(
            ClientSettlement.period_month == month,
            ClientSettlement.kind == "actual",
        )
        .order_by(ClientSettlement.id)
    )
    if client_ids is not None:
        stmt = stmt.where(ClientSettlement.client_id.in_(client_ids))
    result = (await db.execute(stmt)).all()
    from_client = await reminders.client_hours_clients(
        db, {row[2] for row in result}, month
    )
    out = []
    for row in result:
        s = Settlement(
            id=row[0],
            contract_id=row[1],
            client_id=row[2],
            client_name=row[3],
            person=row[4] or f"Kontrakt {row[1]}",
            month=month,
            status=row[5],
            checks=list(row[6] or []),
            fix_reason=row[7],
            report_mime=row[8],
            report_sender=row[9],
            # Adres z kontraktu, potem z kartoteki — jak rozpoznanie nadawcy
            # (``identity``); powtórka 7: większość kontraktów nie ma adresu.
            consultant_email=identity.normalize_email(row[10])
            or identity.normalize_email(row[11]),
            contract_owner=row[12],
            client_owner=row[13],
        )
        s.found = defects_in(
            status=s.status,
            checks=s.checks,
            fix_reason=s.fix_reason,
            report_mime=s.report_mime,
            report_sender=s.report_sender,
            consultant_reports=s.client_id not in from_client,
        )
        out.append(s)
    return out


async def sync_month(
    db: AsyncSession,
    month: str,
    today: date,
    *,
    client_ids: Optional[set[int]] = None,
) -> tuple[list[Settlement], dict[str, int]]:
    """Zapisuje wady miesiąca: nowe, powracające i poprawione (bez commita)."""

    settlements = await _settlements(db, month, client_ids=client_ids)
    seen: dict[tuple[int, str], tuple[Settlement, Found]] = {
        (s.contract_id, f.code): (s, f) for s in settlements for f in s.found
    }
    existing_stmt = select(ClientSettlementFeedback).where(
        ClientSettlementFeedback.period_month == month
    )
    if client_ids is not None:
        existing_stmt = existing_stmt.where(
            ClientSettlementFeedback.client_id.in_(client_ids)
        )
    existing = {
        (row.contract_id, row.code): row
        for row in (await db.scalars(existing_stmt)).all()
    }
    counts = {"new": 0, "open": 0, "reopened": 0, "resolved": 0}
    for key, (s, found) in seen.items():
        row = existing.get(key)
        defect = BY_CODE[found.code]
        if row is None:
            db.add(
                ClientSettlementFeedback(
                    contract_id=s.contract_id,
                    client_id=s.client_id,
                    period_month=month,
                    code=found.code,
                    audience=defect.audience,
                    detail=found.detail,
                    first_seen_on=today,
                    last_seen_on=today,
                )
            )
            counts["new"] += 1
            continue
        if row.resolved_on is not None:
            row.resolved_on = None
            counts["reopened"] += 1
        else:
            counts["open"] += 1
        row.last_seen_on = max(row.last_seen_on, today)
        row.detail = found.detail
        row.audience = defect.audience
    for key, row in existing.items():
        if key not in seen and row.resolved_on is None:
            row.resolved_on = today
            counts["resolved"] += 1
    await db.flush()
    return settlements, counts


async def _who(db: AsyncSession, settlements: list[Settlement]) -> dict[int, Who]:
    if not settlements:
        return {}
    client_ids = {s.client_id for s in settlements}
    leads = await reminders._client_leads(db, client_ids)
    users = await reminders._active_users(
        db,
        {
            uid
            for s in settlements
            for uid in (s.contract_owner, s.client_owner)
            if uid is not None
        }
        | set(leads.values()),
    )
    state = await portal_settings.load(db)
    return {
        s.contract_id: Who(
            consultant_email=s.consultant_email,
            owner=reminders.pick_owner(
                contract_owner=s.contract_owner,
                client_owner=s.client_owner,
                client_lead=leads.get(s.client_id),
                users=users,
            ),
            panel_open=state.open_for(s.contract_id),
        )
        for s in settlements
    }


async def _reserve(db: AsyncSession, row_ids: list[int], today: date) -> list[int]:
    """Rezerwacja przed wysyłką: drugi przebieg tego samego dnia nic nie dostaje.

    Commit od razu, jak w ``reminders._reserve``: wysłany komunikat nie może
    zależeć od reszty przebiegu."""

    if not row_ids:
        return []
    reserved = await db.scalars(
        update(ClientSettlementFeedback)
        .where(
            ClientSettlementFeedback.id.in_(row_ids),
            ClientSettlementFeedback.resolved_on.is_(None),
            (ClientSettlementFeedback.last_sent_on.is_(None))
            | (ClientSettlementFeedback.last_sent_on < today),
        )
        .values(
            last_sent_on=today,
            send_count=ClientSettlementFeedback.send_count + 1,
        )
        .returning(ClientSettlementFeedback.id)
    )
    ids = list(reserved.all())
    await db.commit()
    return ids


async def _log(db: AsyncSession, row_ids: list[int], entry: dict[str, Any]) -> None:
    for row_id in row_ids:
        row = await db.get(ClientSettlementFeedback, row_id)
        if row is not None:
            row.sends = [*(row.sends or []), entry]
    await db.commit()


def real_sends(sends: Iterable[Any]) -> int:
    return sum(
        1
        for entry in sends or []
        if isinstance(entry, dict) and entry.get("outcome") in ("sent", "simulated")
    )


def _outcome(result: Optional[MailOutcome]) -> str:
    if result is None:
        return "blocked"
    if result.status == "accepted":
        return "simulated" if result.simulated else "sent"
    return "failed"


async def _send_mail(
    db: AsyncSession,
    target: Target,
    contract_id: int,
    subject: str,
    text: str,
    settings: Settings,
) -> str:
    """Mail do konsultanta albo klienta. ``panel``: przez ``portal_mail.send``
    (wyłącznik panelu dla kontraktu); ``all``: ten sam nadawca bez panelu."""

    try:
        if settings.external == "panel":
            result = await portal_mail.send(
                db,
                contract_id=contract_id,
                to=target.address or "",
                subject=subject,
                text=text,
                cc=target.cc,
            )
        else:
            mailer = portal_mail.default_mailer()
            if mailer is None:
                return "blocked"
            if target.cc:
                result = await mailer.send(
                    to=target.address or "", subject=subject, text=text, cc=target.cc
                )
            else:
                result = await mailer.send(
                    to=target.address or "", subject=subject, text=text
                )
    except Exception:  # noqa: BLE001 — jeden zły adres nie zatrzymuje reszty
        logger.exception("settlement_feedback: mail contract=%s", contract_id)
        result = MailOutcome("uncertain", "exception")
    return _outcome(result)


async def _ring(
    db: AsyncSession, target: Target, ctx: Context, title: str, message: str
) -> str:
    from app.services.notification_triggers import emit  # noqa: PLC0415

    row = await emit(
        db,
        user_id=target.user_id or 0,
        title=title,
        message=message,
        ntype=NotificationType.settlement_feedback,
        related_entity_type="client_settlement",
        related_entity_id=ctx.settlement_id,
        link=f"/contracts/{ctx.contract_id}",
    )
    return "sent" if row is not None else "blocked"


async def deliver_month(
    db: AsyncSession,
    settlements: list[Settlement],
    month: str,
    today: date,
    settings: Settings,
) -> dict[str, int]:
    """Komunikaty miesiąca, którym przyszedł termin (pierwszy albo przypomnienie)."""

    counts = {"messages": 0, "items": 0, "no_recipient": 0, "failed": 0}
    by_contract = {s.contract_id: s for s in settlements if s.found}
    if not by_contract:
        return counts
    rows = (
        await db.scalars(
            select(ClientSettlementFeedback)
            .where(
                ClientSettlementFeedback.period_month == month,
                ClientSettlementFeedback.contract_id.in_(list(by_contract)),
                ClientSettlementFeedback.resolved_on.is_(None),
            )
            .order_by(ClientSettlementFeedback.id)
        )
    ).all()
    by_id = {row.id: row for row in rows}
    whos = await _who(db, list(by_contract.values()))
    address = reminders.settlements_address() or "adres rozliczeń"
    groups: dict[tuple[int, tuple[Any, ...]], tuple[Target, list[Item]]] = {}
    for row in rows:
        if not due(row.last_sent_on, today, settings.every_days):
            continue
        s = by_contract[row.contract_id]
        found = next((f for f in s.found if f.code == row.code), None)
        if found is None:
            continue
        defect = BY_CODE[row.code]
        target, instruction = target_for(defect, found, whos[s.contract_id], settings)
        item = Item(row.id, defect, found, instruction)
        key = (s.contract_id, target.key)
        groups.setdefault(key, (target, []))[1].append(item)
    for (contract_id, _), (target, items) in groups.items():
        s = by_contract[contract_id]
        ctx = Context(
            contract_id=contract_id,
            client_id=s.client_id,
            client_name=s.client_name,
            person=s.person,
            month=month,
            settlement_id=s.id,
        )
        reserved = await _reserve(db, [i.row_id for i in items], today)
        items = [i for i in items if i.row_id in reserved]
        if not items:
            continue
        reminder = any(real_sends(by_id[i.row_id].sends) for i in items)
        if target.kind in (CONSULTANT, CLIENT):
            subject, text = compose_mail(target, ctx, items, address, reminder=reminder)
            channel = "mail"
        else:
            subject, text = compose_bell(target, ctx, items, address)
            channel = "bell"
        if target.kind == "none":
            outcome = NO_RECIPIENT
        elif settings.dry_run:
            outcome = DRY_RUN
        elif channel == "mail":
            outcome = await _send_mail(db, target, contract_id, subject, text, settings)
        else:
            outcome = await _ring(db, target, ctx, subject, text)
        await _log(
            db,
            [i.row_id for i in items],
            {
                "on": today.isoformat(),
                "mode": settings.mode,
                "to": target.kind,
                "channel": channel if target.kind != "none" else None,
                "address": target.address,
                "cc": target.cc,
                "user_id": target.user_id,
                "why": target.why,
                "codes": [i.defect.code for i in items],
                "subject": subject,
                "text": text,
                "outcome": outcome,
            },
        )
        counts["messages"] += 1
        counts["items"] += len(items)
        if outcome == NO_RECIPIENT:
            counts["no_recipient"] += 1
        elif outcome in ("failed", "blocked"):
            counts["failed"] += 1
    return counts


async def run(
    db: AsyncSession,
    today: date,
    *,
    months: Optional[list[str]] = None,
    settings: Optional[Settings] = None,
    client_ids: Optional[set[int]] = None,
) -> dict[str, Any]:
    """Automat: wady miesięcy, stan wierszy i komunikaty z terminem na dziś.

    ``months``/``settings``/``client_ids`` podaje pomiar na kopii produkcji;
    automat bierze ``months_for(today)``, zapis z bazy i klientów z regułami."""

    settings = settings or await load(db)
    if not settings.active:
        return {"status": "disabled"}
    if not await module_settings.is_enabled(db):
        return {"status": "module_disabled"}
    out: dict[str, Any] = {"status": "done", "mode": settings.mode, "months": {}}
    for month in months or months_for(today):
        covered = (
            client_ids
            if client_ids is not None
            else await reminders.automatic_clients(db, month)
        )
        settlements, counts = await sync_month(db, month, today, client_ids=covered)
        await db.commit()
        counts.update(await deliver_month(db, settlements, month, today, settings))
        out["months"][month] = counts
    return out


# ── Odczyt (Finanse, powtórka próby) ───────────────────────────────────────


async def report(
    db: AsyncSession,
    months: list[str],
    *,
    client_id: Optional[int] = None,
    open_only: bool = False,
) -> list[dict[str, Any]]:
    """Wady miesięcy z dziennikiem „wysłałbym / wysłałem: komu, co, kiedy”."""

    stmt = (
        select(
            ClientSettlementFeedback,
            Client.name,
            func.nullif(func.concat_ws(" ", Candidate.name, Candidate.lastname), ""),
        )
        .join(Contract, Contract.id == ClientSettlementFeedback.contract_id)
        .outerjoin(Client, Client.id == ClientSettlementFeedback.client_id)
        .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
        .where(ClientSettlementFeedback.period_month.in_(months))
        .order_by(
            ClientSettlementFeedback.period_month,
            Client.name,
            ClientSettlementFeedback.contract_id,
            ClientSettlementFeedback.id,
        )
    )
    if client_id is not None:
        stmt = stmt.where(ClientSettlementFeedback.client_id == client_id)
    if open_only:
        stmt = stmt.where(ClientSettlementFeedback.resolved_on.is_(None))
    out = []
    for row, client_name, person in (await db.execute(stmt)).all():
        defect = BY_CODE.get(row.code)
        out.append(
            {
                "id": row.id,
                "contract_id": row.contract_id,
                "client_id": row.client_id,
                "client_name": client_name,
                "person": person,
                "month": row.period_month,
                "code": row.code,
                "title": defect.title if defect else row.code,
                "audience": row.audience,
                "detail": row.detail,
                "first_seen_on": row.first_seen_on.isoformat(),
                "last_seen_on": row.last_seen_on.isoformat(),
                "resolved_on": row.resolved_on.isoformat() if row.resolved_on else None,
                "last_sent_on": row.last_sent_on.isoformat()
                if row.last_sent_on
                else None,
                "send_count": row.send_count,
                "sends": list(row.sends or []),
            }
        )
    return out


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Liczby do powtórki próby: wady, komunikaty i adresaci (per miesiąc)."""

    messages: set[tuple[Any, ...]] = set()
    to: dict[str, int] = defaultdict(int)
    for row in rows:
        for entry in row["sends"]:
            key = (row["contract_id"], row["month"], entry.get("on"), entry.get("to"))
            if key in messages:
                continue
            messages.add(key)
            to[str(entry.get("to"))] += 1
    return {
        "defects": len(rows),
        "open": sum(1 for r in rows if r["resolved_on"] is None),
        "resolved": sum(1 for r in rows if r["resolved_on"] is not None),
        "messages": len(messages),
        "messages_to": dict(sorted(to.items())),
    }
