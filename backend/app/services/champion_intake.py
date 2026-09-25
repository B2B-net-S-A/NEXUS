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
    "experience",
    "project",
    "screening_questions",
    "client",
    "insights",
    "documents",
)
EXPERIENCE_LISTS = ("domains", "certifications", "regulations")
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


# ── A document rate written in PLN per hour ──────────────────────────────────
#
# Matched on the folded text (lower case, no diacritics, "zł" -> "zl"). The
# grammar is TOKEN-based, not one fixed phrase: recruiters put the currency,
# the per-hour unit and the net qualifiers in any order ("140 zł netto/h",
# "140 zł/h netto", "PLN 140/h", "140 zł/h (netto, B2B)"). The first grammar
# (11.09) rejected "140 zł netto/h", and a stored rate whose text it rejected
# lost its number on the next reconcile, import or template copy — together
# with `jobs.rate_budget_hourly`.
#
# A number: an optional space as the thousands separator ("1 400") and a comma
# or a dot as the decimal one ("140,50").
_RATE_NUMBER = r"\d{1,3}(?: \d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
_PLN = re.compile(r"(?<![a-z])(?:pln|zl(?:otych|oty|ote)?)(?![a-z])\.?")
_HOUR = r"(?:h|hr|hour|godz(?:ina|ine|\.)?)(?![a-z])"
_PER_HOUR = re.compile(
    rf"/\s*(?:1\s*)?{_HOUR}|(?<![a-z])(?:za|na|per)\s+(?:1\s*)?{_HOUR}"
)
# Qualifiers that keep the value a net B2B hourly rate. "brutto" is NOT one:
# a gross figure is a different number than the budget it would be read as.
_NET_QUALIFIER = re.compile(
    r"(?<![a-z])(?:na\s+)?b2b(?![a-z])"
    r"|(?<![a-z])(?:netto|net)(?![a-z])"
    r"|(?:\+|(?<![a-z])plus|(?<![a-z])bez)\s*vat(?![a-z])"
)
# A label in front of the value: "Stawka: 140 zł/h", "Maks. stawka kandydata:".
_RATE_LABEL = re.compile(
    r"^(?:(?:maksymalna|maks\.?|max\.?)\s*)?(?:stawka|budzet|rate)(?![a-z])"
    r"(?:\s+(?:maksymalna|maks\.?|max\.?|kandydata|godzinowa|netto|b2b|docelowa)"
    r"(?![a-z]))*\s*:?\s*"
)
_RATE_SHAPES = (
    # "120–140", "120/140", "od 120 do 140"
    (
        re.compile(rf"(?:od\s*)?({_RATE_NUMBER})\s*(?:-|/|do)\s*({_RATE_NUMBER})"),
        "range",
    ),
    # "do 140", "max. 140" — an upper bound: anything above zero up to it
    (
        re.compile(
            r"(?:do|max\.?|maks\.?|maksymalnie|up\s+to|nie\s+wiecej\s+niz|<=?)"
            rf"\s*({_RATE_NUMBER})"
        ),
        "upper",
    ),
    # "140", "ok. 140"
    (re.compile(rf"(?:ok\.?|okolo|ca\.?|~)?\s*({_RATE_NUMBER})"), "single"),
)


def _rate_float(text):
    return float(text.replace(" ", "").replace(",", "."))


def pln_hourly_bounds(value):
    """``(low, high)`` of a document rate written in PLN per hour, else None.

    Accepts one value, a range ("120–140", "120/140", "od 120 do 140") or an
    upper bound ("do 140", "max. 140"), with the currency and the per-hour
    unit in any order and spelling ("zł/h", "PLN / h", "zł za godzinę", "PLN
    140/h"), optionally net of VAT and after a "Stawka:" label ("140 zł
    netto/h", "140 zł/h (netto, B2B)", "120 – 140 PLN/h + VAT"). Any other
    currency, a day/MD/month rate, a gross figure, a missing currency or unit
    and any word left over ("lub 1000 zł/MD", "do negocjacji") answer None:
    such a text cannot vouch for a PLN/h number, whatever the model put next
    to it.

    Nothing is capped here — "1 400 zł/h" answers ``(1400.0, 1400.0)``;
    `rate` decides whether a number is a plausible budget.
    """
    text = folded(str(value or ""))
    # Typographic dashes and the minus sign are range separators too; the
    # no-break spaces ("1 400" pasted from Word) are plain separators.
    text = re.sub(r"[\u2010-\u2015\u2212]", "-", text)
    text = re.sub(r"[\u00a0\u2007\u202f]", " ", text).strip()
    if not (_PLN.search(text) and _PER_HOUR.search(text)):
        return None
    text = _RATE_LABEL.sub("", text, count=1)
    for token in (_PER_HOUR, _PLN, _NET_QUALIFIER):
        text = token.sub(" ", text)
    # "(netto, B2B)" leaves an empty pair of brackets behind.
    text = re.sub(r"\([\s,;/]*\)", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .,;:")
    for pattern, kind in _RATE_SHAPES:
        match = pattern.fullmatch(text)
        if not match:
            continue
        values = [_rate_float(v) for v in match.groups()]
        if kind == "range":
            low, high = values
        elif kind == "upper":
            low, high = 0.0, values[0]
        else:
            low = high = values[0]
        return (low, high) if 0 <= low <= high else None
    return None


# A rate phrase inside free text (a pasted request, not a rate field): an
# optional label, an optional bound word, one value or a range, the currency
# and net qualifiers, then the per-hour unit. Only the WINDOW is found here;
# whether it really is a PLN/h rate is decided by `pln_hourly_bounds`.
# The text is whitespace-collapsed BEFORE matching (``budget_max_pln_hour``),
# so every separator below is at most ONE space (`` ?``). Stacked ``\s*``
# groups next to each other made this regex backtrack cubically on a pasted
# request with a long run of blank lines after a number — one call froze the
# single uvicorn process for tens of seconds (adversarial review 17.09.2026).
_BUDGET_WINDOW = re.compile(
    rf"(?:(?:stawka|budzet)[^:\n]{{0,30}}: ?)?"
    rf"(?:(?:od|do|max\.?|maks\.?|maksymalnie) ?)?(?:pln ?)?(?:{_RATE_NUMBER})"
    rf"(?: ?(?:-|/|do) ?(?:{_RATE_NUMBER}))? ?(?:pln|zl)?\.? ?"
    rf"(?:(?:netto|net|\+ ?vat|b2b) ?)*"
    rf"(?:/ ?(?:1 ?)?(?:h|hr|godz(?:ina|ine|\.)?)"
    rf"|(?:za|na|per) (?:1 ?)?(?:h|godz(?:ina|ine|\.)?))(?![a-z])"
)

# A budget phrase is short; a 20 000-character paste never needs more than
# this to find it, and the cap bounds the work regardless of the regex.
_BUDGET_TEXT_LIMIT = 5000


def budget_max_pln_hour(text: str | None) -> int | None:
    """Upper PLN/h budget stated in a pasted request, else None.

    A SUGGESTION for the Talent Radar budget field (17.09.2026), never a
    filter by itself: the recruiter sees it filled and can clear it. Every
    rate phrase in the text must agree on one upper bound — two different
    rates ("120 zł/h i 160 zł/h") are ambiguous and suggest nothing.
    """
    t = folded((text or "")[:_BUDGET_TEXT_LIMIT])
    t = re.sub(r"[\u2010-\u2015\u2212]", "-", t)
    t = re.sub(r"\s+", " ", t)
    highs = {
        bounds[1]
        for match in _BUDGET_WINDOW.finditer(t)
        if (bounds := pln_hourly_bounds(match.group(0)))
    }
    if len(highs) != 1:
        return None
    high = next(iter(highs))
    return int(high) if 0 < high <= 2000 else None


def document_rate(text):
    """``(rate, is_bound)`` read from a document's rate text, or None.

    The text is the source of truth and its UPPER bound is the budget: the
    field is the candidate's maximum PLN/h and `dealbreaker_filters` reads it
    as a ceiling, so a range "120–140 zł/h" is a budget of 140 — the parser's
    midpoint (130) understated it. ``is_bound`` says the text was a range or
    "do X" rather than one value: worth a warning, never a reason to drop it.
    """
    single = rate(text)
    if single is not None:
        return single, False
    bounds = pln_hourly_bounds(text)
    if bounds is None:
        return None
    low, high = bounds
    value = rate(high)
    if value is None:
        return None
    return value, low < high


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
        "Stawka w dokumencie jest zakresem lub górną granicą (PLN/h) — przyjęto "
        "górną granicę jako maksymalną stawkę kandydata. Sprawdź, czy to "
        "właściwa wartość.",
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


def _set_aside_requirements_lost(stored_meta, meta, path="stack.must"):
    """Stored set-aside MUST entries the current normaliser cannot restore.

    A normalisation without `previous` (validation) drops the stored
    `intake.unresolved` note of a non-empty stack and does not pull the
    entries back (see `prepare_profile`). That is silent on purpose for the
    entries the current normaliser accepts — they rejoin the list on the next
    stack edit. An entry it would reject (longer than `STACK_ITEM_MAX_CHARS`)
    never rejoins: it is reported, as a warning only.
    """
    stored_note = str((stored_meta.get("unresolved") or {}).get(path) or "")
    lines = [line.strip() for line in stored_note.splitlines() if meaningful(line)]
    _, _, _, unstorable = split_skills([], lines)
    current_note = str((meta.get("unresolved") or {}).get(path) or "")
    still_noted = set(current_note.splitlines())
    return [line for line in unstorable if line not in still_noted]


def _value_at(profile, path):
    section, _, key = path.partition(".")
    value = (profile or {}).get(section)
    if not key:
        return value
    return value.get(key) if isinstance(value, dict) else None


RATE_PATH = "basics.rate_value"


def _rate_number(value):
    """A rate as a number — "140", 140 and 140.0 are the same rate — or None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return rate(str(value).strip())


def _same_rate(a, b) -> bool:
    """The same rate input: the same number, or the same text (blank = None)."""
    number_a, number_b = _rate_number(a), _rate_number(b)
    if number_a is not None and number_b is not None:
        return abs(number_a - number_b) < 1e-9
    if number_a is not None or number_b is not None:
        return False
    return str(a or "").strip() == str(b or "").strip()


def rate_unchanged(value, previous) -> bool:
    """Whether ``value`` is the budget already stored in ``previous``.

    Compared as NUMBERS ("140" == 140.0): a form sends the stored number back
    as text. Only a stored number counts — with no stored budget there is
    nothing a save could wrongly re-derive, and the document text or
    unresolved note the save brings (an import of "45 EUR/h") is recorded.
    """
    stored = ((previous or {}).get("basics") or {}).get("rate_value")
    return _rate_number(stored) is not None and _same_rate(value, stored)


def _keep_stored_rate(basics, unresolved, advisory, previous):
    """The stored rate, its document text and its notes, exactly as stored."""
    stored_basics = previous.get("basics") or {}
    stored_meta = previous.get("intake") or {}
    basics["rate_value"] = stored_basics.get("rate_value")
    basics["rate_raw"] = stored_basics.get("rate_raw")
    for notes, key in ((unresolved, "unresolved"), (advisory, "advisory")):
        note = (stored_meta.get(key) or {}).get(RATE_PATH)
        if note is None:
            notes.pop(RATE_PATH, None)
        else:
            notes[RATE_PATH] = note


def _normalize_rate(basics, raw_fields, unresolved, advisory):
    """`rate_value` from a document's rate text or from a typed number.

    Only for a rate that is NEW — a fresh document, a preview, or a save that
    changed the number (`prepare_profile` keeps an unchanged stored rate as
    it is, see `rate_unchanged`).

    A document text — `rate_raw` from the AI parser, the cell of the Word
    form (`raw_fields`), or the text an import dialog sends back with an
    untouched document rate — is the source of truth: one PLN/h value is the
    budget, a range or "do X" gives its UPPER bound, noted in `advisory`
    ("120–140 zł/h" -> 140; the field is the candidate's maximum PLN/h and the
    dealbreaker reads it as a ceiling, so the parser's midpoint understated
    it). A text in any other unit ("45 EUR/h", "1200 PLN/MD", "20 000
    PLN/mies. brutto") vouches for no number: it stays unresolved, the budget
    stays empty and validation reports `missing_budget` — a kept number would
    be copied into an empty `jobs.rate_budget_hourly` and read by scoring and
    the rate dealbreaker as the candidate's maximum PLN/h, even when the model
    converted the unit on its own.

    Without a text the value is a typed (or parsed) number: stored as the
    budget, with no document text and no warning.
    """
    path = RATE_PATH
    advisory.pop(path, None)
    text = raw_fields[path] if path in raw_fields else basics.get("rate_raw")
    text = "" if text is None else str(text)
    if text.strip():
        found = document_rate(text)
        basics["rate_raw"] = text if len(text) <= 255 else None
        if found is None:
            unresolved[path] = text
            basics["rate_value"] = None
            return
        value, bound = found
        unresolved.pop(path, None)
        basics["rate_value"] = value
        if bound:
            advisory[path] = text[:STACK_ITEM_MAX_CHARS]
        return
    value = basics.get("rate_value")
    # A typed number replaces the document text; a typed text that is not a
    # number stays visible in `unresolved` only (as the editor shows it).
    basics["rate_raw"] = None
    if value is None or not str(value).strip():
        basics["rate_value"] = None
        return
    result = rate(value)
    if result is None:
        unresolved[path] = str(value)
    else:
        unresolved.pop(path, None)
    basics["rate_value"] = result


def normalize_experience_items(value, *, with_years):
    """Lista pozycji sekcji 4: trim, dedup po nazwie, limit — bez odrzucania.

    Przyjmuje listę słowników, listę napisów albo jeden napis rozdzielony
    przecinkami / średnikami / nowymi liniami (import dokumentu). Pozycja bez
    nazwy odpada; za długa nazwa jest przycinana, bo `model_validate` na końcu
    `prepare_profile` zamieniłby ją w 500 na zapisie całego profilu.
    """
    from app.schemas.champion import (
        EXPERIENCE_ITEM_MAX_CHARS,
        EXPERIENCE_ITEMS_MAX,
    )

    if isinstance(value, str):
        value = [part for part in re.split(r"[\n;,]+", value)]
    items = []
    seen = set()
    for raw in value if isinstance(value, list) else []:
        entry = raw if isinstance(raw, dict) else {"name": raw}
        name = re.sub(r"\s+", " ", str(entry.get("name") or "")).strip()
        if not meaningful(name):
            continue
        name = name[:EXPERIENCE_ITEM_MAX_CHARS]
        key = folded(name).strip()
        if key in seen:
            continue
        seen.add(key)
        level = entry.get("level") if entry.get("level") in ("must", "nice") else "must"
        years = (
            number(entry.get("min_years"), 40, integer=True)
            if with_years and entry.get("min_years") not in (None, "")
            else None
        )
        note = entry.get("note")
        items.append(
            {
                "name": name,
                "level": level,
                "min_years": years,
                "note": note.strip()[:300] if isinstance(note, str) else "",
            }
        )
        if len(items) >= EXPERIENCE_ITEMS_MAX:
            break
    return items


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
    a preview, validation) the whole profile is normalised — but a stack entry
    set aside in `unresolved` by an older normaliser is never pulled back:
    that happens only on a save that edits the stack field.

    The rate is compared as a NUMBER, whatever `rate_raw` the save carries: an
    unchanged rate keeps its stored value, document text and notes. The
    reconcile dialog, an import that keeps the current rate and a template
    copy send the stored number back (as "140", or with the stored text, or
    with none); re-deriving it from a text the grammar could not read wiped
    140 PLN/h from ~949 profiles of the 08.2026 import and, with the sync box
    ticked, from `jobs.rate_budget_hourly`.
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
        *(f"experience.{key}" for key in EXPERIENCE_LISTS),
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
    if (
        previous is not None
        and RATE_PATH not in raw_fields
        and rate_unchanged(basics.get("rate_value"), previous)
    ):
        _keep_stored_rate(basics, unresolved, advisory, previous)
    elif {RATE_PATH, "basics.rate_raw"} & dirty:
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
        # Entries an older normaliser set aside in `unresolved` rejoin the
        # list only on a SAVE that edits this field (`previous` given). A
        # normalisation without `previous` — `validation()` above all — must
        # see the stack as stored: resurrecting there validated a list that
        # differed from the stored one and from `jobs.must_skills` synced from
        # it, a `skill_column_conflict` nobody could see in the editor.
        restored = (
            [
                line
                for line in str(unresolved.get(path) or "").splitlines()
                if meaningful(line)
            ]
            if previous is not None
            else []
        )
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
    experience = data.setdefault("experience", {}) or {}
    data["experience"] = experience
    for key in EXPERIENCE_LISTS:
        if f"experience.{key}" in dirty:
            experience[key] = normalize_experience_items(
                experience.get(key), with_years=key == "domains"
            )
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
    """Issues of the profile AS STORED; never rewrites what it is given.

    The re-normalisation below only re-derives notes from stored values — it
    pulls no set-aside entry back into the stack (see `prepare_profile`) — and
    the recruitment columns are compared with the stack as stored, the list
    `jobs.must_skills`/`nice_skills` were synced from. The budget checks read
    the rate as stored too: re-reading a stored document text can give
    another number than the one stored (a range whose parser midpoint was
    stored before the upper bound became the rule), and that number was never
    the budget of this profile or of `jobs.rate_budget_hourly`.

    An empty stored MUST/NICE list is not treated as missing on its own: it
    inherits the recruitment's `must_skills`/`nice_skills` column (via
    `effective_skill_names`) for the missing/ineligible checks below, the
    same way an empty `basics.role_name` falls back to `job.title`.
    """
    from pydantic import ValidationError

    try:
        cp = ChampionProfile.model_validate(profile or {}).model_dump(mode="json")
    except ValidationError:
        cp = prepare_profile(profile)
    stored_stack = cp["stack"]
    stored_rate = cp["basics"].get("rate_value")
    stored_meta = cp.get("intake") or {}
    meta = stored_meta
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

    basics = {**cp["basics"], "rate_value": stored_rate}
    stack = cp["stack"]
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
    lost = _set_aside_requirements_lost(stored_meta, meta) if active else []
    if lost:
        add(
            "unstorable_requirement",
            "stack.must",
            "Wymaganie odłożone przy wcześniejszym zapisie jest za długie na "
            f"jedną pozycję listy MUST (limit {STACK_ITEM_MAX_CHARS} znaków) i nie "
            "trafi do wymagań rekrutacji. Skróć je albo podziel i dodaj ponownie.",
            source="\n".join(lost),
            warning=True,
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
    inherited = {}
    if job is not None:
        for key in STACK_COLUMNS:
            if not stored_stack[key]:
                inherited[key] = effective_skill_names(job, key)
    names = [x["name"] for x in stack["must"]] or inherited.get("must", [])
    nice_names = [x["name"] for x in stack["nice"]] or inherited.get("nice", [])
    if not names and not nice_names:
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
            if not stored_stack[key]:
                # Empty stored list inherits the column (see above) — there
                # is nothing of the profile's own to conflict with it.
                continue
            raw_column = getattr(job, column, None)
            declared = effective_skill_names(job, key)
            # The stored stack: that is what the columns were synced from.
            requested = [item["name"] for item in stored_stack[key]]
            if (
                raw_column is not None
                or getattr(job, "matching_requirements", None) is not None
            ) and skill_groups(declared) != skill_groups(requested):
                add(
                    "skill_column_conflict",
                    f"stack.{key}",
                    "Profil i pola rekrutacji mają różne wymagania. Uzgodnij wybraną listę.",
                    # No gate reads NICE (dealbreakers and readiness are MUST
                    # only), so a NICE mismatch is a warning at most.
                    warning=key == "nice",
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
    deadline = getattr(job, "deadline", None)
    state = {
        "profile": getattr(job, "champion_profile", None),
        "title": getattr(job, "title", None),
        "client_id": getattr(job, "client_id", None),
        "requirements": getattr(job, "matching_requirements", None),
        "reviewed": getattr(job, "requirements_reviewed", None),
        "office_location": getattr(job, "office_location", None),
        "deadline": deadline.isoformat() if deadline else None,
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


def _rubric_job_value(job, key, column):
    """A rubric value as offered to the intake form — same source as `validation()`."""

    if key == "rate_value":
        raw = getattr(job, column, None)
        return float(raw) if raw is not None else None
    if key == "candidate_location_pref":
        return getattr(job, "office_location", None) or getattr(job, column, None)
    return getattr(job, column, None)


def response_context(job):
    deadline = getattr(job, "deadline", None)

    return {
        "validation": validation(job.champion_profile, job),
        "fingerprint": fingerprint(job),
        "job_values": {
            **{
                key: _rubric_job_value(job, key, column)
                for key, column in RUBRICS.items()
            },
            **{
                key: "\n".join(effective_skill_names(job, key))
                for key, column in STACK_COLUMNS.items()
            },
            "role_name": getattr(job, "title", None),
            "deadline": deadline.isoformat() if deadline else None,
        },
    }


async def preview_document(data, filename, *, db=None, model=None, max_text=None):
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
        # `max_text` podnosi limit WYŁĄCZNIE dla przebiegu backfillu z Traffita
        # (dokumenty ponad 14 000 znaków); ekran importu zostaje przy MAX_TEXT.
        limit = max_text or MAX_TEXT
        if len(text) > limit:
            raise ValueError(
                f"Dokument przekracza limit {limit} znaków odczytu przez AI. "
                "Skróć treść albo użyj wzoru Word v4; niczego nie zaimportowano."
            )
        # `model` idzie dalej WYŁĄCZNIE, gdy przebieg go ustawia (backfill):
        # zwykła ścieżka woła parser dokładnie tak jak przed 22.09.2026.
        parse_kwargs = {"model": model} if model else {}
        if max_text:
            parse_kwargs["max_chars"] = max_text
        if db is None:
            parsed = await parse_champion_document(text, **parse_kwargs)
        else:
            from app.models.ai_feature import AIFeatureKey
            from app.services.ai_quota import ai_feature

            async with ai_feature(db, AIFeatureKey.champion_profile_parse):
                parsed = await parse_champion_document(text, **parse_kwargs)
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


def _without_search_rows(section, value):
    from app.services.champion_view import without_search_rows

    return without_search_rows(value) if section == "search" else value


def user_edit(old, patch, actor_id, *, imported=False, actor_name=None):
    from app.services.champion_insights import merge_insights

    normalized = ChampionProfile.model_validate(old or {}).model_dump(mode="json")
    patch = migrate_legacy_champion_shape(patch)
    merged = deepcopy(normalized)
    for key in SECTION_KEYS:
        if key == "insights":
            continue
        if key in patch:
            merged[key] = (
                {**merged[key], **patch[key]}
                if isinstance(merged[key], dict) and isinstance(patch[key], dict)
                else patch[key]
            )
    # Sekcja 8 NIE jest zwykłą listą do podmiany: autor i daty stempluje
    # serwer, a wpisy składane przy odczycie (`verification:*`, `legacy:*`)
    # nie są zapisywane jako notatki (patrz `champion_insights`).
    # `migrate_legacy_champion_shape` dokłada `insights` do KAŻDEGO patcha
    # dopiero wtedy, gdy ten go niesie — brak klucza = sekcja nietknięta.
    if "insights" in (patch or {}) and isinstance(patch.get("insights"), list):
        merged["insights"] = merge_insights(
            normalized,
            patch["insights"],
            actor_id=actor_id,
            actor_name=actor_name,
            default_origin="document" if imported else "manual",
        )
    changed = any(merged[k] != normalized[k] for k in SECTION_KEYS)
    if not changed and not imported and old:
        return normalized
    # Sama sekcja 8 (notatki) i same wymagania do wyszukiwania w bazie
    # (sekcja 2, 25.09.2026) to nie zmiana profilu roli: bez `prepare_profile`,
    # który przestemplowałby `intake.applied_at`. `intake` wchodzi do odcisku
    # rankingu, więc odhaczenie „do dopytania” albo dopisanie wiersza
    # unieważniałoby pełny przegląd bazy (409) — a żadne z nich nie zmienia
    # tego, kogo szukają automaty. Walidacja normalizuje wiersze, więc pusty
    # wiersz z edytora daje profil równy zapisanemu (bez zmiany).
    if (
        not imported
        and old
        and all(
            _without_search_rows(k, merged[k]) == _without_search_rows(k, normalized[k])
            for k in SECTION_KEYS
            if k != "insights"
        )
    ):
        edited = ChampionProfile.model_validate(merged).model_dump(mode="json")
        return normalized if edited == normalized else edited
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
    # A stored budget the save leaves UNCHANGED is kept whole by
    # `prepare_profile` (value, text and notes), whatever `rate_raw` the save
    # carries; the rules below decide only what a NEW rate is read from.
    if "rate_value" in patch_basics:
        if imported:
            # An import brings the document's text WITH the parser's number,
            # and `_normalize_rate` reads the budget from that text. Clearing
            # it whenever the number differed from the stored one let any
            # imported number win ("45 EUR/h" became 45 PLN/h in
            # `jobs.rate_budget_hourly`) and dropped its warning. The text
            # comes from the import or not at all — never from the profile the
            # import replaces.
            merged["basics"]["rate_raw"] = patch_basics.get("rate_raw")
        elif not _same_rate(
            patch_basics["rate_value"], normalized["basics"]["rate_value"]
        ):
            # A number typed in the editor is the Delivery Lead's decision;
            # the old document text must not overrule it.
            merged["basics"]["rate_raw"] = None
    return prepare_profile(merged, actor_id=actor_id, previous=normalized)


def copy_profile(profile, actor_id):
    """A template copy (`POST /api/jobs` with `from_job_id`), as stored.

    The source profile is its own `previous`: every field is unchanged, so
    nothing is re-normalised — the rate keeps its number and document text,
    the stack its entries, the notes stay as they were. Only the intake stamp
    and the import provenance are new, as for any import. Until 09.2026 the
    copy went through a fresh-document import and re-read the stored rate
    text; "140 zł netto/h" gave the new recruitment no budget at all.
    """
    stored = ChampionProfile.model_validate(profile or {}).model_dump(mode="json")
    # Rozmowy dotyczą KONKRETNEGO zlecenia: notatki z sekcji 8, podsumowanie
    # historii i weryfikacja nie przechodzą do kopii. Stare pola, z których
    # składane są wpisy `legacy:*`, zostają — są częścią opisu klienta.
    stored["insights"] = []
    for key in ("client_history", "verification"):
        stored.pop(key, None)
    return user_edit(stored, deepcopy(stored), actor_id, imported=True)


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
