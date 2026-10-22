"""Ocena prepu v2 — czyste funkcje bez bazy (decyzje Artura 22.10.2026).

Model (``prep_review``) dostaje trzy listy punktów, które zbudował KOD:

* tematy prowadzącego z Ustawienia → Ocena prepów — czy padły
  (``covered`` / ``partial`` / ``missing``),
* punkty odpowiedzi kandydata: must-have rekrutacji, pytania tego klienta,
  a w Prepie 2 punkty z notatki na Prep 2 — jak kandydat odpowiedział
  (``strong`` / ``general`` / ``weak`` / ``missing``, skala z ustawień),

i do każdego daje cytat. Cytat, którego nie ma w transkrypcie, zamienia punkt
w „nie było” z flagą ``unverified`` — model nie zaliczy niczego bez dowodu.

Wynik liczy kod: każde kryterium ma wynik 0–100, wynik prepu to średnia
ważona wagami z ustawień (kryterium bez punktów — np. brak pytań klienta albo
udział kandydata bez mówców w transkrypcie — wypada, a jego waga rozkłada się
na resztę). Poziom z progów; reguły „najwyżej OK” i „za krótki = słaby”.

Z Prepu 1 kod wybiera „Do powtórzenia na Prep 2” (``followup``) — to notatka
rekrutera. W Prepie 2 te same punkty są oceniane jeszcze raz, a wynik
porównuje się z Prepem 1 (``comparison``).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from app.services.prep_review_config import PrepReviewConfig

QUOTE_MIN_CHARS = 6
TOPIC_STATUSES = ("covered", "partial", "missing")
GRADES = ("strong", "general", "weak", "missing")
LEVEL_LABELS = {"weak": "słaby", "ok": "OK", "good": "dobry"}
GRADE_LABELS = {
    "strong": "mocna",
    "general": "ogólna",
    "weak": "słaba",
    "missing": "nie było",
    "covered_in_prep1": "mocna w Prepie 1",
}
TOPIC_POINTS = {"covered": 100, "partial": 50, "missing": 0}
REASON_LABELS = {
    "weak": "słaba odpowiedź",
    "missing": "nie omówiono",
    "missing_topic": "temat obowiązkowy pominięty",
    "general": "ogólna odpowiedź",
    "unpracticed": "pytanie klienta nieprzećwiczone",
}
MAX_LIST = 3
MAX_LINE = 300

# Zgodność z oknem sprzed v2 (``criteria.items``): stopień → status punktu.
LEGACY_STATUS = {
    "strong": "covered",
    "general": "partial",
    "weak": "partial",
    "missing": "missing",
    "covered_in_prep1": "covered_in_prep1",
}


@dataclass(frozen=True)
class Item:
    key: str
    label: str
    # "topic" | "must" | "question" | "followup"
    kind: str
    required: bool = False


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().casefold()


def _json_object(raw: str) -> dict:
    body = (raw or "").strip()
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in model output")
    data = json.loads(body[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("model output is not an object")
    return data


def verified_quote(quote: Any, haystack: str) -> Optional[str]:
    if not isinstance(quote, str):
        return None
    q = quote.strip().strip("„”\"'")
    if len(q) < QUOTE_MIN_CHARS or norm(q) not in haystack:
        return None
    return q[:300]


def _choice(value: Any, allowed: tuple[str, ...]) -> Optional[str]:
    """Wartość modelu bez wielkości liter („Strong” = „strong”)."""
    if not isinstance(value, str):
        return None
    v = value.strip().casefold()
    return v if v in allowed else None


def _lines(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out = []
    for entry in value:
        if isinstance(entry, str) and entry.strip():
            out.append(re.sub(r"\s+", " ", entry).strip()[:MAX_LINE])
    return out[:MAX_LIST]


def _entries(data: dict, group: str, needed: bool) -> dict[str, dict]:
    entries = data.get(group)
    if needed and not isinstance(entries, list):
        raise ValueError(f"model output without {group}")
    given: dict[str, dict] = {}
    for entry in entries or []:
        if isinstance(entry, dict) and entry.get("key"):
            given.setdefault(str(entry["key"]).strip(), entry)
    return given


def _check_protocol(
    items: list[Item], given: dict[str, dict], field_name: str, allowed: tuple
) -> None:
    """Odpowiedź, która nie trzyma się kluczy albo wartości, to awaria modelu.

    Runda 8 (R8-N9-2): obce klucze albo pominięta grupa zerowały punkty
    i dawały „słaby” z dzwonkiem — a awaria modelu ma dawać ``unavailable``.
    Pojedynczy pominięty punkt dalej dostaje „nie było”; odmowa dopiero, gdy
    nie pasuje co najmniej połowa kluczy albo wartości.
    """
    if not items:
        return
    matched = [given[i.key] for i in items if i.key in given]
    if len(matched) * 2 < len(items):
        raise ValueError("model output keys do not match the items")
    valid = sum(1 for e in matched if _choice(e.get(field_name), allowed) is not None)
    if valid * 2 < len(matched):
        raise ValueError("model output values are not recognised")


def parse_review(raw: str, *, items: list[Item], transcript: str) -> dict:
    """JSON modelu → tematy, odpowiedzi i wnioski; cytaty sprawdzone w transkrypcie.

    Rzuca ``ValueError`` przy odpowiedzi niezgodnej z protokołem — wołający
    zapisuje wtedy ocenę jako niedostępną (``level=NULL``).
    """
    data = _json_object(raw)
    haystack = norm(transcript)
    topics = [i for i in items if i.kind == "topic"]
    answers = [i for i in items if i.kind != "topic"]
    given_topics = _entries(data, "topics", bool(topics))
    given_answers = _entries(data, "answers", bool(answers))
    _check_protocol(topics, given_topics, "status", TOPIC_STATUSES)
    _check_protocol(answers, given_answers, "grade", GRADES)

    topics_out = []
    for item in topics:
        entry = given_topics.get(item.key) or {}
        status = _choice(entry.get("status"), TOPIC_STATUSES) or "missing"
        quote = (
            verified_quote(entry.get("quote"), haystack)
            if status != "missing"
            else None
        )
        unverified = status != "missing" and quote is None
        topics_out.append(
            {
                "key": item.key,
                "label": item.label,
                "required": item.required,
                "status": "missing" if unverified else status,
                "quote": quote,
                "unverified": unverified,
            }
        )

    answers_out = []
    for item in answers:
        entry = given_answers.get(item.key) or {}
        grade = _choice(entry.get("grade"), GRADES) or "missing"
        quote = (
            verified_quote(entry.get("quote"), haystack) if grade != "missing" else None
        )
        unverified = grade != "missing" and quote is None
        note = entry.get("note")
        answers_out.append(
            {
                "key": item.key,
                "label": item.label,
                "kind": item.kind,
                "grade": "missing" if unverified else grade,
                "quote": quote,
                "note": note.strip()[:MAX_LINE]
                if isinstance(note, str) and note.strip()
                else None,
                "unverified": unverified,
            }
        )

    own = data.get("own_projects") if isinstance(data.get("own_projects"), dict) else {}
    own_quote = verified_quote(own.get("quote"), haystack)
    summary = data.get("summary")
    return {
        "summary": summary.strip()[:2000]
        if isinstance(summary, str) and summary.strip()
        else None,
        "topics": topics_out,
        "answers": answers_out,
        "went_well": _lines(data.get("went_well")),
        "went_wrong": _lines(data.get("went_wrong")),
        "improve": _lines(data.get("improve")),
        "own_projects": {
            "told": bool(own.get("told")) and own_quote is not None,
            "quote": own_quote,
        },
    }


def mark_covered_in_prep1(answers: list[dict], prep1_strong: set[str]) -> list[dict]:
    """Prep 2: pytanie klienta mocne już w Prepie 1 nie liczy się do wyniku."""
    out = []
    for answer in answers:
        if (
            answer["kind"] == "question"
            and answer["grade"] != "strong"
            and answer["key"] in prep1_strong
        ):
            out.append({**answer, "grade": "covered_in_prep1"})
        else:
            out.append(answer)
    return out


@dataclass
class Score:
    level: str
    total: Optional[int]
    scores: dict[str, Optional[int]]
    weights_used: dict[str, int]
    caps: list[str] = field(default_factory=list)


def _avg(values: list[float]) -> Optional[int]:
    return round(sum(values) / len(values)) if values else None


def criterion_scores(
    parsed: dict,
    *,
    config: PrepReviewConfig,
    talk_share: Optional[float],
) -> dict[str, Optional[int]]:
    """Wynik 0–100 każdego kryterium; ``None`` = kryterium bez punktów."""
    points = {g: config.answer_scale[g].points for g in GRADES}

    def answers(kind: str) -> list[float]:
        return [
            points[a["grade"]]
            for a in parsed["answers"]
            if a["kind"] == kind and a["grade"] in points
        ]

    talk = None
    if config.talk_share_enabled and talk_share is not None:
        target = max(config.talk_share_target, 1) / 100
        talk = round(min(1.0, talk_share / target) * 100)
    return {
        "topics": _avg([TOPIC_POINTS[t["status"]] for t in parsed["topics"]]),
        "must_answers": _avg(answers("must")),
        "client_questions": _avg(answers("question")),
        "prep1_followup": _avg(answers("followup")),
        "talk_share": talk,
    }


def score_review(
    parsed: dict,
    *,
    config: PrepReviewConfig,
    prep_no: int,
    talk_share: Optional[float],
    duration_seconds: int,
) -> Score:
    rules = config.prep2 if prep_no == 2 else config.prep1
    all_scores = criterion_scores(parsed, config=config, talk_share=talk_share)
    scores = {crit: all_scores.get(crit) for crit in rules.weights}
    weights_used = {
        crit: w
        for crit, w in rules.weights.items()
        if scores[crit] is not None and w > 0
    }
    weight_sum = sum(weights_used.values())
    total = (
        round(sum(scores[c] * w for c, w in weights_used.items()) / weight_sum)
        if weight_sum
        else None
    )
    caps: list[str] = []
    if total is None:
        level = "ok"
    elif total >= config.good_threshold:
        level = "good"
    elif total < config.weak_threshold:
        level = "weak"
    else:
        level = "ok"
    if config.min_minutes_enabled and duration_seconds < config.min_minutes * 60:
        caps.append("too_short")
        level = "weak"
    if (
        level == "good"
        and config.required_topic_caps_ok
        and any(t["required"] and t["status"] == "missing" for t in parsed["topics"])
    ):
        caps.append("required_topic_missing")
        level = "ok"
    if (
        level == "good"
        and config.weak_must_caps_ok
        and any(a["kind"] == "must" and a["grade"] == "weak" for a in parsed["answers"])
    ):
        caps.append("weak_must_answer")
        level = "ok"
    return Score(level, total, scores, weights_used, caps)


def followup_items(parsed: dict, config: PrepReviewConfig) -> list[dict]:
    """„Do powtórzenia na Prep 2” z oceny Prepu 1 — notatka rekrutera.

    Kolejność: słabe odpowiedzi, must-have, których nie omówiono, pominięte
    tematy obowiązkowe, ogólne odpowiedzi, nieprzećwiczone pytania klienta.
    """
    rules = config.followup
    buckets: dict[str, list[dict]] = {k: [] for k in REASON_LABELS}
    for a in parsed["answers"]:
        if a["kind"] not in ("must", "question"):
            continue
        if a["grade"] == "weak" and rules.weak_answers:
            reason = "weak"
        elif a["grade"] == "general" and rules.general_answers:
            reason = "general"
        elif a["grade"] == "missing" and a["kind"] == "must" and rules.weak_answers:
            reason = "missing"
        elif a["grade"] == "missing" and rules.unpracticed_client_questions:
            reason = "unpracticed"
        else:
            continue
        buckets[reason].append(
            {
                "key": a["key"],
                "label": a["label"],
                "kind": a["kind"],
                "reason": reason,
                "quote": a["quote"],
                "note": a["note"],
            }
        )
    if rules.missing_required_topics:
        for t in parsed["topics"]:
            if t["required"] and t["status"] == "missing":
                buckets["missing_topic"].append(
                    {
                        "key": t["key"],
                        "label": t["label"],
                        "kind": "topic",
                        "reason": "missing_topic",
                        "quote": None,
                        "note": None,
                    }
                )
    ordered = [
        *buckets["weak"],
        *buckets["missing"],
        *buckets["missing_topic"],
        *buckets["general"],
        *buckets["unpracticed"],
    ]
    return ordered[: rules.max_items]


def comparison(parsed: dict, prep1_followup: list[dict]) -> list[dict]:
    """Prep 2: każdy punkt z notatki — przed (Prep 1) i po (Prep 2)."""
    after = {a["key"]: a for a in parsed["answers"] if a["kind"] == "followup"}
    rows = []
    for item in prep1_followup:
        now = after.get(f"followup:{item['key']}")
        rows.append(
            {
                "key": item["key"],
                "label": item["label"],
                "before": item.get("reason"),
                "after": now["grade"] if now else "missing",
                "quote": now["quote"] if now else None,
            }
        )
    return rows


def legacy_items(parsed: dict) -> list[dict]:
    """Punkty w kształcie sprzed v2 — dla okna oceny, zanim dostanie zakładki."""
    return [
        {
            "key": a["key"],
            "label": a["label"],
            "kind": a["kind"],
            "status": LEGACY_STATUS.get(a["grade"], "missing"),
            "quote": a["quote"],
            "unverified": a["unverified"],
        }
        for a in parsed["answers"]
        if a["kind"] in ("must", "question")
    ]


def note_content(
    *,
    prep_no: int,
    level: Optional[str],
    total: Optional[int],
    parsed: Optional[dict],
    talk_share: Optional[float],
    duration_seconds: int,
    followup: list[dict],
    compared: list[dict],
) -> str:
    """Notatka „Prep N — podsumowanie z Teams”: fakty, wnioski i co dalej.

    Bez surowego transkryptu i bez cytatów (cytat bywa daną osobową
    z rozmowy — zostaje w ocenie za bramką rekrutacji).
    """
    facts = [f"Czas: {max(1, round(duration_seconds / 60))} min"]
    if talk_share is not None:
        facts.append(f"kandydat mówił {round(talk_share * 100)}% czasu")
    lines = [f"# Prep {prep_no} — podsumowanie z Teams"]
    if level and parsed is not None:
        head = f"Ocena: {LEVEL_LABELS[level]}"
        if total is not None:
            head += f" ({total}%)"
        facts.insert(0, head)
        topics = parsed["topics"]
        if topics:
            done = sum(1 for t in topics if t["status"] == "covered")
            facts.append(f"tematy {done}/{len(topics)}")
        graded = [a for a in parsed["answers"] if a["kind"] in ("must", "question")]
        if graded:
            counts = {g: sum(1 for a in graded if a["grade"] == g) for g in GRADES}
            facts.append(
                f"odpowiedzi: {counts['strong']} mocne, {counts['general']} ogólne, "
                f"{counts['weak']} słabe"
            )
    lines.append(" · ".join(facts))
    summary = parsed.get("summary") if parsed else None
    lines.append(
        summary
        or "Podsumowanie AI jest niedostępne — pełny transkrypt "
        "jest w kalendarzu „Rozmowy u klienta”."
    )
    if level and parsed is not None:
        for title, key in (
            ("Dobrze", "went_well"),
            ("Nie tak", "went_wrong"),
            ("Dla prowadzącego", "improve"),
        ):
            if parsed.get(key):
                lines.append(f"{title}: " + "; ".join(parsed[key]))
        if prep_no == 1 and followup:
            lines.append(
                "Do powtórzenia na Prep 2: "
                + "; ".join(
                    f"{i + 1}) {f['label']} — {REASON_LABELS[f['reason']]}"
                    for i, f in enumerate(followup)
                )
            )
        if prep_no == 2 and compared:
            lines.append(
                "Punkty z Prepu 1: "
                + "; ".join(
                    f"{c['label']}: {REASON_LABELS.get(c['before'], c['before'])} → "
                    f"{GRADE_LABELS.get(c['after'], c['after'])}"
                    for c in compared
                )
            )
    return "\n\n".join(lines)
