"""Focused recipient-scope regression tests for Delivery background alerts."""

from __future__ import annotations

import uuid

import pytest

from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.section_permission import UserSectionOverride
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.services.delivery_alert_recipients import (
    load_delivery_alert_recipient_scope,
)
from app.services.dl_alerts import dl_user_ids_for_client

pytestmark = pytest.mark.asyncio


async def test_delivery_alert_recipients_honour_roles_access_and_client_scope():
    suffix = uuid.uuid4().hex[:8]
    user_ids: list[int] = []
    client_ids: list[int] = []

    try:
        async with AsyncSessionLocal() as db:
            primary_admin = User(
                email=f"delivery-alert-admin-{suffix}@example.com",
                password_hash="test-only",
                name="Primary admin",
                role=UserRole.admin,
                roles=[UserRole.admin.value],
                is_active=True,
            )
            secondary_admin = User(
                email=f"delivery-alert-secondary-admin-{suffix}@example.com",
                password_hash="test-only",
                name="Secondary admin",
                role=UserRole.recruiter,
                roles=[UserRole.recruiter.value, UserRole.admin.value],
                is_active=True,
            )
            assigned_dl = User(
                email=f"delivery-alert-dl-{suffix}@example.com",
                password_hash="test-only",
                name="Assigned DL",
                role=UserRole.delivery_lead,
                roles=[UserRole.delivery_lead.value],
                is_active=True,
            )
            denied_dl = User(
                email=f"delivery-alert-denied-dl-{suffix}@example.com",
                password_hash="test-only",
                name="Denied DL",
                role=UserRole.delivery_lead,
                roles=[UserRole.delivery_lead.value],
                is_active=True,
            )
            secondary_dl = User(
                email=f"delivery-alert-secondary-dl-{suffix}@example.com",
                password_hash="test-only",
                name="Secondary DL",
                role=UserRole.recruiter,
                roles=[UserRole.recruiter.value, UserRole.delivery_lead.value],
                is_active=True,
            )
            unassigned_dl = User(
                email=f"delivery-alert-unassigned-dl-{suffix}@example.com",
                password_hash="test-only",
                name="Unassigned DL",
                role=UserRole.delivery_lead,
                roles=[UserRole.delivery_lead.value],
                is_active=True,
            )
            inactive_dl = User(
                email=f"delivery-alert-inactive-dl-{suffix}@example.com",
                password_hash="test-only",
                name="Inactive DL",
                role=UserRole.delivery_lead,
                roles=[UserRole.delivery_lead.value],
                is_active=False,
            )
            granted_recruiter = User(
                email=f"delivery-alert-recruiter-{suffix}@example.com",
                password_hash="test-only",
                name="Granted recruiter",
                role=UserRole.recruiter,
                roles=[UserRole.recruiter.value],
                is_active=True,
            )
            own_client = Client(name=f"Delivery alert own client {suffix}")
            other_client = Client(name=f"Delivery alert other client {suffix}")
            users = [
                primary_admin,
                secondary_admin,
                assigned_dl,
                denied_dl,
                secondary_dl,
                unassigned_dl,
                inactive_dl,
                granted_recruiter,
            ]
            db.add_all([*users, own_client, other_client])
            await db.flush()
            user_ids = [user.id for user in users]
            client_ids = [own_client.id, other_client.id]

            db.add_all(
                [
                    DeliveryLeadClientAssignment(
                        delivery_lead_user_id=user.id,
                        client_id=own_client.id,
                        is_head=False,
                    )
                    for user in (
                        assigned_dl,
                        denied_dl,
                        secondary_dl,
                        inactive_dl,
                        granted_recruiter,
                    )
                ]
            )
            db.add_all(
                [
                    UserSectionOverride(
                        user_id=assigned_dl.id,
                        section="delivery",
                        access="read",
                    ),
                    UserSectionOverride(
                        user_id=denied_dl.id,
                        section="delivery",
                        access="none",
                    ),
                    UserSectionOverride(
                        user_id=secondary_dl.id,
                        section="delivery",
                        access="write",
                    ),
                    UserSectionOverride(
                        user_id=unassigned_dl.id,
                        section="delivery",
                        access="write",
                    ),
                    UserSectionOverride(
                        user_id=inactive_dl.id,
                        section="delivery",
                        access="write",
                    ),
                    UserSectionOverride(
                        user_id=granted_recruiter.id,
                        section="delivery",
                        access="write",
                    ),
                ]
            )
            await db.commit()

        async with AsyncSessionLocal() as db:
            scope = await load_delivery_alert_recipient_scope(db)
            dl_alert_recipients = set(
                await dl_user_ids_for_client(db, client_ids[0], scope=scope)
            )

        own_recipients = set(scope.for_client(client_ids[0]))
        other_recipients = set(scope.for_client(client_ids[1]))

        assert primary_admin.id in own_recipients
        assert secondary_admin.id in own_recipients
        assert primary_admin.id in other_recipients
        assert secondary_admin.id in other_recipients
        assert assigned_dl.id in own_recipients
        assert secondary_dl.id in own_recipients
        assert assigned_dl.id not in other_recipients
        assert secondary_dl.id not in other_recipients
        assert denied_dl.id not in own_recipients
        assert unassigned_dl.id not in own_recipients
        assert inactive_dl.id not in own_recipients
        assert granted_recruiter.id not in own_recipients
        assert dl_alert_recipients == {assigned_dl.id, secondary_dl.id}
    finally:
        if user_ids or client_ids:
            async with AsyncSessionLocal() as db:
                if user_ids:
                    await db.execute(
                        UserSectionOverride.__table__.delete().where(
                            UserSectionOverride.user_id.in_(user_ids)
                        )
                    )
                    await db.execute(
                        DeliveryLeadClientAssignment.__table__.delete().where(
                            DeliveryLeadClientAssignment.delivery_lead_user_id.in_(
                                user_ids
                            )
                        )
                    )
                if client_ids:
                    await db.execute(
                        Client.__table__.delete().where(Client.id.in_(client_ids))
                    )
                if user_ids:
                    await db.execute(
                        User.__table__.delete().where(User.id.in_(user_ids))
                    )
                await db.commit()
