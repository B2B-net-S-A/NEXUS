"""Client-scoped order-number matching for Finance imports.

Finance worksheets carry the numeric SAP order identifier in ``Uwagi``.
Polkomtel stores the same identifier with the literal ``SAP`` prefix on the
order group.  The generic matcher must stay exact: BIK, BNP and every other
client keep their existing identifiers and must not inherit a broad
"digits-only" normalization.
"""

from __future__ import annotations

import re
from collections.abc import Iterable


# Canonical production client pinned by the order-type policy and the
# Polkomtel import completion report.  Tests move this gate to their freshly
# seeded client; matching by name is deliberately forbidden because Traffit
# can update client names.
POLKOMTEL_CLIENT_ID = 15

# Only the documented Polkomtel representation is normalized.  In particular,
# an arbitrary identifier containing digits (``PO-123`` / ``123/2026``) is not
# collapsed to those digits, which would create cross-client false matches.
_POLKOMTEL_SAP_ORDER_RE = re.compile(r"^SAP[\s:-]*(\d+)$", re.IGNORECASE)


def polkomtel_numeric_order_number(
    client_id: int | None, order_number: str | None
) -> str | None:
    """Return the numeric suffix of a canonical Polkomtel ``SAP`` number.

    ``None`` means "do not normalize".  The full-string regex is intentional:
    partial or compound numbers fail closed instead of being guessed.
    """

    if client_id != POLKOMTEL_CLIENT_ID or order_number is None:
        return None
    match = _POLKOMTEL_SAP_ORDER_RE.fullmatch(str(order_number).strip())
    return match.group(1) if match else None


def finance_order_number_matches(
    *,
    client_id: int | None,
    order_number: str | None,
    numeric_hints: Iterable[str],
) -> bool:
    """Match a stored order number against numeric hints from Finance.

    Existing exact behaviour is preserved first.  The sole extra equivalence
    is ``SAP 1234567`` <-> ``1234567`` for canonical Polkomtel.
    """

    if order_number is None:
        return False
    hints = frozenset(str(hint).strip() for hint in numeric_hints if str(hint).strip())
    stored = str(order_number).strip()
    if stored in hints:
        return True
    numeric = polkomtel_numeric_order_number(client_id, stored)
    return numeric is not None and numeric in hints
