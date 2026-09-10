"""Shared Champion intake, draft validation and operation-specific gates."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from copy import deepcopy
from datetime import datetime, timezone

from app.schemas.champion import ChampionProfile, migrate_legacy_champion_shape
from app.services.champion_document import folded, meaningful, table_profile

logger = logging.getLogger(__name__)
POLICY_VERSION = 1
MAX_TEXT = 14_000
OPERATIONS = ["search", "handoff", "cv"]
SECTION_KEYS = (
    "basics",
    "search",
    "stack",
    "project",
    "screening_questions",
    "client",
    "documents",
)
RUBRICS = {
    "rate_value": "rate_budget_hourly",
    "onsite_days_per_week": "onsite_days_per_week",
    "work_mode": "remote_policy",
    "candidate_location_pref": "location",
}

STACK_COLUMNS = {"must": "must_skills", "nice": "nice_skills"}
SYNC_FIELDS = set(RUBRICS) | set(STACK_COLUMNS)


def content(profile):
    normalized = ChampionProfile.model_validate(profile or {}).model_dump(mode="json")
    return {k: normalized[k] for k in SECTION_KEYS}


def mode(value):
    text = folded(str(value or "")).strip()
    modes = {
        "zdalnie": ("zdal", "remote", "home office", "z domu"),
        "hybrydowo": ("hybryd", "hybrid"),
        "stacjonarnie": ("stacjon", "onsite", "on-site"),
    }
    hits = [name for name, aliases in modes.items() if any(a in text for a in aliases)]
    return hits[0] if len(hits) == 1 else None


def number(value, maximum, *, integer=False):
    if isinstance(value, bool):
        return None
    text = str(value).strip().replace(",", ".")
    if not re.fullmatch(r"\d+(?:\.\d+)?", text):
        return None
    value = float(text)
    if not 0 <= value <= maximum or (integer and not value.is_integer()):
        return None
    return int(value) if integer else value


def rate(value):
    text = re.sub(r"\s*(?:PLN|zł)\s*/\s*(?:h|godz\.?)\s*$", "", str(value), flags=re.I)
    result = number(text, 2000)
    return result if result and result > 0 else None


def date(value):
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(value).strip(), fmt).date().isoformat()
        except ValueError:
            pass
    return None


def split_skills(value):
    from app.services.champion_document import _split_skills

    if isinstance(value, str):
        value = _split_skills(value)
    out, dropped = [], []
    for item in value or []:
        text = str(item.get("name", "") if isinstance(item, dict) else item).strip()
        if not meaningful(text) or len(text) > 120 or len(text.split()) > 12:
            if text:
                dropped.append(text)
        elif text.casefold() not in {s["name"].casefold() for s in out}:
            out.append({"name": text})
    return out, dropped


def prepare_profile(data, *, actor_id=None, template_version=None, raw_fields=None):
    """Store unresolved input alongside null/empty canonical values, not guesses."""
    data = deepcopy(data or {})
    old_meta = data.get("intake") or {}
    unresolved = dict(old_meta.get("unresolved") or {})
    basics = data.setdefault("basics", {})
    raw_fields = raw_fields or {}
    normalizers = {
        "rate_value": rate,
        "seniority_min_years": lambda v: number(v, 60, integer=True),
        "onsite_days_per_week": lambda v: number(v, 7, integer=True),
        "work_mode": mode,
        "start_date": date,
        "deadline": date,
    }
    for key, normalize in normalizers.items():
        path = f"basics.{key}"
        value = raw_fields.get(path, basics.get(key))
        if key == "rate_value" and basics.get("rate_raw") and path not in raw_fields:
            # Never trust an AI-chosen number if the source was a range/unit mismatch.
            value = basics["rate_raw"]
        if value in (None, ""):
            basics[key] = None
            continue
        result = normalize(value)
        if result is None:
            unresolved[path] = str(value)
        else:
            unresolved.pop(path, None)
        basics[key] = result
        if key == "rate_value":
            basics["rate_raw"] = str(value) if len(str(value)) <= 255 else None
    for key in ("role_name", "candidate_location_pref", "language", "contract_length"):
        value = basics.get(key)
        if value and not meaningful(value):
            unresolved[f"basics.{key}"] = str(value)
            basics[key] = None
        elif value:
            unresolved.pop(f"basics.{key}", None)
    stack = data.setdefault("stack", {})
    for key in ("must", "nice"):
        values, dropped = split_skills(stack.get(key))
        stack[key] = values
        path = f"stack.{key}"
        if dropped:
            unresolved[path] = "\n".join(dropped)
        elif values:
            unresolved.pop(path, None)
    search = data.setdefault("search", {})
    if isinstance(search.get("disqualifiers"), str):
        search["disqualifiers"] = [
            x.strip() for x in search["disqualifiers"].splitlines() if meaningful(x)
        ]
    questions = []
    for q in data.get("screening_questions") or []:
        if isinstance(q, dict) and meaningful(q.get("question")):
            questions.append({**q, "id": str(q.get("id") or f"q{len(questions) + 1}")})
    data["screening_questions"] = questions
    for section in ("project", "client"):
        for key, value in list(data.setdefault(section, {}).items()):
            if isinstance(value, str) and not meaningful(value):
                data[section][key] = ""
    for key, limit in {
        "role_name": 255,
        "candidate_location_pref": 255,
        "language": 50,
        "contract_length": 255,
    }.items():
        if basics.get(key) and len(str(basics[key])) > limit:
            unresolved[f"basics.{key}"] = str(basics[key])
            basics[key] = None
    data["intake"] = {
        "policy_version": POLICY_VERSION,
        "template_version": template_version or old_meta.get("template_version"),
        "unresolved": unresolved,
        "applied_by": actor_id,
        "applied_at": datetime.now(timezone.utc).isoformat(),
    }
    return ChampionProfile.model_validate(data).model_dump(mode="json")


def validation(profile, job=None, *, enforce=False):
    from pydantic import ValidationError

    try:
        cp = ChampionProfile.model_validate(profile or {}).model_dump(mode="json")
    except ValidationError:
        cp = prepare_profile(profile)
    meta = cp.get("intake") or {}
    active = (
        enforce
        or ((profile or {}).get("intake") or {}).get("policy_version") == POLICY_VERSION
    )
    if active:
        cp = prepare_profile(cp)
        meta = cp.get("intake") or {}
    issues = []

    def add(code, path, message, operations=OPERATIONS, source=None, warning=False):
        issues.append(
            {
                "code": code,
                "path": path,
                "message": message,
                "severity": "warning" if warning or not active else "error",
                "blocked_operations": list(operations)
                if active and not warning
                else [],
                "source": source,
            }
        )

    basics, stack = cp["basics"], cp["stack"]
    for path, source in (meta.get("unresolved") or {}).items():
        ops = (
            ["search", "handoff"]
            if path
            in (
                "basics.rate_value",
                "basics.work_mode",
                "basics.onsite_days_per_week",
                "basics.candidate_location_pref",
            )
            else OPERATIONS
        )
        add(
            "unresolved_value",
            path,
            "Popraw niejednoznaczny wpis lub jawnie wyczyść pole.",
            ops,
            source,
            warning=path == "stack.nice",
        )
    if not meaningful(basics.get("role_name") or getattr(job, "title", None)):
        add("missing_role", "basics.role_name", "Uzupełnij nazwę roli.")
    if not any(meaningful(cp["project"].get(k)) for k in ("about", "responsibilities")):
        add(
            "missing_context",
            "project.about",
            "Uzupełnij kontekst projektu lub obowiązki.",
        )
    valid_q = [q for q in cp["screening_questions"] if meaningful(q.get("question"))]
    if len(valid_q) < 2:
        add(
            "missing_questions",
            "screening_questions",
            "Dodaj co najmniej dwa rzeczywiste pytania screeningowe.",
        )
    for i, q in enumerate(valid_q):
        if not meaningful(q.get("ideal_answer")):
            add(
                "missing_answer",
                f"screening_questions.{i}.ideal_answer",
                "Uzupełnij wskazówki oceny odpowiedzi.",
                warning=True,
            )
    names = [x["name"] for x in stack["must"]]
    if not names and not stack["nice"]:
        add("missing_requirements", "stack.must", "Uzupełnij wymagania roli.")
    if not names:
        add(
            "missing_must",
            "stack.must",
            "Uzupełnij rzeczywiste wymagania MUST lub uzgodnij proces z DL.",
            ["search", "handoff"],
        )
    elif active:
        from app.services.dealbreaker_filters import gate_eligible_must_skills

        if not gate_eligible_must_skills(names):
            add(
                "ineligible_must",
                "stack.must",
                "MUST nie zawiera wymagania obsługiwanego przez bramkę searchu.",
                ["search", "handoff"],
            )
    overlap = {x["name"].casefold() for x in stack["must"]} & {
        x["name"].casefold() for x in stack["nice"]
    }
    if overlap:
        add(
            "conflicting_priority",
            "stack.nice",
            "Ta sama umiejętność występuje w MUST i NICE.",
        )
    notes = " ".join([stack.get("notes", ""), cp["search"].get("notes", "")])
    alternatives = bool(
        re.search(r"wystarczy jedna z|\s(?:lub|albo|or)\s", notes, re.I)
    )
    if alternatives and not getattr(job, "requirements_reviewed", False):
        add(
            "review_alternatives",
            "stack.notes",
            "Sprawdź i zatwierdź alternatywy w wymaganiach rekrutacji.",
        )
    values = dict(basics)
    if job is not None:
        from app.services.skill_normalize import iter_skill_names

        for key, column in STACK_COLUMNS.items():
            declared = {
                name.casefold() for name in iter_skill_names(getattr(job, column, None))
            }
            requested = {item["name"].casefold() for item in stack[key]}
            if declared and declared != requested:
                add(
                    "skill_column_conflict",
                    f"stack.{key}",
                    "Profil i pola rekrutacji mają różne wymagania. Uzgodnij wybraną listę.",
                )
        if getattr(job, "client_id", None) is None:
            add(
                "missing_client", "client_id", "Wybierz klienta.", ["search", "handoff"]
            )
        for key, column in RUBRICS.items():
            column_value = getattr(job, column, None)
            if key == "candidate_location_pref":
                column_value = getattr(job, "office_location", None) or column_value
            if key == "work_mode":
                column_value = mode(getattr(column_value, "value", column_value))
            if column_value not in (None, ""):
                original = basics.get(key)
                if (
                    original not in (None, "")
                    and str(original).casefold() != str(column_value).casefold()
                    and original != column_value
                ):
                    add(
                        "column_conflict",
                        f"basics.{key}",
                        "Profil i pola rekrutacji mają różne wartości. Uzgodnij je.",
                        ["search", "handoff"],
                    )
                values[key] = column_value
    if rate(values.get("rate_value")) is None:
        add(
            "missing_budget",
            "basics.rate_value",
            "Podaj jedną dodatnią stawkę kandydata w PLN/h.",
            ["search", "handoff"],
        )
    work_mode = mode(values.get("work_mode"))
    if not work_mode:
        add(
            "missing_work_mode",
            "basics.work_mode",
            "Wybierz tryb pracy.",
            ["search", "handoff"],
        )
    days = values.get("onsite_days_per_week")
    if work_mode in ("hybrydowo", "stacjonarnie"):
        if days is None or days == 0:
            add(
                "missing_office_days",
                "basics.onsite_days_per_week",
                "Dla obecności w biurze podaj dodatnią liczbę dni.",
                ["search", "handoff"],
            )
        if not meaningful(values.get("candidate_location_pref")):
            add(
                "missing_office_city",
                "basics.candidate_location_pref",
                "Podaj miasto biura.",
                ["search", "handoff"],
            )
    if work_mode == "zdalnie" and days not in (None, 0):
        add(
            "conflicting_office_days",
            "basics.onsite_days_per_week",
            "Praca zdalna jest sprzeczna z wymaganymi dniami w biurze.",
            ["search", "handoff"],
        )
    city = str(values.get("candidate_location_pref") or "")
    if re.search(r"[,;/]|\s(?:lub|albo)\s", city, re.I):
        add(
            "ambiguous_office",
            "basics.candidate_location_pref",
            "Uzgodnij jednoznaczną lokalizację biura.",
            ["search", "handoff"],
        )
    start, deadline = date(basics.get("start_date")), date(basics.get("deadline"))
    if start and deadline and deadline > start:
        add(
            "date_order",
            "basics.deadline",
            "Termin na kandydatów jest późniejszy niż start. Potwierdź poprawne daty.",
        )
    if len(re.split(r"(?<=[.!?])\s+", cp["project"]["about"].strip())) > 2:
        add(
            "long_project",
            "project.about",
            "Opis projektu ma więcej niż dwa zdania; uporządkuj go. Tekst został zachowany.",
            warning=True,
        )
    return {
        "policy_version": POLICY_VERSION if active else None,
        "status": "draft" if any(i["severity"] == "error" for i in issues) else "ready",
        "issues": issues,
        "blocked_operations": sorted(
            {o for i in issues for o in i["blocked_operations"]}
        ),
    }


def enforce_operation(job, operation, *, force=False):
    from fastapi import HTTPException

    cp = getattr(job, "champion_profile", None)
    if not cp:
        return
    result = validation(cp, job, enforce=force)
    if operation in result["blocked_operations"]:
        logger.info(
            "champion_validation_blocked operation=%s codes=%s",
            operation,
            [
                i["code"]
                for i in result["issues"]
                if operation in i["blocked_operations"]
            ],
        )
        raise HTTPException(
            422,
            {
                "message": "Profil Championa wymaga poprawy przed użyciem.",
                "validation": result,
            },
        )


def fingerprint(job):
    state = {
        "profile": getattr(job, "champion_profile", None),
        "title": getattr(job, "title", None),
        "client_id": getattr(job, "client_id", None),
        "requirements": getattr(job, "matching_requirements", None),
        "reviewed": getattr(job, "requirements_reviewed", None),
        "office_location": getattr(job, "office_location", None),
    }
    state.update(
        {
            column: getattr(job, column, None)
            for column in [*RUBRICS.values(), *STACK_COLUMNS.values()]
        }
    )
    return hashlib.sha256(
        json.dumps(state, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def response_context(job):
    from app.services.skill_normalize import iter_skill_names

    return {
        "validation": validation(job.champion_profile, job),
        "fingerprint": fingerprint(job),
        "job_values": {
            **{key: getattr(job, column, None) for key, column in RUBRICS.items()},
            **{
                key: "\n".join(iter_skill_names(getattr(job, column, None)))
                for key, column in STACK_COLUMNS.items()
            },
        },
    }


async def preview_document(data, filename, *, db=None):
    from app.services.champion_profile_ingest import (
        extract_document_text,
        parse_champion_document,
    )

    from fastapi.concurrency import run_in_threadpool

    text = await run_in_threadpool(extract_document_text, data, filename)
    if not text:
        raise ValueError("Nie odczytano tekstu dokumentu.")
    if len(text) > MAX_TEXT:
        raise ValueError(
            f"Dokument przekracza limit {MAX_TEXT} znaków. Skróć treść; niczego nie zaimportowano."
        )
    structured = (
        await run_in_threadpool(table_profile, data)
        if filename.lower().endswith(".docx")
        else None
    )
    if structured:
        cp = prepare_profile(
            structured["profile"],
            raw_fields=structured["raw_fields"],
            template_version=structured["template_version"],
        )
    else:
        if db is None:
            parsed = await parse_champion_document(text)
        else:
            from app.models.ai_feature import AIFeatureKey
            from app.services.ai_quota import ai_feature

            async with ai_feature(db, AIFeatureKey.champion_profile_parse):
                parsed = await parse_champion_document(text)
        from app.services.champion_profile_ingest import build_champion_dict

        cp = prepare_profile(build_champion_dict(parsed, file_id=None))
    from app.services.champion_profile_ingest import PARSER_VERSION

    cp["_parser"] = PARSER_VERSION
    cp["_source"] = "champion_upload"
    return {
        "champion_profile": cp,
        "validation": validation(cp),
        "must_skills": [s["name"] for s in cp["stack"]["must"]],
        "nice_skills": [s["name"] for s in cp["stack"]["nice"]],
        "summary": {
            "role_name": cp["basics"]["role_name"],
            "must_count": len(cp["stack"]["must"]),
            "nice_count": len(cp["stack"]["nice"]),
            "rate_value": cp["basics"]["rate_value"],
            "location": cp["basics"]["candidate_location_pref"],
            "work_mode": cp["basics"]["work_mode"],
            "onsite_days_per_week": cp["basics"]["onsite_days_per_week"],
        },
    }


def user_edit(old, patch, actor_id, *, imported=False):
    normalized = ChampionProfile.model_validate(old or {}).model_dump(mode="json")
    patch = migrate_legacy_champion_shape(patch)
    merged = deepcopy(normalized)
    for key in SECTION_KEYS:
        if key in patch:
            merged[key] = (
                {**merged[key], **patch[key]}
                if isinstance(merged[key], dict) and isinstance(patch[key], dict)
                else patch[key]
            )
    changed = any(merged[k] != normalized[k] for k in SECTION_KEYS)
    if not changed and not imported and old:
        return normalized
    if imported:
        from app.services.champion_profile_ingest import PARSER_VERSION

        merged["_source"] = "champion_upload"
        merged["_parser"] = PARSER_VERSION
        merged["intake"] = {
            "unresolved": (patch.get("intake") or {}).get("unresolved", {}),
            "template_version": (patch.get("intake") or {}).get("template_version"),
        }
    else:
        unresolved = dict((normalized.get("intake") or {}).get("unresolved", {}))
        for section, fields in patch.items():
            if isinstance(fields, dict):
                for key, value in fields.items():
                    if value != (normalized.get(section) or {}).get(key):
                        unresolved.pop(f"{section}.{key}", None)
        merged["intake"] = {
            **(normalized.get("intake") or {}),
            "unresolved": unresolved,
        }
    if (
        "rate_value" in patch.get("basics", {})
        and patch["basics"]["rate_value"] != normalized["basics"]["rate_value"]
    ):
        merged["basics"]["rate_raw"] = None
    return prepare_profile(merged, actor_id=actor_id)


def sync_selected_rubrics(job, profile, fields):
    from app.services.champion_job_sync import champion_work_mode_to_remote
    from app.services.requirement_contract import apply_requirement_source_update

    for key in fields:
        if key in STACK_COLUMNS:
            sync_skill_column(
                job,
                key,
                [
                    {"name": item["name"], "level": None}
                    for item in profile["stack"][key]
                ],
            )
            continue
        if key not in RUBRICS:
            raise ValueError("Nieznane pole uzgodnienia rekrutacji.")
        value = profile["basics"].get(key)
        if key == "work_mode":
            value = champion_work_mode_to_remote(value)
        apply_requirement_source_update(job, RUBRICS[key], value)


def sync_skill_column(job, key, items):
    from app.services.skill_normalize import iter_skill_names
    from app.services.requirement_contract import apply_requirement_source_update

    column = STACK_COLUMNS[key]
    current = getattr(job, column, None)
    if {name.casefold() for name in iter_skill_names(current)} == {
        item["name"].casefold() for item in items
    }:
        return
    apply_requirement_source_update(job, column, items)
