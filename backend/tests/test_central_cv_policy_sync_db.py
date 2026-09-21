"""Hosted PostgreSQL: central publications retain previous recipes and drafts."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select, func
from app.core.database import AsyncSessionLocal
from app.models.client import Client, ClientStatus
from app.models.client_cv_rule import ClientCvRule
from app.models.client_cv_rule_publication import ClientCvRulePublication
from app.models.client_cv_rule_event import ClientCvRuleEvent
from app.services.cv_generator_b2b import central_policies as policies


async def test_sync_publishes_once_preserves_history_and_never_activates_draft(monkeypatch):
    async with AsyncSessionLocal() as db:
        client=Client(name='CV policy test '+uuid4().hex, status=ClientStatus.active, hidden=False, external_source='traffit', external_id='cv-test-'+uuid4().hex, cv_content_mode_cap='basic')
        db.add(client)
        await db.flush()
        policy={**policies.policy_for(11),'client_id':client.id,'external_id':client.external_id}
        monkeypatch.setattr(policies,'catalog',lambda:(policy,))
        old=ClientCvRule(client_id=client.id,version=7,edit_revision=4,confirmed_at=datetime.now(timezone.utc),filename_pattern='OLD_{IMIE_NAZWISKO}',generator_instructions='Legacy instruction',draft_payload={'generator_instructions':'DO NOT ACTIVATE'})
        db.add(old)
        await db.commit()
        assert await policies.synchronize(db)==1
        assert old.version==8 and old.cv_language=='en'
        assert old.generator_instructions is None and old.draft_payload is None
        assert client.cv_content_mode_cap=='basic'
        assert await policies.synchronize(db)==0
        previous=await db.get(ClientCvRulePublication,(client.id,7))
        assert previous.recipe['filename_pattern']=='OLD_{IMIE_NAZWISKO}'
        assert previous.recipe['generator_instructions']=='Legacy instruction'
        event=await db.scalar(select(ClientCvRuleEvent).where(ClientCvRuleEvent.client_id==client.id))
        assert event.changes['previous_draft']['generator_instructions']=='DO NOT ACTIVATE'
        assert await db.scalar(select(func.count()).select_from(ClientCvRulePublication).where(ClientCvRulePublication.client_id==client.id))==2
