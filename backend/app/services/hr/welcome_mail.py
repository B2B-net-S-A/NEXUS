"""Mail powitalny konsultanta (etap 3, O6, karta „Mail powitalny” z makiety M6).

Konsultant nie ma konta w NEXUSIE, więc zamiast zadań w aplikacji dostaje
jeden mail: kiedy i gdzie zaczyna, kto go odbierze, co zabrać, jakie dokumenty
przysłać i kto jest jego opiekunem. Treść składa się z pakietu klienta
(``client_pack``), ale decyzję o wysłaniu podejmuje człowiek: opiekun ogląda
podgląd, może go poprawić i dopiero wtedy wysyła.

* **Przełącznik** ``app_settings['consultant_welcome_mail']`` — domyślnie
  WYŁĄCZONY (brak wiersza = wyłączony). Wyłączony = podgląd działa, wysyłka
  409 z wyjaśnieniem. Włącza go administrator; to wysyłka do ludzi spoza
  firmy, więc pierwszą uruchamia Artur.
* **Nadawca** — skrzynka M365 administracji (``admin_cases.mailbox.m365_mailbox``,
  Reply-To = adres widoczny ``public_address``)
  przez ten sam kanał co komunikaty do konsultantów
  (``care.announcement_mail.default_mailer``, rejestracja „NEXUS Kadry”).
  Tryb z ``HR_M365_MODE``: ``off`` = brak nadawcy (409), ``simulate`` = nic
  nie wychodzi (ślad ``delivery = simulated``), ``live`` = Graph. Odpowiedzi
  konsultanta trafiają do administracja@, a czytnik zamienia je w sprawy.
* **Jeden mail na kontrakt** (``consultant_welcome_mails``): zapis i wysyłka
  w jednej transakcji pod blokadą doradczą — drugi klik dostaje 409,
  odłożona albo odrzucona wysyłka niczego nie zapisuje (502, można ponowić).
  Wynik niepewny (brama Graph odpowiedziała błędem, mail mógł wyjść) zostaje
  zapisany jako ``uncertain`` — bez ponowienia, żeby nie wysłać dwa razy.
* Wysłanie odhacza pozycję ścieżki ``welcome_mail`` w wejściu konsultanta
  (``lifecycle_service.complete_task_by_key``).
* Logi i ślad w audycie bez adresu i treści maila.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional, Protocol, Sequence

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract
from app.models.equipment import ConsultantWelcomeMail
from app.models.user import User
from app.services.admin_cases import mailbox as admin_mailbox
from app.services.care.announcement_audience import valid_email
from app.services.equipment.errors import EquipmentError
from app.services.hr import audit, client_pack
from app.services.hr_lifecycle_schema import KEY_WELCOME_MAIL

logger = logging.getLogger(__name__)

SETTING_KEY = "consultant_welcome_mail"
MAX_SUBJECT = 200
MAX_BODY = 5000

DISABLED_DETAIL = (
    "Wysyłka maili powitalnych jest jeszcze wyłączona — to mail do osoby spoza "
    "firmy, więc włącza ją administrator. Podgląd działa."
)
NO_MAILBOX_DETAIL = (
    "Skrzynka administracja@ nie jest ustawiona, więc mail nie ma nadawcy."
)
SEND_FAILED_DETAIL = "Nie udało się wysłać maila — spróbuj ponownie za chwilę."
NO_TRANSPORT_DETAIL = (
    "Wysyłka ze skrzynki administracja@ nie działa: Microsoft 365 dla „Ludzi” jest "
    "wyłączony albo brak poświadczeń rejestracji. Zgłoś to administratorowi."
)
CONTRACT_NOT_FOUND = "Nie ma takiego kontraktu."

_WEEKDAYS = (
    "w poniedziałek",
    "we wtorek",
    "w środę",
    "w czwartek",
    "w piątek",
    "w sobotę",
    "w niedzielę",
)
_PLACEHOLDER_NAME = "[imię]"
_PLACEHOLDER_START = "[dzień startu]"


@dataclass(frozen=True)
class Issue:
    code: str
    message: str
    #: Blokuje wysyłkę (bez adresu albo daty startu nie ma czego wysłać).
    blocking: bool

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "blocking": self.blocking}


@dataclass(frozen=True)
class Draft:
    recipient_email: Optional[str]
    recipient_name: Optional[str]
    subject: str
    body: str
    issues: tuple[Issue, ...]

    @property
    def blocking(self) -> Optional[Issue]:
        return next((issue for issue in self.issues if issue.blocking), None)


class WelcomeMailSender(Protocol):
    """Nadawca z administracja@ — ten sam co komunikaty do konsultantów
    (``care.announcement_mail``: ``GraphMailer`` albo ``SimulatedMailer``).

    Wynik ma ``status`` (``accepted``, ``deferred``, ``failed``, ``uncertain``)
    i ``simulated``; testy podają fałszywego nadawcę o tym kształcie."""

    async def send(self, *, to: str, subject: str, text: str) -> Any: ...


def default_sender() -> Optional[WelcomeMailSender]:
    """Zależność trasy: nadawca według ``HR_M365_MODE`` (``off`` = ``None``,
    ``simulate`` = nic nie wychodzi, ``live`` = Graph). Testy ją podmieniają."""
    from app.services.care import announcement_mail

    return announcement_mail.default_mailer()


# ── Przełącznik ──────────────────────────────────────────────────────────────


async def is_enabled(db: AsyncSession) -> bool:
    raw = await db.scalar(select(AppSetting.value).where(AppSetting.key == SETTING_KEY))
    return isinstance(raw, dict) and raw.get("enabled") is True


async def set_enabled(db: AsyncSession, enabled: bool, *, actor: User) -> bool:
    row = await db.get(AppSetting, SETTING_KEY)
    if row is None:
        db.add(
            AppSetting(key=SETTING_KEY, value={"enabled": enabled}, updated_by=actor.id)
        )
    else:
        row.value = {"enabled": enabled}
        row.updated_by = actor.id
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=None,
        entity_type="app_setting",
        entity_id=SETTING_KEY,
        action="welcome_mail_switch",
        details={"enabled": enabled},
    )
    await db.flush()
    return enabled


# ── Treść ────────────────────────────────────────────────────────────────────


def _day_phrase(start: Optional[date]) -> str:
    if start is None:
        return _PLACEHOLDER_START
    return f"{_WEEKDAYS[start.weekday()]} {start:%d.%m}"


def _clock(value: Optional[str]) -> Optional[str]:
    """„09:00” → „9:00” (tak, jak się pisze w mailu)."""
    if not value:
        return None
    hours, _, minutes = value.partition(":")
    return f"{int(hours)}:{minutes}" if hours.isdigit() else value


def _document(item: client_pack.PackItem) -> str:
    return f"{item.name} ({item.note})" if item.note else item.name


def _documents_line(
    prefix: str, items: Sequence[client_pack.PackItem]
) -> Optional[str]:
    if not items:
        return None
    return f"{prefix}: " + "; ".join(_document(item) for item in items) + "."


def compose(
    *,
    first_name: Optional[str],
    client_name: str,
    start_date: Optional[date],
    first_day: Optional[client_pack.FirstDay],
    documents: Sequence[client_pack.PackItem],
    owner_name: Optional[str],
    owner_email: Optional[str],
) -> tuple[str, str]:
    """Temat i treść maila z danych kontraktu i pakietu (czysta funkcja)."""

    place = first_day.place if first_day else None
    clock = _clock(first_day.time if first_day else None)
    start = _day_phrase(start_date)
    opening = f"{start}{f' o {clock}' if clock else ''} zaczynasz w {client_name}"
    opening += f" ({place})." if place else "."
    lines = [f"Cześć {first_name}," if first_name else "Dzień dobry,", "", opening]
    if first_day and first_day.contact_name:
        lines.append(f"Odbierze Cię {first_day.contact_name}.")
    if first_day and first_day.bring:
        lines.append(f"Zabierz ze sobą: {first_day.bring}.")
    before = [d for d in documents if (d.offset_days or 0) < 0]
    on_day = [d for d in documents if (d.offset_days or 0) == 0]
    after = [d for d in documents if (d.offset_days or 0) > 0]
    for line in (
        _documents_line("Przed startem prześlij", before),
        _documents_line("W dniu startu", on_day),
        _documents_line("W pierwszych dniach po starcie", after),
    ):
        if line:
            lines.append(line)
    if owner_name:
        lines += [
            "",
            "Opiekuję się Twoją współpracą po naszej stronie — napisz albo "
            "zadzwoń w każdej sprawie.",
            "",
            "Pozdrawiam,",
            owner_name,
        ]
        if owner_email:
            lines.append(owner_email)
    else:
        lines += ["", "W razie pytań odpisz na tę wiadomość.", "", "Pozdrawiamy"]
    when = f"{start_date:%d.%m.%Y}" if start_date else _PLACEHOLDER_START
    subject = f"Twój start w {client_name} — {when}"
    return subject[:MAX_SUBJECT], "\n".join(lines)


async def _owner(db: AsyncSession, contract_id: int) -> Optional[User]:
    from app.services.care import access as care_access

    contracts = await care_access.contracts_by_id(db, [contract_id])
    if contract_id not in contracts:
        return None
    owners = await care_access.effective_owners(db, [contracts[contract_id]])
    user_id = owners[contract_id].user_id
    return await db.get(User, user_id) if user_id else None


async def draft_for(db: AsyncSession, contract_id: int) -> Draft:
    """Podgląd maila dla kontraktu z listą braków (blokujących i nie)."""

    contract = await db.get(Contract, contract_id)
    if contract is None:
        raise EquipmentError(CONTRACT_NOT_FOUND, status=404)
    candidate = (
        await db.get(Candidate, contract.candidate_id)
        if contract.candidate_id
        else None
    )
    client = await db.get(Client, contract.client_id) if contract.client_id else None
    pack = (
        await client_pack.load_pack(db, contract.client_id)
        if contract.client_id
        else None
    )
    first_day = await client_pack.first_day(db, contract_id)
    owner = await _owner(db, contract_id)
    email = (
        contract.candidate_email or (candidate.email if candidate else None) or ""
    ).strip()
    issues: list[Issue] = []
    if not email:
        issues.append(
            Issue(
                "no_email", "Kontrakt i profil kandydata nie mają adresu e-mail.", True
            )
        )
    elif valid_email(email) is None:
        issues.append(
            Issue(
                "bad_email",
                "Adres e-mail konsultanta jest niepoprawny — popraw go w kontrakcie "
                "albo w profilu kandydata.",
                True,
            )
        )
    if contract.start_date is None:
        issues.append(Issue("no_start", "Kontrakt nie ma daty startu.", True))
    if pack is None or not pack.exists:
        issues.append(
            Issue(
                "no_pack",
                "Klient nie ma pakietu „Wejście u klienta” — mail ma tylko datę startu.",
                False,
            )
        )
    elif first_day is None or not first_day.contact_name:
        issues.append(
            Issue(
                "no_contact",
                "Nie wiadomo, kto odbiera konsultanta — wskaż menedżera w kontrakcie "
                "albo osobę w pakiecie klienta.",
                False,
            )
        )
    if owner is None:
        issues.append(
            Issue("no_owner", "Kontrakt nie ma opiekuna — mail nie ma podpisu.", False)
        )
    first_name = (candidate.name or "").strip() if candidate else ""
    subject, body = compose(
        first_name=first_name or None,
        client_name=client.name if client else "kliencie",
        start_date=contract.start_date,
        first_day=first_day,
        documents=pack.documents if pack else (),
        owner_name=owner.name if owner else None,
        owner_email=owner.email if owner else None,
    )
    name = (
        " ".join(p for p in (candidate.name, candidate.lastname) if p)
        if candidate
        else None
    )
    return Draft(
        recipient_email=email or None,
        recipient_name=name or None,
        subject=subject,
        body=body,
        issues=tuple(issues),
    )


async def client_preview(db: AsyncSession, client_id: int) -> tuple[str, str]:
    """Podgląd z pakietu klienta (zakładka „Wejście u klienta”) — bez kontraktu,
    z polami w nawiasach zamiast imienia i dnia startu."""

    client = await db.get(Client, client_id)
    if client is None:
        raise EquipmentError("Nie ma takiego klienta.", status=404)
    pack = await client_pack.load_pack(db, client_id)
    contact_name = None
    if pack.first_day_contact_id:
        from app.models.contact import Contact

        contact = await db.get(Contact, pack.first_day_contact_id)
        contact_name = contact.name if contact else None
    first_day = client_pack.FirstDay(
        contact_id=pack.first_day_contact_id,
        contact_name=(
            f"menedżer z kontraktu (zapasowo: {contact_name})"
            if contact_name
            else "menedżer z kontraktu"
        ),
        place=pack.first_day_place,
        time=pack.first_day_time,
        bring=pack.first_day_bring,
    )
    return compose(
        first_name=_PLACEHOLDER_NAME,
        client_name=client.name,
        start_date=None,
        first_day=first_day,
        documents=pack.documents,
        owner_name="[opiekun]",
        owner_email=None,
    )


async def sent_for(
    db: AsyncSession, contract_id: int
) -> Optional[ConsultantWelcomeMail]:
    # Po scaleniu duplikatów kontraktu bywa kilka śladów — liczy się pierwszy.
    return await db.scalar(
        select(ConsultantWelcomeMail)
        .where(ConsultantWelcomeMail.contract_id == contract_id)
        .order_by(ConsultantWelcomeMail.sent_at, ConsultantWelcomeMail.id)
        .limit(1)
    )


def _clean_subject(value: str) -> str:
    subject = " ".join((value or "").split())
    if not subject:
        raise EquipmentError("Wpisz temat maila.")
    if len(subject) > MAX_SUBJECT:
        raise EquipmentError(f"Temat może mieć najwyżej {MAX_SUBJECT} znaków.")
    return subject


def _clean_body(value: str) -> str:
    body = "\n".join(line.rstrip() for line in (value or "").strip().splitlines())
    if not body:
        raise EquipmentError("Treść maila jest pusta.")
    if len(body) > MAX_BODY:
        raise EquipmentError(f"Treść może mieć najwyżej {MAX_BODY} znaków.")
    return body


async def send(
    db: AsyncSession,
    contract_id: int,
    *,
    subject: str,
    body: str,
    actor: User,
    sender: Optional[WelcomeMailSender],
) -> ConsultantWelcomeMail:
    """Wysyła mail (treść po poprawkach opiekuna) i zapisuje ślad."""

    if not await is_enabled(db):
        raise EquipmentError(DISABLED_DETAIL, status=409)
    if admin_mailbox.m365_mailbox() is None:
        raise EquipmentError(NO_MAILBOX_DETAIL, status=409)
    if sender is None:
        raise EquipmentError(NO_TRANSPORT_DETAIL, status=409)
    clean_subject = _clean_subject(subject)
    clean_body = _clean_body(body)
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext('consultant_welcome_mail'), :id)"),
        {"id": contract_id},
    )
    previous = await sent_for(db, contract_id)
    if previous is not None:
        raise EquipmentError(
            f"Mail powitalny wysłano już {previous.sent_at:%d.%m.%Y}.", status=409
        )
    draft = await draft_for(db, contract_id)
    if draft.blocking is not None or not draft.recipient_email:
        raise EquipmentError(
            draft.blocking.message if draft.blocking else "Brak adresu e-mail."
        )
    # Ślad trafia do bazy PRZED wysyłką (stan „uncertain”): awaria po wysłaniu
    # (zadanie z listy, audyt, commit trasy) nie może go cofnąć, bo kolejne
    # „Wyślij” poszłoby drugi raz do konsultanta (audyt 19.10.2026; tak samo
    # kolejka komunikatów). Mail na pewno niewysłany = ślad usunięty.
    row = ConsultantWelcomeMail(
        contract_id=contract_id,
        recipient_email=draft.recipient_email,
        subject=clean_subject,
        body=clean_body,
        sent_by=actor.id,
        delivery="uncertain",
    )
    db.add(row)
    await db.commit()
    outcome = await sender.send(
        to=draft.recipient_email, subject=clean_subject, text=clean_body
    )
    status = getattr(outcome, "status", None)
    if status not in ("accepted", "uncertain"):
        # Odłożona albo odrzucona: mail na pewno nie wyszedł — można ponowić.
        await db.delete(row)
        await db.commit()
        logger.warning(
            "welcome_mail: send not accepted",
            extra={
                "event_kind": "welcome_mail",
                "failure_kind": getattr(outcome, "code", None) or str(status),
            },
        )
        raise EquipmentError(SEND_FAILED_DETAIL, status=502)
    if status == "uncertain":
        row.delivery = "uncertain"
    elif getattr(outcome, "simulated", False):
        row.delivery = "simulated"
    else:
        row.delivery = "sent"
    from app.services.hr.lifecycle_service import complete_task_by_key

    checked = await complete_task_by_key(
        db, contract_id=contract_id, key=KEY_WELCOME_MAIL, actor_id=actor.id
    )
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=None,
        entity_type="contract",
        entity_id=contract_id,
        action="welcome_mail_sent",
        details={
            "welcome_mail_id": row.id,
            "delivery": row.delivery,
            "entry_task_checked": checked,
        },
    )
    await db.flush()
    await db.refresh(row)
    return row


async def tick_entry_task_if_sent(db: AsyncSession, contract_id: int) -> bool:
    """Kontrakt z wysłanym mailem ma odhaczone zadanie „Mail powitalny”.

    Po scaleniu duplikatów kontraktu mail mógł wyjść z kontraktu, którego
    wejście anulowano — zadanie zachowanej listy zamyka się wtedy tutaj
    (jako osoba odhaczenia: ta, która wysłała mail). Nie commituje.
    """

    sent = await sent_for(db, contract_id)
    if sent is None:
        return False
    from app.services.hr.lifecycle_service import complete_task_by_key

    return await complete_task_by_key(
        db, contract_id=contract_id, key=KEY_WELCOME_MAIL, actor_id=sent.sent_by
    )


def sent_payload(
    row: ConsultantWelcomeMail, *, sender_name: Optional[str]
) -> dict[str, Any]:
    return {
        "id": row.id,
        "sent_at": row.sent_at.isoformat() if row.sent_at else None,
        "sent_by": row.sent_by,
        "sent_by_name": sender_name,
        "recipient_email": row.recipient_email,
        "subject": row.subject,
        "body": row.body,
        "delivery": row.delivery,
    }
