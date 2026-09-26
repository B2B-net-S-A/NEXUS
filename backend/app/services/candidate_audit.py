"""Minimal immutable audit events for sensitive candidate-module operations.

M2 audit PR 1 (access containment) requires an audit trail for:

- candidate exports (requested/completed),
- CV / document downloads (single, bulk ZIP, presigned URL),
- denied/blocked sensitive operations (anonymize, hard delete),
- bulk operations execute.

Events reuse the existing ``Activity`` audit table (``entity_type`` +
``action`` + JSONB ``details``) instead of introducing a parallel store.
``details`` MUST NOT contain raw PII (names, emails, phones, CV content,
query strings with personal data) — counts, formats, ids and reason codes
only.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.activity import Activity

logger = logging.getLogger(__name__)

# Audit actions (Activity.action) emitted by the candidate module.
EXPORT_REQUESTED = "export_requested"
CV_DOWNLOADED = "cv_downloaded"
BULK_CV_DOWNLOADED = "bulk_cv_downloaded"
DOCUMENT_DOWNLOADED = "document_downloaded"
DOCUMENT_URL_ISSUED = "document_url_issued"
SENSITIVE_OPERATION_BLOCKED = "sensitive_operation_blocked"
# Trwałe usunięcie profilu kandydata (admin). Zapisywane PRZED usunięciem, żeby
# ślad przetrwał samą operację — po `db.delete()` nie ma już czego audytować.
HARD_DELETED = "candidate_hard_deleted"
BULK_ACTION_EXECUTED = "bulk_action_executed"
# Client-facing pricing mutation („stawka do klienta"). Records old→new so a
# rate change leaves a trail (P1-11). Financial payload — must stay out of any
# non-finance-redacted read surface (e.g. the candidate timeline feed).
CLIENT_RATE_CHANGED = "client_rate_changed"
PROFILE_RATE_CHANGED = "profile_rate_changed"
LANGUAGES_REPLACED = "candidate_languages_replaced"
LOCATION_CHANGED = "candidate_location_changed"
WORK_MODE_CHANGED = "candidate_work_mode_changed"
NOTES_FACT_APPLIED = "candidate_notes_fact_applied"
# 0374: telefon praktykanta zapisał fakty w profilu / przekazał osobę rekruterowi.
TRAINEE_CALL_SAVED = "candidate_trainee_call_saved"
TRAINEE_HANDOVER = "candidate_trainee_handover"
# Ręczna korekta faktów z telefonu praktykanta (audyt 24.09.2026): stare → nowe.
CALL_FACTS_CORRECTED = "candidate_call_facts_corrected"
IDENTITY_SOURCE_QUARANTINED = "candidate_identity_source_quarantined"
IDENTITY_SOURCE_QUARANTINE_OVERRIDDEN = (
    "candidate_identity_source_quarantine_overridden"
)
IDENTITY_MANUAL_OWNERSHIP_SET = "candidate_identity_manual_ownership_set"
IDENTITY_RESTORED_FROM_TRAFFIT = "candidate_identity_restored_from_traffit"


def record_candidate_audit(
    db: AsyncSession,
    *,
    action: str,
    user_id: Optional[int],
    entity_id: int = 0,
    details: Optional[dict[str, Any]] = None,
) -> None:
    """Stage an immutable audit event on the current session (no commit).

    ``entity_id=0`` marks module-level events (exports, bulk ops) that do not
    target a single candidate. Caller owns the transaction; endpoints that
    only read (downloads/exports) must ``await db.commit()`` themselves so
    the event survives the request.
    """
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=entity_id,
            action=action,
            user_id=user_id,
            details=details or {},
            external_source="audit",
        )
    )


def candidate_subject_reference(candidate_id: int) -> str:
    """Pseudonimowy klucz podmiotu dla umów odpiętych od usuniętego kandydata.

    Po `ON DELETE SET NULL` (migracja 0225) faktury tej samej osoby przestają
    być ze sobą powiązane, a bez tego księgowość nie uzgodni rozrachunków.
    Ten klucz je łączy, nie przywracając tożsamości.

    Kluczowany HMAC, nie goły hash z `candidate_id`: samo id ma zerową entropię,
    więc niekluczowany digest odwraca się tablicą 10^7 wartości w sekundę.
    Ten sam klucz i wzorzec separacji domeny co
    `candidate_identity_quarantine._fingerprint`.
    """
    key = settings.CANDIDATE_IDENTITY_FINGERPRINT_KEY.strip()
    if not key:
        # Fail-closed jak w quarantine: produkcja przewraca się już na walidacji
        # Settings, ale świadomie DEBUG-owy deployment nie może stemplować umów
        # kluczem domyślnym ani efemerycznym.
        raise RuntimeError(
            "CANDIDATE_IDENTITY_FINGERPRINT_KEY is required to pseudonymise "
            "contracts of a deleted candidate"
        )
    message = f"candidate-subject-v1\x00{candidate_id}".encode("utf-8")
    return hmac.new(key.encode("utf-8"), message, hashlib.sha256).hexdigest()[:64]


def candidate_source_tombstone(external_source: str, external_id: Any) -> str:
    """HMAC identyfikatora kandydata w systemie źródłowym — nagrobek (0388).

    Runda 6 audytu (RODO-01): usunięty kandydat z Traffita wracał nocnym
    syncem, bo importer nie wiedział, że rekord `/employees/{id}` kiedyś
    usunięto. Nagrobek nie może trzymać surowego `external_id` (to wciąż
    identyfikator osoby, której dane usuwamy), więc zapisujemy kluczowany
    HMAC — importer liczy ten sam dla każdego rekordu i porównuje zbiory.
    Ten sam klucz co `candidate_subject_reference`; rotacja klucza gubi
    nagrobki tak samo jak pseudonimy umów.
    """
    key = settings.CANDIDATE_IDENTITY_FINGERPRINT_KEY.strip()
    if not key:
        raise RuntimeError(
            "CANDIDATE_IDENTITY_FINGERPRINT_KEY is required to tombstone "
            "a deleted candidate's source record"
        )
    source = str(external_source or "").strip()
    ext = str(external_id or "").strip()
    message = f"candidate-source-tombstone-v1\x00{source}\x00{ext}".encode("utf-8")
    return hmac.new(key.encode("utf-8"), message, hashlib.sha256).hexdigest()


# `purged_candidates.external_source` dla nagrobka po adresie e-mail — nie
# jest nazwą żadnego systemu źródłowego, więc nie zderzy się z nagrobkiem
# identyfikatora (UNIQUE jest na parze źródło + hash).
EMAIL_TOMBSTONE_SOURCE = "email"


def candidate_email_tombstone(email: Any) -> Optional[str]:
    """HMAC znormalizowanego adresu e-mail usuniętej osoby — nagrobek.

    Runda 7 audytu (R7-V2-2): nagrobek samego `external_id` nie obejmował
    drugiej kartoteki Traffita tej samej osoby (ten sam mail, inny id) —
    import zakładał ją od nowa, bo mail zniknął z bazy razem z wierszem.
    Adres normalizowany tak jak mapa `email_to_id` importera (bez białych
    znaków, małe litery). Pusty adres = brak nagrobka (`None`).
    """
    normalized = str(email or "").strip().lower()
    if not normalized:
        return None
    key = settings.CANDIDATE_IDENTITY_FINGERPRINT_KEY.strip()
    if not key:
        raise RuntimeError(
            "CANDIDATE_IDENTITY_FINGERPRINT_KEY is required to tombstone "
            "a deleted candidate's email"
        )
    message = f"candidate-email-tombstone-v1\x00{normalized}".encode("utf-8")
    return hmac.new(key.encode("utf-8"), message, hashlib.sha256).hexdigest()
