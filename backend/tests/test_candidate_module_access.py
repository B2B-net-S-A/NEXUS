"""Security matrix for the candidate/talent module (M2 audit PR 1).

Verifies the P0 containment contracts:

- **M2-SEC-01** — the read-only viewer role ``user`` gets 403 on every
  candidate read surface (list, detail, timeline, history, documents, CV,
  search, notes, sources, pools, marketplace, recommendations) while all
  internal operational roles keep access.
- **M2-SEC-02** — bulk ``anonymize_pii`` is blocked (409) for everyone and
  never mutates the database; switching the ``action`` in the body cannot
  escalate past the role guard.
- **M2-SEC-03** — hard NDA/blacklist/competitor conflicts are enforced even
  when the caller passes ``industry_blocklist=false`` (fail-closed).
- **M2-SEC-04** — viewer cannot mutate notes, source events, talent pools,
  tags or rates; client-rate mutations require the finance capability.
- **M2-PRIV-02** — operational hard delete answers 409 (covered in
  ``test_candidate_delete.py``).
- Export is restricted to TAC-and-up and leaves an immutable audit event
  without PII.
- Capability checks evaluate the UNION of primary and secondary roles.

Pattern follows ``test_rbac.py``: status-code asymmetry — for denied roles we
assert exactly 403; for allowed roles we assert *not* 403 (404/422/500 from
missing fixtures are acceptable — the guard is what's under test).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.user import User, UserRole

ROLES = [
    UserRole.admin,
    UserRole.head_of_recruitment,
    UserRole.delivery_lead,
    UserRole.finance,
    UserRole.tac,
    UserRole.recruiter,
    UserRole.sourcer,
    UserRole.user,
]

OPERATIONAL_ROLES = {
    UserRole.admin,
    UserRole.head_of_recruitment,
    UserRole.delivery_lead,
    UserRole.tac,
    UserRole.recruiter,
    UserRole.sourcer,
}
WRITE_ROLES = {
    UserRole.admin,
    UserRole.delivery_lead,
    UserRole.tac,
    UserRole.recruiter,
    UserRole.sourcer,
}
EXPORT_ROLES = {
    UserRole.admin,
    UserRole.head_of_recruitment,
    UserRole.delivery_lead,
    UserRole.tac,
}
FINANCE_ROLES = {UserRole.admin}


# ── Fixtures ─────────────────────────────────────────────────────────────────


async def _seed_user(
    role: UserRole, secondary: list[str] | None = None
) -> tuple[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"m2acc-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!M2"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name=f"M2 Access {role.value}",
                role=role,
                roles=secondary or [role.value],
                is_active=True,
            )
        )
        await db.commit()
    return email, password


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, f"login failed: {resp.text}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture(scope="module")
async def m2_client() -> AsyncClient:
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest_asyncio.fixture(scope="module")
async def headers_by_role(m2_client: AsyncClient) -> dict[UserRole, dict[str, str]]:
    """One seeded user + login per role, reused across the whole module."""
    out: dict[UserRole, dict[str, str]] = {}
    for role in ROLES:
        email, password = await _seed_user(role)
        out[role] = await _login(m2_client, email, password)
    return out


async def _seed_candidate(**overrides) -> int:
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name=overrides.pop("name", "M2"),
            lastname=overrides.pop("lastname", f"Access-{uuid.uuid4().hex[:6]}"),
            email=overrides.pop("email", f"m2acc-{uuid.uuid4().hex[:8]}@example.com"),
            **overrides,
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


# ── M2-SEC-01: read surfaces — viewer 403, operational roles pass ────────────

READ_ENDPOINTS = [
    ("GET", "/api/candidates", None),
    ("GET", "/api/candidates/999999", None),
    ("GET", "/api/candidates/999999/quick-view", None),
    ("GET", "/api/candidates/999999/timeline", None),
    ("GET", "/api/candidates/999999/history", None),
    ("GET", "/api/candidates/999999/languages", None),
    ("GET", "/api/candidates/999999/profile-rate", None),
    ("GET", "/api/candidates/999999/recent-recruitments?limit=5", None),
    ("GET", "/api/candidates/999999/activity-summary", None),
    ("POST", "/api/candidates/999999/activity-summary/refresh", None),
    (
        "GET",
        "/api/candidates/999999/identity-quarantine/note/999999",
        None,
    ),
    ("GET", "/api/candidates/999999/documents", None),
    ("GET", "/api/candidates/999999/cv-download", None),
    ("GET", "/api/candidates/999999/documents/1/content", None),
    ("GET", "/api/candidates/999999/documents/1/url", None),
    ("GET", "/api/candidates/check-exists?email=nobody%40example.com", None),
    ("GET", "/api/candidates/companies/suggest", None),
    ("GET", "/api/candidates/titles/suggest", None),
    ("GET", "/api/notes", None),
    ("GET", "/api/candidates/999999/sources", None),
    ("GET", "/api/talent-pools", None),
    ("GET", "/api/marketplace/pool", None),
    ("GET", "/api/marketplace/candidates", None),
    ("POST", "/api/search/candidates", {}),
    ("POST", "/api/candidates/check-duplicates", {}),
    ("POST", "/api/candidates/bulk-cv-download", {"candidate_ids": [999999]}),
    # ── PR1b: sibling routers that serve the SAME candidate data ────────────
    # Found by the independent module-2 re-audit: PR1 closed the canonical
    # /api/candidates/* surfaces but these two routers kept bare CurrentUser,
    # so a viewer could still (a) stream any candidate's original/branded CV
    # by walking sequential stage_id values and (b) harvest name/lastname/
    # email through the pin router's CandidatePinBrief. Regression-locked here
    # so a future router cannot silently reopen the same hole.
    ("GET", "/api/candidates/stages/999999/cv/original", None),
    ("GET", "/api/candidates/stages/999999/cv/original/download", None),
    ("GET", "/api/candidates/stages/999999/cv/branded", None),
    ("GET", "/api/candidates/stages/999999/cv/branded/render-pdf", None),
    ("GET", "/api/candidates/pins", None),
    ("GET", "/api/candidates/999999/pin", None),
    ("POST", "/api/candidates/999999/pin", None),
    # ── PR1c: panel generatora B2B (w sidebarze dostępny dla WSZYSTKICH ról) ──
    # typeahead przeszukiwał całą bazę po imieniu/nazwisku/emailu (puste q =
    # ostatnio modyfikowani), lista pokazywała candidate_name cudzych CV,
    # a /generated/{id}/docx nie miał ŻADNEJ kontroli własności → viewer
    # pobierał dowolne wygenerowane CV kandydata po sekwencyjnym ID.
    ("GET", "/api/cv-generator/candidates", None),
    ("GET", "/api/cv-generator/generated", None),
    ("GET", "/api/cv-generator/generated/999999/docx", None),
]

# Druga, równoległa powierzchnia eksportu/importu kandydatów (import_export.py).
# PR1 zamknął /api/candidates/export (TAC+ i audyt), a ta trasa została na gołym
# CurrentUser i strumieniowała CAŁĄ bazę (bez limitu) do dowolnej zalogowanej
# roli. Trzymana w osobnej macierzy, bo dzieli kontrakt z eksportem, nie z read.
PARALLEL_EXPORT_ENDPOINTS = [
    ("GET", "/api/export/candidates", None),
]


@pytest.mark.parametrize("method,path,body", READ_ENDPOINTS)
async def test_read_surface_role_matrix(
    m2_client: AsyncClient,
    headers_by_role: dict[UserRole, dict[str, str]],
    method: str,
    path: str,
    body,
):
    for role in ROLES:
        resp = await m2_client.request(
            method, path, headers=headers_by_role[role], json=body
        )
        if role in OPERATIONAL_ROLES:
            assert resp.status_code != 403, (
                f"[{role.value}] {method} {path} unexpectedly forbidden"
            )
        else:
            assert resp.status_code == 403, (
                f"[{role.value}] {method} {path} expected 403, got {resp.status_code}"
            )


async def test_viewer_gets_403_not_404_for_existing_and_missing_ids(
    m2_client: AsyncClient, headers_by_role: dict[UserRole, dict[str, str]]
):
    """Anti-enumeration: the viewer cannot distinguish an existing candidate
    from a missing one — both return 403."""
    candidate_id = await _seed_candidate()
    viewer = headers_by_role[UserRole.user]

    r_existing = await m2_client.get(f"/api/candidates/{candidate_id}", headers=viewer)
    r_missing = await m2_client.get("/api/candidates/999999", headers=viewer)
    assert r_existing.status_code == 403
    assert r_missing.status_code == 403


PROFILE_FACT_WRITE_ENDPOINTS = [
    (
        "PUT",
        "/api/candidates/999999/languages",
        {"languages": []},
        '"candidate-languages-999999-v1"',
    ),
    (
        "PATCH",
        "/api/candidates/999999/profile-rate",
        {"amount": "150.00"},
        '"candidate-profile-rate-999999-v1"',
    ),
    (
        "PATCH",
        "/api/candidates/999999/location",
        {"city": "Warszawa", "country": "PL"},
        None,
    ),
]


@pytest.mark.parametrize("method,path,body,if_match", PROFILE_FACT_WRITE_ENDPOINTS)
async def test_profile_fact_writer_role_matrix(
    m2_client: AsyncClient,
    headers_by_role: dict[UserRole, dict[str, str]],
    method: str,
    path: str,
    body,
    if_match: str | None,
):
    for role in ROLES:
        headers = dict(headers_by_role[role])
        if if_match:
            headers["If-Match"] = if_match
        response = await m2_client.request(
            method,
            path,
            headers=headers,
            json=body,
        )
        if role in OPERATIONAL_ROLES:
            assert response.status_code != 403, (
                f"[{role.value}] {method} {path} unexpectedly forbidden"
            )
        else:
            assert response.status_code == 403, (
                f"[{role.value}] {method} {path} expected 403, "
                f"got {response.status_code}"
            )


async def test_profile_fact_etags_reject_stale_writers_and_rate_clears_to_null(
    m2_client: AsyncClient,
    headers_by_role: dict[UserRole, dict[str, str]],
):
    """Two callers reading the same version cannot silently overwrite facts."""

    candidate_id = await _seed_candidate()
    headers = headers_by_role[UserRole.admin]

    languages_read = await m2_client.get(
        f"/api/candidates/{candidate_id}/languages",
        headers=headers,
    )
    assert languages_read.status_code == 200, languages_read.text
    languages_etag = languages_read.headers["etag"]
    first_languages = await m2_client.put(
        f"/api/candidates/{candidate_id}/languages",
        headers={**headers, "If-Match": languages_etag},
        json={
            "languages": [
                {
                    "language_code": "en",
                    "language_name": "English",
                    "cefr_level": "C1",
                    "is_level_unknown": False,
                }
            ]
        },
    )
    assert first_languages.status_code == 200, first_languages.text
    assert first_languages.headers["etag"] != languages_etag
    stale_languages = await m2_client.put(
        f"/api/candidates/{candidate_id}/languages",
        headers={**headers, "If-Match": languages_etag},
        json={"languages": []},
    )
    assert stale_languages.status_code in {409, 412}

    rate_read = await m2_client.get(
        f"/api/candidates/{candidate_id}/profile-rate",
        headers=headers,
    )
    assert rate_read.status_code == 200, rate_read.text
    rate_etag = rate_read.headers["etag"]
    first_rate = await m2_client.patch(
        f"/api/candidates/{candidate_id}/profile-rate",
        headers={**headers, "If-Match": rate_etag},
        json={"amount": "199.99"},
    )
    assert first_rate.status_code == 200, first_rate.text
    assert first_rate.json()["amount"] == "199.99"
    current_rate_etag = first_rate.headers["etag"]

    stale_rate = await m2_client.patch(
        f"/api/candidates/{candidate_id}/profile-rate",
        headers={**headers, "If-Match": rate_etag},
        json={"amount": None},
    )
    assert stale_rate.status_code in {409, 412}
    cleared_rate = await m2_client.patch(
        f"/api/candidates/{candidate_id}/profile-rate",
        headers={**headers, "If-Match": current_rate_etag},
        json={"amount": None},
    )
    assert cleared_rate.status_code == 200, cleared_rate.text
    assert cleared_rate.json()["amount"] is None
    assert cleared_rate.json()["currency"] == "PLN"
    assert cleared_rate.json()["unit"] == "hour"
    assert cleared_rate.json()["tax_basis"] == "net"
    assert cleared_rate.json()["contract_type"] == "b2b"


# ── M2-SEC-04: write surfaces — viewer (and below-write roles) 403 ───────────

WRITE_ENDPOINTS = [
    ("POST", "/api/notes", {"content": "x", "candidate_id": 999999}),
    ("POST", "/api/candidates/999999/sources", {"channel": "other"}),
    ("POST", "/api/talent-pools", {"name": "m2-denied"}),
    ("POST", "/api/candidates/999999/assign-to-job/999999", None),
    (
        "PUT",
        "/api/candidates/999999/identity-quarantine/note/999999",
        {"provenance": "manual_review"},
    ),
    # expected-rate przeniesiony z write- do rate-edit-matrix (M4 PR-01):
    # sourcer stracił edycję stawek — patrz test niżej i
    # tests/test_recruitment_module_access.py.
    (
        "POST",
        "/api/candidates/bulk",
        {"action": "add_tags", "candidate_ids": [999999], "params": {"tags": ["x"]}},
    ),
    # Upload pliku do teczki kandydata. Body celowo puste — guard roli musi
    # zadziałać PRZED walidacją multiparta, więc dozwolone role dostają 422
    # (brak `file`), a viewer 403.
    ("POST", "/api/candidates/999999/documents", None),
]

# M4 PR-01: stawka kandydata = osobne capability (admin/DL/tac/recruiter,
# bez sourcera) — audyt M4 P0.3.
RATE_EDIT_ROLES = {
    UserRole.admin,
    UserRole.delivery_lead,
    UserRole.tac,
    UserRole.recruiter,
}


async def test_expected_rate_requires_rate_edit_capability(
    m2_client: AsyncClient, headers_by_role: dict[UserRole, dict[str, str]]
):
    """Expected rate — rola sourcer i viewer 403 (M4 PR-01 zawężenie)."""
    for role in ROLES:
        resp = await m2_client.patch(
            "/api/candidates/999999/recruitments/999999/expected-rate",
            headers=headers_by_role[role],
            json={"rate_value": 100},
        )
        if role in RATE_EDIT_ROLES:
            assert resp.status_code != 403, (
                f"[{role.value}] expected-rate unexpectedly forbidden"
            )
        else:
            assert resp.status_code == 403, (
                f"[{role.value}] expected-rate expected 403, got {resp.status_code}"
            )


@pytest.mark.parametrize("method,path,body", WRITE_ENDPOINTS)
async def test_write_surface_role_matrix(
    m2_client: AsyncClient,
    headers_by_role: dict[UserRole, dict[str, str]],
    method: str,
    path: str,
    body,
):
    for role in ROLES:
        resp = await m2_client.request(
            method, path, headers=headers_by_role[role], json=body
        )
        if role in WRITE_ROLES:
            assert resp.status_code != 403, (
                f"[{role.value}] {method} {path} unexpectedly forbidden"
            )
        else:
            assert resp.status_code == 403, (
                f"[{role.value}] {method} {path} expected 403, got {resp.status_code}"
            )


async def test_client_rate_requires_finance_capability(
    m2_client: AsyncClient, headers_by_role: dict[UserRole, dict[str, str]]
):
    """Candidate-specific client rate is Admin-only; Finance gets no PII."""
    for role in ROLES:
        resp = await m2_client.patch(
            "/api/candidates/999999/recruitments/999999/client-rate",
            headers=headers_by_role[role],
            json={"rate_value": 100},
        )
        if role in FINANCE_ROLES:
            assert resp.status_code != 403, f"[{role.value}] unexpectedly forbidden"
        else:
            assert resp.status_code == 403, (
                f"[{role.value}] expected 403, got {resp.status_code}"
            )


async def test_identity_quarantine_override_is_admin_or_hor_only(
    m2_client: AsyncClient,
    headers_by_role: dict[UserRole, dict[str, str]],
):
    path = "/api/candidates/999999/identity-quarantine/note/999999/override"
    for role in ROLES:
        response = await m2_client.post(
            path,
            headers=headers_by_role[role],
            json={"reason": "Zweryfikowano właściciela źródła"},
        )
        if role in {UserRole.admin, UserRole.head_of_recruitment}:
            assert response.status_code != 403, (
                f"[{role.value}] override unexpectedly forbidden"
            )
        else:
            assert response.status_code == 403, (
                f"[{role.value}] override expected 403, got {response.status_code}"
            )


async def test_denied_activity_and_override_calls_never_reach_services(
    m2_client: AsyncClient,
    headers_by_role: dict[UserRole, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
):
    summary_service = AsyncMock()
    refresh_service = AsyncMock()
    override_service = AsyncMock()
    monkeypatch.setattr(
        "app.api.candidate_activity_summary.get_summary_state",
        summary_service,
    )
    monkeypatch.setattr(
        "app.api.candidate_activity_summary.get_or_generate",
        refresh_service,
    )
    monkeypatch.setattr(
        "app.api.candidate_identity_quarantine.override_identity_quarantine",
        override_service,
    )

    summary_response = await m2_client.get(
        "/api/candidates/999999/activity-summary",
        headers=headers_by_role[UserRole.user],
    )
    refresh_response = await m2_client.post(
        "/api/candidates/999999/activity-summary/refresh",
        headers=headers_by_role[UserRole.user],
    )
    override_response = await m2_client.post(
        "/api/candidates/999999/identity-quarantine/note/999999/override",
        headers=headers_by_role[UserRole.recruiter],
        json={"reason": "Zweryfikowano właściciela źródła"},
    )

    assert summary_response.status_code == 403
    assert refresh_response.status_code == 403
    assert override_response.status_code == 403
    summary_service.assert_not_awaited()
    refresh_service.assert_not_awaited()
    override_service.assert_not_awaited()


# ── Export: TAC-and-up + immutable audit ─────────────────────────────────────


@pytest.mark.parametrize("method,path,body", PARALLEL_EXPORT_ENDPOINTS)
async def test_parallel_export_surface_matches_export_capability(
    m2_client: AsyncClient,
    headers_by_role: dict[UserRole, dict[str, str]],
    method: str,
    path: str,
    body,
):
    """`/api/export/candidates` musi mieć DOKŁADNIE ten sam kontrakt co
    `/api/candidates/export` — inaczej PR1 zamknął jedne drzwi, a druga
    trasa dalej wydawała całą bazę (imię/nazwisko/email/telefon/stawka)
    każdej zalogowanej roli, łącznie z read-only viewerem."""
    for role in ROLES:
        resp = await m2_client.request(
            method, path, headers=headers_by_role[role], json=body
        )
        if role in EXPORT_ROLES:
            assert resp.status_code != 403, (
                f"[{role.value}] {method} {path} unexpectedly forbidden"
            )
        else:
            assert resp.status_code == 403, (
                f"[{role.value}] {method} {path} expected 403, "
                f"got {resp.status_code} — równoległy eksport omija gate PR1"
            )


async def test_export_role_matrix(
    m2_client: AsyncClient, headers_by_role: dict[UserRole, dict[str, str]]
):
    for role in ROLES:
        resp = await m2_client.get(
            "/api/candidates/export?limit=1", headers=headers_by_role[role]
        )
        if role in EXPORT_ROLES:
            assert resp.status_code == 200, (
                f"[{role.value}] export expected 200, got {resp.status_code}"
            )
        else:
            assert resp.status_code == 403, (
                f"[{role.value}] export expected 403, got {resp.status_code}"
            )

    # POST variant: viewer + recruiter denied regardless of body shape.
    for role in (UserRole.user, UserRole.recruiter, UserRole.sourcer):
        resp = await m2_client.post(
            "/api/candidates/export",
            headers=headers_by_role[role],
            json={"format": "csv", "scope": "selected", "candidate_ids": [1]},
        )
        assert resp.status_code == 403, f"[{role.value}] POST export not denied"


async def test_export_emits_audit_event_without_pii(
    m2_client: AsyncClient, headers_by_role: dict[UserRole, dict[str, str]]
):
    from app.models.activity import Activity

    resp = await m2_client.get(
        "/api/candidates/export?limit=1&q=SecretName",
        headers=headers_by_role[UserRole.admin],
    )
    assert resp.status_code == 200

    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(Activity)
            .where(
                Activity.entity_type == "candidate",
                Activity.action == "export_requested",
            )
            .order_by(Activity.id.desc())
            .limit(1)
        )
    assert row is not None, "export must leave an audit event"
    details_str = str(row.details)
    # The audit payload records THAT a query filter was used — never its value.
    assert "SecretName" not in details_str
    assert row.details.get("filtered_by_query") is True
    assert row.details.get("format") == "csv"


# ── M2-SEC-02: bulk anonymize blocked for everyone ───────────────────────────


async def test_bulk_anonymize_is_blocked_and_mutates_nothing(
    m2_client: AsyncClient, headers_by_role: dict[UserRole, dict[str, str]]
):
    from app.models.candidate import Candidate

    candidate_id = await _seed_candidate(name="Keep", lastname="Intact")

    # Viewer: role guard fires first — 403.
    r_viewer = await m2_client.post(
        "/api/candidates/bulk",
        headers=headers_by_role[UserRole.user],
        json={"action": "anonymize_pii", "candidate_ids": [candidate_id]},
    )
    assert r_viewer.status_code == 403

    # Admin (and every write-capable role): action itself is disabled — 409.
    for role in (UserRole.admin, UserRole.recruiter):
        resp = await m2_client.post(
            "/api/candidates/bulk",
            headers=headers_by_role[role],
            json={"action": "anonymize_pii", "candidate_ids": [candidate_id]},
        )
        assert resp.status_code == 409, (
            f"[{role.value}] expected 409, got {resp.status_code}: {resp.text}"
        )
        assert "workflow" in resp.json()["detail"].lower()

    # The candidate row is byte-identical — nothing was blanked.
    async with AsyncSessionLocal() as db:
        c = await db.get(Candidate, candidate_id)
        assert c is not None
        assert c.name == "Keep"
        assert c.lastname == "Intact"
        assert c.email is not None


async def test_bulk_body_escalation_does_not_bypass_guard(
    m2_client: AsyncClient, headers_by_role: dict[UserRole, dict[str, str]]
):
    """Changing `action` inside the body must not change the required
    permission: viewer stays 403 for EVERY action value."""
    for action in ("add_tags", "assign_talent_pool", "assign_to_job", "anonymize_pii"):
        resp = await m2_client.post(
            "/api/candidates/bulk",
            headers=headers_by_role[UserRole.user],
            json={"action": action, "candidate_ids": [1]},
        )
        assert resp.status_code == 403, f"action={action}: viewer not denied"


# ── M2-SEC-03: hard conflicts are fail-closed ────────────────────────────────


async def test_hard_conflicts_enforced_with_blocklist_flag_off():
    """`industry_blocklist=False` must NOT re-include hard-blocked jobs.

    Unit-level check on `apply_user_filters`: a candidate with an active NDA
    conflict against a client keeps that client's job excluded regardless of
    the flag; the flag only suppresses the soft current-employment warning.
    """
    from app.models.candidate import Candidate
    from app.models.candidate_conflict import CandidateConflict, ConflictType
    from app.models.client import Client
    from app.models.job import Job
    from app.services.recommendation_filters import (
        RecommendationFilters,
        apply_user_filters,
    )

    async with AsyncSessionLocal() as db:
        client_blocked = Client(name=f"M2-NDA-{uuid.uuid4().hex[:6]}")
        client_soft = Client(name=f"M2-Emp-{uuid.uuid4().hex[:6]}")
        client_free = Client(name=f"M2-Free-{uuid.uuid4().hex[:6]}")
        db.add_all([client_blocked, client_soft, client_free])
        await db.commit()
        for obj in (client_blocked, client_soft, client_free):
            await db.refresh(obj)

        candidate = Candidate(
            name="Conflict",
            lastname=f"Case-{uuid.uuid4().hex[:6]}",
            email=f"m2conf-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(candidate)
        await db.commit()
        await db.refresh(candidate)

        db.add_all(
            [
                CandidateConflict(
                    candidate_id=candidate.id,
                    client_id=client_blocked.id,
                    type=ConflictType.nda,
                    active=True,
                ),
                CandidateConflict(
                    candidate_id=candidate.id,
                    client_id=client_soft.id,
                    type=ConflictType.current_employment,
                    active=True,
                ),
            ]
        )
        job_blocked = Job(title="NDA-blocked job", client_id=client_blocked.id)
        job_soft = Job(title="Soft-warned job", client_id=client_soft.id)
        job_free = Job(title="Free job", client_id=client_free.id)
        db.add_all([job_blocked, job_soft, job_free])
        await db.commit()
        for obj in (job_blocked, job_soft, job_free):
            await db.refresh(obj)

        jobs = [job_blocked, job_soft, job_free]

        # Flag ON (default) — NDA job dropped, soft job annotated.
        kept_on, stats_on = await apply_user_filters(
            candidate, jobs, RecommendationFilters(industry_blocklist=True), db
        )
        kept_on_ids = {fj.job.id for fj in kept_on}
        assert job_blocked.id not in kept_on_ids
        assert job_soft.id in kept_on_ids
        assert any(fj.warning for fj in kept_on if fj.job.id == job_soft.id)
        assert stats_on.dropped_blocklist == 1

        # Flag OFF — the hard drop is IDENTICAL; only the warning disappears.
        kept_off, stats_off = await apply_user_filters(
            candidate, jobs, RecommendationFilters(industry_blocklist=False), db
        )
        kept_off_ids = {fj.job.id for fj in kept_off}
        assert job_blocked.id not in kept_off_ids, (
            "industry_blocklist=False re-included a hard-blocked job "
            "(M2-SEC-03 regression)"
        )
        assert kept_off_ids == kept_on_ids
        assert stats_off.dropped_blocklist == 1
        assert all(fj.warning is None for fj in kept_off)


async def test_seeking_contractors_rejects_viewer(
    m2_client: AsyncClient, headers_by_role: dict[UserRole, dict[str, str]]
):
    resp = await m2_client.get(
        "/api/recommendations/seeking-contractors",
        headers=headers_by_role[UserRole.user],
    )
    assert resp.status_code == 403


# ── Secondary roles: union semantics ─────────────────────────────────────────


async def test_secondary_role_grants_candidate_access(m2_client: AsyncClient):
    """A user whose PRIMARY role is `user` but who holds a secondary
    `recruiter` role passes the capability check (union semantics)."""
    email, password = await _seed_user(UserRole.user, secondary=["user", "recruiter"])
    headers = await _login(m2_client, email, password)

    resp = await m2_client.get("/api/candidates?page_size=1", headers=headers)
    assert resp.status_code != 403, resp.text


# ── Global search projection ────────────────────────────────────────────────


async def test_global_search_hides_candidates_from_viewer(
    m2_client: AsyncClient, headers_by_role: dict[UserRole, dict[str, str]]
):
    marker = f"M2Glob{uuid.uuid4().hex[:6]}"
    await _seed_candidate(lastname=marker)

    r_viewer = await m2_client.get(
        f"/api/search/global?q={marker}", headers=headers_by_role[UserRole.user]
    )
    assert r_viewer.status_code == 200
    viewer_body = r_viewer.json()
    assert viewer_body["candidates"] == [], "viewer must not see candidate hits"

    r_admin = await m2_client.get(
        f"/api/search/global?q={marker}", headers=headers_by_role[UserRole.admin]
    )
    assert r_admin.status_code == 200
    admin_names = [c["name"] for c in r_admin.json()["candidates"]]
    assert any(marker in n for n in admin_names), "admin should still find them"


async def test_unified_search_hides_candidates_from_viewer(
    m2_client: AsyncClient, headers_by_role: dict[UserRole, dict[str, str]]
):
    marker = f"M2Uni{uuid.uuid4().hex[:6]}"
    await _seed_candidate(lastname=marker)

    resp = await m2_client.get(
        f"/api/search/?q={marker}", headers=headers_by_role[UserRole.user]
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "candidates" not in body["results"] or body["results"]["candidates"] == []
