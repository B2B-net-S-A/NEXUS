# Completion report — odrzucenie kandydata działa na jobach bez szablonu pipeline

> Data: 2026-06-05 · Zakres: frontend (Kanban + modal odrzucenia)

## Problem (zgłoszenie)

Na `https://nexus.dynaminds.pl/jobs/9011` w dialogu **„Odrzuć kandydata"** nie
dało się kliknąć **„Potwierdź"** — przycisk był trwale zablokowany. Pole
**„Powód *"** było puste (brak jakichkolwiek opcji radio), więc nie dało się
wybrać powodu, a powód jest wymagany.

## Root cause

- Job 9011 ma `pipeline_template_id = null` (legacy job, import z Traffit —
  działa na enumach legacy, stąd kolumna „Zweryfikowany"/`verified` widoczna na
  boardzie).
- `KanbanBoardV2` ładował powody odrzucenia z szablonu joba i robił
  `if (!tid) return;` — dla joba bez szablonu lista `rejectionReasons` zostawała
  pusta.
- `RejectionV2`: `filtered = reasons.filter(...)` → puste → `RadioGroup` bez
  opcji → `reasonId` nigdy nie był ustawiony → `submitDisabled = !reasonId`
  zawsze `true` → **dead-end**.
- Backend `POST /api/pipeline/move` wymaga `rejection_reason_id` **lub**
  `rejection_reason` (wolny tekst) przy ruchu na etap terminalny (422 inaczej).

Dotyczyło to **wszystkich legacy jobów bez szablonu** (nie tylko 9011), a także
hipotetycznie szablonów utworzonych bez powodów (`POST /pipeline-templates`
startuje z `rejection_reasons = []`).

## Fix

Dwie warstwy (defense-in-depth):

1. **`KanbanBoardV2.tsx` — fallback do szablonu domyślnego.** Gdy job nie ma
   szablonu (lub szablon nie zwraca powodów), dociągamy powody z szablonu
   `is_default` (`pipelineTemplatesApi.list()` → `get(default.id)`). Dzięki temu
   legacy joby dostają standardowy, **kontrolowany słownik** (6 × `rejected`,
   4 × `withdrawn`) — odrzucenia nadal agregują się w raportach lejka.
2. **`RejectionV2.tsx` — siatka bezpieczeństwa: wolny tekst.** Jeśli mimo
   wszystko brak powodów (brak szablonu domyślnego / wszystkie nieaktywne),
   pole „Powód" renderuje `Textarea`. Powód trafia do `notes` (zapisywane +
   widoczne w timeline) i jako `rejection_reason` (przejście walidacji 422).
   `submitDisabled` wymaga wtedy niepustego tekstu zamiast `reasonId`.

Dodatkowo `rejection_reason_id` jest wysyłane jako `undefined` zamiast pustego
stringa (uniknięcie błędu koercji `Optional[int]` w trybie wolnego tekstu).

## Pliki

- `frontend/src/components/v2/pages/KanbanBoardV2.tsx` — fallback powodów +
  przekazanie `freeReason` w `sendMove`.
- `frontend/src/components/v2/modals/RejectionV2.tsx` — tryb wolnego tekstu +
  `submitDisabled`.

## Weryfikacja

- `npm run type-check` ✅ · `npm run lint` ✅ (tylko warningi) · `npm run build` ✅
- UI (Chrome) na `jobs/9011`: dialog odrzucenia pokazuje powody (fallback
  domyślny) i „Potwierdź" jest aktywny po wyborze powodu.

## Znane ograniczenia / follow-up

- Backend nie persystuje wolnego tekstu `rejection_reason` w dedykowanej
  kolumnie — w trybie fallback powód jest zapisywany w `notes` (świadome).
- Warto rozważyć przypisanie szablonu domyślnego do legacy jobów bez szablonu
  (data backfill `jobs.pipeline_template_id`), wtedy fallback FE nie byłby
  potrzebny — out of scope tej zmiany.
