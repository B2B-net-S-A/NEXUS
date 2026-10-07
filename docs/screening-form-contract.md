# Formularz screeningu — kontrakt API (0424, 07.10.2026)

Jeden formularz na parę (kandydat, rekrutacja) zastępuje arkusz screeningu, ręczne pola karty rekomendacji
i osobne pole stawki. Decyzje Artura D1–D10 z 07.10.2026, makieta: https://claude.ai/artifact/TNGomEmwM6ehsbdPDSaaBi.
Wszystko w formularzu jest dla Delivery Leada — nic z niego nie idzie do klienta.

Sekcja Pipeline. Trasy w `backend/app/api/screening_form.py`, logika w `backend/app/services/screening_form.py`
(baza) i `backend/app/services/screening_form_rules.py` (czyste funkcje). Front: `frontend/src/lib/api/screeningForm.ts`,
klucz react-query `["screening-form", jobId, candidateId]` (funkcja `screeningFormQueryKey(jobId, candidateId)`).

## Typy wspólne

```ts
type RateUnit = "hourly" | "daily" | "monthly";

interface FormRate {            // stawka kandydata w tej rekrutacji
  amount: number;               // > 0
  unit: RateUnit;
  currency: string;             // 3 litery, domyślnie "PLN"
}

type ReadOnlyReason =
  | "job_closed"                // Job.status == "closed"
  | "process_closed"            // proces pary zamknięty (zatrudnienie, odrzucenie, rezygnacja, rezerwa)
  | "process_voided"            // proces unieważniony (usunięty z rekrutacji)
  | "no_stage";                 // para nie ma żadnego wiersza etapu

interface VersionChange {
  section: "answers" | "terms" | "assessment" | "rate";
  key: string;                  // "q3", "availability", "overall_fit", "rate", "experience:<kind>:<name>"…
  label: string;                // po polsku: „Pytanie 3”, „Dostępność”, „Stawka kandydata”…
  before: string | null;        // wartość tekstowa do pokazania
  after: string | null;
}
```

## GET /api/screening-form?candidate_id=&job_id=

Bramka odczytu jak karta: `CandidatePIIAccess`/`OperationalUser` + `ensure_job_read_access`. 404 dla nieistniejącej pary.

```ts
interface ScreeningFormState {
  candidate_id: number;
  job_id: number;
  version: number;              // najwyższy version_no pary; 0 = brak wersji
  versions_count: number;
  editable: boolean;            // false przy read_only_reason albo braku prawa zapisu
  read_only_reason: ReadOnlyReason | null;
  read_only_message: string | null;   // zdanie po polsku do pokazania
  stage_id: number | null;      // NAJNOWSZY wiersz etapu pary (tam idzie zapis)
  board_column: string | null;  // new|screening|verified|cv_qc|cv_sent|client_interview|contract|hired|closed
  process_state_version: number;      // do StageMove.expected_state_version
  claim: { user_id: number; user_name: string | null; until: string; mine: boolean } | null;

  // Pytania i arkusz — ten sam kształt co GET /api/pipeline/stages/{id}/screening
  champion_profile: Record<string, unknown>;    // champion_view.api_response(job.champion_profile)
  sheet: ScreeningAnswers | null;               // najnowszy wypełniony arkusz pary z bieżącej próby (z question_text)
  sheet_source_stage_id: number | null;
  legacy_notes: string | null;                  // sheet.notes, gdy niepuste („Notatka z arkusza”, tylko do odczytu)
  note_answers: Array<{ question_id: string; number: number; question: string; answer: string }>;
                                                // odpowiedzi odczytane z notatek-kart dla pytań bez odpowiedzi w arkuszu (podpowiedź „Użyj”)

  // Pola karty rekomendacji (bez stawki — stawka jest w `rate`)
  card: {
    fields: Record<string, RecommendationCardField>;   // wartość efektywna (ręczna wygrywa z notatką), jak CardResponse.fields
    previous: Record<string, RecommendationCardField>; // z poprzedniej próby — podpowiedź
    suggestions: Record<string, string>;
    completeness: { status: "complete" | "partial" | "empty"; filled: number; total: number; missing: string[] };
    labels: Record<string, string>;                    // DISPLAY_LABELS
    editable_fields: string[];                         // EDITABLE_FIELDS bez "rate"
  };

  rate: (FormRate & { source: "stage" | "card"; at: string | null }) | null;  // bieżąca stawka kandydata pary
  rate_hints: {
    card: FormRate | null;          // stawka z karty (PLN/h odczytane bez zgadywania)
    rate_from: FormRate | null;     // „Stawka od” kandydata (minimum z 18 mies.)
  };
  rate_change_notifies: boolean;    // kolumna pary ∈ NOTIFY_COLUMNS → zmiana stawki otworzy sprawę u DL
  can_edit_rate: boolean;           // user_can_edit_rates
  suggestions_from_notes: Record<string, unknown>;   // kształt screening_suggestions.suggestions_from_notes
  assist_enabled: boolean;          // RECOMMENDATION_CARD_ASSIST_ENABLED
  phrase_language: "pl" | "en";
}
```

## PUT /api/screening-form

Bramka zapisu: `CandidateWriteAccess` + `ensure_job_membership` + `assert_pair_editable` + `candidate_claim.assert_can_act`.

```ts
interface ScreeningFormSave {
  candidate_id: number;
  job_id: number;
  expected_version: number;        // ScreeningFormState.version z chwili otwarcia
  sheet: {
    answers: Array<{
      question_id: string;
      response: string;
      deal_breaker_hit: boolean;
      origin: "manual" | "reassign_suggested" | "note_import" | "phrased";
      keywords?: string | null;
      skipped?: boolean;
    }>;
    experience_checks: ExperienceCheck[];
    overall_fit: "fit" | "uncertain" | "miss";
    internal_note?: string | null;  // tylko przy przepięciu
    clear_legacy_notes?: boolean;   // true = wyczyść sheet.notes (po „Przenieś do Dlaczego ten kandydat”)
  } | null;                         // null = arkusz bez zmian
  card: {
    fields: Record<string, string | null>;   // tylko klucze z editable_fields; null zdejmuje pole ręczne; "rate" → 422
    origins?: Record<string, { origin: "note_ai" | "note_rule" | "phrased"; keywords?: string | null }>;
  } | null;
  rate: FormRate | null;            // null = stawka bez zmian
  note_import: { text: string; source_name?: string | null } | null;   // tekst notatki użytej do wypełnienia
}

interface ScreeningFormSaveResult extends ScreeningFormState {
  saved_version: number | null;     // null = nic się nie zmieniło, wersji nie dodano
  undo_to_version: number | null;   // wersja sprzed tego zapisu (dla „Cofnij”); null, gdy nie ma do czego wrócić
  changed: string[];                // etykiety zmienionych pól
  note_id: number | null;           // notatka z note_import
  cache_invalidated: boolean;
}
```

Zasady serwera:
- Arkusz zapisuje się na NAJNOWSZY wiersz etapu pary (blokada `FOR UPDATE`); `notes` przepisane z poprzedniego arkusza,
  chyba że `clear_legacy_notes`; `humanize_origins` przed `stamp_sheet`. Pusty arkusz (bez żadnej treści) nie jest
  zapisywany — nie może spełnić bramki „Zweryfikowany”.
- Pole karty zapisuje się tylko, gdy różni się od wartości efektywnej (pole z notatki nie staje się „ręczne” bez zmiany).
- Stawka przez `candidate_rate_change.change_rate(source="screening", reason="conversation")`; pole karty `rate`
  dostaje tekst tej stawki („150 zł/h”). Przed „Zweryfikowany” bez powiadomień, od „Zweryfikowany” jak każda zmiana
  stawki w procesie (0418). Maile po commicie.
- `note_import` → `Note(kind=HUMAN)` z nagłówkiem „Notatka z rozmowy (plik: X)”, `note_id` w pochodzeniu pól.
- Wersja zapisu powstaje tylko przy realnej zmianie stanu. Przed pierwszą wersją, gdy para ma już treść, serwer
  zapisuje wersję `baseline`; gdy stan różni się od ostatniej wersji (zapis starą trasą albo automat), wersję `external`.

Błędy:
- 409 `{code: "SCREENING_FORM_READ_ONLY", reason: ReadOnlyReason, message}`
- 409 `{code: "SCREENING_FORM_VERSION_CONFLICT", current_version, saved_by_name, saved_at, message}`
- 423 blokada 12 h (dotychczasowy kształt `CANDIDATE_CLAIMED`)
- 422 `{code: "SCREENING_FORM_INVALID", message}` — nieznane pytanie/pole, `rate` w `card.fields`, `phrased` poza polami
  opisowymi, `note_ai`/`note_rule` bez `note_import`, kwota ≤ 0
- 403 zmiana stawki bez `user_can_edit_rates`

## GET /api/screening-form/versions?candidate_id=&job_id=

```ts
interface ScreeningFormVersion {
  version_no: number;
  action: "baseline" | "external" | "save" | "restore" | "undo" | "fix_requested";
  source: "form" | "note_import";
  created_at: string;
  created_by: number | null;
  created_by_name: string | null;
  restored_from_version: number | null;
  note_id: number | null;
  changes: VersionChange[];
}
// odpowiedź: { items: ScreeningFormVersion[] (od najnowszej), total: number }
```

## POST /api/screening-form/restore

```ts
interface ScreeningFormRestore {
  candidate_id: number;
  job_id: number;
  version_no: number;
  expected_version: number;
  mode: "restore" | "undo";     // undo = cofnięcie ostatniego zapisu (stawka z reason="typo")
}
// odpowiedź: ScreeningFormSaveResult & { rate_not_restored: boolean; skipped_answers: string[] }
```
- Przywrócenie to NOWA wersja (`restore`/`undo`, `restored_from_version`); nic nie znika z historii.
- Stawka wraca tylko poza `NOTIFY_COLUMNS` (inaczej `rate_not_restored: true` — zmianą od „Zweryfikowany” zarządza DL).
- Odpowiedź na pytanie, którego treść w Profilu Championa się zmieniła, jest pomijana (`skipped_answers`).

## Udostępnianie karty Championa (D2)

- `POST /api/pipeline/stages/{id}/share-token` → 410 `{code: "CHAMPION_SHARE_REMOVED", message}`; `DELETE` zostaje.
- Publiczny `GET` karty → 410 bez odczytu bazy; strona `/share/champion-card/[token]` pokazuje „link nieważny”.
- Migracja 0424 odwołuje wszystkie tokeny.
