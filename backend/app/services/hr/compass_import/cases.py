"""Import skrzynki administracja@ z Compassa do „Spraw” NEXUSA.

Tabele Compassa: ``support_tickets`` (tylko kategorie ``inbox_%``; słownik
``support_categories`` daje ``slug``), ``support_inbox_meta`` (priorytet,
terminy, checklista, dane konsultanta), ``support_ticket_comments``,
``support_inbox_email_archive`` (treść maili ze starego auto-importu).

Reguły:

* sprawa → ``admin_cases`` z ``source = 'compass_import'`` i
  ``source_key = 'compass:<uuid>'``; obszar z kategorii (``inbox_onboarding``
  → onboarding, ``inbox_wypowiedzenie`` → offboarding, ``inbox_negocjacje``
  → negocjacje, kategorie marketingu → marketing, ``inbox_inne`` → inne),
  priorytet P1–P3, status kanbanu; ``closed_at`` stoi tylko przy sprawie
  zrobionej albo zamkniętej (Compass trzymał ``resolved_at`` osobno od statusu),
* komentarze → ``admin_case_comments``, mail z archiwum →
  ``admin_case_messages`` (treść tekstowa po oczyszczeniu),
* kolejny import dokłada brakujące komentarze i maile; nagłówka sprawy
  zmienionej w NEXUSIE nie nadpisuje (pozycja „conflict”),
* rozmowy kontraktorów (``contractor_%``) i helpdesk zostają w Compassie,
* bez powiadomień.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Mapping, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_case import AdminCase, AdminCaseComment, AdminCaseMessage
from app.models.hr_ops import HrImportBatch
from app.services.admin_cases import rules
from app.services.admin_cases_schema import PRIORITIES, TERMINAL_STATUSES

from .bundle import Bundle
from .common import (
    ImportPlan,
    People,
    changed_fields,
    join_notes,
    load_people,
    local_date,
    parse_date,
    parse_datetime,
    parse_uuid,
    source_id,
    text,
)
from .core import ModulePlan, RowPlan, remember

MODULE = "cases"
TICKETS = "support_tickets"

AREA_BY_SLUG: dict[str, str] = {
    "inbox_onboarding": "onboarding",
    "inbox_offboarding": "offboarding",
    "inbox_wypowiedzenie": "offboarding",
    "inbox_negocjacje": "negotiation",
    "inbox_administracja": "administration",
    "inbox_marketing": "marketing",
    "inbox_grafika": "marketing",
    "inbox_publikacja": "marketing",
    "inbox_wydarzenie": "marketing",
    "inbox_kampania": "marketing",
    "inbox_inne": "other",
}
STATUS_MAP: dict[str, str] = {
    "open": "new",
    "in_progress": "in_progress",
    "waiting_user": "waiting",
    "resolved": "done",
    "closed": "closed",
}
#: Priorytet helpdesku, gdy sprawa nie ma metadanych skrzynki.
LEGACY_PRIORITY: dict[str, str] = {
    "urgent": "P1",
    "high": "P1",
    "normal": "P2",
    "low": "P3",
}
HEADER_FIELDS = (
    "title",
    "area",
    "priority",
    "status",
    "due_on",
    "follow_up_on",
    "assignee_user_id",
    "checklist",
    "description",
    "subject_user_id",
    "closed_at",
)


def _slug(row: Mapping[str, Any], categories: Mapping[str, str]) -> str:
    return str(
        row.get("category_slug") or categories.get(str(row.get("category_id"))) or ""
    )


def _description(row: Mapping[str, Any], meta: Mapping[str, Any]) -> Optional[str]:
    parts: list[str] = []
    body = text(row.get("body_md"))
    if body:
        parts.append(body)
    waiting = text(meta.get("waiting_for"))
    if waiting:
        parts.append(f"Czeka na: {waiting}")
    person = [
        value
        for value in (
            text(meta.get("consultant_name")),
            text(meta.get("consultant_phone")),
        )
        if value
    ]
    client = text(meta.get("client_name"))
    if person or client:
        line = "Konsultant: " + (" · ".join(person) if person else "—")
        if client:
            line += f" · klient: {client}"
        parts.append(line)
    materials = [
        f"- {text(item.get('label')) or 'link'}: {text(item.get('url'))}"
        for item in meta.get("materials") or []
        if isinstance(item, dict) and text(item.get("url"))
    ]
    if materials:
        parts.append("Materiały:\n" + "\n".join(materials))
    return "\n\n".join(parts) or None


def _comment(row: Mapping[str, Any], people: People) -> Optional[dict[str, Any]]:
    body = text(row.get("body_md"))
    if body is None:
        return None
    return {
        "author_user_id": people.account(row.get("author_id")),
        "body": body,
        "created_at": parse_datetime(row.get("created_at")),
    }


def _message(
    ticket_id: str, meta: Mapping[str, Any], archive: Mapping[str, Any]
) -> dict[str, Any]:
    plain = archive.get("email_body_text")
    body = (
        rules.body_to_text(plain, "text")
        if text(plain)
        else rules.body_to_text(archive.get("email_body_html"), "html")
    )
    return {
        "graph_message_id": (
            text(meta.get("external_message_id"), 512) or f"compass:{ticket_id}"
        ),
        "conversation_id": text(archive.get("external_conversation_id"), 512),
        "sender_email": text(meta.get("email_from"), 320),
        "subject": text(meta.get("email_subject"), 500),
        "received_at": parse_datetime(meta.get("email_received_at")),
        "body_text": body,
        "attachments": [],
    }


async def plan(db: AsyncSession, bundle: Bundle) -> ModulePlan:
    result = ImportPlan(module=MODULE)
    people = await load_people(db, bundle)
    categories = {
        str(row.get("id")): str(row.get("slug") or "")
        for row in bundle.rows("support_categories")
    }
    metas = {
        str(row.get("ticket_id")): row for row in bundle.rows("support_inbox_meta")
    }
    archives = {
        str(row.get("ticket_id")): row
        for row in bundle.rows("support_inbox_email_archive")
    }
    comments: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in bundle.rows("support_ticket_comments"):
        comments[str(row.get("ticket_id"))].append(row)

    for row in bundle.rows(TICKETS):
        sid = source_id(TICKETS, row)
        ticket_id = str(row.get("id"))
        if parse_uuid(row.get("id")) is None:
            result.rows.append(RowPlan(sid, "skip", "wiersz bez id"))
            continue
        slug = _slug(row, categories)
        if slug.startswith("contractor_"):
            result.rows.append(
                RowPlan(sid, "skip", "rozmowa kontraktora — skasowana w Compassie")
            )
            continue
        if not slug.startswith("inbox_"):
            result.rows.append(
                RowPlan(sid, "skip", "zgłoszenie spoza skrzynki administracja@")
            )
            continue
        notes: list[str] = []
        meta = metas.get(ticket_id, {})
        area = AREA_BY_SLUG.get(slug, "other")
        if area in ("administration", "other") and meta.get("work_area") == "marketing":
            area = "marketing"
        priority = meta.get("priority_level")
        if priority not in PRIORITIES:
            priority = LEGACY_PRIORITY.get(str(row.get("priority")), "P2")
        status = STATUS_MAP.get(str(row.get("status")), "new")
        closed_at: Optional[datetime] = None
        if status in TERMINAL_STATUSES:
            closed_at = (
                parse_datetime(row.get("resolved_at"))
                or parse_datetime(row.get("updated_at"))
                or parse_datetime(row.get("created_at"))
            )
            if closed_at is None:
                result.rows.append(
                    RowPlan(sid, "skip", "sprawa zamknięta bez żadnej daty")
                )
                continue
        elif row.get("resolved_at"):
            notes.append("data rozwiązania przy sprawie otwartej — pominięta")
        try:
            checklist = rules.normalize_checklist(meta.get("checklist") or [])
        except rules.ChecklistError:
            checklist = []
            notes.append("checklista niepoprawna — pominięta")
        header = {
            "title": rules.case_title_from_subject(row.get("subject")),
            "area": area,
            "priority": priority,
            "status": status,
            "due_on": parse_date(meta.get("planned_due_date"))
            or local_date(meta.get("due_date")),
            "follow_up_on": parse_date(meta.get("follow_up_date")),
            "assignee_user_id": people.account(row.get("assignee_id")),
            "checklist": checklist,
            "description": _description(row, meta),
            "subject_user_id": people.account(meta.get("consultant_id")),
            "closed_at": closed_at,
        }
        case_comments = [
            comment
            for comment in (_comment(item, people) for item in comments[ticket_id])
            if comment is not None
        ]
        messages = (
            [_message(ticket_id, meta, archives[ticket_id])]
            if ticket_id in archives
            else []
        )
        payload = {
            "header": header,
            "source_key": f"compass:{ticket_id}",
            "created_by": people.account(row.get("user_id")),
            "created_at": parse_datetime(row.get("created_at")),
            "comments": case_comments,
            "messages": messages,
        }
        reason = join_notes(notes)
        existing = await db.scalar(
            select(AdminCase).where(AdminCase.source_key == payload["source_key"])
        )
        if existing is None:
            taken = [
                message["graph_message_id"]
                for message in messages
                if await db.scalar(
                    select(AdminCaseMessage.id).where(
                        AdminCaseMessage.graph_message_id == message["graph_message_id"]
                    )
                )
                is not None
            ]
            if taken:
                result.rows.append(
                    RowPlan(sid, "conflict", "mail tej sprawy jest już w innej sprawie")
                )
                continue
            result.rows.append(RowPlan(sid, "create", reason, payload))
            continue
        payload["case_id"] = existing.id
        if changed_fields(existing, header):
            result.rows.append(
                RowPlan(
                    sid,
                    "conflict",
                    "sprawa zmieniona w NEXUSIE albo w Compassie — nagłówek bez nadpisania",
                    payload,
                )
            )
            continue
        known_comments = {
            (comment.body, comment.created_at)
            for comment in await db.scalars(
                select(AdminCaseComment).where(AdminCaseComment.case_id == existing.id)
            )
        }
        payload["comments"] = [
            comment
            for comment in case_comments
            if (comment["body"], comment["created_at"]) not in known_comments
        ]
        known_messages = set(
            await db.scalars(
                select(AdminCaseMessage.graph_message_id).where(
                    AdminCaseMessage.graph_message_id.in_(
                        [message["graph_message_id"] for message in messages]
                    )
                )
            )
        )
        payload["messages"] = [
            message
            for message in messages
            if message["graph_message_id"] not in known_messages
        ]
        action = "update" if payload["comments"] or payload["messages"] else "unchanged"
        result.rows.append(RowPlan(sid, action, reason, payload))
    return result


async def apply(
    db: AsyncSession,
    module_plan: ModulePlan,
    batch: HrImportBatch,
    actor_user_id: Optional[int],
) -> dict[str, int]:
    written = {"cases_created": 0, "comments_written": 0, "messages_written": 0}
    for row in module_plan.rows:
        if row.action not in ("create", "update"):
            continue
        payload = row.payload
        if row.action == "create":
            case = AdminCase(
                source="compass_import",
                source_key=payload["source_key"],
                created_by=payload["created_by"],
                **payload["header"],
            )
            if payload["created_at"] is not None:
                case.created_at = payload["created_at"]
            db.add(case)
            await db.flush()
            written["cases_created"] += 1
        else:
            case = await db.get(AdminCase, payload["case_id"])
        for comment in payload["comments"]:
            item = AdminCaseComment(
                case_id=case.id,
                author_user_id=comment["author_user_id"],
                body=comment["body"],
            )
            if comment["created_at"] is not None:
                item.created_at = comment["created_at"]
            db.add(item)
        for message in payload["messages"]:
            db.add(AdminCaseMessage(case_id=case.id, **message))
        written["comments_written"] += len(payload["comments"])
        written["messages_written"] += len(payload["messages"])
        await db.flush()
        await remember(
            db,
            module=MODULE,
            source_id=row.source_id,
            target_table="admin_cases",
            target_id=case.id,
            decision="auto",
            batch=batch,
        )
    await db.flush()
    return written
