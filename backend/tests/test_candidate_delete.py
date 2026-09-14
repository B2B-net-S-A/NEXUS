"""Tests for `DELETE /api/candidates/{candidate_id}` — BLOCKED endpoint.

M2 audit PR 1 (M2-PRIV-02): operational hard delete is disabled. The ON
DELETE CASCADE sweep (migrations 0141+0146) silently removed contracts,
notes, stages and audit history while storage/Qdrant artifacts stayed
orphaned. Until the PR 2 privacy executor lands, the endpoint answers 409
(„privacy workflow required”) and the candidate + all related rows survive
byte-identical.

Guard order: ``DeliveryLeadPlus`` still runs first, so roles below
admin/delivery_lead get 403 and never reach the 409 block.

The schema invariant test (every candidate FK has an ON DELETE rule) stays —
the future privacy executor relies on the same DB rules.

Uses the in-process ``app_client`` / ``app_auth_headers`` fixtures from conftest
(real postgres in CI).
"""

from __future__ import annotations

import uuid

import pytest
from datetime import date

from httpx import AsyncClient
from sqlalchemy import func, select, text


async def _seed_candidate() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Del",
            lastname=f"Test-{uuid.uuid4().hex[:6]}",
            email=f"del-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_note(candidate_id: int) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.note import Note

    async with AsyncSessionLocal() as db:
        note = Note(candidate_id=candidate_id, content="zostanie usunięta z kandydatem")
        db.add(note)
        await db.commit()
        await db.refresh(note)
        return note.id


async def _seed_contract(candidate_id: int) -> int:
    """A contract is a previously-blocking relation (FK had no ON DELETE)."""
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.contract import Contract

    async with AsyncSessionLocal() as db:
        cli = Client(name=f"DelClient-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        contract = Contract(
            candidate_id=candidate_id,
            client_id=cli.id,
            start_date=date(2026, 1, 1),
        )
        db.add(contract)
        await db.commit()
        await db.refresh(contract)
        return contract.id


async def _count(model, **filters) -> int:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        stmt = select(func.count()).select_from(model)
        for col, val in filters.items():
            stmt = stmt.where(getattr(model, col) == val)
        return int(await db.scalar(stmt) or 0)


async def test_delete_candidate_requires_auth(app_client: AsyncClient):
    r = await app_client.delete("/api/candidates/1")
    # FastAPI HTTPBearer returns 403 when the Authorization header is missing.
    assert r.status_code in (401, 403)


async def test_admin_hard_delete_removes_the_candidate_and_its_notes(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Usunięcie jest REALNE (nie archiwizacja, nie soft-delete).

    Do 2026-08 ta trasa zwracała 409 (M2-PRIV-02), bo kaskada niszczyła też
    faktury. Odblokowana dopiero razem z migracją 0224, która odpina umowy —
    patrz test niżej.
    """
    from app.models.candidate import Candidate
    from app.models.note import Note

    candidate_id = await _seed_candidate()
    await _seed_note(candidate_id)

    assert await _count(Candidate, id=candidate_id) == 1
    assert await _count(Note, candidate_id=candidate_id) == 1

    r = await app_client.delete(
        f"/api/candidates/{candidate_id}", headers=app_auth_headers
    )
    assert r.status_code == 204, r.text

    # Kandydat i jego dane rekrutacyjne znikają z bazy.
    assert await _count(Candidate, id=candidate_id) == 0
    assert await _count(Note, candidate_id=candidate_id) == 0

    # GET zwraca 404 — profil naprawdę nie istnieje.
    r2 = await app_client.get(
        f"/api/candidates/{candidate_id}", headers=app_auth_headers
    )
    assert r2.status_code == 404


async def test_hard_delete_keeps_the_contract_and_pseudonymises_it(
    app_client: AsyncClient, app_auth_headers: dict
):
    """SEDNO migracji 0225: „usuń kandydata" nie znaczy „usuń faktury".

    `invoices`, `document_signatures` i `client_orders` nie mają własnego FK na
    kandydata — wiszą na umowie. Gdyby umowa poszła kaskadą, zniknęłyby razem
    z nią, a to dokumenty księgowe i dowodowe.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.contract import Contract

    candidate_id = await _seed_candidate()
    contract_id = await _seed_contract(candidate_id)

    r = await app_client.delete(
        f"/api/candidates/{candidate_id}", headers=app_auth_headers
    )
    assert r.status_code == 204, r.text

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)

    assert contract is not None, "umowa NIE MOŻE zniknąć razem z kandydatem"
    # FK wyzerowany przez ON DELETE SET NULL…
    assert contract.candidate_id is None
    # …ale dokument pozostaje przypisywalny do jednego podmiotu, inaczej
    # księgowość nie uzgodniłaby rozrachunków osoby, której już nie ma.
    assert contract.candidate_subject_ref
    assert len(contract.candidate_subject_ref) == 64


async def test_subject_reference_is_stable_and_not_the_raw_id(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Pseudonim jest kluczowanym HMAC-em, nie zapisanym id ani jego digestem.

    Gdyby był gołym hashem z `candidate_id`, odwróciłoby go przejście 10^7
    wartości — a wtedy „pseudonimizacja" nie pseudonimizuje niczego.
    """
    from app.services.candidate_audit import candidate_subject_reference

    ref = candidate_subject_reference(4242)
    assert ref == candidate_subject_reference(4242), "musi być deterministyczny"
    assert ref != candidate_subject_reference(4243)
    assert "4242" not in ref
    import hashlib

    assert ref != hashlib.sha256(b"4242").hexdigest()[:64]


async def test_hard_delete_emits_an_audit_row_that_survives_the_delete(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Ślad audytu musi przeżyć operację, którą opisuje.

    Zapisywany PRZED `db.delete()` — po usunięciu wiersza nie ma już czego
    audytować, a `Activity` nie jest kasowane kaskadą dla tej ścieżki.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.activity import Activity

    candidate_id = await _seed_candidate()
    await _seed_contract(candidate_id)

    r = await app_client.delete(
        f"/api/candidates/{candidate_id}", headers=app_auth_headers
    )
    assert r.status_code == 204, r.text

    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(Activity)
            .where(
                Activity.entity_type == "candidate",
                Activity.entity_id == candidate_id,
                Activity.action == "candidate_hard_deleted",
            )
            .order_by(Activity.id.desc())
            .limit(1)
        )
    assert row is not None, "audyt zniknął razem z kandydatem"
    assert row.details.get("operation") == "hard_delete"
    assert row.details.get("contracts_detached") == 1
    # Bez PII w payloadzie audytu.
    assert "@" not in str(row.details)


async def test_hard_delete_erases_full_search_rows_and_fails_active_scans(
    app_client: AsyncClient, app_auth_headers: dict
):
    """RODO: wiersze pełnego przeglądu bazy nie mają FK na kandydata.

    Niosą dowody dopasowania osoby, więc bez jawnego kasowania przeżywałyby
    usunięcie profilu. Aktywny przegląd nie może stracić wiersza po cichu
    (`finish_run` wymaga rozliczenia całej migawki), więc kończy się `failed`.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.activity import Activity
    from app.models.candidate_search_run import (
        CandidateSearchResult,
        CandidateSearchRun,
    )
    from app.models.client import Client
    from app.models.user import User, UserRole

    candidate_id = await _seed_candidate()
    bystander_id = await _seed_candidate()
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        author = User(
            name="Search author",
            email=f"search-author-{unique}@example.com",
            password_hash="unused",
            role=UserRole.recruiter,
            is_active=True,
        )
        client = Client(name=f"SearchErasure-{unique}")
        db.add_all([author, client])
        await db.flush()
        runs = {
            state: CandidateSearchRun(
                id=str(uuid.uuid4()),
                created_by=author.id,
                client_id=client.id,
                state=state,
                request_fingerprint="e" * 64,
                request_context={},
                version_trace={},
                population_size=2,
                metrics={},
            )
            for state in ("complete", "running")
        }
        db.add_all(runs.values())
        await db.flush()
        for run in runs.values():
            for cid in (candidate_id, bystander_id):
                db.add(
                    CandidateSearchResult(
                        run_id=run.id,
                        candidate_id=cid,
                        candidate_version="v1",
                        state="evaluated",
                        evidence={"requirements": [{"any_of": ["python"]}]},
                    )
                )
        await db.commit()
        run_ids = {state: run.id for state, run in runs.items()}
        author_id, client_id = author.id, client.id

    try:
        r = await app_client.delete(
            f"/api/candidates/{candidate_id}", headers=app_auth_headers
        )
        assert r.status_code == 204, r.text

        async with AsyncSessionLocal() as db:
            left = (
                await db.execute(
                    select(
                        CandidateSearchResult.run_id,
                        CandidateSearchResult.candidate_id,
                    ).where(CandidateSearchResult.run_id.in_(run_ids.values()))
                )
            ).all()
            finished = await db.get(CandidateSearchRun, run_ids["complete"])
            active = await db.get(CandidateSearchRun, run_ids["running"])
            audit = await db.scalar(
                select(Activity)
                .where(
                    Activity.entity_type == "candidate",
                    Activity.entity_id == candidate_id,
                    Activity.action == "candidate_hard_deleted",
                )
                .order_by(Activity.id.desc())
                .limit(1)
            )
        assert {cid for _, cid in left} == {bystander_id}, "usunięta osoba zostaje"
        assert len(left) == 2, "wiersze innych kandydatów nie mogą zniknąć"
        assert finished.state == "complete"
        assert active.state == "failed" and active.error_code == "candidate_erased"
        assert audit.details["search_rows_deleted"] == 2
        assert audit.details["search_runs_failed"] == 1
    finally:
        from sqlalchemy import delete

        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(CandidateSearchRun).where(
                    CandidateSearchRun.id.in_(list(run_ids.values()))
                )
            )
            await db.execute(
                text("DELETE FROM candidates WHERE id = :id"), {"id": bystander_id}
            )
            await db.execute(
                text("DELETE FROM clients WHERE id = :id"), {"id": client_id}
            )
            await db.execute(
                text("DELETE FROM users WHERE id = :id"), {"id": author_id}
            )
            await db.commit()


async def test_hard_delete_of_missing_candidate_is_404_not_204(
    app_client: AsyncClient, app_auth_headers: dict
):
    """204 na nieistniejącym id kłamałoby, że coś usunięto."""
    r = await app_client.delete("/api/candidates/999999999", headers=app_auth_headers)
    assert r.status_code == 404, r.text


async def test_every_candidate_fk_has_on_delete_rule():
    """Schema invariant (the real guard for the prod bug): EVERY foreign key
    referencing ``candidates.id`` must declare an ``ON DELETE`` rule (CASCADE or
    SET NULL).

    A FK left at NO ACTION/RESTRICT blocks the hard delete with an
    ``IntegrityError`` → unhandled 500 → Starlette emits it ABOVE the CORS
    middleware → the browser sees only an opaque "Network Error". Migration
    ``0146`` makes the DB authoritative for every candidate FK; this test fails
    if that migration is reverted or a new uncascaded FK is introduced.

    Postgres-specific: ``pg_constraint.confdeltype`` —
    a=NO ACTION, r=RESTRICT, c=CASCADE, n=SET NULL, d=SET DEFAULT.
    """
    from app.core.database import AsyncSessionLocal

    sql = text(
        """
        SELECT rel.relname AS table_name,
               att.attname AS column_name,
               con.confdeltype::text AS on_delete
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        JOIN pg_class frel ON frel.oid = con.confrelid
        JOIN pg_attribute att
          ON att.attrelid = con.conrelid AND att.attnum = ANY(con.conkey)
        WHERE con.contype = 'f' AND frel.relname = 'candidates'
        ORDER BY 1, 2
        """
    )
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(sql)).all()

    assert rows, "expected at least one FK referencing candidates"
    offenders = [(t, c, d) for (t, c, d) in rows if d not in ("c", "n")]
    assert not offenders, (
        "FK(s) to candidates without ON DELETE CASCADE/SET NULL — these block "
        f"hard delete and surface as a browser 'Network Error': {offenders}"
    )


@pytest.mark.parametrize("role_name", ["recruiter", "delivery_lead"])
async def test_hard_delete_is_admin_only(app_client: AsyncClient, role_name: str):
    """Guard jest WĘŻSZY niż przy zwykłej edycji kandydata.

    `delivery_lead` jest tu kluczowy, nie dekoracyjny: do 2026-08 ta trasa była
    chroniona `DeliveryLeadPlus`, więc DL mógł usuwać profile. Ticket zawęża to
    do admina, a bez tego przypadku nic by tego zawężenia nie pilnowało —
    przypadek rekrutera przechodziłby również pod starym, szerszym guardem.
    """
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.candidate import Candidate
    from app.models.user import User, UserRole

    unique = uuid.uuid4().hex[:8]
    email = f"pytest-{role_name}-{unique}@example.com"
    password = f"T3st_{unique}!PassX"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name=f"Pytest {role_name}",
                role=UserRole(role_name),
                is_active=True,
                profile_completed=True,
            )
        )
        await db.commit()

    login = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    candidate_id = await _seed_candidate()
    r = await app_client.delete(f"/api/candidates/{candidate_id}", headers=headers)
    assert r.status_code == 403, r.text

    # Kandydat przeżywa odrzuconą próbę.
    assert await _count(Candidate, id=candidate_id) == 1


async def test_missing_fingerprint_key_is_503_with_a_reason_not_a_bare_500(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Fail-closed ZOSTAJE, ale operator musi wiedzieć, dlaczego.

    Bez `CANDIDATE_IDENTITY_FINGERPRINT_KEY` nie da się spseudonimizować umów,
    więc usunięcie musi zostać zablokowane — inaczej faktury straciłyby jedyne
    powiązanie z podmiotem. Nieobsłużony `RuntimeError` dawał jednak gołe
    „Internal Server Error", a przyczynę tylko w logach.
    """
    from app.core.config import settings
    from app.models.candidate import Candidate

    candidate_id = await _seed_candidate()
    await _seed_contract(candidate_id)
    monkeypatch.setattr(settings, "CANDIDATE_IDENTITY_FINGERPRINT_KEY", "")

    r = await app_client.delete(
        f"/api/candidates/{candidate_id}", headers=app_auth_headers
    )
    assert r.status_code == 503, r.text
    assert "CANDIDATE_IDENTITY_FINGERPRINT_KEY" in r.json()["detail"]

    # Kandydat i umowa przeżywają zablokowaną próbę.
    assert await _count(Candidate, id=candidate_id) == 1


# ── F04 (audyt 14.09.2026): pliki storage idą do trwałego rejestru kasowań ───


async def _seed_candidate_with_files() -> tuple[int, list[str]]:
    """Kandydat z kluczem CV na wierszu i dokumentem w object storage."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.candidate_document import CandidateDocument, CandidateDocumentKind

    unique = uuid.uuid4().hex[:8]
    cv_key = f"cv/{unique}-cv.pdf"
    doc_key = f"cv/{unique}-doc.pdf"
    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Del",
            lastname=f"Files-{unique}",
            email=f"del-files-{unique}@example.com",
            cv_storage_key=cv_key,
        )
        db.add(c)
        await db.flush()
        db.add(
            CandidateDocument(
                candidate_id=c.id,
                filename="dokument.pdf",
                storage_key=doc_key,
                document_kind=CandidateDocumentKind.other,
            )
        )
        await db.commit()
        return c.id, sorted([cv_key, doc_key])


async def test_hard_delete_hands_storage_keys_to_the_cleanup_ledger(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """„Usunięcie wycofane w całości" nie obejmowało plików.

    Do 09.2026 handler kasował obiekty pętlą PRZED commitem, a błąd w jej
    środku dawał 503 i rollback — który nie przywraca obiektów skasowanych
    wcześniej w tej samej pętli. Teraz w żądaniu storage nie jest wołany
    wcale: klucze lądują w `cv_source_cleanup` w TEJ SAMEJ transakcji co
    usunięcie wiersza, a obiekty kasuje pętla tła z ponowieniami. Niedostępny
    storage (`is_available() == False`) nie blokuje już usunięcia.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.cv_source_cleanup import CvSourceCleanup
    from app.services import cv_source_cleanup, object_storage

    candidate_id, keys = await _seed_candidate_with_files()

    def _never(_key: str) -> None:
        raise AssertionError("storage nie może być wołany w żądaniu DELETE")

    monkeypatch.setattr(object_storage, "delete_cv", _never)
    monkeypatch.setattr(object_storage, "is_available", lambda: False)

    r = await app_client.delete(
        f"/api/candidates/{candidate_id}", headers=app_auth_headers
    )
    assert r.status_code == 204, r.text
    assert await _count(Candidate, id=candidate_id) == 0

    async with AsyncSessionLocal() as db:
        ledger = sorted(
            (
                await db.scalars(
                    select(CvSourceCleanup.storage_key).where(
                        CvSourceCleanup.storage_key.in_(keys)
                    )
                )
            ).all()
        )
    assert ledger == keys, "każdy klucz kandydata musi mieć wiersz w rejestrze"

    # Pętla tła zdejmuje wiersze i dopiero ONA woła storage.
    deleted: list[str] = []

    async def _fake_run(fn, key):
        assert fn is object_storage.delete_cv
        deleted.append(key)

    monkeypatch.setattr(cv_source_cleanup, "run_in_threadpool", _fake_run)
    async with AsyncSessionLocal() as db:
        await cv_source_cleanup.clean_pending_sources(db, limit=200)

    assert set(keys) <= set(deleted)
    async with AsyncSessionLocal() as db:
        left = (
            await db.scalars(
                select(CvSourceCleanup.storage_key).where(
                    CvSourceCleanup.storage_key.in_(keys)
                )
            )
        ).all()
    assert left == [], "po skasowaniu obiektów wiersze rejestru znikają"


async def test_ledger_rows_roll_back_with_a_failed_delete(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Rejestr żyje w transakcji usunięcia: odmowa (503 za brak klucza
    pseudonimizacji) nie może zostawić intencji kasowania plików żyjącego
    kandydata — pętla tła skasowałaby jego CV mimo że profil został."""
    from app.core.config import settings
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.cv_source_cleanup import CvSourceCleanup

    candidate_id, keys = await _seed_candidate_with_files()
    await _seed_contract(candidate_id)
    monkeypatch.setattr(settings, "CANDIDATE_IDENTITY_FINGERPRINT_KEY", "")

    r = await app_client.delete(
        f"/api/candidates/{candidate_id}", headers=app_auth_headers
    )
    assert r.status_code == 503, r.text
    assert await _count(Candidate, id=candidate_id) == 1

    async with AsyncSessionLocal() as db:
        ledger = (
            await db.scalars(
                select(CvSourceCleanup.storage_key).where(
                    CvSourceCleanup.storage_key.in_(keys)
                )
            )
        ).all()
    assert ledger == [], "odmowa nie może zakolejkować kasowania plików"
