"""Treść maili skasowana przez aktualizacje delty — ponowny odczyt z Graph (02.11.2026).

Do 02.11.2026 aktualizacja delty bez ``body`` (zwykle po samym przeczytaniu)
zerowała w `emails` treść, podgląd i flagę załączników. Kod poprawia
`sync._apply_partial_delta`; ten skrypt odczytuje treść tych wierszy ze skrzynek.
Uruchamiaj dopiero po wdrożeniu poprawki, inaczej delta skasuje ją ponownie.

Uruchomienie (w kontenerze backendu)::

    python -m app.cli.m365_email_body_refetch
    python -m app.cli.m365_email_body_refetch --apply --expected <odcisk>

Zasady:

* wiersz = poczta przychodząca, ``body_html IS NULL``, pusty tekst i podgląd, nie
  prywatny, ma ``m365_message_id`` i nadawcę. Wiersze bez nadawcy powstały
  z aktualizacji nieznanej wiadomości i nie mają czego uzupełniać: tylko liczba;
* próba na sucho pyta Graph wyłącznie o ``id`` i niczego nie zapisuje w `emails`;
  z ``--apply`` czyta treść, zapisuje po ``BATCH_SIZE`` wierszy i zdejmuje tylko
  pustkę. Drugi bieg jest bezpieczny (np. po ponownym podłączeniu skrzynki);
* identyfikator Graph zmienia się po przeniesieniu do innego folderu, więc po
  404 szukamy wiadomości po ``internetMessageId`` w tej samej skrzynce;
* wiadomość z kategorią prywatną dostaje znacznik prywatności, bez treści;
* paragon ``app_settings['m365_email_body_refetch_2026_11']`` niesie same liczby
  i id. Raport jest bez adresów, tematów i treści (logi Actions są publiczne).

Cofnięcie: uzupełnione wiersze z paragonu (``filled_ids``) wracają do pustych,
a treść nadal leży w skrzynkach, więc bieg można powtórzyć::

    UPDATE emails SET body_html = NULL, body_text = '', body_preview = ''
    WHERE id IN (SELECT (jsonb_array_elements_text(value->'filled_ids'))::int
                 FROM app_settings
                 WHERE key = 'm365_email_body_refetch_2026_11');
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import sys
from collections import Counter
from typing import Any, Optional

from sqlalchemy import func, or_, select

logger = logging.getLogger(__name__)

RECEIPT_KEY = "m365_email_body_refetch_2026_11"
BATCH_SIZE = 50
REFETCH_SELECT = "id,body,bodyPreview,hasAttachments,categories"


def wiped_rows_filter() -> tuple:
    """Warunek wiersza, któremu delta skasowała treść."""
    from app.models.m365 import Email, EmailDirection

    return (
        Email.direction == EmailDirection.received,
        Email.body_html.is_(None),
        func.coalesce(Email.body_text, "") == "",
        func.coalesce(Email.body_preview, "") == "",
        Email.is_private_filtered.is_(False),
        Email.m365_message_id.is_not(None),
    )


def fingerprint(email_ids: list[int]) -> str:
    return hashlib.sha256(json.dumps(sorted(email_ids)).encode()).hexdigest()[:12]


async def plan(db) -> dict[str, Any]:
    """Wiersze do uzupełnienia: id per skrzynka, bez skrzynek do ponownego podłączenia."""
    from app.models.m365 import Email, M365Connection, M365SyncStatus

    rows = (
        await db.execute(
            select(Email.id, Email.user_id, M365Connection.id)
            .outerjoin(
                M365Connection,
                (M365Connection.user_id == Email.user_id)
                & M365Connection.is_active.is_(True)
                & (
                    M365Connection.last_sync_status != M365SyncStatus.reconnect_required
                ),
            )
            .where(*wiped_rows_filter(), func.coalesce(Email.from_address, "") != "")
            .order_by(Email.id)
        )
    ).all()
    without_sender = await db.scalar(
        select(func.count(Email.id)).where(
            *wiped_rows_filter(),
            or_(Email.from_address.is_(None), Email.from_address == ""),
        )
    )
    by_connection: dict[int, list[int]] = {}
    no_connection = 0
    for email_id, _user_id, connection_id in rows:
        if connection_id is None:
            no_connection += 1
        else:
            by_connection.setdefault(connection_id, []).append(email_id)
    return {
        "by_connection": by_connection,
        "no_connection": no_connection,
        "without_sender": without_sender or 0,
    }


async def fetch_message(gc, row, select_fields: str) -> Optional[dict]:
    """Wiadomość po id, a po przeniesieniu (404) po ``internetMessageId``."""
    from app.services.m365.graph_client import GraphRequestError

    try:
        return await gc.get(
            f"/me/messages/{row.m365_message_id}", params={"$select": select_fields}
        )
    except GraphRequestError as exc:
        if exc.status != 404:
            raise
    internet_id = row.m365_internet_message_id
    if not internet_id:
        return None
    escaped = internet_id.replace("'", "''")
    page = await gc.get(
        "/me/messages",
        params={
            "$filter": f"internetMessageId eq '{escaped}'",
            "$select": select_fields,
            "$top": 1,
        },
    )
    found = page.get("value") or []
    return found[0] if found else None


async def fill_row(row, message: dict) -> str:
    """Uzupełnij wiersz odczytaną wiadomością. Zwraca wynik do raportu."""
    from app.core.config import settings
    from app.services.m365.sync import message_body

    categories = message.get("categories") or []
    row.raw_categories = categories
    if settings.M365_IGNORE_CATEGORY in categories:
        row.is_private_filtered = True
        return "private"
    row.has_attachments = bool(message.get("hasAttachments"))
    body_html, body_text, body_preview = await message_body(message)
    if not body_html and not body_text:
        return "empty_in_mailbox"
    row.body_html = body_html
    row.body_text = body_text
    row.body_preview = body_preview
    return "filled"


async def refetch_connection(
    db, connection_id: int, email_ids: list[int], *, apply: bool
) -> tuple[Counter, list[int]]:
    """Jedna skrzynka. Błąd pojedynczej wiadomości nie zatrzymuje reszty."""
    from app.models.m365 import Email, M365Connection
    from app.services.m365.graph_client import GraphClient

    counts: Counter = Counter()
    filled: list[int] = []
    conn = await db.get(M365Connection, connection_id)
    select_fields = REFETCH_SELECT if apply else "id"
    try:
        async with GraphClient(conn, db, sales_ok=True) as gc:
            for start in range(0, len(email_ids), BATCH_SIZE):
                chunk = email_ids[start : start + BATCH_SIZE]
                rows = (
                    await db.scalars(
                        select(Email).where(Email.id.in_(chunk), *wiped_rows_filter())
                    )
                ).all()
                for row in rows:
                    try:
                        message = await fetch_message(gc, row, select_fields)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "m365 refetch: email %s: %s", row.id, type(exc).__name__
                        )
                        counts["errors"] += 1
                        continue
                    if message is None:
                        counts["gone_from_mailbox"] += 1
                    elif not apply:
                        counts["found"] += 1
                    else:
                        result = await fill_row(row, message)
                        counts[result] += 1
                        if result == "filled":
                            filled.append(row.id)
                if apply:
                    await db.commit()
    except Exception as exc:  # noqa: BLE001
        # Np. właściciel stracił dostęp: reszta skrzynek idzie dalej.
        await db.rollback()
        logger.warning(
            "m365 refetch: connection %s: %s", connection_id, type(exc).__name__
        )
        counts["mailbox_failed_rows"] += len(email_ids) - sum(counts.values())
    return counts, filled


async def save_receipt(db, *, counts: Counter, filled: list[int]) -> None:
    """Dopisz do paragonu: kolejny bieg dokłada id, nie gubi poprzednich."""
    from app.models.app_setting import AppSetting

    receipt = await db.get(AppSetting, RECEIPT_KEY)
    previous = receipt.value if receipt is not None else {"filled_ids": [], "runs": []}
    value = {
        "filled_ids": sorted({*previous["filled_ids"], *filled}),
        "runs": [*previous["runs"], dict(counts)],
    }
    if receipt is None:
        db.add(AppSetting(key=RECEIPT_KEY, value=value))
    else:
        receipt.value = value
    await db.commit()


async def main(argv: Optional[list[str]] = None) -> int:
    from app.core.database import AsyncSessionLocal, engine

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--expected", help="odcisk planu z próby na sucho (wymagany z --apply)"
    )
    args = parser.parse_args(argv)

    async with AsyncSessionLocal() as db:
        items = await plan(db)
        all_ids = [i for ids in items["by_connection"].values() for i in ids]
        print_fingerprint = fingerprint(all_ids)
        if args.apply and args.expected != print_fingerprint:
            print(
                f"Odcisk {print_fingerprint} różny od --expected — przerywam.",
                file=sys.stderr,
            )
            return 2

        counts: Counter = Counter()
        filled: list[int] = []
        for connection_id, email_ids in items["by_connection"].items():
            one, ids = await refetch_connection(
                db, connection_id, email_ids, apply=args.apply
            )
            counts.update(one)
            filled += ids
        if args.apply:
            await save_receipt(db, counts=counts, filled=filled)
    await engine.dispose()

    print(
        json.dumps(
            {
                "mode": "apply" if args.apply else "dry-run",
                "fingerprint": print_fingerprint,
                "planned": len(all_ids),
                "mailboxes": len(items["by_connection"]),
                "skipped_no_connection": items["no_connection"],
                "skipped_without_sender": items["without_sender"],
                **counts,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
