# Dwie listy powodów odrzucenia w Ustawieniach — audyt (20.10.2026)

Tylko odczyt: kod na `origin/main` (c9efa82cd) i zapytania read-only na produkcji
(`SET default_transaction_read_only = on`, wyłącznie liczby i nazwy powodów).
Decyzja co dalej należy do Artura.

## Dwie listy

| | 1. Procesy rekrutacyjne | 2. Listy wyboru → „Powody odrzucenia” |
|---|---|---|
| Ekran | `frontend/src/components/settings/PipelineTemplatesTab.tsx:564` (sekcja „Powody odrzucenia / wycofania” per szablon) | `/settings/dictionaries` (`frontend/src/app/settings/dictionaries/page.tsx`, kafelek `frontend/src/lib/settings-registry.ts:336`) |
| Tabela | `rejection_reasons` (`backend/app/models/pipeline_template.py:169`), FK z `candidate_stages.rejection_reason_id` (`backend/app/models/recruitment_pipeline.py:146`) i `interview_feedback.rejection_reason_id` (`backend/app/models/interview_feedback.py:161`) | `dictionaries` + `dictionary_items` (`backend/app/models/dictionary.py`), zasiane w migracji 0088 (`backend/alembic/versions/0088_dictionaries.py:111`, 7 pozycji) |
| API | `backend/app/api/pipeline_templates.py:612–675` | `backend/app/api/dictionaries.py:39` (odczyt dla formularzy), `:72–175` (admin) |

## Kto czyta listę 1 (szablony procesu)

Każda ścieżka, która zapisuje albo pokazuje powód, idzie przez `rejection_reasons`:

- **Okno odrzucenia (Tablica, ruch karty)** — `frontend/src/hooks/useJobPipelineTemplate.ts:88–99`
  (`pipelineTemplatesApi.get(...).rejection_reasons`), używane w `KanbanBoardV2.tsx:2255`.
- **Ta sama lista w innych oknach** — `frontend/src/lib/rejection-reasons.ts:65–81`
  (`loadJobRejectionReasons`: szablon rekrutacji, awaryjnie szablon domyślny), wołane z
  `JobInterviewsTab.tsx:274`, `DlReviewPanel.tsx:469`, `ScreeningFullForm.tsx:1215`.
- **Zapis ruchu** — `backend/app/api/pipeline.py:1708–1718` sprawdza `rejection_reason_id`
  w `rejection_reasons` (aktywny), wymaga go przy wycofaniu (`:1686`).
- **Weto hiring managera** — `backend/app/api/hiring_manager_feedback.py:255–264`.
- **Statystyki** — Insights „rozbicie etapów” `backend/app/services/insights_stage_breakdown.py:469`;
  aktywność rekrutacji `backend/app/services/recruitment_activity.py:279`;
  „CV w drodze” `backend/app/services/cv_in_transit.py:170`; ryzyko kandydata
  `backend/app/services/candidate_risk.py:153`; historia u klienta w Championie
  `backend/app/services/champion_client_history.py:96–126`.
- **Lista i historia kandydata** — kolumna „Powód odrzucenia” `backend/app/api/candidates.py:3231`,
  historia procesów `:5531`.
- **API integracyjne** — `backend/app/api/integrations_v1/recruitments.py:660`,
  `recruitment_writes.py:598`.
- Etykiety po polsku dla kodów (`counter_offer`, `legacy_unknown`, „Inne (rejected)”) to słownik
  w kodzie `backend/app/services/rejection_reason_labels.py`, nie tabela z Listy wyboru.

**Mail odrzucenia** nie zawiera powodu: `backend/app/services/rejection_email_scheduler.py`
nie odwołuje się ani do `rejection_reasons`, ani do słowników (treść domyślna w kodzie, opis
w nagłówku pliku, linie 22–29). **Eksport kandydatów** (CSV/XLSX, `_EXPORT_COLUMNS`
w `backend/app/api/candidates.py`) nie ma kolumny powodu.

## Kto czyta listę 2 (słownik „Powody odrzucenia”)

Nikt poza samym ekranem Ustawień:

- Backend: modele `Dictionary` / `DictionaryItem` importuje tylko `backend/app/api/dictionaries.py`
  (i rejestr `app/models/__init__.py`). Żadnego zapytania SQL do `dictionary_items` poza tym plikiem.
- Na produkcji jedyny klucz obcy do `dictionary_items`/`dictionaries` to
  `dictionary_items_dictionary_id_fkey` (wewnętrzny) — żadna tabela danych nie wskazuje na pozycję słownika.
- Frontend: `dictionariesApi` (`frontend/src/lib/api.ts:7158`) wołają tylko
  `app/settings/dictionaries/page.tsx:268,275` (lista i szczegóły dla admina).
  `dictionariesApi.itemsBySlug` — odczyt „dla formularzy” — nie ma ani jednego wywołania.
  Słowniki w `lib/api/jobPortals.ts`, `PortalListingForm.tsx` i `app/preview/new-job` to inne
  słowniki (JJIT/RocketJobs, `/api/job-boards/{board}/dictionaries`), z tą tabelą niezwiązane.
- Opis w migracji („używane w raporcie odrzuceń”) nie ma pokrycia w kodzie: raport odrzuceń
  (Insights) czyta `rejection_reasons`.

To samo dotyczy drugiego słownika na tym ekranie, „Branża” (`industry`, 8 pozycji): też bez czytelników.

## Liczby z produkcji (20.10.2026)

Słownik (lista 2): 7 pozycji, wszystkie aktywne, ostatnia zmiana 2026-05-08 (dzień zasiania
migracją; nikt ich nie edytował). Zapisów, które by go używały: **0** — nie ma kolumny, w której
odrzucenie mogłoby wskazać pozycję słownika.

Szablony (lista 1): 28 wierszy `rejection_reasons` w 4 szablonach (24 aktywne).

| Szablon | aktywne powody | użycia w `candidate_stages` |
|---|---|---|
| Default B2B (domyślny) | 18 | 648 |
| B2B | 2 | 333 |
| Proces rekrutacyjny | 2 | 1 |
| ZZZ-claude-reorder-smoke-… | 2 | 0 |

Wiersze etapów terminalnych:

| etap | z powodem z listy 1 | bez powodu, z notatką | bez powodu i notatki |
|---|---|---|---|
| odrzucony | 510 | 28 142 | 2 454 |
| wycofany | 471 (111 z notatką) | 0 | 0 |

Wiersze „bez powodu” to głównie historia z Traffita (lipiec–wrzesień: 6–27 z powodem na
~1 850–2 150 miesięcznie). W październiku, po przejściu na NEXUS: 630 z powodem, 413 bez.
Od 12.10 najczęstsze powody: „Inne” 186, `legacy_unknown` 111 (wycofania z fal przeniesienia
z Traffita), „Brak doświadczenia” 101, „Nie spełnia wymagań technicznych” 74, „Za wysokie
oczekiwania finansowe” 73, „Zatrudniony gdzie indziej” 46; 4 odrzucenia bez powodu.
Weta hiring managera: 11, z powodem 1.

Pokrycie nazw: z 7 pozycji słownika tylko „Kandydat się wycofał” ma imiennika w `rejection_reasons`
(szablon domyślny, 2 użycia) — zbieżność nazwy, bez powiązania w danych.

## Rekomendacja

Słownik „Powody odrzucenia” w Listach wyboru jest martwy: nic go nie czyta, nic na niego nie
wskazuje, a admin, który go edytuje, nie zmienia niczego w oknie odrzucenia. To pułapka, nie
druga funkcja. Jedna lista = Procesy rekrutacyjne.

1. **Ukryć słownik „Powody odrzucenia” z Listy wyboru** (rekomendowane) — bez migracji danych,
   bo żaden zapis go nie używa. Najprościej: filtr slugów na ekranie i w `GET /api/settings/dictionaries`
   albo usunięcie wiersza słownika migracją. Opis kafelka „Branże, powody odrzucenia…”
   (`settings-registry.ts:336`) do poprawy. Skoro „Branża” też nie ma czytelników, można
   rozważyć ukrycie całego kafelka Listy wyboru.
2. **Przepiąć okno odrzucenia na słownik** — niezalecane: słownik nie ma kategorii
   rejected/withdrawn, flagi `disqualifies_person` ani wiązania z szablonem, a na nim stoją
   bramka ruchu, weta HM i Insights. Trzeba by odtworzyć to wszystko w drugiej tabeli i przenieść
   ~980 odwołań.
3. **Zostawić jak jest** — dwa ekrany „Powody odrzucenia”, z których jeden nic nie robi.
