"""Maile z „cyrylicy w smart_name” — odpięcie i ponowne dopasowanie (20.10.2026).

Do 26.09.2026 reguła `smart_name` (`app/services/m365/matcher.py`) składała
imię i nazwisko do ASCII. Zapis cyrylicą składał się do pustego napisu,
a wzorzec ``\\b\\b.*\\b\\b`` pasował do każdego tematu, więc pierwszy taki
kandydat w tabeli dostawał każdy niedopasowany mail. `smart_thread` doklejał mu
potem odpowiedzi z tych wątków (nadal, do tej naprawy). Pomiar 20.10: trzech
kandydatów, 4 701 maili, w żadnym adresu tej osoby. CV z tych maili trafiały do
profilu, a bramka tożsamości (imię cyrylicą = `inconclusive`) robiła z cudzego
CV główne. Kod poprawia `matcher.name_folds_to_nothing` i
`candidate_identity_quarantine.identity_unreadable`; ten skrypt naprawia dane
(decyzja Artura z 20.10.2026: odpiąć i dopasować na nowo).

Uruchomienie (w kontenerze backendu, po wdrożeniu)::

    python -m app.cli.m365_unreadable_name_rematch
    python -m app.cli.m365_unreadable_name_rematch --apply --expected <odcisk>
    … --apply … --reread <id>   # odczyt AI profilu z głównego CV po naprawie

Zasady:

* poszkodowany = kandydat z mailem `smart_name`, którego imię albo nazwisko
  składa się do niczego (`name_folds_to_nothing`). Jego maile `smart_name`
  i `smart_thread` bez ręcznej decyzji są odpinane. `smart_thread` zostaje,
  gdy w tym wątku jest mail podpięty do tej osoby inną metodą (strict, ręcznie,
  z CV) — wtedy wątek naprawdę jest jej;
* każdy odpięty mail przechodzi od razu przez obecny matcher, w kolejności
  przyjścia (odpowiedź w wątku widzi wcześniejsze dopasowanie). Bez trafienia
  zostaje niedopasowany. Mail prywatny (`is_private_filtered`) i mail ze
  skrzynki osoby bez dostępu do poczty kandydatów (`eligible_m365_owner`)
  matchera nie widzą i zostają niedopasowane — te same warunki co zwykły
  rematch (`microsoft365_sync._rematch_pass`, audyt 21.10.2026);
* załączniki tych maili odczytane do poszkodowanego tracą `parsed_candidate_id`
  i znacznik próby: CV z maila dopasowanego do prawdziwej osoby czyta kolejka
  `m365_cv_parse` (przez bramkę tożsamości), reszta czeka na dopasowanie;
* dokument m365 poszkodowanego z plikiem z tych maili (a nie z jego innych
  maili) jest miękko usuwany (`removed_at`, `source_deleted_at`) — nic nie
  kasujemy. Gdy był głównym CV, główne przechodzi na plik ze wskaźnika
  kandydata (`cv_filename`), a bez niego na najnowsze bieżące CV;
* profil czytany z usuwanego pliku (`cv_highlights.source_document_id`, a bez
  tego śladu: plik był głównym CV i wskaźnik `cv_filename` ma jego nazwę)
  traci przy ``--apply`` fakty z tego CV jak w kwarantannie tożsamości: tekst
  CV, umiejętności, doświadczenie, podsumowanie AI i wektor
  (`clear_foreign_cv_projection`; audyt 22.10.2026, F114, decyzja Artura).
  Próba na sucho wypisuje te osoby w ``projection_from_foreign`` — kto po
  naprawie ma główne CV, idzie do ``--reread``;
* kopia CV etapu z usuwanym plikiem przerywa ``--apply`` (CV u klienta to
  decyzja Artura). Pomiar 20.10: zero;
* ``--apply`` wymaga ``--expected`` równego odciskowi z próby na sucho. Próba
  robi te same zmiany w transakcji i ją wycofuje. Paragon
  ``app_settings['m365_unreadable_name_rematch_2026_10']`` niesie same liczby
  i id; drugie ``--apply`` przy paragonie jest odrzucane. Raport bez nazwisk,
  adresów i tematów (logi Actions są publiczne).

Bieg z 20–21.10.2026 poszedł przed audytem 22.10 (F113, F114), a paragon
blokuje ponowne ``--apply``. Kogo dotyczą obie luki, mówi raport tylko do
odczytu ``backend/scripts/m365_cv_repair_followup_report.sql``.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import and_, exists, func, select, text, update
from sqlalchemy.orm import aliased

logger = logging.getLogger(__name__)

RECEIPT_KEY = "m365_unreadable_name_rematch_2026_10"


@dataclass
class Plan:
    victims: list[int] = field(default_factory=list)
    # (email_id, poszkodowany, nowy kandydat albo None, nowa metoda)
    emails: list[tuple[int, int, Optional[int], str]] = field(default_factory=list)
    # maile `smart_thread` zostawione, bo wątek ma mail tej osoby inną metodą
    kept_thread_email_ids: list[int] = field(default_factory=list)
    # (attachment_id, poszkodowany, mail przychodzący)
    attachments: list[tuple[int, int, bool]] = field(default_factory=list)
    # (doc_id, poszkodowany)
    removals: list[tuple[int, int]] = field(default_factory=list)
    # poszkodowany → (główne przed, główne po)
    primaries: dict[int, tuple[Optional[int], Optional[int]]] = field(
        default_factory=dict
    )
    # poszkodowany → (nazwa pliku ze wskaźnika po naprawie)
    pointers: dict[int, Optional[str]] = field(default_factory=dict)
    # (poszkodowany, doc_id, skrót pliku) — profil czytany z usuwanego pliku
    projections: list[tuple[int, int, Optional[str]]] = field(default_factory=list)
    stage_copies: int = 0

    def fingerprint(self) -> str:
        payload = {
            "emails": sorted(self.emails, key=lambda e: e[0]),
            "kept": sorted(self.kept_thread_email_ids),
            "attachments": sorted(self.attachments),
            "removals": sorted(self.removals),
            "primaries": sorted(
                (cid, before, after) for cid, (before, after) in self.primaries.items()
            ),
            "projections": sorted((cid, doc) for cid, doc, _ in self.projections),
        }
        return hashlib.sha256(json.dumps(payload).encode()).hexdigest()[:12]


def projected_document(candidate, docs) -> Optional[Any]:
    """Dokument, z którego odczytano profil, spośród ``docs`` (albo None).

    Ślad odczytu (`cv_highlights.source_document_id`) wygrywa; profil bez
    śladu (odczyt sprzed 17.09.2026) liczy się jak w kwarantannie: plik był
    głównym CV, a wskaźnik `cv_filename` ma jego nazwę.
    """
    extracted = candidate.cv_extracted_data
    highlights = extracted.get("cv_highlights") if isinstance(extracted, dict) else None
    source_id = (
        highlights.get("source_document_id") if isinstance(highlights, dict) else None
    )
    if source_id is not None:
        return next((d for d in docs if d.id == source_id), None)
    pointer = (candidate.cv_filename or "").lower()
    return next(
        (d for d in docs if d.is_primary and pointer and d.filename.lower() == pointer),
        None,
    )


async def find_victims(db) -> list[int]:
    from app.models.candidate import Candidate
    from app.models.m365 import Email, EmailMatchMethod
    from app.services.m365.matcher import name_folds_to_nothing

    rows = (
        await db.execute(
            select(Candidate.id, Candidate.name, Candidate.lastname)
            .where(
                exists().where(
                    Email.candidate_id == Candidate.id,
                    Email.match_method == EmailMatchMethod.smart_name,
                )
            )
            .order_by(Candidate.id)
        )
    ).all()
    return [r.id for r in rows if name_folds_to_nothing(r.name, r.lastname)]


async def _select_emails(db, victims: list[int]):
    from app.models.m365 import Email, EmailMatchMethod

    smart = (EmailMatchMethod.smart_name, EmailMatchMethod.smart_thread)
    other = aliased(Email)
    legit_thread = exists().where(
        other.m365_conversation_id == Email.m365_conversation_id,
        other.candidate_id == Email.candidate_id,
        other.match_method.notin_(smart),
    )
    scope = (
        Email.candidate_id.in_(victims),
        Email.match_method.in_(smart),
        Email.matched_by_user_id.is_(None),
    )
    kept_clause = and_(
        Email.match_method == EmailMatchMethod.smart_thread, legit_thread
    )
    kept = list(
        await db.scalars(select(Email.id).where(*scope, kept_clause).order_by(Email.id))
    )
    rows = (
        await db.execute(
            select(
                Email.id,
                Email.candidate_id,
                Email.user_id,
                Email.from_address,
                Email.to_addresses,
                Email.cc_addresses,
                Email.subject,
                Email.m365_conversation_id,
                Email.is_private_filtered,
            )
            .where(*scope, ~kept_clause)
            .order_by(Email.received_at.asc().nulls_last(), Email.id.asc())
        )
    ).all()
    return rows, kept


async def plan_and_stage(db, *, now: Optional[datetime] = None) -> Plan:
    """Zmiany w bieżącej transakcji + plan. Commit albo rollback robi wołający."""
    from app.models.candidate import Candidate
    from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
    from app.models.candidate_stage_cv import CandidateStageCV
    from app.models.m365 import (
        Email,
        EmailAttachment,
        EmailDirection,
        EmailMatchMethod,
        M365Connection,
    )
    from app.services.cv_source import current_cv_filters, current_cv_ordering
    from app.services.m365 import matcher
    from app.services.m365.access import eligible_m365_owner
    from app.tasks.microsoft365_sync import _addresses

    now = now or datetime.now(timezone.utc)
    items = Plan(victims=await find_victims(db))
    if not items.victims:
        return items
    rows, items.kept_thread_email_ids = await _select_emails(db, items.victims)
    email_ids = [r.id for r in rows]
    owner_of = {r.id: r.candidate_id for r in rows}

    for chunk in _chunks(email_ids):
        await db.execute(
            update(Email)
            .where(Email.id.in_(chunk))
            .values(
                candidate_id=None,
                match_method=EmailMatchMethod.unmatched,
                match_confidence=None,
                matched_at=None,
            )
            .execution_options(synchronize_session="evaluate")
        )
    await db.flush()

    mailbox: dict[int, Optional[str]] = {}
    owner_eligible: dict[int, bool] = {}
    for row in rows:
        if row.user_id not in owner_eligible:
            owner_eligible[row.user_id] = (
                await eligible_m365_owner(db, row.user_id) is not None
            )
        if row.is_private_filtered or not owner_eligible[row.user_id]:
            # Odpięty jak reszta, ale bez matchera — jak w zwykłym rematchu.
            items.emails.append(
                (row.id, owner_of[row.id], None, EmailMatchMethod.unmatched.value)
            )
            continue
        if row.user_id not in mailbox:
            mailbox[row.user_id] = await db.scalar(
                select(M365Connection.mailbox_upn).where(
                    M365Connection.user_id == row.user_id
                )
            )
        result = await matcher.match(
            db,
            matcher.IncomingMessage(
                from_address=row.from_address or "",
                to_addresses=_addresses(row.to_addresses),
                cc_addresses=_addresses(row.cc_addresses),
                subject=row.subject,
                conversation_id=row.m365_conversation_id,
                owner_address=mailbox[row.user_id],
            ),
        )
        items.emails.append(
            (row.id, owner_of[row.id], result.candidate_id, result.method)
        )
        if result.candidate_id is None:
            continue
        # Zapis od razu: następna odpowiedź w wątku widzi to dopasowanie.
        await db.execute(
            update(Email)
            .where(Email.id == row.id)
            .values(
                candidate_id=result.candidate_id,
                match_method=EmailMatchMethod(result.method),
                match_confidence=result.confidence,
                matched_at=now,
            )
            .execution_options(synchronize_session="evaluate")
        )

    attachment_rows = []
    for chunk in _chunks(email_ids):
        attachment_rows += (
            await db.execute(
                select(
                    EmailAttachment.id,
                    EmailAttachment.email_id,
                    EmailAttachment.sha256,
                    EmailAttachment.parsed_candidate_id,
                    Email.direction,
                )
                .join(Email, Email.id == EmailAttachment.email_id)
                .where(EmailAttachment.email_id.in_(chunk))
            )
        ).all()
    moved_shas: dict[int, set[str]] = {cid: set() for cid in items.victims}
    for a in attachment_rows:
        victim = owner_of[a.email_id]
        if a.sha256:
            moved_shas[victim].add(a.sha256)
        if a.parsed_candidate_id == victim:
            items.attachments.append(
                (a.id, victim, a.direction == EmailDirection.received)
            )
    for chunk in _chunks([a for a, _, _ in items.attachments]):
        await db.execute(
            update(EmailAttachment)
            .where(EmailAttachment.id.in_(chunk))
            .values(
                parsed_candidate_id=None, cv_parse_attempted_at=None, parse_error=None
            )
            .execution_options(synchronize_session="evaluate")
        )

    for victim in items.victims:
        # Pliki z maili, które zostają przy tej osobie, nie są cudze.
        own_shas = set(
            await db.scalars(
                select(EmailAttachment.sha256)
                .join(Email, Email.id == EmailAttachment.email_id)
                .where(
                    Email.candidate_id == victim,
                    EmailAttachment.sha256.is_not(None),
                )
            )
        )
        foreign = moved_shas[victim] - own_shas
        docs = list(
            await db.scalars(
                select(CandidateDocument)
                .where(
                    CandidateDocument.candidate_id == victim,
                    CandidateDocument.external_source == "m365",
                    CandidateDocument.removed_at.is_(None),
                    CandidateDocument.content_sha256.in_(sorted(foreign)),
                )
                .order_by(CandidateDocument.id)
            )
        )
        if not docs:
            continue
        candidate = await db.scalar(
            select(Candidate).where(Candidate.id == victim).with_for_update()
        )
        items.stage_copies += int(
            await db.scalar(
                select(func.count()).where(
                    CandidateStageCV.candidate_id == victim,
                    CandidateStageCV.original_cv_sha256.in_(
                        [d.content_sha256 for d in docs]
                    ),
                )
            )
            or 0
        )
        before = next((d.id for d in docs if d.is_primary), None)
        fed = projected_document(candidate, docs)
        if fed is not None:
            items.projections.append((victim, fed.id, fed.content_sha256))
        removed_names = {d.filename.lower() for d in docs if d.filename}
        for doc in docs:
            doc.is_primary = False
            doc.removed_at = now
            doc.source_deleted_at = doc.source_deleted_at or now
            items.removals.append((doc.id, victim))
        await db.flush()
        pointer = candidate.cv_filename
        if pointer and pointer.lower() in removed_names:
            pointer = None
        if before is not None:
            remaining = list(
                await db.scalars(
                    select(CandidateDocument)
                    .where(
                        CandidateDocument.candidate_id == victim,
                        CandidateDocument.document_kind == CandidateDocumentKind.cv,
                        *current_cv_filters(),
                    )
                    .order_by(*current_cv_ordering())
                )
            )
            successor = next(
                (d for d in remaining if pointer and d.filename == pointer),
                remaining[0] if remaining else None,
            )
            if successor is not None:
                successor.is_primary = True
                pointer = successor.filename
            items.primaries[victim] = (
                before,
                successor.id if successor is not None else None,
            )
        if pointer != candidate.cv_filename:
            candidate.cv_filename = pointer
            items.pointers[victim] = pointer
        await db.flush()
    return items


def summarize(items: Plan) -> dict[str, Any]:
    by_method = Counter((victim, method) for _, victim, _, method in items.emails)
    relinked = {new for _, _, new, _ in items.emails if new is not None}
    return {
        "fingerprint": items.fingerprint(),
        "victims": items.victims,
        "emails": len(items.emails),
        "emails_by_victim_and_new_method": {
            f"{victim}:{method}": count
            for (victim, method), count in sorted(by_method.items())
        },
        "relinked_to_victim": sum(
            1 for _, victim, new, _ in items.emails if new == victim
        ),
        "relinked_candidates": len(relinked),
        "kept_thread_emails": len(items.kept_thread_email_ids),
        "attachments_released": len(items.attachments),
        "attachments_released_incoming": sum(1 for *_, inc in items.attachments if inc),
        "removed_documents": items.removals,
        "primaries": {str(c): list(v) for c, v in items.primaries.items()},
        "pointer_changed": sorted(items.pointers),
        "projection_from_foreign": [
            {"candidate": cid, "doc": doc} for cid, doc, _ in items.projections
        ],
        "stage_copies_with_removed_file": items.stage_copies,
    }


async def clear_projections(db, items: Plan) -> int:
    """Fakty z cudzego CV znikają z profilu (tylko przy ``--apply``).

    Czyszczenie kasuje też wektor w Qdrancie od razu, więc nie biegnie
    w próbie na sucho, którą zamyka rollback.
    """
    from app.services.candidate_identity_quarantine import (
        clear_foreign_cv_projection,
    )

    for victim, doc_id, sha in items.projections:
        await clear_foreign_cv_projection(
            db, candidate_id=victim, document_id=doc_id, document_hash=sha
        )
    await db.flush()
    return len(items.projections)


async def write_history(db, items: Plan) -> None:
    from app.models.activity import Activity

    for victim in items.victims:
        db.add(
            Activity(
                entity_type="candidate",
                entity_id=victim,
                action="m365_unreadable_name_rematch",
                details={
                    "emails_released": sum(
                        1 for _, v, _, _ in items.emails if v == victim
                    ),
                    "attachments_released": sum(
                        1 for _, v, _ in items.attachments if v == victim
                    ),
                    "removed_doc_ids": [d for d, v in items.removals if v == victim],
                    "primary": list(items.primaries.get(victim, (None, None))),
                    "projection_cleared": any(
                        v == victim for v, _, _ in items.projections
                    ),
                },
            )
        )
    await db.flush()


def _chunks(ids: list[int], size: int = 1000):
    for start in range(0, len(ids), size):
        yield ids[start : start + size]


async def _receipt_exists(db) -> bool:
    return bool(
        await db.scalar(
            text("SELECT 1 FROM app_settings WHERE key = :k"), {"k": RECEIPT_KEY}
        )
    )


async def _write_receipt(db, payload: dict[str, Any]) -> None:
    await db.execute(
        text(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (:k, CAST(:v AS jsonb), NOW())
            """
        ),
        {"k": RECEIPT_KEY, "v": json.dumps(payload)},
    )


async def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--expected", help="odcisk planu z próby na sucho (wymagany z --apply)"
    )
    parser.add_argument(
        "--reread",
        type=int,
        action="append",
        default=[],
        help="po zapisie odczyt AI profilu z jego głównego CV (profil, który "
        "czytał cudze CV)",
    )
    args = parser.parse_args(argv)

    from app.core.database import AsyncSessionLocal
    from app.models.candidate_document import CandidateDocument, CandidateDocumentKind

    async with AsyncSessionLocal() as db:
        if args.apply:
            await db.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                {"key": RECEIPT_KEY},
            )
            if await _receipt_exists(db):
                print(f"Paragon {RECEIPT_KEY} już jest — przerywam.", file=sys.stderr)
                return 2
        items = await plan_and_stage(db)
        report = summarize(items)
        print(json.dumps({"plan": report}, ensure_ascii=False, default=str))
        if not args.apply:
            await db.rollback()
            print(
                "Na sucho — nic nie zmieniono. Zapis: --apply --expected "
                f"{report['fingerprint']}"
            )
            return 0
        if args.expected != report["fingerprint"]:
            await db.rollback()
            print(
                f"Plan różni się od próby: odcisk {report['fingerprint']}, "
                f"oczekiwano {args.expected} — przerywam.",
                file=sys.stderr,
            )
            return 2
        if items.stage_copies:
            await db.rollback()
            print(
                "Kopie CV etapu z usuwanym plikiem — decyzja Artura, przerywam.",
                file=sys.stderr,
            )
            return 2
        projections_cleared = await clear_projections(db, items)
        await write_history(db, items)
        receipt = {
            "finished_at": datetime.now(timezone.utc).isoformat(),
            **{k: v for k, v in report.items() if k != "removed_documents"},
            "removed_doc_ids": [d for d, _ in items.removals],
            "projections_cleared": projections_cleared,
        }
        await _write_receipt(db, receipt)
        await db.commit()
        primary_now = dict(
            (
                await db.execute(
                    select(CandidateDocument.candidate_id, CandidateDocument.id).where(
                        CandidateDocument.candidate_id.in_(args.reread or [0]),
                        CandidateDocument.document_kind == CandidateDocumentKind.cv,
                        CandidateDocument.is_primary.is_(True),
                        CandidateDocument.source_deleted_at.is_(None),
                    )
                )
            ).all()
        )
    print(json.dumps(receipt, ensure_ascii=False, default=str))
    if args.reread:
        from app.api.candidates import _enrich_candidate_from_document_task

        for cid in args.reread:
            if cid not in primary_now:
                print(f"Odczyt {cid} pominięty — bez głównego CV.")
                continue
            await _enrich_candidate_from_document_task(
                cid, primary_now[cid], trigger="cv_repair"
            )
            print(f"Odczyt profilu {cid} z dokumentu {primary_now[cid]}.")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(asyncio.run(main()))
