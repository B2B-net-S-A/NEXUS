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

Dwa ograniczenia dołożone 09.2026, oba widoczne dla użytkownika:

* bieg AUTOMATYCZNY rusza wyłącznie w oknie godzin pracy
  (``ORDER_MAIL_RECHECK_START_HOUR_LOCAL`` .. ``_END_HOUR_LOCAL``, Europe/Warsaw).
  Bieg ręczny okna nie pyta. Zawężenie dotyczy TYLKO tego modułu — pobieranie
  poczty i sonda ``checks.order_mail`` zostają dobowe;
* wiersz w ``order_mail_recheck_runs`` powstaje TYLKO wtedy, gdy bieg coś
  zmienił. Wcześniej historia dostawała 24 wiersze dziennie, w większości
  identyczne („sprawdzono N, zaakceptowano 0, te same powody"), a realna
  informacja w nich tonęła. Bieg bez zmian przesuwa wyłącznie znacznik
  „Sprawdzone ostatnio" (``app_settings[STATE_KEY]``).

Czego pominięty wiersz NIE pomija: stempla ``last_at`` na dokumencie, licznika
prób i karty dla Delivery Leada. Historia jest podsumowaniem biegu, a nie jego
mechanizmem — gdyby te trzy rzeczy zależały od zapisu wiersza, karta przestałaby
wychodzić dokładnie wtedy, gdy nic się nie zmienia, czyli gdy jest najbardziej
potrzebna.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import Integer, delete, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.models.order_mail import (
    OUTCOME_APPLIED,
    OUTCOME_AUTO_APPLIED,
    OUTCOME_DUPLICATE,
    OUTCOME_FAILED,
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
    alert_after_hours,
    classify_hold,
    is_recheck_time,
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

#: Znacznik „Sprawdzone ostatnio" + odcisk poprzedniego wyniku. Wiersz
#: ``app_settings``, bez migracji — to stan pętli, nie konfiguracja (ten sam
#: wzorzec co ``compass_lifecycle``). Kolumna na ``order_mail_recheck_runs``
#: odpada z definicji: bieg bez zmian nie zapisuje tam wiersza, więc nie ma na
#: czym stanąć. ``order_mail_sync_state.stats`` też — ``_write_state``
#: przepisuje ten jsonb w całości na końcu biegu skrzynki.
STATE_KEY = "order_mail_recheck_state"
_STATE_VERSION = 1

#: Pola wpisu historii wchodzące do odcisku. ``client_name`` jest świadomie
#: poza: uzupełnia je dopiero ``_fill_client_names`` przy zapisie, więc w tym
#: miejscu jest zawsze ``None`` i niczego by nie rozróżniło.
_FINGERPRINT_FIELDS = (
    "document_id",
    "outcome",
    "category",
    "reasons",
    "alerted",
    "order_number",
    "people",
)

_STATE_UPSERT = text(
    """
    INSERT INTO app_settings (key, value, updated_at)
    VALUES (:key, CAST(:patch AS jsonb), NOW())
    ON CONFLICT (key) DO UPDATE SET
        value = app_settings.value || EXCLUDED.value,
        updated_at = NOW()
    """
)


#: Wpis „Nieudane” (błąd przetwarzania maila) ponawiamy z zachowanego PDF-a
#: najwyżej tyle razy i tylko tak długo od nadejścia maila. Do 25.09.2026
#: `failed` był stanem końcowym: przejściowa awaria (baza, magazyn, restart)
#: zostawiała zamówienie nieprzeczytane na zawsze (audyt 25.09.2026). Każda
#: próba to odczyt modelem, więc liczba prób jest skończona.
FAILED_RETRY_MAX_ATTEMPTS = 3
FAILED_RETRY_MAX_AGE_DAYS = 7


@dataclass
class RecheckRunResult:
    checked: int = 0
    applied: int = 0
    held: int = 0
    alerts: int = 0
    failed_retried: int = 0
    failed_recovered: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)


def recheck_enabled() -> bool:
    return bool(settings.ORDER_MAIL_RECHECK_ENABLED)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def client_not_deleted_clause():
    """Wpis bez klienta albo klienta, który nie jest usunięty.

    Runda 8 (R8-V1-3): writer odmawia zapisu u usuniętego klienta
    (``DELETED_CLIENT_REFUSAL``), więc wstrzymany wpis takiego klienta wracał
    co godzinę do ponownej weryfikacji (odczyt PDF, czasem OCR), zawsze z tą
    samą odmową, a po trzech próbach dostawał kartę DL. Tę samą klauzulę czyta
    dobowa reguła kart (``rule_order_mail_review``) — inaczej bezpiecznik
    czasowy wystawiałby kartę wpisowi, którego recheck już nie dotyka.
    """
    from app.models.client import Client

    return ~(
        select(Client.id)
        .where(
            Client.id == OrderMailDocument.client_id,
            Client.deleted_at.is_not(None),
        )
        .correlate(OrderMailDocument)
        .exists()
    )


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
            ),
            client_not_deleted_clause(),
        )
        .order_by(last_at.nulls_first(), OrderMailDocument.id)
        .limit(max(1, settings.ORDER_MAIL_RECHECK_MAX_DOCS))
    )
    return list((await db.scalars(stmt)).all())


def failed_retry_attempts(row: OrderMailDocument) -> int:
    return int(
        ((row.document_meta or {}).get("failed_retry") or {}).get("attempts") or 0
    )


def failed_retry_pending(
    row: OrderMailDocument, *, now: datetime, has_file: bool
) -> bool:
    """Czy wpis „Nieudane” czeka jeszcze na automatyczne ponowienie.

    Lustro ``_failed_candidate_ids`` dla jednego wpisu — kolejka mówi
    operatorowi „system ponawia sam” wyłącznie wtedy, gdy to prawda. Bez pliku
    na dysku ponowienie i tak wyczerpuje limit prób (``_retry_failed_one``),
    więc brak pliku = brak ponowień.
    """
    if row.outcome != OUTCOME_FAILED or not row.storage_path or not has_file:
        return False
    if failed_retry_attempts(row) >= FAILED_RETRY_MAX_ATTEMPTS:
        return False
    received = row.received_at or row.created_at
    if received is None:
        return False
    if received.tzinfo is None:
        received = received.replace(tzinfo=timezone.utc)
    return received >= now - timedelta(days=FAILED_RETRY_MAX_AGE_DAYS)


async def _failed_candidate_ids(db: AsyncSession, *, now: datetime) -> list[int]:
    """Wpisy „Nieudane” z plikiem, młodsze niż 7 dni, z niewyczerpanymi próbami."""
    cutoff = now - timedelta(days=FAILED_RETRY_MAX_AGE_DAYS)
    received = func.coalesce(
        OrderMailDocument.received_at, OrderMailDocument.created_at
    )
    attempts = func.coalesce(
        OrderMailDocument.document_meta["failed_retry"]["attempts"].astext.cast(
            Integer
        ),
        0,
    )
    stmt = (
        select(OrderMailDocument.id)
        .where(
            OrderMailDocument.outcome == OUTCOME_FAILED,
            OrderMailDocument.storage_path.is_not(None),
            received >= cutoff,
            attempts < FAILED_RETRY_MAX_ATTEMPTS,
        )
        .order_by(OrderMailDocument.id)
        .limit(max(1, settings.ORDER_MAIL_RECHECK_MAX_DOCS))
    )
    return list((await db.scalars(stmt)).all())


async def _locked(db: AsyncSession, doc_id: int) -> Optional[OrderMailDocument]:
    return await db.get(
        OrderMailDocument, doc_id, with_for_update=True, populate_existing=True
    )


async def _retry_failed_one(
    db: AsyncSession, doc_id: int, *, registry: Any, now: datetime
) -> Optional[str]:
    """Jedna próba ponownego przetworzenia. Zwraca wynik albo ``None`` (pominięty).

    Próba jest liczona PRZED przetworzeniem, osobnym commitem: restart kontenera
    w trakcie odczytu (deploy) nie może dawać nieskończonych prób. Przetwarzanie
    trzyma blokadę wiersza — ta sama ścieżka co nowy mail
    (``process_pdf_bytes``: rozpoznanie klienta, odczyt, plan, bramka, zapis).
    Świadomie inaczej niż ``retry_ai_fallback_documents`` (odczyt poza blokadą):
    jedyna akcja kolejki na wpisie ``failed`` to „Odrzuć” (od rundy 2 audytu
    25.09.2026) — czeka na blokadę wiersza i po odczycie działa na NOWYM
    stanie wpisu: zapisane zamówienie (`auto_applied`) odmówi 409, a wpis
    wstrzymany (`needs_review`, `unrecognized_client`) da się odrzucić jak
    każdy inny w kolejce; odrzucenie w przerwie między próbą a odczytem
    wyłapuje ponowne sprawdzenie ``outcome`` po blokadzie. Bieg jest jeden
    naraz (blokada biegu skrzynki), a rozdzielenie ``process_pdf_bytes`` na
    odczyt i zapis zdublowałoby ścieżkę nowego maila.
    """
    from app.services.order_mail_ingest import (
        _first_with_sha,
        process_pdf_bytes,
        processing_error,
    )

    row = await _locked(db, doc_id)
    if (
        row is None
        or row.outcome != OUTCOME_FAILED
        or failed_retry_attempts(row) >= FAILED_RETRY_MAX_ATTEMPTS
    ):
        await db.commit()
        return None
    attempts = failed_retry_attempts(row) + 1
    meta = {"attempts": attempts, "last_at": now.isoformat(), "last_failure": None}

    # Ten sam PDF przysłany ponownie i już przetworzony — ten wpis jest jego
    # duplikatem; drugi odczyt dałby drugi zapis tego samego zamówienia.
    original = (
        await _first_with_sha(db, row.attachment_sha256)
        if row.attachment_sha256
        else None
    )
    if original is not None and original.id != row.id:
        row.outcome = OUTCOME_DUPLICATE
        row.duplicate_of_id = original.id
        row.client_id = original.client_id
        row.client_key = original.client_key
        row.error = None
        row.document_meta = {**(row.document_meta or {}), "failed_retry": meta}
        await db.commit()
        return OUTCOME_DUPLICATE

    try:
        path = storage_service.get_order_mail_attachment_path(row.storage_path)
    except (FileNotFoundError, ValueError):
        path = None
    if path is None or not path.is_file():
        # Pliku nie ma — kolejne próby nic nie zmienią, więc wyczerpujemy limit.
        row.document_meta = {
            **(row.document_meta or {}),
            "failed_retry": {
                **meta,
                "attempts": FAILED_RETRY_MAX_ATTEMPTS,
                "last_failure": "brak pliku PDF",
            },
        }
        await db.commit()
        return None
    row.document_meta = {**(row.document_meta or {}), "failed_retry": meta}
    await db.commit()

    payload = await run_in_threadpool(path.read_bytes)
    row = await _locked(db, doc_id)
    if row is None or row.outcome != OUTCOME_FAILED:
        await db.commit()  # ktoś zdążył wpis zmienić
        return None
    try:
        row.error = None
        await process_pdf_bytes(db, row, payload, registry=registry)
        row.document_meta = {
            **(row.document_meta or {}),
            "failed_retry": {**meta, "recovered_at": now.isoformat()},
        }
        db.add(row)
        await db.commit()
        return row.outcome
    except Exception as exc:  # noqa: BLE001 — jeden wpis nie wywraca biegu
        logger.exception("order_mail: retry of failed doc %s failed", doc_id)
        await db.rollback()
        row = await _locked(db, doc_id)
        if row is not None:
            # Klasa wyjątku, nie ``repr`` (ścieżki, SQL) — pełny opis jest w logu.
            row.error = processing_error(exc)
            row.document_meta = {
                **(row.document_meta or {}),
                "failed_retry": {**meta, "last_failure": type(exc).__name__},
            }
            await db.commit()
        return OUTCOME_FAILED


async def retry_failed_documents(
    db: AsyncSession, result: RecheckRunResult, *, now: datetime
) -> None:
    """Ponów przetworzenie wpisów „Nieudane” z zachowanego PDF-a."""
    ids = await _failed_candidate_ids(db, now=now)
    if not ids:
        return
    from app.services.order_mail_ingest import build_registry_from_db

    registry = await build_registry_from_db(db)
    for doc_id in ids:
        try:
            outcome = await _retry_failed_one(db, doc_id, registry=registry, now=now)
        except Exception:  # noqa: BLE001 — jeden wpis nie wywraca biegu
            logger.exception("order_mail: retry of failed doc %s crashed", doc_id)
            await db.rollback()
            continue
        if outcome is None:
            continue
        result.failed_retried += 1
        if outcome != OUTCOME_FAILED:
            result.failed_recovered += 1


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
    # Odczyt powstał bez reguł klienta (klient był nieznany) — przeliczenie
    # planu zastosuje je deterministycznie, bez modelu (FIN-MAIL-05).
    row.document_meta = {**(row.document_meta or {}), "policies_pending": True}
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
        # WYPROWADZONY z okna godzin, nie surowa wartość z konfiguracji — przy
        # zamkniętym oknie nocnym surowe 6 h alarmowałoby całą kolejkę co noc.
        after_hours=alert_after_hours(),
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

    row = await db.get(
        OrderMailDocument, doc_id, with_for_update=True, populate_existing=True
    )
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
        row = await db.get(
            OrderMailDocument, doc_id, with_for_update=True, populate_existing=True
        )
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


def outcome_fingerprint(details: list[dict[str, Any]]) -> str:
    """Odcisk WYNIKU biegu — po nim poznajemy „nic się nie zmieniło".

    Porównujemy stan wstrzymanych zamówień, nie same liczniki: zmiana powodu
    przy niezmienionej liczbie wpisów też jest zmianą i musi zostawić ślad
    w historii. ``alerted`` wchodzi do odcisku, bo bieg, w którym poszła karta
    do Delivery Leada, jest zdarzeniem, choć powody wyglądają identycznie.

    Sortowanie po ``document_id``: kolejność wpisów zależy od rotacji
    ``last_at NULLS FIRST``, więc ta sama kolejka potrafi przyjść w innej
    kolejności i bez sortowania każdy bieg wyglądałby na zmianę.
    """
    rows = sorted(
        (
            {k: entry.get(k) for k in _FINGERPRINT_FIELDS}
            for entry in details
            if isinstance(entry, dict)
        ),
        key=lambda row: row.get("document_id") or 0,
    )
    blob = json.dumps(rows, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


async def read_recheck_state(db: AsyncSession) -> dict[str, Any]:
    """Znacznik ostatniego sprawdzenia. Brak wiersza = pusty stan, nie błąd."""
    try:
        row = await db.execute(
            text("SELECT value FROM app_settings WHERE key = :key"),
            {"key": STATE_KEY},
        )
        value = row.scalar()
    except Exception:  # noqa: BLE001 — brak znacznika nie może wywrócić biegu
        logger.exception("order_mail: could not read recheck state")
        # Bez wycofania sesja zostaje w padniętej transakcji i wywraca to, co
        # wołający zrobi dalej — a ta funkcja ma odpowiadać „nie wiem", nie
        # zatruwać cudzą pracę.
        await db.rollback()
        return {}
    return value if isinstance(value, dict) else {}


async def _save_state(
    db: AsyncSession,
    *,
    checked_at: datetime,
    fingerprint: str,
    changed: bool,
    unchanged_runs: int,
) -> None:
    """Przesuń znacznik „Sprawdzone ostatnio". Nigdy nie rzuca.

    Scalenie (``||``), nie nadpisanie: wiersz może z czasem dostać klucze
    zapisywane gdzie indziej, a padnięty zapis znacznika nie ma prawa wycofać
    przeliczenia, które właśnie się udało.
    """
    patch = {
        "version": _STATE_VERSION,
        "last_checked_at": checked_at.astimezone(timezone.utc).isoformat(),
        "fingerprint": fingerprint,
        "unchanged_runs": unchanged_runs,
    }
    if changed:
        patch["last_change_at"] = patch["last_checked_at"]
    try:
        await db.execute(_STATE_UPSERT, {"key": STATE_KEY, "patch": json.dumps(patch)})
        await db.commit()
    except Exception:  # noqa: BLE001 — znacznik jest informacją, nie mechanizmem
        logger.exception("order_mail: could not stamp recheck state")
        await db.rollback()


async def _prune_history(db: AsyncSession) -> None:
    """Retencja historii — wołana w KAŻDYM biegu, także tym bez zmian.

    Gdyby wisiała na zapisie wiersza, tydzień bez zmian oznaczałby tydzień bez
    sprzątania, a trzydziestodniowa obietnica retencji byłaby spełniana
    przypadkiem.
    """
    cutoff = _now() - timedelta(days=max(1, settings.ORDER_MAIL_RECHECK_HISTORY_DAYS))
    try:
        await db.execute(
            delete(OrderMailRecheckRun).where(OrderMailRecheckRun.started_at < cutoff)
        )
        await db.commit()
    except Exception:  # noqa: BLE001 — sprzątanie nie wywraca biegu
        logger.exception("order_mail: recheck history retention failed")
        await db.rollback()


async def _record_run(
    db: AsyncSession, result: RecheckRunResult, *, started_at: datetime, trigger: str
) -> None:
    """Wiersz historii. Historia jest ZDENORMALIZOWANA świadomie."""
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
    await db.commit()


async def run_recheck(
    db: AsyncSession, *, trigger: str = "scheduled"
) -> RecheckRunResult:
    """Cały bieg. Jeden zepsuty wpis nie wywraca pozostałych ani biegu skrzynki."""
    result = RecheckRunResult()
    if not recheck_enabled():
        return result
    started_at = _now()
    if trigger != "manual" and not is_recheck_time(started_at):
        # Poza oknem godzin pracy: zero zapytań, zero stempli, znacznik
        # „Sprawdzone ostatnio" stoi na ostatnim realnym biegu. To jest prawda
        # („ostatnio sprawdzone o 17:05"), a nie brak danych — dlatego marker
        # NIE jest tu przesuwany. Ręczne „Pobierz zamówienia z maila"
        # (`trigger="manual"`) tu nie trafia.
        return result
    # Najpierw wpisy „Nieudane”: udane ponowienie zwykle kończy się „Do
    # weryfikacji”, więc ten sam bieg od razu przelicza je dalej.
    try:
        await retry_failed_documents(db, result, now=started_at)
    except Exception:  # noqa: BLE001 — ponowienie nie wywraca biegu
        logger.exception("order_mail: retry of failed documents failed")
        await db.rollback()
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
    state = await read_recheck_state(db)
    fingerprint = outcome_fingerprint(result.details)
    if result.checked or result.details:
        # Bieg ręczny zapisuje wiersz zawsze: jest odpowiedzią na kliknięcie,
        # a „nic się nie zmieniło" to odpowiedź, na którą klikający czeka.
        # `applied` jest wymienione osobno, choć zapis i tak zdejmuje wpis
        # z kolejki i zmienia odcisk — reguła z ticketu ma być widoczna
        # w kodzie, nie wyprowadzana.
        changed = (
            trigger == "manual"
            or result.applied > 0
            or fingerprint != state.get("fingerprint")
        )
        if changed:
            await _record_run(db, result, started_at=started_at, trigger=trigger)
    else:
        # Pusta kolejka: bieg się odbył, ale nie miał czego raportować. Znacznik
        # i tak przesuwamy — pusta historia z aktualnym „Sprawdzone ostatnio"
        # mówi „mechanizm żyje, nie ma nic do zrobienia", a bez znacznika
        # czytałaby się jak awaria.
        changed = False
    await _prune_history(db)
    await _save_state(
        db,
        checked_at=started_at,
        fingerprint=fingerprint,
        changed=changed,
        unchanged_runs=0 if changed else int(state.get("unchanged_runs") or 0) + 1,
    )
    return result
