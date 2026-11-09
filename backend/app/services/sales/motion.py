"""„Sales Motion” z Atlasa przy szansie: Fabryki IT, MEDDIC, produkty (odczyt).

Import z Atlasa kładzie ``custom_fields`` szansy pod kluczem ``atlas``
(``it_factory``, ``meddic``, ``products``, ``subscription_items``). Karta szansy
pokazuje je tak, jak Atlas: mapa decyzyjna z kompletnością liczoną na nowo
(≥3 osoby z nazwiskiem, 5 dat procesu zakupowego — ``src/api/it_factory_schemas.py``
w Atlasie), a każda osoba z mapy wskazuje kontakt w NEXUSIE, jeśli go znamy.
Zapis osób na mapie: ``services/sales/decision_map.py``.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sales import SalesCompanyContact, SalesContact

DECISION_MAP_REQUIRED = 3
PURCHASING_MILESTONE_SLOTS: tuple[str, ...] = (
    "vendor_questionnaire_submitted_at",
    "nda_signed_at",
    "added_to_vendor_list_at",
    "next_evaluation_at",
    "next_rfp_expected_at",
)
ATLAS_CONTACT_REF = "atlas:contacts:"


def decision_map_completeness(it_factory: dict[str, Any]) -> int:
    entries = it_factory.get("decision_map") or []
    if not isinstance(entries, list):
        return 0
    return sum(
        1
        for entry in entries
        if isinstance(entry, dict)
        and isinstance(entry.get("name"), str)
        and entry["name"].strip()
    )


def process_completeness(it_factory: dict[str, Any]) -> int:
    process = it_factory.get("purchasing_process") or {}
    milestones = process.get("milestones") if isinstance(process, dict) else None
    if not isinstance(milestones, dict):
        return 0
    return sum(
        1
        for slot in PURCHASING_MILESTONE_SLOTS
        if isinstance(milestones.get(slot), str) and milestones[slot].strip()
    )


def entry_keys(entries: list[dict[str, Any]]) -> list[str]:
    """Klucz każdej osoby: skrót jej treści, więc każda zmiana zmienia klucz.

    Dwa identyczne wpisy różnią się numerem kolejnym.
    """

    seen: Counter[str] = Counter()
    keys = []
    for entry in entries:
        content = json.dumps(entry, sort_keys=True, ensure_ascii=False, default=str)
        seen[content] += 1
        digest = hashlib.sha256(f"{seen[content]}:{content}".encode()).hexdigest()
        keys.append(digest[:16])
    return keys


def _norm(value: Any) -> Optional[str]:
    text = value.strip().lower() if isinstance(value, str) else ""
    return text or None


async def resolve_contacts(
    db: AsyncSession, company_id: int, entries: list[dict[str, Any]]
) -> list[Optional[int]]:
    """Kontakt NEXUSA dla każdej osoby z mapy: id z Atlasa, potem e-mail, potem nazwisko."""

    refs = {
        f"{ATLAS_CONTACT_REF}{entry['contact_id']}"
        for entry in entries
        if entry.get("contact_id")
    }
    by_ref: dict[str, int] = {}
    if refs:
        by_ref = {
            ref: contact_id
            for contact_id, ref in (
                await db.execute(
                    select(SalesContact.id, SalesContact.external_ref).where(
                        SalesContact.external_ref.in_(refs)
                    )
                )
            ).all()
        }
    linked = select(SalesCompanyContact.contact_id).where(
        SalesCompanyContact.company_id == company_id
    )
    company_contacts = (
        await db.execute(
            select(SalesContact.id, SalesContact.email, SalesContact.full_name)
            .where(
                or_(
                    SalesContact.company_id == company_id,
                    SalesContact.id.in_(linked),
                )
            )
            .order_by(SalesContact.archived_at.is_not(None), SalesContact.id)
        )
    ).all()
    by_email: dict[str, int] = {}
    by_name: dict[str, int] = {}
    for contact_id, email, full_name in company_contacts:
        if (key := _norm(email)) is not None:
            by_email.setdefault(key, contact_id)
        if (key := _norm(full_name)) is not None:
            by_name.setdefault(key, contact_id)

    resolved: list[Optional[int]] = []
    for entry in entries:
        ref = (
            f"{ATLAS_CONTACT_REF}{entry['contact_id']}"
            if entry.get("contact_id")
            else None
        )
        found = by_ref.get(ref) if ref else None
        if found is None and (email := _norm(entry.get("email"))) is not None:
            found = by_email.get(email)
        if found is None and (name := _norm(entry.get("name"))) is not None:
            found = by_name.get(name)
        resolved.append(found)
    return resolved


async def _fill_from_contacts(db: AsyncSession, entries: list[dict[str, Any]]) -> None:
    """Puste dane osoby z mapy uzupełnia z jej kontaktu; wpis z Atlasa ma pierwszeństwo."""

    ids = {entry["nexus_contact_id"] for entry in entries if entry["nexus_contact_id"]}
    if not ids:
        return
    contacts = {
        contact.id: contact
        for contact in (
            await db.execute(select(SalesContact).where(SalesContact.id.in_(ids)))
        ).scalars()
    }
    for entry in entries:
        contact = contacts.get(entry["nexus_contact_id"])
        if contact is None:
            continue
        if contact.do_not_contact_at is not None:
            entry["do_not_contact"] = True
        values = {
            "email": contact.email,
            "phone": contact.phone or contact.mobile_phone,
            "linkedin_url": contact.linkedin_url,
            "notes": contact.notes,
        }
        for field, value in values.items():
            if value and not entry.get(field):
                entry[field] = value
                # Formularz pokazuje to jako podpowiedź, nie jako wartość z mapy.
                entry["from_contact"].append(field)


async def build_atlas_motion(
    db: AsyncSession, *, company_id: int, custom_fields: Optional[dict[str, Any]]
) -> Optional[dict[str, Any]]:
    """``None``, gdy szansa nie ma z Atlasa niczego z „Sales Motion”."""

    atlas = (custom_fields or {}).get("atlas")
    if not isinstance(atlas, dict):
        return None
    it_factory = atlas.get("it_factory")
    meddic = atlas.get("meddic")
    products = atlas.get("products")
    subscription_items = atlas.get("subscription_items")
    it_factory = dict(it_factory) if isinstance(it_factory, dict) else None
    meddic = dict(meddic) if isinstance(meddic, dict) else None
    products = (
        [str(p) for p in products if p not in (None, "")]
        if isinstance(products, list)
        else []
    )
    subscription_items = (
        [item for item in subscription_items if isinstance(item, dict)]
        if isinstance(subscription_items, list)
        else []
    )
    if (
        it_factory is None
        and meddic is None
        and not products
        and not subscription_items
    ):
        return None

    if it_factory is not None:
        raw_entries = it_factory.get("decision_map")
        entries = (
            [dict(e) for e in raw_entries if isinstance(e, dict)]
            if isinstance(raw_entries, list)
            else []
        )
        # Klucz liczony z treści zapisanej, zanim dojdą pola wyliczane przy odczycie.
        keys = entry_keys(entries)
        contact_ids = await resolve_contacts(db, company_id, entries)
        for entry, key, contact_id in zip(entries, keys, contact_ids):
            entry["key"] = key
            entry["nexus_contact_id"] = contact_id
            entry["from_contact"] = []
            entry["do_not_contact"] = bool(entry.get("do_not_contact"))
        await _fill_from_contacts(db, entries)
        it_factory["decision_map"] = entries
        it_factory["decision_map_completeness"] = decision_map_completeness(it_factory)
        it_factory["decision_map_required"] = DECISION_MAP_REQUIRED
        it_factory["process_completeness"] = process_completeness(it_factory)
        it_factory["process_completeness_max"] = len(PURCHASING_MILESTONE_SLOTS)
    return {
        "it_factory": it_factory,
        "meddic": meddic,
        "products": products,
        "subscription_items": subscription_items,
    }
