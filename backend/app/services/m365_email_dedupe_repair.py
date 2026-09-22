"""Jednorazowe scalenie zdublowanych maili M365 (INT-14, audyt 22.09.2026).

Do 09.2026 wysyłka z NEXUSA zapisywała identyfikator SZKICU jako trwałe ID
wiadomości, a synchronizacja dopasowywała wiersze wyłącznie po tym ID. Po
przeniesieniu szkicu do Wysłanych Graph nadaje nowe ID, więc delta zakładała
drugi wiersz tej samej wiadomości (na produkcji: każdy mail wysłany z NEXUSA
i ~35 grup łącznie). Od tej zmiany sync dopasowuje po ``internetMessageId``
(``sync._adopt_by_internet_message_id``); ten moduł sprząta to, co już jest.

Grupa = ta sama skrzynka (``user_id``) i ten sam ``m365_internet_message_id``.
Zostaje jeden wiersz: ten z kluczem wysyłki (``idempotency_key`` — ślad
wysyłki z NEXUSA), a bez niego najstarszy. Wiersz zachowany:

* przejmuje aktualne ID Graph z najnowszego wiersza grupy (to on przyszedł
  z synchronizacji po przeniesieniu — stare ID szkicu dawało 404);
* przejmuje powiązanie z kandydatem, gdy sam go nie ma;
* przejmuje załączniki duplikatów, których jeszcze nie ma (ta sama nazwa
  i rozmiar = ten sam plik; powtórki giną razem z duplikatem, CASCADE);
* przejmuje odwołania z ``scheduled_rejection_emails.email_id``.

Katalog kluczy obcych do ``emails`` jest czytany z bazy: tabela spoza znanej
listy zatrzymuje sprzątanie bez zapisu (marker nie powstaje, log mówi dlaczego).
Blok jest jednorazowy (marker w ``app_settings`` + advisory lock) i odpalany
z ``entrypoint.sh``; paragon niesie wyłącznie liczby i ID.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting

logger = logging.getLogger(__name__)

REPAIR_MARKER = "0342_m365_email_dedupe"

# Klucze obce do ``emails.id`` obsłużone przez sprzątanie (tabela, kolumna).
KNOWN_EMAIL_FKS = frozenset(
    {
        ("email_attachments", "email_id"),
        ("scheduled_rejection_emails", "email_id"),
    }
)

_GROUPS_SQL = text(
    """
    SELECT user_id,
           m365_internet_message_id,
           array_agg(id ORDER BY (idempotency_key IS NULL), id) AS ids
      FROM emails
     WHERE m365_internet_message_id IS NOT NULL
     GROUP BY user_id, m365_internet_message_id
    HAVING count(*) > 1
     ORDER BY min(id)
    """
)

_FK_CATALOG_SQL = text(
    """
    SELECT child.relname AS table_name, att.attname AS column_name
      FROM pg_constraint con
      JOIN pg_class parent ON parent.oid = con.confrelid
      JOIN pg_class child ON child.oid = con.conrelid
      JOIN pg_attribute att
        ON att.attrelid = con.conrelid AND att.attnum = con.conkey[1]
     WHERE con.contype = 'f' AND parent.relname = 'emails'
    """
)


async def _unknown_fks(db: AsyncSession) -> list[str]:
    rows = (await db.execute(_FK_CATALOG_SQL)).all()
    return sorted(
        f"{row.table_name}.{row.column_name}"
        for row in rows
        if (row.table_name, row.column_name) not in KNOWN_EMAIL_FKS
    )


async def _merge_group(db: AsyncSession, ids: list[int]) -> dict[str, Any]:
    keep_id, drop_ids = ids[0], ids[1:]
    newest_id = max(ids)

    # Załączniki duplikatów, których zachowany wiersz jeszcze nie ma.
    moved = await db.execute(
        text(
            """
            UPDATE email_attachments a
               SET email_id = :keep
             WHERE a.email_id = ANY(:drop)
               AND NOT EXISTS (
                   SELECT 1 FROM email_attachments k
                    WHERE k.email_id = :keep
                      AND k.filename = a.filename
                      AND k.size_bytes = a.size_bytes
               )
               AND a.id = (
                   SELECT min(b.id) FROM email_attachments b
                    WHERE b.email_id = ANY(:drop)
                      AND b.filename = a.filename
                      AND b.size_bytes = a.size_bytes
               )
            """
        ),
        {"keep": keep_id, "drop": drop_ids},
    )
    rejections = await db.execute(
        text(
            "UPDATE scheduled_rejection_emails SET email_id = :keep "
            "WHERE email_id = ANY(:drop)"
        ),
        {"keep": keep_id, "drop": drop_ids},
    )
    # Pola przejmowane przed usunięciem duplikatów (UNIQUE na m365_message_id
    # pozwala przepisać ID dopiero po DELETE — stąd odczyt do zmiennych).
    newest = (
        await db.execute(
            text(
                "SELECT m365_message_id, m365_conversation_id FROM emails "
                "WHERE id = :id"
            ),
            {"id": newest_id},
        )
    ).one()
    candidate = await db.scalar(
        text(
            "SELECT candidate_id FROM emails WHERE id = ANY(:ids) "
            "AND candidate_id IS NOT NULL ORDER BY (id = :keep) DESC, id LIMIT 1"
        ),
        {"ids": ids, "keep": keep_id},
    )
    await db.execute(
        text("DELETE FROM emails WHERE id = ANY(:drop)"), {"drop": drop_ids}
    )
    await db.execute(
        text(
            """
            UPDATE emails
               SET m365_message_id = :message_id,
                   m365_conversation_id = CASE
                       WHEN left(m365_conversation_id, 8) = 'pending:'
                       THEN :conversation_id ELSE m365_conversation_id END,
                   candidate_id = COALESCE(candidate_id, :candidate_id),
                   send_state = CASE
                       WHEN send_state IN ('pending', 'uncertain') THEN 'sent'
                       ELSE send_state END
             WHERE id = :keep
            """
        ),
        {
            "keep": keep_id,
            "message_id": newest.m365_message_id,
            "conversation_id": newest.m365_conversation_id,
            "candidate_id": candidate,
        },
    )
    return {
        "kept_id": keep_id,
        "deleted_ids": drop_ids,
        "attachments_moved": moved.rowcount or 0,
        "rejection_links_moved": rejections.rowcount or 0,
    }


async def run_m365_email_dedupe_repair(
    db: AsyncSession, *, marker: str = REPAIR_MARKER
) -> Optional[dict[str, Any]]:
    """Scal duplikaty. ``None`` = już było. Wołający commituje."""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": marker}
    )
    await db.execute(text("SET LOCAL lock_timeout = '15s'"))
    if await db.get(AppSetting, marker) is not None:
        return None

    unknown = await _unknown_fks(db)
    if unknown:
        # Nowa tabela wskazująca na maile — usunięcie duplikatu zabrałoby jej
        # wiersze (CASCADE) albo wywróciło DELETE. Bez markera: po dopisaniu
        # jej do KNOWN_EMAIL_FKS następny start spróbuje ponownie.
        raise RuntimeError(f"unknown FK to emails: {', '.join(unknown)}")

    groups = (await db.execute(_GROUPS_SQL)).all()
    merged = [await _merge_group(db, list(row.ids)) for row in groups]
    summary: dict[str, Any] = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "groups": len(merged),
        "rows_deleted": sum(len(item["deleted_ids"]) for item in merged),
        "attachments_moved": sum(item["attachments_moved"] for item in merged),
        "rejection_links_moved": sum(item["rejection_links_moved"] for item in merged),
        "merged": merged,
    }
    db.add(AppSetting(key=marker, value=summary))
    await db.flush()
    logger.info(
        "m365 email dedupe: %s groups, %s rows deleted",
        summary["groups"],
        summary["rows_deleted"],
    )
    return summary


def summarize_for_log(summary: Optional[dict[str, Any]]) -> str:
    if summary is None:
        return "already done"
    return (
        f"groups={summary['groups']} rows_deleted={summary['rows_deleted']} "
        f"attachments_moved={summary['attachments_moved']} "
        f"rejection_links_moved={summary['rejection_links_moved']}"
    )
