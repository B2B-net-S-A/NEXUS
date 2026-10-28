"""DDL „Nowej osoby w NEXUSIE” (0609) — jedno źródło dla migracji i entrypointu.

Decyzja Artura z 28.10.2026: pierwsze logowanie przez Microsoft zakłada konto
„Konsultant/Kontraktor” (``employee``) i nikt się o tym nie dowiadywał. Konto
dostaje znacznik ``users.setup_pending_since``, a Head of Recruitment i admini
— dzwonek i mail ``new_person_signed_in``. Znacznik znika, gdy ktoś zdecyduje
(„Ustaw nową osobę” albo zmiana roli w „Osoby i role”).

Lustro 1:1 w ``entrypoint.sh`` — pilnuje ``test_new_person_setup.py``.
"""

ENUM_DDL = "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'new_person_signed_in'"

COLUMN_DDL = (
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS setup_pending_since TIMESTAMPTZ NULL"
)

# Konta założone przez SSO od 19.10.2026 (od tego dnia rolą startową jest
# „Pracownik”), które dalej mają tylko tę rolę i o których nikt nie
# zdecydował. Idempotentne: decyzja zostawia wpis w `activities`, więc
# kolejny start kontenera nie oznacza konta drugi raz. Bez powiadomień —
# lista w „Czeka na Ciebie” wystarczy.
BACKFILL_SQL = (
    "UPDATE users u SET setup_pending_since = u.created_at "
    "WHERE u.setup_pending_since IS NULL AND u.is_active "
    "AND u.roles = jsonb_build_array('employee') "
    "AND u.created_at >= '2026-10-19' "
    "AND EXISTS (SELECT 1 FROM activities a WHERE a.entity_type = 'user' "
    "AND a.entity_id = u.id AND a.action = 'sso_user_provisioned') "
    "AND NOT EXISTS (SELECT 1 FROM activities a WHERE a.entity_type = 'user' "
    "AND a.entity_id = u.id "
    "AND a.action IN ('role_changed', 'roles_changed', 'new_person_setup_decided'))"
)
