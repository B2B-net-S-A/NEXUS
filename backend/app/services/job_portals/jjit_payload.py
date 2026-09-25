"""Ogłoszenie dla JustJoin.IT / RocketJobs — czyste funkcje (0381).

Wejście: ``PostingContent.job`` (biała lista ``public_job_payload`` — nigdy
klient ani stawka) + ustawienia ogłoszenia wpisane przez Delivery Leada
(``options``). Wyjście: ciało ``POST …/job-advertisements`` z dokumentacji
Employer Public API (1EP). Bez I/O — identyfikatory umiejętności i sposób
płatności podaje wołający.

Reguły dostawcy (dokumentacja 1EP, changelog do 03.09.2026):

* JustJoin.IT: 1–10 umiejętności, wszystkie ``required: true`` (mile widziane
  trafiają wyłącznie do opisu); RocketJobs: 1–8 wymaganych + 0–8 mile widzianych.
* ``employmentTypes``: najwyżej 2, jedna waluta, ``b2b`` tylko ``net``,
  widełki > 0, najwyżej 2 miejsca po przecinku, ``to`` ≤ 3 × ``from``.
* ``hybridWorkSchedule`` tylko przy ``hybrid``: dni biuro + dom = 5, każde 1–4.
* ``body`` HTML, co najmniej 5 znaków (portal i tak sanityzuje).

Widełki (decyzja Artura 25.09.2026) są OPCJONALNE i wpisuje je człowiek —
nigdy nie wyliczamy ich z budżetu rekrutacji ani ze stawki Championa.
"""

from __future__ import annotations

import html
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Optional

BOARD_JJIT = "justjoinit"
BOARD_ROCKETJOBS = "rocketjobs"
BOARDS = (BOARD_JJIT, BOARD_ROCKETJOBS)

REQUIRED_LIMIT = {BOARD_JJIT: 10, BOARD_ROCKETJOBS: 8}
NICE_LIMIT = {BOARD_JJIT: 0, BOARD_ROCKETJOBS: 8}

SALARY_UNITS = ("hour", "month")
WORKPLACE_TYPES = ("remote", "office", "hybrid")
MAX_SALARY_SPREAD = 3

OPTION_KEYS = (
    "category",
    "experience_level",
    "working_time",
    "workplace_type",
    "office_days",
    "city",
    "salary",
)

_REMOTE_TO_WORKPLACE = {"onsite": "office", "hybrid": "hybrid", "remote": "remote"}
_SENIORITY_TO_LEVEL = {
    "junior": "junior",
    "mid": "mid",
    "senior": "senior",
    "lead": "senior",
    "architect": "senior",
}
_WORK_MODE_TO_TIME = {"fulltime": "full_time", "parttime": "part_time"}


# ── Ustawienia ogłoszenia ───────────────────────────────────────────────────


def _text(value: Any, limit: int = 120) -> Optional[str]:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text[:limit] or None


def _money(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        amount = Decimal(str(value).replace(",", ".").replace(" ", ""))
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite():
        return None
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def normalize_options(raw: Any) -> dict[str, Any]:
    """Znane klucze w stałym kształcie; nieznane odpadają (JSONB bez śmieci)."""
    data = raw if isinstance(raw, dict) else {}
    office_days = data.get("office_days")
    try:
        office_days = int(office_days) if office_days not in (None, "") else None
    except (TypeError, ValueError):
        office_days = None
    salary_raw = data.get("salary") if isinstance(data.get("salary"), dict) else None
    salary: Optional[dict[str, Any]] = None
    if salary_raw is not None:
        low, high = _money(salary_raw.get("from")), _money(salary_raw.get("to"))
        unit = (
            salary_raw.get("unit") if salary_raw.get("unit") in SALARY_UNITS else None
        )
        if low is not None or high is not None:
            salary = {
                "from": float(low) if low is not None else None,
                "to": float(high) if high is not None else None,
                "unit": unit or "month",
            }
    workplace = data.get("workplace_type")
    return {
        "category": _text(data.get("category"), 80),
        "experience_level": _text(data.get("experience_level"), 40),
        "working_time": _text(data.get("working_time"), 40),
        "workplace_type": workplace if workplace in WORKPLACE_TYPES else None,
        "office_days": office_days,
        "city": _text(data.get("city"), 120),
        "salary": salary,
    }


def default_options(
    params: dict[str, Any], *, work_mode: Optional[str] = None
) -> dict[str, Any]:
    """Podpowiedź z rekrutacji. Kategoria zawsze pusta — wybiera człowiek."""
    remote = params.get("remote_policy")
    workplace = _REMOTE_TO_WORKPLACE.get(str(remote or ""))
    office_days = params.get("onsite_days_per_week")
    return normalize_options(
        {
            "category": None,
            "experience_level": _SENIORITY_TO_LEVEL.get(
                str(params.get("seniority") or "")
            ),
            "working_time": _WORK_MODE_TO_TIME.get(str(work_mode or ""), "full_time"),
            "workplace_type": workplace,
            "office_days": office_days if workplace == "hybrid" else None,
            "city": params.get("city"),
            "salary": None,
        }
    )


def skill_split(board: str, job: dict[str, Any]) -> tuple[list[str], list[str]]:
    """(wymagane, mile widziane) przycięte do limitów portalu."""
    must = [
        str(item.get("name") if isinstance(item, dict) else item).strip()
        for item in job.get("must") or []
    ]
    nice = [str(item).strip() for item in job.get("nice") or []]
    must = _unique([m for m in must if m])
    nice = [
        n
        for n in _unique([n for n in nice if n])
        if n.casefold() not in {m.casefold() for m in must}
    ]
    return must[: REQUIRED_LIMIT[board]], nice[: NICE_LIMIT[board]]


def _unique(names: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for name in names:
        key = name.casefold()
        if key not in seen:
            seen.add(key)
            out.append(name[:100])
    return out


def validate(board: str, job: dict[str, Any], options: dict[str, Any]) -> list[str]:
    """Braki po polsku — sprawdzane przed kolejką, żeby nie palić kredytów."""
    problems: list[str] = []
    if board not in BOARDS:
        return ["Nieznany portal."]
    if not options.get("category"):
        problems.append("Wybierz kategorię ogłoszenia.")
    if not options.get("experience_level"):
        problems.append("Wybierz poziom doświadczenia.")
    if not options.get("working_time"):
        problems.append("Wybierz wymiar pracy.")
    workplace = options.get("workplace_type")
    if not workplace:
        problems.append("Wybierz tryb pracy (zdalnie, biuro albo hybrydowo).")
    office_days = options.get("office_days")
    if office_days is not None:
        if workplace != "hybrid":
            problems.append("Dni w biurze podaje się tylko przy pracy hybrydowej.")
        elif not 1 <= office_days <= 4:
            problems.append("Dni w biurze przy pracy hybrydowej: od 1 do 4.")
    if not options.get("city"):
        problems.append("Podaj miasto — portal wymaga co najmniej jednej lokalizacji.")
    must, _nice = skill_split(board, job)
    if not must:
        problems.append("Rekrutacja nie ma wymaganych umiejętności (must-have).")
    salary = options.get("salary")
    if salary:
        low, high = salary.get("from"), salary.get("to")
        if low is None or high is None:
            problems.append("Widełki: podaj obie kwoty albo zostaw obie puste.")
        elif low <= 0:
            problems.append("Widełki: kwota „od” musi być większa od zera.")
        elif high < low:
            problems.append("Widełki: kwota „do” nie może być mniejsza niż „od”.")
        elif high > low * MAX_SALARY_SPREAD:
            problems.append(
                "Widełki: kwota „do” może być najwyżej 3 razy większa niż „od”."
            )
    body = build_body(job)
    if len(_strip_tags(body)) < 5:
        problems.append("Opis publiczny jest pusty — uzupełnij go na stronie kariery.")
    return problems


# ── Treść ────────────────────────────────────────────────────────────────────


def _strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value).strip()


def _paragraphs(text: Optional[str]) -> list[str]:
    if not text:
        return []
    return [" ".join(p.split()) for p in re.split(r"\n\s*\n", text) if p.strip()]


def build_body(job: dict[str, Any]) -> str:
    """HTML ogłoszenia z białej listy; każdy tekst przez ``html.escape``."""
    show = job.get("show") if isinstance(job.get("show"), dict) else {}
    parts: list[str] = []
    subtitle = job.get("subtitle")
    if subtitle:
        parts.append(f"<p><strong>{html.escape(str(subtitle))}</strong></p>")
    for paragraph in _paragraphs(job.get("about")):
        parts.append(f"<p>{html.escape(paragraph)}</p>")
    must = [
        str(item.get("name") if isinstance(item, dict) else item)
        for item in job.get("must") or []
    ]
    if must and show.get("must", True):
        parts.append("<h3>Wymagania</h3>")
        parts.append(_list(must))
    nice = [str(item) for item in job.get("nice") or []]
    if nice and show.get("nice", True):
        parts.append("<h3>Mile widziane</h3>")
        parts.append(_list(nice))
    params = job.get("params") if isinstance(job.get("params"), dict) else {}
    details = []
    if params.get("start"):
        details.append(f"Start: {params['start']}")
    if params.get("duration"):
        details.append(f"Czas trwania: {params['duration']}")
    if details and show.get("params", True):
        parts.append("<h3>Szczegóły</h3>")
        parts.append(_list(details))
    return "".join(parts)


def _list(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{html.escape(i)}</li>" for i in items) + "</ul>"


# ── Ciało żądania ───────────────────────────────────────────────────────────


def skill_key(name: str) -> str:
    """Klucz dopasowania nazwy umiejętności do odpowiedzi ``PUT /skills``.

    Bez wielkości liter, spacji i kropek, ale z ``+``/``#`` (C++ ≠ C ≠ C#).
    """
    return re.sub(r"[^0-9a-z+#]", "", name.casefold())


def requirements(
    board: str, job: dict[str, Any], skill_ids: dict[str, dict[str, str]]
) -> list[dict[str, Any]]:
    """``skill_ids``: ``skill_key`` nazwy → ``{"id", "name"}`` z ``PUT /skills``."""
    must, nice = skill_split(board, job)
    out: list[dict[str, Any]] = []
    for required, names in ((True, must), (False, nice)):
        for name in names:
            skill = skill_ids.get(skill_key(name))
            if not skill:
                continue
            out.append(
                {
                    "skillId": skill["id"],
                    "skillName": skill["name"],
                    "level": None,
                    "ordinal": len(out),
                    "required": required,
                }
            )
    return out


def employment_types(options: dict[str, Any]) -> list[dict[str, Any]]:
    salary = options.get("salary")
    return [
        {
            "type": "b2b",
            "currency": "PLN",
            "amountType": "net",
            "salary": (
                {"from": salary["from"], "to": salary["to"], "unit": salary["unit"]}
                if salary and salary.get("from") and salary.get("to")
                else None
            ),
        }
    ]


def hybrid_schedule(options: dict[str, Any]) -> Optional[dict[str, int]]:
    days = options.get("office_days")
    if options.get("workplace_type") != "hybrid" or not days or not 1 <= days <= 4:
        return None
    return {"officeDays": days, "remoteDays": 5 - days}


def content_fields(
    board: str,
    job: dict[str, Any],
    options: dict[str, Any],
    *,
    apply_url: str,
    skill_ids: dict[str, dict[str, str]],
) -> dict[str, Any]:
    """Pola wspólne dla utworzenia i edycji (bez tytułu, płatności, portalu)."""
    return {
        "body": build_body(job),
        "workplaceType": options["workplace_type"],
        "workingTime": options["working_time"],
        "experienceLevel": options["experience_level"],
        "customConsent": None,
        "futureConsent": None,
        "apply": {"url": apply_url, "email": None},
        "requirements": requirements(board, job, skill_ids),
        "languages": None,
        "locations": [
            {
                "countryCode": "PL",
                "street": "",
                "city": options["city"],
                "geoCoordinates": None,
            }
        ],
        "employmentTypes": employment_types(options),
        "hybridWorkSchedule": hybrid_schedule(options),
    }


def create_body(
    board: str,
    *,
    title: str,
    job: dict[str, Any],
    options: dict[str, Any],
    apply_url: str,
    skill_ids: dict[str, dict[str, str]],
    payment: dict[str, str],
    external_id: str,
) -> dict[str, Any]:
    body = {
        "jobBoard": board,
        "title": title,
        "informationClause": None,
        "contact": None,
        "hiringCompany": None,
        "category": options["category"],
        "payment": payment,
        "externalId": external_id,
    }
    body.update(
        content_fields(board, job, options, apply_url=apply_url, skill_ids=skill_ids)
    )
    return body


def update_body(
    board: str,
    *,
    current: dict[str, Any],
    job: dict[str, Any],
    options: dict[str, Any],
    apply_url: str,
    skill_ids: dict[str, dict[str, str]],
) -> dict[str, Any]:
    """``PUT`` podmienia CAŁE ogłoszenie: klauzula, kontakt i tagi idą z ``GET``.

    Bez ``jobBoard``, ``title``, ``payment``, ``externalId`` (dokumentacja).
    Kategoria w edycji to ``categories`` (tablica z jednym kluczem).
    """
    body = content_fields(board, job, options, apply_url=apply_url, skill_ids=skill_ids)
    body["informationClause"] = current.get("informationClause") or ""
    body["contact"] = current.get("contact")
    body["publicTags"] = current.get("publicTags") or []
    body["categories"] = [options["category"]]
    for key in ("customConsent", "futureConsent"):
        if current.get(key) is not None:
            body[key] = current[key]
    return body


def pick_payment(
    board: str, balance: dict[str, Any], *, now_iso: str
) -> Optional[dict[str, str]]:
    """Kod z pozostałym użyciem (najpierw kończący się najwcześniej), inaczej
    aktywna subskrypcja — kolejność z dokumentacji dostawcy."""

    def usable(item: dict[str, Any]) -> bool:
        if str(item.get("jobBoard") or board).casefold() != board:
            return False
        try:
            left = int(item.get("maxUsage") or 0) - int(item.get("currentUsage") or 0)
        except (TypeError, ValueError):
            return False
        return left > 0

    codes = [
        c
        for c in balance.get("codes") or []
        if isinstance(c, dict)
        and c.get("name")
        and usable(c)
        and (not c.get("expiresAt") or str(c["expiresAt"]) > now_iso)
    ]
    codes.sort(key=lambda c: str(c.get("expiresAt") or "9999"))
    if codes:
        return {"type": "Code", "id": str(codes[0]["name"])}
    for sub in balance.get("subscriptions") or []:
        if (
            isinstance(sub, dict)
            and sub.get("id")
            and sub.get("isActive")
            and usable(sub)
        ):
            return {"type": "Subscription", "id": str(sub["id"])}
    return None
