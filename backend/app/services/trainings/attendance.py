"""Lista obecności ze spotkania Teams („Raport obecności” / „Attendance report”).

Teams eksportuje CSV w UTF-16 LE z BOM (czasem UTF-8), rozdzielany tabulatorem
(czasem przecinkiem albo średnikiem), w sekcjach: „1. Podsumowanie / Summary”,
„2. Uczestnicy / Participants”, „3. Działania podczas spotkania / In-Meeting
Activities”. Bierzemy sekcję uczestników (jeden wiersz na osobę, łączny czas);
gdy jej nie ma, sumujemy wejścia z sekcji działań. Czas bywa „1 h 23 min 5 s”,
„1h 23m 5s” albo „01:23:05”.

Dopasowanie: konto po ``users.email``, konsultant po ``contracts.candidate_email``
aktywnego kontraktu. Adres pasujący do dwóch różnych osób zostaje bez dopasowania.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass, replace
from typing import Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contract import Contract, ContractStatus
from app.models.user import User


@dataclass(frozen=True)
class AttendanceRow:
    name: str
    email: str
    minutes: Optional[int]
    user_id: Optional[int] = None
    contract_id: Optional[int] = None


_SECTION = re.compile(r"^\s*(\d+)\s*[.)]\s*(.+?)\s*$")
_PARTICIPANTS = ("participants", "uczestnicy")
_ACTIVITIES = (
    "in-meeting activities",
    "in meeting activities",
    "dzialania",
    "aktywnosci",
)

_NAME_HEADERS = ("name", "full name", "imie i nazwisko", "nazwa", "uczestnik", "imie")
_EMAIL_HEADERS = ("email", "e-mail", "adres e-mail", "adres email", "email address")
_UPN_HEADERS = ("participant id (upn)", "identyfikator uczestnika (upn)", "upn")
_DURATION_HEADERS = (
    "in-meeting duration",
    "in meeting duration",
    "duration",
    "attendance duration",
    "czas w spotkaniu",
    "czas trwania",
    "czas uczestnictwa",
    "czas",
)

_UNIT = re.compile(r"(\d+)\s*([a-z.]+)")
_CLOCK = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{2})$")
_LIVE = (ContractStatus.active, ContractStatus.ending)


def _plain(value: str) -> str:
    """Etykieta bez polskich znaków, spacji na brzegach i wielkich liter."""
    value = value.replace("ł", "l").replace("Ł", "L")
    decomposed = unicodedata.normalize("NFKD", value)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(stripped.strip().strip('"').casefold().split())


def _decode(data: bytes) -> str:
    if data.startswith(b"\xff\xfe"):
        return data[2:].decode("utf-16-le", errors="replace")
    if data.startswith(b"\xfe\xff"):
        return data[2:].decode("utf-16-be", errors="replace")
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")
    sample = data[:200]
    if sample and sample.count(b"\x00") > len(sample) // 4:
        # UTF-16 bez BOM: zera w co drugim bajcie.
        encoding = "utf-16-le" if sample[1:2] == b"\x00" else "utf-16-be"
        return data.decode(encoding, errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1250", errors="replace")


def _delimiter(line: str) -> str:
    if "\t" in line:
        return "\t"
    return ";" if line.count(";") > line.count(",") else ","


def _split(line: str, delimiter: str) -> list[str]:
    return [cell.strip() for cell in next(csv.reader([line], delimiter=delimiter), [])]


def parse_duration(value: str) -> Optional[int]:
    """Minuty z „1 h 23 min 5 s”, „1h 23m 5s”, „45 min”, „01:23:05”; puste → None."""
    text = _plain(value or "")
    if not text:
        return None
    clock = _CLOCK.match(text.replace(" ", ""))
    if clock:
        hours, minutes, seconds = (int(part or 0) for part in clock.groups())
        return (hours * 3600 + minutes * 60 + seconds + 30) // 60
    seconds = 0
    found = False
    for amount, unit in _UNIT.findall(text):
        letter = unit[0]
        if letter in ("h", "g"):  # h, hr, hours, godz.
            seconds += int(amount) * 3600
        elif letter == "m":  # m, min, mins, minut
            seconds += int(amount) * 60
        elif letter == "s":  # s, sec, sek
            seconds += int(amount)
        else:
            continue
        found = True
    if not found:
        return None
    return (seconds + 30) // 60


def _column(header: list[str], names: Iterable[str]) -> Optional[int]:
    labels = [_plain(cell) for cell in header]
    for name in names:
        if name in labels:
            return labels.index(name)
    return None


def _sections(lines: list[str]) -> dict[str, list[str]]:
    """Linie podzielone na sekcje „N. Tytuł”; plik bez sekcji to jedna tabela."""
    sections: dict[str, list[str]] = {}
    current = "table"
    for line in lines:
        cells = [cell for cell in re.split(r"[\t,;]", line) if cell.strip()]
        match = _SECTION.match(cells[0].strip().strip('"')) if len(cells) == 1 else None
        if match:
            title = _plain(match.group(2))
            if title.startswith(_PARTICIPANTS):
                current = "participants"
            elif title.startswith(_ACTIVITIES):
                current = "activities"
            else:
                current = f"other:{match.group(1)}"
            continue
        sections.setdefault(current, []).append(line)
    return sections


def _table(lines: list[str]) -> list[AttendanceRow]:
    rows: list[AttendanceRow] = []
    header: Optional[list[str]] = None
    delimiter = "\t"
    name_at = email_at = upn_at = duration_at = None
    for line in lines:
        if not line.strip():
            continue
        if header is None:
            delimiter = _delimiter(line)
            cells = _split(line, delimiter)
            name_at = _column(cells, _NAME_HEADERS)
            email_at = _column(cells, _EMAIL_HEADERS)
            upn_at = _column(cells, _UPN_HEADERS)
            duration_at = _column(cells, _DURATION_HEADERS)
            if name_at is not None and (
                email_at is not None or duration_at is not None
            ):
                header = cells
            continue
        cells = _split(line, delimiter)

        def cell(index: Optional[int], cells: list[str] = cells) -> str:
            return cells[index] if index is not None and index < len(cells) else ""

        name = cell(name_at)
        email = cell(email_at).lower()
        if "@" not in email:
            email = cell(upn_at).lower()
        if "@" not in email:
            email = ""
        if not name and not email:
            continue
        if _plain(name) in _NAME_HEADERS:
            continue  # powtórzony nagłówek
        rows.append(
            AttendanceRow(
                name=name, email=email, minutes=parse_duration(cell(duration_at))
            )
        )
    return rows


def _key(row: AttendanceRow) -> str:
    return row.email or f"name:{_plain(row.name)}"


def _merge(rows: list[AttendanceRow], *, add: bool) -> list[AttendanceRow]:
    """Jedna osoba = jeden wiersz. Uczestnicy: najdłuższy czas (dwa urządzenia
    to nie dwa razy dłużej); działania: suma wejść."""
    merged: dict[str, AttendanceRow] = {}
    for row in rows:
        key = _key(row)
        seen = merged.get(key)
        if seen is None:
            merged[key] = row
            continue
        if row.minutes is None:
            minutes = seen.minutes
        elif seen.minutes is None:
            minutes = row.minutes
        else:
            minutes = (
                seen.minutes + row.minutes if add else max(seen.minutes, row.minutes)
            )
        merged[key] = replace(seen, name=seen.name or row.name, minutes=minutes)
    return list(merged.values())


def parse_teams_report(data: bytes) -> list[AttendanceRow]:
    text = _decode(data)
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    sections = _sections(lines)
    if "participants" in sections:
        return _merge(_table(sections["participants"]), add=False)
    if "activities" in sections:
        return _merge(_table(sections["activities"]), add=True)
    return _merge(_table(sections.get("table", [])), add=False)


async def match(db: AsyncSession, rows: list[AttendanceRow]) -> list[AttendanceRow]:
    """Uzupełnia ``user_id`` (``users.email``) i ``contract_id`` (aktywny kontrakt po
    ``candidate_email``). Adres dwóch różnych kont albo osób zostaje bez dopasowania."""
    emails = sorted({row.email.strip().lower() for row in rows if row.email})
    if not emails:
        return list(rows)

    users: dict[str, set[int]] = {}
    for user_id, email in (
        await db.execute(
            select(User.id, func.lower(User.email)).where(
                func.lower(User.email).in_(emails)
            )
        )
    ).all():
        users.setdefault(email, set()).add(user_id)

    contracts: dict[str, list[tuple[int, object]]] = {}
    for contract_id, candidate_id, email in (
        await db.execute(
            select(
                Contract.id, Contract.candidate_id, func.lower(Contract.candidate_email)
            )
            .where(func.lower(Contract.candidate_email).in_(emails))
            .where(Contract.status.in_(_LIVE))
            .order_by(Contract.start_date.desc().nulls_last(), Contract.id.desc())
        )
    ).all():
        contracts.setdefault(email, []).append(
            (contract_id, candidate_id or f"c{contract_id}")
        )

    matched: list[AttendanceRow] = []
    for row in rows:
        email = row.email.strip().lower()
        user_ids = users.get(email) or set()
        found = contracts.get(email) or []
        people = {person for _, person in found}
        matched.append(
            replace(
                row,
                user_id=next(iter(user_ids)) if len(user_ids) == 1 else None,
                contract_id=found[0][0] if found and len(people) == 1 else None,
            )
        )
    return matched


async def replace_rows(
    db: AsyncSession, training_id: int, rows: list[AttendanceRow]
) -> None:
    """Nowy raport zastępuje poprzedni (CSV z Teams albo raport z Graph, 0696)."""

    from sqlalchemy import delete  # noqa: PLC0415

    from app.models.training import TrainingAttendance  # noqa: PLC0415

    await db.execute(
        delete(TrainingAttendance).where(TrainingAttendance.training_id == training_id)
    )
    for row in rows:
        db.add(
            TrainingAttendance(
                training_id=training_id,
                display_name=row.name[:255],
                email=(row.email or "")[:255],
                minutes=row.minutes,
                user_id=row.user_id,
                contract_id=row.contract_id,
            )
        )
    await db.flush()
