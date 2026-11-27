"""Krajowy Rejestr Zadłużonych przed podpisem umowy B2B (0800, 27.11.2026).

Decyzje Artura: półautomat (człowiek sprawdza w portalu, NEXUS zapisuje wynik),
NIP i PESEL (PESEL tylko do wyszukania, bez zapisu), wpis zatrzymuje wysyłkę
i „Oznacz jako podpisaną” do decyzji Delivery Leada, trwające kontrakty
później. Część bez bazy sprawdza regułę bramki, część z bazą — trasy.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import select

from app.schemas.b2b_contract_generator import (
    B2BKrzCheckIn,
    B2BKrzDecisionIn,
    B2BRenderRequest,
)
from app.services.b2b_contract_generator import krz

NOW = datetime(2026, 11, 27, 21, 0, tzinfo=timezone.utc)


def _row(**over):
    base = dict(
        id=1,
        source="generator",
        contract_kind=None,
        signature_status="unsigned",
        contract_status="in_progress",
        partner_nip="5214188498",
        krz_check=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _check(result="clear", *, nip="5214188498", decision=None, kind=None):
    check = krz.new_check(
        result=result,
        entry_kind=kind or ("enforcement" if result == "entry" else None),
        entry_note="Km 123/24" if result == "entry" else None,
        nip=nip,
        actor_id=7,
        now=NOW,
    )
    if decision:
        check = krz.with_decision(
            check, decision=decision, reason="spłacone", actor_id=8, now=NOW
        )
    return check


# ── Reguła bramki (bez bazy) ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "check,expected",
    [
        (None, krz.MSG_NOT_CHECKED),
        (_check("clear"), None),
        (_check("entry"), krz.MSG_WAITING_DECISION),
        (_check("entry", decision="allowed"), None),
        (_check("entry", decision="rejected"), krz.MSG_REJECTED),
    ],
)
def test_gate_follows_the_check_and_the_decision(check, expected):
    assert krz.block_reason(_row(krz_check=check), from_mass_send=False) == expected


@pytest.mark.parametrize(
    "over",
    [
        {"contract_kind": "mandate"},
        {"source": "excel"},
        {"signature_status": "signed_both"},
    ],
)
def test_rows_outside_the_rule_are_never_blocked(over):
    assert krz.block_reason(_row(**over), from_mass_send=False) is None


def test_new_agreement_for_active_contractors_is_not_blocked():
    # Trwające kontrakty: „później, z API” (decyzja 27.11.2026).
    assert krz.block_reason(_row(), from_mass_send=True) is None
    assert not krz.applies(_row(), from_mass_send=True)


def test_changed_nip_voids_the_result():
    row = _row(partner_nip="7331345328", krz_check=_check("clear"))
    assert krz.current_check(row) is None
    assert krz.nip_changed(row)
    assert krz.block_reason(row, from_mass_send=False) == krz.MSG_NIP_CHANGED
    # NIP w innym zapisie to ten sam numer.
    assert krz.current_check(_row(partner_nip="521-418-84-98", krz_check=_check()))


def test_clear_result_drops_entry_details_and_note_is_trimmed():
    clear = krz.new_check(
        result="clear",
        entry_kind="bankruptcy",
        entry_note="x",
        nip="521-418-84-98",
        actor_id=1,
        now=NOW,
    )
    assert clear["entry_kind"] is None and clear["entry_note"] is None
    assert clear["nip"] == "5214188498"
    entry = krz.new_check(
        result="entry",
        entry_kind="bankruptcy",
        entry_note="  " + "a" * 400,
        nip=None,
        actor_id=1,
        now=NOW,
    )
    assert len(entry["entry_note"]) == krz.ENTRY_NOTE_MAX


def test_same_result_is_not_recorded_twice():
    assert krz.same_result(_check("clear"), _check("clear"))
    assert not krz.same_result(_check("clear"), _check("entry"))
    assert not krz.same_result(_check("clear"), _check("clear", nip="7331345328"))


def test_entry_needs_a_kind_and_decision_needs_a_reason():
    with pytest.raises(ValidationError):
        B2BKrzCheckIn(result="entry")
    assert B2BKrzCheckIn(result="clear").entry_kind is None
    with pytest.raises(ValidationError):
        B2BKrzDecisionIn(decision="allowed", reason="   ")


def test_pesel_has_no_place_in_the_api():
    # PESEL zostaje w przeglądarce (RODO): ani pole, ani zapis w umowie.
    assert "pesel" not in B2BKrzCheckIn.model_fields
    check = B2BKrzCheckIn.model_validate({"result": "clear", "pesel": "44051401359"})
    assert "pesel" not in check.model_dump()
    assert "pesel" not in _check("entry")


def test_render_payload_does_not_keep_the_krz_result():
    payload = B2BRenderRequest(
        partner_name="Ewa Test",
        client_name="Klient",
        krz_check={"result": "clear"},
    )
    assert "krz_check" not in payload.model_dump(mode="json", exclude={"krz_check"})


def test_bell_types_are_registered_everywhere():
    from app.models.notification import NotificationType as T
    from app.services.notification_access import NOTIFICATION_SECTION_BY_TYPE
    from app.services.notification_categories import (
        CATEGORY_BY_TYPE,
        NotificationCategory,
    )
    from app.services.notification_substitution import CURRENT_WORK_TYPES
    from app.services.notification_topics import TOPIC_BY_TYPE
    from app.services.section_permissions import ProductSection

    for ntype in (T.b2b_krz_entry, T.b2b_krz_allowed):
        assert CATEGORY_BY_TYPE[ntype] is NotificationCategory.mentions
        assert ntype in TOPIC_BY_TYPE
    assert NOTIFICATION_SECTION_BY_TYPE[T.b2b_krz_entry] is ProductSection.sourcing
    assert NOTIFICATION_SECTION_BY_TYPE[T.b2b_krz_allowed] is ProductSection.delivery
    # Na decyzję czeka umowa — przy urlopie DL-a dzwonek idzie do zastępcy.
    assert T.b2b_krz_entry in CURRENT_WORK_TYPES


# ── Trasy (z bazą) ───────────────────────────────────────────────────────────

PATH = "/api/b2b-generator/generated"


async def _seed_row(*, author_id: int, dl_id: int) -> dict:
    from app.core.database import AsyncSessionLocal
    from app.models.b2b_generated_contract import B2BGeneratedContract
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.team_structure import DeliveryLeadClientAssignment

    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"KRZ {unique}")
        candidate = Candidate(
            name="Ewa", lastname=f"Krz{unique}", email=f"krz-{unique}@example.com"
        )
        db.add_all([client, candidate])
        await db.flush()
        job = Job(
            title=f"Java {unique}",
            status=JobStatus.published,
            client_id=client.id,
            recruiter_id=author_id,
            delivery_lead_id=dl_id,
        )
        db.add(job)
        db.add(
            DeliveryLeadClientAssignment(
                delivery_lead_user_id=dl_id, client_id=client.id, is_head=True
            )
        )
        await db.flush()
        seq = int(uuid.uuid4().int % 900_000) + 100_000
        row = B2BGeneratedContract(
            year=2099,
            seq=seq,
            contract_number=f"{seq}/2099",
            partner_name=f"Ewa Krz{unique}",
            partner_nip="5214188498",
            client_id=client.id,
            client_name=client.name,
            candidate_id=candidate.id,
            job_id=job.id,
            created_by=author_id,
            contract_status="in_progress",
            signature_status="unsigned",
            render_payload={"partner_name": f"Ewa Krz{unique}"},
        )
        db.add(row)
        await db.commit()
        return {"generated_id": row.id, "number": row.contract_number}


@pytest.fixture
async def world(app_client: AsyncClient) -> dict:
    from tests.test_b2b_generator_rate_visibility import _seed_user

    author_h, author_id = await _seed_user(app_client, "recruiter")
    outsider_h, _ = await _seed_user(app_client, "recruiter")
    dl_h, dl_id = await _seed_user(app_client, "delivery_lead")
    finance_h, finance_id = await _seed_user(app_client, "finance")
    seeded = await _seed_row(author_id=author_id, dl_id=dl_id)
    return {
        **seeded,
        "author": author_h,
        "author_id": author_id,
        "outsider": outsider_h,
        "dl": dl_h,
        "dl_id": dl_id,
        "finance_id": finance_id,
    }


async def _bells(user_id: int, ntype: str, generated_id: int) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.notification import Notification, NotificationType

    async with AsyncSessionLocal() as db:
        found = await db.scalars(
            select(Notification.id).where(
                Notification.user_id == user_id,
                Notification.notification_type == NotificationType(ntype),
                Notification.related_entity_id == generated_id,
            )
        )
        return len(found.all())


async def _row_from_list(app_client, world, who="author") -> dict:
    resp = await app_client.get(PATH, params={"q": world["number"]}, headers=world[who])
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"] if isinstance(resp.json(), dict) else resp.json()
    return next(i for i in items if i["id"] == world["generated_id"])


@pytest.mark.asyncio
async def test_unchecked_agreement_waits_for_krz_and_a_clear_result_releases_it(
    app_client, world
):
    gid = world["generated_id"]
    item = await _row_from_list(app_client, world)
    assert item["krz"]["required"] is True
    assert item["krz"]["block_reason"] == krz.MSG_NOT_CHECKED
    assert item["krz"]["can_record"] is True
    assert item["can_send_esign"] is False

    asked = await app_client.post(
        f"{PATH}/{gid}/signature-request", headers=world["author"]
    )
    assert asked.status_code == 409 and asked.json()["detail"] == krz.MSG_NOT_CHECKED

    denied = await app_client.put(
        f"{PATH}/{gid}/krz", json={"result": "clear"}, headers=world["outsider"]
    )
    assert denied.status_code == 403

    saved = await app_client.put(
        f"{PATH}/{gid}/krz", json={"result": "clear"}, headers=world["author"]
    )
    assert saved.status_code == 200, saved.text
    state = saved.json()["krz"]
    assert state["result"] == "clear" and state["block_reason"] is None
    assert state["checked_by_name"]

    history = await app_client.get(
        f"{PATH}/{gid}/status-history", headers=world["author"]
    )
    assert any(
        e["kind"] == "krz" and e["label"] == "KRZ: brak wpisów" for e in history.json()
    )
    form = await app_client.get(f"{PATH}/{gid}/form", headers=world["author"])
    assert form.json()["form"]["krz_check"]["result"] == "clear"

    # Ten sam wynik drugi raz nie dokłada wpisu w historii.
    await app_client.put(
        f"{PATH}/{gid}/krz", json={"result": "clear"}, headers=world["author"]
    )
    again = await app_client.get(
        f"{PATH}/{gid}/status-history", headers=world["author"]
    )
    assert sum(e["kind"] == "krz" for e in again.json()) == 1


@pytest.mark.asyncio
async def test_entry_rings_the_dl_who_allows_it_and_finance_hears_about_it(
    app_client, world
):
    gid = world["generated_id"]
    saved = await app_client.put(
        f"{PATH}/{gid}/krz",
        json={"result": "entry", "entry_kind": "enforcement", "entry_note": "Km 1/24"},
        headers=world["author"],
    )
    assert saved.status_code == 200, saved.text
    state = saved.json()["krz"]
    assert state["block_reason"] == krz.MSG_WAITING_DECISION
    assert state["entry_label"] == "Umorzona egzekucja (bezskuteczna)"
    assert state["decider_names"] and state["can_decide"] is False
    assert await _bells(world["dl_id"], "b2b_krz_entry", gid) == 1

    by_author = await app_client.post(
        f"{PATH}/{gid}/krz/decision",
        json={"decision": "allowed", "reason": "spłacone w 2025"},
        headers=world["author"],
    )
    assert by_author.status_code == 403

    dl_view = await _row_from_list(app_client, world, who="dl")
    assert dl_view["krz"]["can_decide"] is True
    allowed = await app_client.post(
        f"{PATH}/{gid}/krz/decision",
        json={"decision": "allowed", "reason": "spłacone w 2025"},
        headers=world["dl"],
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["krz"]["block_reason"] is None
    assert allowed.json()["krz"]["decision"] == "allowed"
    assert await _bells(world["finance_id"], "b2b_krz_allowed", gid) == 1

    twice = await app_client.post(
        f"{PATH}/{gid}/krz/decision",
        json={"decision": "rejected", "reason": "jednak nie"},
        headers=world["dl"],
    )
    assert twice.status_code == 409


@pytest.mark.asyncio
async def test_rejected_entry_cancels_the_agreement(app_client, world):
    gid = world["generated_id"]
    await app_client.put(
        f"{PATH}/{gid}/krz",
        json={"result": "entry", "entry_kind": "bankruptcy"},
        headers=world["author"],
    )
    rejected = await app_client.post(
        f"{PATH}/{gid}/krz/decision",
        json={"decision": "rejected", "reason": "upadłość w toku"},
        headers=world["dl"],
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["contract_status"] == "cancelled"
    history = await app_client.get(f"{PATH}/{gid}/status-history", headers=world["dl"])
    last = [e for e in history.json() if e["kind"] == "krz"][-1]
    assert last["to_status"] == "cancelled" and last["from_status"] == "in_progress"
