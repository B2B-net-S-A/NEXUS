# CV Generator — lista „Wygenerowane CV" + opcjonalne auto-pobieranie

**Data:** 2026-06-16
**PR:** [#507](https://github.com/artur-t-96/Nexus/pull/507)
**Moduł:** `/cv-generator` (Generator CV B2B)

## Zgłoszenie

Generując kilka CV pod rząd i przeglądając w międzyczasie innych kandydatów, pliki lądują bezimiennie w folderze „Pobrane" — trudno potem dopasować który plik to który kandydat. Prośba: żeby wygenerowane CV zapisywało się w panelu (podgląd / lista) zamiast wymuszonego pobierania. Po dopytaniu Artur wybrał: **dwie opcje** — jak dotychczas (auto-pobieranie) **lub** lista w panelu.

## Rozwiązanie (wzorzec 1:1 jak Generator Umów B2B, PR #501)

### Lista „Wygenerowane CV"
- Server-side, **przetrwa nawigację i odświeżenie** (kluczowe — user przegląda innych kandydatów w trakcie).
- Każdy wpis: kandydat · stanowisko · język · kto wygenerował · kiedy.
- Akcje: **Podgląd** (inline DOCX w aplikacji przez `docx-preview`), **Pobierz**, **Usuń** (autor lub admin).

### Toggle „Pobierz automatycznie po wygenerowaniu"
- W Opcjach, domyślnie **WYŁĄCZONY**, zapamiętywany per przeglądarka (`localStorage`).
- Wyłączony → CV trafia tylko na listę (koniec zaśmiecania Pobranych).
- Włączony → zachowanie jak dotychczas (auto-download do „Pobrane").

### Re-render bez Claude
- Każda generacja (New i Old mode) zapisuje `render_payload` (= `candidate_data`).
- Podgląd/pobranie z listy odtwarza DOCX **deterministycznie z payloadu, bez ponownego (płatnego) wywołania Claude**.

## Pliki

**Backend:**
- `app/models/cv_generated_document.py` — nowy model `CvGeneratedDocument` (`render_payload` JSON+JSONB).
- `alembic/versions/0133_cv_generated_documents.py` — migracja (idempotentne `CREATE TABLE IF NOT EXISTS`, down_revision `0132`).
- `app/services/cv_generator_b2b/standalone_service.py` — `GenerationResult` niesie `render_payload` (deepcopy **przed** mutacją blind przy renderze) + `job_id`; helper `rerender_docx_from_payload`.
- `app/api/cv_generator_b2b.py` — `_persist_generated` (save przy generacji) + endpointy `GET /generated`, `GET /generated/{id}/docx`, `DELETE /generated/{id}`; `X-Generated-Id` w odpowiedzi generacji.
- `app/models/__init__.py` — rejestracja modelu.

**Frontend:**
- `components/v2/pages/CVGeneratorStandaloneV2.tsx` — toggle auto-download, query listy, sekcja „Wygenerowane CV", `GeneratedCvPreviewModal` (inline docx-preview), handlery download/delete.

## Gotchas / decyzje

- **Blind CV:** lista pokazuje **prawdziwe** imię (z `render_payload`, zrzuconego przed anonimizacją) do identyfikacji wewnętrznej; sam DOCX zostaje zanonimizowany przy re-renderze. `result.candidate_name` jest „Kandydat" po renderze, więc do listy bierzemy `render_payload["name"]`.
- **Deepcopy payloadu:** `render_cv_to_bytes` mutuje dict in-place (blind) → zapis robimy z `copy.deepcopy` przed renderem, a re-render też deep-copiuje, żeby zapisany payload był wielokrotnie używalny.
- **Uprawnienia:** lista + pobranie dla każdego zalogowanego (panel zespołowy, jak #501); usunięcie tylko autor/admin.
- **Curly-quote gotcha (FE):** `„...""` w literałach JS — zamykający `"` to ASCII U+0022 i kończy string. W toastach użyto sformułowań bez wewnętrznych cudzysłowów; w treści JSX cudzysłowy są OK (to tekst, nie literał).

## Weryfikacja

- 39 testów BE zielonych (2 nowe: re-render z payloadu produkuje DOCX; blind re-render nie mutuje zapisanego payloadu).
- `ruff format --check` + `ruff check` czyste.
- FE: `tsc --noEmit` + `eslint` + `next build` czyste.
- Migracja walidowana przez CI (`alembic upgrade head` na test DB).
- TODO po deploy: smoke-test UI przez Chrome (generacja → wpis na liście → Podgląd → Pobierz; toggle auto-download).

## Świadomie poza zakresem

- Integracja z zakładką „Pliki" kandydata (Artur wybrał wariant „lista w panelu", nie profil).
- Pojedynczy chip z koniunkcją nie jest tu tematem (to osobny obszar boldowania).
