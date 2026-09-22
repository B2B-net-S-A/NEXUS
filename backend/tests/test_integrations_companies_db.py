"""ATLAS `/api/integrations/companies/people` — ścieżka przez PRAWDZIWĄ bazę.

`test_integrations_companies.py` pokrywa czyste funkcje (normalizacja,
rozstrzygnięcie current/past w Pythonie). Tu sprawdzamy to, czego one nie
widzą, bo żyje w SQL-u:

- ``via_us`` liczy kontrakty, które faktycznie trwały
  (``active``/``ending``/``ended``) oraz szkic / umowę do podpisu z realną
  obsadą (aktywne zamówienie albo bieżący etap „Zatrudniony") — goły szkic
  i unieważniony nie są „umieściliśmy tam ludzi", a flaga
  ``current_employment`` mówi „pracuje tam", nie „przez nas" (aktywna →
  ``current``, zdjęta → ``past``);
- ``_past_company_predicate`` nie gubi osób, których NAJNOWSZA, zakończona
  praca leży na pozycji 0 (stare ``idx > 1``), a „present"/„obecnie" w ``end``
  to praca obecna;
- surowy alias, którego forma kanoniczna jest za krótka, nie trafia do
  ``LIKE`` (dawniej „IT" szło jako ``LIKE '%it%'``);
- zapytanie ma sufit wierszy (liczony w WIERSZACH, nie osobach) i limit czasu
  (503 zamiast wiszącego workera).

Nazwa firmy niesie losowy tag — baza testowa jest wspólna dla przebiegu,
więc tylko unikalna nazwa izoluje wynik od kandydatów z innych plików.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

import app.models  # noqa: F401  (zarejestruj wszystkie mappery)
from app.api import integrations_companies
from app.api.oauth_token import _create_client_token
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate, CandidateStatus
from app.models.candidate_conflict import CandidateConflict, ConflictType
from app.models.client import Client
from app.models.contract import Contract, ContractStatus
from app.models.oauth_client import OAuthClient

URL = "/api/integrations/companies/people"


ATLAS_CLIENT_ID = f"atlas-test-{uuid.uuid4().hex[:8]}"


@pytest_asyncio.fixture(autouse=True)
async def _atlas_client():
    """``require_scope`` czyta klienta z bazy przy każdym żądaniu (AUTH-02)."""

    async with AsyncSessionLocal() as db:
        db.add(
            OAuthClient(
                name="ATLAS (test)",
                client_id=ATLAS_CLIENT_ID,
                secret_hash="!test-no-secret!",
                scopes=["candidate:read"],
                enabled=True,
            )
        )
        await db.commit()
    yield
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(OAuthClient).where(OAuthClient.client_id == ATLAS_CLIENT_ID)
        )
        await db.commit()


def _headers() -> dict[str, str]:
    token = _create_client_token(
        SimpleNamespace(client_id=ATLAS_CLIENT_ID),
        ["candidate:read"],
    )
    return {"Authorization": f"Bearer {token}"}


async def _candidate(db, lastname: str, *, experience=None) -> Candidate:
    cand = Candidate(
        name="Atlas",
        lastname=lastname,
        email=f"{lastname.lower()}@example.com",
        status=CandidateStatus.active,
        experience=experience,
    )
    db.add(cand)
    await db.flush()
    return cand


def _contract(candidate_id: int, client_id: int, status: ContractStatus) -> Contract:
    return Contract(
        candidate_id=candidate_id,
        client_id=client_id,
        status=status,
        start_date=date(2025, 1, 1),
        rate_candidate=Decimal("100.000"),
        rate_client=Decimal("150.000"),
        margin=Decimal("50.000"),
        rate_unit="hourly",
    )


async def _seed_company() -> dict:
    tag = uuid.uuid4().hex[:8]
    company = f"Zyrafa Systemy {tag}"
    async with AsyncSessionLocal() as db:
        client = Client(name=company)
        db.add(client)
        await db.flush()

        active = await _candidate(db, f"Aktywny{tag}")
        ended = await _candidate(db, f"Zakonczony{tag}")
        draft = await _candidate(db, f"Szkic{tag}")
        void = await _candidate(db, f"Uniewazniony{tag}")
        flagged_now = await _candidate(db, f"Flaga{tag}")
        flag_lifted = await _candidate(db, f"FlagaZdjeta{tag}")
        # Najnowsza praca — ZAKOŃCZONA — na pozycji 0: stare `idx > 1` ją gubiło.
        past_first = await _candidate(
            db,
            f"Poprzedni{tag}",
            experience=[
                {
                    "company": company,
                    "role": "Analityk",
                    "start": "2020",
                    "end": "2023",
                },
                {
                    "company": "Inna Firma",
                    "role": "Junior",
                    "start": "2018",
                    "end": "2020",
                },
            ],
        )
        current_cv = await _candidate(
            db,
            f"Obecny{tag}",
            experience=[
                {
                    "company": f"{company} S.A.",
                    "role": "Lead",
                    "start": "2024",
                    "end": None,
                },
            ],
        )

        db.add_all(
            [
                _contract(active.id, client.id, ContractStatus.active),
                _contract(ended.id, client.id, ContractStatus.ended),
                _contract(draft.id, client.id, ContractStatus.draft),
                _contract(void.id, client.id, ContractStatus.void),
                CandidateConflict(
                    candidate_id=flagged_now.id,
                    client_id=client.id,
                    type=ConflictType.current_employment,
                    active=True,
                ),
                CandidateConflict(
                    candidate_id=flag_lifted.id,
                    client_id=client.id,
                    type=ConflictType.current_employment,
                    active=False,
                ),
            ]
        )
        await db.commit()
        return {
            "company": company,
            "client_id": client.id,
            "active": active.id,
            "ended": ended.id,
            "draft": draft.id,
            "void": void.id,
            "flagged_now": flagged_now.id,
            "flag_lifted": flag_lifted.id,
            "past_first": past_first.id,
            "current_cv": current_cv.id,
        }


def _by_id(body: dict) -> dict[int, str]:
    return {p["candidate_id"]: p["relationship"] for p in body["people"]}


@pytest.mark.asyncio
async def test_buckets_come_from_real_placements_not_drafts_or_flags(
    app_client,
) -> None:
    world = await _seed_company()

    resp = await app_client.post(
        URL, json={"names": [world["company"]]}, headers=_headers()
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    got = _by_id(body)

    assert body["matched_client"]["id"] == world["client_id"]
    # Umieszczeni przez nas: kontrakt, który faktycznie trwał.
    assert got[world["active"]] == "via_us"
    assert got[world["ended"]] == "via_us"
    # Szkic i unieważniony NIE są placementem — i nic innego ich nie łączy
    # z firmą, więc nie ma ich w odpowiedzi wcale.
    assert world["draft"] not in got
    assert world["void"] not in got
    # Flaga zatrudnienia to „pracuje tam", nie „przez nas".
    assert got[world["flagged_now"]] == "current"
    assert got[world["flag_lifted"]] == "past"
    # CV: zakończona praca na pozycji 0 to „past" (stare `idx > 1` ją gubiło),
    # otwarta — „current".
    assert got[world["past_first"]] == "past"
    assert got[world["current_cv"]] == "current"

    assert body["counts"] == {"via_us": 2, "current": 2, "past": 2, "unknown": 0}
    assert body["truncated"] is False


@pytest.mark.asyncio
async def test_past_predicate_matches_a_finished_job_at_position_zero() -> None:
    """Predykat SQL wprost — ten sam, którego używa filtr „Poprzednia firma”."""
    from app.api.candidates import _past_company_predicate

    world = await _seed_company()
    needle = world["company"].split()[-1]  # unikalny tag
    async with AsyncSessionLocal() as db:
        ids = set(
            (
                await db.execute(
                    select(Candidate.id).where(_past_company_predicate([needle]))
                )
            )
            .scalars()
            .all()
        )
    assert world["past_first"] in ids
    # Otwarta praca na pozycji 0 to praca OBECNA — nie wpada do „past".
    assert world["current_cv"] not in ids


@pytest.mark.asyncio
async def test_a_raw_alias_with_a_too_short_canonical_form_never_reaches_like(
    app_client, monkeypatch
) -> None:
    """„IT” (kanonicznie „it”) nie może iść do `LIKE '%it%'` obok pełnej nazwy."""
    world = await _seed_company()
    seen: list[list[str]] = []
    original = integrations_companies._current_company_predicate

    def spy(values):
        seen.append(list(values))
        return original(values)

    monkeypatch.setattr(integrations_companies, "_current_company_predicate", spy)
    resp = await app_client.post(
        URL, json={"names": [world["company"], "IT"]}, headers=_headers()
    )
    assert resp.status_code == 200, resp.text
    assert seen, "prefiltr nie został wywołany"
    assert all("IT" not in values and "it" not in values for values in seen), seen
    assert world["company"] in seen[0]


@pytest.mark.asyncio
async def test_prefilter_row_cap_flags_the_answer_as_truncated(
    app_client, monkeypatch
) -> None:
    world = await _seed_company()
    monkeypatch.setattr(integrations_companies, "_PREFILTER_ROW_CAP", 1)

    resp = await app_client.post(
        URL, json={"names": [world["company"]]}, headers=_headers()
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Dwa kontrakty, dwa trafienia w CV — sufit 1 widzi tylko część.
    assert body["truncated"] is True


@pytest.mark.asyncio
async def test_statement_timeout_becomes_a_503_not_a_hung_worker(
    app_client, monkeypatch
) -> None:
    """Limit czasu jest lokalny dla transakcji i kończy się czytelnym 503."""
    world = await _seed_company()
    monkeypatch.setattr(integrations_companies, "_STATEMENT_TIMEOUT_MS", 1)

    async def slow_resolve(db, canonical_names, nip):
        from sqlalchemy import text

        await db.execute(text("SELECT pg_sleep(0.2)"))
        return None

    monkeypatch.setattr(integrations_companies, "_resolve_client", slow_resolve)
    resp = await app_client.post(
        URL, json={"names": [world["company"]]}, headers=_headers()
    )
    assert resp.status_code == 503, resp.text
    assert resp.json()["detail"]["error"] == "lookup_timeout"

    # Limit nie wycieka poza żądanie: kolejne zapytanie w tej samej puli działa.
    monkeypatch.undo()
    ok = await app_client.post(
        URL, json={"names": [world["company"]]}, headers=_headers()
    )
    assert ok.status_code == 200, ok.text


# ── Szkic z realną obsadą to placement; `truncated` liczy WIERSZE (09.2026) ──


async def _hired_stage(
    db, *, candidate_id: int, client_id: int, reverted: bool
) -> None:
    """Etap „Zatrudniony" w rekrutacji klienta; `reverted` = późniejszy ruch.

    Rok spoza zakresu fixture'ów Insights — baza testowa jest wspólna, a etap
    `hired` to placement w widokach analitycznych.
    """
    from app.models.job import Job, JobStatus
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    job = Job(
        title=f"Atlas hired {uuid.uuid4().hex[:6]}",
        status=JobStatus.published,
        client_id=client_id,
    )
    db.add(job)
    await db.flush()
    db.add(
        CandidateStage(
            candidate_id=candidate_id,
            job_id=job.id,
            stage=PipelineStage.hired,
            moved_at=datetime(2046, 5, 4, 9, 0, tzinfo=timezone.utc),
        )
    )
    if reverted:
        db.add(
            CandidateStage(
                candidate_id=candidate_id,
                job_id=job.id,
                stage=PipelineStage.rejected,
                moved_at=datetime(2046, 5, 5, 9, 0, tzinfo=timezone.utc),
            )
        )


@pytest.mark.asyncio
async def test_a_draft_contract_counts_when_it_carries_a_live_order_or_a_hire(
    app_client,
) -> None:
    """Zatrudnienie zakłada SZKIC kontraktu — Delivery domyka go później.

    Do 09.2026 `via_us` pomijał każdy szkic, więc osoba pracująca u klienta na
    niedomkniętej w NEXUSIE umowie znikała z referencji. Szkic liczy się, gdy
    niesie realną obsadę (aktywne zamówienie albo bieżący etap „Zatrudniony"
    w rekrutacji tego klienta) — goły szkic dalej nie.
    """
    from app.models.client_order import ClientOrder, ClientOrderStatus

    tag = uuid.uuid4().hex[:8]
    company = f"Kormoran Uslugi {tag}"
    async with AsyncSessionLocal() as db:
        client = Client(name=company)
        db.add(client)
        await db.flush()

        with_order = await _candidate(db, f"SzkicZamowienie{tag}")
        signing_with_order = await _candidate(db, f"DoPodpisu{tag}")
        with_hire = await _candidate(db, f"SzkicZatrudniony{tag}")
        reverted_hire = await _candidate(db, f"CofnietyEtap{tag}")
        bare = await _candidate(db, f"GolySzkic{tag}")
        cancelled_order = await _candidate(db, f"AnulowaneZam{tag}")

        contracts = {
            with_order.id: _contract(with_order.id, client.id, ContractStatus.draft),
            signing_with_order.id: _contract(
                signing_with_order.id, client.id, ContractStatus.ready_for_signature
            ),
            with_hire.id: _contract(with_hire.id, client.id, ContractStatus.draft),
            reverted_hire.id: _contract(
                reverted_hire.id, client.id, ContractStatus.draft
            ),
            bare.id: _contract(bare.id, client.id, ContractStatus.draft),
            cancelled_order.id: _contract(
                cancelled_order.id, client.id, ContractStatus.draft
            ),
        }
        db.add_all(contracts.values())
        await db.flush()
        for candidate_id, status in (
            (with_order.id, ClientOrderStatus.active),
            (signing_with_order.id, ClientOrderStatus.active),
            (cancelled_order.id, ClientOrderStatus.cancelled),
        ):
            db.add(
                ClientOrder(
                    client_id=client.id,
                    contract_id=contracts[candidate_id].id,
                    title=f"Zamowienie {tag}",
                    status=status,
                    start_date=date(2026, 1, 1),
                )
            )
        await _hired_stage(
            db, candidate_id=with_hire.id, client_id=client.id, reverted=False
        )
        await _hired_stage(
            db, candidate_id=reverted_hire.id, client_id=client.id, reverted=True
        )
        await db.commit()
        ids = {
            "with_order": with_order.id,
            "signing_with_order": signing_with_order.id,
            "with_hire": with_hire.id,
            "reverted_hire": reverted_hire.id,
            "bare": bare.id,
            "cancelled_order": cancelled_order.id,
        }

    resp = await app_client.post(URL, json={"names": [company]}, headers=_headers())
    assert resp.status_code == 200, resp.text
    got = _by_id(resp.json())

    assert got.get(ids["with_order"]) == "via_us"
    assert got.get(ids["signing_with_order"]) == "via_us"
    assert got.get(ids["with_hire"]) == "via_us"
    # Cofnięte zatrudnienie, anulowane zamówienie i goły szkic nie są obsadą.
    assert ids["reverted_hire"] not in got
    assert ids["cancelled_order"] not in got
    assert ids["bare"] not in got
    assert resp.json()["counts"]["via_us"] == 3


@pytest.mark.asyncio
async def test_truncated_counts_conflict_rows_not_people(
    app_client, monkeypatch
) -> None:
    """Sufit prefiltra dotyczy WIERSZY — kilka zdjętych flag jednej osoby to kilka wierszy.

    Liczenie osób (unikalnych `candidate_id`) ukrywało ucięcie: sufit+1 wierszy
    dla mniej niż sufitu osób wracało jako odpowiedź kompletna.
    """
    tag = uuid.uuid4().hex[:8]
    company = f"Czapla Konsulting {tag}"
    async with AsyncSessionLocal() as db:
        client = Client(name=company)
        db.add(client)
        await db.flush()
        person = await _candidate(db, f"WieleFlag{tag}")
        db.add_all(
            [
                CandidateConflict(
                    candidate_id=person.id,
                    client_id=client.id,
                    type=ConflictType.current_employment,
                    active=False,
                )
                for _ in range(3)
            ]
        )
        await db.commit()
        person_id = person.id

    monkeypatch.setattr(integrations_companies, "_PREFILTER_ROW_CAP", 2)
    resp = await app_client.post(URL, json={"names": [company]}, headers=_headers())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert _by_id(body) == {person_id: "past"}
    assert body["truncated"] is True


@pytest.mark.asyncio
async def test_present_like_end_words_are_current_employment(app_client) -> None:
    """„present"/„obecnie"/„teraz" w `end` to praca OBECNA — w ATLAS i w filtrze listy."""
    from app.api.candidates import _current_company_predicate, _past_company_predicate

    tag = uuid.uuid4().hex[:8]
    company = f"Sikorka Dane {tag}"
    async with AsyncSessionLocal() as db:
        present_first = await _candidate(
            db,
            f"Obecnie{tag}",
            experience=[
                {"company": company, "role": "Lead", "start": "2023", "end": "Present"}
            ],
        )
        # Na dalszej pozycji — tam, gdzie historyczna reguła pozycji bez daty
        # liczy wpis jako przeszły; słowny znacznik tę regułę wyłącza.
        present_later = await _candidate(
            db,
            f"Teraz{tag}",
            experience=[
                {
                    "company": "Inna Firma",
                    "role": "Dev",
                    "start": "2015",
                    "end": "2019",
                },
                {
                    "company": "Druga Firma",
                    "role": "Dev",
                    "start": "2019",
                    "end": "2021",
                },
                {
                    "company": company,
                    "role": "Architekt",
                    "start": "2021",
                    # Tabulator i nowa linia z parsera CV — SQL musi
                    # przycinać tak samo jak Python (`.strip()`).
                    "end": "\tteraz\n",
                },
            ],
        )
        finished = await _candidate(
            db,
            f"Byly{tag}",
            experience=[
                {"company": company, "role": "Analityk", "start": "2018", "end": "2020"}
            ],
        )
        await db.commit()
        ids = (present_first.id, present_later.id, finished.id)

    resp = await app_client.post(URL, json={"names": [company]}, headers=_headers())
    assert resp.status_code == 200, resp.text
    got = _by_id(resp.json())
    assert got[ids[0]] == "current"
    assert got[ids[1]] == "current"
    assert got[ids[2]] == "past"

    async with AsyncSessionLocal() as db:
        past_ids = set(
            (
                await db.execute(
                    select(Candidate.id).where(_past_company_predicate([tag]))
                )
            )
            .scalars()
            .all()
        )
        current_ids = set(
            (
                await db.execute(
                    select(Candidate.id).where(_current_company_predicate([tag]))
                )
            )
            .scalars()
            .all()
        )
    assert past_ids & set(ids) == {ids[2]}
    assert current_ids & set(ids) == {ids[0], ids[1]}
