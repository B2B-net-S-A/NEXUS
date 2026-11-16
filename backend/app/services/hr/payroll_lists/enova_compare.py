"""Porównanie listy płac NEXUSA z listą z Enovy, osoba po osobie, do grosza (K7b).

Bloker przełączenia z Enovy (decyzja Artura 13.11.2026): 2–3 miesiące list
liczonych równolegle muszą się zgadzać do grosza na każdej osobie. Płace
wczytują eksport listy z Enovy (ten sam plik co do LP w K3c — XLSX albo CSV,
wiersz na osobę) przy liście NEXUSA tego miesiąca i dostają różnice per osoba
i kwota. Plik nie jest zapisywany; ślad (``payroll_enova_compared``) niesie
tylko liczby osób, bez kwot i nazwisk.

Dopasowanie osób: imię i nazwisko jako zbiór słów bez znaków diakrytycznych
(„Kowalski Jan” = „Jan Kowalski”). Osoba z kilkoma pozycjami na liście NEXUSA
(UoP i zlecenie, dwa zlecenia) porównuje się sumą — Enova daje wiersz na osobę.
Kwoty pracodawcy porównujemy tylko, gdy plik ma ich kolumny.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_payroll_lists import PayrollList, PayrollListLine
from app.models.user import User
from app.services.finance_ledger import identifiers
from app.services.hr import audit
from app.services.hr.payroll_lists.ledger_post import row_of
from app.services.ledger import payroll_lists as enova

#: Porównywane kwoty: klucz → (etykieta, kolumny pliku, które ją dają).
FIELDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "gross": ("Brutto", ("gross",)),
    "emp_social": (
        "Składki pracownika",
        ("emp_social", "emp_pension", "emp_disability", "emp_sickness"),
    ),
    "health": ("Zdrowotna", ("health",)),
    "pit": ("Zaliczka PIT", ("pit",)),
    "ppk_emp": ("PPK pracownika", ("ppk_emp",)),
    "net": ("Do wypłaty", ("net",)),
    "er_social": (
        "Składki pracodawcy",
        ("er_social", "er_pension", "er_disability", "accident"),
    ),
    "fp": ("FP i FS", ("fp", "fs")),
    "fgsp": ("FGŚP", ("fgsp",)),
    "ppk_er": ("PPK pracodawcy", ("ppk_er",)),
}


def name_key(name: str) -> frozenset[str]:
    return frozenset(
        identifiers.fold(token) for token in name.replace(",", " ").split() if token
    )


def _values(amounts: dict[str, int]) -> dict[str, int]:
    return {
        "gross": amounts.get("gross", 0),
        "emp_social": enova.employee_social(amounts),
        "health": amounts.get("health", 0),
        "pit": amounts.get("pit", 0),
        "ppk_emp": amounts.get("ppk_emp", 0),
        "net": amounts.get("net", 0),
        "er_social": enova.employer_social(amounts),
        "fp": amounts.get("fp", 0) + amounts.get("fs", 0),
        "fgsp": amounts.get("fgsp", 0),
        "ppk_er": amounts.get("ppk_er", 0),
    }


def compare_rows(
    nexus: list[enova.PayrollRow], parsed: enova.ParsedList
) -> dict[str, Any]:
    """Czysta funkcja: różnice per osoba (grosze)."""

    present = set(parsed.headers)
    fields = [key for key, (_label, cols) in FIELDS.items() if present & set(cols)]
    ours: dict[frozenset[str], dict[str, Any]] = {}
    for row in nexus:
        key = name_key(row.person or "")
        bucket = ours.setdefault(
            key, {"name": row.person or "", "amounts": defaultdict(int), "lines": 0}
        )
        for name, value in _values(row.amounts).items():
            bucket["amounts"][name] += value
        bucket["lines"] += 1
    theirs: dict[frozenset[str], list[enova.PayrollRow]] = defaultdict(list)
    for row in parsed.rows:
        theirs[name_key(row.person or "")].append(row)
    people: list[dict[str, Any]] = []
    only_enova: list[dict[str, Any]] = []
    for key, rows in theirs.items():
        if not key or key not in ours or len(rows) != 1:
            for row in rows:
                only_enova.append(
                    {
                        "line": row.line,
                        "person": row.person or "",
                        "reason": "two_rows"
                        if len(rows) > 1 and key in ours
                        else "no_match",
                    }
                )
            continue
        mine = ours[key]
        other = _values(rows[0].amounts)
        diffs = [
            {
                "key": name,
                "label": FIELDS[name][0],
                "nexus": mine["amounts"][name],
                "enova": other[name],
                "diff": mine["amounts"][name] - other[name],
            }
            for name in fields
        ]
        people.append(
            {
                "person": mine["name"],
                "enova_line": rows[0].line,
                "nexus_lines": mine["lines"],
                "equal": all(item["diff"] == 0 for item in diffs),
                "fields": diffs,
            }
        )
    matched = {name_key(p["person"]) for p in people}
    only_nexus = [
        {"person": data["name"]} for key, data in ours.items() if key not in matched
    ]
    people.sort(key=lambda item: (item["equal"], item["person"].casefold()))
    totals = {
        name: {
            "label": FIELDS[name][0],
            "nexus": sum(item["amounts"][name] for item in ours.values()),
            "enova": sum(_values(row.amounts)[name] for row in parsed.rows),
        }
        for name in fields
    }
    for item in totals.values():
        item["diff"] = item["nexus"] - item["enova"]
    equal = sum(1 for item in people if item["equal"])
    return {
        "fields": [{"key": key, "label": FIELDS[key][0]} for key in fields],
        "people": people,
        "only_nexus": only_nexus,
        "only_enova": only_enova,
        "totals": totals,
        "summary": {
            "matched": len(people),
            "equal": equal,
            "different": len(people) - equal,
            "only_nexus": len(only_nexus),
            "only_enova": len(only_enova),
            "all_equal": equal == len(people) and not only_nexus and not only_enova,
        },
        "errors": parsed.errors[:50],
        "warnings": parsed.warnings[:50],
        "problems": parsed.problems,
    }


async def compare(
    db: AsyncSession, *, actor: User, lst: PayrollList, content: bytes
) -> dict[str, Any]:
    parsed = enova.parse(content)
    lines = list(
        await db.scalars(
            select(PayrollListLine)
            .where(PayrollListLine.list_id == lst.id)
            .order_by(PayrollListLine.id)
        )
    )
    result = compare_rows([row_of(line) for line in lines if line.result], parsed)
    result["list"] = {"id": lst.id, "number": lst.number, "status": lst.status}
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=None,
        entity_type="payroll_list",
        entity_id=lst.id,
        action="payroll_enova_compared",
        sensitivity="payroll",
        details={"number": lst.number, **result["summary"]},
    )
    return result


__all__ = ["FIELDS", "compare", "compare_rows", "name_key"]
