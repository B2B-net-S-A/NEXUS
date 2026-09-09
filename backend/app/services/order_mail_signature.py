"""Complete email order drafts when the contractor agreement is signed."""

from sqlalchemy import select, or_, func
from app.models.contract import Contract, ContractStatus
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.document_signature import DocumentSignature, SignatureStatus
from app.models.order_mail import OrderMailDocument
from app.models.activity import Activity
from app.services.contract_rates import RATE_SCHEDULE_LOADS, effective_rate_fields
from app.core.scheduling import business_today
from app.services.order_rate_snapshots import convert_order_rate


async def can_activate_mail_order(db, contract):
    if contract.status in (
        ContractStatus.active,
        ContractStatus.ending,
        ContractStatus.ended,
    ):
        return True
    generated = await db.scalar(
        select(B2BGeneratedContract.id)
        .where(
            B2BGeneratedContract.contract_id == contract.id,
            B2BGeneratedContract.signature_status == "signed_both",
        )
        .limit(1)
    )
    signature = await db.scalar(
        select(DocumentSignature.id)
        .where(
            DocumentSignature.contract_id == contract.id,
            DocumentSignature.status == SignatureStatus.completed,
        )
        .limit(1)
    )
    return bool(generated or signature)


async def complete_signed_mail_drafts(db, contract_id, *, actor_id=None):
    from app.api.client_orders import (
        _activate_complete_draft,
        _materialize_group_after_activation,
    )
    from app.services.contract_lifecycle import sync_contract_to_live_order

    contract = await db.scalar(
        select(Contract)
        .where(Contract.id == contract_id)
        .options(*RATE_SCHEDULE_LOADS)
        .execution_options(populate_existing=True)
    )
    if not contract or not await can_activate_mail_order(db, contract):
        return 0
    orders = (
        await db.scalars(
            select(ClientOrder)
            .where(
                ClientOrder.contract_id == contract_id,
                ClientOrder.status == ClientOrderStatus.draft,
                # Persisted source link covers updated recruitment drafts as well.
                select(OrderMailDocument.id)
                .where(
                    or_(
                        OrderMailDocument.applied_order_id == ClientOrder.id,
                        OrderMailDocument.proposal["apply_result"]["rows"].contains(
                            func.jsonb_build_array(
                                func.jsonb_build_object("order_id", ClientOrder.id)
                            )
                        ),
                    ),
                )
                .exists(),
            )
            .with_for_update()
        )
    ).all()
    changed = 0
    for order in orders:
        effective = effective_rate_fields(
            contract, order.start_date or business_today()
        )
        if effective.get("rate_candidate") is None:
            continue
        order.contract = contract
        order.rate_candidate = convert_order_rate(
            effective["rate_candidate"],
            contract.rate_unit,
            order.rate_unit,
            order.billing_hours_per_month,
        )
        order.rate_candidate_currency = effective.get("rate_candidate_currency")
        if _activate_complete_draft(order):
            await _materialize_group_after_activation(db, order, actor_id=actor_id)
            await sync_contract_to_live_order(
                db,
                contract,
                order_start=order.start_date,
                order_end=order.end_date,
                actor_id=actor_id,
            )
            db.add(
                Activity(
                    entity_type="client_order",
                    entity_id=order.id,
                    action="activated_after_signature",
                    user_id=actor_id,
                    details={"contract_id": contract_id},
                )
            )
            changed += 1
    return changed
