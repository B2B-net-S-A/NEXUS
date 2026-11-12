"""Potwierdzenie usług dla klienta, jeden dokument na projekt (roadmapa E6.2).

Reguła ``cl.client_document`` z ``per`` = „projekt” i ``from`` = pierwszy
miesiąc (u klienta rozliczanego projektami: Service Delivery Confirmation od
listopada 2026). Dokument składamy z Time Sheet osób miesiąca: wiersze z tym
samym Task ID i opisem łączą się w jeden, suma MD = godziny / ``fields.md_hours``.

Dokument jest bez danych osobowych: bez nazwisk, a PDF bez autora
w metadanych (próbka klienta miała nazwisko w polu „Autor”). Task ID to
„Nr strumienia” z Time Sheet, a bez niego liczba godzin zadania — tak wyglądał
dokument przyjęty przez klienta za październik (odpowiedź rozliczeń z 12.11.2026:
„dopasuj cokolwiek z TS-a”).

Miesiąc z estymacją (``cl.estimate``) bierze plan, tak jak faktura do klienta:
etap „FORECAST” zamiast „ACTUAL”. Osoba z RCP do poprawy albo bez czytelnego
Time Sheet nie wchodzi do dokumentu i jest wypisana na liście.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from html import escape
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import DEFAULT_TZ
from app.models.client import Client
from app.models.client_settlement import ClientSettlement
from app.models.consultant_portal import CpDocument
from app.services.client_settlements import service, timesheet
from app.services.consultant_portal import documents as portal_documents

SUPPLIER = "B2B.net S.A."
PER_PROJECT = {"projekt", "project", "projekty"}
EN_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
#: Stany rozliczenia, które wchodzą do dokumentu (RCP do poprawy nie).
INCLUDED = ("checking", "ok", "warnings", "no_md", "accepted")


class DocumentError(service.SettlementError):
    pass


@dataclass
class Task:
    task_id: Optional[str]
    description: str
    hours: Decimal = Decimal("0")


@dataclass
class Project:
    name: str
    hours: Decimal = Decimal("0")
    people: int = 0
    accepted: int = 0
    order_numbers: list[str] = field(default_factory=list)
    tasks: dict[tuple[str, str], Task] = field(default_factory=dict)


def rule_for(rules: dict[str, dict[str, Any]], month: str) -> Optional[dict[str, str]]:
    """Parametry reguły, gdy obejmuje miesiąc i dokument jest per projekt."""

    rule = rules["cl.client_document"]
    if rule["level"] == "off":
        return None
    params = {k: str(v or "").strip() for k, v in rule["params"].items()}
    if params.get("per", "").lower() not in PER_PROJECT:
        return None
    start = params.get("from", "")
    if re.fullmatch(r"\d{4}-\d{2}", start) and month < start:
        return None
    return params


def _hours_text(value: Decimal) -> str:
    return f"{value.normalize():f}"


def _md_text(value: Decimal) -> str:
    return f"{value.normalize():f}"


async def _settlements(
    db: AsyncSession, client_id: int, month: str
) -> tuple[list[ClientSettlement], str]:
    """Rozliczenia miesiąca do dokumentu: plan, gdy miesiąc ma estymację
    (jak faktura do klienta), inaczej RCP faktyczne."""

    found = (
        await db.scalars(
            select(ClientSettlement).where(
                ClientSettlement.client_id == client_id,
                ClientSettlement.period_month == month,
            )
        )
    ).all()
    estimates = {s.contract_id: s for s in found if s.kind == service.ESTIMATE}
    actual = {s.contract_id: s for s in found if s.kind == service.ACTUAL}
    stage = "FORECAST" if estimates else "ACTUAL"
    chosen = []
    for contract_id in sorted(set(estimates) | set(actual)):
        estimate = estimates.get(contract_id)
        if estimate is not None and (
            estimate.status != "needs_fix" or contract_id not in actual
        ):
            chosen.append(estimate)
        else:
            chosen.append(actual[contract_id])
    return chosen, stage


async def collect(db: AsyncSession, client_id: int, month: str) -> dict[str, Any]:
    """Lista dokumentów miesiąca klienta: projekty, osoby, godziny, MD.

    Bez kwot: dokument mówi o godzinach, a kwota do klienta (z limitem puli
    zamówienia) jest w „Do faktury dla klienta”."""

    client = await db.get(Client, client_id)
    if client is None:
        raise DocumentError("Nie ma takiego klienta.", status=404)
    rules = await service.rules_for(db, client_id, month)
    params = rule_for(rules, month)
    base: dict[str, Any] = {
        "client_id": client_id,
        "month": month,
        "enabled": params is not None,
        "kind": (params or {}).get("kind") or "Service Delivery Confirmation",
        "stage": None,
        "projects": [],
        "skipped": [],
    }
    if params is None:
        return base
    projects, skipped, stage = await _projects(db, client, month, rules)
    base["stage"] = stage
    base["skipped"] = skipped
    base["projects"] = [
        {
            "project": p.name,
            "people": p.people,
            "accepted": p.accepted,
            "hours": f"{p.hours:.2f}",
            "md": f"{timesheet.md_from_hours(p.hours, timesheet.per_md(rules)):.3f}",
            "order_numbers": p.order_numbers,
            "tasks": len(p.tasks),
        }
        for p in projects
    ]
    return base


async def _projects(
    db: AsyncSession,
    client: Client,
    month: str,
    rules: dict[str, dict[str, Any]],
) -> tuple[list[Project], list[dict[str, str]], str]:
    settlements, stage = await _settlements(db, client.id, month)
    numbers = await service._order_numbers(
        db, [s.contract_id for s in settlements], month
    )
    projects: dict[str, Project] = {}
    skipped: list[dict[str, str]] = []
    for s in settlements:
        person = await service._contract(db, s.contract_id)
        if s.status not in INCLUDED:
            skipped.append({"person": person.name, "reason": "RCP do poprawy"})
            continue
        sheet = await _read(db, s)
        if sheet is None or not sheet.entries:
            skipped.append(
                {
                    "person": person.name,
                    "reason": "Brak Time Sheet w Excelu z godzinami",
                }
            )
            continue
        number = numbers.get(s.contract_id)
        for name, hours in sheet.hours_by_project().items():
            project = projects.setdefault(name, Project(name))
            project.hours += hours
            project.people += 1
            project.accepted += s.status == "accepted"
            if number and number not in project.order_numbers:
                project.order_numbers.append(number)
        for entry in sheet.entries:
            project = projects[sheet.project_of(entry)]
            key = (entry.task_id or "", entry.description.strip().lower())
            task = project.tasks.setdefault(
                key, Task(entry.task_id, entry.description.strip() or "—")
            )
            task.hours += entry.hours
    ordered = sorted(projects.values(), key=lambda p: p.name.lower())
    return ordered, skipped, stage


async def _read(
    db: AsyncSession, s: ClientSettlement
) -> Optional[timesheet.ParsedTimesheet]:
    if s.report_document_id is None:
        return None
    document = await db.get(CpDocument, s.report_document_id)
    if document is None or document.mime != timesheet.XLSX:
        return None
    try:
        content = portal_documents.path_for(document.file_path).read_bytes()
    except OSError:
        return None
    return await asyncio.to_thread(timesheet.parse, content, document.mime)


def render_html(
    *,
    kind: str,
    client_name: str,
    project: Project,
    month: str,
    stage: str,
    per_md: Decimal,
) -> str:
    year, mon = (int(x) for x in month.split("-"))
    rows = "".join(
        "<tr>"
        f"<td>{escape(task.task_id or _hours_text(task.hours) + 'h')}</td>"
        f"<td>{escape(task.description)}</td>"
        "</tr>"
        for task in project.tasks.values()
    )
    total_md = timesheet.md_from_hours(project.hours, per_md)
    meta = (
        ("Supplier", SUPPLIER),
        ("Customer", client_name),
        ("Project Name", project.name),
        ("Date", f"{EN_MONTHS[mon - 1]} {year}"),
        ("Order Number", ", ".join(project.order_numbers) or "—"),
        ("Stage", stage),
    )
    generated = datetime.now(ZoneInfo(DEFAULT_TZ)).strftime("%Y-%m-%d")
    return (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>{escape(kind)} {escape(project.name)} {year}-{mon:02d}</title><style>"
        "@page{size:A4;margin:18mm 16mm}"
        "body{font-family:'DejaVu Sans','Liberation Sans',sans-serif;font-size:10pt;color:#1f2933}"
        "h1{font-size:15pt;margin:0 0 4pt}h2{font-size:11pt;margin:14pt 0 4pt}"
        "table{border-collapse:collapse;width:100%}"
        ".meta th{text-align:left;width:32%;padding:2pt 8pt 2pt 0;color:#52606d;font-weight:600}"
        ".meta td{padding:2pt 0}"
        ".tasks th{text-align:left;border-bottom:1px solid #9aa5b1;padding:4pt;font-size:9pt;color:#52606d}"
        ".tasks td{border-bottom:0.5px solid #d9e2ec;padding:3pt 4pt;vertical-align:top}"
        ".tasks td:first-child{width:22%;white-space:nowrap}"
        ".total{margin-top:10pt;font-weight:700;font-size:11pt}"
        ".foot{margin-top:18pt;font-size:8pt;color:#7b8794}"
        "</style></head><body>"
        f"<h1>{escape(kind)}</h1>"
        "<table class='meta'>"
        + "".join(
            f"<tr><th>{escape(k)}:</th><td>{escape(v)}</td></tr>" for k, v in meta
        )
        + "</table><h2>Tasks List</h2>"
        "<table class='tasks'><thead><tr><th>Task ID</th><th>Description</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
        f"<p class='total'>TOTAL MDs: {escape(_md_text(total_md))}</p>"
        f"<p class='foot'>Generated {generated}.</p>"
        "</body></html>"
    )


def render_pdf(html: str) -> bytes:
    from weasyprint import HTML

    return HTML(string=html).write_pdf()


def file_name(project: str, month: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9.\-]+", "_", project).strip("_") or "projekt"
    return f"SDC_{safe}_{month}.pdf"


async def document(
    db: AsyncSession, client_id: int, month: str, project: str
) -> tuple[bytes, str]:
    """PDF dla jednego projektu i nazwa pliku."""

    client = await db.get(Client, client_id)
    if client is None:
        raise DocumentError("Nie ma takiego klienta.", status=404)
    rules = await service.rules_for(db, client_id, month)
    params = rule_for(rules, month)
    if params is None:
        raise DocumentError(
            "Klient nie ma w regułach dokumentu na projekt za ten miesiąc.", status=404
        )
    projects, _skipped, stage = await _projects(db, client, month, rules)
    found = next((p for p in projects if p.name == project), None)
    if found is None:
        raise DocumentError(
            "W tym miesiącu nie ma godzin dla tego projektu.", status=404
        )
    html = render_html(
        kind=params.get("kind") or "Service Delivery Confirmation",
        client_name=client.name,
        project=found,
        month=month,
        stage=stage,
        per_md=timesheet.per_md(rules),
    )
    content = await asyncio.to_thread(render_pdf, html)
    return content, file_name(project, month)
