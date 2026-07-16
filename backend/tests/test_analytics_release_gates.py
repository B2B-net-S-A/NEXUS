"""Bramki release Analytics (plan PR 8) — blokujące testy CI.

CI musi blokować (plan §PR8):
1. NOWE heady Alembica (chroniczny multi-head prod: baseline 24 — plan
   wymagał "dokładnie jeden", ale wymuszenie single-head to osobna,
   ryzykowna operacja scalająca; bramka pilnuje ZERA nowych),
2. mutacje w analytics/DynaReporter chronione tylko CurrentUser,
3. viewer-safe odpowiedzi z zakazanym polem finansowym,
4. dryf kontraktu OpenAPI /api/analytics/v1 bez świadomej aktualizacji.

RBAC matrix + zakaz 500-jako-odmowy egzekwuje test_rbac.py (też blocking).
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.user import User, UserRole

BACKEND = Path(__file__).resolve().parents[1]

# Baseline historycznych headów (stan 2026-07-16). Nowa migracja MUSI
# doczepić się do istniejącego grafu (down_revision = aktualny czubek
# łańcucha 01xx), nie tworzyć nowego heada. 25. head to
# 0175_stage_notif_user_fk_cascade (równoległa sesja 2026-07-16 — dubel
# numeru 0175 i wiszący czubek; gate powstał ZA późno żeby go złapać).
# Obniżaj baseline przy scalaniu headów; NIGDY nie podnoś bez powodu.
_ALEMBIC_HEADS_BASELINE = 25


def _alembic_heads() -> list[str]:
    versions = BACKEND / "alembic" / "versions"
    revs: dict[str, str] = {}
    downs: set[str] = set()
    for f in versions.glob("*.py"):
        src = f.read_text(encoding="utf-8")
        m = re.search(r"^revision(?::\s*str)?\s*=\s*['\"]([^'\"]+)", src, re.M)
        if m:
            revs[m.group(1)] = f.name
        for dd in re.findall(r"down_revision(?::[^=]*)?\s*=\s*(.+)", src):
            for tok in re.findall(r"['\"]([^'\"]+)['\"]", dd):
                downs.add(tok)
    return [r for r in revs if r not in downs]


def test_no_new_alembic_heads():
    heads = _alembic_heads()
    assert len(heads) <= _ALEMBIC_HEADS_BASELINE, (
        f"Nowy head Alembica! ({len(heads)} > baseline {_ALEMBIC_HEADS_BASELINE}). "
        "Doczep migrację do aktualnego czubka łańcucha 01xx (down_revision), "
        f"nadmiarowe heady: sprawdź {sorted(heads)[-5:]}"
    )


# ── Gate 2: żadnych mutacji na gołym CurrentUser w analytics/Dyna ────────────

_WRITE_DECORATOR = re.compile(
    r"@router\.(post|put|patch|delete)\([^)]*\)\s*\nasync def (\w+)\((.*?)\):",
    re.S,
)

# Wyjątki świadome: self-scoped stan usera (read-marker notyfikacji).
_ALLOWED_CURRENTUSER_WRITES = {
    ("dynareporter_competitions.py", "mark_read"),
    # Mindy: POSTy generujące LLM-komentarz/czat nad WŁASNYM KPI usera —
    # nic nie zapisują do danych raportowych.
    ("dynareporter_mindy.py", "commentary"),
    ("dynareporter_mindy.py", "chat"),
}


def test_no_currentuser_only_mutations_in_analytics_and_dyna():
    api_dir = BACKEND / "app" / "api"
    offenders: list[str] = []
    for f in list(api_dir.glob("dynareporter_*.py")) + [
        api_dir / "analytics_v1.py",
        api_dir / "financial_adjustments.py",
    ]:
        src = f.read_text(encoding="utf-8")
        for m in _WRITE_DECORATOR.finditer(src):
            handler, params = m.group(2), m.group(3)
            if (f.name, handler) in _ALLOWED_CURRENTUSER_WRITES:
                continue
            protected = (
                "AdminUser" in params
                or "require_capability" in params
                or "require_dynareporter_section" in params
                or "DlAssignedOrAdmin" in params
            )
            if "CurrentUser" in params and not protected:
                offenders.append(f"{f.name}::{handler}")
    assert not offenders, (
        f"Mutacje chronione tylko CurrentUser w analytics/Dyna (plan §PR8): {offenders}"
    )


# ── Gate 3: viewer-safe bez pól finansowych ──────────────────────────────────

_FORBIDDEN_KEY_PARTS = (
    "mrr",
    "margin",
    "revenue",
    "salary",
    "rate_client",
    "rate_candidate",
    "ltv",
    "profit",
    "cost",
)


def _forbidden_keys(payload, path="") -> list[str]:
    found: list[str] = []
    if isinstance(payload, dict):
        for k, v in payload.items():
            lk = k.lower()
            if any(part in lk for part in _FORBIDDEN_KEY_PARTS):
                found.append(f"{path}/{k}")
            found.extend(_forbidden_keys(v, f"{path}/{k}"))
    elif isinstance(payload, list):
        for i, item in enumerate(payload[:20]):
            found.extend(_forbidden_keys(item, f"{path}[{i}]"))
    return found


@pytest_asyncio.fixture
async def gates_client():
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=True),
        base_url="http://testserver",
    ) as c:
        yield c


async def _viewer_headers(client: AsyncClient) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"gate-viewer-{unique}@example.com"
    password = f"T3st_{unique}!G"
    async with AsyncSessionLocal() as db:
        existing = await db.scalar(select(User).where(User.email == email))
        if existing is None:
            db.add(
                User(
                    email=email,
                    password_hash=hash_password(password),
                    name="Gate Viewer",
                    role=UserRole.user,
                    is_active=True,
                )
            )
            await db.commit()
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


VIEWER_SAFE_ENDPOINTS = [
    "/api/analytics/v1/overview",
    "/api/analytics/v1/pipeline/snapshot",
    "/api/analytics/v1/recruitment/funnel",
    "/api/analytics/v1/sources",
    "/api/analytics/v1/calls/aggregate",
    "/api/dashboard/stats",
    "/api/dashboard/kpis",
    "/api/dashboard/pipeline-funnel",
]


@pytest.mark.asyncio
async def test_viewer_safe_responses_have_no_finance_fields(gates_client, monkeypatch):
    """Fizyczny denylist: odpowiedzi viewer-safe nie mogą nieść finansów."""
    monkeypatch.setattr(settings, "ANALYTICS_V1_MODE", "shadow")
    headers = await _viewer_headers(gates_client)
    for path in VIEWER_SAFE_ENDPOINTS:
        resp = await gates_client.get(path, headers=headers)
        assert resp.status_code == 200, f"{path}: {resp.status_code} {resp.text}"
        bad = _forbidden_keys(resp.json())
        assert not bad, f"{path} niesie pola finansowe dla viewera: {bad}"


# ── Gate 4: kontrakt OpenAPI /api/analytics/v1 ───────────────────────────────

_CONTRACT_FILE = BACKEND / "tests" / "analytics_v1_openapi_contract.json"


def _current_contract() -> dict:
    from app.main import app

    schema = app.openapi()
    paths = {
        p: sorted(methods.keys())
        for p, methods in schema.get("paths", {}).items()
        if p.startswith("/api/analytics/v1")
    }
    return {"paths": paths}


def test_analytics_openapi_contract_committed():
    """Dryf kontraktu v1 bez aktualizacji committed snapshotu = czerwone CI.

    Zmieniłeś /api/analytics/v1? Uruchom:
      python -c "from tests.test_analytics_release_gates import write_contract; write_contract()"
    i zacommituj zaktualizowany analytics_v1_openapi_contract.json
    (świadoma zmiana kontraktu; frontend stats-api.ts musi być w sync).
    """
    current = _current_contract()
    assert _CONTRACT_FILE.exists(), (
        "Brak committed kontraktu — wygeneruj: python -c "
        '"from tests.test_analytics_release_gates import write_contract; write_contract()"'
    )
    committed = json.loads(_CONTRACT_FILE.read_text(encoding="utf-8"))
    assert current == committed, (
        "Kontrakt /api/analytics/v1 zdryfował względem committed snapshotu. "
        "Jeśli zmiana jest świadoma: zaktualizuj snapshot (docstring wyżej) "
        "i dopasuj frontend/src/lib/stats-api.ts."
    )


def write_contract() -> None:  # pragma: no cover — narzędzie deweloperskie
    _CONTRACT_FILE.write_text(
        json.dumps(_current_contract(), indent=2, ensure_ascii=False, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    print(f"written: {_CONTRACT_FILE}")
