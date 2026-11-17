"""Dzwonienie: powtórki z kolejnych list i firmy już w CRM (zgłoszenie dzwoniących 17.11.2026).

Lista z 13.11 miała samo nazwisko („Nowacka” zamiast „Ewa Nowacka”) i 380 numerów,
pod które już dzwoniono, weszło do kolejki jako nowe. Rekord z listy bez wyniku
wracał też jako „Nowy”, choć ofertę zapisano już jako szansę.

Dane są fikcyjne; numery i nazwy niosą losowy znacznik, bo baza testowa jest wspólna.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tests.test_sales_calling_import import _csv, _fates, _named_company, _phone, _tag
from tests.test_sales_calling_queue import (
    _campaign,
    _contact,
    _opportunity,
    _queue,
    _record,
)
from tests.test_sales_companies_api import _headers, _user

URL = "/api/sales/calling"


def _ids(queue: dict, section: str = "new") -> set:
    return {item["record_id"] for item in queue[section]}


# ── Import: bramka „Już dzwoniono” ────────────────────────────────────────


@pytest.mark.asyncio
async def test_surname_only_row_with_a_called_number_is_already_called(
    app_client,
) -> None:
    """Przypadek z 13.11: ten sam numer, na liście samo nazwisko."""

    caller = await _user("sales_edit")
    other = await _user("sales_edit")
    tag = _tag()
    phone = _phone()
    company_id = await _named_company(f"Nowacka Systemy {tag}")
    await _record(
        other.id,
        await _campaign(),
        company_id,
        phone=phone,
        person_name="Ewa Nowacka",
        state="not_interested",
        last_outcome_at=datetime.now(timezone.utc),
    )

    body, fates = await _fates(
        app_client,
        caller,
        await _campaign(),
        _csv(f"Nowacka Systemy {tag};Nowacka;CTO;+48 {phone};;"),
    )

    assert fates[0][0] == "already_called"
    assert other.name in fates[0][1] and "Nie zainteresowany" in fates[0][1]
    assert "Ewa Nowacka" in fates[0][1]
    assert body["addable"] == 0
    assert body["counts"]["already_called"] == 1


@pytest.mark.asyncio
async def test_called_number_under_another_company_card_is_already_called(
    app_client,
) -> None:
    """Numer łączy się z rekordem także wtedy, gdy plik ma inną nazwę firmy."""

    caller = await _user("sales_edit")
    tag = _tag()
    phone = _phone()
    company_id = await _named_company(f"Stara Nazwa {tag}")
    await _record(
        caller.id,
        await _campaign(),
        company_id,
        phone=phone,
        state="offer_sent",
        last_outcome_at=datetime.now(timezone.utc),
    )

    _body, fates = await _fates(
        app_client, caller, await _campaign(), _csv(f"Nowa Nazwa {tag};;;{phone};;")
    )

    assert fates[0][0] == "already_called"
    assert "Oferta ogólna wysłana" in fates[0][1]


@pytest.mark.asyncio
async def test_same_email_with_a_new_number_is_already_called(app_client) -> None:
    caller = await _user("sales_edit")
    tag = _tag()
    email = f"ewa-{tag}@firma-{tag}.example"
    company_id = await _named_company(f"Adresowa {tag}")
    await _record(
        caller.id,
        await _campaign(),
        company_id,
        phone=_phone(),
        email=email.upper(),
        state="offer_sent",
        last_outcome_at=datetime.now(timezone.utc),
    )

    _body, fates = await _fates(
        app_client,
        caller,
        await _campaign(),
        _csv(f"Adresowa {tag};Ewa;CFO;{_phone()};{email};"),
    )

    assert fates[0][0] == "already_called"
    assert "Oferta ogólna wysłana" in fates[0][1]


@pytest.mark.asyncio
async def test_new_person_in_a_called_company_is_added_with_a_note(
    app_client,
) -> None:
    """Dopasowanie po osobie: nowy decydent w tej samej firmie przechodzi z dopiskiem."""

    caller = await _user("sales_edit")
    tag = _tag()
    company_id = await _named_company(f"Dwie Osoby {tag}")
    await _record(
        caller.id,
        await _campaign(),
        company_id,
        phone=_phone(),
        person_name="Jan Pierwszy",
        state="no_answer",
        last_outcome_at=datetime.now(timezone.utc),
    )

    body, fates = await _fates(
        app_client,
        caller,
        await _campaign(),
        _csv(f"Dwie Osoby {tag};Anna Druga;CIO;{_phone()};;"),
    )

    assert fates[0][0] == "linked"
    assert "W tej firmie dzwoniono już" in fates[0][1]
    assert "Nie odebrał" in fates[0][1] and "Jan Pierwszy" in fates[0][1]
    assert body["addable"] == 1


@pytest.mark.asyncio
async def test_surname_only_row_matches_the_record_in_the_same_campaign(
    app_client,
) -> None:
    """Rekord bez wyniku w tej kampanii: numer wygrywa z różnym zapisem nazwiska."""

    caller = await _user("sales_edit")
    tag = _tag()
    phone = _phone()
    campaign_id = await _campaign()
    company_id = await _named_company(f"Ta Sama {tag}")
    await _record(
        caller.id, campaign_id, company_id, phone=phone, person_name="Ewa Nowacka"
    )

    _body, fates = await _fates(
        app_client, caller, campaign_id, _csv(f"Ta Sama {tag};Nowacka;;{phone};;")
    )

    assert fates[0] == ("already_in_campaign", "Ten rekord jest już w tej kampanii.")


@pytest.mark.asyncio
async def test_number_waiting_in_another_campaign_is_not_added_twice(
    app_client,
) -> None:
    caller = await _user("sales_edit")
    tag = _tag()
    phone = _phone()
    company_id = await _named_company(f"Czeka {tag}")
    await _record(caller.id, await _campaign("Wiosna"), company_id, phone=phone)

    _body, fates = await _fates(
        app_client,
        caller,
        await _campaign(),
        _csv(f"Inna Karta {tag};;;{phone};;"),
    )

    assert fates[0][0] == "already_in_campaign"
    assert "czeka już na liście" in fates[0][1] and "Wiosna" in fates[0][1]


@pytest.mark.asyncio
async def test_called_number_is_not_saved_by_the_import(app_client) -> None:
    caller = await _user("sales_edit")
    tag = _tag()
    phone = _phone()
    company_id = await _named_company(f"Zapis {tag}")
    await _record(
        caller.id,
        await _campaign(),
        company_id,
        phone=phone,
        state="meeting_booked",
        last_outcome_at=datetime.now(timezone.utc),
    )
    campaign_id = await _campaign()

    resp = await app_client.post(
        f"{URL}/campaigns/{campaign_id}/import",
        files={
            "file": ("lista.csv", _csv(f"Zapis {tag};Nowak;;{phone};;"), "text/csv")
        },
        data={"contact_source": "Lista testowa"},
        headers=_headers(caller),
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["added"] == 0
    assert resp.json()["counts"]["already_called"] == 1


# ── Kolejka ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_queue_skips_a_new_record_whose_number_was_already_called(
    app_client,
) -> None:
    caller = await _user("sales_edit")
    company_id = await _named_company(f"Powtórka {_tag()}")
    phone = _phone()
    await _record(
        caller.id,
        await _campaign(),
        company_id,
        phone=phone,
        state="not_interested",
        last_outcome_at=datetime.now(timezone.utc),
    )
    campaign_id = await _campaign()
    repeat_id = await _record(caller.id, campaign_id, company_id, phone=f"+48 {phone}")
    fresh_id = await _record(caller.id, campaign_id, company_id, phone=_phone())

    queue = await _queue(app_client, caller)

    assert fresh_id in _ids(queue)
    assert repeat_id not in _ids(queue)
    assert queue["counts"]["new"] == 1


@pytest.mark.asyncio
async def test_queue_skips_a_list_record_once_the_company_has_a_later_opportunity(
    app_client,
) -> None:
    """Oferta zapisana jako szansa, rekord z listy bez wyniku."""

    caller = await _user("sales_edit")
    campaign_id = await _campaign()
    in_crm_id = await _named_company(f"Muzeum {_tag()}")
    earlier_id = await _named_company(f"Wcześniej {_tag()}")
    before = datetime.now(timezone.utc) - timedelta(days=5)
    in_crm_record = await _record(
        caller.id, campaign_id, in_crm_id, phone=_phone(), created_at=before
    )
    earlier_record = await _record(
        caller.id, campaign_id, earlier_id, phone=_phone(), created_at=before
    )
    await _opportunity(caller.id, in_crm_id, created=before + timedelta(days=1))
    await _opportunity(caller.id, earlier_id, created=before - timedelta(days=1))

    queue = await _queue(app_client, caller)

    assert in_crm_record not in _ids(queue)
    assert earlier_record in _ids(queue)


# ── Karta ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_card_shows_earlier_calls_and_the_opportunity_in_crm(
    app_client,
) -> None:
    caller = await _user("sales_edit")
    other = await _user("sales_edit")
    company_id = await _named_company(f"Karta {_tag()}")
    phone = _phone()
    before = datetime.now(timezone.utc) - timedelta(days=3)
    called_id = await _record(
        other.id,
        await _campaign(),
        company_id,
        phone=phone,
        person_name="Ewa Nowacka",
        state="bad_contact",
        last_outcome_at=before,
    )
    record_id = await _record(
        caller.id, await _campaign(), company_id, phone=phone, created_at=before
    )
    opp_id = await _opportunity(caller.id, company_id)

    resp = await app_client.get(f"{URL}/records/{record_id}", headers=_headers(caller))

    assert resp.status_code == 200, resp.text
    card = resp.json()
    assert [call["record_id"] for call in card["earlier_calls"]] == [called_id]
    label = card["earlier_calls"][0]["label"]
    assert other.name in label and "Zły numer" in label and "Ewa Nowacka" in label
    assert card["crm_opportunity"]["id"] == opp_id
    assert card["crm_opportunity"]["stage_name"] == "Lead"


@pytest.mark.asyncio
async def test_card_without_repeats_has_empty_fields(app_client) -> None:
    caller = await _user("sales_edit")
    company_id = await _named_company(f"Czysta {_tag()}")
    contact_id = await _contact(company_id, phone=_phone())
    record_id = await _record(
        caller.id,
        await _campaign(),
        company_id,
        phone=_phone(),
        contact_id=contact_id,
    )

    resp = await app_client.get(f"{URL}/records/{record_id}", headers=_headers(caller))

    assert resp.status_code == 200, resp.text
    assert resp.json()["earlier_calls"] == []
    assert resp.json()["crm_opportunity"] is None


@pytest.mark.asyncio
async def test_bad_number_blocks_only_the_number_not_the_person(app_client) -> None:
    """„Zły numer” zamyka rekord; ta sama osoba z nowym numerem wraca z kolejnej listy."""

    caller = await _user("sales_edit")
    tag = _tag()
    email = f"ewa-{tag}@firma-{tag}.example"
    company_id = await _named_company(f"Zły Numer {tag}")
    contact_id = await _contact(company_id, full_name="Ewa Nowacka", email=email)
    old_phone = _phone()
    await _record(
        caller.id,
        await _campaign(),
        company_id,
        phone=old_phone,
        email=email,
        contact_id=contact_id,
        state="bad_contact",
        last_outcome_at=datetime.now(timezone.utc),
    )
    campaign_id = await _campaign()

    _body, fates = await _fates(
        app_client,
        caller,
        campaign_id,
        _csv(
            f"Zły Numer {tag};Ewa Nowacka;CFO;{_phone()};{email};",
            f"Zły Numer {tag};Ktoś Inny;CTO;{old_phone};;",
        ),
    )
    assert fates[0][0] == "linked"
    assert fates[1][0] == "already_called"

    fresh_id = await _record(
        caller.id,
        campaign_id,
        company_id,
        phone=_phone(),
        email=email,
        contact_id=contact_id,
    )
    assert fresh_id in _ids(await _queue(app_client, caller))


@pytest.mark.asyncio
async def test_opportunity_in_another_pipeline_does_not_hide_the_record(
    app_client,
) -> None:
    """Szansa z lejka botów (np. fabryki IT) nie zdejmuje firmy z kolejki dzwonienia."""

    from app.core.database import AsyncSessionLocal
    from app.models.sales import SalesOpportunity, SalesPipeline, SalesPipelineStage

    caller = await _user("sales_edit")
    company_id = await _named_company(f"Inny Lejek {_tag()}")
    before = datetime.now(timezone.utc) - timedelta(days=5)
    record_id = await _record(
        caller.id, await _campaign(), company_id, phone=_phone(), created_at=before
    )
    async with AsyncSessionLocal() as db:
        pipeline = SalesPipeline(key=f"test-{_tag()}", name="Lejek testowy")
        db.add(pipeline)
        await db.flush()
        stage = SalesPipelineStage(pipeline_id=pipeline.id, key="new", name="Nowa")
        db.add(stage)
        await db.flush()
        db.add(
            SalesOpportunity(
                company_id=company_id,
                pipeline_id=pipeline.id,
                stage_id=stage.id,
                title="Szansa z innego lejka",
                owner_user_id=caller.id,
                created_by_user_id=caller.id,
            )
        )
        await db.commit()

    queue = await _queue(app_client, caller)
    assert record_id in _ids(queue)
    card = await app_client.get(f"{URL}/records/{record_id}", headers=_headers(caller))
    assert card.json()["crm_opportunity"] is None
