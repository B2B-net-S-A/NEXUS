# „Szukaj w CV” przy wymaganiu szuka słów, nie etykiety — raport (16.10.2026)

Zgłoszenie Artura: „opcja znajdź w CV nie działa, nie wyszukuje stacku pomimo,
że jest w CV” (zrzut: krytyczne „.NET lub C#”, „OWASP Top 10”). Makiety
i warianty: https://claude.ai/artifact/GPiTEmysE6a4EPnXgVWFoc — decyzja Artura:
„wariant 1: słowa z serwera dla każdego wymagania, lupa szuka listy, linia
„Szukam: …”, jeden PR z auto-merge”. Reguła:
`docs/claude/kandydaci-wyszukiwanie/podglad-cv-pdf-js-lupa-szukaj-w-cv.md`,
sekcja z 16.10.2026.

## Co było nie tak (odtworzone przed zmianą)

- `CandidatePreviewPane.pickRequirement` wkładał do lupy całą etykietę wymagania,
  a `PdfDocumentViewer.dispatchFind` szukał jej jako jednej frazy. Etykieta
  „.NET lub C#” to zapis grupy alternatyw (`requirement_contract.requirement_label`
  skleja `any_of` przez „ lub ”) — takiego zdania nie ma w żadnym CV.
- Harness `/preview/cv-search`: „.NET lub C#” → „Brak wyników”, „C#” w tym samym
  pliku → „1 z 2”. DOCX (`findMatchOffsets`) tak samo: 0 trafień dla etykiety,
  2 dla „.NET”, 1 dla „C#”.
- To samo dla „Java 17” (w CV „Java”), „Docker/Kubernetes” i nawiasów
  („SQL (bardzo dobra znajomość)”).

## Co weszło

| Część | Zmiana | Pliki |
|---|---|---|
| Serwer | `requirement_find_words(label)` — opcje i warianty nazw jak `requirement_search_words` (bramka, „Szukaj ręcznie”), opcja jednoliterowa tylko odpada („C lub C++” → „C++”) | `backend/app/services/keyword_suggest.py` |
| Serwer | `requirement_find_words` w odpowiedzi profilu Championa: etykieta → słowa dla każdego „Musi mieć” i „Mile widziane” (z profilu i z kolumn rekrutacji); krytyczna z wyboru DL dostaje słowa wiersza (`match_must_labels`, rdzeń bez gwiazdki) | `backend/app/services/champion_intake.py` |
| Lupa | `DocumentQuery` = fraza albo lista; pdf.js dostaje tablicę, DOCX podświetla alternatywę (dłuższe słowo wygrywa) | `lib/document-text-search.ts`, `PdfDocumentViewer.tsx` |
| Lupa | Zlecenie z `terms`: pole pokazuje nazwę wymagania, lupa szuka słów; ręczna zmiana pola = fraza. Wynik „w toku” do pierwszej odpowiedzi pdf.js (bez mignięcia „nie ma w CV”) | `FilePreviewModal.tsx`, `SearchablePdfPreview.tsx` |
| Ekran | Linia „Szukam: …” / „Szukałem: … — tej nazwy nie ma w CV” pod paskiem (PDF i DOCX) | `DocumentSearchBar.tsx` (`DocumentSearchTerms`) |
| Ekran | Lista „Wymagania” i pasek nad CV podają `(nazwa, słowa)`; słowa z odpowiedzi serwera | `JobRequirementsSummary.tsx`, `JobRequirementsStrip.tsx`, `use-job-requirements.ts`, `CandidatePreviewPane.tsx`, `lib/api.ts` |

Do tego: wpis inwentarza `preview.requirement-cv-search-words`, harness
`/preview/screening-form` ze słowami, jakie policzyłby serwer. Bez migracji.
Cytat z edytora CV („Pokaż w oryginale”) dalej szuka frazy.

## Weryfikacja

- Backend bez bazy (Python 3.12): `test_keyword_suggest.py`,
  `test_critical_skills.py`, `test_champion_intake_v4.py` — 69 zielonych, w tym
  2 nowe (najpierw czerwone). 6 testów endpointu podpowiedzi wymaga Postgresa —
  sprawdza je CI. `ruff check` i `ruff format --check` czyste.
- Vitest: 8 plików (lupa, PDF, wymagania, pasek, podglądy, panel, warsztat
  screeningu) — 110 zielonych; 5 nowych testów najpierw czerwonych.
  Inwentarz 366, harnessy 77. `tsc --noEmit`, eslint zmienionych plików — czysto.
- `check_stamps.py` — przewodniki Jarvisa bez rozjazdu. Indeks CLAUDE.md bez zmian.
- Przeglądarka, harness `/preview/screening-form`, 1280×720:
  - chip „Java 17” nad CV → pole „Java 17”, „1 z 1”, „Szukam: Java”, podświetlone „Java”;
  - „Kafka” z zakładki „Wymagania” → „Brak wyników”, „Szukałem: Kafka — tej nazwy
    nie ma w CV…” w jednej linii;
  - ręcznie „Selenium” → „2 z 2”, linii nie ma;
  - plik Word w „Inne pliki” → ta sama linia nad DOCX.

## Czego ta zmiana nie załatwi

Wymaganie, którego słownik nie zna w innej pisowni („Unit Tests” vs „unit
testing”, „OWASP Top 10” vs „OWASP”, „OAuth2” vs „OAuth 2.0”), dalej szuka tylko
swojej nazwy — lupa mówi to wprost. Naprawa: alias w Ustawienia → Słownik
umiejętności (admin, Head of Recruitment); po zapisie słowo trafia do lupy od razu.
Warianty nazw w makietach liczyłem na słowniku z repozytorium — produkcyjnego
nie odczytałem.

## Po wdrożeniu (okno 19:00–07:00)

1. `/api/health` → `version` = SHA z maina z tym PR-em.
2. Panel osoby w rekrutacji z wymaganiem „… lub …” → „Szukaj w CV” → linia
   „Szukam:” ze słowami i podświetlenia w CV.
