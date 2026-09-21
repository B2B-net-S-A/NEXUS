from datetime import date
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from app.api import cv_generator_b2b as api
from app.services.cv_generator_b2b import job_leases, requirement_map
from app.services.cv_generator_b2b.job_snapshot import _encode
from app.services.cv_generator_b2b.standalone_service import PreparedSourceFacts, GenerationResult
from app.services.cv_generator_b2b.client_rules import CvRuleSnapshot
from tests.test_cv_enqueue_sources import source


@pytest.mark.parametrize('mode',['new','upload'])
@pytest.mark.parametrize('second_ready',[False,True])
async def test_retry_never_rerenders_or_charges_finished_language_and_reuses_failed_row(monkeypatch,mode,second_ready):
    facts=PreparedSourceFacts('original source','{}','sha','notes')
    primary=NS(id=11,language='pl',status='ready',central_policy={'required_languages':['pl','en']},job_id=4,candidate_id=2,client_id=5,candidate_name='Synthetic Person',position='Developer')
    second=NS(id=12,status='ready' if second_ready else 'failed',error_message='failed')
    job=NS(second_generated_id=12,prepared_source_facts=_encode(facts))
    db=AsyncMock(); db.add=Mock(); db.get.side_effect=lambda model,pk: primary if pk==11 else second
    manager=Mock(__aenter__=AsyncMock(return_value=db),__aexit__=AsyncMock(return_value=None))
    monkeypatch.setattr(api,'AsyncSessionLocal',lambda:manager)
    monkeypatch.setattr(job_leases,'lock_owned_job',AsyncMock(return_value=job))
    monkeypatch.setattr(job_leases,'register_second_document',AsyncMock())
    monkeypatch.setattr(requirement_map,'ensure_requirement_map',AsyncMock())
    prepare=Mock(side_effect=AssertionError('must reuse prepared facts'))
    monkeypatch.setattr(api,'prepare_source_facts',prepare)
    quota=AsyncMock(return_value=api.QuotaState(1,100,date(2026,9,1),str(uuid4())))
    monkeypatch.setattr(api,'_charge_second_language_or_note',quota)
    monkeypatch.setattr(api,'_charge_final_review',AsyncMock(return_value=None))
    pending=AsyncMock(side_effect=AssertionError('duplicate output'))
    monkeypatch.setattr(api,'_create_pending_row',pending)
    finalize=AsyncMock(return_value=True);monkeypatch.setattr(api,'_finalize_success',finalize)
    seen=[]
    result=GenerationResult(candidate_name='Synthetic Person',filename='cv-en.docx',docx_bytes=b'docx',warnings=[],processing_time_ms=1,render_payload={},job_id=4)
    async def render_new(captured,**kwargs):
        assert kwargs['prepared_source_facts']==facts
        seen.append(kwargs['language']);return result
    def render_upload(payload,**kwargs):
        assert kwargs['prepared_source_facts']==facts
        seen.append(payload.language);return result
    monkeypatch.setattr(api,'generate_cv_from_candidate_source',render_new)
    monkeypatch.setattr(api,'generate_cv_from_uploads',render_upload)
    monkeypatch.setattr(api,'_upload_requirements',lambda _:[])
    rule=CvRuleSnapshot(filename_pattern=None,spaces_to_underscores=False,cv_language=None,requires_en_copy=True,requires_rodo_consent_block=False,auto_second_language=True)
    if mode=='new':
        await api._run_generate_new_job(11,candidate_id=2,stage_id=3,language='pl',blind_cv=False,user_id=7,source=source(),rule_snapshot=rule)
    else:
        payload=api.UploadGenerationInput(cv_bytes=b'file',cv_filename='file.pdf',language='pl',blind_cv=False,client_rule=rule)
        await api._run_generate_upload_job(11,payload=payload,user_id=7)
    assert primary.status=='ready'
    assert seen==([] if second_ready else ['en'])
    assert quota.await_count==(0 if second_ready else 1)
    assert finalize.await_count==(0 if second_ready else 1)
    if not second_ready: assert finalize.call_args.args[1]==12
    prepare.assert_not_called();pending.assert_not_called()
