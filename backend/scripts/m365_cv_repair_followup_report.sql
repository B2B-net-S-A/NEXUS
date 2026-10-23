-- Kogo po naprawach #2449 i #2455 dotyczą F114 i F113 (audyt 22.10.2026).
-- TYLKO ODCZYT: same id, flagi i liczby — bez nazwisk, adresów i nazw plików
-- (wynik bywa wklejany do logów i notatek).
--
-- Skrypty `app.cli.m365_document_repair` (paragon m365_document_repair_2026_10)
-- i `app.cli.m365_unreadable_name_rematch` (m365_unreadable_name_rematch_2026_10)
-- poszły na produkcji 20–21.10.2026, zanim czyściły fakty z cudzego CV (F114)
-- i zdejmowały ukrycie ze zwracanego dokumentu (F113). Ich paragony blokują
-- ponowne `--apply`, więc ten raport mówi, czy cokolwiek zostało do poprawy.
-- Zapis (czyszczenie, przywrócenie) dopiero po zgodzie Artura.
--
-- Uruchomienie (klucz i kontener: pamięć nexus-prod-readonly-audit-access):
--   ssh -i ~/.ssh/nexus_prod_root_ed25519 root@91.99.199.112 \
--     "docker exec -i \$(docker ps --format '{{.Names}}' | grep '^postgres-ocgkw' | head -1) \
--      psql -U nexus -d nexus -v ON_ERROR_STOP=1 -P pager=off" \
--     < backend/scripts/m365_cv_repair_followup_report.sql

SET default_transaction_read_only = on;

-- F114 (pewne): profil nadal czytany z dokumentu, który naprawa zabrała tej
-- osobie (`removed_doc_ids` w historii naprawy = cudzy plik zwrócony
-- właścicielowi albo miękko usunięty). Przy #2449 ślad nie odróżnia tekstu
-- z cudzych bajtów od tekstu z własnego załącznika osoby — `has_primary_cv`
-- mówi, czy można ją potem przeczytać na nowo (`--reread`).
WITH repaired AS (
    SELECT a.action, a.entity_id AS candidate_id, d.value::bigint AS doc_id
    FROM activities a
    CROSS JOIN LATERAL jsonb_array_elements_text(
        COALESCE(a.details -> 'removed_doc_ids', '[]'::jsonb)
    ) AS d(value)
    WHERE a.entity_type = 'candidate'
      AND a.action IN ('m365_documents_repaired', 'm365_unreadable_name_rematch')
)
SELECT r.action,
       r.candidate_id,
       r.doc_id,
       c.raw_cv_text IS NOT NULL AS has_cv_text,
       c.ai_summary IS NOT NULL AS has_ai_summary,
       c.embedding_id IS NOT NULL AS has_vector,
       CASE WHEN jsonb_typeof(c.skills) = 'array'
            THEN jsonb_array_length(c.skills) END AS skills,
       EXISTS (
           SELECT 1 FROM candidate_documents p
           WHERE p.candidate_id = c.id
             AND p.document_kind = 'cv'
             AND p.is_primary
             AND p.source_deleted_at IS NULL
       ) AS has_primary_cv
FROM repaired r
JOIN candidates c ON c.id = r.candidate_id
WHERE c.cv_extracted_data -> 'cv_highlights' ->> 'source_document_id' = r.doc_id::text
ORDER BY r.action, r.candidate_id, r.doc_id;

-- F114 (do przejrzenia): osoby z historii obu napraw bez głównego CV, ale
-- z tekstem CV w profilu — profil bez śladu odczytu (sprzed 17.09.2026) nie
-- wpada do zapytania wyżej.
SELECT a.action,
       count(DISTINCT c.id) AS people,
       count(DISTINCT c.id) FILTER (
           WHERE c.cv_extracted_data -> 'cv_highlights' ->> 'source_document_id' IS NULL
       ) AS without_read_trace
FROM activities a
JOIN candidates c ON c.id = a.entity_id
WHERE a.entity_type = 'candidate'
  AND a.action IN ('m365_documents_repaired', 'm365_unreadable_name_rematch')
  AND c.raw_cv_text IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM candidate_documents p
      WHERE p.candidate_id = c.id
        AND p.document_kind = 'cv'
        AND p.is_primary
        AND p.source_deleted_at IS NULL
  )
GROUP BY a.action
ORDER BY a.action;

-- F113: dokument zwrócony właścicielowi, który nadal jest ukryty (usunięty
-- u złego posiadacza albo miękko usunięty synchronizacją), i czy właściciel
-- ma inny widoczny dokument z tym samym plikiem.
SELECT a.entity_id AS owner_id,
       cd.id AS doc_id,
       cd.candidate_id = a.entity_id AS still_with_owner,
       cd.removed_at IS NOT NULL AS removed,
       cd.source_deleted_at IS NOT NULL AS source_deleted,
       cd.removed_by IS NOT NULL AS has_removed_by,
       EXISTS (
           SELECT 1 FROM candidate_documents o
           WHERE o.candidate_id = a.entity_id
             AND o.id <> cd.id
             AND o.content_sha256 = cd.content_sha256
             AND o.source_deleted_at IS NULL
             AND o.removed_at IS NULL
       ) AS owner_has_visible_copy
FROM activities a
CROSS JOIN LATERAL jsonb_array_elements_text(
    COALESCE(a.details -> 'returned_doc_ids', '[]'::jsonb)
) AS d(value)
JOIN candidate_documents cd ON cd.id = d.value::bigint
WHERE a.entity_type = 'candidate'
  AND a.action = 'm365_documents_repaired'
  AND (cd.removed_at IS NOT NULL OR cd.source_deleted_at IS NOT NULL)
ORDER BY a.entity_id, cd.id;

-- F113: powody pominięcia nowej kopii w paragonie naprawy (liczby);
-- „removed” i „key_taken” u właściciela zwróconego pliku to ten błąd.
SELECT key, value -> 'skipped' AS skipped, value -> 'returned' AS returned
FROM app_settings
WHERE key = 'm365_document_repair_2026_10';
