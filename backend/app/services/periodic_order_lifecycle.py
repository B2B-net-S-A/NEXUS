"""Writer-time lifecycle for standalone periodic orders.

Draft completeness and explicit operator decisions belong to the caller.
MD/cost orders and group lines have their own budget-based lifecycle.
"""

from datetime import date

from app.core.scheduling import business_today
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.order_type import OrderType
from app.services.order_types import effective_standalone_order_type


def refresh_periodic_order_status(
    order: ClientOrder, *, today: date | None = None
) -> bool:
    """Reconcile an eligible period write; return whether the status changed.

    Future orders retain the existing ``active`` representation; their start
    date controls placement in the upcoming timeline. Both bounds are inclusive.
    Call only on creation/activation or an actual period change, never on a
    metadata-only write or a PATCH carrying an explicit status.
    """
    if (
        order.order_group_id is not None
        or effective_standalone_order_type(order.client_id, order.order_type)
        != OrderType.periodic
        or order.status not in (ClientOrderStatus.active, ClientOrderStatus.completed)
    ):
        return False
    boundary = today or business_today()
    if order.end_date is not None and order.end_date < boundary:
        target = ClientOrderStatus.completed
    elif order.start_date is not None:
        target = ClientOrderStatus.active
    else:
        # Missing start is not evidence for reviving a historical order.
        return False
    if order.status == target:
        return False
    order.status = target
    return True
