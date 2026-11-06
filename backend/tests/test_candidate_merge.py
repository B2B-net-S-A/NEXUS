"""Scalanie duplikatów kandydatów (PR2) — testy na żywej bazie.

Pokrywa:

- konflikt unikalności rozstrzygany PER WIERSZ (``my_people_overrides``:
  para, która się zderza, zostawia nowszy wpis; wpis bez kolizji jest
  przepinany — nigdy „usuń wszystkie wiersze duplikatu”);
- FK o innej nazwie kolumny (``application_submissions.matched_candidate_id``);
- referencje polimorficzne (``activities``, ``notifications`` z linkiem);
- wybór pól przy konflikcie + kontakt duplikatu zachowany w ``custom_fields``;
- tożsamość z Traffita przechodzi na ocalałego; oba z Traffita się scalają
  (Traffit wyłączony 14.10.2026), oba z innego żywego systemu = 409;
- odcisk: rozjazd = 409; ten sam kandydat = 422; rekruter = 403;
- ocalały zachowuje główne CV, a podgląd pokazuje plik, gdy główne się zmienia;
- karta w rekrutacji wspólnej dla obu profili: reguła etapu, podgląd, proces;
- Historia zdarzeń bez imion i nazwisk.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.activity import Activity
from app.models.application_submission import ApplicationSubmission
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.critical_event import CriticalEvent
from app.models.job import Job, JobStatus
from app.models.my_people import MyPeopleOverride
from app.models.notification import Notification, NotificationType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.recruitment_process import ProcessStatus, RecruitmentProcess
from app.models.user import User, UserRole
from app.services.candidate_merge import CardRow, card_after_merge

pytestmark = pytest.mark.asyncio


async def _user(app_client: AsyncClient, role: UserRole) -> tuple[int, dict]:
    unique = uuid.uuid4().hex[:8]
    email = f"merge-{role.value}-{unique}@example.com"
    password = f"P4ss_{unique}!X"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Merge {role.value}",
            role=role,
            roles=[role.value],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        user_id = user.id
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return user_id, {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _candidate(**fields) -> int:
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name=fields.pop("name", "Jan"),
            lastname=fields.pop("lastname", f"Scalany{suffix}"),
            email=fields.pop("email", f"merge-{suffix}@example.com"),
            **fields,
        )
        db.add(cand)
        await db.commit()
        return cand.id


async def _preview(api, headers, survivor: int, other: int):
    return await api.get(
        f"/api/candidates/{survivor}/merge-preview",
        params={"other": other},
        headers=headers,
    )


async def _merge(api, headers, survivor: int, other: int, fp: str, choices=None):
    return await api.post(
        f"/api/candidates/{survivor}/merge",
        json={"other": other, "fingerprint": fp, "choices": choices},
        headers=headers,
    )


async def test_merge_moves_rows_resolving_unique_conflicts_per_row(
    app_client: AsyncClient,
):
    admin_id, headers = await _user(app_client, UserRole.admin)
    other_id, _ = await _user(app_client, UserRole.recruiter)
    survivor = await _candidate(phone="+48 600 100 200")
    duplicate = await _candidate(phone="+48 600 999 999", tags=["kafka"])
    older = datetime.now(timezone.utc) - timedelta(days=5)
    async with AsyncSessionLocal() as db:
        # Kolizja: ten sam użytkownik przypiął OBU — zostaje nowszy wpis
        # (duplikatu), starszy (ocalałego) znika.
        db.add(
            MyPeopleOverride(
                user_id=admin_id, candidate_id=survivor, kind="pinned", created_at=older
            )
        )
        db.add(
            MyPeopleOverride(user_id=admin_id, candidate_id=duplicate, kind="pinned")
        )
        # Bez kolizji: przypięcie innej osoby po prostu przechodzi.
        db.add(
            MyPeopleOverride(user_id=other_id, candidate_id=duplicate, kind="pinned")
        )
        submission = ApplicationSubmission(
            submitted_first_name="Jan",
            submitted_last_name="Scalany",
            submitted_email="jan@example.com",
            matched_candidate_id=duplicate,
            status="linked",
        )
        db.add(submission)
        db.add(
            Activity(
                entity_type="candidate",
                entity_id=duplicate,
                action="note_added",
                user_id=admin_id,
                details={},
            )
        )
        db.add(
            Notification(
                user_id=admin_id,
                title="Nowe zgłoszenie",
                message="x",
                notification_type=NotificationType.new_application,
                related_entity_type="candidate",
                related_entity_id=duplicate,
                link=f"/candidates/{duplicate}",
            )
        )
        await db.commit()
        submission_id = submission.id

    preview = await _preview(app_client, headers, survivor, duplicate)
    assert preview.status_code == 200, preview.text
    plan = preview.json()
    assert plan["can_apply"] is True
    refs = {(r["table"], r["column"]): r for r in plan["references"]}
    assert refs[("my_people_overrides", "candidate_id")]["rows"] == 2
    assert refs[("my_people_overrides", "candidate_id")]["conflicts"] == 1
    assert refs[("application_submissions", "matched_candidate_id")]["rows"] == 1
    phone = next(f for f in plan["fields"] if f["field"] == "phone")
    assert phone["conflict"] is True

    merged = await _merge(
        app_client,
        headers,
        survivor,
        duplicate,
        plan["fingerprint"],
        choices={"phone": "duplicate"},
    )
    assert merged.status_code == 200, merged.text
    assert merged.json()["replaced_rows"] == 1

    async with AsyncSessionLocal() as db:
        assert await db.get(Candidate, duplicate) is None
        kept = await db.get(Candidate, survivor)
        assert kept.phone == "+48 600 999 999"
        assert "kafka" in kept.tags
        merged_contacts = kept.custom_fields["merged_duplicates"]
        assert merged_contacts[-1]["candidate_id"] == duplicate
        pins = (
            await db.scalars(
                select(MyPeopleOverride).where(
                    MyPeopleOverride.candidate_id == survivor
                )
            )
        ).all()
        assert sorted(p.user_id for p in pins) == sorted([admin_id, other_id])
        admin_pin = next(p for p in pins if p.user_id == admin_id)
        assert admin_pin.created_at > older  # nowszy (z duplikatu) wygrał
        sub = await db.get(ApplicationSubmission, submission_id)
        assert sub.matched_candidate_id == survivor
        moved_activity = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "candidate",
                Activity.entity_id == survivor,
                Activity.action == "note_added",
            )
        )
        assert moved_activity is not None
        note = await db.scalar(
            select(Notification).where(
                Notification.related_entity_type == "candidate",
                Notification.related_entity_id == survivor,
                Notification.user_id == admin_id,
            )
        )
        assert note is not None and note.link == f"/candidates/{survivor}"
        event = await db.scalar(
            select(CriticalEvent).where(
                CriticalEvent.event_type == "candidate.merge",
                CriticalEvent.entity_id == survivor,
            )
        )
        assert event is not None and event.outcome == "executed"
        assert "Scalany" not in (event.reason or "") + (event.entity_label or "")


async def test_traffit_identity_moves_to_survivor(app_client: AsyncClient):
    _, headers = await _user(app_client, UserRole.head_of_recruitment)
    ext = f"tt-{uuid.uuid4().hex[:8]}"
    survivor = await _candidate()
    duplicate = await _candidate(external_source="traffit", external_id=ext)

    plan = (await _preview(app_client, headers, survivor, duplicate)).json()
    resp = await _merge(app_client, headers, survivor, duplicate, plan["fingerprint"])
    assert resp.status_code == 200, resp.text
    async with AsyncSessionLocal() as db:
        kept = await db.get(Candidate, survivor)
        assert (kept.external_source, kept.external_id) == ("traffit", ext)


async def test_both_from_traffit_merge_keeps_duplicate_id_in_history(
    app_client: AsyncClient,
):
    _, headers = await _user(app_client, UserRole.admin)
    survivor_ext = f"tt-{uuid.uuid4().hex[:8]}"
    duplicate_ext = f"tt-{uuid.uuid4().hex[:8]}"
    survivor = await _candidate(external_source="traffit", external_id=survivor_ext)
    duplicate = await _candidate(external_source="traffit", external_id=duplicate_ext)

    plan = (await _preview(app_client, headers, survivor, duplicate)).json()
    assert plan["can_apply"] is True
    assert plan["blockers"] == []

    resp = await _merge(app_client, headers, survivor, duplicate, plan["fingerprint"])
    assert resp.status_code == 200, resp.text
    async with AsyncSessionLocal() as db:
        assert await db.get(Candidate, duplicate) is None
        kept = await db.get(Candidate, survivor)
        assert (kept.external_source, kept.external_id) == ("traffit", survivor_ext)
        entry = kept.custom_fields["merged_duplicates"][-1]
        assert entry["candidate_id"] == duplicate
        assert entry["external_source"] == "traffit"
        assert entry["external_id"] == duplicate_ext


async def test_both_from_same_live_external_source_is_blocked(app_client: AsyncClient):
    _, headers = await _user(app_client, UserRole.admin)
    survivor = await _candidate(
        external_source="talent_radar", external_id=f"tr-{uuid.uuid4().hex[:8]}"
    )
    duplicate = await _candidate(
        external_source="talent_radar", external_id=f"tr-{uuid.uuid4().hex[:8]}"
    )
    plan = (await _preview(app_client, headers, survivor, duplicate)).json()
    assert plan["can_apply"] is False
    assert [b["code"] for b in plan["blockers"]] == ["both_external"]

    resp = await _merge(app_client, headers, survivor, duplicate, plan["fingerprint"])
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "merge_blocked"
    async with AsyncSessionLocal() as db:
        assert await db.get(Candidate, duplicate) is not None


async def test_stale_fingerprint_is_409_and_keeps_both(app_client: AsyncClient):
    _, headers = await _user(app_client, UserRole.admin)
    survivor = await _candidate()
    duplicate = await _candidate()
    plan = (await _preview(app_client, headers, survivor, duplicate)).json()
    async with AsyncSessionLocal() as db:
        dup = await db.get(Candidate, duplicate)
        dup.city = "Gdańsk"
        await db.commit()

    resp = await _merge(app_client, headers, survivor, duplicate, plan["fingerprint"])
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "fingerprint_mismatch"
    async with AsyncSessionLocal() as db:
        assert await db.get(Candidate, duplicate) is not None


async def test_refusals(app_client: AsyncClient):
    _, admin = await _user(app_client, UserRole.admin)
    _, recruiter = await _user(app_client, UserRole.recruiter)
    survivor = await _candidate()
    duplicate = await _candidate()

    same = await _preview(app_client, admin, survivor, survivor)
    assert same.status_code == 422
    missing = await _preview(app_client, admin, survivor, 999_999_999)
    assert missing.status_code == 404
    forbidden = await _preview(app_client, recruiter, survivor, duplicate)
    assert forbidden.status_code == 403
    forbidden = await _merge(app_client, recruiter, survivor, duplicate, "0" * 64)
    assert forbidden.status_code == 403


async def test_academy_rejection_survives_merge_with_a_newer_application(
    app_client: AsyncClient,
):
    """Akademia pamięta „nie” na zawsze. Scalenie profilu odrzuconej osoby z jej
    świeżym profilem (nowe zgłoszenie z innym e-mailem) nie może zostawić
    NOWSZEGO wiersza „do telefonu” — wygrywa odrzucenie, z śladem powrotu.
    Ocalały ma świeży wiersz, więc bez tej reguły (remis/nowszy = ocalały)
    odrzucenie znikałoby razem z duplikatem."""
    from app.models.academy import AcademyApplication, AcademyProgram

    _, headers = await _user(app_client, UserRole.admin)
    survivor = await _candidate()
    duplicate = await _candidate()
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        program = AcademyProgram(name=f"Merge {uuid.uuid4().hex[:6]}")
        db.add(program)
        await db.flush()
        rejected = AcademyApplication(
            program_id=program.id,
            candidate_id=duplicate,
            applied_at=now - timedelta(days=60),
            status="rejected",
            closed_reason="Doświadczenie ponad limit",
            closed_at=now - timedelta(days=59),
        )
        fresh = AcademyApplication(
            program_id=program.id,
            candidate_id=survivor,
            applied_at=now - timedelta(days=1),
            status="to_call",
        )
        db.add_all([rejected, fresh])
        await db.commit()
        rejected_id, fresh_id = rejected.id, fresh.id

    preview = await _preview(app_client, headers, survivor, duplicate)
    assert preview.status_code == 200, preview.text
    merged = await _merge(
        app_client, headers, survivor, duplicate, preview.json()["fingerprint"]
    )
    assert merged.status_code == 200, merged.text

    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(
                select(AcademyApplication).where(
                    AcademyApplication.program_id == program.id
                )
            )
        ).all()
        assert [r.id for r in rows] == [rejected_id]
        kept = rows[0]
        assert kept.candidate_id == survivor
        assert kept.status == "rejected"
        assert kept.reapplied_at is not None
        assert await db.get(AcademyApplication, fresh_id) is None


async def test_jarvis_conversation_links_follow_the_survivor(app_client: AsyncClient):
    """Runda 6 audytu: powiązanie rozmowy Jarvisa z duplikatem musi przejść na
    ocalałego — po nim usunięcie osoby (art. 17) kasuje rozmowy."""
    from app.models.jarvis import JarvisConversation, JarvisConversationEntity

    user_id, headers = await _user(app_client, UserRole.admin)
    survivor = await _candidate()
    duplicate = await _candidate()
    async with AsyncSessionLocal() as db:
        only_dup = JarvisConversation(user_id=user_id)
        both = JarvisConversation(user_id=user_id)
        db.add_all([only_dup, both])
        await db.flush()
        db.add_all(
            [
                JarvisConversationEntity(
                    conversation_id=only_dup.id,
                    entity_type="candidate",
                    entity_id=duplicate,
                ),
                JarvisConversationEntity(
                    conversation_id=both.id,
                    entity_type="candidate",
                    entity_id=duplicate,
                ),
                JarvisConversationEntity(
                    conversation_id=both.id, entity_type="candidate", entity_id=survivor
                ),
            ]
        )
        await db.commit()
        only_dup_id, both_id = only_dup.id, both.id

    preview = await _preview(app_client, headers, survivor, duplicate)
    assert preview.status_code == 200, preview.text
    merged = await _merge(
        app_client, headers, survivor, duplicate, preview.json()["fingerprint"]
    )
    assert merged.status_code == 200, merged.text

    async with AsyncSessionLocal() as db:
        links = (
            await db.execute(
                select(
                    JarvisConversationEntity.conversation_id,
                    JarvisConversationEntity.entity_id,
                ).where(
                    JarvisConversationEntity.conversation_id.in_([only_dup_id, both_id])
                )
            )
        ).all()
    assert sorted((str(c), e) for c, e in links) == sorted(
        [(str(only_dup_id), survivor), (str(both_id), survivor)]
    )


async def test_merge_fences_active_search_runs_like_erasure(app_client: AsyncClient):
    """Runda 8 (R8-N11-6): migawka przeglądu bazy z obiema osobami.

    Przepięcie wiersza duplikatu kolidowało z PK `(run_id, candidate_id)`
    i łamało kompletność migawki — `finish_run` rzucał ValueError przy każdej
    próbie, aż przegląd kończył się `failed` z nieczytelnym kodem. Scalenie
    ogradza go teraz jak usunięcie osoby.
    """
    from sqlalchemy import delete

    from app.models.candidate_search_run import (
        CandidateSearchResult,
        CandidateSearchRun,
    )
    from app.models.client import Client

    user_id, headers = await _user(app_client, UserRole.admin)
    survivor = await _candidate()
    duplicate = await _candidate()
    active_id, finished_id = str(uuid.uuid4()), str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        client = Client(name=f"R8-N11-6-{uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.flush()
        for run_id, state in ((active_id, "running"), (finished_id, "complete")):
            db.add(
                CandidateSearchRun(
                    id=run_id,
                    created_by=user_id,
                    client_id=client.id,
                    state=state,
                    request_fingerprint="m" * 64,
                    request_context={},
                    version_trace={},
                    population_size=2,
                    metrics={},
                )
            )
        await db.flush()
        for run_id in (active_id, finished_id):
            for cid in (survivor, duplicate):
                db.add(
                    CandidateSearchResult(
                        run_id=run_id,
                        candidate_id=cid,
                        candidate_version="v",
                        state="pending",
                    )
                )
        await db.commit()

    try:
        preview = await _preview(app_client, headers, survivor, duplicate)
        assert preview.status_code == 200, preview.text
        merged = await _merge(
            app_client, headers, survivor, duplicate, preview.json()["fingerprint"]
        )
        assert merged.status_code == 200, merged.text

        async with AsyncSessionLocal() as db:
            active = await db.get(CandidateSearchRun, active_id)
            finished = await db.get(CandidateSearchRun, finished_id)
            # Runda 9 (R9-N5-7): przegląd w toku traci wiersz duplikatu, nie pada.
            assert (active.state, active.population_size) == ("running", 1)
            assert finished.state == "complete"
            left = (
                await db.execute(
                    select(
                        CandidateSearchResult.run_id, CandidateSearchResult.candidate_id
                    ).where(CandidateSearchResult.run_id.in_([active_id, finished_id]))
                )
            ).all()
        assert sorted(tuple(r) for r in left) == sorted(
            [(active_id, survivor), (finished_id, survivor)]
        )
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(CandidateSearchRun).where(
                    CandidateSearchRun.id.in_([active_id, finished_id])
                )
            )
            await db.commit()


async def test_two_primary_cvs_both_survive_merge_with_one_primary(
    app_client: AsyncClient,
):
    """Runda 9 (R9-N8-2): scalenie nigdy nie kasuje CV.

    Częściowy indeks „jedno główne CV na osobę” był traktowany jak zwykły
    konflikt i starszy wiersz znikał; ta sama treść (odcisk SHA) w obu
    profilach też kończyła się DELETE-em.
    """
    from app.models.candidate_document import CandidateDocument, CandidateDocumentKind

    _, headers = await _user(app_client, UserRole.admin)
    survivor = await _candidate()
    duplicate = await _candidate()
    older = datetime.now(timezone.utc) - timedelta(days=3)
    same_sha = uuid.uuid4().hex * 2
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                CandidateDocument(
                    candidate_id=survivor,
                    filename="stare.pdf",
                    storage_key=f"cv/t/{uuid.uuid4().hex}.pdf",
                    document_kind=CandidateDocumentKind.cv,
                    is_primary=True,
                    created_at=older,
                    updated_at=older,
                ),
                CandidateDocument(
                    candidate_id=duplicate,
                    filename="nowe.pdf",
                    storage_key=f"cv/t/{uuid.uuid4().hex}.pdf",
                    document_kind=CandidateDocumentKind.cv,
                    is_primary=True,
                ),
                CandidateDocument(
                    candidate_id=survivor,
                    filename="kopia-a.pdf",
                    storage_key=f"cv/t/{uuid.uuid4().hex}.pdf",
                    document_kind=CandidateDocumentKind.other,
                    content_sha256=same_sha,
                ),
                CandidateDocument(
                    candidate_id=duplicate,
                    filename="kopia-b.pdf",
                    storage_key=f"cv/t/{uuid.uuid4().hex}.pdf",
                    document_kind=CandidateDocumentKind.other,
                    content_sha256=same_sha,
                ),
            ]
        )
        await db.commit()

    plan = (await _preview(app_client, headers, survivor, duplicate)).json()
    resp = await _merge(app_client, headers, survivor, duplicate, plan["fingerprint"])
    assert resp.status_code == 200, resp.text

    async with AsyncSessionLocal() as db:
        docs = (
            await db.scalars(
                select(CandidateDocument).where(
                    CandidateDocument.candidate_id == survivor
                )
            )
        ).all()
        assert sorted(d.filename for d in docs) == [
            "kopia-a.pdf",
            "kopia-b.pdf",
            "nowe.pdf",
            "stare.pdf",
        ]
        assert [d.filename for d in docs if d.is_primary] == ["stare.pdf"]
        shas = [d.content_sha256 for d in docs if d.filename.startswith("kopia")]
        assert shas.count(same_sha) == 1


async def _primary_doc(candidate_id: int, filename: str, *, at: datetime) -> int:
    from app.models.candidate_document import CandidateDocument, CandidateDocumentKind

    async with AsyncSessionLocal() as db:
        doc = CandidateDocument(
            candidate_id=candidate_id,
            filename=filename,
            storage_key=f"cv/t/{uuid.uuid4().hex}.pdf",
            document_kind=CandidateDocumentKind.cv,
            is_primary=True,
            created_at=at,
            updated_at=at,
        )
        db.add(doc)
        await db.commit()
        return doc.id


async def _primary_filenames(candidate_id: int) -> list[str]:
    from app.models.candidate_document import CandidateDocument

    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(CandidateDocument.filename).where(
                        CandidateDocument.candidate_id == candidate_id,
                        CandidateDocument.is_primary.is_(True),
                    )
                )
            ).all()
        )


async def test_merge_keeps_survivor_primary_cv_when_duplicate_row_is_newer(
    app_client: AsyncClient,
):
    """05.11.2026: data wiersza to data importu, nie wersja CV.

    Nowszy wiersz duplikatu zabierał flagę: ocalały dostawał CV bez danych
    osobowych albo starszą wersję, a podgląd tego nie pokazywał. Generator
    i paczka CV brały potem ten plik.
    """
    _, headers = await _user(app_client, UserRole.admin)
    survivor = await _candidate()
    duplicate = await _candidate()
    now = datetime.now(timezone.utc)
    kept = await _primary_doc(survivor, "ocalaly.pdf", at=now - timedelta(days=30))
    await _primary_doc(duplicate, "duplikat.pdf", at=now)

    plan = (await _preview(app_client, headers, survivor, duplicate)).json()
    assert plan["primary_cv"]["changes"] is False
    assert plan["primary_cv"]["after"]["document_id"] == kept

    resp = await _merge(app_client, headers, survivor, duplicate, plan["fingerprint"])
    assert resp.status_code == 200, resp.text
    assert await _primary_filenames(survivor) == ["ocalaly.pdf"]


async def test_merge_preview_shows_duplicate_primary_cv_when_survivor_has_none(
    app_client: AsyncClient,
):
    _, headers = await _user(app_client, UserRole.admin)
    survivor = await _candidate()
    duplicate = await _candidate()
    incoming = await _primary_doc(
        duplicate, "duplikat.pdf", at=datetime.now(timezone.utc)
    )

    plan = (await _preview(app_client, headers, survivor, duplicate)).json()
    assert plan["primary_cv"] == {
        "before": None,
        "after": {
            "document_id": incoming,
            "filename": "duplikat.pdf",
            "from_duplicate": True,
        },
        "changes": True,
    }

    resp = await _merge(app_client, headers, survivor, duplicate, plan["fingerprint"])
    assert resp.status_code == 200, resp.text
    assert await _primary_filenames(survivor) == ["duplikat.pdf"]


async def test_merge_preview_shows_when_duplicate_primary_replaces_legacy_cv(
    app_client: AsyncClient,
):
    """CV z kolumn ocalałego ustępuje dokumentowi w ``get_current_cv``."""
    _, headers = await _user(app_client, UserRole.admin)
    survivor = await _candidate(
        cv_filename="z-kolumn.pdf", cv_storage_key=f"cv/t/{uuid.uuid4().hex}.pdf"
    )
    duplicate = await _candidate()
    await _primary_doc(duplicate, "duplikat.pdf", at=datetime.now(timezone.utc))

    primary_cv = (await _preview(app_client, headers, survivor, duplicate)).json()[
        "primary_cv"
    ]
    assert primary_cv["before"] == {
        "document_id": None,
        "filename": "z-kolumn.pdf",
        "from_duplicate": False,
    }
    assert primary_cv["after"]["filename"] == "duplikat.pdf"
    assert primary_cv["changes"] is True


async def test_merge_fingerprint_follows_primary_cv(app_client: AsyncClient):
    """Nowe główne CV między podglądem a scaleniem = nieaktualny podgląd."""
    _, headers = await _user(app_client, UserRole.admin)
    survivor = await _candidate()
    duplicate = await _candidate()
    from app.models.candidate_document import CandidateDocument

    doc_id = await _primary_doc(
        duplicate, "duplikat.pdf", at=datetime.now(timezone.utc)
    )
    async with AsyncSessionLocal() as db:
        (await db.get(CandidateDocument, doc_id)).is_primary = False
        await db.commit()
    plan = (await _preview(app_client, headers, survivor, duplicate)).json()
    assert plan["primary_cv"]["changes"] is False
    async with AsyncSessionLocal() as db:
        (await db.get(CandidateDocument, doc_id)).is_primary = True
        await db.commit()

    resp = await _merge(app_client, headers, survivor, duplicate, plan["fingerprint"])
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "fingerprint_mismatch"


async def test_merge_keeps_duplicate_legacy_cv_as_extra_document(
    app_client: AsyncClient,
):
    from app.models.candidate_document import CandidateDocument

    _, headers = await _user(app_client, UserRole.admin)
    survivor = await _candidate(
        cv_filename="ocalaly.pdf", cv_storage_key=f"cv/t/{uuid.uuid4().hex}.pdf"
    )
    dup_key = f"cv/t/{uuid.uuid4().hex}.pdf"
    duplicate = await _candidate(cv_filename="duplikat.pdf", cv_storage_key=dup_key)
    plan = (await _preview(app_client, headers, survivor, duplicate)).json()
    resp = await _merge(app_client, headers, survivor, duplicate, plan["fingerprint"])
    assert resp.status_code == 200, resp.text
    async with AsyncSessionLocal() as db:
        kept = await db.scalar(
            select(CandidateDocument).where(
                CandidateDocument.candidate_id == survivor,
                CandidateDocument.storage_key == dup_key,
            )
        )
        assert kept is not None and kept.is_primary is False


async def test_merge_restrictive_facts_and_empty_fields_come_from_duplicate(
    app_client: AsyncClient,
):
    """Runda 9 (R9-N8-1): czarna lista i „tylko etat” nie znikają przy scaleniu."""
    from app.models.candidate import CandidateStatus

    _, headers = await _user(app_client, UserRole.admin)
    survivor = await _candidate(b2b_willingness="b2b", accepts_more_office_days=True)
    duplicate = await _candidate(
        status=CandidateStatus.blacklisted,
        b2b_willingness="employment_only",
        accepts_more_office_days=False,
        skills=[{"name": "Kotlin"}],
        work_time_preference="part_time_only",
    )
    plan = (await _preview(app_client, headers, survivor, duplicate)).json()
    fields = {f["field"]: f for f in plan["fields"]}
    assert fields["status"]["rule"] == "restrictive"
    assert fields["status"]["default"] == "duplicate"
    assert fields["b2b_willingness"]["default"] == "duplicate"
    assert fields["skills"]["duplicate"] == "Kotlin"

    # Pola restrykcyjne nie są do wyboru.
    refused = await _merge(
        app_client,
        headers,
        survivor,
        duplicate,
        plan["fingerprint"],
        choices={"status": "survivor"},
    )
    assert refused.status_code == 422
    resp = await _merge(app_client, headers, survivor, duplicate, plan["fingerprint"])
    assert resp.status_code == 200, resp.text
    async with AsyncSessionLocal() as db:
        kept = await db.get(Candidate, survivor)
        assert kept.status == CandidateStatus.blacklisted
        assert kept.b2b_willingness == "employment_only"
        assert kept.accepts_more_office_days is False
        assert kept.skills == [{"name": "Kotlin"}]
        assert kept.work_time_preference == "part_time_only"


async def _job(recruiter_id: int) -> int:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Merge client {tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Merge job {tag}",
            client_id=client.id,
            status=JobStatus.published,
            recruiter_id=recruiter_id,
        )
        db.add(job)
        await db.commit()
        return job.id


async def _stages(
    candidate_id: int, job_id: int, *rows: tuple[PipelineStage, datetime]
) -> None:
    async with AsyncSessionLocal() as db:
        db.add_all(
            CandidateStage(
                candidate_id=candidate_id,
                job_id=job_id,
                stage=stage,
                moved_at=moved_at,
            )
            for stage, moved_at in rows
        )
        await db.commit()


async def _board_stage(api, headers, job_id: int, candidate_id: int) -> list[str]:
    resp = await api.get(f"/api/pipeline/kanban/{job_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    return [
        item["stage"]
        for column in resp.json()["columns"]
        for item in column["items"]
        if item["candidate_id"] == candidate_id
    ]


@pytest.mark.parametrize(
    ("survivor", "duplicate", "kept"),
    [
        # Dwa żywe etapy: zostaje dalszy, niezależnie od daty i strony.
        (("cv_sent", 1), ("screening", 2), "survivor"),
        (("screening", 2), ("cv_sent", 1), "duplicate"),
        (("new", 1), ("screening", 2), "duplicate"),
        # Ten sam etap: nowszy wiersz.
        (("new", 2), ("new", 1), "survivor"),
        (("new", 1), ("new", 2), "duplicate"),
        # Zatrudniony wygrywa zawsze, także z nowszym odrzuceniem.
        (("hired", 1), ("rejected", 2), "survivor"),
        (("screening", 2), ("hired", 1), "duplicate"),
        # Automatyczne „Nowi” po odrzuceniu niczego nie odwołuje (789166).
        (("new", 2), ("rejected", 1), "duplicate"),
        (("posting", 2), ("withdrawn", 1), "duplicate"),
        # Nowsza praca dalej niż „Nowi” odwołuje starsze odrzucenie.
        (("screening", 2), ("rejected", 1), "survivor"),
        # Nowsze odrzucenie zostaje, nawet gdy drugi profil był dalej.
        (("cv_sent", 1), ("rejected", 2), "duplicate"),
        # Dwa etapy końcowe: nowszy wiersz.
        (("rejected", 2), ("withdrawn", 1), "survivor"),
        (("rejected", 1), ("withdrawn", 2), "duplicate"),
    ],
)
async def test_card_after_merge_rule(survivor, duplicate, kept):
    base = datetime(2026, 10, 1, tzinfo=timezone.utc)

    def row(spec: tuple[str, int], row_id: int) -> CardRow:
        return CardRow(
            stage=PipelineStage(spec[0]),
            moved_at=base + timedelta(days=spec[1]),
            id=row_id,
        )

    assert card_after_merge(row(survivor, 1), row(duplicate, 2)) == kept


async def _card_history(job_id: int, candidate_id: int) -> list[CandidateStage]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(CandidateStage)
                    .where(
                        CandidateStage.candidate_id == candidate_id,
                        CandidateStage.job_id == job_id,
                    )
                    .order_by(CandidateStage.moved_at, CandidateStage.id)
                )
            ).all()
        )


async def test_merge_keeps_the_card_further_in_the_process(app_client: AsyncClient):
    """Nowszy wiersz duplikatu nie cofa karty z „CV wysłane” na „Screening”."""
    admin_id, headers = await _user(app_client, UserRole.admin)
    job_id = await _job(admin_id)
    survivor = await _candidate()
    duplicate = await _candidate()
    t0 = datetime.now(timezone.utc) - timedelta(days=10)
    await _stages(
        survivor,
        job_id,
        (PipelineStage.new, t0),
        (PipelineStage.cv_sent, t0 + timedelta(days=1)),
    )
    newest = t0 + timedelta(days=3)
    await _stages(
        duplicate,
        job_id,
        (PipelineStage.new, t0 + timedelta(days=2)),
        (PipelineStage.screening, newest),
    )

    plan = (await _preview(app_client, headers, survivor, duplicate)).json()
    assert len(plan["cards"]) == 1
    card = plan["cards"][0]
    assert card["job_id"] == job_id
    assert card["survivor_stage"] == "cv_sent"
    assert card["duplicate_stage"] == "screening"
    assert card["result_stage"] == "cv_sent"
    assert card["result_stage_name"] == "CV Wysłane"
    assert card["kept"] == "survivor"
    assert card["restores"] is True

    merged = await _merge(app_client, headers, survivor, duplicate, plan["fingerprint"])
    assert merged.status_code == 200, merged.text
    assert merged.json()["cards_restored"] == 1

    assert await _board_stage(app_client, headers, job_id, survivor) == ["cv_sent"]
    history = await _card_history(job_id, survivor)
    # Historia obu profili zostaje, wynik to dopisany wiersz tuż po najnowszym:
    # bez nowej daty liczniki dnia i terminy z etapu nie ruszają się od scalenia.
    assert [row.stage.value for row in history] == [
        "new",
        "cv_sent",
        "new",
        "screening",
        "cv_sent",
    ]
    assert history[-1].moved_at == newest + timedelta(microseconds=1)
    assert history[-1].notes

    async with AsyncSessionLocal() as db:
        activity = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "candidate",
                Activity.entity_id == survivor,
                Activity.action == "candidates_merged",
            )
        )
        assert activity.details["cards_restored"] == [
            {
                "job_id": job_id,
                "stage": "cv_sent",
                "new_stage_row_id": history[-1].id,
                "from_stage_row_id": history[1].id,
            }
        ]

    move = await app_client.post(
        "/api/pipeline/move",
        json={"candidate_id": survivor, "job_id": job_id, "stage": "client_interview"},
        headers=headers,
    )
    assert move.status_code == 200, move.text
    assert await _board_stage(app_client, headers, job_id, survivor) == [
        "client_interview"
    ]


async def test_merge_newest_card_wins_adds_no_row(app_client: AsyncClient):
    admin_id, headers = await _user(app_client, UserRole.admin)
    job_id = await _job(admin_id)
    survivor = await _candidate()
    duplicate = await _candidate()
    t0 = datetime.now(timezone.utc) - timedelta(days=10)
    await _stages(survivor, job_id, (PipelineStage.new, t0))
    await _stages(duplicate, job_id, (PipelineStage.cv_sent, t0 + timedelta(days=1)))

    plan = (await _preview(app_client, headers, survivor, duplicate)).json()
    assert plan["cards"][0]["restores"] is False
    assert plan["cards"][0]["kept"] == "duplicate"
    merged = await _merge(app_client, headers, survivor, duplicate, plan["fingerprint"])
    assert merged.status_code == 200, merged.text
    assert merged.json()["cards_restored"] == 0
    assert len(await _card_history(job_id, survivor)) == 2
    assert await _board_stage(app_client, headers, job_id, survivor) == ["cv_sent"]


async def test_merge_older_rejection_beats_newer_entry_row_with_its_reason(
    app_client: AsyncClient,
):
    """Karta wraca na odrzucenie z powodem i notatką, jak na wierszu człowieka."""
    admin_id, headers = await _user(app_client, UserRole.admin)
    job_id = await _job(admin_id)
    survivor = await _candidate()
    duplicate = await _candidate()
    t0 = datetime.now(timezone.utc) - timedelta(days=10)
    await _stages(survivor, job_id, (PipelineStage.new, t0 + timedelta(minutes=3)))
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=duplicate,
                job_id=job_id,
                stage=PipelineStage.rejected,
                moved_at=t0,
                moved_by=admin_id,
                notes="Pracuje u tego klienta",
                rejection_note="Inne",
                ended_by="recruiter",
            )
        )
        await db.commit()

    plan = (await _preview(app_client, headers, survivor, duplicate)).json()
    assert plan["cards"][0]["result_stage"] == "rejected"
    assert plan["cards"][0]["restores"] is True
    merged = await _merge(app_client, headers, survivor, duplicate, plan["fingerprint"])
    assert merged.status_code == 200, merged.text

    kept = (await _card_history(job_id, survivor))[-1]
    assert kept.stage == PipelineStage.rejected
    assert kept.notes == "Pracuje u tego klienta"
    assert kept.rejection_note == "Inne"
    assert kept.ended_by == "recruiter"
    assert kept.moved_by == admin_id


async def test_merge_process_follows_the_kept_card(app_client: AsyncClient):
    """Opiekun i kredyt zostają z kartą, nie z nowszym wierszem procesu."""
    admin_id, headers = await _user(app_client, UserRole.admin)
    job_id = await _job(admin_id)
    survivor = await _candidate()
    duplicate = await _candidate()
    t0 = datetime.now(timezone.utc) - timedelta(days=10)
    await _stages(survivor, job_id, (PipelineStage.cv_sent, t0))
    await _stages(duplicate, job_id, (PipelineStage.screening, t0 + timedelta(days=1)))
    async with AsyncSessionLocal() as db:
        kept_process = RecruitmentProcess(
            candidate_id=survivor,
            job_id=job_id,
            attempt_no=1,
            status=ProcessStatus.open,
            owner_user_id=admin_id,
            credit_user_id=admin_id,
            updated_at=t0,
        )
        db.add(kept_process)
        db.add(
            RecruitmentProcess(
                candidate_id=duplicate,
                job_id=job_id,
                attempt_no=1,
                status=ProcessStatus.open,
                updated_at=t0 + timedelta(days=1),
            )
        )
        await db.commit()
        kept_process_id = kept_process.id

    plan = (await _preview(app_client, headers, survivor, duplicate)).json()
    merged = await _merge(app_client, headers, survivor, duplicate, plan["fingerprint"])
    assert merged.status_code == 200, merged.text

    history = await _card_history(job_id, survivor)
    async with AsyncSessionLocal() as db:
        processes = (
            await db.scalars(
                select(RecruitmentProcess).where(
                    RecruitmentProcess.candidate_id == survivor,
                    RecruitmentProcess.job_id == job_id,
                )
            )
        ).all()
    assert [p.id for p in processes] == [kept_process_id]
    assert processes[0].owner_user_id == admin_id
    assert processes[0].credit_user_id == admin_id
    assert processes[0].legacy_current_candidate_stage_id == history[-1].id


async def test_merge_preview_fingerprint_changes_when_a_card_moves(
    app_client: AsyncClient,
):
    admin_id, headers = await _user(app_client, UserRole.admin)
    job_id = await _job(admin_id)
    survivor = await _candidate()
    duplicate = await _candidate()
    t0 = datetime.now(timezone.utc) - timedelta(days=10)
    await _stages(survivor, job_id, (PipelineStage.new, t0))
    await _stages(duplicate, job_id, (PipelineStage.new, t0 + timedelta(days=1)))
    first = (await _preview(app_client, headers, survivor, duplicate)).json()
    assert first["cards"][0]["restores"] is False
    await _stages(survivor, job_id, (PipelineStage.cv_sent, t0 + timedelta(days=2)))
    second = (await _preview(app_client, headers, survivor, duplicate)).json()
    assert second["cards"][0]["result_stage"] == "cv_sent"
    assert second["fingerprint"] != first["fingerprint"]


async def test_merge_preview_lists_no_card_without_a_shared_job(
    app_client: AsyncClient,
):
    admin_id, headers = await _user(app_client, UserRole.admin)
    job_a = await _job(admin_id)
    job_b = await _job(admin_id)
    survivor = await _candidate()
    duplicate = await _candidate()
    now = datetime.now(timezone.utc)
    await _stages(survivor, job_a, (PipelineStage.cv_sent, now))
    await _stages(duplicate, job_b, (PipelineStage.screening, now))
    plan = (await _preview(app_client, headers, survivor, duplicate)).json()
    assert plan["cards"] == []
