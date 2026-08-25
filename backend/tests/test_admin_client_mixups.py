"""Raport rozjazdu przypisania klienta — reguła grupowania i dowody.

Dwa niezależne zgłoszenia tej samej pomyłki (kontrakt i umowa B2B wskazujące
„BNP Paribas Cardif” zamiast „CARDIF - ASSURANCES RISQUES DIVERS S.A. ODDZIAŁ
W POLSCE”) są sygnałem systemowym, nie dwoma błędami danych. Ten raport ma je
wyszukiwać — ale WYŁĄCZNIE wyszukiwać: rozstrzyga człowiek.
"""

from __future__ import annotations

import uuid

import pytest

from app.api.admin_client_mixups import name_tokens, shares_identity_token
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, ContractType
from app.models.job import Job

CARDIF = "CARDIF - ASSURANCES RISQUES DIVERS SPÓŁKA AKCYJNA ODDZIAŁ W POLSCE"
BNP_CARDIF = "BNP Paribas Cardif"
BNP_BANK = "BNP Paribas Bank Polska"


class TestNameTokens:
    def test_drops_legal_form_and_administrative_noise(self):
        """„SPÓŁKA AKCYJNA ODDZIAŁ W POLSCE" nie identyfikuje firmy."""
        tokens = name_tokens(CARDIF)
        assert "cardif" in tokens
        for noise in ("spolka", "akcyjna", "oddzial", "polsce"):
            assert noise not in tokens

    def test_diacritics_fold(self):
        assert name_tokens("SPÓŁKA Cardif") == name_tokens("SPOLKA Cardif")

    def test_short_tokens_are_dropped(self):
        """Dwuznakowy skrót trafia w przypadkowe firmy."""
        assert name_tokens("BP SA") == frozenset()

    def test_empty_input_is_not_a_crash(self):
        assert name_tokens(None) == frozenset()
        assert name_tokens("   ") == frozenset()


class TestSharesIdentityToken:
    def test_the_reported_pair_is_matched(self):
        assert shares_identity_token(CARDIF, BNP_CARDIF)

    def test_substring_trap_is_not_a_match(self):
        """„BNP Paribas Bank Polska" to ODRĘBNY, prawdziwy klient.

        Naiwne dopasowanie po podciągu („BNP” w obu nazwach) wciągnęłoby go do
        raportu razem z jego prawdziwymi kontraktami — a raport mieszający
        poprawne przypisania z podejrzanymi przestaje być listą do weryfikacji.
        Rozdziela je dopiero wspólny TOKEN: bank nie ma „cardif”.
        """
        assert not shares_identity_token(CARDIF, BNP_BANK)

    def test_two_bnp_records_still_share_paribas(self):
        """Rodzina „paribas" istnieje i to jest poprawne — tam pomyłka też grozi."""
        assert shares_identity_token(BNP_CARDIF, BNP_BANK)
        assert "paribas" in (name_tokens(BNP_CARDIF) & name_tokens(BNP_BANK))

    def test_unrelated_clients_do_not_match(self):
        assert not shares_identity_token("Erste Bank Polska S.A.", CARDIF)

    def test_legal_form_alone_never_makes_a_family(self):
        """Bez odsiania form prawnych połowa bazy byłaby jedną rodziną."""
        assert not shares_identity_token(
            "Alfa Spółka Akcyjna", "Beta Spółka Akcyjna"
        )


# ── Integracja: raport na zaseedowanej parze ────────────────────────────────


async def _seed_confusable_pair() -> tuple[int, int, int]:
    """Dwa rekordy klienta o mylnie podobnych nazwach + kontrakt na złym z nich."""
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        right = Client(name=f"CARDIF ASSURANCES {suffix} ODDZIAŁ W POLSCE", nip="5262561140")
        wrong = Client(name=f"BNP Paribas Cardif {suffix}", nip="6760111111")
        candidate = Candidate(name=f"Maciej{suffix}", lastname=f"Rogala{suffix}")
        db.add_all([right, wrong, candidate])
        await db.flush()
        # Rekrutacja należy do WŁAŚCIWEGO klienta — to jest dowód pomyłki.
        job = Job(title=f"Java Developer {suffix}", client_id=right.id)
        db.add(job)
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=wrong.id,
            job_id=job.id,
            contract_type=ContractType.b2b,
            status=ContractStatus.draft,
        )
        db.add(contract)
        await db.commit()
        return right.id, wrong.id, contract.id


@pytest.mark.asyncio
async def test_report_flags_the_contract_whose_job_belongs_to_the_other_client(
    app_client, app_auth_headers
):
    right_id, wrong_id, contract_id = await _seed_confusable_pair()

    resp = await app_client.get(
        "/api/admin/client-mixups", params={"q": "cardif"}, headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    rows = [
        row
        for family in body["families"]
        for row in family["contracts"]
        if row["contract_id"] == contract_id
    ]
    assert len(rows) == 1, body
    row = rows[0]
    # Rozjazd „klient przypisany ≠ klient rekrutacji" to najmocniejszy dowód
    # dostępny maszynowo — i JEDYNE, co raport twierdzi. Nie poprawia niczego.
    assert row["job_client_mismatch"] is True
    assert row["assigned_client"]["id"] == wrong_id
    assert row["job_client"]["id"] == right_id
    # NIP obu stron jedzie razem z wierszem — to on rozstrzyga, nie nazwa.
    assert row["assigned_client"]["nip"] == "6760111111"
    assert row["job_client"]["nip"] == "5262561140"


@pytest.mark.asyncio
async def test_report_is_read_only(app_client, app_auth_headers):
    """Dwa wywołania zwracają to samo — raport niczego nie konsumuje."""
    await _seed_confusable_pair()
    first = await app_client.get(
        "/api/admin/client-mixups", params={"q": "cardif"}, headers=app_auth_headers
    )
    second = await app_client.get(
        "/api/admin/client-mixups", params={"q": "cardif"}, headers=app_auth_headers
    )
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()


@pytest.mark.asyncio
async def test_unrelated_query_returns_an_empty_report_not_everything(
    app_client, app_auth_headers
):
    """Zawężenie MUSI zawężać — raport „o wszystkim" jest nie do przejrzenia."""
    await _seed_confusable_pair()
    resp = await app_client.get(
        "/api/admin/client-mixups",
        params={"q": "nieistniejacaklauzula"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["families"] == []
