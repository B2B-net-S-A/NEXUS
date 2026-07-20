"""Bramki release Analytics (plan PR 8) — blokujące testy CI.

CI musi blokować (plan §PR8):
1. NOWE heady Alembica — od 2026-07-20 baseline wynosi 1, czyli plan
   doczekał się swojego "dokładnie jednego". Scalenie okazało się tanie
   (0179 łączy 0177+0178); ryzykowna wydawała się tylko dlatego, że
   regexowy licznik headów raportował 26 zamiast 2,
2. mutacje w analytics/DynaReporter chronione tylko CurrentUser,
3. viewer-safe odpowiedzi z zakazanym polem finansowym,
4. dryf kontraktu OpenAPI /api/analytics/v1 bez świadomej aktualizacji.

RBAC matrix + zakaz 500-jako-odmowy egzekwuje test_rbac.py (też blocking).
"""

from __future__ import annotations

import json
import ast
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

# Dozwolona liczba headów. Od 2026-07-20 wynosi 1 — czyli łańcuch MUSI mieć
# dokładnie jeden czubek.
#
# Poprzednia wartość (25) nie opisywała rzeczywistości, tylko błąd parsera:
# regexowa wersja `_alembic_heads()` nie czytała wieloliniowego
# `down_revision = (...)`, więc liczyła 26 headów, podczas gdy sam alembic
# raportował 2. Baseline podnoszono, żeby pomieścić zmyślone heady — a to
# znaczy, że prawdziwy nowy head mógł się pojawić, nigdy nie przekraczając
# progu. Bramka przez cały ten czas mierzyła szum.
#
# Po scaleniu 0177+0178 przez 0179 i naprawie parsera prawdziwa liczba to 1.
# Trzymamy ją na 1: `alembic upgrade head` (l. poj.) w backup-drill.yml
# rozwiązuje się tylko przy jednym czubku, więc każdy rozjazd natychmiast
# psuje ścieżkę odtworzenia po awarii. NIGDY nie podnoś tej wartości —
# zamiast tego dopisz migrację merge.
_ALEMBIC_HEADS_BASELINE = 1


def _alembic_heads() -> list[str]:
    """Heads in the migration graph, parsed with `ast` rather than regex.

    The previous implementation used
    ``re.findall(r"down_revision(?::[^=]*)?\\s*=\\s*(.+)", src)``. ``.`` does not
    match newlines, so for the multi-line merge form::

        down_revision = (
            "0177_analytics_snapshots_cutovers",
            "0178_recruitment_processes",
        )

    the capture was the bare ``(`` and the inner token scan found **no
    parents** — every ancestor declared that way stayed unclaimed and was
    counted as a head. 14 files parsed differently under the two approaches,
    11 of them multi-line tuples.

    The consequence was worse than a wrong number: this gate exists to stop
    head sprawl, and it reported 26 heads while alembic itself reported 2. The
    baseline was then raised to 25 to accommodate the phantom count, which
    meant a genuine new head could appear without ever crossing the threshold.
    Fixing head sprawl also *tripped* it, because a merge revision necessarily
    uses the very syntax the regex could not read.

    Parsing the assignment properly handles both the string and the
    tuple/list form, and matches ``alembic heads`` exactly.
    """
    versions = BACKEND / "alembic" / "versions"
    revs: set[str] = set()
    downs: set[str] = set()
    for f in versions.glob("*.py"):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover — a broken migration file
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            target = node.targets[0] if isinstance(node, ast.Assign) else node.target
            if not isinstance(target, ast.Name):
                continue
            value = node.value
            if target.id == "revision" and isinstance(value, ast.Constant):
                revs.add(value.value)
            elif target.id == "down_revision":
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    downs.add(value.value)
                elif isinstance(value, (ast.Tuple, ast.List)):
                    for element in value.elts:
                        if isinstance(element, ast.Constant) and isinstance(
                            element.value, str
                        ):
                            downs.add(element.value)
    return sorted(revs - downs)


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
# UWAGA (audyt M7 PR-01): mindy commentary/chat zeszły z allowlisty — mają
# teraz router-level guard (require_dynareporter_section), wykrywany niżej.
_ALLOWED_CURRENTUSER_WRITES = {
    ("dynareporter_competitions.py", "mark_read"),
}

# Router-level guard: `APIRouter(dependencies=[Depends(require_...)])` chroni
# wszystkie endpointy pliku, mimo że nie widać go w sygnaturze handlera.
_ROUTER_LEVEL_GUARD = re.compile(
    r"APIRouter\(\s*dependencies=\[.*?"
    r"(?:require_capability|require_dynareporter_section|AdminUser|DlAssignedOrAdmin)"
    r".*?\]",
    re.S,
)


def test_no_currentuser_only_mutations_in_analytics_and_dyna():
    api_dir = BACKEND / "app" / "api"
    offenders: list[str] = []
    for f in list(api_dir.glob("dynareporter_*.py")) + [
        api_dir / "analytics_v1.py",
        api_dir / "financial_adjustments.py",
    ]:
        src = f.read_text(encoding="utf-8")
        router_level_guard = bool(_ROUTER_LEVEL_GUARD.search(src))
        for m in _WRITE_DECORATOR.finditer(src):
            handler, params = m.group(2), m.group(3)
            if (f.name, handler) in _ALLOWED_CURRENTUSER_WRITES:
                continue
            protected = (
                router_level_guard
                or "AdminUser" in params
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
