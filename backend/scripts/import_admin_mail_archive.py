"""Import archiwum administracja@ (JSONL z ``archive_eml_to_jsonl.py``) do ``archived_mails``.

Decyzja Artura z 23.11.2026: historia skrzynki z home.pl wchodzi do historii
kontraktów, bez zakładania spraw. Mail przypinamy do kontraktu, gdy wiadomo,
kogo dotyczy:

1. adres konsultanta (nadawca albo odbiorca) z kontraktu, profilu albo
   ``known_sender_emails`` → kontrakt tej osoby trwający w dniu maila
   (albo ostatni przed nim),
2. numer umowy w temacie („1234/2026”) → umowa z Generatora,
3. adres ``imie.nazwisko@…`` → jedyny kandydat z kontraktem o tym kluczu osoby.

Reszta zostaje bez kontraktu (widać ją w raporcie, nie na ekranie).

    docker exec -i <backend> python -m scripts.import_admin_mail_archive < administracja.jsonl
    docker exec -i <backend> python -m scripts.import_admin_mail_archive --apply < administracja.jsonl
    docker exec -i <backend> python -m scripts.import_admin_mail_archive --report-2026 < administracja.jsonl

Bez ``--apply`` tylko liczy. ``--report-2026`` wypisuje CSV wątków wypowiedzeń
z 2026 r. wobec stanu kontraktów (id, bez nazwisk — wynik idzie do Artura,
nie do repo). Klucz importu to SHA-256 z manifestu: ponowny bieg nic nie dubluje.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable, Optional

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_date, business_today
from app.models.notice_mail import ArchivedMail
from app.services.admin_cases import notice_rules as rules
from app.services.care.card_linking import person_key
from app.services.notice_mail_schema import BODY_MAX

OWN_DOMAINS = ("b2bnetwork.pl", "b2bnetsa.onmicrosoft.com")
_THREAD_PREFIX = re.compile(r"^((re|fw|fwd|odp|pd|aw|wg)\s*:\s*)+", re.IGNORECASE)
BATCH = 200


@dataclass(frozen=True)
class ContractSpan:
    contract_id: int
    candidate_id: int
    start: Optional[date]
    end: Optional[date]
    status: str
    terminated_at: Optional[date]
    agreement_mode: Optional[str]


@dataclass
class Index:
    by_email: dict[str, set[int]]
    by_person: dict[str, set[int]]
    by_number: dict[str, int]
    spans: dict[int, list[ContractSpan]]
    contracts: dict[int, ContractSpan]
    #: Konta NEXUSA (pracownicy): ich adres ``imie.nazwisko@`` to nadawca, nie konsultant.
    staff: set[str]


async def load_index(db) -> Index:
    rows = (
        await db.execute(
            text(
                """
                SELECT k.id, k.candidate_id, k.start_date,
                       coalesce(k.terminated_at, k.end_date) AS last_day,
                       k.status::text AS status, k.terminated_at,
                       k.agreement_termination_mode,
                       lower(btrim(k.candidate_email)) AS contract_email,
                       lower(btrim(c.email)) AS profile_email,
                       c.name, c.lastname
                FROM contracts k JOIN candidates c ON c.id = k.candidate_id
                WHERE k.voided_at IS NULL
                """
            )
        )
    ).mappings()
    index = Index({}, {}, {}, {}, {}, set())
    for row in rows:
        span = ContractSpan(
            row["id"],
            row["candidate_id"],
            row["start_date"],
            row["last_day"],
            row["status"],
            row["terminated_at"],
            row["agreement_termination_mode"],
        )
        index.contracts[span.contract_id] = span
        index.spans.setdefault(span.candidate_id, []).append(span)
        for mail in (row["contract_email"], row["profile_email"]):
            if mail:
                index.by_email.setdefault(mail, set()).add(span.candidate_id)
        key = person_key(f"{row['name']} {row['lastname']}")
        if key:
            index.by_person.setdefault(key, set()).add(span.candidate_id)
    for email_value, candidate_id in (
        await db.execute(text("SELECT email, candidate_id FROM known_sender_emails"))
    ).all():
        index.by_email.setdefault(email_value, set()).add(candidate_id)
    index.staff = {
        email_value
        for (email_value,) in (
            await db.execute(
                text("SELECT lower(btrim(email)) FROM users WHERE email IS NOT NULL")
            )
        ).all()
    }
    for number, contract_id in (
        await db.execute(
            text(
                "SELECT contract_number, contract_id FROM b2b_generated_contracts "
                "WHERE contract_id IS NOT NULL"
            )
        )
    ).all():
        index.by_number[number] = contract_id
    return index


def _contract_on(spans: Iterable[ContractSpan], day: date) -> Optional[int]:
    """Kontrakt trwający w dniu maila; inaczej ostatni zaczęty przed nim."""

    spans = sorted(spans, key=lambda s: (s.start or date.min, s.contract_id))
    covering = [
        s
        for s in spans
        if (s.start is None or s.start <= day) and (s.end is None or s.end >= day)
    ]
    if covering:
        return covering[-1].contract_id
    before = [s for s in spans if s.start is None or s.start <= day]
    if before:
        return before[-1].contract_id
    return spans[0].contract_id if spans else None


def match(
    record: dict[str, Any], index: Index
) -> tuple[Optional[int], Optional[int], Optional[str]]:
    received = _parse(record.get("received_at"))
    day = business_date(received) if received else business_today()
    addresses = [record.get("sender_email"), *(record.get("to_emails") or [])]
    candidates: set[int] = set()
    for address in addresses:
        if address and not address.endswith(OWN_DOMAINS):
            candidates |= index.by_email.get(address, set())
    if len(candidates) == 1:
        candidate_id = next(iter(candidates))
        return candidate_id, _contract_on(index.spans[candidate_id], day), "email"
    number = rules.contract_number_in(record.get("subject"))
    if number and number in index.by_number:
        contract_id = index.by_number[number]
        span = index.contracts.get(contract_id)
        return (span.candidate_id if span else None), contract_id, "contract_number"
    for address in addresses:
        if address in index.staff:
            continue
        name = rules.name_from_address(address)
        found = index.by_person.get(person_key(name), set()) if name else set()
        if len(found) == 1:
            candidate_id = next(iter(found))
            return candidate_id, _contract_on(index.spans[candidate_id], day), "name"
    return None, None, None


def _parse(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _row(record: dict[str, Any], index: Index) -> dict[str, Any]:
    candidate_id, contract_id, reason = match(record, index)
    return {
        "mailbox": str(record["mailbox"])[:32],
        "folder": str(record["folder"])[:200],
        "sha256": record["sha256"],
        "received_at": _parse(record.get("received_at")),
        "message_id": (record.get("message_id") or None) and record["message_id"][:512],
        "sender_email": record.get("sender_email"),
        "sender_name": record.get("sender_name"),
        "to_emails": record.get("to_emails") or [],
        "subject": record.get("subject"),
        "body_text": (record.get("body_text") or "").replace("\x00", "")[:BODY_MAX],
        "attachments": record.get("attachments") or [],
        "eml_path": record.get("eml_path"),
        "candidate_id": candidate_id,
        "contract_id": contract_id,
        "match_reason": reason,
    }


def report_2026(records: list[dict[str, Any]], index: Index, out) -> Counter:
    """Wątki wypowiedzeń z 2026 r. wobec kontraktu: czy zakończenie jest zapisane."""

    writer = csv.writer(out)
    writer.writerow(
        [
            "data",
            "rodzaj",
            "kontrakt",
            "status",
            "zakonczenie_zapisane",
            "dopasowanie",
            "watek",
        ]
    )
    seen: set[str] = set()
    stats: Counter = Counter()
    for record in sorted(records, key=lambda r: r.get("received_at") or ""):
        if not str(record.get("received_at") or "").startswith("2026"):
            continue
        if str(record.get("folder", "")).upper().startswith("SENT"):
            continue
        signal = rules.classify(
            subject=record.get("subject"),
            body=record.get("body_text"),
            attachment_names=[
                a.get("name", "") for a in record.get("attachments") or []
            ],
            today=date(2026, 11, 23),
        )
        if signal is None or signal.kind not in (
            rules.CONSULTANT_NOTICE,
            rules.CLIENT_TERMINATION,
        ):
            continue
        thread = _THREAD_PREFIX.sub("", record.get("subject") or "").strip().lower()
        if thread in seen:
            continue
        seen.add(thread)
        _, contract_id, reason = match(record, index)
        span = index.contracts.get(contract_id) if contract_id else None
        recorded = bool(span and (span.terminated_at or span.agreement_mode))
        state = (
            "bez_dopasowania"
            if span is None
            else ("zapisane" if recorded else f"brak_zapisu:{span.status}")
        )
        stats[state] += 1
        writer.writerow(
            [
                str(record.get("received_at", ""))[:10],
                signal.kind,
                contract_id or "",
                span.status if span else "",
                "tak" if recorded else "nie",
                reason or "",
                len(seen),
            ]
        )
    return stats


async def run(*, apply: bool, report: bool, stream) -> dict[str, Any]:
    records = [json.loads(line) for line in stream if line.strip()]
    async with AsyncSessionLocal() as db:
        index = await load_index(db)
        if report:
            stats = report_2026(records, index, sys.stdout)
            return {"report": dict(stats)}
        rows = [_row(record, index) for record in records]
        reasons = Counter(row["match_reason"] or "none" for row in rows)
        result: dict[str, Any] = {
            "records": len(rows),
            "with_contract": sum(1 for row in rows if row["contract_id"]),
            "by_reason": dict(reasons),
            "applied": False,
        }
        if not apply:
            return result
        inserted = 0
        for start in range(0, len(rows), BATCH):
            chunk = rows[start : start + BATCH]
            statement = (
                insert(ArchivedMail)
                .values(chunk)
                .on_conflict_do_nothing(constraint="uq_archived_mails_sha256")
                .returning(ArchivedMail.id)
            )
            inserted += len((await db.execute(statement)).all())
        await db.commit()
        return {**result, "applied": True, "inserted": inserted}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--apply", action="store_true", help="zapisz do bazy")
    parser.add_argument(
        "--report-2026", action="store_true", help="CSV wątków wypowiedzeń z 2026 r."
    )
    args = parser.parse_args()
    result = asyncio.run(
        run(apply=args.apply, report=args.report_2026, stream=sys.stdin)
    )
    print(json.dumps(result), file=sys.stderr if args.report_2026 else sys.stdout)


if __name__ == "__main__":
    main()
