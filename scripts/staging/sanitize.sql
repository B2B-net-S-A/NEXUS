-- Sanitizacja kopii produkcji na stagingu (docs/staging-laptop-plan.md).
--
-- Biegnie w scripts/staging/restore_from_backup.sh zaraz po pg_restore,
-- zanim wystartuje backend. Zapora wyjścia i zatrzymane pętle
-- (backend/app/core/staging.py) i tak nie wypuszczą niczego z laptopa; ten plik
-- usuwa z kopii to, co działałoby jak klucz do prawdziwych systemów, gdyby
-- kopia wyciekła z laptopa albo zapora miała dziurę.
--
-- Nazwy tabel sprawdza backend/tests/test_staging_sanitize_sql.py — tabela
-- przemianowana w migracji zatrzymuje CI, zamiast cicho wypaść z sanitizacji.

\set ON_ERROR_STOP on
BEGIN;

-- Zrzut z pg_dump ustawia pusty search_path (`set_config('search_path', '', …)`),
-- a klon z Hetznera biegnie w tej samej transakcji co restore — bez tego
-- nazwy tabel poniżej nie istnieją.
SET LOCAL search_path = public;

-- Tokeny OAuth skrzynek M365 (szyfrowane kluczem produkcji, ale klucz nie
-- powinien być jedyną zaporą) i kursory delty: staging nie czyta poczty.
UPDATE m365_connections
SET access_token_ct = '',
    refresh_token_ct = '',
    delta_token_messages = NULL,
    delta_token_inbox = NULL,
    delta_token_sent = NULL,
    delta_token_events = NULL,
    is_active = false;

-- Subskrypcje webhooków Graph wskazują na adres produkcji.
DELETE FROM graph_subscriptions;

-- Klucze API kont serwisowych (Compass, integracje) — na stagingu nieważne.
UPDATE service_account_keys
SET revoked_at = COALESCE(revoked_at, now()),
    revoke_reason = COALESCE(revoke_reason, 'staging: kopia produkcji');

-- Jednorazowe linki resetu hasła i weryfikacji adresu z produkcji.
DELETE FROM password_reset_tokens;
DELETE FROM email_verification_tokens;

COMMIT;
