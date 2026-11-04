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
* bez powiadomień,
* **kontrakt konsultanta** (decyzja 7, 22.10.2026): Compass trzyma przy
  sprawie tylko tekst — imię i nazwisko konsultanta i nazwę klienta
  (``support_inbox_meta``). Sprawa łączy się z kontraktem regułami kart
  z Compassa (``care/card_linking``): klient po nazwie (po scaleniu; kilku
  klientów o tej nazwie — wygrywa ten, u którego osoba ma pewny kontrakt),
  osoba po imieniu i nazwisku, dzień założenia sprawy w okresie umowy.
  Pewny kontrakt = ``contract_id``; niepewny = nic (propozycje liczy odczyt
  sprawy, ``admin_cases/contract_links``). Kontraktu wpisanego w NEXUSIE
  import nie nadpisuje ani nie zeruje.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_case import AdminCase, AdminCaseComment, AdminCaseMessage
from app.models.client import Client
from app.models.hr_ops import HrImportBatch
from app.services.admin_cases import rules
from app.services.admin_cases_schema import PRIORITIES, TERMINAL_STATUSES
from app.services.care import card_linking
from app.services.client_portfolio_import import (
    loose_client_name,
    normalize_client_name,
)

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


#: Słowa bez znaczenia przy porównaniu nazw klientów (jak import kart).
_CLIENT_NOISE_WORDS = frozenset({"ex", "o"})


def _client_words(name: Optional[str]) -> frozenset[str]:
    return frozenset(loose_client_name(name).split()) - _CLIENT_NOISE_WORDS


@dataclass
class ContractLinker:
    """Klient z nazwy Compassa + kontrakt osoby (reguły ``card_linking``)."""

    by_key: dict[str, set[int]]
    by_loose: dict[str, set[int]]
    by_words: dict[frozenset[str], set[int]]
    index: card_linking.ContractIndex

    def client_options(self, name: Optional[str]) -> set[int]:
        for found in (
            self.by_key.get(normalize_client_name(name)),
            self.by_loose.get(loose_client_name(name)),
            self.by_words.get(_client_words(name)),
        ):
            if found:
                return set(found)
        return set()

    def contract_for(
        self, client_name: Optional[str], person_name: Optional[str], day: date
    ) -> Optional[int]:
        """Pewny kontrakt albo ``None`` (kilku klientów bez rozstrzygnięcia też)."""

        if not client_name or not person_name:
            return None
        hits = {
            match.contract_id
            for option in self.client_options(client_name)
            if (match := self.index.match(option, person_name, day)).contract_id
        }
        return next(iter(hits)) if len(hits) == 1 else None


async def load_linker(db: AsyncSession) -> ContractLinker:
    finals = await card_linking.final_client_ids(db)
    by_key: dict[str, set[int]] = defaultdict(set)
    by_loose: dict[str, set[int]] = defaultdict(set)
    by_words: dict[frozenset[str], set[int]] = defaultdict(set)
    for client_id, name, display in (
        await db.execute(select(Client.id, Client.name, Client.display_name))
    ).all():
        final = finals.get(client_id, client_id)
        for value in (name, display):
            if normalize_client_name(value):
                by_key[normalize_client_name(value)].add(final)
            if loose_client_name(value):
                by_loose[loose_client_name(value)].add(final)
            if _client_words(value):
                by_words[_client_words(value)].add(final)
    return ContractLinker(
        by_key=dict(by_key),
        by_loose=dict(by_loose),
        by_words=dict(by_words),
        index=await card_linking.load_index(db),
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
    linker: Optional[ContractLinker] = None
    if any(
        text(meta.get("consultant_name")) and text(meta.get("client_name"))
        for meta in metas.values()
    ):
        linker = await load_linker(db)

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
        day = local_date(row.get("created_at"))
        contract_id = (
            linker.contract_for(
                text(meta.get("client_name")), text(meta.get("consultant_name")), day
            )
            if linker is not None and day is not None
            else None
        )
        payload = {
            "header": header,
            "contract_id": contract_id,
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
        # Kontrakt dopisujemy tylko sprawie bez kontraktu — wybór w NEXUSIE
        # (obsługa albo czytnik poczty) wygrywa z późniejszym „pewnym”.
        payload["link_contract"] = (
            existing.contract_id is None and payload["contract_id"] is not None
        )
        action = (
            "update"
            if payload["comments"] or payload["messages"] or payload["link_contract"]
            else "unchanged"
        )
        result.rows.append(RowPlan(sid, action, reason, payload))
    return result


async def apply(
    db: AsyncSession,
    module_plan: ModulePlan,
    batch: HrImportBatch,
    actor_user_id: Optional[int],
) -> dict[str, int]:
    written = {
        "cases_created": 0,
        "comments_written": 0,
        "messages_written": 0,
        "contracts_linked": 0,
    }
    for row in module_plan.rows:
        if row.action not in ("create", "update"):
            continue
        payload = row.payload
        if row.action == "create":
            case = AdminCase(
                source="compass_import",
                source_key=payload["source_key"],
                created_by=payload["created_by"],
                contract_id=payload.get("contract_id"),
                **payload["header"],
            )
            if payload["created_at"] is not None:
                case.created_at = payload["created_at"]
            db.add(case)
            await db.flush()
            written["cases_created"] += 1
            if case.contract_id is not None:
                written["contracts_linked"] += 1
        else:
            case = await db.get(AdminCase, payload["case_id"])
            if payload.get("link_contract") and case.contract_id is None:
                case.contract_id = payload["contract_id"]
                written["contracts_linked"] += 1
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
