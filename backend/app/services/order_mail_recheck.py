"""Godzinowa ponowna weryfikacja wstrzymanych zamówień z maila.

Wpis, który trafił do „Do weryfikacji", nie wracał sam: jedyne automatyczne
przeliczenie (``replan_outdated_documents``) odpalało się tylko po zmianie
``rule_version`` polityki klienta. Jeśli przyczyna zniknęła z innego powodu —
podpisano umowę B2B nowego kontraktora, ktoś uzupełnił NIP klienta — dokument
wisiał ze starym powodem, dopóki człowiek nie kliknął „Przelicz plan".

Ten moduł robi to samo, co ten przycisk, dla KAŻDEGO wstrzymanego wpisu, w tym
samym biegu skrzynki (``ORDER_MAIL_POLL_INTERVAL_MINUTES``, domyślnie 60 min).
Jedzie lokalnie i PRZED Graphem, więc działa też przy awarii skrzynki.

Dwie ścieżki, bo dwa różne stany wstrzymania:

* **„Do weryfikacji"** — dokument ma klienta i odczyt: ``replan_and_apply``
  odświeża plan z zapisanego odczytu i zapisuje pewny plan. Bez modelu AI.
* **„Nie rozpoznano klienta"** — dokument nie ma klienta: ponawiamy SAMO
  rozpoznanie (tekst z zapisanego PDF-a + rejestr NIP-ów). Dopiero rozpoznany
  klient przechodzi na ścieżkę pierwszą. Świadomie nie wołamy ponownie
  ``process_pdf_bytes``: ta funkcja czyta modelem PRZED sprawdzeniem klienta,
  więc płaciłaby za AI w każdym biegu.

Kartę Delivery Leada wystawia dopiero trzecia nieudana próba z rzędu — i nigdy
zamówienie czekające na podpis umowy (patrz ``order_mail_recheck_reasons``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.models.order_mail import (
    OUTCOME_APPLIED,
    OUTCOME_AUTO_APPLIED,
    OUTCOME_NEEDS_REVIEW,
    OUTCOME_UNRECOGNIZED,
    OrderMailDocument,
    OrderMailRecheckRun,
)
from app.services import storage_service
from app.services.order_document_text import extract_order_text
from app.services.order_pdf_parser import polish_gate_reason
from app.services.order_mail_recheck_reasons import (
    CATEGORY_UNRECOGNIZED,
    advance_attempts,
    classify_hold,
    should_alert,
)

logger = logging.getLogger(__name__)

#: Ile powodów i znaków trafia do historii biegu. Historia ma odpowiadać na
#: pytanie „dlaczego to wisiało", nie być kopią dokumentu.
MAX_HISTORY_REASONS = 5
MAX_HISTORY_REASON_CHARS = 400

OUTCOME_ENTRY_APPLIED = "applied"
OUTCOME_ENTRY_HELD = "held"
OUTCOME_ENTRY_ERROR = "error"


@dataclass
class RecheckRunResult:
    checked: int = 0
    applied: int = 0
    held: int = 0
    alerts: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)


def recheck_enabled() -> bool:
    return bool(settings.ORDER_MAIL_RECHECK_ENABLED)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _candidate_ids(db: AsyncSession, *, now: datetime) -> list[int]:
    """Wstrzymane wpisy do przejrzenia w tym biegu, najdawniej sprawdzone pierwsze.

    Sufit na bieg jest świadomy: każdy recheck to ekstrakcja tekstu z PDF-a,
    a skan idzie przez OCR. Kolejność po ``last_at`` z ``NULLS FIRST`` sprawia,
    że przy kolejce większej niż sufit nic nie głoduje — najnowsze wpisy nie
    mają jeszcze śladu, więc idą pierwsze, a reszta rotuje.

    Wpisy „Nie rozpoznano klienta" starsze niż
    ``ORDER_MAIL_RECHECK_UNRECOGNIZED_DAYS`` odpadają: znikają z kolejki tylko
    ręcznie, więc bez sufitu OCR-owalibyśmy je co godzinę bez końca.
    """
    cutoff = now - timedelta(days=max(1, settings.ORDER_MAIL_RECHECK_UNRECOGNIZED_DAYS))
    received = func.coalesce(
        OrderMailDocument.received_at, OrderMailDocument.created_at
    )
    last_at = OrderMailDocument.document_meta["recheck"]["last_at"].astext
    stmt = (
        select(OrderMailDocument.id)
        .where(
            or_(
                (OrderMailDocument.outcome == OUTCOME_NEEDS_REVIEW)
                & OrderMailDocument.client_id.is_not(None)
                & OrderMailDocument.applied_order_id.is_(None),
                (OrderMailDocument.outcome == OUTCOME_UNRECOGNIZED)
                & (received >= cutoff),
            )
        )
        .order_by(last_at.nulls_first(), OrderMailDocument.id)
        .limit(max(1, settings.ORDER_MAIL_RECHECK_MAX_DOCS))
    )
    return list((await db.scalars(stmt)).all())


async def _reidentify_client(db: AsyncSession, row: OrderMailDocument) -> bool:
    """Ponów SAMO rozpoznanie klienta dla wpisu „Nie rozpoznano klienta".

    Bez modelu: tekst z zapisanego PDF-a plus rejestr z bazy. Zwraca ``True``,
    gdy klient został rozpoznany — wtedy wywołujący przechodzi na zwykłą
    ścieżkę przeliczenia planu.
    """
    from app.services.order_mail_ingest import (
        build_registry_from_db,
        resolve_order_client_id,
    )
    from app.services.order_client_identity import identify_client

    if not row.storage_path:
        return False
    try:
        # Helper RZUCA, gdy pliku nie ma — a plik znika (retencja, ręczne
        # sprzątanie). Brak pliku to „nie da się rozpoznać", nie awaria biegu.
        path = storage_service.get_order_mail_attachment_path(row.storage_path)
    except (FileNotFoundError, ValueError):
        return False
    if not path.is_file():
        return False
    doc = await run_in_threadpool(
        extract_order_text, str(path), row.attachment_name or "zamowienie.pdf"
    )
    registry = await build_registry_from_db(db)
    ident = identify_client(doc.text, registry, sender_email=row.sender_email)
    client_id, policy_key = await resolve_order_client_id(db, ident)
    if client_id is None:
        return False
    row.client_id = client_id
    row.client_key = policy_key or (ident.client_key if ident.client_key else None)
    row.identification_method = ident.method
    row.identification_reason = ident.reason
    # Dalej jedzie zwykła ścieżka kolejki: plan i bramka rozstrzygną, czy
    # dokument wolno zapisać automatem.
    row.outcome = OUTCOME_NEEDS_REVIEW
    return True


def _history_entry(
    row: OrderMailDocument, *, outcome: str, category: Optional[str]
) -> dict[str, Any]:
    from app.services.order_mail_ingest import _mail_candidate_names

    # Ta sama redakcja co kolejka (`order_mail_queue._serialize`): powody
    # zapisane przed 09.2026 bywają po angielsku, a historia stałaby wtedy
    # obok kolejki z innym tekstem tego samego powodu.
    reasons = [
        polish_gate_reason(str(text))[:MAX_HISTORY_REASON_CHARS]
        for text in (row.gate_reasons or [])[:MAX_HISTORY_REASONS]
    ]
    return {
        "document_id": row.id,
        "client_id": row.client_id,
        "client_name": None,
        "order_number": (row.extraction or {}).get("title") or row.attachment_name,
        "people": _mail_candidate_names(row)[:5],
        "outcome": outcome,
        "category": category,
        "reasons": reasons,
    }


async def _maybe_alert(db: AsyncSession, row: OrderMailDocument, meta: dict) -> bool:
    """Karta dla Delivery Leada — tylko gdy reguła alertu na to pozwala."""
    from app.services.order_mail_ingest import notify_review

    if row.client_id is None:
        return False
    if not should_alert(
        meta,
        waiting_since=row.received_at or row.created_at,
        now=_now(),
        after_attempts=settings.ORDER_MAIL_RECHECK_ALERT_AFTER_ATTEMPTS,
        after_hours=settings.ORDER_MAIL_RECHECK_ALERT_AFTER_HOURS,
    ):
        return False
    try:
        # SAVEPOINT: padnięte powiadomienie nie może wycofać przeliczenia ani
        # licznika prób. Bez tego wpis co godzinę wracałby na tę samą próbę,
        # a karta nigdy by nie wyszła.
        async with db.begin_nested():
            created = await notify_review(db, row)
    except Exception:  # noqa: BLE001 — alert nie może wywrócić ponownej weryfikacji
        logger.exception("order_mail: recheck alert failed for doc %s", row.id)
        return False
    if created:
        meta["alerted_at"] = _now().isoformat()
    return bool(created)


async def _close_review_cards(db: AsyncSession, doc_id: int) -> None:
    """Dokument opuścił kolejkę — zdejmij kartę od razu, nie czekaj na skaner."""
    from app.services.dl_alerts import resolve_entity_alerts

    await resolve_entity_alerts(
        db, alert_type="order_mail_review", entity_key=f"order_mail:{doc_id}"
    )


async def _recheck_one(db: AsyncSession, doc_id: int) -> Optional[dict[str, Any]]:
    """Jeden dokument w osobnej transakcji. Zwraca wpis do historii albo ``None``."""
    from app.services.order_mail_ingest import _replannable, replan_and_apply

    row = await db.get(OrderMailDocument, doc_id, with_for_update=True)
    if row is None or row.outcome not in (OUTCOME_NEEDS_REVIEW, OUTCOME_UNRECOGNIZED):
        await db.commit()  # zwolnij blokadę wiersza
        return None

    recognized_now = False
    if row.outcome == OUTCOME_UNRECOGNIZED:
        recognized_now = await _reidentify_client(db, row)
        if not recognized_now:
            meta = advance_attempts(
                (row.document_meta or {}).get("recheck"),
                category=CATEGORY_UNRECOGNIZED,
                now=_now(),
            )
            row.document_meta = {**(row.document_meta or {}), "recheck": meta}
            entry = _history_entry(
                row, outcome=OUTCOME_ENTRY_HELD, category=meta["category"]
            )
            await db.commit()
            return entry

    if not _replannable(row):
        # Brak odczytu, brak pliku na dysku albo zamówienie już (częściowo)
        # zapisane. To NIE naprawi się samo, więc wpis eskaluje jak każdy inny
        # problem — i MUSI dostać stempel czasu. Bez stempla sortowanie
        # `last_at NULLS FIRST` stawiało go na czele rotacji w każdym biegu:
        # sto takich wierszy zjadało cały budżet, nie zostawiając w historii
        # ani jednego śladu.
        category = classify_hold(
            row.gate_reason_codes, client_known=row.client_id is not None
        )
        meta = advance_attempts(
            (row.document_meta or {}).get("recheck"), category=category, now=_now()
        )
        row.document_meta = {**(row.document_meta or {}), "recheck": meta}
        await db.flush()
        alerted = await _maybe_alert(db, row, meta)
        if alerted:
            row.document_meta = {**row.document_meta, "recheck": {**meta}}
        entry = _history_entry(row, outcome=OUTCOME_ENTRY_HELD, category=category)
        entry["alerted"] = alerted
        entry["reasons"] = entry["reasons"] or [
            "Nie da się przeliczyć: brak odczytu, pliku źródłowego albo "
            "zamówienie zostało już częściowo zapisane"
        ]
        await db.commit()
        return entry

    await replan_and_apply(db, row, actor_user_id=None)
    if row.outcome in (OUTCOME_AUTO_APPLIED, OUTCOME_APPLIED):
        meta_before = row.document_meta or {}
        row.document_meta = {k: v for k, v in meta_before.items() if k != "recheck"}
        await _close_review_cards(db, row.id)
        entry = _history_entry(row, outcome=OUTCOME_ENTRY_APPLIED, category=None)
        await db.commit()
        return entry

    category = classify_hold(
        row.gate_reason_codes, client_known=row.client_id is not None
    )
    meta = advance_attempts(
        (row.document_meta or {}).get("recheck"), category=category, now=_now()
    )
    # Kolejność jest load-bearing: wynik przeliczenia i licznik prób idą do
    # transakcji PRZED savepointem alertu. Wycofanie savepointu unieważnia
    # obiekty zmienione w jego trakcie, a niezapisany stan wróciłby wtedy jako
    # leniwy odczyt — w sesji async to MissingGreenlet.
    row.document_meta = {**(row.document_meta or {}), "recheck": meta}
    await db.flush()
    alerted = await _maybe_alert(db, row, meta)
    if alerted:
        # ``meta`` dostało ``alerted_at`` w miejscu, a JSONB nie śledzi mutacji
        # w środku — dopiero NOWY obiekt jest dla SQLAlchemy zmianą.
        row.document_meta = {**row.document_meta, "recheck": {**meta}}
    entry = _history_entry(row, outcome=OUTCOME_ENTRY_HELD, category=category)
    entry["alerted"] = alerted
    await db.commit()
    return entry


async def _stamp_failed_attempt(db: AsyncSession, doc_id: int) -> Optional[str]:
    """Policz nieudaną próbę po wycofanej transakcji. Nigdy nie rzuca."""
    try:
        row = await db.get(OrderMailDocument, doc_id, with_for_update=True)
        if row is None:
            await db.commit()
            return None
        category = classify_hold(
            row.gate_reason_codes, client_known=row.client_id is not None
        )
        meta = advance_attempts(
            (row.document_meta or {}).get("recheck"), category=category, now=_now()
        )
        row.document_meta = {**(row.document_meta or {}), "recheck": meta}
        await db.flush()
        alerted = await _maybe_alert(db, row, meta)
        if alerted:
            row.document_meta = {**row.document_meta, "recheck": {**meta}}
        await db.commit()
        return category
    except Exception:  # noqa: BLE001 — stempel nie może wywrócić biegu
        logger.exception("order_mail: could not stamp failed recheck for %s", doc_id)
        await db.rollback()
        return None


async def _fill_client_names(db: AsyncSession, details: list[dict[str, Any]]) -> None:
    from app.models.client import Client
    from app.services.client_identity import client_display_name_expression

    ids = {d["client_id"] for d in details if d.get("client_id")}
    if not ids:
        return
    rows = (
        await db.execute(
            select(Client.id, client_display_name_expression()).where(
                Client.id.in_(ids)
            )
        )
    ).all()
    names = {cid: name for cid, name in rows}
    for detail in details:
        detail["client_name"] = names.get(detail.get("client_id"))


async def _record_run(
    db: AsyncSession, result: RecheckRunResult, *, started_at: datetime, trigger: str
) -> None:
    """Wiersz historii + retencja. Historia jest ZDENORMALIZOWANA świadomie."""
    await _fill_client_names(db, result.details)
    db.add(
        OrderMailRecheckRun(
            started_at=started_at,
            finished_at=_now(),
            trigger="manual" if trigger == "manual" else "scheduled",
            checked=result.checked,
            applied=result.applied,
            held=result.held,
            details=result.details,
        )
    )
    cutoff = _now() - timedelta(days=max(1, settings.ORDER_MAIL_RECHECK_HISTORY_DAYS))
    await db.execute(
        delete(OrderMailRecheckRun).where(OrderMailRecheckRun.started_at < cutoff)
    )
    await db.commit()


async def run_recheck(
    db: AsyncSession, *, trigger: str = "scheduled"
) -> RecheckRunResult:
    """Cały bieg. Jeden zepsuty wpis nie wywraca pozostałych ani biegu skrzynki."""
    result = RecheckRunResult()
    if not recheck_enabled():
        return result
    started_at = _now()
    for doc_id in await _candidate_ids(db, now=started_at):
        try:
            entry = await _recheck_one(db, doc_id)
        except Exception as exc:  # noqa: BLE001 — jeden wpis nie wywraca biegu
            logger.exception("order_mail: recheck failed for doc %s", doc_id)
            await db.rollback()
            # Stempel PO rollbacku, osobną transakcją: bez niego wpis wracał na
            # czoło rotacji (`last_at NULLS FIRST`) co godzinę i zamrażał
            # licznik prób, więc Delivery Lead nie dostawał karty nigdy —
            # a dobowy skaner zamykał nawet tę, którą dostał wcześniej.
            category = await _stamp_failed_attempt(db, doc_id)
            result.checked += 1
            result.held += 1
            result.details.append(
                {
                    "document_id": doc_id,
                    "client_id": None,
                    "client_name": None,
                    "order_number": None,
                    "people": [],
                    "outcome": OUTCOME_ENTRY_ERROR,
                    "category": category,
                    # Klasa wyjątku, nie ``repr``: ten drugi wchodzi do listy
                    # widocznej dla człowieka i potrafi nieść ścieżki z dysku.
                    "reasons": [
                        f"Ponowna weryfikacja nie powiodła się ({type(exc).__name__})"
                    ],
                }
            )
            continue
        if entry is None:
            continue
        result.checked += 1
        if entry["outcome"] == OUTCOME_ENTRY_APPLIED:
            result.applied += 1
        else:
            result.held += 1
        if entry.get("alerted"):
            result.alerts += 1
        result.details.append(entry)
    if result.checked or result.details:
        await _record_run(db, result, started_at=started_at, trigger=trigger)
    return result
