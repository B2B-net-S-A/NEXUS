"""Komunikaty do konsultantów — dostęp, przepływ, raport, wypis, odpowiedzi (O12).

Decyzja O12 (Artur 17.10.2026, „idź według rekomendacji”): mail
z administracja@, osobny do każdego, odpowiedzi do Spraw. Powyżej 20 osób
zatwierdza head back office albo admin (nigdy autor — pilnuje też CHECK
w bazie), wysyłka próbna obowiązkowa po każdej zmianie treści, informacyjne
z wypisem. Moduł wchodzi z wyłączoną wysyłką (``app_settings`` bez wiersza);
pierwszą uruchamia Artur.

* **Autor**: opiekunowie (TCM), Delivery Lead u swoich klientów, head back
  office (``structure.load_division_heads()['back_office']``) i admin.
  Komunikat widzi autor, head back office i admin.
* **Przepływ**: szkic → próba do siebie (``tested_version`` = wersja treści)
  → „Wyślij”: lista odbiorców zamraża się (zatwierdzający widzi dokładnie tę
  listę); do 20 osób idzie od razu do kolejki, powyżej — czeka na
  zatwierdzenie → kolejka 30 maili na minutę (``announcement_queue``) → raport.
* **Wyłączona wysyłka**: tworzenie, podgląd i próba do siebie działają (to
  konto wewnętrzne), wysyłka do konsultantów = 409, kolejka stoi.
* **Wypis** z informacyjnych: token z linku (w bazie SHA-256), wypisany
  przestaje dostawać informacyjne; obowiązkowe dostaje dalej.
* **Odpowiedź** z ``[Komunikat <id>/<kod>]`` w temacie: czytnik administracja@
  zakłada sprawę, a ``link_mail_case`` przypina ją do komunikatu i kontraktu
  nadawcy; odbity mail oznacza osobę i daje opiekunowi „popraw e-mail”.

Logi i ślad niosą identyfikatory i liczby — bez adresów i treści.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_case import AdminCase
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.care_announcement import (
    CareAnnouncement,
    CareAnnouncementOptOut,
    CareAnnouncementRecipient,
    CareAnnouncementReply,
)
from app.models.client import Client
from app.models.notification import NotificationType
from app.models.user import User, UserRole
from app.services.care import access as care_access
from app.services.care import announcement_audience as audience_svc
from app.services.care import announcement_mail as mail
from app.services.care.access import full_name
from app.services.care_announcements_schema import (
    BODY_MAX,
    KINDS,
    RECIPIENT_STATUSES,
    SETTING_KEY,
    SUBJECT_MAX,
)
from app.services.hr import audit
from app.services.hr.notify import notify_each
from app.services.section_permissions import (
    ProductSection,
    SectionAccess,
    section_access_for_user,
)

logger = logging.getLogger(__name__)

APPROVAL_THRESHOLD = 20
RATE_PER_MINUTE = 30
RETURN_NOTE_MAX = 500
ENTITY = "care_announcement"

SENDING_OFF = (
    "Wysyłka komunikatów do konsultantów jest wyłączona. Włącza ją administrator "
    "w ustawieniach komunikatów."
)
NO_TRANSPORT = "Wysyłka maili z administracja@ nie jest jeszcze skonfigurowana."
NOT_FOUND = "Nie ma takiego komunikatu."
UNTESTED = (
    "Najpierw wyślij komunikat próbnie do siebie — próba jest potrzebna po każdej "
    "zmianie treści."
)
AUTHOR_DENIED = (
    "Komunikaty do konsultantów piszą opiekunowie, Delivery Lead u swoich klientów, "
    "head back office i administrator."
)
APPROVER_DENIED = (
    f"Komunikat do więcej niż {APPROVAL_THRESHOLD} osób zatwierdza head back office "
    "albo administrator."
)
OWN_APPROVAL = (
    "Komunikatu nie zatwierdza jego autor ani osoba, która wysłała go do zatwierdzenia."
)
EDIT_DENIED = "Komunikat zmienia jego autor albo administrator."


class AnnouncementError(Exception):
    """Odmowa z komunikatem dla użytkownika (status HTTP w ``status``)."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


# ── Dostęp ───────────────────────────────────────────────────────────────────


async def back_office_head_id(db: AsyncSession) -> Optional[int]:
    from app.services.hr.structure import load_division_heads

    return (await load_division_heads(db)).get("back_office")


def may_author(user: User, *, is_head: bool) -> bool:
    if user.has_role(UserRole.admin) or is_head:
        return True
    return (
        care_access.is_care_worker(user)
        and section_access_for_user(user, ProductSection.delivery) >= SectionAccess.read
    )


@dataclass(frozen=True)
class Actor:
    user: User
    allowed: frozenset[int] | None
    is_admin: bool
    is_head: bool

    @property
    def can_approve(self) -> bool:
        return self.is_admin or self.is_head


async def actor_for(db: AsyncSession, user: User) -> Actor:
    is_head = (await back_office_head_id(db)) == user.id
    is_admin = user.has_role(UserRole.admin)
    allowed = (
        None if is_admin or is_head else await care_access.allowed_client_ids(user, db)
    )
    return Actor(user=user, allowed=allowed, is_admin=is_admin, is_head=is_head)


def may_view(actor: Actor, announcement: CareAnnouncement) -> bool:
    return actor.can_approve or announcement.created_by == actor.user.id


def may_edit(actor: Actor, announcement: CareAnnouncement) -> bool:
    return actor.is_admin or announcement.created_by == actor.user.id


async def load(
    db: AsyncSession, actor: Actor, announcement_id: int, *, for_update: bool = False
) -> CareAnnouncement:
    query = select(CareAnnouncement).where(CareAnnouncement.id == announcement_id)
    if for_update:
        query = query.with_for_update()
    announcement = await db.scalar(query)
    if announcement is None or not may_view(actor, announcement):
        raise AnnouncementError(404, NOT_FOUND)
    return announcement


# ── Przełącznik wysyłki ──────────────────────────────────────────────────────


async def sending_enabled(db: AsyncSession) -> bool:
    raw = await db.scalar(select(AppSetting.value).where(AppSetting.key == SETTING_KEY))
    return isinstance(raw, dict) and raw.get("sending_enabled") is True


def settings_payload(enabled: bool) -> dict[str, Any]:
    return {
        "sending_enabled": enabled,
        "transport": mail.transport_status(),
        "sender": mail.sender_address(),
        "approval_threshold": APPROVAL_THRESHOLD,
        "rate_per_minute": RATE_PER_MINUTE,
    }


async def set_sending(db: AsyncSession, actor: Actor, enabled: bool) -> dict[str, Any]:
    if not actor.is_admin:
        raise AnnouncementError(
            403,
            "Wysyłkę komunikatów włącza i wyłącza administrator.",
        )
    statement = insert(AppSetting).values(
        key=SETTING_KEY, value={"sending_enabled": enabled}, updated_by=actor.user.id
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": statement.excluded.value, "updated_by": actor.user.id},
        )
    )
    audit.record(
        db,
        actor_user_id=actor.user.id,
        subject_user_id=None,
        entity_type=ENTITY,
        entity_id="settings",
        action="care_announcement.sending_switched",
        details={"sending_enabled": enabled},
    )
    return settings_payload(enabled)


# ── Treść ────────────────────────────────────────────────────────────────────


def _clean_subject(value: object) -> str:
    if not isinstance(value, str):
        raise AnnouncementError(422, "Wpisz temat komunikatu.")
    subject = " ".join(value.replace("\x00", "").split())
    if len(subject) < 3:
        raise AnnouncementError(422, "Temat musi mieć co najmniej 3 znaki.")
    if len(subject) > SUBJECT_MAX - 24:  # miejsce na znacznik w temacie
        raise AnnouncementError(
            422, f"Temat może mieć najwyżej {SUBJECT_MAX - 24} znaków."
        )
    if mail.MARKER_RE.search(subject) or "{" in subject:
        raise AnnouncementError(
            422, "Temat nie ma pól — {imię} i {opiekun} działają w treści."
        )
    return subject


def _clean_body(value: object) -> str:
    if not isinstance(value, str) or not value.replace("\x00", "").strip():
        raise AnnouncementError(422, "Wpisz treść komunikatu.")
    body = value.replace("\x00", "").replace("\r\n", "\n").strip()
    if len(body) > BODY_MAX:
        raise AnnouncementError(422, f"Treść może mieć najwyżej {BODY_MAX} znaków.")
    unknown = mail.unknown_placeholders(body)
    if unknown:
        raise AnnouncementError(
            422,
            f"Nieznane pole {', '.join(unknown)}. Dostępne pola: "
            f"{', '.join(mail.PLACEHOLDERS)}.",
        )
    return body


def _clean_kind(value: object) -> str:
    if value not in KINDS:
        raise AnnouncementError(422, "Wybierz rodzaj: obowiązkowy albo informacyjny.")
    return str(value)


def _audience(actor: Actor, raw: object) -> audience_svc.Audience:
    try:
        parsed = audience_svc.parse_audience(raw)
    except audience_svc.AudienceError as exc:
        raise AnnouncementError(422, str(exc)) from exc
    for client_id in parsed.client_ids:
        care_access.assert_client_in_scope(client_id, actor.allowed)
    return parsed


async def create(
    db: AsyncSession,
    actor: Actor,
    *,
    kind: object,
    subject: object,
    body: object,
    audience: object,
) -> CareAnnouncement:
    announcement = CareAnnouncement(
        code=mail.new_code(),
        kind=_clean_kind(kind),
        subject=_clean_subject(subject),
        body=_clean_body(body),
        audience=_audience(actor, audience).as_json(),
        created_by=actor.user.id,
    )
    db.add(announcement)
    await db.flush()
    return announcement


def _require_draft(announcement: CareAnnouncement) -> None:
    if announcement.status != "draft":
        raise AnnouncementError(
            409, "Komunikat jest już wysłany do zatwierdzenia albo do kolejki."
        )


async def update_draft(
    db: AsyncSession, actor: Actor, announcement: CareAnnouncement, changes: dict
) -> CareAnnouncement:
    if not may_edit(actor, announcement):
        raise AnnouncementError(403, EDIT_DENIED)
    _require_draft(announcement)
    content_changed = False
    if "kind" in changes:
        kind = _clean_kind(changes["kind"])
        content_changed |= kind != announcement.kind
        announcement.kind = kind
    if "subject" in changes:
        subject = _clean_subject(changes["subject"])
        content_changed |= subject != announcement.subject
        announcement.subject = subject
    if "body" in changes:
        body = _clean_body(changes["body"])
        content_changed |= body != announcement.body
        announcement.body = body
    if "audience" in changes:
        announcement.audience = _audience(actor, changes["audience"]).as_json()
    if content_changed:
        announcement.content_version += 1
    announcement.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return announcement


# ── Podgląd odbiorców ────────────────────────────────────────────────────────


def _person_row(person: audience_svc.Person) -> dict[str, Any]:
    return {
        "candidate_id": person.candidate_id,
        "contract_id": person.contract_id,
        "client_id": person.client_id,
        "client_name": person.client_name,
        "name": person.name,
        "email": person.email,
        "owner_name": person.owner_name,
        "form": person.form,
        "end_date": person.end_date.isoformat() if person.end_date else None,
        "status": person.status,
    }


def _summary(statuses: Iterable[str]) -> dict[str, int]:
    counted = Counter(statuses)
    will = counted.get("pending", 0)
    return {
        "total": sum(counted.values()),
        "will_receive": will,
        "excluded_no_email": counted.get("excluded_no_email", 0),
        "excluded_opted_out": counted.get("excluded_opted_out", 0),
        "requires_approval": will > APPROVAL_THRESHOLD,
    }


async def preview(
    db: AsyncSession, actor: Actor, *, kind: object, audience: object
) -> dict[str, Any]:
    people = await audience_svc.resolve(
        db,
        allowed=actor.allowed,
        audience=_audience(actor, audience),
        kind=_clean_kind(kind),
    )
    return {
        **_summary(person.status for person in people),
        "rows": [_person_row(person) for person in people],
    }


# ── Próba, wysłanie, zatwierdzenie ───────────────────────────────────────────


def _first_word(name: Optional[str]) -> Optional[str]:
    parts = (name or "").split()
    return parts[0] if parts else None


async def test_send(
    db: AsyncSession,
    actor: Actor,
    announcement: CareAnnouncement,
    *,
    mailer: Optional[mail.AnnouncementMailer] = None,
) -> CareAnnouncement:
    """Próba do osoby, która ją zleca — działa także przy wyłączonej wysyłce."""

    if not may_edit(actor, announcement):
        raise AnnouncementError(403, EDIT_DENIED)
    _require_draft(announcement)
    sender = mailer or mail.default_mailer()
    if sender is None:
        raise AnnouncementError(409, NO_TRANSPORT)
    to = audience_svc.valid_email(actor.user.email)
    if to is None:
        raise AnnouncementError(422, "Twoje konto nie ma poprawnego adresu e-mail.")
    subject, text = mail.compose(
        announcement_id=announcement.id,
        code=announcement.code,
        kind=announcement.kind,
        subject=announcement.subject,
        body=announcement.body,
        first_name=_first_word(actor.user.name),
        owner=mail.owner_label(actor.user.name, actor.user.email),
        unsubscribe=None,
        test=True,
    )
    outcome = await sender.send(to=to, subject=subject, text=text)
    if outcome.status != "accepted":
        logger.warning(
            "[care_announcements] próba %s nie wyszła: %s",
            announcement.id,
            outcome.code or outcome.status,
        )
        raise AnnouncementError(
            503,
            "Nie udało się wysłać próby. Spróbuj ponownie za chwilę.",
        )
    announcement.tested_version = announcement.content_version
    announcement.tested_at = datetime.now(timezone.utc)
    await db.flush()
    return announcement


async def _freeze(
    db: AsyncSession, announcement: CareAnnouncement, people: list[audience_svc.Person]
) -> None:
    await db.execute(
        delete(CareAnnouncementRecipient).where(
            CareAnnouncementRecipient.announcement_id == announcement.id
        )
    )
    for person in people:
        db.add(
            CareAnnouncementRecipient(
                announcement_id=announcement.id,
                candidate_id=person.candidate_id,
                contract_id=person.contract_id,
                client_id=person.client_id,
                owner_user_id=person.owner_user_id,
                first_name=person.first_name,
                email=person.email,
                status=person.status,
            )
        )
    await db.flush()


async def _author_scope(
    db: AsyncSession, actor: Actor, announcement: CareAnnouncement
) -> Actor:
    """Zakres klientów autora (usunięte konto autora — zakres wysyłającego)."""

    if announcement.created_by is None or announcement.created_by == actor.user.id:
        return actor
    author = await db.get(User, announcement.created_by)
    return actor if author is None else await actor_for(db, author)


async def _approver_ids(db: AsyncSession, author_id: Optional[int]) -> list[int]:
    head = await back_office_head_id(db)
    if head is not None and head != author_id:
        active = await db.scalar(
            select(User.id).where(User.id == head, User.is_active.is_(True))
        )
        if active is not None:
            return [head]
    admins = await db.scalars(
        select(User.id).where(
            User.is_active.is_(True),
            (User.role == UserRole.admin) | User.roles.contains([UserRole.admin.value]),
        )
    )
    return [uid for uid in admins.all() if uid != author_id]


def _link(announcement_id: int) -> str:
    return f"/care?tab=announcements&announcement={announcement_id}"


def _short(text: str, limit: int = 120) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


async def submit(
    db: AsyncSession, actor: Actor, announcement: CareAnnouncement
) -> CareAnnouncement:
    if not may_edit(actor, announcement):
        raise AnnouncementError(403, EDIT_DENIED)
    _require_draft(announcement)
    if announcement.tested_version != announcement.content_version:
        raise AnnouncementError(409, UNTESTED)
    # Zakres autora, nie wysyłającego: „wszyscy” w szkicu Delivery Leada to
    # jego klienci także wtedy, gdy „Wyślij” klika admin.
    scope = await _author_scope(db, actor, announcement)
    people = await audience_svc.resolve(
        db,
        allowed=scope.allowed,
        audience=_audience(scope, announcement.audience),
        kind=announcement.kind,
    )
    will = sum(1 for person in people if person.status == "pending")
    if will == 0:
        raise AnnouncementError(
            422,
            "Nikt z tej grupy nie dostanie komunikatu — brak adresów e-mail "
            "albo wszyscy się wypisali.",
        )
    requires = will > APPROVAL_THRESHOLD
    if not requires and not await sending_enabled(db):
        raise AnnouncementError(409, SENDING_OFF)
    now = datetime.now(timezone.utc)
    await _freeze(db, announcement, people)
    announcement.recipient_count = will
    announcement.requires_approval = requires
    announcement.submitted_by = actor.user.id
    announcement.submitted_at = now
    announcement.return_note = None
    if requires:
        announcement.status = "pending"
    else:
        announcement.status = "queued"
        announcement.queued_at = now
    announcement.updated_at = now
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.user.id,
        subject_user_id=None,
        entity_type=ENTITY,
        entity_id=announcement.id,
        action="care_announcement.submitted",
        details={"recipients": will, "requires_approval": requires},
    )
    if requires:
        author_name = actor.user.name or "Autor"
        await notify_each(
            db,
            await _approver_ids(db, announcement.created_by),
            title="Komunikat do zatwierdzenia",
            message=(
                f"{author_name}: „{_short(announcement.subject)}” — "
                f"{will} osób czeka na Twoje zatwierdzenie."
            ),
            ntype=NotificationType.care_announcement,
            link=_link(announcement.id),
            related_entity_type="care_announcement_review",
            related_entity_id=announcement.id,
            log_tag="care_announcements",
        )
    return announcement


async def approve(
    db: AsyncSession, actor: Actor, announcement: CareAnnouncement
) -> CareAnnouncement:
    if not actor.can_approve:
        raise AnnouncementError(403, APPROVER_DENIED)
    if actor.user.id in (announcement.created_by, announcement.submitted_by):
        raise AnnouncementError(403, OWN_APPROVAL)
    if announcement.status != "pending":
        raise AnnouncementError(409, "Ten komunikat nie czeka na zatwierdzenie.")
    if not await sending_enabled(db):
        raise AnnouncementError(409, SENDING_OFF)
    now = datetime.now(timezone.utc)
    announcement.status = "queued"
    announcement.approved_by = actor.user.id
    announcement.approved_at = now
    announcement.queued_at = now
    announcement.updated_at = now
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.user.id,
        subject_user_id=announcement.created_by,
        entity_type=ENTITY,
        entity_id=announcement.id,
        action="care_announcement.approved",
        details={"recipients": announcement.recipient_count},
    )
    await notify_each(
        db,
        [announcement.created_by],
        title="Komunikat zatwierdzony",
        message=(
            f"„{_short(announcement.subject)}” idzie do "
            f"{announcement.recipient_count} osób."
        ),
        ntype=NotificationType.care_announcement,
        link=_link(announcement.id),
        related_entity_type="care_announcement_decision",
        related_entity_id=announcement.id,
        exclude=[actor.user.id],
        log_tag="care_announcements",
    )
    return announcement


async def return_to_draft(
    db: AsyncSession, actor: Actor, announcement: CareAnnouncement, note: object
) -> CareAnnouncement:
    if not actor.can_approve:
        raise AnnouncementError(403, APPROVER_DENIED)
    if announcement.status != "pending":
        raise AnnouncementError(409, "Ten komunikat nie czeka na zatwierdzenie.")
    cleaned = " ".join(str(note or "").replace("\x00", "").split()) or None
    if cleaned and len(cleaned) > RETURN_NOTE_MAX:
        raise AnnouncementError(
            422, f"Uwaga może mieć najwyżej {RETURN_NOTE_MAX} znaków."
        )
    await db.execute(
        delete(CareAnnouncementRecipient).where(
            CareAnnouncementRecipient.announcement_id == announcement.id
        )
    )
    announcement.status = "draft"
    announcement.return_note = cleaned
    announcement.recipient_count = 0
    announcement.requires_approval = False
    announcement.submitted_by = None
    announcement.submitted_at = None
    announcement.updated_at = datetime.now(timezone.utc)
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.user.id,
        subject_user_id=announcement.created_by,
        entity_type=ENTITY,
        entity_id=announcement.id,
        action="care_announcement.returned",
        details={"with_note": cleaned is not None},
    )
    await notify_each(
        db,
        [announcement.created_by],
        title="Komunikat wrócił do poprawy",
        message=cleaned or f"„{_short(announcement.subject)}” wrócił do szkicu.",
        ntype=NotificationType.care_announcement,
        link=_link(announcement.id),
        related_entity_type="care_announcement_decision",
        related_entity_id=announcement.id,
        exclude=[actor.user.id],
        log_tag="care_announcements",
    )
    return announcement


async def cancel(
    db: AsyncSession, actor: Actor, announcement: CareAnnouncement
) -> CareAnnouncement:
    if not (may_edit(actor, announcement) or actor.can_approve):
        raise AnnouncementError(403, EDIT_DENIED)
    if announcement.status not in ("draft", "pending", "queued"):
        raise AnnouncementError(409, "Tego komunikatu nie da się już anulować.")
    now = datetime.now(timezone.utc)
    stopped = await db.execute(
        update(CareAnnouncementRecipient)
        .where(
            CareAnnouncementRecipient.announcement_id == announcement.id,
            CareAnnouncementRecipient.status == "pending",
        )
        .values(status="cancelled", updated_at=now)
    )
    announcement.status = "cancelled"
    announcement.cancelled_by = actor.user.id
    announcement.cancelled_at = now
    announcement.updated_at = now
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.user.id,
        subject_user_id=announcement.created_by,
        entity_type=ENTITY,
        entity_id=announcement.id,
        action="care_announcement.cancelled",
        details={"stopped": stopped.rowcount or 0},
    )
    return announcement


# ── Odczyt: lista, szczegół, raport ──────────────────────────────────────────


async def _counts(
    db: AsyncSession, announcement_ids: list[int]
) -> dict[int, dict[str, int]]:
    out: dict[int, dict[str, int]] = {
        aid: {key: 0 for key in (*RECIPIENT_STATUSES, "unsubscribed")}
        for aid in announcement_ids
    }
    if not announcement_ids:
        return out
    rows = (
        await db.execute(
            select(
                CareAnnouncementRecipient.announcement_id,
                CareAnnouncementRecipient.status,
                func.count(),
            )
            .where(CareAnnouncementRecipient.announcement_id.in_(announcement_ids))
            .group_by(
                CareAnnouncementRecipient.announcement_id,
                CareAnnouncementRecipient.status,
            )
        )
    ).all()
    for aid, status_value, count in rows:
        out[aid][status_value] = count
    unsubscribed = (
        await db.execute(
            select(CareAnnouncementRecipient.announcement_id, func.count())
            .where(
                CareAnnouncementRecipient.announcement_id.in_(announcement_ids),
                CareAnnouncementRecipient.unsubscribed_at.is_not(None),
            )
            .group_by(CareAnnouncementRecipient.announcement_id)
        )
    ).all()
    for aid, count in unsubscribed:
        out[aid]["unsubscribed"] = count
    return out


async def _reply_counts(
    db: AsyncSession, announcement_ids: list[int]
) -> dict[int, dict[str, int]]:
    out = {aid: {"reply": 0, "bounce": 0} for aid in announcement_ids}
    if not announcement_ids:
        return out
    rows = (
        await db.execute(
            select(
                CareAnnouncementReply.announcement_id,
                CareAnnouncementReply.kind,
                func.count(),
            )
            .where(CareAnnouncementReply.announcement_id.in_(announcement_ids))
            .group_by(CareAnnouncementReply.announcement_id, CareAnnouncementReply.kind)
        )
    ).all()
    for aid, kind, count in rows:
        out[aid][kind] = count
    return out


async def _names_for(
    db: AsyncSession, announcements: list[CareAnnouncement]
) -> tuple[dict[int, str], dict[int, str]]:
    """(nazwy kont, nazwy klientów) potrzebne liście i szczegółowi."""

    user_ids: set[Optional[int]] = set()
    client_ids: set[int] = set()
    for row in announcements:
        user_ids.update((row.created_by, row.approved_by, row.submitted_by))
        user_ids.update(row.audience.get("owner_user_ids") or [])
        client_ids.update(row.audience.get("client_ids") or [])
    users = await care_access.user_names(db, user_ids)
    clients: dict[int, str] = {}
    if client_ids:
        rows = (
            await db.execute(
                select(Client.id, Client.name).where(Client.id.in_(sorted(client_ids)))
            )
        ).all()
        clients = {cid: name for cid, name in rows}
    return users, clients


def _person(user_id: Optional[int], names: dict[int, str]) -> Optional[dict[str, Any]]:
    if user_id is None:
        return None
    return {"id": user_id, "name": names.get(user_id, "—")}


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _row(
    actor: Actor,
    announcement: CareAnnouncement,
    *,
    users: dict[int, str],
    clients: dict[int, str],
    counts: dict[str, int],
    replies: dict[str, int],
) -> dict[str, Any]:
    return {
        "id": announcement.id,
        "marker": mail.marker(announcement.id, announcement.code),
        "kind": announcement.kind,
        "status": announcement.status,
        "subject": announcement.subject,
        "author": _person(announcement.created_by, users),
        "audience": announcement.audience,
        "audience_label": audience_svc.audience_label(
            announcement.audience, client_names=clients, owner_names=users
        ),
        "recipient_count": announcement.recipient_count,
        "requires_approval": announcement.requires_approval,
        "approver": _person(announcement.approved_by, users),
        "created_at": _iso(announcement.created_at),
        "submitted_at": _iso(announcement.submitted_at),
        "approved_at": _iso(announcement.approved_at),
        "queued_at": _iso(announcement.queued_at),
        "send_started_at": _iso(announcement.send_started_at),
        "send_finished_at": _iso(announcement.send_finished_at),
        "cancelled_at": _iso(announcement.cancelled_at),
        "counts": counts,
        "replies": replies,
        "can_approve": (
            announcement.status == "pending"
            and actor.can_approve
            and actor.user.id
            not in (announcement.created_by, announcement.submitted_by)
        ),
    }


async def list_for(db: AsyncSession, actor: Actor) -> list[dict[str, Any]]:
    query = select(CareAnnouncement).order_by(CareAnnouncement.created_at.desc())
    if not actor.can_approve:
        query = query.where(CareAnnouncement.created_by == actor.user.id)
    announcements = list((await db.scalars(query.limit(200))).all())
    ids = [row.id for row in announcements]
    users, clients = await _names_for(db, announcements)
    counts = await _counts(db, ids)
    replies = await _reply_counts(db, ids)
    return [
        _row(
            actor,
            row,
            users=users,
            clients=clients,
            counts=counts[row.id],
            replies=replies[row.id],
        )
        for row in announcements
    ]


async def _recipients(db: AsyncSession, announcement_id: int) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(
                CareAnnouncementRecipient,
                Candidate.name,
                Candidate.lastname,
                Client.name,
                User.name,
            )
            .join(Candidate, Candidate.id == CareAnnouncementRecipient.candidate_id)
            .outerjoin(Client, Client.id == CareAnnouncementRecipient.client_id)
            .outerjoin(User, User.id == CareAnnouncementRecipient.owner_user_id)
            .where(CareAnnouncementRecipient.announcement_id == announcement_id)
            .order_by(Client.name, Candidate.lastname, Candidate.name)
        )
    ).all()
    return [
        {
            "candidate_id": recipient.candidate_id,
            "contract_id": recipient.contract_id,
            "client_id": recipient.client_id,
            "client_name": client_name,
            "name": full_name(first, last) or "Konsultant",
            "email": recipient.email,
            "owner_name": owner_name,
            "status": recipient.status,
            "error_code": recipient.error_code,
            "sent_at": _iso(recipient.sent_at),
            "unsubscribed": recipient.unsubscribed_at is not None,
            "simulated": recipient.simulated,
        }
        for recipient, first, last, client_name, owner_name in rows
    ]


async def _replies(db: AsyncSession, announcement_id: int) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(CareAnnouncementReply, AdminCase.title, AdminCase.status)
            .join(AdminCase, AdminCase.id == CareAnnouncementReply.case_id)
            .where(CareAnnouncementReply.announcement_id == announcement_id)
            .order_by(CareAnnouncementReply.created_at.desc())
            .limit(200)
        )
    ).all()
    return [
        {
            "case_id": reply.case_id,
            "kind": reply.kind,
            "title": title,
            "case_status": case_status,
            "created_at": _iso(reply.created_at),
        }
        for reply, title, case_status in rows
    ]


async def detail(
    db: AsyncSession, actor: Actor, announcement: CareAnnouncement
) -> dict[str, Any]:
    users, clients = await _names_for(db, [announcement])
    counts = (await _counts(db, [announcement.id]))[announcement.id]
    replies = (await _reply_counts(db, [announcement.id]))[announcement.id]
    editable = may_edit(actor, announcement) and announcement.status == "draft"
    test_current = announcement.tested_version == announcement.content_version
    return {
        **_row(
            actor,
            announcement,
            users=users,
            clients=clients,
            counts=counts,
            replies=replies,
        ),
        "body": announcement.body,
        "content_version": announcement.content_version,
        "tested_at": _iso(announcement.tested_at) if test_current else None,
        "test_current": test_current,
        "return_note": announcement.return_note,
        "submitted_by": _person(announcement.submitted_by, users),
        "recipients": (
            []
            if announcement.status == "draft"
            else await _recipients(db, announcement.id)
        ),
        "reply_cases": await _replies(db, announcement.id),
        "can_edit": editable,
        "can_test": editable,
        "can_submit": editable and test_current,
        "can_cancel": announcement.status in ("draft", "pending", "queued")
        and (may_edit(actor, announcement) or actor.can_approve),
    }


# ── Wypis (publiczny link) ───────────────────────────────────────────────────


async def _by_token(
    db: AsyncSession, raw_token: str, *, for_update: bool = False
) -> Optional[CareAnnouncementRecipient]:
    if not raw_token or len(raw_token) > 128:
        return None
    query = select(CareAnnouncementRecipient).where(
        CareAnnouncementRecipient.unsubscribe_token_sha256 == mail.token_hash(raw_token)
    )
    if for_update:
        query = query.with_for_update()
    return await db.scalar(query)


async def unsubscribe_state(db: AsyncSession, raw_token: str) -> Optional[bool]:
    """``None`` = nie ma takiego linku; inaczej czy osoba jest wypisana."""

    recipient = await _by_token(db, raw_token)
    if recipient is None:
        return None
    opted = await db.get(CareAnnouncementOptOut, recipient.candidate_id)
    return opted is not None


async def unsubscribe(db: AsyncSession, raw_token: str) -> bool:
    """Wypis z informacyjnych; ``False`` = nie ma takiego linku. Idempotentny."""

    recipient = await _by_token(db, raw_token, for_update=True)
    if recipient is None:
        return False
    await db.execute(
        insert(CareAnnouncementOptOut)
        .values(candidate_id=recipient.candidate_id, recipient_id=recipient.id)
        .on_conflict_do_nothing(index_elements=[CareAnnouncementOptOut.candidate_id])
    )
    if recipient.unsubscribed_at is None:
        recipient.unsubscribed_at = datetime.now(timezone.utc)
    await db.flush()
    logger.info("[care_announcements] wypis recipient=%s", recipient.id)
    return True


# ── Odpowiedzi i odbite maile (czytnik administracja@) ──────────────────────

#: Zwrotki wysyła serwer poczty (Exchange: ``postmaster@`` albo
#: ``MicrosoftExchange…@``) — temat „Undeliverable” od człowieka to odpowiedź,
#: inaczej każdy odbiorca znający znacznik oznaczałby cudze adresy jako odbite.
_BOUNCE_SENDERS = ("postmaster@", "mailer-daemon@", "microsoftexchange")


def looks_like_bounce(sender: Optional[str]) -> bool:
    lowered = (sender or "").lower()
    return any(lowered.startswith(prefix) for prefix in _BOUNCE_SENDERS)


async def link_mail_case(
    db: AsyncSession,
    case: AdminCase,
    *,
    subject: Optional[str],
    sender_email: Optional[str],
    body_text: str,
) -> Optional[str]:
    """Przypina nową sprawę z maila do komunikatu ze znacznika w temacie.

    Zwraca ``reply`` / ``bounce`` albo ``None`` (brak znacznika, zły kod).
    Nie commituje — wchodzi w punkt zapisu czytnika.
    """

    match = mail.MARKER_RE.search(subject or "")
    if match is None:
        return None
    announcement = await db.scalar(
        select(CareAnnouncement).where(
            CareAnnouncement.id == int(match.group(1)),
            CareAnnouncement.code == match.group(2),
            CareAnnouncement.queued_at.is_not(None),
        )
    )
    if announcement is None:
        return None
    recipients = (
        await db.scalars(
            select(CareAnnouncementRecipient).where(
                CareAnnouncementRecipient.announcement_id == announcement.id,
                CareAnnouncementRecipient.email.is_not(None),
            )
        )
    ).all()
    kind = "bounce" if looks_like_bounce(sender_email) else "reply"
    matched: Optional[CareAnnouncementRecipient] = None
    if kind == "bounce":
        haystack = (body_text or "").lower()
        bounced = [
            r
            for r in recipients
            if r.status in ("sent", "uncertain") and r.email.lower() in haystack
        ]
        now = datetime.now(timezone.utc)
        for recipient in bounced:
            recipient.status = "bounced"
            recipient.bounced_at = now
            recipient.sent_at = recipient.sent_at or now
        matched = bounced[0] if bounced else None
        await _notify_bounces(db, bounced)
    else:
        sender = (sender_email or "").lower()
        matched = next((r for r in recipients if r.email.lower() == sender), None)
    if matched is not None and case.contract_id is None:
        case.contract_id = matched.contract_id
    await db.execute(
        insert(CareAnnouncementReply)
        .values(
            announcement_id=announcement.id,
            case_id=case.id,
            recipient_id=matched.id if matched else None,
            kind=kind,
        )
        .on_conflict_do_nothing(constraint="uq_care_announcement_replies_case")
    )
    await db.flush()
    return kind


async def _notify_bounces(
    db: AsyncSession, bounced: list[CareAnnouncementRecipient]
) -> None:
    for recipient in bounced:
        if recipient.owner_user_id is None or recipient.contract_id is None:
            continue
        candidate = await db.get(Candidate, recipient.candidate_id)
        name = (
            full_name(candidate.name, candidate.lastname) if candidate else None
        ) or "konsultanta"
        await notify_each(
            db,
            [recipient.owner_user_id],
            title="Komunikat nie doszedł — popraw e-mail",
            message=(
                f"Mail do: {name} wrócił jako niedoręczony. Popraw adres e-mail "
                "w kontrakcie albo w profilu, żeby następny komunikat doszedł."
            ),
            ntype=NotificationType.care_announcement,
            link=f"/contracts/{recipient.contract_id}",
            related_entity_type="care_announcement_bounce",
            related_entity_id=recipient.id,
            log_tag="care_announcements",
        )
