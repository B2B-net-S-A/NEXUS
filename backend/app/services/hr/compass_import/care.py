"""Import mapy technologicznej i rozmów opiekunów z Compassa.

Tabele Compassa: ``tech_interview_cards`` (+ ``tech_interview_card_technologies``,
``tech_interview_card_vendors``, ``tech_interview_card_initiatives``,
``tech_card_sales_status``), słowniki ``technologies``, ``vendors``,
``client_areas``, ``clients``, rejestr ``contractors`` i
``contractor_conversations``.

Połączenie z NEXUSEM (decyzja D7: karta i rozmowa żyją na kontrakcie):

* klient: nazwa klienta Compassa = nazwa (albo nazwa wyświetlana) klienta
  NEXUSA po ``normalize_client_name``; klient scalony → klient docelowy;
  dwa trafienia = brak pewności,
* osoba: WYŁĄCZNIE kotwica z kolejki „Tożsamość NEXUS” Compassa
  (``contractors.nexus_candidate_id``, a bez niej ``nexus_contract_id`` →
  kandydat kontraktu). Po samym imieniu i nazwisku nie łączymy — tak samo
  zdecydował Compass („Name matching is intentionally forbidden”),
* kontrakt: kandydat + klient + okres (dzień rozmowy w trakcie umowy, umowa
  nie anulowana i nie szkic) — dokładnie jeden, inaczej „conflict”.

Karta bez pewnego kontraktu trafia do klienta z pustym ``contract_id``
(schemat dopuszcza to tylko dla importu) jako „conflict” do dopięcia; karta
bez klienta jest pomijana. Rozmowa bez pewnego kontraktu nie przechodzi.
Technologia spoza słownika ``skills`` (nazwa ani alias) idzie do
``skill_review_queue``, a karta trzyma tekst w ``unrecognized_skills``.
Import nie zgłasza „Do przepięcia”, nie zamyka punktów planu i nie wysyła
przypomnień.
"""

from __future__ import annotations

import calendar as month_calendar
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping, Optional

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus
from app.models.contract_care import (
    CareConversation,
    ClientArea,
    SkillReviewItem,
    TechCard,
    TechCardSkill,
    TechCardVendor,
    TechVendor,
)
from app.models.hr_ops import HrImportBatch
from app.services.care import skills as care_skills
from app.services.client_portfolio_import import normalize_client_name
from app.services.contract_care_schema import (
    CARD_STATUSES,
    HIRING_SOURCES,
    NOTE_MAX,
    SALES_STATUSES,
    SHORT_TEXT_MAX,
)

from .bundle import Bundle
from .common import (
    ImportPlan,
    People,
    changed_fields,
    join_notes,
    load_people,
    parse_date,
    parse_datetime,
    parse_uuid,
    small_int,
    source_id,
    text,
)
from .core import ModulePlan, RowPlan, remember

MODULE = "care"
CARDS = "tech_interview_cards"
CONVERSATIONS = "contractor_conversations"

NO_LINK = "kontraktor bez powiązania z NEXUSEM (kolejka „Tożsamość NEXUS”)"
UNSURE_CONTRACT = "kontrakt niepewny — karta przy kliencie, bez kontraktu"
UNKNOWN_SKILL = "technologia spoza słownika — w kolejce do przejrzenia"
_SKIPPED_CONTRACT_STATUSES = (ContractStatus.void, ContractStatus.draft)

CATEGORY_LABELS: dict[str, str] = {
    "szkolenia": "Szkolenia",
    "podwyzka": "Podwyżka",
    "follow_up": "Follow-up",
    "zejscie": "Zejście",
    "przedluzenie": "Przedłużenie",
    "informacyjnie": "Informacyjnie",
    "konferencja": "Konferencja",
    "onboarding": "Onboarding",
    "exit": "Exit",
    "delegacja": "Delegacja",
    "internalizacja": "Internalizacja",
    "zmiana_stawki": "Zmiana stawki",
    "inne": "Inne",
}
STATUS_LABELS: dict[str, str] = {
    "w_toku": "w toku",
    "rozwiazane": "rozwiązane",
    "potrzebny_kontakt": "potrzebny kontakt",
    "pilne": "pilne",
}
CARD_FIELDS = (
    "contract_id",
    "client_id",
    "author_user_id",
    "interview_on",
    "status",
    "is_draft",
    "finalized_at",
    "satisfaction",
    "hiring",
    "hiring_source",
    "hiring_roles",
    "project_end_on",
    "project_end_unknown",
    "team_size",
    "team_externals",
    "initiatives",
    "memorable_quote",
    "note",
    "sales_status",
    "sales_deal_title",
    "sales_reason",
    "sales_handled_by",
    "sales_handled_at",
)


@dataclass
class Links:
    """Klienci, kotwice kontraktorów i kontrakty kandydatów (jeden przebieg)."""

    clients_by_key: dict[str, set[int]]
    compass_clients: dict[str, str]
    contractors: dict[str, Mapping[str, Any]]
    contract_candidate: dict[int, Optional[int]] = field(default_factory=dict)
    known_candidates: set[int] = field(default_factory=set)
    contracts: dict[int, list[tuple[int, int, Optional[date], Optional[date]]]] = field(
        default_factory=dict
    )

    def client_for_name(self, name: Optional[str]) -> Optional[int]:
        matches = self.clients_by_key.get(normalize_client_name(name), set())
        return next(iter(matches)) if len(matches) == 1 else None

    def client_for(self, compass_client_id: Any) -> Optional[int]:
        return self.client_for_name(self.compass_clients.get(str(compass_client_id)))

    def candidate_for(self, contractor_id: Any) -> Optional[int]:
        row = self.contractors.get(str(contractor_id)) or {}
        candidate = small_int(row.get("nexus_candidate_id"))
        if candidate is not None and candidate in self.known_candidates:
            return candidate
        contract = small_int(row.get("nexus_contract_id"))
        if contract is not None:
            return self.contract_candidate.get(contract)
        return None

    def contract_for(
        self, candidate_id: int, client_id: Optional[int], day: date
    ) -> tuple[Optional[int], Optional[int]]:
        """(kontrakt, klient) — dokładnie jeden kontrakt w okresie, inaczej pusto."""

        hits = [
            (contract_id, contract_client)
            for contract_id, contract_client, start, end in self.contracts.get(
                candidate_id, []
            )
            if (client_id is None or contract_client == client_id)
            and (start is None or start <= day)
            and (end is None or end >= day)
        ]
        return hits[0] if len(hits) == 1 else (None, None)


async def _links(db: AsyncSession, bundle: Bundle) -> Links:
    clients_by_key: dict[str, set[int]] = defaultdict(set)
    rows = (
        await db.execute(
            select(
                Client.id,
                Client.name,
                Client.display_name,
                Client.merged_into_client_id,
            )
        )
    ).all()
    merged = {client_id: target for client_id, _, _, target in rows}

    def final(client_id: int) -> int:
        seen: set[int] = set()
        while merged.get(client_id) and client_id not in seen:
            seen.add(client_id)
            client_id = merged[client_id]
        return client_id

    for client_id, name, display, _ in rows:
        for value in (name, display):
            key = normalize_client_name(value)
            if key:
                clients_by_key[key].add(final(client_id))

    contractors = {str(row.get("id")): row for row in bundle.rows("contractors")}
    contract_ids = {
        small_int(row.get("nexus_contract_id"))
        for row in contractors.values()
        if small_int(row.get("nexus_contract_id")) is not None
    }
    candidate_ids = {
        small_int(row.get("nexus_candidate_id"))
        for row in contractors.values()
        if small_int(row.get("nexus_candidate_id")) is not None
    }
    links = Links(
        clients_by_key=dict(clients_by_key),
        compass_clients={
            str(row.get("id")): str(row.get("name") or "")
            for row in bundle.rows("clients")
        },
        contractors=contractors,
    )
    if contract_ids:
        links.contract_candidate = dict(
            (
                await db.execute(
                    select(Contract.id, Contract.candidate_id).where(
                        Contract.id.in_(sorted(contract_ids))
                    )
                )
            ).all()
        )
    candidate_ids |= {cid for cid in links.contract_candidate.values() if cid}
    if candidate_ids:
        links.known_candidates = set(
            await db.scalars(
                select(Candidate.id).where(Candidate.id.in_(sorted(candidate_ids)))
            )
        )
        by_candidate: dict[int, list] = defaultdict(list)
        for contract_id, candidate_id, client_id, start, end in (
            await db.execute(
                select(
                    Contract.id,
                    Contract.candidate_id,
                    Contract.client_id,
                    Contract.start_date,
                    Contract.end_date,
                ).where(
                    Contract.candidate_id.in_(sorted(links.known_candidates)),
                    Contract.status.notin_(_SKIPPED_CONTRACT_STATUSES),
                )
            )
        ).all():
            by_candidate[candidate_id].append(
                (contract_id, final(client_id), start, end)
            )
        links.contracts = dict(by_candidate)
    return links


def _month_end(year: Optional[int], month: Optional[int]) -> Optional[date]:
    if year is None or month is None or not (1 <= month <= 12 and 2000 <= year <= 2100):
        return None
    return date(year, month, month_calendar.monthrange(year, month)[1])


def _card_note(row: Mapping[str, Any]) -> Optional[str]:
    labelled = (
        ("Temat", row.get("title")),
        ("Komentarz do zadowolenia", row.get("satisfaction_comment")),
        ("Technologie stare i nowe", row.get("tech_old_new")),
        ("Dostawcy — uwagi", row.get("vendors_note")),
        ("Ubezpieczenie zawodowe", row.get("professional_insurance")),
    )
    lines = [f"{label}: {text(value)}" for label, value in labelled if text(value)]
    return "\n".join(lines) or None


async def _review_mapped(db: AsyncSession) -> dict[str, int]:
    """Nazwy z kolejki, które już zmapowano na umiejętność."""

    rows = await db.execute(
        select(SkillReviewItem.name_key, SkillReviewItem.skill_id).where(
            SkillReviewItem.status.in_(("mapped", "created")),
            SkillReviewItem.skill_id.is_not(None),
        )
    )
    return {key: skill_id for key, skill_id in rows.all()}


async def _plan_cards(
    db: AsyncSession, bundle: Bundle, people: People, links: Links, result: ImportPlan
) -> None:
    dictionary = await care_skills.load_dictionary(db)
    reviewed = await _review_mapped(db)
    technologies = {str(row.get("id")): row for row in bundle.rows("technologies")}
    vendors = {str(row.get("id")): row for row in bundle.rows("vendors")}
    areas = {str(row.get("id")): row for row in bundle.rows("client_areas")}
    card_techs: dict[str, list[str]] = defaultdict(list)
    for row in bundle.rows("tech_interview_card_technologies"):
        card_techs[str(row.get("card_id"))].append(str(row.get("technology_id")))
    card_vendors: dict[str, list[str]] = defaultdict(list)
    for row in bundle.rows("tech_interview_card_vendors"):
        card_vendors[str(row.get("card_id"))].append(str(row.get("vendor_id")))
    initiatives: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in bundle.rows("tech_interview_card_initiatives"):
        name = text(row.get("name"), 200)
        if name:
            initiatives[str(row.get("card_id"))].append(
                {
                    "name": name,
                    "kind": str(row.get("kind") or "inne"),
                    "priority": str(row.get("priority") or "normalny"),
                }
            )
    sales = {
        str(row.get("card_id")): row for row in bundle.rows("tech_card_sales_status")
    }

    for row in bundle.rows(CARDS):
        sid = source_id(CARDS, row)
        card_key = str(row.get("id"))
        compass_card_id = parse_uuid(row.get("id"))
        interview_on = parse_date(row.get("interview_date"))
        if compass_card_id is None or interview_on is None:
            result.rows.append(RowPlan(sid, "skip", "karta bez id albo daty rozmowy"))
            continue
        client_id = links.client_for(row.get("client_id"))
        if client_id is None:
            result.rows.append(
                RowPlan(sid, "skip", "klient karty bez odpowiednika w NEXUSIE")
            )
            continue
        notes: list[str] = []
        candidate_id = links.candidate_for(row.get("contractor_id"))
        contract_id = None
        if candidate_id is not None:
            contract_id, _ = links.contract_for(candidate_id, client_id, interview_on)
        if contract_id is None:
            notes.append(UNSURE_CONTRACT if candidate_id is not None else NO_LINK)

        skill_ids: set[int] = set()
        unrecognized: dict[str, str] = {}
        for tech_id in card_techs[card_key]:
            tech = technologies.get(tech_id) or {}
            name = text(tech.get("name"))
            if not name:
                continue
            candidates = [name, *[str(alias) for alias in tech.get("aliases") or []]]
            found = next(
                (
                    dictionary.resolve(value)
                    for value in candidates
                    if dictionary.resolve(value) is not None
                ),
                None,
            )
            if found is None:
                found = reviewed.get(care_skills.name_key(name))
            if found is not None:
                skill_ids.add(found)
            else:
                unrecognized[care_skills.name_key(name)] = name
        if unrecognized:
            notes.append(UNKNOWN_SKILL)

        is_draft = bool(row.get("is_draft", True))
        status = row.get("status") if row.get("status") in CARD_STATUSES else None
        if not is_draft and status is None:
            is_draft = True
            notes.append("karta gotowa bez statusu — zapisana jako szkic")
        hiring = row.get("hiring") if isinstance(row.get("hiring"), bool) else None
        project_end_unknown = bool(row.get("project_end_unknown"))
        externals = small_int(row.get("team_externals"))
        satisfaction = small_int(row.get("satisfaction"))
        sale = sales.get(card_key, {})
        sales_status = (
            sale.get("status") if sale.get("status") in SALES_STATUSES else None
        )
        area = areas.get(str(row.get("client_area_id"))) or {}
        values = {
            "contract_id": contract_id,
            "client_id": client_id,
            "author_user_id": people.account(row.get("tcm_id"))
            or people.account(row.get("created_by")),
            "interview_on": interview_on,
            "status": status,
            "is_draft": is_draft,
            "finalized_at": None
            if is_draft
            else parse_datetime(row.get("finalized_at")),
            "satisfaction": satisfaction if satisfaction in range(1, 6) else None,
            "hiring": hiring,
            "hiring_source": row.get("hiring_source")
            if hiring is True and row.get("hiring_source") in HIRING_SOURCES
            else None,
            "hiring_roles": [
                role.strip()[:120]
                for role in (row.get("hiring_roles") or [])
                if isinstance(role, str) and role.strip()
            ]
            if hiring is True
            else [],
            "project_end_on": None
            if project_end_unknown
            else _month_end(
                small_int(row.get("project_end_year")),
                small_int(row.get("project_end_month")),
            ),
            "project_end_unknown": project_end_unknown,
            "team_size": text(row.get("team_size"), 80),
            "team_externals": externals
            if externals is not None and 0 <= externals <= 10000
            else None,
            "initiatives": initiatives[card_key],
            "memorable_quote": text(row.get("memorable_quote"), SHORT_TEXT_MAX),
            "note": _card_note(row),
            "sales_status": sales_status,
            "sales_deal_title": text(sale.get("atlas_deal_title"), SHORT_TEXT_MAX)
            if sales_status
            else None,
            "sales_reason": text(sale.get("reason")) if sales_status else None,
            "sales_handled_by": text(sale.get("handled_by_name"), 200)
            if sales_status
            else None,
            "sales_handled_at": parse_datetime(sale.get("handled_at"))
            if sales_status
            else None,
        }
        payload = {
            "compass_card_id": compass_card_id,
            "values": values,
            "skill_ids": sorted(skill_ids),
            "unrecognized": [unrecognized[key] for key in sorted(unrecognized)],
            "vendors": sorted(
                {
                    text((vendors.get(vendor_id) or {}).get("name"), 120) or ""
                    for vendor_id in card_vendors[card_key]
                }
                - {""}
            ),
            "area": text(area.get("name"), 120),
            "created_at": parse_datetime(row.get("created_at")),
        }
        reason = join_notes(notes)
        existing = await db.scalar(
            select(TechCard).where(TechCard.compass_card_id == compass_card_id)
        )
        if existing is None:
            action = "conflict" if contract_id is None or unrecognized else "create"
            payload["write"] = True
            result.rows.append(RowPlan(sid, action, reason, payload))
            continue
        payload["card_id"] = existing.id
        if existing.contract_id is not None and contract_id is None:
            # Kontrakt dopięty w NEXUSIE zostaje (import go nie odpina).
            values["contract_id"] = existing.contract_id
        changed = changed_fields(existing, values)
        same_relations = await _same_relations(db, existing, payload)
        if not changed and same_relations:
            result.rows.append(RowPlan(sid, "unchanged", reason, payload))
        elif changed == ["contract_id"] and same_relations:
            # Kotwica osoby dopisana w Compassie po poprzednim imporcie.
            payload["write"] = True
            result.rows.append(RowPlan(sid, "update", reason, payload))
        else:
            result.rows.append(
                RowPlan(
                    sid,
                    "conflict",
                    "karta zmieniona w NEXUSIE albo w Compassie — bez nadpisania",
                    payload,
                )
            )


async def _same_relations(
    db: AsyncSession, card: TechCard, payload: Mapping[str, Any]
) -> bool:
    skills = sorted(
        await db.scalars(
            select(TechCardSkill.skill_id).where(TechCardSkill.card_id == card.id)
        )
    )
    vendor_keys = sorted(
        await db.scalars(
            select(TechVendor.name_key)
            .join(TechCardVendor, TechCardVendor.vendor_id == TechVendor.id)
            .where(TechCardVendor.card_id == card.id)
        )
    )
    area_key = None
    if card.client_area_id is not None:
        area_key = await db.scalar(
            select(ClientArea.name_key).where(ClientArea.id == card.client_area_id)
        )
    wanted_area = care_skills.name_key(payload["area"]) if payload["area"] else None
    return (
        skills == payload["skill_ids"]
        and vendor_keys == sorted(care_skills.name_key(v) for v in payload["vendors"])
        and area_key == wanted_area
        and sorted(card.unrecognized_skills or [])
        == sorted(care_skills.name_key(v) for v in payload["unrecognized"])
    )


async def _plan_conversations(
    db: AsyncSession, bundle: Bundle, people: People, links: Links, result: ImportPlan
) -> None:
    for row in bundle.rows(CONVERSATIONS):
        sid = source_id(CONVERSATIONS, row)
        occurred_on = parse_date(row.get("conversation_date"))
        if parse_uuid(row.get("id")) is None or occurred_on is None:
            result.rows.append(RowPlan(sid, "skip", "rozmowa bez id albo daty"))
            continue
        candidate_id = links.candidate_for(row.get("contractor_id"))
        if candidate_id is None:
            result.rows.append(RowPlan(sid, "skip", NO_LINK))
            continue
        client_id = links.client_for_name(row.get("client_snapshot"))
        contract_id, _ = links.contract_for(candidate_id, client_id, occurred_on)
        if contract_id is None:
            result.rows.append(RowPlan(sid, "conflict", "kontrakt rozmowy niepewny"))
            continue
        notes: list[str] = []
        follow_up = parse_date(row.get("follow_up_date"))
        if follow_up is not None and follow_up < occurred_on:
            follow_up = None
            notes.append("termin kontaktu przed datą rozmowy — pominięty")
        header = " · ".join(
            value
            for value in (
                CATEGORY_LABELS.get(str(row.get("category"))),
                STATUS_LABELS.get(str(row.get("status"))),
            )
            if value
        )
        body = text(row.get("note"))
        note = "\n\n".join(part for part in (header, body) if part)[:NOTE_MAX] or None
        values = {
            "contract_id": contract_id,
            "author_user_id": people.account(row.get("tcm_id"))
            or people.account(row.get("created_by")),
            "occurred_on": occurred_on,
            "channel": "phone",
            "note": note,
            "follow_up_on": follow_up,
        }
        compass_source_id = str(row.get("id"))
        payload = {
            "compass_source_id": compass_source_id,
            "values": values,
            "created_at": parse_datetime(row.get("created_at")),
        }
        existing = await db.scalar(
            select(CareConversation).where(
                CareConversation.compass_source_id == compass_source_id
            )
        )
        reason = join_notes(notes)
        if existing is None:
            result.rows.append(RowPlan(sid, "create", reason, payload))
            continue
        payload["conversation_id"] = existing.id
        action = "update" if changed_fields(existing, values) else "unchanged"
        result.rows.append(RowPlan(sid, action, reason, payload))


async def plan(db: AsyncSession, bundle: Bundle) -> ModulePlan:
    result = ImportPlan(module=MODULE)
    people = await load_people(db, bundle)
    links = await _links(db, bundle)
    await _plan_cards(db, bundle, people, links, result)
    await _plan_conversations(db, bundle, people, links, result)
    return result


async def _upsert_by_key(
    db: AsyncSession, model, values: dict[str, Any], keys: list[str]
) -> int:
    statement = (
        insert(model)
        .values(**values)
        .on_conflict_do_nothing(index_elements=keys)
        .returning(model.id)
    )
    created = (await db.execute(statement)).scalar_one_or_none()
    if created is not None:
        return created
    query = select(model.id)
    for key in keys:
        query = query.where(getattr(model, key) == values[key])
    return (await db.scalars(query)).one()


async def _write_card(db: AsyncSession, row: RowPlan) -> TechCard:
    payload = row.payload
    values = payload["values"]
    if "card_id" in payload:
        card = await db.get(TechCard, payload["card_id"])
        for key, value in values.items():
            setattr(card, key, value)
    else:
        card = TechCard(compass_card_id=payload["compass_card_id"], **values)
        if payload["created_at"] is not None:
            card.created_at = payload["created_at"]
        db.add(card)
    card.client_area_id = (
        await _upsert_by_key(
            db,
            ClientArea,
            {
                "client_id": values["client_id"],
                "name": payload["area"],
                "name_key": care_skills.name_key(payload["area"]),
            },
            ["client_id", "name_key"],
        )
        if payload["area"]
        else None
    )
    await db.flush()
    resolved = await care_skills.resolve_card_names(
        db,
        payload["unrecognized"],
        previous_unrecognized=card.unrecognized_skills or [],
        actor_id=None,
    )
    card.unrecognized_skills = resolved.unrecognized
    skill_ids = set(payload["skill_ids"]) | resolved.skill_ids
    await db.execute(delete(TechCardSkill).where(TechCardSkill.card_id == card.id))
    if skill_ids:
        await db.execute(
            insert(TechCardSkill).values(
                [{"card_id": card.id, "skill_id": sid} for sid in sorted(skill_ids)]
            )
        )
    vendor_ids = [
        await _upsert_by_key(
            db,
            TechVendor,
            {"name": name, "name_key": care_skills.name_key(name)},
            ["name_key"],
        )
        for name in payload["vendors"]
    ]
    await db.execute(delete(TechCardVendor).where(TechCardVendor.card_id == card.id))
    if vendor_ids:
        await db.execute(
            insert(TechCardVendor).values(
                [
                    {"card_id": card.id, "vendor_id": vid}
                    for vid in sorted(set(vendor_ids))
                ]
            )
        )
    await db.flush()
    return card


async def apply(
    db: AsyncSession,
    module_plan: ModulePlan,
    batch: HrImportBatch,
    actor_user_id: Optional[int],
) -> dict[str, int]:
    written = {
        "cards_written": 0,
        "cards_without_contract": 0,
        "conversations_written": 0,
    }
    for row in module_plan.rows:
        table = row.source_id.split(":", 1)[0]
        if table == CARDS and row.payload.get("write"):
            card = await _write_card(db, row)
            written["cards_written"] += 1
            if card.contract_id is None:
                written["cards_without_contract"] += 1
            target_table, target_id = "tech_cards", card.id
        elif table == CONVERSATIONS and row.action in ("create", "update"):
            payload = row.payload
            if "conversation_id" in payload:
                conversation = await db.get(
                    CareConversation, payload["conversation_id"]
                )
                for key, value in payload["values"].items():
                    setattr(conversation, key, value)
            else:
                conversation = CareConversation(
                    compass_source_id=payload["compass_source_id"], **payload["values"]
                )
                if payload["created_at"] is not None:
                    conversation.created_at = payload["created_at"]
                db.add(conversation)
            await db.flush()
            written["conversations_written"] += 1
            target_table, target_id = "care_conversations", conversation.id
        else:
            continue
        await remember(
            db,
            module=MODULE,
            source_id=row.source_id,
            target_table=target_table,
            target_id=target_id,
            decision="auto",
            batch=batch,
        )
    await db.flush()
    return written
