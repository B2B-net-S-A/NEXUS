"""Shared Champion intake, draft validation and operation-specific gates."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from copy import deepcopy
from datetime import datetime, timezone

from app.schemas.champion import (
    STACK_ITEM_MAX_CHARS,
    ChampionProfile,
    migrate_legacy_champion_shape,
)
from app.services.champion_document import folded, meaningful, table_profile

logger = logging.getLogger(__name__)
POLICY_VERSION = 1
# Input limit of the AI parser (`parse_champion_document`), and ONLY of it: a
# longer text makes the model run out of output tokens and return a profile
# with silently missing sections. The Word form read from its tables involves
# no model, so it has no such limit.
MAX_TEXT = 14_000
OPERATIONS = ["search", "handoff", "cv"]


def gate_enabled() -> bool:
    """Whether Champion draft issues hard-block search/handoff/CV.

    Default OFF: issues are advisory only (pre-#1477 behavior). Flip
    CHAMPION_INTAKE_GATE_ENABLED=true in Coolify to re-enable blocking
    once the profiles have been cleaned up.
    """

    return os.getenv("CHAMPION_INTAKE_GATE_ENABLED", "false").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


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


# A document rate that is PLN per hour, written as one value or a range: the
# only text a parser's number may be checked against. Matched on the folded
# text (lower case, no diacritics, "zł" -> "zl").
_RATE_NUMBER = r"\d+(?:[.,]\d+)?"
_PLN_PER_HOUR = re.compile(
    r"(?:pln|zl(?:otych|oty|ote)?\.?)\s*(?:/|za|na|per)\s*(?:1\s*)?"
    r"(?:h|godz(?:ine|ina|\.)?|hour)(?![a-z])"
)
# Qualifiers that keep the value a net B2B hourly rate. "brutto" is NOT one:
# a gross figure is a different number than the budget it would be read as.
_NET_QUALIFIER = re.compile(r"(?<![a-z])(?:netto|net|\+\s*vat|b2b)(?![a-z])")
_RATE_SHAPES = (
    # "120–140", "od 120 do 140"
    (re.compile(rf"(?:od\s*)?({_RATE_NUMBER})\s*(?:-|do)\s*({_RATE_NUMBER})"), 2),
    # "do 140", "max. 140" — an upper bound: anything above zero up to it
    (re.compile(rf"(?:do|max\.?|maks\.?|maksymalnie|up\s+to)\s*({_RATE_NUMBER})"), 1),
    # "140", "ok. 140"
    (re.compile(rf"(?:ok\.?|okolo|~)?\s*({_RATE_NUMBER})"), 0),
)


def pln_hourly_bounds(value):
    """``(low, high)`` of a document rate written in PLN per hour, else None.

    Accepts one value, a range or an upper bound, optionally net of VAT
    ("120–140 zł/h", "do 140 PLN/h netto", "max. 140 zł/godz. + VAT"). Any
    other currency, a day/MD/month rate, a gross figure, a missing unit or
    extra words ("lub 1000 zł/MD", "do negocjacji") answer None: such a text
    cannot vouch for a PLN/h number, whatever the model put next to it.
    """
    # Typographic dashes and the minus sign are range separators too.
    text = re.sub(r"[\u2010-\u2015\u2212]", "-", folded(str(value or "")))
    if not _PLN_PER_HOUR.search(text):
        return None
    text = _NET_QUALIFIER.sub(" ", _PLN_PER_HOUR.sub(" ", text))
    text = re.sub(r"\(\s*\)", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .,;:")
    for pattern, kind in _RATE_SHAPES:
        match = pattern.fullmatch(text)
        if not match:
            continue
        values = [float(v.replace(",", ".")) for v in match.groups()]
        if kind == 2:
            low, high = values
        elif kind == 1:
            low, high = 0.0, values[0]
        else:
            low = high = values[0]
        return (low, high) if 0 <= low <= high else None
    return None


def date(value):
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(value).strip(), fmt).date().isoformat()
        except ValueError:
            pass
    return None


# A requirement longer than this reads like prose rather than a technology. It
# is KEPT (in the stack and in `jobs.must_skills`) and only flagged: until
# 09.2026 crossing either bound moved the entry to `intake.unresolved` and out
# of the requirement list, so scoring and the search lost a requirement the
# Delivery Lead had written down.
LONG_REQUIREMENT_WORDS = 12
LONG_REQUIREMENT_CHARS = 120

ADVISORY_ISSUES = {
    "basics.rate_value": (
        "rate_source_ambiguous",
        "Stawka w dokumencie jest zakresem lub ma dopisek (PLN/h). Zachowano "
        "liczbę z tego zakresu — sprawdź, czy to właściwa maksymalna stawka "
        "kandydata.",
    ),
    "stack.must": (
        "long_requirement",
        "Wymaganie zapisane jest opisowo. Zostało zachowane; rozważ skrócenie "
        "go do nazwy technologii.",
    ),
    "stack.nice": (
        "long_requirement",
        "Wymaganie zapisane jest opisowo. Zostało zachowane; rozważ skrócenie "
        "go do nazwy technologii.",
    ),
}


def split_skills(value, restored=()):
    """Split MUST/NICE input into stack entries without losing a requirement.

    Returns ``(items, placeholders, long_items, unstorable)``: every meaningful
    entry (deduplicated case-insensitively, in input order), the non-answers
    such as "brak"/"do ustalenia", the kept entries that read like prose
    (advisory only) and the entries too long to store as one item.
    ``restored`` are entries an earlier version of this function set aside in
    ``intake.unresolved``; they rejoin the list instead of staying lost there.
    """
    from app.services.champion_document import _split_skills

    if isinstance(value, str):
        value = _split_skills(value)
    items, placeholders, long_items, unstorable = [], [], [], []
    seen = set()
    for item in [*(value or []), *restored]:
        text = str(item.get("name", "") if isinstance(item, dict) else item).strip()
        if not text:
            continue
        if not meaningful(text):
            placeholders.append(text)
            continue
        if len(text) > STACK_ITEM_MAX_CHARS:
            unstorable.append(text)
            continue
        if text.casefold() in seen:
            continue
        seen.add(text.casefold())
        items.append({"name": text})
        if (
            len(text) > LONG_REQUIREMENT_CHARS
            or len(text.split()) > LONG_REQUIREMENT_WORDS
        ):
            long_items.append(text)
    return items, placeholders, long_items, unstorable


def _value_at(profile, path):
    section, _, key = path.partition(".")
    value = (profile or {}).get(section)
    if not key:
        return value
    return value.get(key) if isinstance(value, dict) else None


def _normalize_rate(basics, raw_fields, unresolved, advisory):
    """`rate_value` from the typed number or the document text.

    The document text (`rate_raw`) wins when it parses as one PLN/h value — it
    is the source the number was read from. When it does not, the number next
    to it (the AI parser's reading) is kept ONLY if the text is still PLN per
    hour and the number lies inside what it says ("120–140 zł/h", "do 140
    PLN/h netto"); the text is then recorded as advisory. Until 09.2026 such a
    range replaced the number and nulled it on every content-changing save.

    A text in any other unit ("45 EUR/h", "1200 PLN/MD", "20 000 PLN/mies.
    brutto") vouches for no number: it stays unresolved, the budget stays
    empty and validation reports `missing_budget`. A kept number would be
    copied into an empty `jobs.rate_budget_hourly` and read by scoring and the
    rate dealbreaker as the candidate's maximum PLN/h — even when the model
    converted the unit on its own.
    """
    path = "basics.rate_value"
    advisory.pop(path, None)
    raw = basics.get("rate_raw")
    value = raw_fields.get(path, basics.get("rate_value"))
    if raw and path not in raw_fields:
        current = rate(value) if value not in (None, "") else None
        bounds = pln_hourly_bounds(raw) if rate(raw) is None else None
        if current is not None and bounds and bounds[0] <= current <= bounds[1]:
            basics["rate_value"] = current
            unresolved.pop(path, None)
            advisory[path] = str(raw)[:STACK_ITEM_MAX_CHARS]
            if len(str(raw)) > 255:
                basics["rate_raw"] = None
            return
        value = raw
    if value in (None, ""):
        basics["rate_value"] = None
        return
    result = rate(value)
    if result is None:
        unresolved[path] = str(value)
    else:
        unresolved.pop(path, None)
    basics["rate_value"] = result
    basics["rate_raw"] = str(value) if len(str(value)) <= 255 else None


def prepare_profile(
    data,
    *,
    actor_id=None,
    template_version=None,
    raw_fields=None,
    previous=None,
):
    """Store unresolved input alongside null/empty canonical values, not guesses.

    ``previous`` is the normalised stored profile. When given, only the fields
    whose value differs from it are normalised; everything else stays exactly
    as stored, together with its `unresolved`/`advisory` notes. An edit of the
    project description must not re-parse, and so rewrite, a rate or a
    requirement list nobody touched. Without ``previous`` (a fresh document,
    a preview, validation) the whole profile is normalised.
    """
    data = deepcopy(data or {})
    old_meta = data.get("intake") or {}
    unresolved = dict(old_meta.get("unresolved") or {})
    advisory = dict(old_meta.get("advisory") or {})
    basics = data.setdefault("basics", {})
    raw_fields = raw_fields or {}
    normalizers = {
        "seniority_min_years": lambda v: number(v, 60, integer=True),
        "onsite_days_per_week": lambda v: number(v, 7, integer=True),
        "work_mode": mode,
        "start_date": date,
        "deadline": date,
    }
    text_limits = {
        "role_name": 255,
        "candidate_location_pref": 255,
        "language": 50,
        "contract_length": 255,
    }
    tracked = [
        *(
            f"basics.{key}"
            for key in ("rate_value", "rate_raw", *normalizers, *text_limits)
        ),
        "stack.must",
        "stack.nice",
        "search.disqualifiers",
        "screening_questions",
        *(
            f"{section}.{key}"
            for section in ("project", "client")
            for key in (data.get(section) or {})
        ),
    ]
    # Decided BEFORE anything is rewritten: a normaliser must not make its
    # neighbour look edited.
    dirty = {
        path
        for path in tracked
        if previous is None
        or path in raw_fields
        or _value_at(data, path) != _value_at(previous, path)
    }
    if {"basics.rate_value", "basics.rate_raw"} & dirty:
        _normalize_rate(basics, raw_fields, unresolved, advisory)
    for key, normalize in normalizers.items():
        path = f"basics.{key}"
        if path not in dirty:
            continue
        value = raw_fields.get(path, basics.get(key))
        if value in (None, ""):
            basics[key] = None
            continue
        result = normalize(value)
        if result is None:
            unresolved[path] = str(value)
        else:
            unresolved.pop(path, None)
        basics[key] = result
    for key, limit in text_limits.items():
        path = f"basics.{key}"
        if path not in dirty:
            continue
        value = basics.get(key)
        if value and (not meaningful(value) or len(str(value)) > limit):
            unresolved[path] = str(value)
            basics[key] = None
        elif value:
            unresolved.pop(path, None)
    stack = data.setdefault("stack", {})
    for key in ("must", "nice"):
        path = f"stack.{key}"
        if path not in dirty:
            continue
        restored = [
            line
            for line in str(unresolved.get(path) or "").splitlines()
            if meaningful(line)
        ]
        values, placeholders, long_items, unstorable = split_skills(
            stack.get(key), restored
        )
        stack[key] = values
        set_aside = placeholders + unstorable
        if set_aside:
            unresolved[path] = "\n".join(set_aside)
        elif values:
            unresolved.pop(path, None)
        if long_items:
            advisory[path] = "\n".join(long_items)
        else:
            advisory.pop(path, None)
    search = data.setdefault("search", {})
    if "search.disqualifiers" in dirty and isinstance(search.get("disqualifiers"), str):
        search["disqualifiers"] = [
            x.strip() for x in search["disqualifiers"].splitlines() if meaningful(x)
        ]
    if "screening_questions" in dirty:
        questions = []
        for q in data.get("screening_questions") or []:
            if isinstance(q, dict) and meaningful(q.get("question")):
                questions.append(
                    {**q, "id": str(q.get("id") or f"q{len(questions) + 1}")}
                )
        data["screening_questions"] = questions
    for section in ("project", "client"):
        for key, value in list(data.setdefault(section, {}).items()):
            if (
                f"{section}.{key}" in dirty
                and isinstance(value, str)
                and not meaningful(value)
            ):
                data[section][key] = ""
    data["intake"] = {
        "policy_version": POLICY_VERSION,
        "template_version": template_version or old_meta.get("template_version"),
        "unresolved": unresolved,
        "advisory": advisory,
        "document_context": old_meta.get("document_context", {}),
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
    blocking = gate_enabled()

    def add(code, path, message, operations=OPERATIONS, source=None, warning=False):
        issues.append(
            {
                "code": code,
                "path": path,
                "message": message,
                "severity": "warning" if warning or not active else "error",
                "blocked_operations": list(operations)
                if active and not warning and blocking
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
    for path, source in (meta.get("advisory") or {}).items():
        code, message = ADVISORY_ISSUES.get(
            path, ("advisory_value", "Sprawdź ten wpis.")
        )
        add(code, path, message, source=source, warning=True)
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
        for key, column in STACK_COLUMNS.items():
            raw_column = getattr(job, column, None)
            declared = effective_skill_names(job, key)
            requested = [item["name"] for item in stack[key]]
            if (
                raw_column is not None
                or getattr(job, "matching_requirements", None) is not None
            ) and skill_groups(declared) != skill_groups(requested):
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

    return {
        "validation": validation(job.champion_profile, job),
        "fingerprint": fingerprint(job),
        "job_values": {
            **{
                key: (
                    float(getattr(job, column))
                    if key == "rate_value" and getattr(job, column, None) is not None
                    else getattr(job, column, None)
                )
                for key, column in RUBRICS.items()
            },
            **{
                key: "\n".join(effective_skill_names(job, key))
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
    structured = (
        await run_in_threadpool(table_profile, data)
        if filename.lower().endswith(".docx")
        else None
    )
    if structured:
        # The Word form is read from its tables — no model, no input limit.
        structured["profile"]["intake"] = {
            "document_context": structured.get("document_context", {})
        }
        cp = prepare_profile(
            structured["profile"],
            raw_fields=structured["raw_fields"],
            template_version=structured["template_version"],
        )
    else:
        # Checked BEFORE the quota block: rejecting an over-long document must
        # not cost an AI call from the monthly limit.
        if len(text) > MAX_TEXT:
            raise ValueError(
                f"Dokument przekracza limit {MAX_TEXT} znaków odczytu przez AI. "
                "Skróć treść albo użyj wzoru Word v4; niczego nie zaimportowano."
            )
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
            "advisory": (patch.get("intake") or {}).get("advisory", {}),
            "template_version": (patch.get("intake") or {}).get("template_version"),
            "document_context": (patch.get("intake") or {}).get("document_context", {}),
        }
    else:
        meta = normalized.get("intake") or {}
        unresolved = dict(meta.get("unresolved") or {})
        advisory = dict(meta.get("advisory") or {})
        for section, fields in patch.items():
            if isinstance(fields, dict):
                for key, value in fields.items():
                    path = f"{section}.{key}"
                    if value != (normalized.get(section) or {}).get(key):
                        advisory.pop(path, None)
                        # Requirements an earlier normaliser set aside are not
                        # a stale value of this field: nobody saw them in the
                        # editor, so nobody can have removed them. They stay
                        # and rejoin the list in `prepare_profile`.
                        if path not in ("stack.must", "stack.nice"):
                            unresolved.pop(path, None)
        merged["intake"] = {**meta, "unresolved": unresolved, "advisory": advisory}
    patch_basics = patch.get("basics") or {}
    if "rate_value" in patch_basics:
        if imported:
            # An import brings the document's text WITH the parser's number,
            # and `_normalize_rate` needs the pair to decide whether that
            # number is a PLN/h budget at all. Clearing the text whenever the
            # number differed from the stored one let any imported number win
            # ("45 EUR/h" became 45 PLN/h in `jobs.rate_budget_hourly`) and
            # dropped its warning. The text comes from the import or not at
            # all — never from the profile the import replaces.
            merged["basics"]["rate_raw"] = patch_basics.get("rate_raw")
        elif patch_basics["rate_value"] != normalized["basics"]["rate_value"]:
            # A number typed in the editor is the Delivery Lead's decision;
            # the old document text must not overrule it.
            merged["basics"]["rate_raw"] = None
    return prepare_profile(merged, actor_id=actor_id, previous=normalized)


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

    if getattr(job, "matching_requirements", None) is not None and skill_groups(
        effective_skill_names(job, key)
    ) != skill_groups([item["name"] for item in items]):
        apply_requirement_source_update(job, "matching_requirements", None)
    column = STACK_COLUMNS[key]
    current = getattr(job, column, None)
    if {name.casefold() for name in iter_skill_names(current)} == {
        item["name"].casefold() for item in items
    }:
        return
    apply_requirement_source_update(job, column, items)


def effective_skill_names(job, key):
    from app.services.requirement_contract import stored_contract, requirement_labels
    from app.services.skill_normalize import iter_skill_names

    contract = stored_contract(job)
    return (
        requirement_labels(contract)[key]
        if contract is not None
        else iter_skill_names(getattr(job, STACK_COLUMNS[key], None))
    )


def skill_groups(names):
    from app.services.requirement_contract import explicit_contract

    return {frozenset(group.any_of) for group in explicit_contract(names, []).all_of}
