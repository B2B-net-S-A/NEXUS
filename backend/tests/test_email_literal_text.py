"""Adres e-mail szukamy dokładnie, bez gałęzi literówek (20.10.2026).

Zgłoszenie rekrutera: w oknie „Dodaj kandydatów do pipeline” wpisany
``borysiewicz@onet.pl`` dawał 476 wyników — gałąź literówek (podobieństwo
trygramów ≥ 0,2 na imieniu, nazwisku i e-mailu) łapała każdego z adresem
w tej samej domenie, a właściwa osoba ginęła pod nimi. Adres to identyfikator:
trafia go podłańcuch w polach, CV i notatkach, literówek się nie szuka.

Baza testowa jest wspólna i nieczyszczona — asercje dotyczą własnych wierszy.
"""

import uuid

from sqlalchemy import select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate, CandidateStatus
from app.services.candidate_search_predicates import (
    literal_text_clause,
    literal_text_threshold,
    prepare_literal_text,
)


def test_email_nie_ma_progu_literowek() -> None:
    assert literal_text_threshold("borysiewicz@onet.pl") is None
    assert literal_text_threshold("  Borysiewicz@Onet.pl ") is None
    # imię i nazwisko dalej toleruje literówki
    assert literal_text_threshold("Mateusz Borysiewicz") == 0.5
    assert literal_text_threshold("borysiewicz") == 0.2


def test_klauzula_emaila_bez_galezi_podobienstwa() -> None:
    email_sql = str(literal_text_clause("borysiewicz@onet.pl"))
    name_sql = str(literal_text_clause("Borysiewicz Mateusz"))
    # operator podobieństwa pg_trgm (`%`) stoi tylko w gałęzi literówek;
    # wzorce ILIKE idą jako parametry, więc nie dają `%` w treści SQL
    assert " % " not in email_sql
    assert " % " in name_sql


async def test_email_trafia_tylko_wlasciciela_adresu() -> None:
    tag = uuid.uuid4().hex[:8]
    owner_email = f"borysiewicz-{tag}@onet.pl"
    async with AsyncSessionLocal() as db:
        rows = {
            "owner": Candidate(
                name="Mateusz", lastname=f"Borysiewicz-{tag}", email=owner_email
            ),
            "same_domain": Candidate(
                name="Kamil", lastname=f"Mol-{tag}", email=f"kamil.mol-{tag}@onet.pl"
            ),
            "in_cv": Candidate(
                name="Ola",
                lastname=f"Cv-{tag}",
                raw_cv_text=f"Kontakt: {owner_email.upper()}",
            ),
        }
        db.add_all(rows.values())
        await db.commit()
        ids = {key: c.id for key, c in rows.items()}

    async with AsyncSessionLocal() as db:
        clause = await prepare_literal_text(db, owner_email.upper())
        found = set(
            (
                await db.scalars(
                    select(Candidate.id).where(clause, Candidate.id.in_(ids.values()))
                )
            ).all()
        )
    assert {key for key, cid in ids.items() if cid in found} == {"owner", "in_cv"}


async def test_wlasciciel_adresu_pierwszy_w_oknie_dodawania(
    app_client, app_auth_headers
) -> None:
    """Okno „Dodaj kandydatów do pipeline” sortuje po `ts_rank` z `fts_doc`,
    w którym jest CV, ale nie pole e-mail — osoba z adresem w CV stała wyżej
    niż jego właściciel."""
    tag = uuid.uuid4().hex[:8]
    email = f"wlasciciel-{tag}@onet.pl"
    async with AsyncSessionLocal() as db:
        owner = Candidate(
            name="Mateusz",
            lastname=f"Wlasciciel-{tag}",
            email=email,
            status=CandidateStatus.active,
        )
        mention = Candidate(
            name="Ola",
            lastname=f"Polecajaca-{tag}",
            raw_cv_text=f"Polecam: {email}",
            status=CandidateStatus.active,
        )
        db.add_all([owner, mention])
        await db.commit()
        owner_id, mention_id = owner.id, mention.id

    resp = await app_client.post(
        "/api/search/candidates",
        json={
            "q": email,
            "sort": "relevance",
            "page": 1,
            "page_size": 25,
            "search_mode": "hybrid",
            "semantics_version": 2,
            "text_mode": "auto",
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["meta"]["interpretation"]["kind"] == "email"
    ids = [item["id"] for item in body["items"]]
    assert ids == [owner_id, mention_id], ids
