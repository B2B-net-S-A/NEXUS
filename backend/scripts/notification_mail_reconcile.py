"""Rozstrzygnięcie niepewnej wysyłki maila powiadomienia po sprawdzeniu Exchange.

Wiersz `Notification` z `email_delivery_uncertain=true` żadna pętla już nie
weźmie (chroni to przed duplikatem), a monitor `app_mail_monitor` liczy go do
alarmu przez `UNCERTAIN_ALARM_WINDOW`. Runbook
`docs/sentry-mail-ai-recovery.md` każe operatorowi najpierw sprawdzić
Exchange message trace, a potem celowo oznaczyć wynik albo zaplanować
ponowienie konkretnych rekordów. Ten skrypt robi tylko to, dla jawnie
podanych id — trybu „wszystkie niepewne” nie ma, bo masowy reset wysłałby
drugi mail każdemu, kto pierwszy już dostał.

    python -m scripts.notification_mail_reconcile 123 --delivered          # podgląd
    python -m scripts.notification_mail_reconcile 123 --delivered --apply
    python -m scripts.notification_mail_reconcile 123 --resend --apply

Bez `--apply` nic nie zmienia. Wiersz bez flagi, już wysłany albo nieistniejący
= odmowa całego biegu. Log ma tylko id, typ i tryb; adresat w podglądzie jest
zamaskowany, treści nie ma nigdzie.

Kolumny, które czytają ścieżki wysyłki (12.11.2026):
- `job_chat_*` — `tasks/chat_email_fallback.py`: `email_sent_at IS NULL`,
  flaga, `email_send_started_at` pusty albo starszy niż 15 min,
  `email_next_attempt_at` pusty albo miniony; do tego nieprzeczytane
  i odbiorca offline.
- rodzaje z `IMMEDIATE_KINDS` — `tasks/notification_email_outbox.py`: te same
  trzy pierwsze warunki, `email_next_attempt_at` ignoruje; wiersz starszy niż
  `MAX_AGE` (24 h) nie idzie już mailem.
- `job_deadline_*` — `tasks/job_deadline_alerts.py`: jak outbox, bez `MAX_AGE`.

`--resend` zdejmuje flagę i zeruje `email_next_attempt_at`: pusta wartość jest
„do wysłania teraz” dla wszystkich trzech ścieżek, a ustawiona liczyłaby się
w monitorze jako ponowienie z wiekiem od `created_at` (alarm od razu przy
wierszu sprzed godziny). `email_send_started_at` zostaje jako ślad pierwszej
próby; po 15 minutach rezerwacja i tak jest przeterminowana.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification
from app.models.user import User
from app.services.notification_delivery import immediate_email_kind
from app.tasks.chat_email_fallback import _CHAT_NOTIF_TYPES
from app.tasks.job_deadline_alerts import _DEADLINE_NTYPES
from app.tasks.notification_email_outbox import MAX_AGE

logger = logging.getLogger(__name__)

# Górna granica id na jeden bieg: narzędzie jest do rozstrzygania pojedynczych
# rekordów po message trace, nie do czyszczenia zaległości.
MAX_IDS = 20

EXIT_OK = 0
EXIT_REFUSED = 3


@dataclass(frozen=True)
class Row:
    id: int
    notification_type: str
    path: str | None
    created_at: datetime
    send_started_at: datetime | None
    sent_at: datetime | None
    uncertain: bool
    is_read: bool
    recipient: str


def mask_email(address: str | None) -> str:
    if not address or "@" not in address:
        return "(brak adresu)"
    local, domain = address.rsplit("@", 1)
    return f"{local[:1]}***@{domain}"


def mail_path(notif: Notification) -> str | None:
    """Pętla, która wysyła mail dla tego wiersza, albo `None`."""
    if notif.notification_type in _CHAT_NOTIF_TYPES:
        return "chat_email_fallback"
    if notif.notification_type in _DEADLINE_NTYPES:
        return "job_deadline_alerts"
    kind = immediate_email_kind(
        notif.notification_type,
        title=notif.title,
        related_entity_type=notif.related_entity_type,
    )
    return f"notification_email_outbox:{kind}" if kind else None


async def load_rows(db: AsyncSession, ids: list[int]) -> dict[int, Row]:
    pairs = (
        await db.execute(
            select(Notification, User.email)
            .outerjoin(User, User.id == Notification.user_id)
            .where(Notification.id.in_(ids))
        )
    ).all()
    return {
        notif.id: Row(
            id=notif.id,
            notification_type=notif.notification_type.value,
            path=mail_path(notif),
            created_at=notif.created_at,
            send_started_at=notif.email_send_started_at,
            sent_at=notif.email_sent_at,
            uncertain=bool(notif.email_delivery_uncertain),
            is_read=bool(notif.is_read),
            recipient=mask_email(email),
        )
        for notif, email in pairs
    }


def refusals(
    rows: dict[int, Row], ids: list[int], mode: str, now: datetime
) -> list[str]:
    problems = []
    for notif_id in ids:
        row = rows.get(notif_id)
        if row is None:
            problems.append(f"{notif_id}: nie ma takiego powiadomienia")
        elif row.sent_at is not None:
            problems.append(f"{notif_id}: mail już ma `email_sent_at`")
        elif not row.uncertain:
            problems.append(
                f"{notif_id}: brak `email_delivery_uncertain` — nie ma czego rozstrzygać"
            )
        elif mode == "resend" and row.path is None:
            problems.append(
                f"{notif_id}: typ {row.notification_type} nie ma pętli wysyłki — ponowienie nic nie wyśle"
            )
        elif (
            mode == "resend"
            and row.path.startswith("notification_email_outbox")
            and row.created_at < now - MAX_AGE
        ):
            problems.append(
                f"{notif_id}: starsze niż {MAX_AGE} — outbox go już nie wyśle"
            )
    return problems


def describe(row: Row) -> str:
    started = row.send_started_at.isoformat() if row.send_started_at else "-"
    note = (
        " (przeczytane: fallback czatu go pominie)"
        if row.is_read and row.path == "chat_email_fallback"
        else ""
    )
    return (
        f"{row.id}: {row.notification_type} · ścieżka {row.path or '-'} · "
        f"utworzone {row.created_at.isoformat()} · próba {started} · "
        f"do {row.recipient}{note}"
    )


def _values(mode: str) -> dict:
    if mode == "delivered":
        return {
            "email_sent_at": func.coalesce(
                Notification.email_send_started_at, func.now()
            ),
            "email_delivery_uncertain": False,
            "email_next_attempt_at": None,
        }
    return {"email_delivery_uncertain": False, "email_next_attempt_at": None}


async def apply(db: AsyncSession, ids: list[int], mode: str) -> list[int]:
    """Jeden UPDATE pod tym samym warunkiem co odmowa; wszystko albo nic."""
    result = await db.execute(
        update(Notification)
        .where(
            Notification.id.in_(ids),
            Notification.email_delivery_uncertain.is_(True),
            Notification.email_sent_at.is_(None),
        )
        .values(**_values(mode))
        .returning(Notification.id)
    )
    changed = sorted(result.scalars().all())
    if len(changed) != len(set(ids)):
        await db.rollback()
        return []
    await db.commit()
    return changed


async def run(db: AsyncSession, ids: list[int], mode: str, do_apply: bool) -> int:
    rows = await load_rows(db, ids)
    for notif_id in ids:
        if notif_id in rows:
            print(describe(rows[notif_id]))
    problems = refusals(rows, ids, mode, datetime.now(timezone.utc))
    if problems:
        for problem in problems:
            print(f"ODMOWA {problem}", file=sys.stderr)
        print("Nic nie zmieniono.", file=sys.stderr)
        return EXIT_REFUSED
    if not do_apply:
        print(f"Podgląd: --{mode} dla {len(ids)} rekordów. Zapis dopiero z --apply.")
        return EXIT_OK
    changed = await apply(db, ids, mode)
    if not changed:
        print(
            "ODMOWA: stan rekordów zmienił się w trakcie biegu. Nic nie zmieniono.",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    logger.info("notification_mail_reconcile: %s ids=%s", mode, changed)
    print(f"Zapisano --{mode} dla id: {', '.join(map(str, changed))}")
    return EXIT_OK


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.notification_mail_reconcile",
        description="Rozstrzygnij niepewną wysyłkę maila konkretnych powiadomień.",
    )
    parser.add_argument("ids", nargs="+", type=int, help="id powiadomień (jawnie)")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--delivered",
        action="store_const",
        const="delivered",
        dest="mode",
        help="message trace potwierdza dostawę: oznacz jako wysłane",
    )
    mode.add_argument(
        "--resend",
        action="store_const",
        const="resend",
        dest="mode",
        help="message trace nie zna maila: niech pętla spróbuje raz jeszcze",
    )
    parser.add_argument(
        "--apply", action="store_true", help="zapisz (bez tego tylko podgląd)"
    )
    args = parser.parse_args(argv)
    args.ids = list(dict.fromkeys(args.ids))
    if len(args.ids) > MAX_IDS:
        parser.error(f"najwyżej {MAX_IDS} id na bieg — to nie jest narzędzie masowe")
    return args


async def _main(args: argparse.Namespace) -> int:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        return await run(db, args.ids, args.mode, args.apply)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    return asyncio.run(_main(args))


if __name__ == "__main__":
    sys.exit(main())
