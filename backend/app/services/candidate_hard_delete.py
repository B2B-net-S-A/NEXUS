"""Trwałe usunięcie kandydata — jedna ścieżka dla przycisku „Usuń” i korekt.

Wydzielone z ``DELETE /api/candidates/{id}`` (20.10.2026), żeby jednorazowe
sprzątanie rekordów testowych z produkcji (``prod_test_records_cleanup``)
szło dokładnie tą samą drogą co usunięcie z profilu: pseudonim na umowach,
retencja plików, anonimizacja kalendarza, audyt i outbox wektora. Endpoint
mapuje :class:`CandidateEraseBlocked` na odpowiedź HTTP; commit należy do
wołającego, a :func:`finish_after_commit` biegnie po nim.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument
from app.models.contract import Contract
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.cv_generated_share import CvGeneratedShareToken
from app.models.index_outbox import IndexOutboxEvent
from app.models.note import Note
from app.models.user import User
from app.services import candidate_audit
from app.services.candidate_audit import candidate_subject_reference
from app.services.critical_events import record_executed

logger = logging.getLogger(__name__)


class CandidateEraseBlocked(Exception):
    """Usunięcie niemożliwe teraz; nic nie zostało zmienione."""

    def __init__(self, *, status_code: int, detail: Any) -> None:
        super().__init__(status_code)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class EraseOutcome:
    candidate_id: int
    champion_job_ids: tuple[int, ...]
    teams_to_cancel: tuple[tuple[str, str], ...]
    tokens_revoked: int


async def erase_candidate(
    db: AsyncSession, candidate: Candidate, *, actor: Optional[User]
) -> EraseOutcome:
    """Usuń wiersz kandydata z całym sprzątaniem; bez commitu."""

    candidate_id = candidate.id
    actor_id = actor.id if actor is not None else None

    # Serialize erasure with new source rows referencing this candidate.
    await db.refresh(candidate, with_for_update=True)

    # Zgłoszenia Akademii znikają kaskadą. Zwrócone wydanie sprzętu traci
    # posiadacza (historia zostaje w protokole), niezwróconego nie zostawiamy
    # „wydanego nikomu” — najpierw zwrot (0465, decyzja z przeglądu 16.10).
    from app.services.equipment.registry import (
        ACADEMY_EQUIPMENT_HELD,
        active_academy_assignments,
    )

    if await active_academy_assignments(db, candidate_id=candidate_id):
        raise CandidateEraseBlocked(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "academy_equipment_active",
                "message": ACADEMY_EQUIPMENT_HELD,
            },
        )

    # Klucze plików trzeba zebrać TERAZ — po `db.delete()` wiersze już nie
    # istnieją, a bez klucza nie da się skasować obiektu ze storage.
    storage_keys: list[str] = []
    if candidate.cv_storage_key:
        storage_keys.append(candidate.cv_storage_key)
    document_keys = await db.execute(
        select(CandidateDocument.storage_key).where(
            CandidateDocument.candidate_id == candidate_id,
            CandidateDocument.storage_key.is_not(None),
        )
    )
    storage_keys.extend(k for k in document_keys.scalars().all() if k)

    from app.services.cv_source_erasure import detach_candidate_job_sources

    storage_keys.extend(await detach_candidate_job_sources(db, candidate_id))

    # Zgłoszenia z formularza aplikacyjnego (z CV w bazie albo w storage)
    # ZOSTAJĄ: FK `matched_candidate_id` to SET NULL (decyzja Artura
    # 26.09.2026 — „nie usuwać nigdy żadnych CV”, RODO pomijamy; do tego dnia
    # kasowała je `erase_candidate_submissions`, audyt 22.09 r2 CAND-02).

    # audyt 22.09 r2 (PROD-02): kopie snapshotów CV etapów w object storage
    # (`stage-cv/<candidate_id>/…`) znikają razem z osobą — wiersze
    # `candidate_stage_cvs` kaskadują, obiekty w storage nie.
    from app.services.candidate_stage_cv_service import snapshot_keys_for_candidate

    storage_keys.extend(await snapshot_keys_for_candidate(db, candidate_id))
    storage_keys = sorted(set(storage_keys))

    # Pseudonimizacja umów PRZED usunięciem: `SET NULL` zadziała w bazie sam,
    # ale zerwie jedyne powiązanie między fakturami jednego podmiotu.
    # Fail-closed ZOSTAJE (bez możliwości pseudonimizacji umów nie wolno usunąć
    # kandydata), ale nieobsłużony `RuntimeError` dawał operatorowi gołe
    # „Internal Server Error", a przyczynę — brak
    # `CANDIDATE_IDENTITY_FINGERPRINT_KEY` — tylko w logach. 503, bo to problem
    # konfiguracji serwera, nie błąd żądania.
    try:
        subject_ref = candidate_subject_reference(candidate_id)
    except RuntimeError as exc:
        raise CandidateEraseBlocked(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    # Runda 9 (R9-N7-12): CV trzymane w bazie znikały z kaskadą, a klucze
    # plików w magazynie traciły jedyny wskaźnik. Najpierw kopia i rejestr
    # (pod pseudonimem), dopiero potem cokolwiek innego — bez magazynu przy CV
    # w bazie odmawiamy, zanim coś zmienimy.
    from app.services.candidate_cv_retention import (
        CvRetentionUnavailable,
        retain_candidate_files,
    )

    try:
        cv_files_retained = await retain_candidate_files(
            db, candidate_id, subject_ref=subject_ref, storage_keys=storage_keys
        )
    except CvRetentionUnavailable as exc:
        raise CandidateEraseBlocked(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "cv_retention_unavailable",
                "message": (
                    "Nie można teraz usunąć kandydata: jego CV zapisane w bazie "
                    "nie dały się przenieść do magazynu plików. Spróbuj później."
                ),
            },
        ) from exc
    contracts_detached = (
        await db.execute(
            update(Contract)
            .where(
                Contract.candidate_id == candidate_id,
                Contract.candidate_subject_ref.is_(None),
            )
            .values(candidate_subject_ref=subject_ref)
        )
    ).rowcount

    # Kontakt do konsultanta skopiowany na umowę (migracja 0316) MUSI zniknąć
    # razem z osobą. Wiersz umowy celowo zostaje (wiszą na nim podpisy i
    # faktury), ale e-mail i telefon to dokładnie te dane, których dotyczy
    # art. 17 — zostawione tu przeżyłyby usunięcie profilu w ciszy, bo żaden
    # ekran nie mówi, że umowa trzyma własną kopię. Osobny UPDATE, nie
    # rozszerzenie tego wyżej: tamten jest zawężony do umów jeszcze nie
    # ostemplowanych, a czyścić trzeba WSZYSTKIE umowy tej osoby.
    await db.execute(
        update(Contract)
        .where(Contract.candidate_id == candidate_id)
        .values(candidate_email=None, candidate_phone=None)
    )

    # Odwołanie publicznych linków do WYGENEROWANYCH CV tej osoby. `cv_generated
    # _documents.candidate_id` to `SET NULL`, więc dokument (a z nim
    # `render_payload` = pełne CV) przeżywa usunięcie — a token, który go
    # odblokowuje, kaskaduje z dokumentu, nie z kandydata. Bez tego
    # `/api/public/cv-i/{token}` dalej serwowałby CV usuniętej osoby hiring
    # managerowi u klienta przez cały TTL linku (do 90 dni), a jego czat AI
    # dalej odpowiadałby na nowe pytania o nią. Dwie pozostałe rodziny tokenów
    # (`champion_share`, `cv_share_token`) kaskadują z kandydata i znikają same.
    # Od rundy 6 audytu same dokumenty też znikają (`erase_candidate_leftovers`
    # niżej) — odwołanie zostaje, bo tylko ono zostawia ślad w dowodzie
    # wykonania (`share_tokens_revoked`).
    now = datetime.now(timezone.utc)
    tokens_revoked = (
        await db.execute(
            update(CvGeneratedShareToken)
            .where(
                CvGeneratedShareToken.generated_document_id.in_(
                    select(CvGeneratedDocument.id).where(
                        CvGeneratedDocument.candidate_id == candidate_id
                    )
                ),
                CvGeneratedShareToken.revoked.is_(False),
            )
            .values(
                revoked=True,
                revoked_at=now,
                revoked_by=actor_id,
                revoke_reason="candidate_erasure",
            )
        )
    ).rowcount

    # Wiersze pełnego przeglądu bazy (`candidate_search_results`) nie mają FK
    # na kandydata — celowo, żeby migawka przeżyła zmianę w trakcie przeglądu —
    # więc kaskada ich nie zabierze, a niosą dowody dopasowania tej osoby.
    # Aktywny przegląd nie może po prostu stracić wiersza (`finish_run` wymaga
    # rozliczenia całej migawki), więc najpierw jest oznaczany jako `failed`
    # i jego autor uruchamia go ponownie.
    from app.services.candidate_search_store import erase_candidate

    search_erasure = await erase_candidate(db, candidate_id)

    # Rozmowy Jarvisa, w których padły dane tej osoby (0330) — treść to JSON,
    # więc kaskada FK jej nie sięga; powiązanie trzyma
    # `jarvis_conversation_entities`.
    from app.services.jarvis.erasure import erase_candidate as erase_jarvis_candidate

    jarvis_erasure = await erase_jarvis_candidate(db, candidate_id)
    # Runda 6 audytu (RODO-01/02/03/06/07): nagrobek dla syncu Traffita,
    # wygenerowane CV razem ze zrzutem zgody, powiadomienia z nazwiskiem,
    # nazwisko w dzienniku integracji i stempel próby na załącznikach CV
    # z maili — tego kaskada FK nie zabiera. Po odwołaniu linków wyżej, bo
    # licznik `share_tokens_revoked` liczy tokeny jeszcze istniejących CV.
    from app.services.candidate_erasure_leftovers import erase_candidate_leftovers

    leftovers, leftover_keys = await erase_candidate_leftovers(db, candidate)
    storage_keys = sorted(set(storage_keys) | set(leftover_keys))
    # Skrzynka „Propozycje" (0333): FK ma ON DELETE CASCADE, więc wiersze i tak
    # znikną razem z kandydatem — kasujemy je JAWNIE, żeby liczba trafiła do
    # dowodu wykonania żądania z art. 17 (kaskada nie zostawia śladu).
    from sqlalchemy import delete as sa_delete

    from app.models.job_proposal import JobProposal

    search_erasure["job_proposals_deleted"] = (
        await db.execute(
            sa_delete(JobProposal).where(JobProposal.candidate_id == candidate_id)
        )
    ).rowcount or 0
    # Przyszłe prepy i follow-upy w Teams trzeba odwołać (kandydat ma
    # zaproszenie), a wydarzenia kalendarza — zanonimizować: FK `SET NULL`
    # zostawiał tytuł z imieniem i nazwiskiem oraz e-mail w uczestnikach
    # (runda 6 audytu). Graph wołamy dopiero po commicie usunięcia.
    from app.services.followup_meetings import erase_candidate_meetings

    teams_to_cancel, calendar_erasure = await erase_candidate_meetings(db, candidate)
    search_erasure.update(calendar_erasure)
    # Prepy w Teams (0370): transkrypty i oceny idą kaskadą z kandydatem —
    # kasujemy je jawnie, żeby liczba trafiła do dowodu wykonania art. 17.
    # Kopia nagrania/transkryptu w M365 organizatora podlega retencji tenanta.
    from app.models.prep_meeting import PrepMeeting, PrepReview, PrepTranscript

    search_erasure["prep_transcripts_deleted"] = (
        await db.execute(
            sa_delete(PrepTranscript).where(PrepTranscript.candidate_id == candidate_id)
        )
    ).rowcount or 0
    await db.execute(
        sa_delete(PrepReview).where(PrepReview.candidate_id == candidate_id)
    )
    await db.execute(
        sa_delete(PrepMeeting).where(PrepMeeting.candidate_id == candidate_id)
    )

    # Audyt PRZED usunięciem, żeby ślad przetrwał operację. `Activity` nie ma
    # FK na kandydata z CASCADE dla tej ścieżki — patrz test kontraktowy.
    # `share_tokens_revoked` jest tu, bo inaczej odwołanie publicznych linków
    # nie zostawiałoby żadnego śladu w dowodzie wykonania żądania z art. 17 —
    # z tego samego powodu liczby wierszy przeglądu bazy.
    candidate_audit.record_candidate_audit(
        db,
        action=candidate_audit.HARD_DELETED,
        user_id=actor_id,
        entity_id=candidate_id,
        details={
            "operation": "hard_delete",
            "contracts_detached": contracts_detached,
            "storage_objects_kept": len(storage_keys),
            "cv_files_retained": cv_files_retained,
            "storage_cleanup": "scheduled",
            "share_tokens_revoked": tokens_revoked,
            "subject_ref": subject_ref,
            **search_erasure,
            **jarvis_erasure,
            **leftovers,
        },
    )
    # Historia zdarzeń (Ustawienia). Wpis przeżywa usunięcie, więc NIE niesie
    # imienia i nazwiska — to byłoby zachowanie danych osoby, którą właśnie
    # usuwamy (art. 17 RODO). Identyfikuje ją pseudonim, ten sam co na
    # odpiętych umowach i w audycie kandydata.
    await record_executed(
        db,
        actor=actor,
        event_type="candidate.delete",
        entity_type="contractor",
        entity_id=candidate_id,
        entity_label=f"Kandydat #{candidate_id}",
        reason=(
            "Profil usunięty trwale (RODO). Dziennik nie przechowuje danych "
            "osobowych — osobę identyfikuje pseudonim na odpiętych umowach."
        ),
        details={
            "subject_ref": subject_ref,
            "contracts_detached": contracts_detached,
            "storage_objects_kept": len(storage_keys),
        },
    )

    # Trwały retry kasowania wektora — ten sam kontrakt, którego używa
    # kwarantanna tożsamości (`candidate_identity_quarantine`). `match_index
    # _outbox` nie ma FK na `candidates`, więc wiersz przeżywa usunięcie i
    # worker dokończy sprzątanie, gdy Qdrant wróci. Bez niego wartość zwracana
    # przez `delete_candidate_embedding` (a ono NIE rzuca — łapie wyjątek u
    # siebie i zwraca False) była porzucana i wektor z nazwiskiem oraz
    # fragmentami CV zostawał w indeksie na zawsze.
    db.add(
        IndexOutboxEvent(
            entity_type="candidate",
            entity_id=candidate_id,
            entity_revision=int(now.timestamp() * 1_000_000),
            desired_hash="",
            operation="delete",
            status="pending",
        )
    )

    # Pliki CV ZOSTAJĄ w magazynie (decyzja Artura 26.09.2026: „nie usuwać
    # nigdy żadnych CV”). Do tego dnia każdy klucz szedł do rejestru kasowań
    # `cv_source_cleanup`; klucze nadal zbieramy wyżej, ale tylko do liczby
    # w dowodzie wykonania.
    # 0399: odpowiedzi na notatki kasujemy PRZED kaskadą ORM — inaczej baza
    # zdejmuje je razem z notatką główną (ON DELETE CASCADE), a ORM próbuje
    # skasować je drugi raz.
    await db.execute(
        sa_delete(Note).where(
            Note.candidate_id == candidate_id, Note.parent_note_id.is_not(None)
        )
    )
    # 0450 (D7): kaskada zabierze wiersze championów — rekrutacje, w których
    # osoba była championem, przeliczamy po commicie usunięcia.
    from app.services import job_champions  # noqa: PLC0415

    champion_job_ids = await job_champions.live_job_ids_for_candidate(db, candidate_id)
    await db.delete(candidate)
    # Flush PRZED commitem: kaskady w bazie wykonują się tutaj, więc ewentualny
    # FK bez `ON DELETE` wywali się czytelnie, a rejestr kasowań wycofa się
    # razem z usunięciem.
    await db.flush()

    return EraseOutcome(
        candidate_id=candidate_id,
        champion_job_ids=tuple(champion_job_ids),
        teams_to_cancel=tuple(teams_to_cancel),
        tokens_revoked=tokens_revoked or 0,
    )


async def finish_after_commit(
    db: AsyncSession, outcome: EraseOutcome, *, actor_id: Optional[int]
) -> None:
    """Championi, odwołanie Teams i wektor — po commicie usunięcia."""

    from app.services import job_champions  # noqa: PLC0415
    from app.services.followup_meetings import cancel_erased_meetings  # noqa: PLC0415

    candidate_id = outcome.candidate_id
    # 0450 (D7): rekrutacje, w których usunięta osoba była championem — bez
    # niej mogą wrócić do szukania. Po commicie, we własnych transakcjach.
    for champion_job_id in outcome.champion_job_ids:
        await job_champions.reconcile_after_commit(
            db,
            job_id=champion_job_id,
            candidate_ids=[outcome.candidate_id],
            actor_id=actor_id,
            had_champions=True,
        )

    if outcome.teams_to_cancel:
        await cancel_erased_meetings(outcome.teams_to_cancel)

    # Natychmiastowa próba kasowania wektora. Nieudana NIE jest błędem żądania —
    # usunięcie w bazie już się stało, a wiersz outboxu wyżej gwarantuje retry.
    from app.services.embedding_service import delete_candidate_embedding

    try:
        deleted = await delete_candidate_embedding(candidate_id)
    except Exception:  # noqa: BLE001 — retry stoi w outboxie
        deleted = False
        logger.exception("Qdrant cleanup raised for deleted candidate %s", candidate_id)
    if not deleted:
        logger.error(
            "[delete_candidate] natychmiastowe kasowanie wektora nieudane; "
            "trwały retry zakolejkowany candidate=%s (odwołanych linków: %s)",
            outcome.candidate_id,
            outcome.tokens_revoked,
        )


__all__ = [
    "CandidateEraseBlocked",
    "EraseOutcome",
    "erase_candidate",
    "finish_after_commit",
]
