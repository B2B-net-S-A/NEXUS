SET default_transaction_read_only = on;
-- Wygasłe zgody jednorazowe bez dokumentu — liczby przed przywróceniem
-- (decyzja Artura 23.10.2026, audyt 22.10 F21). Tylko odczyt; same liczby
-- i id zgód — bez nazwisk, tytułów, celów i kwot (repo i logi są publiczne).
--
-- Stan rozliczenia `expired` ustawia wyłącznie `settlement.expire_stale`,
-- który zapisuje w `hr_audit_events` zdarzenie `approval_expired`. Osobnej
-- daty wygaśnięcia (`expired_at`) model nie ma; miesiąc = data zdarzenia
-- w czasie firmy. Ten sam wybór co `app.cli.hr_one_off_expiry_restore`.
--
-- Uruchomienie na serwerze produkcji (plik jest w obrazie backendu):
--   B=$(docker ps --format '{{.Names}}' | grep '^backend-ocgkw' | head -1)
--   PG=$(docker ps --format '{{.Names}}' | grep '^postgres-ocgkw' | head -1)
--   docker exec -i "$B" cat /app/scripts/hr_one_off_expired_report.sql \
--     | docker exec -i "$PG" psql -U nexus -d nexus -v ON_ERROR_STOP=1 -P pager=off

-- 1. Powód stanu `expired` zgody „raz”:
--    wygasla_bez_dokumentu      = do przywrócenia (`restorable` w narzędziu),
--    wygasla_ma_dziś_dokument   = zostaje (dokument dołączony mimo stanu),
--    expired_bez_zdarzenia      = zostaje (stan ustawiony inną drogą).
WITH expired AS (
    SELECT r.id,
           (SELECT max(e.created_at)
              FROM hr_audit_events e
             WHERE e.entity_type = 'approval_request'
               AND e.entity_id = r.id::text
               AND e.action = 'approval_expired') AS expired_at,
           EXISTS (SELECT 1
                     FROM approval_documents d
                    WHERE d.approval_request_id = r.id
                      AND d.status IN ('pinned', 'settled')) AS has_document
      FROM approval_requests r
     WHERE r.status = 'approved'
       AND r.kind <> 'bonus'
       AND r.recurrence = 'once'
       AND r.settlement_status = 'expired'
)
SELECT CASE
           WHEN expired_at IS NULL THEN 'expired_bez_zdarzenia'
           WHEN has_document THEN 'wygasla_ma_dziś_dokument'
           ELSE 'wygasla_bez_dokumentu'
       END AS powod,
       count(*) AS zgody,
       array_agg(id ORDER BY id) AS id_zgod
  FROM expired
 GROUP BY 1
 ORDER BY 1;

-- 2. Do przywrócenia — podział na miesiąc wygaśnięcia (Europe/Warsaw).
WITH expired AS (
    SELECT r.id,
           (SELECT max(e.created_at)
              FROM hr_audit_events e
             WHERE e.entity_type = 'approval_request'
               AND e.entity_id = r.id::text
               AND e.action = 'approval_expired') AS expired_at,
           EXISTS (SELECT 1
                     FROM approval_documents d
                    WHERE d.approval_request_id = r.id
                      AND d.status IN ('pinned', 'settled')) AS has_document
      FROM approval_requests r
     WHERE r.status = 'approved'
       AND r.kind <> 'bonus'
       AND r.recurrence = 'once'
       AND r.settlement_status = 'expired'
)
SELECT to_char(expired_at AT TIME ZONE 'Europe/Warsaw', 'YYYY-MM') AS miesiac_wygasniecia,
       count(*) AS zgody,
       array_agg(id ORDER BY id) AS id_zgod
  FROM expired
 WHERE expired_at IS NOT NULL
   AND NOT has_document
 GROUP BY 1
 ORDER BY 1;

-- 3. Dla porównania: wszystkie zgody `expired` według powtarzania (sama liczba;
--    cykliczne wygasają dalej, F21 ich nie zmienia).
SELECT recurrence, count(*) AS zgody
  FROM approval_requests
 WHERE settlement_status = 'expired'
 GROUP BY recurrence
 ORDER BY recurrence;

-- 4. Czy przywrócenie już było (paragon narzędzia).
SELECT key, value
  FROM app_settings
 WHERE key = 'hr_one_off_expiry_restore_2026_10';
