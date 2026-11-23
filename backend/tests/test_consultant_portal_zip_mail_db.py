"""Czytnik rozliczeń: ZIP w mailu i raport zbiorczy Credit Agricole (z bazą).

Skrzynka to atrapa, dane fikcyjne. Próba IX–X 2026: DL przekazuje na rozliczenia@
raport klienta w ZIP-ie z hasłem (jeden arkusz, kilka osób), konsultant PKO
wysyła „Dokumenty.zip” bez hasła. Bez rozpakowania 6 osobo-miesięcy stało bez MD.
"""

from __future__ import annotations

import base64
import io
import zipfile
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select, update

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.consultant_portal import CpDocument, CpMailboxState
from app.services import storage_service
from app.services.consultant_portal import identity, mailbox
from tests.care_announcements_seed import (  # noqa: F401  (fixture'y)
    care_on,
    make_client,
    make_consultant,
    tag,
)
from tests.consultant_portal_seed import (  # noqa: F401  (fixture'y)
    make_person,
    portal_all,
    portal_restored,
)
from tests.test_client_settlements_report_ca import _row, ca_report
from tests.zip_crypto import encrypted_zip

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.usefixtures("care_on", "portal_all"),
]

DOMAIN = "firma-testowa.example"
PASSWORD = "haslo-testowe"
PDF = b"%PDF-1.4 fikcyjny time sheet"


@pytest.fixture(autouse=True)
def _config(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    # Adres DL-a jest adresem firmy (jak domena adresu rozliczeń na produkcji).
    monkeypatch.setattr(identity, "_company_domains", lambda: frozenset({DOMAIN}))
    monkeypatch.setattr(settings, "CONSULTANT_PORTAL_ZIP_PASSWORD", PASSWORD)


@pytest_asyncio.fixture(autouse=True)
async def _fresh_state():
    async with AsyncSessionLocal() as db:
        state = await db.get(CpMailboxState, 1)
        if state is not None:
            await db.delete(state)
            await db.commit()
    yield


class FakeMailbox:
    def __init__(self, messages, attachments) -> None:
        self.messages = messages
        self.files = attachments

    async def list_messages(self, since):
        return self.messages

    async def attachments(self, message_id):
        return self.files.get(message_id, [])


def _attachment(name: str, data: bytes) -> dict:
    return {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": name,
        "isInline": False,
        "contentBytes": base64.b64encode(data).decode(),
    }


def _message(message_id: str, sender: str, subject: str) -> dict:
    return {
        "id": message_id,
        "subject": subject,
        "hasAttachments": True,
        "from": {"emailAddress": {"address": sender}},
        "receivedDateTime": datetime(2026, 10, 5, 12, tzinfo=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
    }


async def _consultant(client_id: int, first: str, last: str) -> int:
    contract_id, candidate_id = await make_consultant(client_id)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Candidate)
            .where(Candidate.id == candidate_id)
            .values(name=first, lastname=last)
        )
        await db.commit()
    return contract_id


async def _read(reader) -> dict:
    async with AsyncSessionLocal() as db:
        result = await mailbox.run_once(db, mailbox=reader)
        await db.commit()
    return result


async def _of_contract(contract_id: int) -> list[CpDocument]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(CpDocument).where(CpDocument.contract_id == contract_id)
                )
            ).all()
        )


async def test_raport_ca_z_zipa_z_haslem_trafia_do_kazdej_osoby():
    ca1 = f"ca-{tag()}"
    client_id = await make_client()
    jan_last, anna_last = f"Testowy{tag()}", f"Inna{tag()}"
    jan = await _consultant(client_id, "Jan", jan_last)
    anna = await _consultant(client_id, "Anna", anna_last)
    report = ca_report(
        rows=[
            _row(f"{jan_last} Jan", "P1-01", hours=136, te=17),
            _row(f"{anna_last} Anna", "BAU", hours=176, te=22),
            _row("Nieznany Piotr", "BAU", hours=176, te=22),
        ]
    )
    archive = encrypted_zip(
        {"1234_Raport_Rozliczenia_09_2026.xlsx": report}, PASSWORD.encode()
    )
    reader = FakeMailbox(
        [
            _message(
                ca1,
                f"dl.testowa@{DOMAIN}",
                "PD: Dostawca : naliczenie za miesiąc 2026.09",
            )
        ],
        {ca1: [_attachment("1234_Raport_Rozliczenia_09_2026.zip", archive)]},
    )

    result = await _read(reader)

    assert result["created"] == 2
    for contract_id in (jan, anna):
        docs = await _of_contract(contract_id)
        assert len(docs) == 1
        assert docs[0].kind == "report"
        assert (docs[0].period_year, docs[0].period_month) == (2026, 9)
        assert docs[0].file_name == "1234_Raport_Rozliczenia_09_2026.xlsx"
    # Drugi odczyt tego samego maila niczego nie dokłada.
    assert (await _read(reader))["created"] == 0


async def test_raport_ca_z_osobami_u_dwoch_klientow_czeka_na_czlowieka():
    ca2 = f"ca-{tag()}"
    jan_last, anna_last = f"Testowy{tag()}", f"Inna{tag()}"
    jan = await _consultant(await make_client(), "Jan", jan_last)
    anna = await _consultant(await make_client(), "Anna", anna_last)
    report = ca_report(
        rows=[
            _row(f"{jan_last} Jan", "P1", hours=136, te=17),
            _row(f"{anna_last} Anna", "BAU", hours=176, te=22),
        ]
    )
    reader = FakeMailbox(
        [_message(ca2, f"dl.testowa@{DOMAIN}", "naliczenie za miesiąc 2026.09")],
        {
            ca2: [
                _attachment(
                    "raport.zip",
                    encrypted_zip({"raport.xlsx": report}, PASSWORD.encode()),
                )
            ]
        },
    )

    await _read(reader)

    assert await _of_contract(jan) == []
    assert await _of_contract(anna) == []


async def test_raport_ca_od_obcego_adresu_nie_wskazuje_osob():
    ca3 = f"ca-{tag()}"
    client_id = await make_client()
    jan_last = f"Testowy{tag()}"
    jan = await _consultant(client_id, "Jan", jan_last)
    report = ca_report(rows=[_row(f"{jan_last} Jan", "P1", hours=136, te=17)])
    reader = FakeMailbox(
        [_message(ca3, "ktos@obca-poczta.example", "naliczenie za miesiąc 2026.09")],
        {ca3: [_attachment("raport.xlsx", report)]},
    )

    await _read(reader)

    assert await _of_contract(jan) == []


async def test_zip_bez_hasla_od_konsultanta_daje_jego_dokumenty():
    pko1 = f"pko-{tag()}"
    person = await make_person()
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("TimeSheet 2610.pdf", PDF)
    reader = FakeMailbox(
        [_message(pko1, person.email, "Rozliczenie pazdziernik 2026")],
        {pko1: [_attachment("Dokumenty.zip", out.getvalue())]},
    )

    result = await _read(reader)

    assert result["created"] == 1
    docs = await _of_contract(person.contract_id)
    assert [d.file_name for d in docs] == ["TimeSheet 2610.pdf"]
    assert docs[0].kind == "report"
