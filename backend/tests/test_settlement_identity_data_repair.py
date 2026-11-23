"""Poprawki danych 479 (adres w kontrakcie) i 627 (literówka w imieniu) z przeglądu „bez dokumentu”.

Rozliczenia z poczty nie znajdowały tych osób: kontrakt 479 nie miał adresu,
z którego konsultant pisze, a w kartotece 627 imię nie zgadzało się z adresem.
Wartości wyliczamy z kartoteki, więc w repo nie ma danych osób; naprawa nie
rusza tego, co ktoś już poprawił.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import select

from app.services.settlement_identity_data_repair import (
    client_mailbox_address,
    first_name_from_email,
)


def test_client_mailbox_address_is_lowercase_first_dot_last():
    assert (
        client_mailbox_address("Jan", "Kowalski", "erste.pl") == "jan.kowalski@erste.pl"
    )


@pytest.mark.parametrize(
    ("name", "lastname"),
    [("Łukasz", "Nowak"), ("Jan", "Nowak-Kowalski"), ("", "Nowak"), ("Jan", "")],
)
def test_client_mailbox_address_refuses_names_it_cannot_spell_safely(name, lastname):
    assert client_mailbox_address(name, lastname, "erste.pl") is None


def test_first_name_from_email_restores_one_missing_letter():
    assert (
        first_name_from_email("Mihal", "Testowy", "michal.testowy@gmail.com")
        == "Michal"
    )


@pytest.mark.parametrize(
    "email",
    [
        "michal.testowy@gmail.com".replace("testowy", "inny"),  # inne nazwisko
        "mihal.testowy@gmail.com",  # to samo imię, nic do poprawy
        "michaal.testowy@gmail.com",  # dwie litery różnicy
        "mchal.testowy@gmail.com",  # inna litera, nie dopisana
        "michal@gmail.com",  # bez nazwiska
        "michal.jan.testowy@gmail.com",  # trzy człony
        "",
    ],
)
def test_first_name_from_email_refuses_anything_but_a_single_inserted_letter(email):
    assert first_name_from_email("Mihal", "Testowy", email) is None


def test_targets_are_the_two_contracts_from_the_review():
    from app.services.settlement_identity_data_repair import (
        BOSCH_CLIENT_ID,
        CONTRACT_EMAIL_TARGET,
        ERSTE_CLIENT_ID,
        FIRST_NAME_TARGET,
    )

    assert CONTRACT_EMAIL_TARGET == (479, 204927, ERSTE_CLIENT_ID)
    assert FIRST_NAME_TARGET == (627, 443352, BOSCH_CLIENT_ID)


def _ascii_lastname(suffix: str) -> str:
    return "Osoba" + "".join(chr(97 + int(ch, 16) % 26) for ch in suffix)


async def _seed(
    name: str, lastname: str, email: str | None, contract_email: str | None
):
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus, ContractType

    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Naprawa tozsamosci {unique}")
        candidate = Candidate(name=name, lastname=lastname, email=email)
        db.add_all([client, candidate])
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            contract_type=ContractType.b2b,
            status=ContractStatus.active,
            start_date=date(2026, 3, 2),
            currency="PLN",
            candidate_email=contract_email,
        )
        db.add(contract)
        await db.commit()
        return contract.id, candidate.id, client.id


@pytest.mark.asyncio
async def test_repair_fills_email_fixes_name_and_runs_once():
    from app.core.database import AsyncSessionLocal
    from app.models.activity import Activity
    from app.models.candidate import Candidate
    from app.models.contract import Contract
    from app.services.settlement_identity_data_repair import (
        REPAIR_MARKER,
        Target,
        run_settlement_identity_data_repair,
        summarize_for_log,
    )

    suffix = uuid.uuid4().hex[:6]
    lastname = _ascii_lastname(suffix)
    email_seed = await _seed("Jan", lastname, None, None)
    name_seed = await _seed(
        "Mihal", lastname, f"michal.{lastname.lower()}@gmail.com", None
    )
    marker = f"test_identity_repair_{suffix}"

    async with AsyncSessionLocal() as db:
        summary = await run_settlement_identity_data_repair(
            db,
            email_target=Target(*email_seed),
            name_target=Target(*name_seed),
            marker=marker,
        )
        await db.commit()
    assert summarize_for_log(summary) == "fixed 2/2"

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, email_seed[0])
        assert contract.candidate_email == f"jan.{lastname.lower()}@erste.pl"
        candidate = await db.get(Candidate, name_seed[1])
        assert candidate.name == "Michal"
        history = (
            await db.execute(
                select(
                    Activity.entity_type, Activity.entity_id, Activity.details
                ).where(
                    Activity.action == "updated",
                    Activity.details["source"].astext == REPAIR_MARKER,
                    (
                        (Activity.entity_type == "contract")
                        & (Activity.entity_id == email_seed[0])
                    )
                    | (
                        (Activity.entity_type == "candidate")
                        & (Activity.entity_id == name_seed[1])
                    ),
                )
            )
        ).all()
    assert sorted(history) == [
        (
            "candidate",
            name_seed[1],
            {"name": {"old": "Mihal", "new": "Michal"}, "source": REPAIR_MARKER},
        ),
        (
            "contract",
            email_seed[0],
            {
                "candidate_email": f"jan.{lastname.lower()}@erste.pl",
                "source": REPAIR_MARKER,
            },
        ),
    ]

    async with AsyncSessionLocal() as db:
        again = await run_settlement_identity_data_repair(
            db,
            email_target=Target(*email_seed),
            name_target=Target(*name_seed),
            marker=marker,
        )
        await db.rollback()
    assert again is None


@pytest.mark.asyncio
async def test_repair_keeps_data_someone_already_changed():
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.contract import Contract
    from app.services.settlement_identity_data_repair import (
        Target,
        run_settlement_identity_data_repair,
        summarize_for_log,
    )

    suffix = uuid.uuid4().hex[:6]
    lastname = _ascii_lastname(suffix)
    email_seed = await _seed("Jan", lastname, None, f"jan.{suffix}@firma.example")
    name_seed = await _seed(
        "Mihal", lastname, f"michal.{lastname.lower()}@gmail.com", None
    )
    marker = f"test_identity_repair_{suffix}"

    async with AsyncSessionLocal() as db:
        summary = await run_settlement_identity_data_repair(
            db,
            email_target=Target(*email_seed),
            name_target=Target(name_seed[0], email_seed[1], name_seed[2]),
            marker=marker,
        )
        await db.commit()
    assert summarize_for_log(summary) == (
        f"fixed 0/2; skipped {email_seed[0]}:candidate_email:already_set, "
        f"{name_seed[0]}:candidate_name:identity_mismatch"
    )
    async with AsyncSessionLocal() as db:
        assert (
            await db.get(Contract, email_seed[0])
        ).candidate_email == f"jan.{suffix}@firma.example"
        assert (await db.get(Candidate, name_seed[1])).name == "Mihal"
