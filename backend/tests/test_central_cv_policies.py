from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock
import importlib.util
from pathlib import Path

import pytest
from fastapi import HTTPException
from app.services.cv_generator_b2b import central_policies as policies
from app.services.cv_generator_b2b.client_rules import snapshot_rule, build_filename
from app.models.client_cv_rule import ClientCvRule
from app.services.cv_packages import project_number


def rule(client_id):
    policy = policies.policy_for(client_id)
    return snapshot_rule(ClientCvRule(version=1, managed_policy=policies.metadata(policy), **policies.recipe_for(policy)))


@pytest.mark.parametrize('client_id,language,bilingual', [(11,'en',False),(39,None,True),(18,None,True),(12,None,True),(103,None,True),(32,'pl',False),(26,'pl',False),(116,'pl',False),(None,None,False),(999999,None,False)])
def test_catalog_contract(client_id, language, bilingual):
    snapshot = rule(client_id)
    assert snapshot.cv_language == language
    assert snapshot.auto_second_language == bilingual
    assert snapshot.requires_en_copy == bilingual
    assert snapshot.max_roles is None
    assert snapshot.why_points_max == 4
    assert snapshot.notes is None
    assert snapshot.generator_instructions is None


def test_naming_pko_prefix_ca_date_and_kir_spaces():
    assert project_number('ZOB-ZOB-123') == '123'
    pko = build_filename(rule(26), position='Java Developer', candidate_name='Jan Kowalski', project='ZOB-ZOB-123')
    assert pko.filename == 'ZOB-123_Java Developer_Jan Kowalski.docx'
    ca = build_filename(rule(116), position='Java Developer', candidate_name='Jan Kowalski', today=date(2026,9,21))
    assert ca.filename == 'B2B.NET_Java_Developer_Jan_Kowalski_2026-09-21.docx'
    assert build_filename(rule(32), position='Java Developer', candidate_name='Jan Kowalski').filename == 'B2B_Java_Developer_Jan_Kowalski.docx'


def test_incomplete_context_is_generic_and_cap_wins(monkeypatch):
    assert policies.automatic_mode(None) == 'polished'
    import app.services.champion_intake as intake
    monkeypatch.setattr('app.services.cv_generator_b2b.standalone_service.champion_present', lambda _: True)
    job = SimpleNamespace(champion_profile={'any':'profile'})
    monkeypatch.setattr(intake, 'enforce_operation', lambda *a, **kw: None)
    assert policies.automatic_mode(job) == 'tailored'
    assert policies.automatic_mode(job, 'basic') == 'basic'
    def fail(*a, **kw):
        assert kw['force'] is True
        raise HTTPException(422, 'incomplete')
    monkeypatch.setattr(intake, 'enforce_operation', fail)
    assert policies.automatic_mode(job) == 'polished'


async def test_api_rejects_policy_write_before_access_or_mutation(monkeypatch):
    from app.api.client_cv_rules import _require_client_rule_access
    monkeypatch.setattr(policies.settings, 'CV_CENTRAL_POLICIES_ENABLED', True)
    db = AsyncMock()
    with pytest.raises(HTTPException) as error:
        await _require_client_rule_access(db, SimpleNamespace(id=1), 11, write=True)
    assert error.value.status_code == 403
    db.execute.assert_not_called()


def test_migration_is_additive_and_mirrored():
    path = Path(__file__).parents[1] / 'alembic/versions/0331_central_cv_policies.py'
    spec = importlib.util.spec_from_file_location('central_migration', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    entrypoint = (Path(__file__).parents[1] / 'entrypoint.sh').read_text()
    assert all(ddl in entrypoint and 'ADD COLUMN IF NOT EXISTS' in ddl for ddl in module.DDL)


def test_pko_request_number_is_not_internal_ats_reference():
    from app.services.cv_packages import pko_job_reference
    assert pko_job_reference(SimpleNamespace(title="Programista Java (ZOB-2976)", reference_number="74/9/2026/MW/4961")) == "2976"
    assert pko_job_reference(SimpleNamespace(title="Programista Java", reference_number="74/9/2026/MW/4961")) is None
    assert pko_job_reference(SimpleNamespace(title="ZOB-2976", reference_number="ZOB-2900")) is None
