# Rekrutacja v5 — kontrakt między backendem i frontendem (24.09.2026)

Makiety zatwierdzone przez Artura: https://claude.ai/artifact/CG4mBk9xcHZAn3y9jcmMeW
Decyzje Artura (23.09.2026): 8 kolumn; QC CV — AI proponuje poprawki, rekruter
akceptuje; QC twardą bramką przed „CV wysłane”/Cpro, obejście Delivery Lead/admin
z powodem; osobę od Cpro zmienia KAŻDY z zespołu, jedna na firmę (nie per rekrutacja).

## Kolumny Tablicy (klucze)

`new` Nowi · `screening` Screening · `verified` Zweryfikowany · `cv_qc` QC CV ·
`cv_sent` CV wysłane (Nordea: „Wysłane do Cpro”) · `client_interview` Rozmowa u klienta ·
`contract` Umowa · `hired` Zatrudniony · `closed` (pasek zamkniętych).

Wspólne przypadki: `frontend/src/lib/__fixtures__/board-stage-cases.json` (już zaktualizowany).
- Kod etapu `screening` i `prep_call` → kolumna `screening` (już NIE odznaka w Nowych).
- Etap o nazwie DZ („Przepuszczony przez DZ”) albo „QC CV” → kolumna `cv_qc`, BEZ znacznika — to gospodarz kolumny.
- Etap „Wysłać do Cpro” → kolumna `cv_qc`, znacznik `cpro` („w kolejce Cpro”).
- Rodzaj etapu po nazwie w backendzie: `stage_badge_kind` zwraca `"qc"` (zamiast dawnego `"dz"`) dla DZ/QC.
- Migracja 0361 zmienia nazwę etapu „Przepuszczony przez DZ” → „QC CV” w szablonach z `external_source <> 'traffit'` (szablon „Default B2B”). Szablon z Traffita zostaje (nocny sync i tak by go przepisał) — jego etap DZ też trafia do `cv_qc` po nazwie.
- Etap DZ/QC przestaje wymagać roli DL/HoR (każdy, kto może ruszać kartą, przesuwa na QC CV).
- Blokada 12 h i „Rozmowa w Nowych” obejmują kolumny `new` ORAZ `screening`.

## API — nowe / zmienione

### QC CV (backend B1)
`GET /api/pipeline/stages/{stage_id}/qc` — liczy QC dla pary (kandydat, rekrutacja) wiersza etapu, zapisuje przebieg w `cv_qc_runs`. Bramka dostępu jak dawny przegląd DZ, ale dla każdej roli z odczytem rekrutacji (nie tylko DZ).
```json
{
  "stage_id": 1, "candidate_id": 2, "candidate_name": "Anna Kowalczyk",
  "job_id": 3, "job_title": "Senior Java Developer", "client_name": "PKO BP",
  "passed": false, "blocking_failed": 3, "warnings_count": 1,
  "override": null,
  "run_id": 10, "computed_at": "2026-09-24T10:00:00Z",
  "cv": {"source": "branded_draft|branded_finalized|generated|document", "editable": true,
         "stage_id": 1, "generated_document_id": 5, "document_id": null, "filename": null,
         "bold_known": true, "updated_at": "…",
         "blocks": [{"kind": "h|p|li", "section": "role|experience|…|null", "runs": [{"t": "tekst", "b": true}]}]},
  "original_cv": {"source": "snapshot|profile_text|null", "filename": "cv.pdf", "text": "…"},
  "client_request": {"must": ["Java"], "nice": ["Kubernetes"]},
  "checks": [
    {"key": "must_in_cv", "label": "Wszystkie must-have są w CV", "severity": "blocking",
     "status": "pass|fail|manual|skip", "summary": "4/4",
     "items": [{"requirement": "Kafka", "role": "Allegro — Senior Java Dev", "detail": "…", "fix": "bold_all|generate_cv|upload_consent|ask_candidate|remove_term|ai|spelling|null", "term": "Docker"}]}
  ]
}
```
`override` = `{"reason": "…", "by_name": "Piotr Zając", "at": "…"}` gdy DL/admin przepuścił parę mimo QC.
Klucze checków (kolejność): blokujące `must_in_cv`, `must_bolded`, `must_in_roles`, `no_unsupported`,
`years_header`, `dates`, `client_rules`; uwagi `nice_bolded`, `spelling`, `title_matches_role`, `bold_unsupported` (pogrubienia spoza oryginału — uwaga, bo CV EN z oryginału PL pogrubia tłumaczenia).
`status: "manual"` = nie da się policzyć (np. pogrubienia w PDF) — nie blokuje. Bez CV: `must_in_cv` = fail z `fix: "generate_cv"`, `cv: null`.
`passed` = brak blokujących `fail`. 404 bez etapu, 403 bez dostępu.

`POST /api/pipeline/stages/{stage_id}/qc/fixes` — propozycje poprawek (GPT-6 Luna, `AIFeatureKey.dz_review`), pamiętane per skrót wejścia. Nigdy 5xx:
```json
{"status": "ok|unavailable|no_cv|not_editable", "cached": false,
 "fixes": [{"id": "f1", "check_key": "must_in_roles", "requirement": "Java", "role": "ING Tech — Java Developer",
            "current_text": "Rozwijała moduł przelewów SEPA w zespole 8 osób." , "proposed_text": "Rozwijała moduł przelewów SEPA w **Java 11** i **Spring Boot** …",
            "source": "original|notes", "source_quote": "SEPA transfers module (Java 11, Spring Boot)"}]}
```
Poprawka bez cytatu obecnego w oryginale/notatkach jest odrzucana przez serwer.

`POST /api/pipeline/stages/{stage_id}/qc/apply` body jedno z:
`{"action": "ai_fix", "fix_id": "f1", "text": "opcjonalnie edytowany tekst"}` · `{"action": "bold_all", "scope": "must|nice"}` ·
`{"action": "remove_term", "term": "Docker"}` · `{"action": "spelling"}`
→ zmienia szkic CV firmowego pary (podpina gotowe CV z generatora jako szkic, gdy trzeba; zatwierdzone CV wraca do szkicu) i zwraca świeży wynik QC (kształt jak GET).
409 `{"code": "CV_NOT_EDITABLE", "message": "…"}` gdy CV to plik spoza NEXUSA (Word/PDF). 422 dla nieznanej poprawki.

`POST /api/pipeline/stages/{stage_id}/qc/override` body `{"reason": "…"}` (≥ 10 znaków) — tylko admin i Delivery Lead (403 dla reszty). Zapis w historii (`Activity` `cv_qc_override`). Zwraca wynik QC z `override`.

Bramka: `POST /api/pipeline/move` i `/bulk-move` na etap z kolumny `cv_sent` albo na etap Cpro (znacznik `cpro`), gdy para stoi dziś w kolumnie przed `cv_sent`, liczy QC i odmawia:
`409 {"detail": {"code": "CV_QC_FAILED", "message": "CV nie przeszło QC: 3 sprawdzenia do poprawy.", "blocking_failed": 3, "stage_id": <etap do otwarcia QC>}}`
chyba że QC przechodzi albo jest `override`. Wyłącznik `CV_QC_GATE_ENABLED` (domyślnie `true`).

Tablica (`GET` kanbana): każda karta dostaje `qc: {"status": "passed|failed|overridden|unchecked", "blocking_failed": 0}` (najnowszy przebieg pary, jedno zapytanie hurtowe).

### Wymagania przejścia (backend B2)
`GET /api/pipeline/move-requirements?candidate_id=&job_id=&to_stage_def_id=`
```json
{"from_column": "verified", "to_column": "cv_qc", "skipped_columns": [],
 "items": [{"key": "company_cv", "label": "CV firmowe „Pod rekrutację”", "detail": "jeszcze nie wygenerowane",
            "status": "ok|missing|waiting", "blocking": true,
            "action": {"kind": "generate_cv|open_screening|set_candidate_rate|open_qc|set_client_rate|open_debrief|request_slots|null", "label": "Wygeneruj teraz", "stage_id": 1}}],
 "primary": {"kind": "move|hand_to_dl|hand_to_cpro|blocked", "label": "Przesuń na „QC CV”"},
 "owner_note": "CV wysyła Delivery Lead — trafi do jego „Czeka na Ciebie”."}
```
Wymagania per kolumna docelowa (sumowane po pominiętych kolumnach):
- `screening`: brak.
- `verified`: arkusz screeningu (`missing` blokuje, action `open_screening`), stawka kandydata (`missing` blokuje, `set_candidate_rate`), dostępność (nie blokuje).
- `cv_qc`: CV firmowe pary (branded/generated/dokument „B2B”) — `missing` blokuje, action `generate_cv`.
- `cv_sent`: QC przeszło albo override (`missing` blokuje, `open_qc` + `stage_id`); poza Nordeą stawka do klienta — gdy użytkownik nie jest DL/admin: `waiting`, `primary.kind = "hand_to_dl"`; Nordea: `primary.kind = "hand_to_cpro"` z `target_stage_def_id` etapu Cpro w `primary`.
- `client_interview`: termin od klienta (`waiting`, nie blokuje).
- `contract`: debrief (blokuje, `open_debrief`), decyzja klienta (nie blokuje).
- `hired`: podpis obustronny (`waiting`, nie blokuje).

### Cpro — jedna osoba na firmę (backend B2)
`GET /api/board-tasks/cpro/sender` → `{"user_id": 5, "user_name": "Kinga Sordyl", "until": "2026-10-03|null", "fallback_user_id": 4, "fallback_user_name": "…", "set_by_name": "…", "set_at": "…"}` (`user_id` null = nikt).
`PUT /api/board-tasks/cpro/sender` body `{"user_id": 7, "until": "2026-10-03|null"}` — każdy zalogowany z rolą operacyjną; `until` = zastępstwo, po dacie wraca poprzednia osoba. Stan w `app_settings['cpro_sender']`. Powiadamia nową osobę.
`GET /api/board-tasks/cpro/queue` →
```json
{"sender": {…jak wyżej…},
 "jobs": [{"job_id": 1, "job_title": "Java Backend Developer", "client_name": "Nordea", "oldest_since": "…",
           "items": [{"stage_id": 9, "candidate_id": 2, "candidate_name": "…", "since": "…",
                      "process_state_version": 3, "target_stage_def_id": 44, "return_stage_def_id": 41,
                      "client_rate_value": 158.0, "client_rate_unit": "hourly", "client_rate_currency": "PLN",
                      "availability": "2026-11-01|null", "qc_status": "passed|failed|overridden|unchecked",
                      "cv": {"generated_document_id": 5, "document_id": null}}]}],
 "sent_today": 5}
```
„✓ Wrzucone” = zwykłe `POST /api/pipeline/move` na `target_stage_def_id` (etap „CV wysłane” = „Wysłane do Cpro”). Przesuwa osoba od Cpro, admin, DL albo HoR.
„Zwróć do rekrutera” = `POST /api/pipeline/move` na `return_stage_def_id` (etap QC CV) z `notes`.
`jobs.cpro_sender_id` i pasek „Do Cpro wysyła” nad Tablicą — wycofane.

### Znika
Kolejka „Czeka na DZ” (`KIND_DZ`), trasy `GET/POST /api/board-tasks/dz/{stage_id}/review|hints`, okno `DzReviewDialog`, harness `/preview/dz-review`, `CproSenderBar`, odznaka „DZ ✓” i przełącznik DZ w panelu osoby.
Przegląd DL (`dl_review`) = osoby w kolumnie `cv_qc` u klientów innych niż Nordea (z `qc_status`), a nie osoby w „Zweryfikowanym”.
