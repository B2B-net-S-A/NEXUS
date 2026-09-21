from datetime import datetime, timezone
from hashlib import sha256
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from app.services import cv_packages as packages
from app.models.cv_document_version import CvDocumentVersion
from app.models.cv_generated_draft import CvGeneratedDraft
from app.models.note import Note
from app.models.job import Job


@pytest.fixture
def package(monkeypatch):
    policy = {'required_languages':['pl','en'], 'require_recommendation_note':True, 'version':1}
    rows = [NS(id=i, language=lang, status='ready', filename=f'CV_{lang}.docx', candidate_id=8, job_id=9, central_policy=policy, package_review=None, position='Developer', content_mode='tailored', render_payload={}) for i,lang in [(1,'pl'),(2,'en')]]
    versions = {i:NS(id=i+10, language=row.language, generated_owner_id=i, candidate_stage_cv_id=None, content_html=f'<p>{row.language}</p>', content_sha256=sha256(f'<p>{row.language}</p>'.encode()).hexdigest(), docx_content=b'file', docx_sha256=sha256(b'file').hexdigest(), consent_content=None, docx_filename=row.filename) for i,row in enumerate(rows,1)}
    owners = {i:NS(branded_status='finalized', branded_draft_html=versions[i].content_html, edit_revision=1) for i in (1,2)}
    note = NS(id=20, content='Recommendation for this recruitment', updated_at=datetime.now(timezone.utc), candidate_id=8, job_id=9, source_deleted_at=None)
    job = NS(status='complete', input_storage_key='cv/input.json', prepared_source_facts={'facts':True})
    monkeypatch.setattr(packages,'members',AsyncMock(return_value=(job,rows[0],rows)))
    db = AsyncMock()
    async def scalar(query):
        entity = query.column_descriptions[0]['entity']
        params=query.compile().params
        if entity is CvDocumentVersion:
            i=params.get('generated_document_id_1') or params.get('generated_owner_id_1')
            return versions.get(i)
        if entity is CvGeneratedDraft:
            return owners[params['generated_document_id_1']]
        if entity is Note:
            return None if query.column_descriptions[0]['name']=='id' else note
        raise AssertionError(str(query))
    db.scalar.side_effect=scalar
    async def get(model,pk):
        if model is Job: return NS(reference_number='ZOB-123')
        if model is CvDocumentVersion: return versions[pk-10]
        raise AssertionError(model)
    db.get.side_effect=get
    return db,rows,versions,owners,note


async def test_generated_is_not_ready_and_confirmation_pins_both_versions(package):
    db,rows,versions,owners,note=package
    state,_=await packages.assess(db,rows[0])
    assert not state['ready']
    assert state['available_languages']==['pl','en']
    state=await packages.confirm(db,rows[0],note_id=20,sources_checked=True,user_id=5,expected_fingerprint=(await packages.assess(db,rows[0],note_id=20))[0]['fingerprint'])
    assert state['ready']
    assert await packages.require_ready(db,rows[1],11)=={'pl':11,'en':12}
    assert rows[0].package_review['note_version']['hash']==sha256(note.content.encode()).hexdigest()
    assert (await packages.public_documents(db,{'pl':11,'en':12}))['package_documents'][1]['language']=='en'


@pytest.mark.parametrize('change', ['note','draft','version','other_recruitment','deleted_note','missing_en','corrupt_docx','missing_project','wrong_query','bad_consent'])
async def test_changes_or_missing_requirements_block_confirmation_and_api_share(package,change):
    db,rows,versions,owners,note=package
    await packages.confirm(db,rows[0],note_id=20,sources_checked=True,user_id=5,expected_fingerprint=(await packages.assess(db,rows[0],note_id=20))[0]['fingerprint'])
    if change=='note': note.content+=' corrected'
    elif change=='draft': owners[1].branded_status='draft'
    elif change=='version': versions[1].id=99
    elif change=='other_recruitment': note.job_id=10
    elif change=='deleted_note': note.source_deleted_at=datetime.now(timezone.utc)
    elif change=='missing_en': rows[1].status='failed'
    elif change=='corrupt_docx': versions[1].docx_content=b'corrupt'
    elif change=='missing_project': rows[0].central_policy['require_project_ref']=True
    else:
        rows[0].central_policy.update(requires_rodo_consent_block=True,project_ref='124' if change=='wrong_query' else '123')
        for version in versions.values(): version.consent_content=b'not-an-image'
    with pytest.raises(HTTPException) as error:
        await packages.require_ready(db,rows[0],11)
    assert error.value.status_code==409


async def test_no_implicit_note_or_unchecked_sources(package):
    db,rows,*_=package
    with pytest.raises(HTTPException):
        await packages.confirm(db,rows[0],note_id=None,sources_checked=True,user_id=5,expected_fingerprint=(await packages.assess(db,rows[0],note_id=20))[0]['fingerprint'])
    with pytest.raises(HTTPException):
        await packages.confirm(db,rows[0],note_id=20,sources_checked=False,user_id=5,expected_fingerprint=(await packages.assess(db,rows[0],note_id=20))[0]['fingerprint'])


async def test_legacy_share_has_no_new_requirements():
    assert await packages.require_ready(AsyncMock(),NS(central_policy=None),42) is None


async def test_stale_confirmation_cannot_approve_changed_note(package):
    db,rows,_,_,note=package
    fingerprint=(await packages.assess(db,rows[0],note_id=20))[0]['fingerprint']
    note.content+=' changed in another session'
    with pytest.raises(HTTPException) as error:
        await packages.confirm(db,rows[0],note_id=20,sources_checked=True,user_id=5,expected_fingerprint=fingerprint)
    assert error.value.status_code==409
    assert rows[0].package_review is None
