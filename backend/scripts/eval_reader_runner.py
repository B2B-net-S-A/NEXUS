"""Jeden przebieg korpusu czytnika na kodzie z podanego katalogu ``backend/``.

Woła go ``scripts/eval_reader.py`` osobnym procesem dla każdej rewizji: ``--app``
wskazuje rozpakowane ``backend/app`` z tej rewizji, a ten plik (z HEAD) zna format
przypadków. Funkcje czytnika, których starsza rewizja nie ma, kończą przypadek
błędem — liczy się wtedy jako nietrafiony, a nie wywraca przebiegu.

Czytniki:
* ``cv`` — odczyt treści „Nowego CV”: HTML edytora i zapis generatora
  (``cv_json_from_editor_html``, ``restore_experience_dates``,
  ``NewCvDocument.from_cv_json``, ``parse_dates``, ``split_degree``, ``lang_parts``).
  Bez bazy.
* ``rozliczenia`` — czytnik poczty rozliczeń end-to-end: ``mailbox.run_once`` na
  atrapie skrzynki, z osobami, klientami i zamówieniami z przypadku w czystej bazie
  (schemat z ``Base.metadata`` tej rewizji). Wynik to zapisane ``CpDocument``:
  rodzaj, kontrakt osoby, okres.

Wynik: JSON z listą jednostek ``{id, pole, ok, oczekiwane, jest}`` w ``--wynik``.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import copy
import json
import os
import sys
import tempfile
import traceback
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Optional


def load_cases(dirs: list[str]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for raw in dirs:
        root = Path(raw)
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.json")):
            if path.name.startswith("_"):
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            for case in data if isinstance(data, list) else [data]:
                case["_plik"] = str(path)
                case["_katalog"] = str(path.parent)
                cases.append(case)
    return cases


def _unit(
    case: dict, field: str, ok: bool, expected: Any, got: Any, key: str = ""
) -> dict:
    return {
        "id": case["id"] + (f"#{key}" if key else ""),
        "pole": field,
        "ok": bool(ok),
        "oczekiwane": expected,
        "jest": got,
        "zrodlo": case.get("_zrodlo", ""),
    }


def _failed(case: dict, fields: list[str], error: str) -> list[dict]:
    return [{**_unit(case, f, False, "—", "błąd"), "blad": error} for f in fields]


def _subset(expected: dict, got: dict) -> bool:
    return all(got.get(k) == v for k, v in expected.items())


# ── CV ─────────────────────────────────────────────────────────────────────────


def _cv_document(case: dict):
    from app.services.cv_new_layout.document import NewCvDocument

    inp = case.get("wejscie") or {}
    today = date.fromisoformat(case.get("dzis") or "2026-11-26")
    data = copy.deepcopy(inp.get("generator") or {})
    data.setdefault("language", inp.get("jezyk") or "pl")
    if inp.get("blind"):
        data["blind_cv"] = True
    source = inp.get("zrodlo")
    if source:
        from app.services.cv_source_dates import restore_experience_dates

        restore_experience_dates(data, source, today)
    html = inp.get("html")
    if html:
        from app.services.cv_new_content import cv_json_from_editor_html

        content = cv_json_from_editor_html(
            html,
            language=data["language"],
            blind=bool(inp.get("blind")),
            fallback=data,
        )
        data = {**data, **content.cv_json}
    return NewCvDocument.from_cv_json(data), today


def _parsed_fields(case: dict) -> dict[str, list[dict]]:
    """Etap odczytu pliku CV (``cv_parser``): wynik modelu z przypadku (zapisany
    przy odczycie) przechodzi tę samą obróbkę co u rekrutera; bez wyniku modelu
    działa sama heurystyka (nazwa z nagłówka, kontakt z regexu)."""

    from app.services import cv_parser

    spec = case["wejscie"]["odczyt"]
    text = spec.get("tekst") or ""
    model = spec.get("model")
    if model is None:
        out = cv_parser.normalize_cv_output(cv_parser._regex_fallback(text))
    else:
        out = cv_parser.finalize_claude_cv_output(copy.deepcopy(model), text)
    roles = [
        {
            "od": job.get("start"),
            "do": job.get("end"),
            "firma": job.get("company"),
            "stanowisko": job.get("role"),
        }
        for job in out.get("experience") or []
    ]
    schools = [
        {
            "uczelnia": school.get("school"),
            "kierunek": school.get("field"),
            "stopien": school.get("degree"),
            "rok": school.get("year"),
        }
        for school in out.get("education") or []
    ]
    return {
        "daty": roles,
        "edukacja": schools,
        "nazwa": [{"imie": out.get("first_name"), "nazwisko": out.get("last_name")}],
        "jezyki": [
            {"jezyk": x} if isinstance(x, str) else x
            for x in out.get("languages") or []
        ],
    }


def _cv_fields(case: dict) -> dict[str, list[dict]]:
    if (case.get("wejscie") or {}).get("odczyt") is not None:
        return _parsed_fields(case)
    from app.services.cv_new_layout import facts

    doc, today = _cv_document(case)
    now = facts.year_fraction(today)
    language = doc.language
    roles = []
    for role in doc.experience:
        span = facts.parse_dates(role.dates, now)
        roles.append(
            {
                "daty": role.dates,
                "staz": facts.duration_text(span, language),
                "firma": role.company,
                "stanowisko": role.position,
            }
        )
    schools = []
    for school in doc.education:
        field_, degree = facts.split_degree(school.degree)
        schools.append(
            {
                "uczelnia": school.institution,
                "kierunek": field_,
                "stopien": degree,
                "rok": facts.last_year(school.dates),
                "daty": school.dates,
            }
        )
    languages = []
    for entry in doc.languages:
        name, level = facts.lang_parts(entry)
        rank, label = facts.lang_level(level, language)
        languages.append(
            {
                "jezyk": name,
                "kod": facts.lang_code(name),
                "poziom": label,
                "stopien": rank,
            }
        )
    return {
        "daty": roles,
        "edukacja": schools,
        "nazwa": [{"imie_nazwisko": doc.name, "stanowisko": doc.position}]
        + [{"stanowisko_roli": r["stanowisko"]} for r in roles],
        "jezyki": languages,
    }


def _score_lists(case: dict, field: str, expected: list, got: list) -> list[dict]:
    """Każdy oczekiwany wpis to jednostka: wpis o tym samym numerze ma te pola.

    Wpis z ``"_brak": true`` oznacza, że wpisu o tym numerze ma nie być
    (np. stanowisko z nagłówka nie może trafić do języków).
    """

    units = []
    for index, want in enumerate(expected):
        want = dict(want)
        absent = want.pop("_brak", False)
        have = got[index] if index < len(got) else None
        if absent:
            ok = have is None or not _subset(want, have)
        else:
            ok = have is not None and _subset(want, have)
        units.append(_unit(case, field, ok, want, have, key=f"{field}{index + 1}"))
    count = case.get("oczekiwane", {}).get(f"liczba_{field}")
    if count is not None:
        units.append(
            _unit(
                case, field, len(got) == count, count, len(got), key=f"{field}#liczba"
            )
        )
    return units


def run_cv(cases: list[dict]) -> list[dict]:
    units: list[dict] = []
    for case in cases:
        expected = case.get("oczekiwane") or {}
        fields = [f for f in ("daty", "edukacja", "nazwa", "jezyki") if f in expected]
        try:
            got = _cv_fields(case)
        except Exception as exc:  # starsza rewizja bez funkcji albo wyjątek czytnika
            units.extend(_failed(case, fields, f"{type(exc).__name__}: {exc}"))
            continue
        for field in fields:
            units.extend(_score_lists(case, field, expected[field], got[field]))
    return units


# ── Rozliczenia ───────────────────────────────────────────────────────────────


def _filled(model, values: dict, today: date) -> dict:
    """Wartości dla kolumn NOT NULL bez domyślnej, których przypadek nie podaje.

    Kolumny modeli zmieniają się między rewizjami; przypadek opisuje tylko to,
    co czyta czytnik (imię, adres, klient), resztę wypełnia się neutralnie.
    """

    import enum

    from sqlalchemy import (
        JSON,
        Boolean,
        Date,
        DateTime,
        Enum,
        Integer,
        Numeric,
        SmallInteger,
        String,
        Text,
    )
    from sqlalchemy.dialects.postgresql import ARRAY, JSONB

    out = dict(values)
    for column in model.__table__.columns:
        if column.key in out or column.primary_key or column.nullable:
            continue
        if column.default is not None or column.server_default is not None:
            continue
        kind = column.type
        if isinstance(kind, Enum):
            choices = kind.enum_class or kind.enums
            out[column.key] = (
                list(choices)[0]
                if isinstance(choices, type) and issubclass(choices, enum.Enum)
                else list(choices)[0]
            )
        elif isinstance(kind, Boolean):
            out[column.key] = False
        elif isinstance(kind, (Integer, SmallInteger, Numeric)):
            out[column.key] = 0
        elif isinstance(kind, DateTime):
            out[column.key] = datetime.combine(today, time(12), tzinfo=timezone.utc)
        elif isinstance(kind, Date):
            out[column.key] = today
        elif isinstance(kind, (JSON, JSONB)):
            out[column.key] = {}
        elif isinstance(kind, ARRAY):
            out[column.key] = []
        elif isinstance(kind, (String, Text)):
            out[column.key] = "korpus"
    return out


def _day(value: Optional[str]) -> Optional[date]:
    return date.fromisoformat(value) if value else None


async def _seed(db, case: dict, today: date) -> dict[str, int]:
    """Klienci, użytkownicy, osoby z kontraktami i zamówienia z przypadku."""

    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contact import Contact
    from app.models.contract import Contract, ContractStatus, ContractType
    from app.models.user import User, UserRole

    def add(model, **values):
        row = model(**_filled(model, values, today))
        db.add(row)
        return row

    users: dict[str, int] = {}
    for key, spec in (case.get("uzytkownicy") or {}).items():
        role = UserRole(spec.get("rola", "recruiter"))
        row = add(
            User,
            email=spec["email"],
            name=spec.get("nazwa", key),
            role=role,
            roles=[role.value],
            is_active=True,
            profile_completed=True,
        )
        await db.flush()
        users[key] = row.id

    clients: dict[str, int] = {}
    for key, spec in (case.get("klienci") or {}).items():
        # Jawne ``id``: polityki klientów są po ID produkcji (BIK 18, Polkomtel 15).
        extra = {"id": spec["id"]} if spec.get("id") else {}
        row = add(Client, name=spec.get("nazwa", key), nip=spec.get("nip"), **extra)
        await db.flush()
        clients[key] = row.id
        for address in spec.get("kontakty") or []:
            add(Contact, client_id=row.id, name=address.split("@")[0], email=address)
        if spec.get("dl"):
            from app.models.team_structure import DeliveryLeadClientAssignment

            add(
                DeliveryLeadClientAssignment,
                delivery_lead_user_id=users[spec["dl"]],
                client_id=row.id,
                is_head=True,
            )
    await db.flush()

    contracts: dict[str, int] = {}
    for key, spec in (case.get("osoby") or {}).items():
        candidate = add(
            Candidate,
            name=spec.get("imie", ""),
            lastname=spec.get("nazwisko", ""),
            email=spec.get("email"),
        )
        await db.flush()
        for index, deal in enumerate(spec.get("kontrakty") or [{}]):
            client = deal.get("klient") or spec.get("klient")
            if client and client not in clients:
                row = add(Client, name=client)
                await db.flush()
                clients[client] = row.id
            contract = add(
                Contract,
                candidate_id=candidate.id,
                client_id=clients.get(client) if client else None,
                status=ContractStatus(deal.get("status", spec.get("status", "active"))),
                contract_type=ContractType(deal.get("typ", "b2b")),
                start_date=_day(deal.get("od", spec.get("od")))
                or date(today.year - 1, 1, 1),
                end_date=_day(deal.get("do", spec.get("do"))),
                candidate_email=deal.get(
                    "email_kontraktu", spec.get("email_kontraktu")
                ),
            )
            await db.flush()
            contracts[key if index == 0 else f"{key}#{index + 1}"] = contract.id

    if case.get("zamowienia"):
        from app.models.client_order import ClientOrder
        from app.models.client_order_group import ClientOrderGroup

        for spec in case["zamowienia"]:
            group = add(
                ClientOrderGroup,
                client_id=clients[spec["klient"]],
                order_number=spec["numer"],
            )
            await db.flush()
            for person in spec.get("osoby") or []:
                add(
                    ClientOrder,
                    order_group_id=group.id,
                    client_id=clients[spec["klient"]],
                    contract_id=contracts[person],
                    title=spec.get("tytul", spec["numer"]),
                )
    await db.flush()
    return contracts


def _sheet_bytes(sheets: dict) -> bytes:
    """Arkusz z przypadku: ``{"Arkusz1": [["Imię i nazwisko", "Jan"], …]}``."""

    import io

    from openpyxl import Workbook

    book = Workbook()
    book.remove(book.active)
    for title, rows in sheets.items():
        sheet = book.create_sheet(title[:31])
        for row in rows:
            sheet.append(row)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


# Polskie litery w Helvetice przez /Differences (nazwy glifów z glyphlist), żeby
# pdfplumber oddał „ą”, a nie znak zastępczy. Bez zewnętrznych bibliotek (WeasyPrint
# potrzebuje pango, którego na laptopie i w sicie CI nie ma).
_PL_GLYPHS = {
    "ą": "aogonek", "ć": "cacute", "ę": "eogonek", "ł": "lslash", "ń": "nacute",
    "ó": "oacute", "ś": "sacute", "ź": "zacute", "ż": "zdotaccent",
    "Ą": "Aogonek", "Ć": "Cacute", "Ę": "Eogonek", "Ł": "Lslash", "Ń": "Nacute",
    "Ó": "Oacute", "Ś": "Sacute", "Ź": "Zacute", "Ż": "Zdotaccent",
    "–": "endash", "—": "emdash", "„": "quotedblbase", "”": "quotedblright",
    "ü": "udieresis", "ö": "odieresis", "ä": "adieresis", "é": "eacute",
}  # fmt: skip
_PL_CODES = {ch: 128 + i for i, ch in enumerate(_PL_GLYPHS)}


def _pdf_string(text: str) -> bytes:
    out = bytearray(b"(")
    for ch in text:
        code = _PL_CODES.get(ch)
        if code is None:
            code = ord(ch) if 32 <= ord(ch) < 127 else ord("?")
        if code in (40, 41, 92):
            out += b"\\"
        out.append(code)
    return bytes(out + b")")


def _pdf_bytes(text: str) -> bytes:
    """PDF z liniami tekstu; tabulator = następna kolumna (co 110 pt), żeby układ
    tabeli (Time Sheet, RCP) czytał się jak w pliku klienta."""

    lines = (text or "").splitlines() or [""]
    pages = [lines[i : i + 60] for i in range(0, len(lines), 60)]
    objects: list[bytes] = []
    differences = " ".join(f"/{name}" for name in _PL_GLYPHS.values())
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(len(pages)))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    objects.append(
        (
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding "
            f"<< /Type /Encoding /BaseEncoding /WinAnsiEncoding /Differences [128 {differences}] >> >>"
        ).encode()
    )
    for index, page in enumerate(pages):
        stream = bytearray(b"BT /F1 10 Tf\n")
        for row, line in enumerate(page):
            for col, cell in enumerate(line.split("\t")):
                x, y = 40 + 110 * col, 800 - 12 * row
                stream += f"1 0 0 1 {x} {y} Tm ".encode() + _pdf_string(cell) + b" Tj\n"
        stream += b"ET"
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * index} 0 R >>"
            ).encode()
        )
        objects.append(
            f"<< /Length {len(stream)} >>\nstream\n".encode()
            + bytes(stream)
            + b"\nendstream"
        )
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def _docx_bytes(paragraphs: list) -> bytes:
    import io

    from docx import Document

    document = Document()
    for item in paragraphs:
        if isinstance(item, list):  # wiersze tabeli
            table = document.add_table(rows=0, cols=max(len(r) for r in item))
            for row in item:
                cells = table.add_row().cells
                for cell, value in zip(cells, row):
                    cell.text = str(value)
        else:
            document.add_paragraph(str(item))
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def _attachment(spec: dict, folder: str) -> dict:
    if "b64" in spec:
        data = base64.b64decode(spec["b64"])
    elif "plik" in spec:
        data = (Path(folder) / spec["plik"]).read_bytes()
    elif "arkusz" in spec:
        data = _sheet_bytes(spec["arkusz"])
    elif "pdf" in spec:
        data = _pdf_bytes(spec["pdf"])
    elif "docx" in spec:
        data = _docx_bytes(spec["docx"])
    else:
        data = str(spec.get("tekst", "%PDF-1.4 korpus")).encode()
    return {
        "@odata.type": spec.get("typ", "#microsoft.graph.fileAttachment"),
        "name": spec["nazwa"],
        "isInline": bool(spec.get("inline", False)),
        "contentType": spec.get("mime"),
        "contentBytes": base64.b64encode(data).decode(),
    }


def _addresses(value: Optional[str]) -> list[dict]:
    from email.utils import getaddresses

    return [
        {"emailAddress": {"address": addr, "name": name}}
        for name, addr in getaddresses([value or ""])
        if addr
    ]


def _from_eml(raw: bytes, mid: str) -> tuple[dict, list[dict]]:
    """Mail z archiwum (.eml) w kształcie Graph: nagłówki, treść tekstowa,
    załączniki jako ``fileAttachment``, załączone maile jako ``itemAttachment``
    (czytnik bierze je przez ``mime``)."""

    import email
    import email.policy
    from email.utils import parsedate_to_datetime

    message = email.message_from_bytes(raw, policy=email.policy.default)
    files: list[dict] = []
    body = ""
    for part in message.walk():
        if part.is_multipart():
            continue
        disposition = (part.get_content_disposition() or "").lower()
        name = part.get_filename()
        kind = part.get_content_type()
        if kind == "message/rfc822" or (name and name.lower().endswith(".eml")):
            files.append(
                {
                    "@odata.type": "#microsoft.graph.itemAttachment",
                    "name": name or "mail.eml",
                    "isInline": False,
                }
            )
            continue
        if name or disposition == "attachment":
            data = part.get_payload(decode=True) or b""
            files.append(
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": name or "plik",
                    "isInline": disposition == "inline",
                    "contentType": kind,
                    "contentId": (part.get("Content-ID") or "").strip("<>") or None,
                    "contentBytes": base64.b64encode(data).decode(),
                }
            )
        elif kind == "text/plain" and not body:
            body = part.get_content()
    try:
        received = parsedate_to_datetime(message.get("Date")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        received = datetime.now(timezone.utc)
    graph = {
        "id": mid,
        "internetMessageId": message.get("Message-ID"),
        "subject": str(message.get("Subject") or ""),
        "hasAttachments": bool(files),
        "from": (
            _addresses(message.get("From")) or [{"emailAddress": {"address": ""}}]
        )[0],
        "toRecipients": _addresses(message.get("To")),
        "ccRecipients": _addresses(message.get("Cc")),
        "receivedDateTime": received.isoformat().replace("+00:00", "Z"),
        "conversationId": message.get("Thread-Index") or mid,
        "body": {"contentType": "text", "content": body},
        "bodyPreview": body[:255],
    }
    return graph, files


class _Box:
    def __init__(self, case: dict) -> None:
        self.messages: list[dict] = []
        self.files: dict[str, list[dict]] = {}
        self.raw: dict[str, bytes] = {}
        folder = case["_katalog"]
        for index, mail in enumerate(case.get("maile") or []):
            mid = mail.get("id") or f"m{index + 1}"
            if mail.get("eml_plik"):
                raw = (Path(folder) / mail["eml_plik"]).read_bytes()
                message, files = _from_eml(raw, f"korpus-{mid}")
                self.messages.append(message)
                self.files[message["id"]] = files
                self.raw[message["id"]] = raw
                continue
            files = [_attachment(f, folder) for f in mail.get("pliki") or []]
            message = {
                "id": mid,
                "subject": mail.get("temat", ""),
                "hasAttachments": bool(files),
                "from": {"emailAddress": {"address": mail.get("od", "")}},
                "toRecipients": [
                    {"emailAddress": {"address": a}} for a in mail.get("do") or []
                ],
                "ccRecipients": [
                    {"emailAddress": {"address": a}} for a in mail.get("dw") or []
                ],
                "receivedDateTime": mail.get("odebrano")
                or f"{case.get('dzis', '2026-11-24')}T09:00:00Z",
                "conversationId": mail.get("watek", mid),
                "body": {"contentType": "text", "content": mail.get("tresc", "")},
                "bodyPreview": (mail.get("tresc") or "")[:255],
                **(mail.get("graph") or {}),
            }
            self.messages.append(message)
            self.files[mid] = files
            if mail.get("eml"):
                self.raw[mid] = mail["eml"].encode()

    async def list_messages(self, since):
        return self.messages

    async def attachments(self, message_id):
        return self.files.get(message_id, [])

    async def mime(self, message_id):
        return self.raw.get(message_id)

    async def download(self, *args, **kwargs):  # pragma: no cover - zgodność z Graph
        return None


def _schema_fingerprint(metadata) -> str:
    import hashlib

    lines = [
        f"{table.name}:"
        + ",".join(f"{c.name} {c.type!r} {c.nullable}" for c in table.columns)
        for table in sorted(metadata.tables.values(), key=lambda t: t.name)
    ]
    return hashlib.sha1("\n".join(lines).encode()).hexdigest()


async def _prepare_schema(url: str) -> None:
    """Czysta baza ze schematem tej rewizji (``Base.metadata``).

    Baza z poprzedniego biegu zostaje, gdy ma ten sam odcisk schematu: przypadki
    się cofają, więc jest czysta, a ``create_all`` 599 tabel to ~15 s."""

    from sqlalchemy import text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import create_async_engine

    import app.models  # noqa: F401  (rejestr modeli)
    from app.core.database import Base

    fingerprint = _schema_fingerprint(Base.metadata)
    target = make_url(url)
    admin = create_async_engine(
        target.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    async with admin.connect() as conn:
        exists = await conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": target.database},
        )
    if exists:
        probe = create_async_engine(url)
        async with probe.connect() as conn:
            ready = await conn.scalar(
                text("SELECT to_regclass('public._eval_reader_ready')")
            )
            stored = (
                await conn.scalar(text("SELECT fp FROM _eval_reader_ready LIMIT 1"))
                if ready
                else None
            )
        await probe.dispose()
        if stored == fingerprint:
            await admin.dispose()
            return
    async with admin.connect() as conn:
        await conn.execute(
            text(f'DROP DATABASE IF EXISTS "{target.database}" WITH (FORCE)')
        )
        await conn.execute(text(f'CREATE DATABASE "{target.database}"'))
    await admin.dispose()

    engine = create_async_engine(url)
    async with engine.begin() as conn:
        for extension in ("pg_trgm", "unaccent", "btree_gin"):
            await conn.execute(text(f"CREATE EXTENSION IF NOT EXISTS {extension}"))
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("CREATE TABLE _eval_reader_ready (fp text)"))
        await conn.execute(
            text("INSERT INTO _eval_reader_ready VALUES (:fp)"), {"fp": fingerprint}
        )
    await engine.dispose()


def _period(document) -> str:
    return f"{document.period_year:04d}-{document.period_month:02d}"


def _match(documents: list, want: dict, used: set[int]):
    for document in documents:
        if document.id in used:
            continue
        name = document.file_name or ""
        if "plik" in want and name != want["plik"]:
            continue
        if "plik_zawiera" in want and want["plik_zawiera"] not in name:
            continue
        return document
    return None


async def _settlement_case(case: dict, engine, storage_root: Path) -> list[dict]:
    """Jeden przypadek; podmiany (ustawienia, magazyn plików, domena firmy) wracają
    po przypadku, bo test w CI biegnie w jednym procesie z innymi testami."""

    from app.core.config import settings
    from app.services import storage_service
    from app.services.consultant_portal import identity

    today = date.fromisoformat(case.get("dzis") or "2026-11-24")
    moment = datetime.combine(today, time(12), tzinfo=timezone.utc)
    patches: list[tuple[Any, str, Any]] = [
        (settings, key, value) for key, value in (case.get("ustawienia") or {}).items()
    ]
    patches.append((storage_service, "STORAGE_ROOT", storage_root))
    # Domena firmy (skrzynki konsultantów i koordynatorów) jak w testach ``_db``:
    # fikcyjna w repo, prawdziwa w korpusie lokalnym (``domeny_firmy``).
    if hasattr(identity, "_company_domains"):
        domains = frozenset(case.get("domeny_firmy") or ["firma.example.com"])
        patches.append((identity, "_company_domains", lambda: domains))
    previous = [(target, name, getattr(target, name)) for target, name, _ in patches]
    for target, name, value in patches:
        setattr(target, name, value)
    try:
        documents, contracts = await _read_mail(case, today, moment, engine)
    finally:
        for target, name, value in reversed(previous):
            setattr(target, name, value)
    return _score_documents(case, documents, contracts)


async def _clear_mail_state(db) -> None:
    """Kopia produkcji ma już dokumenty i stan skrzynki: w transakcji przypadku
    (cofanej) zaczynamy od pustych, żeby czytnik nie uznał pliku za duplikat."""

    from sqlalchemy import text

    for table in ("cp_documents", "cp_mailbox_state"):
        await db.execute(text(f"DELETE FROM {table}"))


async def _read_mail(case: dict, today: date, moment: datetime, engine):
    """Zasiew, przebieg czytnika i odczyt dokumentów w jednej transakcji, którą
    na końcu cofamy: ``commit`` czytnika zwalnia tylko punkt zapisu."""

    import time_machine
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.app_setting import AppSetting
    from app.models.consultant_portal import CpDocument
    from app.services.consultant_portal import mailbox
    from app.services.consultant_portal_schema import PORTAL_SETTING
    from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING

    async with engine.connect() as conn:
        outer = await conn.begin()
        try:
            with time_machine.travel(moment, tick=False):
                db = AsyncSession(
                    bind=conn,
                    join_transaction_mode="create_savepoint",
                    expire_on_commit=False,
                )
                if case.get("baza") == "kopia":
                    # Kartoteka, klienci, zamówienia i ustawienia portalu z produkcji.
                    await _clear_mail_state(db)
                    contracts: dict[str, int] = {}
                else:
                    db.add(
                        AppSetting(
                            key=HR_MODULES_SETTING,
                            value={k: True for k in HR_MODULE_KEYS},
                        )
                    )
                    db.add(
                        AppSetting(
                            key=PORTAL_SETTING,
                            value={"state": case.get("portal", "internal")},
                        )
                    )
                    contracts = await _seed(db, case, today)
                await db.commit()
                outcome = await mailbox.run_once(db, mailbox=_Box(case), now=moment)
                await db.commit()
                if outcome.get("status") not in ("ok", "partial"):
                    raise RuntimeError(f"czytnik nie ruszył: {outcome}")
                documents = list(
                    (await db.scalars(select(CpDocument).order_by(CpDocument.id))).all()
                )
                await db.close()
        finally:
            await outer.rollback()
    return documents, contracts


def _score_documents(
    case: dict, documents: list, contracts: dict[str, int]
) -> list[dict]:
    by_contract = {v: k for k, v in contracts.items()}
    units: list[dict] = []
    used: set[int] = set()
    for index, want in enumerate(case.get("oczekiwane") or []):
        document = _match(documents, want, used)
        if document is not None:
            used.add(document.id)
        label = want.get("plik") or want.get("plik_zawiera") or f"dok{index + 1}"
        got = (
            None
            if document is None
            else {
                "rodzaj": document.kind,
                "osoba": by_contract.get(document.contract_id, document.contract_id),
                "okres": _period(document),
            }
        )
        for field in ("rodzaj", "osoba", "okres"):
            if field not in want:
                continue
            have = None if got is None else got[field]
            ok = got is not None and have == want[field]
            units.append(_unit(case, field, ok, want[field], have, key=label))
    count = case.get("liczba_dokumentow")
    if count is not None:
        units.append(
            _unit(
                case,
                "rodzaj",
                len(documents) == count,
                count,
                len(documents),
                key="liczba",
            )
        )
    return units


async def run_settlements(
    cases: list[dict], url: str, copy_url: Optional[str] = None
) -> list[dict]:
    """``copy_url`` = kopia produkcji dla przypadków ``"baza": "kopia"`` (korpus
    lokalny); bez niej takie przypadki kończą się błędem „brak kopii”."""

    from sqlalchemy.ext.asyncio import create_async_engine

    seeded = [c for c in cases if c.get("baza") != "kopia"]
    engine = None
    if seeded:
        await _prepare_schema(url)
        engine = create_async_engine(url)
    copy_engine = create_async_engine(copy_url) if copy_url else None
    units: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="eval-reader-") as tmp:
        for case in cases:
            fields = sorted(
                {
                    f
                    for want in case.get("oczekiwane") or []
                    for f in ("rodzaj", "osoba", "okres")
                    if f in want
                }
            )
            try:
                target = copy_engine if case.get("baza") == "kopia" else engine
                if target is None:
                    raise RuntimeError("brak kopii produkcji (EVAL_READER_COPY_URL)")
                units.extend(await _settlement_case(case, target, Path(tmp)))
                if os.environ.get("EVAL_READER_TRACE"):
                    print(f"{case['id']}: ok", file=sys.stderr)
            except Exception as exc:
                detail = "".join(
                    traceback.format_exception_only(type(exc), exc)
                ).strip()
                units.extend(_failed(case, fields, detail[:400]))
    for item in (engine, copy_engine):
        if item is not None:
            await item.dispose()
    return units


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("czytnik", choices=("cv", "rozliczenia"))
    parser.add_argument("--app", required=True, help="katalog backend/ rewizji")
    parser.add_argument("--korpus", nargs="+", required=True)
    parser.add_argument(
        "--zrodla", nargs="+", required=True, help="etykieta każdego katalogu"
    )
    parser.add_argument("--wynik", required=True)
    parser.add_argument("--filtr", default="")
    args = parser.parse_args()

    sys.path.insert(0, os.path.abspath(args.app))
    os.chdir(args.app)
    cases: list[dict] = []
    for folder, label in zip(args.korpus, args.zrodla):
        for case in load_cases([folder]):
            if (
                args.filtr
                and args.filtr not in case["id"]
                and args.filtr not in case["_plik"]
            ):
                continue
            case["_zrodlo"] = label
            cases.append(case)

    if args.czytnik == "cv":
        units = run_cv(cases)
    else:
        units = asyncio.run(
            run_settlements(
                cases,
                os.environ["DATABASE_URL"],
                os.environ.get("EVAL_READER_COPY_URL"),
            )
        )
    Path(args.wynik).write_text(
        json.dumps(
            {"przypadki": len(cases), "jednostki": units},
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
