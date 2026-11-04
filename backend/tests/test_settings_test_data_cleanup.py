"""Sprzątanie śladów testów z Ustawień WYKONANE na bazie testowej (20.10.2026).

Faza startu połyka błąd (``|| echo skipped``), więc pomyłkę w zapytaniu
zobaczylibyśmy dopiero w logu wdrożenia. Baza testowa jest współdzielona:
plan jest budowany z własnych wierszy testu i biegnie z własnym znacznikiem.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.app_setting import AppSetting
from app.models.client import Client
from app.models.client_cv_rule import ClientCvRule
from app.models.client_cv_rule_event import ClientCvRuleEvent
from app.models.client_cv_rule_publication import ClientCvRulePublication
from app.models.client_directory import ClientPortfolioScope
from app.models.client_playbook import ClientPlaybook
from app.models.client_playbook_event import ClientPlaybookEvent
from app.models.contract_template import ContractTemplate
from app.models.pipeline_template import (
    PipelineStageDef,
    PipelineTemplate,
    RejectionReason,
    StageCategoryEnum,
    TerminalType,
)
from app.models.service_account import ServiceAccount, ServiceAccountKey
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.services.settings_test_data_cleanup import (
    PinnedNamed,
    PinnedRow,
    SettingsCleanupPlan,
    run_settings_test_data_cleanup,
)
from tests.test_client_deletion import _client


async def _seed() -> dict:
    suffix = uuid.uuid4().hex[:8]
    client_id = await _client(f"ustawienia {suffix}")
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        client = await db.get(Client, client_id)
        lead = User(
            email=f"pytest-settings-cleanup-{suffix}@example.com",
            password_hash=hash_password(f"T3st_{suffix}!PassX"),
            name="Pytest Delivery Lead",
            role=UserRole.delivery_lead,
            roles=["delivery_lead"],
            is_active=True,
        )
        db.add(lead)
        await db.flush()
        rule = ClientCvRule(client_id=client_id)
        playbook = ClientPlaybook(client_id=client_id)
        assignment = DeliveryLeadClientAssignment(
            delivery_lead_user_id=lead.id, client_id=client_id
        )
        template = PipelineTemplate(name=f"ZZZ-smoke-{suffix}", archived=True)
        contract_template = ContractTemplate(
            name=f"Umowa (smoke test) {suffix}",
            contract_type="b2b",
            content_jinja="<p>smoke</p>",
            is_default=False,
        )
        account = ServiceAccount(slug=f"pytest-ops-{suffix}", name="ops", scopes=[])
        db.add_all(
            [
                rule,
                playbook,
                assignment,
                template,
                contract_template,
                account,
                ClientCvRuleEvent(client_id=client_id, rule_version=1, action="saved"),
                ClientCvRulePublication(
                    client_id=client_id, version=1, recipe={}, published_at=now
                ),
                ClientPlaybookEvent(
                    client_id=client_id, playbook_version=1, action="saved"
                ),
            ]
        )
        await db.flush()
        db.add_all(
            [
                PipelineStageDef(
                    template_id=template.id,
                    name="Alpha",
                    order=1,
                    category=StageCategoryEnum.internal,
                ),
                RejectionReason(
                    template_id=template.id,
                    name="work_mode_mismatch",
                    category=TerminalType.rejected,
                ),
                ServiceAccountKey(
                    key_id=f"v2${uuid.uuid4().hex[:24]}",
                    service_account_id=account.id,
                    secret_sha256="0" * 64,
                    label="claude-session",
                    expires_at=now + timedelta(days=30),
                ),
            ]
        )
        scope_id = await db.scalar(
            select(ClientPortfolioScope.id).where(
                ClientPortfolioScope.client_id == client_id
            )
        )
        await db.commit()
        return {
            "suffix": suffix,
            "client_id": client_id,
            "client_name": client.name,
            "lead_id": lead.id,
            "rule_id": rule.id,
            "playbook_id": playbook.id,
            "assignment_id": assignment.id,
            "scope_id": scope_id,
            "template_id": template.id,
            "template_name": template.name,
            "contract_template_id": contract_template.id,
            "contract_template_name": contract_template.name,
            "account_id": account.id,
            "account_slug": account.slug,
        }


def _plan(seed: dict, *, client_name: str | None = None) -> SettingsCleanupPlan:
    cid = seed["client_id"]
    return SettingsCleanupPlan(
        qa_clients=(PinnedNamed(cid, client_name or seed["client_name"]),),
        cv_rules=(PinnedRow(seed["rule_id"], cid),),
        playbooks=(PinnedRow(seed["playbook_id"], cid),),
        dl_assignments=(PinnedRow(seed["assignment_id"], cid),),
        portfolio_scopes=(PinnedRow(seed["scope_id"], cid),),
        pipeline_template=PinnedNamed(seed["template_id"], seed["template_name"]),
        contract_template=PinnedNamed(
            seed["contract_template_id"], seed["contract_template_name"]
        ),
        service_account=PinnedNamed(seed["account_id"], seed["account_slug"]),
    )


async def _drop(seed: dict, marker: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(AppSetting).where(AppSetting.key == marker))
        await db.execute(
            delete(PipelineTemplate).where(PipelineTemplate.id == seed["template_id"])
        )
        await db.execute(
            delete(ContractTemplate).where(
                ContractTemplate.id == seed["contract_template_id"]
            )
        )
        await db.execute(
            delete(ServiceAccount).where(ServiceAccount.id == seed["account_id"])
        )
        await db.execute(delete(Client).where(Client.id == seed["client_id"]))
        await db.execute(delete(User).where(User.id == seed["lead_id"]))
        await db.commit()


async def _exists(db, model, row_id: int) -> bool:
    return await db.get(model, row_id) is not None


async def test_cleanup_removes_settings_rows_and_keeps_client():
    seed = await _seed()
    marker = f"9999_settings_cleanup_{seed['suffix']}"
    try:
        async with AsyncSessionLocal() as db:
            summary = await run_settings_test_data_cleanup(
                db, marker=marker, plan=_plan(seed)
            )
            await db.commit()
        assert summary is not None
        assert summary["skipped"] == {}
        assert summary["history_rows_deleted"] == 3
        assert summary["service_account_keys_revoked"] == 1

        async with AsyncSessionLocal() as db:
            assert await _exists(db, Client, seed["client_id"])
            for model, key in (
                (ClientCvRule, "rule_id"),
                (ClientPlaybook, "playbook_id"),
                (DeliveryLeadClientAssignment, "assignment_id"),
                (ClientPortfolioScope, "scope_id"),
                (PipelineTemplate, "template_id"),
                (ContractTemplate, "contract_template_id"),
            ):
                assert not await _exists(db, model, seed[key]), model.__tablename__
            assert (
                await db.scalar(
                    select(PipelineStageDef.id).where(
                        PipelineStageDef.template_id == seed["template_id"]
                    )
                )
                is None
            )
            account = await db.get(ServiceAccount, seed["account_id"])
            assert account is not None and account.is_active is False
            key = await db.scalar(
                select(ServiceAccountKey).where(
                    ServiceAccountKey.service_account_id == seed["account_id"]
                )
            )
            assert key is not None and key.revoked_at is not None
            assert (await db.get(AppSetting, marker)) is not None

        async with AsyncSessionLocal() as db:
            again = await run_settings_test_data_cleanup(
                db, marker=marker, plan=_plan(seed)
            )
            await db.rollback()
        assert again is None
    finally:
        await _drop(seed, marker)


async def test_cleanup_leaves_client_rows_when_client_name_differs():
    seed = await _seed()
    marker = f"9999_settings_cleanup_{seed['suffix']}"
    try:
        async with AsyncSessionLocal() as db:
            summary = await run_settings_test_data_cleanup(
                db, marker=marker, plan=_plan(seed, client_name="Inna firma")
            )
            await db.commit()
        assert summary["skipped"][f"clients:{seed['client_id']}"] == (
            "fingerprint_mismatch"
        )
        async with AsyncSessionLocal() as db:
            assert await _exists(db, ClientCvRule, seed["rule_id"])
            assert await _exists(db, ClientPlaybook, seed["playbook_id"])
            assert await _exists(
                db, DeliveryLeadClientAssignment, seed["assignment_id"]
            )
            assert await _exists(db, ClientPortfolioScope, seed["scope_id"])
    finally:
        await _drop(seed, marker)


async def test_cleanup_keeps_pipeline_template_that_is_not_archived():
    seed = await _seed()
    marker = f"9999_settings_cleanup_{seed['suffix']}"
    try:
        async with AsyncSessionLocal() as db:
            template = await db.get(PipelineTemplate, seed["template_id"])
            template.archived = False
            await db.commit()
        async with AsyncSessionLocal() as db:
            summary = await run_settings_test_data_cleanup(
                db, marker=marker, plan=_plan(seed)
            )
            await db.commit()
        assert summary["skipped"][f"pipeline_templates:{seed['template_id']}"] == (
            "fingerprint_mismatch"
        )
        async with AsyncSessionLocal() as db:
            assert await _exists(db, PipelineTemplate, seed["template_id"])
    finally:
        await _drop(seed, marker)
