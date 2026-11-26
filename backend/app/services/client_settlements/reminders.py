"""Przypomnienia o brakującym raporcie godzin (RCP) za miesiąc.

Rekomendacja 4 z makiet panelu Finansów (23.11.2026): w powtórce października
52 kontrakty nie miały raportu w poczcie rozliczeń, a Finanse nie miały akcji
„przypomnij”. Reguły: ``docs/claude/finanse-insights/rozliczenia-przypomnienia-o-raporcie.md``.

* **Brak raportu** = kontrakt, który trwał w miesiącu, bez rozliczenia i bez
  pliku raportu (status ``missing`` z ``service.month_view``; przy estymacji
  liczą się tylko pliki od pierwszego dnia następnego miesiąca).
* **Konsultant** dostaje mail wyłącznie przez ``portal_mail.send`` i tylko wtedy,
  gdy panel jest dla jego kontraktu otwarty (``pilot`` albo ``all``
  z aktywacją). ``internal`` („Tylko zespół”) i ``off`` = do konsultanta nic.
  Przy szablonie ``client_report`` raport przysyła klient, więc konsultant też
  nic nie dostaje.
* **Opiekun**: ``contracts.care_owner_user_id``, potem
  ``clients.default_care_owner_user_id``, potem Delivery Lead klienta
  (``delivery_lead_client_assignments``, najpierw ``is_head``, jak
  ``departure_care``). Tylko aktywne konta. Bez nikogo = „bez adresata”: wiersz
  zostaje na liście Finansów, nic nie znika po cichu.
* **Harmonogram**: 3., 5. i 7. dzień roboczy miesiąca po rozliczanym
  (``business_today``). 3.: konsultant; 5.: konsultant z opiekunem w kopii;
  7.: dzwonek opiekuna z listą jego brakujących raportów.
* **Bez powtórek**: każdy krok zapisuje wiersz ``client_settlement_reminders``
  PRZED wysyłką (unikat kontrakt, miesiąc, kanał, dzień), więc drugi przebieg
  tego samego dnia — restart, przycisk Finansów po automacie — nic nie wysyła.
* **Domyślnie wyłączone**: ``app_settings['client_settlement_reminders']``,
  przełącznik w karcie „Start rozliczeń” (admin). Wyłączone = ani automat, ani
  przycisk; podgląd działa.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.scheduling import business_today
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_settlement import ClientSettlement, ClientSettlementRuleSet
from app.models.client_settlement_reminder import ClientSettlementReminder
from app.models.consultant_panel import ClientSettlementRule
from app.models.consultant_portal import CpDocument
from app.models.contract import Contract
from app.models.contract_care import CLIENTS_CARE, CONTRACTS_CARE
from app.models.notification import NotificationType
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User
from app.services.client_order_lines import format_period_month, month_bounds
from app.services.client_settlements import settings as module_settings
from app.services.client_settlements.service import (
    WORKING_CONTRACT_STATUSES,
    SettlementError,
    estimate_allowed,
    month_end,
    rules_for,
)
from app.services.care.announcement_mail import MailOutcome
from app.services.consultant_portal import portal_mail, portal_settings
from app.services.dl_alerts import client_not_deleted_clause
from app.services.hr.payroll_periods import add_months
from app.services.person_workdays import business_days

logger = logging.getLogger(__name__)

SETTING_KEY = "client_settlement_reminders"
DISABLED_DETAIL = (
    "Przypomnienia o raportach są wyłączone. Włącza je administrator w karcie "
    "„Start rozliczeń”."
)
#: Dzień roboczy miesiąca po rozliczanym → krok.
STEP_BY_DAY: dict[int, str] = {3: "day3", 5: "day5", 7: "day7"}
#: Kroki, w których mail idzie do konsultanta; w ``day5`` opiekun jest w kopii.
CONSULTANT_STEPS = ("day3", "day5")
CC_STEPS = ("day5", "manual")
#: Ile nazwisk mieści dzwonek opiekuna, zanim przejdzie w „i N innych”.
BELL_NAMES = 5

# Dlaczego konsultant nie dostaje maila (``consultant.reason``).
REASON_OK = "ok"
REASON_PORTAL_CLOSED = "portal_closed"
REASON_NO_PANEL = "no_panel"
REASON_CLIENT_REPORT = "client_report"
REASON_NO_EMAIL = "no_email"
REASON_NO_ADDRESS = "no_settlements_address"


# ── Przełącznik ─────────────────────────────────────────────────────────────


def normalize(raw: object) -> dict[str, Any]:
    return {"enabled": isinstance(raw, dict) and raw.get("enabled") is True}


async def is_enabled(db: AsyncSession) -> bool:
    raw = await db.scalar(select(AppSetting.value).where(AppSetting.key == SETTING_KEY))
    return bool(normalize(raw)["enabled"])


async def set_enabled(
    db: AsyncSession, enabled: bool, *, actor: User
) -> dict[str, Any]:
    """Zapis przełącznika (bez commita)."""

    value = {"enabled": bool(enabled)}
    statement = insert(AppSetting).values(
        key=SETTING_KEY, value=value, updated_by=actor.id
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": statement.excluded.value, "updated_by": actor.id},
        )
    )
    return value


# ── Harmonogram ─────────────────────────────────────────────────────────────


def business_day_number(day: date) -> Optional[int]:
    """Który to dzień roboczy miesiąca (od 1); ``None`` w weekend i święto."""

    first = day.replace(day=1)
    days = business_days(first, day)
    return len(days) if days and days[-1] == day else None


def step_for(day: date) -> Optional[str]:
    number = business_day_number(day)
    return STEP_BY_DAY.get(number) if number is not None else None


def _shift(year: int, month: int, delta: int) -> str:
    year, month = add_months(year, month, delta)
    return f"{year}-{month:02d}"


def period_for(day: date) -> str:
    """Miesiąc rozliczany w danym dniu: poprzedni kalendarzowo."""

    return _shift(day.year, day.month, -1)


def schedule(month: str) -> dict[str, str]:
    """Daty kroków dla rozliczanego ``month`` (dni robocze miesiąca po nim)."""

    year, mon = (int(x) for x in month.split("-"))
    first, last = month_bounds(_shift(year, mon, 1))
    days = business_days(first, last)
    return {
        step: days[number - 1].isoformat()
        for number, step in STEP_BY_DAY.items()
        if len(days) >= number
    }


# ── Treść ───────────────────────────────────────────────────────────────────


def settlements_address() -> Optional[str]:
    """Adres, na który konsultant przysyła raport (pierwszy adres rozliczeń)."""

    for raw in (
        settings.CONSULTANT_PORTAL_SETTLEMENTS_ADDRESSES,
        settings.CONSULTANT_PORTAL_SETTLEMENTS_MAILBOX,
    ):
        for part in (raw or "").split(","):
            if part.strip():
                return part.strip()
    return None


#: Reguła klienta, przy której raportem jest zdanie konsultanta w mailu (mLeasing).
DECLARATION_RULE = "report.consultant_declaration"
#: Godziny z raportu klienta (Nordea, T4T): brak RCP konsultanta nie jest brakiem
#: (jak w „Przebiegu miesiąca”, ``month_close.T4T_RULE``).
CLIENT_HOURS_RULE = "report.time_for_teams"
#: Miesiąc w miejscowniku do przykładu deklaracji („We wrześniu nie miałam…”).
IN_MONTH = (
    "W styczniu",
    "W lutym",
    "W marcu",
    "W kwietniu",
    "W maju",
    "W czerwcu",
    "W lipcu",
    "W sierpniu",
    "We wrześniu",
    "W październiku",
    "W listopadzie",
    "W grudniu",
)


def compose(
    month: str, client_name: str, address: str, *, declaration: bool = False
) -> tuple[str, str]:
    """Temat i treść maila do konsultanta (bez nazwisk i kwot).

    ``declaration``: klient z regułą deklaracji (powtórka 7 próby IX–X: mLeasing
    438 X dostałby prośbę o plik RCP z akceptacją klienta, którego tam nie ma)."""

    label = format_period_month(month)
    if declaration:
        name = IN_MONTH[int(month[5:7]) - 1]
        return (
            f"Deklaracja dni pracy za {label}: prosimy o przesłanie",
            "Dzień dobry,\n\n"
            f"nie mamy jeszcze Twojej deklaracji dni pracy za {label} u klienta "
            f"{client_name}. Bez niej nie rozliczymy miesiąca ani Twojej faktury.\n\n"
            f"Napisz, proszę, z adresu firmowego na {address} (najlepiej w mailu "
            "z fakturą) jedno zdanie z nazwą miesiąca, np.:\n"
            f"- „{name} nie miałam/em dni wolnych”,\n"
            f"- „{name} miałam/em 2 dni wolnego”.\n\n"
            "Jeśli deklarację już wysłałeś(-aś), zignoruj tę wiadomość.\n\n"
            "Pozdrawiamy\n"
            "Zespół rozliczeń B2Bnetwork",
        )
    subject = f"Raport godzin za {label}: prosimy o przesłanie"
    text = (
        "Dzień dobry,\n\n"
        f"nie mamy jeszcze Twojego raportu godzin (RCP) za {label} "
        f"u klienta {client_name}. Bez niego nie rozliczymy miesiąca "
        "ani Twojej faktury.\n\n"
        f"Prześlij go, proszę, na adres {address}:\n"
        "- raport z akceptacją klienta (podpis albo mail akceptujący od klienta),\n"
        "- jako plik (PDF albo Excel), nie zrzut ekranu,\n"
        "- z adresu firmowego.\n\n"
        "Jeśli raport już wysłałeś(-aś), zignoruj tę wiadomość.\n\n"
        "Pozdrawiamy\n"
        "Zespół rozliczeń B2Bnetwork"
    )
    return subject, text


def bell_text(
    month: str, client_name: str, people: list[str], *, declaration: bool = False
) -> tuple[str, str]:
    """Tytuł i opis dzwonka opiekuna."""

    label = format_period_month(month)
    shown = ", ".join(people[:BELL_NAMES])
    more = len(people) - BELL_NAMES
    if more > 0:
        shown += f" i {more} {'inna osoba' if more == 1 else 'innych'}"
    title = f"Brak raportu godzin za {label}: {client_name} ({len(people)})"
    if declaration:
        message = (
            f"Nie mamy deklaracji dni pracy za {label} od: {shown}. Poproś o zdanie "
            "z nazwą miesiąca i liczbą dni wolnych w mailu na adres rozliczeń."
        )
        return title, message
    message = (
        f"Nie mamy RCP za {label} od: {shown}. Poproś o raport z akceptacją "
        f"klienta, jako plik, na adres rozliczeń."
    )
    return title, message


# ── Kto nie przysłał i do kogo pisać ───────────────────────────────────────


@dataclass(frozen=True)
class Owner:
    user_id: int
    name: str
    email: Optional[str]
    #: ``contract_care``, ``client_care`` albo ``client_dl``.
    source: str


@dataclass(frozen=True)
class Missing:
    contract_id: int
    client_id: int
    client_name: str
    person: str
    consultant_email: Optional[str]
    consultant_reason: str
    owner: Optional[Owner]
    #: Klient z regułą deklaracji: raportem jest zdanie w mailu, nie plik RCP.
    declaration: bool = False

    @property
    def mail_allowed(self) -> bool:
        return self.consultant_reason == REASON_OK and self.consultant_email is not None

    @property
    def has_recipient(self) -> bool:
        return self.mail_allowed or self.owner is not None


def consultant_reason(
    state: portal_settings.PortalSettings,
    *,
    contract_id: int,
    mode: Optional[str],
    email: Optional[str],
    address: Optional[str],
) -> str:
    """Czy mail do konsultanta wolno wysłać; kolejność = najmocniejszy powód."""

    if mode == "client_report":
        return REASON_CLIENT_REPORT
    if not state.is_on:
        return REASON_PORTAL_CLOSED
    if not state.open_for(contract_id):
        return REASON_NO_PANEL
    if not (email or "").strip():
        return REASON_NO_EMAIL
    if address is None:
        return REASON_NO_ADDRESS
    return REASON_OK


_FULL_NAME = func.nullif(func.concat_ws(" ", Candidate.name, Candidate.lastname), "")
#: Kolumny opieki nie są polami modeli, a tabela ``contracts`` jest już w FROM.
_CONTRACTS_CARE = CONTRACTS_CARE.alias("contracts_care")
_CLIENTS_CARE = CLIENTS_CARE.alias("clients_care")


async def _client_leads(db: AsyncSession, client_ids: set[int]) -> dict[int, int]:
    """Delivery Lead klienta: aktywne konto, najpierw ``is_head``."""

    if not client_ids:
        return {}
    rows = await db.execute(
        select(
            DeliveryLeadClientAssignment.client_id,
            DeliveryLeadClientAssignment.delivery_lead_user_id,
        )
        .join(User, User.id == DeliveryLeadClientAssignment.delivery_lead_user_id)
        .where(
            DeliveryLeadClientAssignment.client_id.in_(client_ids),
            User.is_active.is_(True),
        )
        .order_by(
            DeliveryLeadClientAssignment.is_head.desc(),
            DeliveryLeadClientAssignment.id,
        )
    )
    leads: dict[int, int] = {}
    for client_id, user_id in rows.all():
        leads.setdefault(client_id, user_id)
    return leads


async def client_hours_clients(
    db: AsyncSession, client_ids: set[int], month: str
) -> set[int]:
    """Klienci rozliczani z raportu klienta (reguła T4T, Nordea): konsultant nie
    przysyła RCP, więc jego brak nie jest brakiem (jak w „Przebiegu miesiąca”).

    Powtórka 7 próby IX–X (24.11.2026): bez tego Nordea dawała 282–286
    „braków RCP” na miesiąc i dzwonek DL-a o każdej z tych osób."""

    out = set()
    for cid in client_ids:
        rules = await rules_for(db, cid, month)
        if rules[CLIENT_HOURS_RULE]["level"] != "off":
            out.add(cid)
    return out


async def _active_users(db: AsyncSession, ids: set[int]) -> dict[int, User]:
    if not ids:
        return {}
    users = await db.scalars(
        select(User).where(User.id.in_(ids), User.is_active.is_(True))
    )
    return {user.id: user for user in users.all()}


def pick_owner(
    *,
    contract_owner: Optional[int],
    client_owner: Optional[int],
    client_lead: Optional[int],
    users: dict[int, User],
) -> Optional[Owner]:
    """Opiekun kontraktu, potem opiekun domyślny klienta, potem DL klienta."""

    for user_id, source in (
        (contract_owner, "contract_care"),
        (client_owner, "client_care"),
        (client_lead, "client_dl"),
    ):
        user = users.get(user_id) if user_id is not None else None
        if user is not None:
            return Owner(
                user_id=user.id,
                name=user.name or user.email,
                email=user.email,
                source=source,
            )
    return None


#: Ile ostatnich nadawców dokumentów kontraktu sprawdzamy przy szukaniu adresu konsultanta.
_ADDRESS_SENDERS = 5


async def consultant_addresses(
    db: AsyncSession, contract_ids: set[int], *, today: date
) -> dict[int, str]:
    """Adres, z którego konsultant sam przysyła dokumenty kontraktu.

    Decyzja Artura z 26.11.2026: komunikaty do konsultanta idą tam, skąd on pisze
    do rozliczeń (zwykle alias firmowy), a nie na adres prywatny z kartoteki;
    ``contracts.candidate_email`` jest prawie wszędzie pusty. Bierzemy najnowszego
    nadawcę dokumentu z poczty, którego czytnik poczty rozpoznaje jako tego
    konsultanta (``identity.sender_contract_ids``), więc kierownik u klienta albo
    koordynator nie zostaną adresatem. Bez takiego dokumentu — brak wpisu (wtedy
    adres z kontraktu, potem z kartoteki, jak dotąd)."""

    from app.services.consultant_portal import identity

    if not contract_ids:
        return {}
    rows = (
        await db.execute(
            select(
                CpDocument.contract_id,
                CpDocument.sender_email,
                func.max(CpDocument.created_at).label("last"),
            )
            .where(
                CpDocument.contract_id.in_(contract_ids),
                CpDocument.channel == "mailbox",
                CpDocument.sender_email.is_not(None),
            )
            .group_by(CpDocument.contract_id, CpDocument.sender_email)
            .order_by(CpDocument.contract_id, func.max(CpDocument.created_at).desc())
        )
    ).all()
    by_contract: dict[int, list[str]] = defaultdict(list)
    for contract_id, sender, _last in rows:
        address = identity.normalize_email(sender)
        if address and len(by_contract[contract_id]) < _ADDRESS_SENDERS:
            by_contract[contract_id].append(address)
    found: dict[int, str] = {}
    for contract_id, senders in by_contract.items():
        for address in senders:
            if contract_id in await identity.sender_contract_ids(
                db, address, today=today
            ):
                found[contract_id] = address
                break
    return found


async def missing_reports(
    db: AsyncSession, month: str, *, client_id: Optional[int] = None
) -> list[Missing]:
    """Kontrakty bez raportu za ``month`` z adresatami, posortowane po kliencie."""

    first, last = month_bounds(month)
    year, mon = (int(x) for x in month.split("-"))
    settled = select(ClientSettlement.contract_id).where(
        ClientSettlement.period_month == month, ClientSettlement.kind == "actual"
    )
    stmt = (
        select(
            Contract.id,
            Contract.client_id,
            Contract.candidate_email,
            _FULL_NAME,
            Client.name,
            _CONTRACTS_CARE.c.care_owner_user_id,
            _CLIENTS_CARE.c.default_care_owner_user_id,
        )
        .join(Client, Client.id == Contract.client_id)
        .join(_CONTRACTS_CARE, _CONTRACTS_CARE.c.id == Contract.id)
        .join(_CLIENTS_CARE, _CLIENTS_CARE.c.id == Contract.client_id)
        .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
        .where(
            Contract.status.in_(WORKING_CONTRACT_STATUSES),
            or_(Contract.start_date.is_(None), Contract.start_date <= last),
            or_(Contract.end_date.is_(None), Contract.end_date >= first),
            Contract.id.not_in(settled),
            client_not_deleted_clause(Contract.client_id),
        )
        .order_by(Client.name, Candidate.lastname, Candidate.name, Contract.id)
    )
    if client_id is not None:
        stmt = stmt.where(Contract.client_id == client_id)
    rows = (await db.execute(stmt)).all()
    if not rows:
        return []
    ids = [row[0] for row in rows]
    reports: dict[int, list[datetime]] = defaultdict(list)
    for contract_id, created_at in (
        await db.execute(
            select(CpDocument.contract_id, CpDocument.created_at).where(
                CpDocument.contract_id.in_(ids),
                CpDocument.kind == "report",
                CpDocument.period_year == year,
                CpDocument.period_month == mon,
                CpDocument.status != "rejected",
            )
        )
    ).all():
        reports[contract_id].append(created_at)
    client_ids = {row[1] for row in rows}
    # Przy estymacji (E5.3) pliki sprzed końca miesiąca to plan, nie RCP.
    estimating = {
        cid
        for cid in client_ids
        if any(reports.get(r[0]) for r in rows if r[1] == cid)
        and await estimate_allowed(db, cid, month)
    }
    end = month_end(month)
    modes = dict(
        (
            await db.execute(
                select(ClientSettlementRule.client_id, ClientSettlementRule.mode).where(
                    ClientSettlementRule.client_id.in_(client_ids)
                )
            )
        ).all()
    )
    leads = await _client_leads(db, client_ids)
    declaring = {
        cid
        for cid in client_ids
        if (await rules_for(db, cid, month))[DECLARATION_RULE]["level"] != "off"
    }
    users = await _active_users(
        db,
        {uid for row in rows for uid in (row[5], row[6]) if uid is not None}
        | set(leads.values()),
    )
    state = await portal_settings.load(db)
    address = settlements_address()
    from_client = await client_hours_clients(db, client_ids, month)
    written = await consultant_addresses(db, set(ids), today=business_today())
    out: list[Missing] = []
    for contract_id, cid, email, name, client_name, own, default_own in rows:
        if cid in from_client:
            continue
        email = written.get(contract_id) or email
        files = reports.get(contract_id, [])
        if cid in estimating:
            files = [at for at in files if at >= end]
        if files:
            continue
        reason = consultant_reason(
            state,
            contract_id=contract_id,
            mode=modes.get(cid),
            email=email,
            address=address,
        )
        out.append(
            Missing(
                contract_id=contract_id,
                client_id=cid,
                client_name=client_name,
                person=name or f"Kontrakt {contract_id}",
                consultant_email=(
                    ((email or "").strip() or None) if reason == REASON_OK else None
                ),
                consultant_reason=reason,
                owner=pick_owner(
                    contract_owner=own,
                    client_owner=default_own,
                    client_lead=leads.get(cid),
                    users=users,
                ),
                declaration=cid in declaring,
            )
        )
    return out


# ── Dziennik ────────────────────────────────────────────────────────────────


async def _reserve(
    db: AsyncSession,
    item: Missing,
    month: str,
    *,
    channel: str,
    step: str,
    today: date,
    actor: Optional[User],
) -> Optional[int]:
    """Wiersz dziennika przed wysyłką; ``None`` = dziś już było (bez wysyłki).

    Commit od razu: mail, który wyszedł, nie może zależeć od tego, czy reszta
    przebiegu się uda, bo wtedy następny przebieg wysłałby go drugi raz."""

    row_id = await db.scalar(
        insert(ClientSettlementReminder)
        .values(
            contract_id=item.contract_id,
            client_id=item.client_id,
            period_month=month,
            step=step,
            channel=channel,
            owner_user_id=item.owner.user_id if item.owner else None,
            outcome="pending",
            sent_on=today,
            sent_by=actor.id if actor else None,
        )
        .on_conflict_do_nothing(constraint="uq_client_settlement_reminders_day")
        .returning(ClientSettlementReminder.id)
    )
    await db.commit()
    return row_id


async def _finish(db: AsyncSession, row_id: int, outcome: str) -> None:
    reminder = await db.get(ClientSettlementReminder, row_id)
    if reminder is not None:
        reminder.outcome = outcome
    await db.commit()


def outcome_of(result: Optional[MailOutcome]) -> str:
    if result is None:
        return "blocked"
    if result.status == "accepted":
        return "simulated" if result.simulated else "sent"
    return "failed"


async def last_reminders(
    db: AsyncSession, contract_ids: list[int], month: str
) -> dict[int, dict[str, Any]]:
    """Ostatnie przypomnienie każdego kontraktu za miesiąc."""

    if not contract_ids:
        return {}
    rows = await db.scalars(
        select(ClientSettlementReminder)
        .where(
            ClientSettlementReminder.contract_id.in_(contract_ids),
            ClientSettlementReminder.period_month == month,
        )
        .order_by(ClientSettlementReminder.created_at, ClientSettlementReminder.id)
    )
    out: dict[int, dict[str, Any]] = {}
    for row in rows.all():
        out[row.contract_id] = {
            "sent_on": row.sent_on.isoformat(),
            "step": row.step,
            "channel": row.channel,
            "outcome": row.outcome,
        }
    return out


# ── Wysyłka ─────────────────────────────────────────────────────────────────


async def _mail_consultant(
    db: AsyncSession,
    item: Missing,
    month: str,
    *,
    step: str,
    today: date,
    actor: Optional[User],
) -> Optional[str]:
    """Mail do konsultanta; ``None`` = dziś już wysłane."""

    row_id = await _reserve(
        db, item, month, channel="consultant", step=step, today=today, actor=actor
    )
    if row_id is None:
        return None
    address = settlements_address()
    if address is None or item.consultant_email is None:
        await _finish(db, row_id, "blocked")
        return "blocked"
    subject, text = compose(
        month, item.client_name, address, declaration=item.declaration
    )
    cc = item.owner.email if step in CC_STEPS and item.owner else None
    try:
        result = await portal_mail.send(
            db,
            contract_id=item.contract_id,
            to=item.consultant_email,
            subject=subject,
            text=text,
            cc=cc,
        )
    except Exception:  # noqa: BLE001 — jeden zły adres nie zatrzymuje reszty
        logger.exception("settlement_reminders: mail contract=%s", item.contract_id)
        result = MailOutcome("uncertain", "exception")
    outcome = outcome_of(result)
    await _finish(db, row_id, outcome)
    return outcome


async def _bell_owners(
    db: AsyncSession,
    items: list[Missing],
    month: str,
    *,
    step: str,
    today: date,
    actor: Optional[User],
) -> tuple[int, int]:
    """Jeden dzwonek na (opiekun, klient); zwraca (dzwonki, kontrakty już dziś)."""

    from app.services.notification_triggers import emit

    groups: dict[tuple[int, int], list[Missing]] = defaultdict(list)
    for item in items:
        if item.owner is not None:
            groups[(item.owner.user_id, item.client_id)].append(item)
    bells = repeated = 0
    for (owner_id, client_id), group in groups.items():
        reserved: list[tuple[int, Missing]] = []
        for item in group:
            row_id = await _reserve(
                db, item, month, channel="owner", step=step, today=today, actor=actor
            )
            if row_id is None:
                repeated += 1
            else:
                reserved.append((row_id, item))
        if not reserved:
            continue
        title, message = bell_text(
            month,
            group[0].client_name,
            [item.person for _, item in reserved],
            declaration=group[0].declaration,
        )
        row = await emit(
            db,
            user_id=owner_id,
            title=title,
            message=message,
            ntype=NotificationType.settlement_report_missing,
            related_entity_type="client",
            related_entity_id=client_id,
            link=f"/contracts/{reserved[0][1].contract_id}",
        )
        outcome = "sent" if row is not None else "blocked"
        bells += row is not None
        for row_id, _ in reserved:
            await _finish(db, row_id, outcome)
    return bells, repeated


def _empty_counts() -> dict[str, int]:
    return {
        "missing": 0,
        "mails": 0,
        "bells": 0,
        "already_today": 0,
        "without_recipient": 0,
        "failed": 0,
    }


async def automatic_clients(db: AsyncSession, month: str) -> set[int]:
    """Klienci, których obejmuje automat: z regułami rozliczeń od ``month``.

    Na kopii produkcji z 23.11.2026 „Brak RCP” za październik to 498 kontraktów
    u 28 klientów, ale reguły ma jeden klient (9 braków): reszty NEXUS jeszcze
    nie rozlicza, a automat wysłałby dzwonki o setkach kontraktów. Finanse
    włączają klienta, zapisując mu reguły; przycisk działa dla każdego klienta."""

    rows = await db.scalars(
        select(ClientSettlementRuleSet.client_id)
        .where(ClientSettlementRuleSet.effective_from <= month)
        .distinct()
    )
    return set(rows.all())


async def run_step(
    db: AsyncSession, today: date, *, step: Optional[str] = None
) -> dict[str, Any]:
    """Automat: dzisiejszy krok dla miesiąca poprzedniego (klienci z regułami)."""

    if not await module_settings.is_enabled(db) or not await is_enabled(db):
        return {"status": "disabled"}
    step = step or step_for(today)
    if step is None:
        return {"status": "not_today"}
    month = period_for(today)
    covered = await automatic_clients(db, month)
    items = [i for i in await missing_reports(db, month) if i.client_id in covered]
    counts = _empty_counts()
    counts["missing"] = len(items)
    counts["without_recipient"] = sum(1 for i in items if not i.has_recipient)
    if step in CONSULTANT_STEPS:
        for item in items:
            if not item.mail_allowed:
                continue
            outcome = await _mail_consultant(
                db, item, month, step=step, today=today, actor=None
            )
            _count(counts, outcome)
    else:
        bells, repeated = await _bell_owners(
            db, items, month, step=step, today=today, actor=None
        )
        counts["bells"] += bells
        counts["already_today"] += repeated
    await db.commit()
    return {"status": "done", "step": step, "month": month, **counts}


def _count(counts: dict[str, int], outcome: Optional[str]) -> None:
    if outcome is None:
        counts["already_today"] += 1
    elif outcome in ("sent", "simulated"):
        counts["mails"] += 1
    else:
        counts["failed"] += 1


async def send_manual(
    db: AsyncSession, client_id: int, month: str, *, actor: User, today: date
) -> dict[str, Any]:
    """Przycisk „Przypomnij” Finansów: konsultant z opiekunem w kopii, gdy mail
    wolno wysłać; inaczej dzwonek opiekuna. Bez adresata — nic, ale w liczbie."""

    if not await is_enabled(db):
        raise SettlementError(DISABLED_DETAIL, status=409)
    items = await missing_reports(db, month, client_id=client_id)
    counts = _empty_counts()
    counts["missing"] = len(items)
    counts["without_recipient"] = sum(1 for i in items if not i.has_recipient)
    for item in items:
        if item.mail_allowed:
            outcome = await _mail_consultant(
                db, item, month, step="manual", today=today, actor=actor
            )
            _count(counts, outcome)
    bells, repeated = await _bell_owners(
        db,
        [i for i in items if not i.mail_allowed],
        month,
        step="manual",
        today=today,
        actor=actor,
    )
    counts["bells"] += bells
    counts["already_today"] += repeated
    await db.commit()
    return counts


# ── Podgląd dla Finansów (i widoku „Przebieg miesiąca”) ───────────────────


def _row(item: Missing, last: Optional[dict[str, Any]]) -> dict[str, Any]:
    if item.mail_allowed:
        action = "mail"
    elif item.owner is not None:
        action = "bell"
    else:
        action = "none"
    return {
        "contract_id": item.contract_id,
        "person": item.person,
        "action": action,
        "consultant": {
            "reachable": item.mail_allowed,
            "reason": item.consultant_reason,
            "email": item.consultant_email,
        },
        "owner": (
            {
                "user_id": item.owner.user_id,
                "name": item.owner.name,
                "source": item.owner.source,
            }
            if item.owner
            else None
        ),
        "last_reminder": last,
    }


async def overview(
    db: AsyncSession, month: str, *, client_id: Optional[int] = None
) -> dict[str, Any]:
    """Per klient: ilu brakuje, do kogo pójdzie przypomnienie, kiedy ostatnie."""

    items = await missing_reports(db, month, client_id=client_id)
    last = await last_reminders(db, [i.contract_id for i in items], month)
    covered = await automatic_clients(db, month)
    address = settlements_address()
    by_client: dict[int, list[Missing]] = defaultdict(list)
    for item in items:
        by_client[item.client_id].append(item)
    clients = []
    for cid, group in by_client.items():
        rows = [_row(item, last.get(item.contract_id)) for item in group]
        dates = [r["last_reminder"]["sent_on"] for r in rows if r["last_reminder"]]
        subject, text = compose(
            month,
            group[0].client_name,
            address or "—",
            declaration=group[0].declaration,
        )
        clients.append(
            {
                "client_id": cid,
                "client_name": group[0].client_name,
                "missing": len(group),
                # Automat 3./5./7. dnia obejmuje tylko klientów z regułami.
                "automatic": cid in covered,
                "to_consultant": sum(1 for r in rows if r["action"] == "mail"),
                "to_owner": sum(1 for r in rows if r["action"] == "bell"),
                "without_recipient": sum(1 for r in rows if r["action"] == "none"),
                "last_reminder_on": max(dates) if dates else None,
                "mail": {"subject": subject, "text": text},
                "rows": rows,
            }
        )
    return {
        "enabled": await is_enabled(db),
        "portal_state": await portal_settings.load_raw_state(db),
        "month": month,
        "schedule": schedule(month),
        "settlements_address": address,
        "clients": clients,
    }
