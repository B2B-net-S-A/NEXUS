"""Pure functions: Traffit payload → Nexus column dict.

Tests in tests/test_traffit_mappers.py use anonymized fixtures from
tests/fixtures/traffit/ (anonymized in Faza 0).

Discovery findings (docs/traffit-discovery.md):
- No `guid` in regular responses → external_id = str(id) (int).
- `clients` shape is sparse: only id, name, status — phone/email/website
  uzupełnia Artur ręcznie po imporcie.
- `crm_persons` shape: id, name, lastname, email, status, client.id +
  timestamps. No phone/position/department in this tenant.
- `client.status` is free text PL/EN — normalizujemy na enum.
"""

from __future__ import annotations

from typing import Any, Optional

# Status mapping for Traffit `client.status` (free text) → Nexus ClientStatus enum.
# Lower-cased keys; values match Nexus enum values.
_CLIENT_STATUS_MAP: dict[str, str] = {
    "aktywny": "active",
    "active": "active",
    "nieaktywny": "inactive",
    "inactive": "inactive",
    "prospekt": "prospect",
    "prospect": "prospect",
    "lead": "prospect",
}


def normalize_client_status(raw: Optional[str]) -> str:
    """Map Traffit `status` text → Nexus `ClientStatus` enum value.

    Returns 'active' as fallback (with a notes hint on raw value via mapper).
    """
    if not raw:
        return "active"
    key = raw.strip().lower()
    return _CLIENT_STATUS_MAP.get(key, "active")


def traffit_client_to_nexus(payload: dict[str, Any]) -> dict[str, Any]:
    """Map Traffit client → Nexus `clients` UPSERT dict.

    Required: id, name. Other fields fall back gracefully.
    """
    traffit_id = payload.get("id")
    if traffit_id is None:
        raise ValueError("Traffit client missing 'id'")

    raw_name = (payload.get("name") or "").strip()
    name = raw_name or f"Klient bez nazwy #{traffit_id}"
    raw_status = payload.get("status")

    return {
        "external_id": str(traffit_id),
        "external_source": "traffit",
        "name": name[:255],
        "status": normalize_client_status(raw_status),
        # Pola których Traffit b2bnetwork nie eksponuje — uzupełnia Artur ręcznie:
        # industry, website, address, contact_*, legal_name, nip, regon, nda_signed.
        # Trzymamy raw status w notes jako audit trail jeśli różny od mapped.
        "notes": (
            f"[traffit] status: {raw_status}"
            if raw_status
            and raw_status.strip().lower() not in _CLIENT_STATUS_MAP
            else None
        ),
    }


def _pick_nonempty(*values: Any) -> Optional[str]:
    """Return first non-empty stringified value, or None."""
    for v in values:
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return None


def traffit_crm_person_to_nexus(
    payload: dict[str, Any],
    client_external_id_to_nexus_id: dict[str, int],
    orphan_client_nexus_id: int,
) -> dict[str, Any]:
    """Map Traffit crm_person → Nexus `contacts` UPSERT dict.

    Lookup `client.id` (Traffit) → Nexus `client_id` via external_id map.
    Orphans (no client or unknown) land in `orphan_client_nexus_id`.

    Required: id. Name fallback: email-localpart, then '?'.
    """
    traffit_id = payload.get("id")
    if traffit_id is None:
        raise ValueError("Traffit crm_person missing 'id'")

    raw_first = (payload.get("name") or "").strip()
    raw_last = (payload.get("lastname") or "").strip()
    full_name = " ".join(p for p in (raw_first, raw_last) if p).strip()
    if not full_name:
        email = payload.get("email") or ""
        if "@" in email:
            full_name = email.split("@", 1)[0]
    if not full_name:
        full_name = "?"

    # Lookup client
    client_obj = payload.get("client") or {}
    traffit_client_id = client_obj.get("id") if isinstance(client_obj, dict) else None
    nexus_client_id: int
    if traffit_client_id is not None:
        key = str(traffit_client_id)
        nexus_client_id = client_external_id_to_nexus_id.get(
            key, orphan_client_nexus_id
        )
    else:
        nexus_client_id = orphan_client_nexus_id

    return {
        "external_id": str(traffit_id),
        "external_source": "traffit",
        "client_id": nexus_client_id,
        "name": full_name[:255],
        "email": _pick_nonempty(payload.get("email")),
        "phone": _pick_nonempty(payload.get("phone"), payload.get("mobile")),
        "position": _pick_nonempty(
            payload.get("position"), payload.get("job_title")
        ),
        "department": _pick_nonempty(payload.get("department")),
        "is_decision_maker": bool(payload.get("is_decision_maker") or False),
        "notes": _pick_nonempty(payload.get("notes")),
    }
