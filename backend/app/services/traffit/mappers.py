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

import re
from datetime import date, datetime, timezone
from typing import Any, Optional

# Legacy Traffit hack: recruiters flagged placed consultants by stuffing
# "[zatrudniony]" into the candidate's name/lastname, because Traffit had no
# employment status field. Nexus derives employment properly (active contract /
# `current_employment` conflict / `hired` pipeline stage — see
# app/api/candidates.py::_derive_employment), so the marker is pure noise that
# also breaks name search and CV headers. Strip it on every import so the daily
# sync never re-introduces it (the candidate UPSERT overwrites name/lastname
# from the payload). Matches bracketed / parenthesized / bare forms, any case,
# with adjacent separators; the suffix list covers Polish declensions without
# greedily eating a glued surname.
_EMPLOYMENT_MARKER_RE = re.compile(
    # Multi-char endings first: alternation is ordered, so a bare "e" must not
    # win over "ego"/"ej" and leave a dangling suffix. Plain capturing group
    # (not `(?:...)`) to stay byte-identical with migration 0165's _MARKER,
    # where `(?:` would trip SQLAlchemy text() bind-param parsing.
    r"[\[(]?\s*zatrudnion(ego|ej|ych|ymi|[yaieą])?\s*[\])]?",
    re.IGNORECASE,
)


def strip_employment_marker(value: str) -> str:
    """Remove the legacy ``[zatrudniony]`` employment tag from a name string.

    Returns the input unchanged when no marker is present. Collapses the
    whitespace left behind and trims dangling separators, so
    ``"Kowalski - zatrudniony"`` → ``"Kowalski"`` and
    ``"[ZATRUDNIONY] Jan"`` → ``"Jan"``. May return ``""`` when the field held
    nothing but the marker — callers apply their own empty-name fallback.
    """
    if not value or "zatrudnion" not in value.lower():
        return value
    cleaned = _EMPLOYMENT_MARKER_RE.sub(" ", value)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip(" -–,;")


def _parse_traffit_datetime(value: Any) -> Optional[datetime]:
    """Parse Traffit datetime strings ('yyyy-MM-dd HH:mm:ss' or ISO) to
    timezone-aware UTC datetime. Returns None if value is None/empty/invalid.
    asyncpg requires aware datetime for `timestamp with time zone` columns.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    try:
        # fromisoformat accepts both 'YYYY-MM-DD HH:MM:SS' and 'YYYY-MM-DDTHH:MM:SS'
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


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
            if raw_status and raw_status.strip().lower() not in _CLIENT_STATUS_MAP
            else None
        ),
    }


def _trunc(value: Optional[str], maxlen: int) -> Optional[str]:
    """Truncate string to fit a varchar(N) column. Pass-through for None."""
    if value is None:
        return None
    return value[:maxlen]


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
        "position": _pick_nonempty(payload.get("position"), payload.get("job_title")),
        "department": _pick_nonempty(payload.get("department")),
        "is_decision_maker": bool(payload.get("is_decision_maker") or False),
        "notes": _pick_nonempty(payload.get("notes")),
    }


# ── Faza 5: workflow → pipeline_template + stage_defs ───────────────────────

# Mapowanie Traffit state.type → (Nexus PipelineStage enum, category, terminal flag).
# Discovery (workflow B2B): start, screening, initial_accept, technical_verification,
# task, client_verification, interview, end-good, end-bad, wait.
# Plus `is_rejection: true` na state → wymusza terminal=rejected niezależnie od type.
_TRAFFIT_STATE_TYPE_MAP: dict[str, dict[str, Any]] = {
    "start": {"legacy": "new", "category": "internal", "is_terminal": False},
    "screening": {
        "legacy": "screening",
        "category": "internal",
        "is_terminal": False,
    },
    "initial_accept": {
        "legacy": "verified",
        "category": "internal",
        "is_terminal": False,
    },
    "technical_verification": {
        "legacy": "interview",
        "category": "internal",
        "is_terminal": False,
    },
    "task": {"legacy": "screening", "category": "internal", "is_terminal": False},
    "client_verification": {
        "legacy": "cv_sent",
        "category": "external",
        "is_terminal": False,
    },
    "interview": {
        "legacy": "interview",
        "category": "internal",
        "is_terminal": False,
    },
    "end-good": {
        "legacy": "hired",
        "category": "terminal",
        "is_terminal": True,
        "terminal_type": "hired",
    },
    "end-bad": {
        "legacy": "rejected",
        "category": "terminal",
        "is_terminal": True,
        "terminal_type": "rejected",
    },
    "wait": {
        "legacy": "withdrawn",
        "category": "terminal",
        "is_terminal": True,
        "terminal_type": "withdrawn",
    },
}

# Default fallback dla nieznanych typów (rzadkie custom Traffit states).
_DEFAULT_STATE_MAPPING = {
    "legacy": "screening",
    "category": "internal",
    "is_terminal": False,
}


def map_traffit_state_to_pipeline(state: dict[str, Any]) -> dict[str, Any]:
    """Zwraca mapping z PipelineStageDef-friendly polami dla Traffit state.

    Honoruje state.is_rejection: true (override na terminal=rejected).
    """
    state_type = (state.get("type") or "").strip()
    is_rejection = bool(state.get("is_rejection") or False)

    base = dict(_TRAFFIT_STATE_TYPE_MAP.get(state_type, _DEFAULT_STATE_MAPPING))
    if is_rejection:
        base.update(
            {
                "legacy": "rejected",
                "category": "terminal",
                "is_terminal": True,
                "terminal_type": "rejected",
            }
        )
    return base


def traffit_workflow_to_template(payload: dict[str, Any]) -> dict[str, Any]:
    """Workflow Traffita → PipelineTemplate insert dict (bez stage_defs)."""
    workflow_id = payload.get("id")
    if workflow_id is None:
        raise ValueError("Traffit workflow missing 'id'")
    raw_name = (payload.get("name") or "").strip()
    name = raw_name or f"Traffit Workflow #{workflow_id}"
    return {
        "external_id": str(workflow_id),
        "external_source": "traffit",
        "name": name[:100],
        "description": f"Imported from Traffit (workflow_id={workflow_id})",
        "is_default": False,
    }


def traffit_workflow_state_to_stage_def(
    state: dict[str, Any], order_index: int
) -> dict[str, Any]:
    """Workflow state Traffita → PipelineStageDef insert dict.

    `order_index` jest pozycją w liście (po sortowaniu po `state.order`),
    nie raw `state.order` (który dla terminal states bywa 9999997+).
    """
    state_id = state.get("id")
    if state_id is None:
        raise ValueError("Traffit state missing 'id'")
    raw_name = (state.get("name") or "").strip()
    sid = (state.get("sid") or "").strip()
    name = raw_name or sid or f"Stan #{state_id}"

    mapping = map_traffit_state_to_pipeline(state)

    return {
        "traffit_state_id": str(state_id),
        "name": name[:100],
        "order": order_index,
        "category": mapping["category"],
        "is_terminal": mapping["is_terminal"],
        "terminal_type": mapping.get("terminal_type"),
        "legacy_enum_value": mapping["legacy"],
    }


# ── Faza 5: employee → candidate ────────────────────────────────────────────

# Mapping Traffit `status` text → Nexus CandidateStatus enum.
_CANDIDATE_STATUS_MAP: dict[str, str] = {
    "active": "active",
    "aktywny": "active",
    "inactive": "passive",
    "nieaktywny": "passive",
    "passive": "passive",
    "blacklist": "blacklisted",
    "blacklisted": "blacklisted",
}


def normalize_candidate_status(raw: Optional[str]) -> str:
    if not raw:
        return "active"
    return _CANDIDATE_STATUS_MAP.get(raw.strip().lower(), "active")


# Custom fields Traffit (prefixowane `_`) trafiają do Candidate.cv_extracted_data
# pod kluczem `traffit_<original_key>` żeby nie kolidowały z naszymi polami.
_CUSTOM_FIELD_PREFIX = "_"


def traffit_employee_to_candidate(
    payload: dict[str, Any],
    user_id_map: Optional[dict[str, int]] = None,
) -> dict[str, Any]:
    """Map Traffit employee → Nexus `candidates` UPSERT dict.

    user_id_map: traffit_user_id (str) → nexus_user_id (int) dla mapowania
    `created_by`. None / brak → tracimy attribution (created_by=NULL).

    Custom fields prefixowane `_` (np. `_Position`, `_certificates`) trafiają
    do `cv_extracted_data` jako `traffit_<key>` — catch-all bez kolizji.

    Pliki CV są reprezentowane tylko jako `cv_filename` (nazwa pliku z
    pierwszego wpisu). Binary content pobiera importer osobno przez
    `/employees/{id}/files/{file_id}/content`.
    """
    traffit_id = payload.get("id")
    if traffit_id is None:
        raise ValueError("Traffit employee missing 'id'")

    name = strip_employment_marker((payload.get("name") or "").strip())
    lastname = strip_employment_marker((payload.get("lastname") or "").strip())
    if not name:
        email = payload.get("email") or ""
        if "@" in email:
            name = email.split("@", 1)[0]
        else:
            name = "?"
    if not lastname:
        lastname = "?"

    # Custom fields → cv_extracted_data
    custom: dict[str, Any] = {}
    for key, value in payload.items():
        if key.startswith(_CUSTOM_FIELD_PREFIX) and value is not None:
            clean_key = f"traffit{key}"  # _Position → traffit_Position
            custom[clean_key] = value

    files = payload.get("files") or []
    first_file = files[0] if isinstance(files, list) and files else None
    cv_filename = first_file.get("filename") if isinstance(first_file, dict) else None

    # created_by lookup
    created_by_nexus: Optional[int] = None
    if user_id_map:
        created_by_obj = payload.get("created_by") or {}
        if isinstance(created_by_obj, dict):
            traffit_user_id = created_by_obj.get("id")
            if traffit_user_id is not None:
                created_by_nexus = user_id_map.get(str(traffit_user_id))

    # candidate_languages może być stringiem lub listą — normalizujemy do listy
    raw_langs = payload.get("candidate_languages")
    if isinstance(raw_langs, str) and raw_langs.strip():
        languages: list[Any] = [{"lang": raw_langs.strip(), "level": None}]
    elif isinstance(raw_langs, list):
        languages = raw_langs
    else:
        languages = []

    return {
        "external_id": str(traffit_id),
        "external_source": "traffit",
        "name": name[:100],
        "lastname": lastname[:100],
        "email": _trunc(_pick_nonempty(payload.get("email")), 255),
        "phone": _trunc(
            _pick_nonempty(payload.get("mobile"), payload.get("phone")), 30
        ),
        "linkedin": _trunc(_pick_nonempty(payload.get("linkedin")), 500),
        "location": _trunc(_pick_nonempty(payload.get("candidate_location")), 255),
        "status": normalize_candidate_status(payload.get("status")),
        "ai_summary": _pick_nonempty(payload.get("candidate_about")),
        "languages": languages,
        "cv_filename": _trunc(cv_filename, 500),
        "cv_extracted_data": custom,
        "source": "traffit",
        "created_by": created_by_nexus,
    }


# ── Faza 5: recruitment → job ───────────────────────────────────────────────

_JOB_STATUS_MAP: dict[str, str] = {
    "active": "published",
    "open": "published",
    "otwarta": "published",
    "published": "published",
    "draft": "draft",
    "closed": "closed",
    "zamknieta": "closed",
    "zamknięta": "closed",
}


def normalize_job_status(raw: Optional[str], is_closed: bool = False) -> str:
    if is_closed:
        return "closed"
    if not raw:
        return "draft"
    return _JOB_STATUS_MAP.get(raw.strip().lower(), "draft")


def traffit_recruitment_to_job(
    payload: dict[str, Any],
    client_external_id_to_nexus_id: dict[str, int],
    workflow_external_id_to_template_id: dict[str, int],
    user_id_map: Optional[dict[str, int]] = None,
) -> dict[str, Any]:
    """Map Traffit recruitment → Nexus `jobs` UPSERT dict.

    Nexus_client_id może być None gdy klient jeszcze nie zmigrowany — importer
    decyduje czy skipować rekord, czy zostawić client_id=NULL.
    """
    traffit_id = payload.get("id")
    if traffit_id is None:
        raise ValueError("Traffit recruitment missing 'id'")

    raw_name = (payload.get("name") or "").strip()
    title = raw_name or f"Rekrutacja #{traffit_id}"

    client_obj = payload.get("client") or {}
    traffit_client_id = client_obj.get("id") if isinstance(client_obj, dict) else None
    nexus_client_id: Optional[int] = None
    if traffit_client_id is not None:
        nexus_client_id = client_external_id_to_nexus_id.get(str(traffit_client_id))

    workflow_id = payload.get("workflow_id")
    pipeline_template_id: Optional[int] = None
    if workflow_id is not None:
        pipeline_template_id = workflow_external_id_to_template_id.get(str(workflow_id))

    recruiter_id: Optional[int] = None
    if user_id_map:
        rp = payload.get("responsible_person")
        if isinstance(rp, dict):
            traffit_user_id = rp.get("id")
            if traffit_user_id is not None:
                recruiter_id = user_id_map.get(str(traffit_user_id))

    is_closed = bool(payload.get("is_closed") or False)
    closing_date = payload.get("closing_date")  # "yyyy-MM-dd HH:mm:ss" lub None

    deadline: Optional[date] = None
    if isinstance(closing_date, str) and closing_date.strip():
        # Take date portion (yyyy-MM-dd) and convert to datetime.date for asyncpg.
        try:
            deadline = date.fromisoformat(closing_date.split(" ")[0])
        except ValueError:
            deadline = None

    return {
        "external_id": str(traffit_id),
        "external_source": "traffit",
        "title": title[:255],
        "status": normalize_job_status(payload.get("status"), is_closed),
        "client_id": nexus_client_id,
        "pipeline_template_id": pipeline_template_id,
        "recruiter_id": recruiter_id,
        "reference_number": _pick_nonempty(payload.get("nrRef")),
        "deadline": deadline,
        "custom_fields": {
            "traffit_is_confidential": bool(payload.get("is_confidential") or False),
            "traffit_raw_status": payload.get("status"),
        },
    }


# ── Faza 5: talent → talent_pool ────────────────────────────────────────────


def traffit_talent_to_pool(
    payload: dict[str, Any],
    user_id_map: Optional[dict[str, int]] = None,
) -> dict[str, Any]:
    """Map Traffit talent → Nexus `talent_pools` UPSERT dict."""
    traffit_id = payload.get("id")
    if traffit_id is None:
        raise ValueError("Traffit talent missing 'id'")
    raw_name = (payload.get("name") or "").strip()
    name = raw_name or f"Pula #{traffit_id}"

    created_by_nexus: Optional[int] = None
    if user_id_map:
        created_by_obj = payload.get("created_by") or {}
        if isinstance(created_by_obj, dict):
            traffit_user_id = created_by_obj.get("id")
            if traffit_user_id is not None:
                created_by_nexus = user_id_map.get(str(traffit_user_id))

    return {
        "external_id": str(traffit_id),
        "external_source": "traffit",
        "name": name[:255],
        "description": _pick_nonempty(payload.get("description")),
        "created_by": created_by_nexus,
    }


# ── Faza 5b: recruitment_history → candidate_stages ─────────────────────────


def traffit_recruitment_history_to_stage(
    payload: dict[str, Any],
    employee_external_id_to_candidate_id: dict[str, int],
    recruitment_external_id_to_job_id: dict[str, int],
    state_external_id_to_stage_def_id: dict[str, int],
    state_external_id_to_legacy_enum: dict[str, str],
    user_id_map: Optional[dict[str, int]] = None,
) -> Optional[dict[str, Any]]:
    """Map Traffit recruitment_history record → Nexus `candidate_stages` UPSERT dict.

    Zwraca None jeśli employee/recruitment/state nie ma swojego odpowiednika
    w Nexusie (caller logguje jako skip).

    `traffit_history_id` jest niepowtarzalny per move (idempotent UPSERT).
    """
    history_id = payload.get("id")
    if history_id is None:
        raise ValueError("Traffit recruitment_history missing 'id'")

    employee = payload.get("employee") or {}
    recruitment = payload.get("recruitment") or {}
    workflow_state = payload.get("workflow_state") or {}

    emp_id = employee.get("id") if isinstance(employee, dict) else None
    rec_id = recruitment.get("id") if isinstance(recruitment, dict) else None
    state_id = workflow_state.get("id") if isinstance(workflow_state, dict) else None
    if emp_id is None or rec_id is None or state_id is None:
        return None

    candidate_id = employee_external_id_to_candidate_id.get(str(emp_id))
    job_id = recruitment_external_id_to_job_id.get(str(rec_id))
    stage_def_id = state_external_id_to_stage_def_id.get(str(state_id))
    legacy_enum = state_external_id_to_legacy_enum.get(str(state_id), "screening")

    if candidate_id is None or job_id is None:
        return None

    # moved_at = `date` (start) z payload Traffita.
    # Traffit zwraca string 'yyyy-MM-dd HH:mm:ss'; PG kolumna jest
    # timestamp with time zone, więc parsujemy do tz-aware datetime (UTC).
    moved_at = _parse_traffit_datetime(payload.get("date") or payload.get("created_at"))

    # moved_by — preferuj created_by, fallback updated_by
    moved_by_nexus: Optional[int] = None
    if user_id_map:
        for key in ("created_by", "updated_by"):
            obj = payload.get(key)
            if isinstance(obj, dict):
                tid = obj.get("id")
                if tid is not None:
                    moved_by_nexus = user_id_map.get(str(tid))
                    if moved_by_nexus is not None:
                        break

    return {
        "external_id": str(history_id),
        "external_source": "traffit",
        "candidate_id": candidate_id,
        "job_id": job_id,
        "stage_def_id": stage_def_id,  # może być None gdy stage nieobecny w template
        "stage_legacy_enum": legacy_enum,
        "moved_at": moved_at,
        "moved_by": moved_by_nexus,
    }


# ── Faza 5b: /employees/activities → activities ─────────────────────────────


def traffit_activity_to_activity(
    payload: dict[str, Any],
    employee_external_id_to_candidate_id: dict[str, int],
    user_id_map: Optional[dict[str, int]] = None,
) -> Optional[dict[str, Any]]:
    """Map Traffit activity → Nexus `activities` INSERT dict.

    Zwraca None gdy employee nie ma odpowiednika w Nexusie.

    Activity Nexusa ma {entity_type, entity_id, action, details, user_id}.
    Trzymamy raw Traffit type w details.traffit_type i full content w details.
    """
    activity_id = payload.get("id")
    if activity_id is None:
        raise ValueError("Traffit activity missing 'id'")

    employee = payload.get("employee") or {}
    emp_id = employee.get("id") if isinstance(employee, dict) else None
    # Activities lookup może być w globalnej liście — `employee` zwykle obecny.
    # Ale niektóre tenanty mogą nie mieć tego — wtedy skipujemy.
    if emp_id is None:
        return None

    candidate_id = employee_external_id_to_candidate_id.get(str(emp_id))
    if candidate_id is None:
        return None

    activity_type = payload.get("type") or {}
    type_value = activity_type.get("value") if isinstance(activity_type, dict) else None
    type_id = activity_type.get("id") if isinstance(activity_type, dict) else None

    action = f"traffit:{type_value or 'unknown'}"[:100]

    user_nexus: Optional[int] = None
    if user_id_map:
        cb = payload.get("created_by")
        if isinstance(cb, dict):
            tid = cb.get("id")
            if tid is not None:
                user_nexus = user_id_map.get(str(tid))

    # Preserve raw Traffit user IDs in details so a future re-attribute can
    # match without re-fetching the API. Used by Faza A backfill SQL when
    # `import_users` adds historic users that didn't exist at first import.
    created_by_id = (payload.get("created_by") or {}).get("id")
    updated_by_id = (payload.get("updated_by") or {}).get("id")

    return {
        "external_id": str(activity_id),
        "external_source": "traffit",
        "entity_type": "candidate",
        "entity_id": candidate_id,
        "action": action,
        "details": {
            "traffit_type_id": type_id,
            "traffit_type_value": type_value,
            "activity_date": payload.get("activity_date"),
            "content": payload.get("content"),
            "traffit_created_by_id": created_by_id,
            "traffit_updated_by_id": updated_by_id,
        },
        "user_id": user_nexus,
    }


# ── Faza 5b: /sources/ → candidate.tags entry ───────────────────────────────


def traffit_source_to_candidate_tag(
    payload: dict[str, Any],
    employee_external_id_to_candidate_id: dict[str, int],
) -> Optional[dict[str, Any]]:
    """Map Traffit source record → tag entry dla `candidate.tags` JSONB list.

    Zwraca dict {candidate_id, tag} gdzie tag = {"type": "traffit_source",
    "source_id", "value", "domain", "url"}. Caller append'uje do tags listy
    (z deduplication po source_id).

    Zwraca None gdy employee nie zmigrowany.
    """
    source_id = payload.get("id")
    if source_id is None:
        return None

    employee = payload.get("employee") or {}
    emp_id = employee.get("id") if isinstance(employee, dict) else None
    if emp_id is None:
        return None

    candidate_id = employee_external_id_to_candidate_id.get(str(emp_id))
    if candidate_id is None:
        return None

    dictionary = payload.get("dictionary_item") or {}
    value = dictionary.get("value") if isinstance(dictionary, dict) else None

    return {
        "candidate_id": candidate_id,
        "tag": {
            "type": "traffit_source",
            "source_id": source_id,
            "value": value,
            "domain": payload.get("domain"),
            "url": payload.get("url"),
        },
    }


# ── Faza 5b: pliki — wybór CV ───────────────────────────────────────────────


def select_primary_cv_file(files: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Wybierz najnowszy plik PDF/DOCX jako CV.

    Reguła: preferuj `.pdf` > `.docx` > `.doc` > inne. Wśród tej samej
    kategorii — pierwszy w liście (Traffit zwraca w order of upload).

    Zwraca {id, name} lub None.
    """
    if not files:
        return None
    by_priority = {".pdf": 0, ".docx": 1, ".doc": 2}

    def rank(f: dict[str, Any]) -> int:
        name = (f.get("name") or "").lower()
        for ext, prio in by_priority.items():
            if name.endswith(ext):
                return prio
        return 99

    # Items must have `id` to be downloadable
    candidates = [f for f in files if f.get("id") is not None]
    if not candidates:
        return None
    candidates.sort(key=rank)
    return candidates[0]


# ── Faza A: Traffit user → Nexus user backfill ──────────────────────────────


# Mapping permission_group.name → Nexus UserRole (lowercase value).
_TRAFFIT_GROUP_TO_ROLE: dict[str, str] = {
    "rekruterzy": "recruiter",
    "recruiters": "recruiter",
    "admin": "admin",
    "administrator": "admin",
    "administratorzy": "admin",
    "manager": "delivery_lead",
    "managers": "delivery_lead",
    "lead": "delivery_lead",
    "kierownicy": "delivery_lead",
    "delivery": "delivery_lead",
    "sourcer": "sourcer",
    "sourcerzy": "sourcer",
    "sourcing": "sourcer",
    "tac": "tac",
}


def normalize_traffit_role(group_name: Optional[str]) -> str:
    """Map Traffit permission_group.name → Nexus UserRole enum value.

    Default: 'recruiter' dla nierozpoznanych grup (większość historycznych
    Traffit userów to "Rekruterzy" zgodnie z probe API).
    """
    if not group_name:
        return "recruiter"
    key = group_name.strip().lower()
    if key in _TRAFFIT_GROUP_TO_ROLE:
        return _TRAFFIT_GROUP_TO_ROLE[key]
    # Substring match dla wariantów typu "Rekruterzy 2025"
    for keyword, role in _TRAFFIT_GROUP_TO_ROLE.items():
        if keyword in key:
            return role
    return "recruiter"


def traffit_user_to_nexus(payload: dict[str, Any]) -> dict[str, Any]:
    """Map Traffit user → Nexus `users` UPSERT dict.

    Required: id, email. Inne pola fallback gracefully:
    - name = "{name} {lastname}".strip() lub email-localpart
    - role = mapped from permission_group.name (default 'recruiter')
    - is_active = z payload (większość historycznych userów ma false)
    - password_hash = '!imported-from-traffit-no-login!' (bcrypt-invalid;
      konto jest disabled, login niemożliwy. Jeśli user wraca, admin musi
      ustawić nowe hasło ręcznie.)
    """
    traffit_id = payload.get("id")
    if traffit_id is None:
        raise ValueError("Traffit user missing 'id'")

    email = (payload.get("email") or payload.get("username") or "").strip().lower()
    if not email or "@" not in email:
        raise ValueError(f"Traffit user {traffit_id} missing or invalid email")

    raw_first = (payload.get("name") or "").strip()
    raw_last = (payload.get("lastname") or "").strip()
    full_name = " ".join(p for p in (raw_first, raw_last) if p).strip()
    if not full_name:
        # Fallback to email localpart (e.g. "jakub.petryna" → "Jakub Petryna")
        local = email.split("@", 1)[0]
        full_name = " ".join(
            part.capitalize() for part in local.replace(".", " ").split()
        )
    if not full_name:
        full_name = f"Traffit User #{traffit_id}"

    group = payload.get("permission_group") or {}
    group_name = group.get("name") if isinstance(group, dict) else None
    role = normalize_traffit_role(group_name)

    # is_active default False for safety (większość Traffit-imported userów
    # to historic accounts; admin może ich aktywować ręcznie po imporcie)
    is_active = bool(payload.get("is_active") or False)

    return {
        "external_id": str(traffit_id),
        "external_source": "traffit",
        "email": _trunc(email, 255),
        "name": _trunc(full_name, 255),
        "role": role,
        "is_active": is_active,
        # Bcrypt-invalid placeholder. Login attempt = bcrypt verify fails =>
        # nie ma sposobu na wejście do konta przez ten hash.
        "password_hash": "!imported-from-traffit-no-login!",
    }


def select_all_files_with_priority(
    files: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Sort wszystkie pliki kandydata po priorytecie pdf > docx > doc > inne;
    pierwszy element dostaje `is_primary=True`, pozostałe `False`.

    Używane przez Fazę A `import_candidate_files` żeby zaimportować WSZYSTKIE
    dokumenty (nie tylko primary CV). Zachowuje markowanie primary tak żeby
    zakładka "Pliki" w UI pokazała preferowany na górze listy.

    Zwraca listę dictów z dodatkowym kluczem `is_primary: bool`. Pliki bez
    `id` są skipowane (niemożliwe do pobrania binary).
    """
    if not files:
        return []
    by_priority = {".pdf": 0, ".docx": 1, ".doc": 2}

    def rank(f: dict[str, Any]) -> int:
        name = (f.get("name") or "").lower()
        for ext, prio in by_priority.items():
            if name.endswith(ext):
                return prio
        return 99

    candidates = [f for f in files if f.get("id") is not None]
    if not candidates:
        return []
    sorted_files = sorted(candidates, key=rank)
    result: list[dict[str, Any]] = []
    for i, f in enumerate(sorted_files):
        # Don't mutate input — return shallow-copied dict z is_primary marker
        result.append({**f, "is_primary": (i == 0)})
    return result
