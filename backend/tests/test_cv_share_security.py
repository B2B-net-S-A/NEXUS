"""Share/HTML security v2 (M4 audyt P1.9 + P1.14, plan PR-04).

Kontrakty:

- **sanitizer** — allowlist: XSS corpus (script/onerror/javascript:/svg/iframe)
  jest wycinany, poprawny markup prezentacyjny przeżywa;
- **token v2** — sekret nie istnieje w DB (tylko SHA-256), raw zwracany raz,
  revoke-by-key, lista bez sekretów, max_views egzekwowane atomowo, dual-read
  legacy raw, public response ma Cache-Control: no-store i zsanityzowany HTML,
  access audit w Activity;
- **rejection e-maile** — placeholdery body są escapowane, override template
  musi mieć kategorię rejection, treść maila widzi tylko owner/oversight.

Uses in-process fixtures (real postgres in CI) — migracja 0176 przez
`alembic upgrade heads`.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.services.html_sanitizer import sanitize_cv_html

# ── Sanitizer: XSS corpus ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "payload",
    [
        "<script>alert(1)</script>",
        '<img src=x onerror="alert(1)">',
        '<a href="javascript:alert(1)">klik</a>',
        '<svg onload="alert(1)"><circle r="1"/></svg>',
        '<iframe src="https://evil.example"></iframe>',
        '<object data="https://evil.example"></object>',
        '<form action="https://evil.example"><input name="x"></form>',
        '<div style="background:url(javascript:alert(1))">x</div>',
    ],
)
def test_sanitizer_strips_active_content(payload: str):
    out = sanitize_cv_html(f"<p>CV</p>{payload}")
    lowered = out.lower()
    assert "<script" not in lowered
    assert "onerror" not in lowered
    assert "onload" not in lowered
    assert "javascript:" not in lowered
    assert "<iframe" not in lowered
    assert "<object" not in lowered
    assert "<form" not in lowered
    assert "<p>CV</p>" in out


def test_sanitizer_preserves_presentation_markup():
    html = (
        '<h1 style="color:#123456">Jan K.</h1>'
        '<table><tr><td colspan="2">Python</td></tr></table>'
        '<a href="https://example.com" title="www">link</a>'
        '<img src="data:image/png;base64,iVBOR" alt="logo">'
    )
    out = sanitize_cv_html(html)
    assert "<h1" in out and "color:#123456" in out.replace(" ", "")
    assert '<td colspan="2">' in out
    assert 'href="https://example.com"' in out
    assert 'src="data:image/png;base64,iVBOR"' in out


def test_sanitizer_handles_empty():
    assert sanitize_cv_html(None) == ""
    assert sanitize_cv_html("") == ""


# ── Scheduler: escaping + kategoria template ─────────────────────────────────


def test_rejection_render_escapes_html_in_body_not_subject():
    from types import SimpleNamespace

    from app.services.rejection_email_scheduler import _render

    candidate = SimpleNamespace(name='<script>alert("x")</script>', lastname="Nowak")
    job = SimpleNamespace(title="Dev & Ops <b>senior</b>")
    recruiter = SimpleNamespace(name="Rekruter", email="r@example.com")

    subject, body = _render(
        template=None,
        candidate=candidate,
        job=job,
        recruiter=recruiter,
        other_processes=[],
    )
    assert "<script>" not in body
    assert "&lt;script&gt;" in body
    # Subject to plain text — bez encji HTML.
    assert "&amp;" not in subject
    assert "Dev & Ops" in subject


async def test_rejection_template_override_requires_rejection_category():
    from app.models.email_template import EmailCategory, EmailTemplate
    from app.services.rejection_email_scheduler import _resolve_template

    async with AsyncSessionLocal() as db:
        wrong = EmailTemplate(
            name=f"NotRejection-{uuid.uuid4().hex[:6]}",
            subject="s",
            body="<p>b</p>",
            category=EmailCategory.general,
        )
        db.add(wrong)
        await db.commit()
        await db.refresh(wrong)

        resolved = await _resolve_template(db, wrong.id)
        assert resolved is None or resolved.category == EmailCategory.rejection, (
            "override o złej kategorii nie może zostać użyty"
        )


# ── Fixtures ─────────────────────────────────────────────────────────────────


async def _seed_finalized_cv(html: str) -> tuple[int, int]:
    """Returns (stage_id, csv_id) z finalized branded CV."""
    from app.models.candidate import Candidate
    from app.models.candidate_stage_cv import CandidateStageCV
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Share",
            lastname=f"Sec-{uuid.uuid4().hex[:6]}",
            email=f"share-{uuid.uuid4().hex[:8]}@example.com",
        )
        cli = Client(name=f"ShareClient-{uuid.uuid4().hex[:6]}")
        db.add_all([cand, cli])
        await db.flush()
        job = Job(
            title=f"Share-Job-{uuid.uuid4().hex[:6]}",
            status=JobStatus.published,
            client_id=cli.id,
        )
        db.add(job)
        await db.flush()
        stage = CandidateStage(
            candidate_id=cand.id,
            job_id=job.id,
            stage=PipelineStage.cv_sent,
            moved_at=datetime.now(timezone.utc),
        )
        db.add(stage)
        await db.flush()
        csv = CandidateStageCV(
            candidate_stage_id=stage.id,
            candidate_id=cand.id,
            job_id=job.id,
            branded_status="finalized",
            branded_draft_html=html,
        )
        db.add(csv)
        await db.commit()
        return stage.id, csv.id


# ── Token v2 lifecycle ───────────────────────────────────────────────────────


async def test_token_v2_full_lifecycle(app_client: AsyncClient, app_auth_headers):
    from sqlalchemy import select

    from app.models.cv_share_token import CVShareToken

    stage_id, csv_id = await _seed_finalized_cv(
        "<p>Doświadczenie</p><script>alert('xss')</script>"
    )

    # 1) create — raw zwrócony raz, w DB tylko hash + nie-sekretny revoke_key
    r = await app_client.post(
        f"/api/candidates/stages/{stage_id}/cv/share-token?expires_in_days=7&max_views=2",
        headers=app_auth_headers,
    )
    assert r.status_code == 201, r.text
    created = r.json()
    raw = created["token"]
    revoke_key = created["revoke_key"]
    assert revoke_key.startswith("v2$")
    assert raw != revoke_key

    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(CVShareToken).where(CVShareToken.token == revoke_key)
        )
        assert row is not None
        assert row.token_sha256 == hashlib.sha256(raw.encode()).hexdigest()
        assert raw not in (row.token or ""), "raw sekret nie może być w DB"
        assert row.max_views == 2

    # 2) public GET po raw — działa, HTML zsanityzowany, no-store
    pub = await app_client.get(f"/api/public/cv/{raw}")
    assert pub.status_code == 200, pub.text
    assert "<script" not in pub.json()["cv_html"].lower()
    assert "Doświadczenie" in pub.json()["cv_html"]
    assert pub.headers.get("cache-control") == "no-store"

    # 3) lista — metadane bez sekretu (share_url_suffix None dla v2)
    lst = await app_client.get(
        f"/api/candidates/stages/{stage_id}/cv/share-tokens",
        headers=app_auth_headers,
    )
    assert lst.status_code == 200, lst.text
    items = lst.json()
    assert len(items) == 1
    assert items[0]["revoke_key"] == revoke_key
    assert items[0]["is_v2"] is True
    assert items[0]["share_url_suffix"] is None
    assert items[0]["view_count"] == 1
    assert raw not in lst.text, "lista nie może ujawniać raw tokenu"

    # 4) max_views=2: drugie wejście OK, trzecie 410
    assert (await app_client.get(f"/api/public/cv/{raw}")).status_code == 200
    third = await app_client.get(f"/api/public/cv/{raw}")
    assert third.status_code == 410, third.text

    # 5) revoke by key → public 404
    rv = await app_client.delete(
        f"/api/candidates/stages/cv/share-token/{revoke_key}?reason=test",
        headers=app_auth_headers,
    )
    assert rv.status_code == 200 and rv.json()["status"] == "revoked"
    assert (await app_client.get(f"/api/public/cv/{raw}")).status_code == 404

    # 6) audit: Activity cv_share_viewed istnieje dla tego CV
    from app.models.activity import Activity

    async with AsyncSessionLocal() as db:
        viewed = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "candidate_stage_cv",
                Activity.entity_id == csv_id,
                Activity.action == "cv_share_viewed",
            )
        )
        assert viewed is not None


async def test_v2_revoke_key_is_not_an_access_token(
    app_client: AsyncClient, app_auth_headers
):
    """Nie-sekretny ``revoke_key`` v2 NIE może otwierać CV (re-audyt M2, PR1b).

    Kontrakt P1.9 brzmi „sekret nigdy nie jest przechowywany": w DB leży tylko
    SHA-256, a PK dostaje jawny identyfikator ``v2$<hex>`` służący do
    ODWOŁANIA linku. Dual-read w ``get_public_cv`` dopasowywał jednak
    ``token == <podany>`` bez zawężenia do wierszy legacy, więc revoke_key
    działał jak pełnoprawny token dostępu. A revoke_key jest jawny: wraca
    z API tworzenia, jest na liście linków i ląduje w Activity audit log —
    czyli każdy użytkownik operacyjny (i każdy z dostępem do logów) trzymał
    de facto działające poświadczenie do „klienckiego" linku bez logowania.
    """
    stage_id, _ = await _seed_finalized_cv("<p>Tajne CV</p>")

    r = await app_client.post(
        f"/api/candidates/stages/{stage_id}/cv/share-token?expires_in_days=7",
        headers=app_auth_headers,
    )
    assert r.status_code == 201, r.text
    raw = r.json()["token"]
    revoke_key = r.json()["revoke_key"]
    assert revoke_key.startswith("v2$")

    # Sekret nadal otwiera link — brak regresji dla właściwej ścieżki.
    ok = await app_client.get(f"/api/public/cv/{raw}")
    assert ok.status_code == 200, ok.text

    # Revoke key NIE jest poświadczeniem dostępu.
    denied = await app_client.get(f"/api/public/cv/{revoke_key}")
    assert denied.status_code == 404, (
        "revoke_key otworzył CV — nie-sekretny klucz odwołania działa jako "
        f"token dostępu (status={denied.status_code})"
    )
    assert "Tajne CV" not in denied.text


async def test_token_legacy_dual_read(app_client: AsyncClient, app_auth_headers):
    """Legacy wiersz (raw w PK, bez hasha) nadal działa w public GET."""
    from app.models.cv_share_token import CVShareToken

    stage_id, _ = await _seed_finalized_cv("<p>Legacy</p>")
    legacy_raw = f"legacy-{uuid.uuid4().hex}"
    async with AsyncSessionLocal() as db:
        # znajdź csv_id przez API create? nie — bez tokenu; wstaw ręcznie
        from sqlalchemy import select

        from app.models.candidate_stage_cv import CandidateStageCV

        csv = await db.scalar(
            select(CandidateStageCV).where(
                CandidateStageCV.candidate_stage_id == stage_id
            )
        )
        db.add(
            CVShareToken(
                token=legacy_raw,
                candidate_stage_cv_id=csv.id,
                expires_at=datetime.now(timezone.utc) + timedelta(days=5),
            )
        )
        await db.commit()

    pub = await app_client.get(f"/api/public/cv/{legacy_raw}")
    assert pub.status_code == 200, pub.text

    # Lista pokazuje legacy z odtwarzalnym URL (raw i tak jest w DB)
    lst = await app_client.get(
        f"/api/candidates/stages/{stage_id}/cv/share-tokens",
        headers=app_auth_headers,
    )
    legacy_items = [i for i in lst.json() if not i["is_v2"]]
    assert legacy_items and legacy_items[0]["share_url_suffix"].endswith(legacy_raw)

    # revoke-all czyści wszystko aktywne
    ra = await app_client.delete(
        f"/api/candidates/stages/{stage_id}/cv/share-tokens",
        headers=app_auth_headers,
    )
    assert ra.status_code == 200 and ra.json()["count"] >= 1
    assert (await app_client.get(f"/api/public/cv/{legacy_raw}")).status_code == 404


# ── Rejection e-maile: scope treści ──────────────────────────────────────────


async def test_rejection_email_body_scope(app_client: AsyncClient):
    from app.core.security import hash_password
    from app.models.rejection_email import (
        RejectionEmailStatus,
        ScheduledRejectionEmail,
    )
    from app.models.user import User, UserRole

    stage_id, _ = await _seed_finalized_cv("<p>x</p>")
    # owner + obcy recruiter
    users = {}
    async with AsyncSessionLocal() as db:
        for tag in ("owner", "other"):
            unique = uuid.uuid4().hex[:8]
            u = User(
                email=f"rej-{tag}-{unique}@example.com",
                password_hash=hash_password(f"T3st_{unique}!R"),
                name=f"Rej {tag}",
                role=UserRole.recruiter,
                is_active=True,
            )
            db.add(u)
            await db.flush()
            users[tag] = (u.id, u.email, f"T3st_{unique}!R")
        await db.commit()

    from sqlalchemy import select

    from app.models.recruitment_pipeline import CandidateStage

    async with AsyncSessionLocal() as db:
        stage = await db.scalar(
            select(CandidateStage).where(CandidateStage.id == stage_id)
        )
        mail = ScheduledRejectionEmail(
            candidate_stage_id=stage_id,
            candidate_id=stage.candidate_id,
            job_id=stage.job_id,
            recruiter_id=users["owner"][0],
            to_email="scope@example.com",
            subject="sekret-temat",
            body_html="<p>sekret-body</p>",
            status=RejectionEmailStatus.pending,
            scheduled_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        db.add(mail)
        await db.commit()
        await db.refresh(mail)
        mail_id = mail.id
        candidate_id = stage.candidate_id

    async def login(tag: str) -> dict:
        _, email, password = users[tag]
        resp = await app_client.post(
            "/api/auth/login", json={"email": email, "password": password}
        )
        assert resp.status_code == 200, resp.text
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    owner_h, other_h = await login("owner"), await login("other")

    # GET {id}: owner 200, obcy recruiter 403
    assert (
        await app_client.get(f"/api/rejection-emails/{mail_id}", headers=owner_h)
    ).status_code == 200
    assert (
        await app_client.get(f"/api/rejection-emails/{mail_id}", headers=other_h)
    ).status_code == 403

    # by-candidate: obcy widzi wiersz, ale body zredagowane
    timeline = await app_client.get(
        f"/api/rejection-emails/by-candidate/{candidate_id}", headers=other_h
    )
    assert timeline.status_code == 200
    rows = [x for x in timeline.json() if x["id"] == mail_id]
    assert rows and rows[0]["body_html"] == "" and rows[0]["last_error"] is None

    owner_timeline = await app_client.get(
        f"/api/rejection-emails/by-candidate/{candidate_id}", headers=owner_h
    )
    owner_rows = [x for x in owner_timeline.json() if x["id"] == mail_id]
    assert owner_rows and "sekret-body" in owner_rows[0]["body_html"]
