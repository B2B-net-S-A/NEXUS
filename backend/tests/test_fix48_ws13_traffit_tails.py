"""Ogony wyłączenia Traffita (decyzja Artura 14.10.2026, po WS08).

„My już z Traffita nie korzystamy, żadne importy z Traffita ani sync nie
powinny już działać.” WS08 zamknął `/api/admin/traffit/*`; zostały dwa wejścia,
które nadal prowadziły do Traffita okrężną drogą:

* `POST /api/admin/champion-profiles/ingest` — cel collectora uruchamianego
  w karcie Traffita (import profili Championa z plików Traffita);
* „Wróć do Traffita” (`POST /api/jobs/{id}/manage-in-nexus` z `enabled=false`)
  — oddawał rekrutację nocnemu importowi, którego już nie ma.

Oba odpowiadają 410 po bramkach, zanim cokolwiek przeczytają albo zapiszą.
Do tego uptime-probe nie ostrzega o `checks.traffit = disabled` — to stan
oczekiwany na stałe, a stałe ostrzeżenie uczy ignorować kanał.

Bez bazy: handlery wołane wprost. Ścieżki HTTP z logowaniem są
w `test_job_managed_in_nexus_api.py` i `test_permissions_recruitment.py`
(wymagają Postgresa).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from app.api import admin_champion_ingest, jobs
from app.models.job import Job
from app.models.user import UserRole
from app.schemas.job import JobManageInNexusRequest
from app.services.traffit_retired import TRAFFIT_RETIRED_MESSAGE
from tests.test_permissions_recruitment import _account
from tests.test_uptime_probe_health_checks import _payload, requires_jq
from tests.test_uptime_probe_health_checks import _run as _run_probe

REVERT_MESSAGE = (
    "Traffit jest wyłączony od 14.10.2026 — rekrutacja zostaje prowadzona w NEXUSIE."
)


class _Upload:
    filename = "profil.pdf"
    size = 10

    def __init__(self) -> None:
        self.reads = 0

    async def read(self, limit: int = -1) -> bytes:
        self.reads += 1
        return b"%PDF-1.4 fake"


@pytest.mark.asyncio
async def test_champion_ingest_is_gone_before_reading_the_file(monkeypatch) -> None:
    def _no_extract(*_args, **_kwargs):
        raise AssertionError("odczyt pliku po wyłączeniu Traffita")

    async def _no_ingest(*_args, **_kwargs):
        raise AssertionError("zapis profilu po wyłączeniu Traffita")

    monkeypatch.setattr(admin_champion_ingest, "extract_document_text", _no_extract)
    monkeypatch.setattr(admin_champion_ingest, "ingest_parsed_profile", _no_ingest)
    upload = _Upload()
    db = AsyncMock()

    handler = admin_champion_ingest.champion_ingest.__wrapped__
    resp = await handler(
        request=None,
        current_user=SimpleNamespace(id=1),
        file=upload,
        external_rid="123",
        file_id=5,
        db=db,
    )

    assert resp.status_code == 410
    assert resp.body.decode("utf-8") == ('{"detail":"' + TRAFFIT_RETIRED_MESSAGE + '"}')
    assert upload.reads == 0
    db.execute.assert_not_awaited()


def _traffit_job(*, managed: bool = True) -> tuple[Job, SimpleNamespace]:
    job = Job(
        id=7,
        title="Rekrutacja",
        client_id=5,
        external_source="traffit",
        managed_in_nexus=managed,
    )
    db = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: job)),
        get=AsyncMock(return_value=job),
        add=Mock(),
        commit=AsyncMock(),
        refresh=AsyncMock(),
    )
    return job, db


@pytest.mark.asyncio
@pytest.mark.parametrize("managed", [True, False])
async def test_return_to_traffit_is_gone_for_the_permission_holder(
    managed: bool,
) -> None:
    """Admin (z uprawnieniem) też nie odda rekrutacji Traffitowi — i nic się
    nie zapisuje, także gdy przełącznik już był wyłączony."""
    job, db = _traffit_job(managed=managed)
    admin = _account(UserRole.admin, permissions=("recruitment_manage",))

    with pytest.raises(HTTPException) as gone:
        await jobs.set_job_managed_in_nexus(
            7, JobManageInNexusRequest(enabled=False), admin, db
        )

    assert gone.value.status_code == 410
    assert gone.value.detail == REVERT_MESSAGE
    db.add.assert_not_called()
    db.commit.assert_not_awaited()
    assert job.managed_in_nexus is managed


@pytest.mark.asyncio
async def test_return_to_traffit_still_names_the_permission_first() -> None:
    """Bramka uprawnienia zostaje przed 410: kto go nie ma, słyszy, czego brakuje."""
    _job, db = _traffit_job()

    with pytest.raises(HTTPException) as denied:
        await jobs.set_job_managed_in_nexus(
            7,
            JobManageInNexusRequest(enabled=False),
            _account(UserRole.recruiter),
            db,
        )

    assert denied.value.status_code == 403


@requires_jq
def test_disabled_traffit_check_is_silent_in_uptime_probe(tmp_path) -> None:
    """`traffit = disabled` to stan na stałe (14.10.2026) — bez ostrzeżenia,
    jak `priority_work = disabled`. `degraded` nadal ostrzega."""
    code, outputs, annotations = _run_probe(tmp_path, _payload(traffit="disabled"))
    assert code == 0
    assert outputs.get("fail") == "0"
    assert annotations == []

    code, outputs, annotations = _run_probe(tmp_path, _payload(traffit="degraded"))
    assert outputs.get("fail") == "0"
    assert any(a.startswith("::warning") and "traffit" in a for a in annotations)
